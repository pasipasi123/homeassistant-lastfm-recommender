"""Small rate-limited API clients. Never include request URLs or credentials in errors."""
import base64
import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ServiceError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def request_json(url, *, data=None, headers=None, stop=None):
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
                if code not in (11, 16, 29):
                    safe_code = code if isinstance(code, (int, str)) else "unknown"
                    raise ServiceError(f"API rejected request (code {safe_code}); check app credentials and permissions", code=code)
            else:
                return payload
        except HTTPError as error:
            if error.code != 429 and error.code < 500:
                raise ServiceError(f"API HTTP {error.code}; check credentials, permissions and API access") from None
            if error.code == 429:
                # A long quota cooldown is left for the next scheduled run.
                try:
                    retry_after = int(error.headers.get("Retry-After", delay))
                except ValueError:
                    retry_after = delay
                if retry_after > 120:
                    raise ServiceError("API quota exceeded; retry on a later sync") from None
                delay = max(delay, retry_after)
        except (URLError, TimeoutError, OSError, ValueError):
            pass
        if attempt < 3 and stop.wait(delay):
            raise ServiceError("Request cancelled")
    raise ServiceError("API unavailable after bounded retries; retry on a later sync")


class LastFM:
    def __init__(self, settings, stop):
        self.settings, self.stop = settings, stop

    def call(self, method, **params):
        # At most two requests/second from the single background worker.
        if self.stop.wait(0.5):
            raise ServiceError("Request cancelled")
        return request_json("https://ws.audioscrobbler.com/2.0/?" + urlencode({
            "method": method, "api_key": self.settings.lastfm_api_key,
            "format": "json", **params}), stop=self.stop)

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
        tags = result.get("tags", {}).get("tag", [])
        if isinstance(tags, dict):
            tags = [tags]
        images = [img["#text"] for img in result.get("image", []) if img.get("#text")]
        return [tag["name"] for tag in tags], images[-1] if images else None


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
                                  stop=self.stop)
            self.token = result["access_token"]
            self.expires = time.monotonic() + int(result["expires_in"]) - 60
        if self.stop.wait(0.5):
            raise ServiceError("Request cancelled")
        result = request_json("https://api.spotify.com/v1/search?" + urlencode({
            "q": f'artist:{album["artist"]} album:{album["album"]}', "type": "album", "limit": 1}),
            headers={"Authorization": "Bearer " + self.token}, stop=self.stop)
        items = result.get("albums", {}).get("items", [])
        if not items:
            return None
        item = items[0]
        return {"uri": item["uri"], "name": item["name"],
                "artists": [a["name"] for a in item.get("artists", [])],
                "image_url": item["images"][0]["url"] if item.get("images") else None,
                "confidence": "unverified"}
