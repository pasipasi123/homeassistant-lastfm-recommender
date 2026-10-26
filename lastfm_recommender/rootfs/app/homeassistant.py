"""Restricted HA Core client through Supervisor; never exposes the Supervisor token."""
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from database import normalized, spotify_uri


class HomeAssistantError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class HomeAssistant:
    def __init__(self, token="", base_url="http://supervisor/core/api", *, volume_step=0.01):
        if isinstance(volume_step, bool) or not isinstance(volume_step, (int, float)) or not 0 < volume_step <= 1:
            raise ValueError("Normalized volume step must be greater than 0 and at most 1")
        self._token = token
        self._base = base_url.rstrip("/")
        self._volume_step = volume_step

    @property
    def available(self):
        return bool(self._token)

    def _request(self, path, data=None):
        if not self.available:
            raise HomeAssistantError("Home Assistant access is unavailable. Open this app on Home Assistant OS.")
        request = Request(self._base + path,
                          data=json.dumps(data).encode() if data is not None else None,
                          headers={"Authorization": "Bearer " + self._token,
                                   "Content-Type": "application/json"})
        # Never retry a playback/control POST: a timeout does not prove it failed.
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code in (401, 403):
                raise HomeAssistantError("Home Assistant denied access. Update/restart the app to apply its Core API permission.", error.code) from None
            raise HomeAssistantError(f"Home Assistant returned HTTP {error.code}. Check the selected SpotifyPlus player and HA logs.", error.code) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise HomeAssistantError("Home Assistant did not respond. Check the connection before retrying playback.") from None

    def players(self):
        # integration_entities finds SpotifyPlus players even when users rename
        # the entity so its ID no longer contains the word 'spotifyplus'.
        ids = self._request("/template", {"template": "{{ integration_entities('spotifyplus') | list | to_json }}"})
        if not isinstance(ids, list):
            raise HomeAssistantError("Could not list SpotifyPlus entities from Home Assistant.")
        result = []
        for entity_id in ids:
            if not isinstance(entity_id, str) or not re.fullmatch(r"media_player\.[a-z0-9_]+", entity_id):
                continue
            try:
                state = self._request("/states/" + quote(entity_id, safe=""))
            except HomeAssistantError as error:
                if error.status == 404:
                    # Disabled registry members may not have a live state.
                    continue
                raise
            attributes = state.get("attributes", {})
            result.append({"entity_id": entity_id, "name": attributes.get("friendly_name", entity_id),
                           "state": state.get("state"), "source": attributes.get("source"),
                           "title": attributes.get("media_title"), "artist": attributes.get("media_artist"),
                           "volume_level": attributes.get("volume_level"),
                           "devices": sorted({name for name in (attributes.get("source_list") or [])
                                              if isinstance(name, str) and name.strip() and name not in ("*", "ACTIVE")})})
        return sorted(result, key=lambda player: str(player["name"]).casefold())

    def validate_player(self, entity_id):
        player = next((player for player in self.players() if player["entity_id"] == entity_id), None)
        if player is None:
            raise HomeAssistantError("Select an available SpotifyPlus player first.")
        if player["state"] == "unavailable":
            raise HomeAssistantError("The selected SpotifyPlus player is unavailable in Home Assistant.")
        return player

    def validate_device(self, player, device_id):
        if not isinstance(device_id, str) or not device_id or device_id not in player.get("devices", []):
            raise HomeAssistantError("The selected Spotify Connect device is unavailable. Refresh devices or choose another device.")

    def saved_albums(self, entity_id, offset=0):
        """Read one bounded page; discard the service's user profile and track data."""
        response = self._request("/services/spotifyplus/get_album_favorites?return_response",
                                 {"entity_id": entity_id, "limit": 50, "offset": offset, "sort_result": False})
        data = response.get("service_response", {}).get("result", {}) if isinstance(response, dict) else {}
        return self._album_page(data, offset, 50, wrapped=True)

    def artist_id_for_album(self, entity_id, album_uri, artist_name):
        album_id = spotify_uri(album_uri).split(":")[-1]
        response = self._request("/services/spotifyplus/get_album?return_response",
                                 {"entity_id": entity_id, "album_id": album_id})
        album = response.get("service_response", {}).get("result", {})
        matches = {a["id"] for a in album.get("artists", []) if isinstance(a, dict)
                   and isinstance(a.get("name"), str) and normalized(a["name"]) == normalized(artist_name)
                   and isinstance(a.get("id"), str) and re.fullmatch(r"[A-Za-z0-9]{22}", a["id"])}
        return next(iter(matches)) if len(matches) == 1 else None

    def artist_albums(self, entity_id, artist_id, market, offset=0):
        if not re.fullmatch(r"[A-Za-z0-9]{22}", artist_id):
            raise ValueError("Invalid artist ID")
        response = self._request("/services/spotifyplus/get_artist_albums?return_response",
                                 {"entity_id": entity_id, "artist_id": artist_id, "market": market,
                                  "include_groups": "album,single,compilation", "limit": 10,
                                  "offset": offset, "sort_result": False})
        return self._album_page(response.get("service_response", {}).get("result", {}), offset, 10, wrapped=False)

    @staticmethod
    def _album_page(data, offset, limit, *, wrapped):
        items, total = data.get("items"), data.get("total")
        if (not isinstance(items, list) or len(items) > limit or isinstance(total, bool) or
                not isinstance(total, int) or total < 0 or data.get("offset") != offset):
            raise HomeAssistantError("SpotifyPlus returned an invalid album page. Lookup stopped safely.")
        albums = []
        for item in items:
            album = item.get("album") if wrapped and isinstance(item, dict) else item
            if not isinstance(album, dict):
                raise HomeAssistantError("SpotifyPlus returned an incomplete album. Lookup stopped safely.")
            try:
                uri = spotify_uri(album.get("uri", ""))
                name = album["name"]
                artists = [artist["name"] for artist in album["artists"]]
                if not isinstance(name, str) or not name.strip() or not artists or any(not isinstance(a, str) or not a.strip() for a in artists):
                    raise ValueError
            except (ValueError, TypeError, KeyError, AttributeError):
                raise HomeAssistantError("SpotifyPlus returned invalid album identifiers. Lookup stopped safely.") from None
            albums.append({"uri": uri, "name": name, "artists": artists, "release_date": album.get("release_date", ""),
                           "total_tracks": album.get("total_tracks"), "restricted": bool(album.get("restrictions")),
                           "exact": True})
        return {"albums": albums, "total": total, "has_more": bool(data.get("next")), "count": len(items)}

    def play(self, entity_id, uri, device_id=None):
        player = self.validate_player(entity_id)
        self.validate_device(player, device_id)
        self._request("/services/spotifyplus/player_media_play_context",
                      {"entity_id": entity_id, "context_uri": uri, "device_id": device_id})

    def control(self, entity_id, action, volume=None, device_id=None):
        services = {"pause": "media_pause", "resume": "media_play", "next": "media_next_track",
                    "volume": "volume_set", "volume_up": "volume_set", "volume_down": "volume_set"}
        if action not in services:
            raise ValueError("Unsupported player control")
        player = self.validate_player(entity_id)
        if device_id is not None:
            self.validate_device(player, device_id)
            if player.get("source") != device_id:
                raise HomeAssistantError("Spotify is active on another device. Play an album on the selected device first.")
        data = {"entity_id": entity_id}
        if action in ("volume_up", "volume_down"):
            current = player.get("volume_level")
            if (isinstance(current, bool) or not isinstance(current, (int, float)) or
                    not math.isfinite(current) or not 0 <= current <= 1):
                raise HomeAssistantError("Current volume is unavailable. Refresh the player before adjusting volume.")
            volume = round(max(0, min(1, current + (self._volume_step if action == "volume_up" else -self._volume_step))), 8)
        if action in ("volume", "volume_up", "volume_down"):
            if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 1:
                raise ValueError("Volume must be between 0 and 1")
            data["volume_level"] = volume
        if device_id is not None:
            targeted = {"pause": "player_media_pause", "resume": "player_media_resume", "next": "player_media_skip_next",
                        "volume": "player_set_volume_level", "volume_up": "player_set_volume_level", "volume_down": "player_set_volume_level"}
            data["device_id"] = device_id
            if "volume_level" in data:
                # Spotify's volume_percent query parameter must be an integer.
                # A float such as 31.0 survives SpotifyPlus validation and is
                # forwarded as "31.0", which Spotify rejects with HTTP 400.
                data["volume_level"] = int(data["volume_level"] * 100 + 0.5)
            self._request("/services/spotifyplus/" + targeted[action], data)
        else:
            self._request("/services/media_player/" + services[action], data)
