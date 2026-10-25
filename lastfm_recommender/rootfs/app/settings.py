"""Read Supervisor options without exposing credentials in logs."""
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    lastfm_username: str
    lastfm_api_key: str
    api_token: str = ""
    timezone: str = "Europe/Helsinki"
    sync_interval_minutes: int = 360
    enrich_batch_size: int = 10
    enrich_interval_minutes: int = 5
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_market: str = "FI"
    volume_min: float = 0.0
    volume_max: float = 100.0
    volume_step: float = 1.0
    volume_decimals: int = 1

    @property
    def volume_options(self):
        return {"min": self.volume_min, "max": self.volume_max,
                "step": self.volume_step, "decimals": self.volume_decimals}

    @classmethod
    def read(cls, path):
        options = json.loads(Path(path).read_text(encoding="utf-8"))
        settings = cls(**{key: value for key, value in options.items()
                          if key in cls.__dataclass_fields__})
        if not settings.lastfm_username.strip() or not settings.lastfm_api_key.strip():
            raise ValueError("Set lastfm_username and lastfm_api_key in app options")
        if settings.api_token and len(settings.api_token) < 32:
            raise ValueError("Leave api_token empty for ingress-only access, or use at least 32 characters")
        ZoneInfo(settings.timezone)
        if not 5 <= settings.sync_interval_minutes <= 1440:
            raise ValueError("sync_interval_minutes must be between 5 and 1440")
        if not 0 <= settings.enrich_batch_size <= 100:
            raise ValueError("enrich_batch_size must be between 0 and 100")
        if not 1 <= settings.enrich_interval_minutes <= 1440:
            raise ValueError("enrich_interval_minutes must be between 1 and 1440")
        if bool(settings.spotify_client_id) != bool(settings.spotify_client_secret):
            raise ValueError("Set both Spotify credentials, or leave both empty")
        if not re.fullmatch(r"[A-Z]{2}", settings.spotify_market):
            raise ValueError("spotify_market must be a two-letter uppercase country code")
        values = (settings.volume_min, settings.volume_max, settings.volume_step)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError("Volume bounds and step must be finite numbers")
        if not -200 <= settings.volume_min < settings.volume_max <= 200:
            raise ValueError("Volume min/max must be increasing values between -200 and 200")
        if not 0.01 <= settings.volume_step <= settings.volume_max - settings.volume_min:
            raise ValueError("Volume step must be at least 0.01 and no greater than the display range")
        if (isinstance(settings.volume_decimals, bool) or not isinstance(settings.volume_decimals, int) or
                not 0 <= settings.volume_decimals <= 2):
            raise ValueError("volume_decimals must be 0, 1 or 2")
        if not math.isclose(round(settings.volume_step, settings.volume_decimals), settings.volume_step):
            raise ValueError("volume_decimals must be precise enough to display volume_step")
        return settings
