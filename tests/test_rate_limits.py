"""Respect Spotify quota deadlines across enrichment cycles and restarts."""
import threading
from email.utils import formatdate
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from test_app import DatabaseCase, track
from clients import ServiceError, request_json, retry_after_seconds
from settings import Settings
from worker import Worker


class RetryAfterTests(DatabaseCase):
    def test_retry_after_seconds_dates_and_missing_headers(self):
        now = 1800000000
        with patch("clients.time.time", return_value=now):
            self.assertEqual(retry_after_seconds("86400"), 86400)
            self.assertEqual(retry_after_seconds("5"), 5)
            self.assertEqual(retry_after_seconds("0"), 1)
            self.assertEqual(retry_after_seconds(formatdate(now + 3600, usegmt=True)), 3600)
            self.assertEqual(retry_after_seconds(formatdate(now - 3600, usegmt=True)), 1)
            for value in (None, "", "invalid", "-1", "nan"):
                self.assertEqual(retry_after_seconds(value), 900)

    def test_http_429_stops_after_one_request_without_waiting_or_leaking_credentials(self):
        for header, expected in (("86400", 86400), ("5", 5), (None, 900)):
            stop = Mock(spec=threading.Event)
            stop.is_set.return_value = False
            headers = {"Retry-After": header} if header is not None else {}
            with self.subTest(header=header), patch("clients.urlopen", side_effect=HTTPError(
                    "https://example.com/private-secret", 429, "private-secret", headers, None)) as request:
                with self.assertRaises(ServiceError) as caught:
                    request_json("https://example.com/private-secret", stop=stop)
                self.assertEqual(caught.exception.code, 429)
                self.assertEqual(caught.exception.retry_after, expected)
                self.assertNotIn("private-secret", str(caught.exception))
                self.assertEqual(request.call_count, 1)
                stop.wait.assert_not_called()


class SpotifyCooldownTests(DatabaseCase):
    def worker(self, spotify, lastfm=None):
        lastfm = lastfm or Mock()
        lastfm.album.return_value = (["folk"], None)
        return Worker(self.db, Settings("user", "key", spotify_client_id="client",
                      spotify_client_secret="secret"), threading.Event(), lastfm=lastfm, spotify=spotify)

    def test_cooldown_survives_restart_and_manual_cycles_without_blocking_lastfm(self):
        self.add([track()])
        spotify = Mock()
        spotify.search_album.side_effect = ServiceError("Spotify quota exceeded", code=429, retry_after=3600)
        now = 1800000000
        with patch("worker.time.time", return_value=now):
            worker = self.worker(spotify)
            with self.assertLogs("worker", level="WARNING"):
                worker.enrich()
            deadline = self.db.get_state("spotify_retry_at")
            self.assertGreaterEqual(deadline, now + 3600)
            self.assertEqual(self.db.status()["spotify_retry_at"], deadline)
            self.assertEqual(self.db.get_state("spotify_error"), "Spotify quota exceeded")
            self.assertEqual(len(self.db.spotify_queue(10, "FI")), 1)
        self.add([track(artist="Other", album="Other")])
        restarted = self.worker(spotify)
        restarted.pending = False
        self.assertTrue(restarted.request_enrichment())
        for seconds in (300, 600, 1800, 3599):
            with patch("worker.time.time", return_value=now + seconds), patch("worker.LOG.warning") as log:
                restarted.enrich()
                restarted.enrich_spotify()  # The direct helper cannot bypass the deadline either.
                log.assert_not_called()
        self.assertEqual(spotify.search_album.call_count, 1)
        self.assertEqual(self.db.albums(query="Other")[0]["tags"], ["folk"])
        self.assertEqual(self.db.get_state("spotify_error"), "Spotify quota exceeded")
        spotify.search_album.side_effect = None
        spotify.search_album.return_value = None
        with patch("worker.time.time", return_value=deadline + 1):
            restarted.enrich()
        self.assertEqual(spotify.search_album.call_count, 3)
        self.assertIsNone(self.db.get_state("spotify_retry_at"))
        self.assertIsNone(self.db.get_state("spotify_error"))

    def test_second_quota_response_sets_a_new_deadline(self):
        self.add([track()])
        spotify = Mock()
        spotify.search_album.side_effect = [ServiceError("quota", code=429, retry_after=5),
                                           ServiceError("quota", code=429, retry_after=7200)]
        worker = self.worker(spotify)
        with patch("worker.time.time", return_value=1800000000), patch("worker.LOG.warning"):
            worker.enrich()
        with patch("worker.time.time", return_value=1800000010), patch("worker.LOG.warning"):
            worker.enrich()
        self.assertGreaterEqual(self.db.get_state("spotify_retry_at"), 1800007210)
