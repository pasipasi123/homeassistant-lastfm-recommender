"""Rejected albums must not starve the queue or erase previous matches."""
import io
import json
import threading
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from test_app import DatabaseCase, track, URI
from clients import LastFM, Spotify, ServiceError, request_json
from database import Database
from settings import Settings
from worker import Worker


def http_error(status, payload):
    return HTTPError("https://example.com/?api_key=private-secret", status, "private-secret", {},
                     io.BytesIO(json.dumps(payload).encode()))


class LookupErrorTests(DatabaseCase):
    def settings(self, **kwargs):
        return Settings("user", "private-secret", spotify_client_id="client-id",
                        spotify_client_secret="client-secret", **kwargs)

    def worker(self, lastfm=None, spotify=None, **kwargs):
        return Worker(self.db, self.settings(**kwargs), threading.Event(), lastfm=lastfm, spotify=spotify)

    def test_http_lastfm_error_code_is_preserved_without_echoed_credentials(self):
        with patch("clients.urlopen", side_effect=http_error(404, {"error": 6, "message": "private-secret"})):
            with self.assertRaises(ServiceError) as caught:
                request_json("https://example.com/?api_key=private-secret", operation="Last.fm album.getInfo")
        self.assertEqual((caught.exception.status, caught.exception.code), (404, 6))
        self.assertIn("Last.fm album.getInfo", str(caught.exception))
        self.assertNotIn("private-secret", str(caught.exception))

    def test_lastfm_missing_album_does_not_stop_next_album(self):
        self.add([track(album="First"), track(album="Second")])
        lastfm = Mock()
        lastfm.album.side_effect = [ServiceError("not found", code=6, status=404), (["folk"], None)]
        worker = self.worker(lastfm=lastfm)
        worker.enrich(metadata=True, spotify=False)
        self.assertEqual(lastfm.album.call_count, 2)
        self.assertEqual(self.db.status()["metadata_checked"], 2)
        self.assertEqual(self.db.status()["tagged_albums"], 1)
        self.assertIsNone(self.db.get_state("enrichment_error"))

    def test_lastfm_http_404_without_code_is_deferred_not_cached_as_absent(self):
        self.add([track(album="First"), track(album="Second")])
        lastfm = Mock()
        lastfm.album.side_effect = [ServiceError("Last.fm album.getInfo: HTTP 404", status=404,
                                               operation="Last.fm album.getInfo"), (["folk"], None)]
        worker = self.worker(lastfm=lastfm)
        with self.assertLogs("worker", level="WARNING"):
            worker.enrich(metadata=True, spotify=False)
        self.assertEqual(self.db.status()["metadata_checked"], 1)
        restarted = Database(self.db.path)
        self.assertEqual(restarted.enrichment_queue(10), [])
        with patch("database.time.time", return_value=2000000000):
            self.assertEqual(len(restarted.enrichment_queue(10)), 2)

    def test_spotify_search_400_is_deferred_and_next_album_is_checked(self):
        self.add([track(album="First"), track(album="Second")])
        stop = Mock(spec=threading.Event)
        stop.wait.return_value = stop.is_set.return_value = False
        client = Spotify(self.settings(), stop)
        client.token, client.expires = "private-token", float("inf")
        first_id = self.db.spotify_queue(10, "FI")[0]["id"]
        with patch("clients.urlopen", side_effect=[
                http_error(400, {"error": {"status": 400, "message": "Invalid query private-secret"}}),
                io.BytesIO(b'{"albums":{"items":[],"next":null}}')]) as request:
            with self.assertLogs("worker", level="WARNING") as logs:
                self.worker(spotify=client).enrich(metadata=False, spotify=True)
        self.assertEqual(request.call_count, 2)
        self.assertIn('"album": "First"', " ".join(logs.output))
        self.assertNotIn("private-secret", " ".join(logs.output))
        self.assertIsNone(self.db.album(first_id)["spotify_checked_at"])
        restarted = Database(self.db.path)
        self.assertEqual(restarted.spotify_queue(10, "FI"), [])
        self.assertIn(first_id, [a["id"] for a in restarted.spotify_queue(10, "SE")])

    def test_auth_token_400_pauses_source_without_deferring_album(self):
        self.add([track()])
        error = http_error(400, {"error": "invalid_client", "error_description": "client-secret"})
        with patch("clients.urlopen", side_effect=error) as request, self.assertLogs("worker", level="WARNING") as logs:
            self.worker().enrich(metadata=False, spotify=True)
        self.assertEqual(request.call_count, 1)
        self.assertIn("Spotify token", " ".join(logs.output))
        self.assertNotIn("client-secret", " ".join(logs.output))
        self.assertEqual(len(self.db.spotify_queue(10, "FI")), 1)
        self.assertIsNotNone(self.db.get_state("spotify_retry_at"))

    def test_three_consecutive_rejections_stop_batch_and_preserve_candidates(self):
        self.add([track(album=f"Album {n}") for n in range(5)])
        album_id = self.db.spotify_queue(10, "FI")[0]["id"]
        candidate = {"uri": URI, "confidence": "unverified", "alternatives": []}
        self.db.save_spotify_match(album_id, candidate, "FI")
        with self.db.connect() as conn:
            conn.execute("UPDATE albums SET spotify_checked_at=NULL WHERE id=?", (album_id,))
        spotify = Mock()
        spotify.search_album.side_effect = ServiceError("Spotify album search: HTTP 400", status=400,
                                                      operation="Spotify album search")
        with patch("worker.time.time", return_value=1800000000), self.assertLogs("worker", level="WARNING"):
            self.worker(spotify=spotify).enrich(metadata=False, spotify=True)
        self.assertEqual(spotify.search_album.call_count, 3)
        self.assertGreaterEqual(self.db.get_state("spotify_retry_at"), 1800003600)
        self.assertEqual(json.loads(self.db.album(album_id)["spotify_candidate"]), candidate)

    def test_defer_does_not_replace_manual_confirmation_or_metadata(self):
        self.add([track()])
        album_id = self.db.albums()[0]["id"]
        self.db.confirm_album(album_id, URI, ["folk"])
        self.db.defer_album_lookup(album_id, "spotify:FI")
        self.db.defer_album_lookup(album_id, "lastfm")
        self.assertEqual(self.db.album(album_id)["spotify_uri"], URI)
        self.assertEqual(self.db.album(album_id)["tags"], ["folk"])

    def test_http_auth_code_on_album_method_is_not_treated_as_missing(self):
        self.add([track()])
        lastfm = Mock()
        lastfm.album.side_effect = ServiceError("invalid key", code=10, status=404, operation="Last.fm album.getInfo")
        with self.assertLogs("worker", level="WARNING"):
            self.worker(lastfm=lastfm).enrich(metadata=True, spotify=False)
        self.assertEqual(len(self.db.enrichment_queue(10)), 1)
        self.assertEqual(self.db.status()["metadata_checked"], 0)
