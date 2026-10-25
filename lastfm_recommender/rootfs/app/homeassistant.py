"""Restricted HA Core client through Supervisor; never exposes the Supervisor token."""
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


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
                           "volume_level": attributes.get("volume_level")})
        return sorted(result, key=lambda player: str(player["name"]).casefold())

    def validate_player(self, entity_id):
        player = next((player for player in self.players() if player["entity_id"] == entity_id), None)
        if player is None:
            raise HomeAssistantError("Select an available SpotifyPlus player first.")
        if player["state"] == "unavailable":
            raise HomeAssistantError("The selected SpotifyPlus player is unavailable in Home Assistant.")
        return player

    def play(self, entity_id, uri):
        self.validate_player(entity_id)
        self._request("/services/spotifyplus/player_media_play_context",
                      {"entity_id": entity_id, "context_uri": uri})

    def control(self, entity_id, action, volume=None):
        services = {"pause": "media_pause", "resume": "media_play", "next": "media_next_track",
                    "volume": "volume_set", "volume_up": "volume_set", "volume_down": "volume_set"}
        if action not in services:
            raise ValueError("Unsupported player control")
        player = self.validate_player(entity_id)
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
        self._request("/services/media_player/" + services[action], data)
