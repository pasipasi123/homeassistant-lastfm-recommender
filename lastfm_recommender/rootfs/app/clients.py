"""Small rate-limited API clients. Never include request URLs or credentials in errors."""
import base64
import json
import math
import threading
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from database import matching_artist, normalized, spotify_uri


class ServiceError(Exception):
    def __init__(self, message, code=None, retry_after=None, *, status=None, operation=None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
        self.status = status
        self.operation = operation


def rejected_request(payload, operation, status=None):
    """Keep useful error categories, never provider text that may echo secrets."""
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error if type(error) is int else None
    reason = "request rejected"
    if isinstance(error, str) and error in (
            "invalid_client", "invalid_grant", "invalid_request", "unsupported_grant_type"):
        code, reason = error, error.replace("_", " ")
    elif isinstance(error, dict):
        if status is None and type(error.get("status")) is int:
            status = error["status"]
        message = str(error.get("message", "")).lower()
        for needle, label in (("query", "search query rejected"), ("market", "market rejected"),
                              ("limit", "limit rejected"), ("offset", "offset rejected")):
            if needle in message:
                reason = label
                break
    detail = f"HTTP {status}" if status is not None else "API rejected request"
    if code is not None:
        detail += f" (code {code})"
    if code == 29:
        return ServiceError(f"{operation}: request limit reached; album details paused temporarily",
                            code=29, retry_after=900, status=status, operation=operation)
    return ServiceError(f"{operation}: {detail}; {reason}", code=code, status=status, operation=operation)


def retry_after_seconds(value):
    """Honor delta seconds or HTTP dates; use a conservative fallback if missing."""
    try:
        seconds = int(value)
        if seconds < 0:
            raise ValueError
        return max(1, seconds)
    except (ValueError, TypeError, OverflowError):
        try:
            until = parsedate_to_datetime(value)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            return max(1, math.ceil(until.timestamp() - time.time()))
        except (ValueError, TypeError, OverflowError, AttributeError):
            return 15 * 60


def request_json(url, *, data=None, headers=None, stop=None, operation="API request"):
    stop = stop or threading.Event()
    for attempt in range(4):
        if stop.is_set():
            raise ServiceError("Request cancelled")
        delay = min(2 ** attempt, 30)
        try:
            request = Request(url, data=data, headers={"User-Agent": "LastfmRecommender/0.1",
                                                      **(headers or {})})
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
            if "error" in payload:
                code = payload["error"]
                if code == 29:
                    raise ServiceError("Last.fm request limit reached; album details paused temporarily", code=29, retry_after=900)
                if code not in (11, 16, 29):
                    raise rejected_request(payload, operation)
            else:
                return payload
        except HTTPError as error:
            if error.code != 429 and error.code < 500:
                try:
                    payload = json.loads(error.read(8192))
                except (ValueError, OSError, TypeError, AttributeError):
                    payload = None
                finally:
                    error.close()
                raise rejected_request(payload, operation, error.code) from None
            if error.code == 429:
                # Let the worker persist the deadline instead of blocking or
                # retrying early on its next five-minute enrichment cycle.
                retry_after = retry_after_seconds((error.headers or {}).get("Retry-After"))
                error.close()
                raise ServiceError(f"API quota exceeded; album requests paused for {retry_after} seconds",
                                   code=429, retry_after=retry_after, status=429, operation=operation) from None
            error.close()
        except (URLError, TimeoutError, OSError, ValueError):
            pass
        if attempt < 3 and stop.wait(delay):
            raise ServiceError("Request cancelled")
    raise ServiceError(f"{operation}: unavailable after bounded retries; retry on a later sync", operation=operation)


class LastFM:
    def __init__(self, settings, stop):
        self.settings, self.stop = settings, stop

    def call(self, method, **params):
        # At most two requests/second from the single background worker.
        if self.stop.wait(0.5):
            raise ServiceError("Request cancelled")
        return request_json("https://ws.audioscrobbler.com/2.0/?" + urlencode({
            "method": method, "api_key": self.settings.lastfm_api_key,
            "format": "json", **params}), stop=self.stop, operation=f"Last.fm {method}")

    def recent(self, job):
        payload = self.call("user.getRecentTracks", user=self.settings.lastfm_username,
                            limit=200, page=job["page"], to=job["upper"],
                            **{"from": job["lower"]})
        recent = payload["recenttracks"]
        raw = recent.get("track", [])
        if isinstance(raw, dict):
            raw = [raw]
        tracks = []
        for row in raw:
            if row.get("@attr", {}).get("nowplaying") == "true" or not row.get("date"):
                continue
            tracks.append({"timestamp": int(row["date"]["uts"]),
                           "artist": row["artist"]["#text"],
                           "album": row.get("album", {}).get("#text", ""),
                           "track": row["name"], "track_mbid": row.get("mbid", ""),
                           "album_mbid": row.get("album", {}).get("mbid", "")})
        return tracks, max(1, int(recent["@attr"].get("totalPages", 0)))

    def album(self, album):
        result = self.call("album.getInfo", artist=album["artist"], album=album["album"])["album"]
        if not isinstance(result, dict):
            raise ServiceError("Last.fm returned invalid album metadata; retry on a later update")
        # Last.fm uses empty strings or null instead of objects for some albums.
        raw_tags = result.get("tags")
        tags = raw_tags.get("tag", []) if isinstance(raw_tags, dict) else []
        if isinstance(tags, dict):
            tags = [tags]
        if not isinstance(tags, list):
            tags = []
        raw_images = result.get("image")
        if isinstance(raw_images, dict):
            raw_images = [raw_images]
        images = [img["#text"] for img in (raw_images if isinstance(raw_images, list) else [])
                  if isinstance(img, dict) and isinstance(img.get("#text"), str) and img["#text"].strip()]
        return [tag["name"] for tag in tags if isinstance(tag, dict) and
                isinstance(tag.get("name"), str) and tag["name"].strip()], images[-1] if images else None


class Spotify:
    def __init__(self, settings, stop):
        self.settings, self.stop = settings, stop
        self.token = None
        self.expires = 0

    def search_album(self, album):
        if not self.settings.spotify_client_id:
            return None
        if time.monotonic() >= self.expires:
            auth = base64.b64encode((self.settings.spotify_client_id + ":" +
                                     self.settings.spotify_client_secret).encode()).decode()
            result = request_json("https://accounts.spotify.com/api/token",
                                  data=b"grant_type=client_credentials",
                                  headers={"Authorization": "Basic " + auth,
                                           "Content-Type": "application/x-www-form-urlencoded"},
                                  stop=self.stop, operation="Spotify token")
            self.token = result["access_token"]
            self.expires = time.monotonic() + int(result["expires_in"]) - 60
        if self.stop.wait(0.5):
            raise ServiceError("Request cancelled")
        # Keep edition suffixes and punctuation: stripping them can match a live,
        # remastered or deluxe release to the wrong listening-history album.
        query = f'artist:{album["artist"]} album:{album["album"]}'
        candidates, seen, complete = [], set(), False
        for offset in range(0, 30, 10):
            if offset and self.stop.wait(0.5):
                raise ServiceError("Request cancelled")
            result = request_json("https://api.spotify.com/v1/search?" + urlencode({
                "q": query, "type": "album", "limit": 10, "offset": offset,
                "market": self.settings.spotify_market}),
                headers={"Authorization": "Bearer " + self.token}, stop=self.stop, operation="Spotify album search")
            page = result.get("albums", {})
            for item in page.get("items", []):
                try:
                    uri = spotify_uri(item.get("uri", ""))
                except ValueError:
                    continue
                if uri in seen:
                    continue
                seen.add(uri)
                artists = [a["name"] for a in item.get("artists", [])]
                if not matching_artist(artists, album["artist"]):
                    continue
                exact = (normalized(item["name"]) == normalized(album["album"]) and
                         [normalized(a) for a in artists] == [normalized(album["artist"])])
                candidates.append({"uri": uri, "name": item["name"], "artists": artists,
                    "image_url": item["images"][0]["url"] if item.get("images") else None,
                    "release_date": item.get("release_date", ""),
                    "total_tracks": item.get("total_tracks"), "exact": exact,
                    "restricted": bool(item.get("restrictions"))})
            if not page.get("next"):
                complete = True
                break
        if not candidates:
            return None
        candidates.sort(key=lambda item: not item["exact"])
        exact = [item for item in candidates if item["exact"]]
        automatic = complete and len(exact) == 1 and not exact[0]["restricted"]
        return {**candidates[0], "alternatives": candidates, "complete": complete,
                "confidence": "exact_unique" if automatic else "unverified"}
