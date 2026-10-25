"""Configurable volume display scales and fine adjustment."""
import json
from pathlib import Path
from unittest.mock import patch

from test_app import DatabaseCase, PLAYER
from homeassistant import HomeAssistant
from settings import Settings


class VolumeConfigurationTests(DatabaseCase):
    def read(self, **options):
        path = Path(self.folder.name) / "options.json"
        path.write_text(json.dumps({"lastfm_username": "user", "lastfm_api_key": "test-key", **options}), encoding="utf-8")
        return Settings.read(path)

    def test_existing_installs_keep_absolute_display_defaults(self):
        self.assertEqual(self.read().volume_options, {"min": 0, "max": 100, "step": 1, "decimals": 1})

    def test_custom_scale_and_step_are_used_by_backend(self):
        settings = self.read(volume_min=-80, volume_max=20, volume_step=0.5, volume_decimals=1)
        client = HomeAssistant("test-token", volume_step=settings.volume_step / (settings.volume_max - settings.volume_min))
        with patch.object(client, "validate_player", return_value={"volume_level": 0.32}), \
             patch.object(client, "_request") as request:
            client.control(PLAYER, "volume_up")
        request.assert_called_once_with("/services/media_player/volume_set", {"entity_id": PLAYER, "volume_level": 0.325})

    def test_invalid_or_invisible_steps_are_rejected(self):
        for options in ({"volume_min": 100}, {"volume_max": 0}, {"volume_step": 0},
                        {"volume_step": 101}, {"volume_step": float("nan")}, {"volume_min": True},
                        {"volume_max": float("inf")}, {"volume_min": -201},
                        {"volume_decimals": 3}, {"volume_decimals": True},
                        {"volume_decimals": 0, "volume_step": 0.5}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.read(**options)
