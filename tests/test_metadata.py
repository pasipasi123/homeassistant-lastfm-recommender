"""Independent Last.fm metadata scheduling, progress and retry behavior."""
import io
import json
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from test_app import DatabaseCase, track
from clients import ServiceError, request_json
from settings import Settings
from worker import Worker


class MetadataTests(DatabaseCase):
    def test_batch_sizes_and_manual_queues_are_independent(self):
        self.add([track(album=f"Album {n}") for n in range(5)])
        lastfm, spotify = Mock(), Mock()
        lastfm.album.return_value = ([], None)
        settings = Settings("u", "key", lastfm_batch_size=3, enrich_batch_size=0)
        worker = Worker(self.db, settings, threading.Event(), lastfm=lastfm, spotify=spotify)
        worker.pending = False
        self.assertTrue(worker.request_metadata())
        self.assertFalse(worker.request_metadata())
        self.assertFalse(worker.request_enrichment())
        worker.enrich(metadata=True, spotify=False)
        self.assertEqual(lastfm.album.call_count, 3)
        spotify.search_album.assert_not_called()
        status = self.db.status()
        self.assertEqual(status["metadata_checked"], 3)
        self.assertEqual(status["tagged_albums"], 0)
        worker.enrich(metadata=True, spotify=False)
        self.assertEqual(lastfm.album.call_count, 5)

    def test_spotify_only_batch_does_not_request_tags(self):
        self.add([track()])
        lastfm, spotify = Mock(), Mock()
        spotify.search_album.return_value = None
        worker = Worker(self.db, Settings("u", "key", spotify_client_id="client", spotify_client_secret="secret"),
                        threading.Event(), lastfm=lastfm, spotify=spotify)
        worker.enrich(metadata=False, spotify=True)
        lastfm.album.assert_not_called()
        spotify.search_album.assert_called_once()

    def test_lastfm_cooldown_persists_and_does_not_block_spotify(self):
        self.add([track()])
        lastfm, spotify = Mock(), Mock()
        lastfm.album.side_effect = ServiceError("Last.fm quota", code=29, retry_after=1800)
        spotify.search_album.return_value = None
        settings = Settings("u", "key", spotify_client_id="client", spotify_client_secret="secret")
        worker = Worker(self.db, settings, threading.Event(), lastfm=lastfm, spotify=spotify)
        with patch("worker.time.time", return_value=1800000000), patch("worker.LOG.warning"):
            worker.enrich()
        deadline = self.db.get_state("lastfm_retry_at")
        self.assertGreaterEqual(deadline, 1800001800)
        spotify.search_album.assert_called_once()
        restarted = Worker(self.db, settings, threading.Event(), lastfm=lastfm, spotify=spotify)
        restarted.pending = False
        with patch("worker.time.time", return_value=1800000300), patch("worker.LOG.warning") as log:
            self.assertFalse(restarted.request_metadata())
            restarted.enrich(metadata=True, spotify=False)
            log.assert_not_called()
        self.assertEqual(lastfm.album.call_count, 1)
        lastfm.album.side_effect = None
        lastfm.album.return_value = (["folk"], None)
        with patch("worker.time.time", return_value=deadline + 1):
            restarted.enrich(metadata=True, spotify=False)
        self.assertIsNone(self.db.get_state("lastfm_retry_at"))
        self.assertEqual(self.db.status()["metadata_checked"], 1)
        self.assertEqual(self.db.status()["tagged_albums"], 1)

    def test_lastfm_json_quota_is_not_immediately_retried(self):
        stop = Mock(spec=threading.Event)
        stop.is_set.return_value = False
        with patch("clients.urlopen", return_value=io.BytesIO(b'{"error":29,"message":"quota"}')) as request:
            with self.assertRaises(ServiceError) as caught:
                request_json("https://example.com", stop=stop)
        self.assertEqual(caught.exception.retry_after, 900)
        self.assertEqual(request.call_count, 1)
        stop.wait.assert_not_called()

    def test_missing_new_options_get_independent_defaults_and_invalid_values_fail(self):
        path = Path(self.folder.name) / "options.json"
        base = {"lastfm_username": "u", "lastfm_api_key": "key", "enrich_batch_size": 0}
        path.write_text(json.dumps(base), encoding="utf-8")
        settings = Settings.read(path)
        self.assertEqual((settings.lastfm_batch_size, settings.lastfm_interval_minutes), (50, 1))
        for name, value in (("lastfm_batch_size", -1), ("lastfm_batch_size", 101),
                            ("lastfm_batch_size", True), ("lastfm_interval_minutes", 0),
                            ("lastfm_interval_minutes", 1.5)):
            path.write_text(json.dumps({**base, name: value}), encoding="utf-8")
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                Settings.read(path)
