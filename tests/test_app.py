"""Offline behavioral tests for history preservation and the HA API contract."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lastfm_recommender/rootfs/app"))
from api import make_server
from clients import LastFM, ServiceError
from database import Database, calendar_cutoff, spotify_uri
from settings import Settings
from worker import Worker

URI = "spotify:album:0S2DmRfqWM51FUprHs0qil"
TOKEN = "test-token-" + "x" * 32


def track(timestamp=1435705200, artist="Sufjan Stevens", album="Illinois", name="Chicago"):
    return {"timestamp": timestamp, "artist": artist, "album": album, "track": name}


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "history.db")

    def add(self, tracks):
        job = self.db.begin_import(2000000000)
        self.db.save_page(tracks, job, 1)
        self.db.finish_import(job["upper"])

class StorageTests(DatabaseCase):
    def test_duplicates_across_pages_resume_and_overlapping_runs(self):
        event = track()
        job = self.db.begin_import(2000000000)
        next_job = self.db.save_page([event, event], job, 2)
        resumed = Database(self.db.path).begin_import(2100000000)
        self.assertEqual(resumed, next_job)
        self.db.save_page([event], resumed, 2)
        self.db.finish_import(job["upper"])
        self.assertEqual(self.db.status()["scrobbles"], 3)
        job = self.db.begin_import(2100000000)
        next_job = self.db.save_page([event], job, 2)
        self.db.save_page([event, event, event], next_job, 2)
        self.db.finish_import(job["upper"])
        self.assertEqual(self.db.status()["scrobbles"], 4)
        self.assertEqual(self.db.albums()[0]["scrobbles_total"], 4)

    def test_page_and_checkpoint_rollback_together(self):
        job = self.db.begin_import(2000000000)
        with self.assertRaises(TypeError):
            self.db.save_page([track(), track(artist=None)], job, 2)
        self.assertEqual(self.db.status()["scrobbles"], 0)
        self.assertEqual(self.db.get_state("import")["page"], 1)

    def test_missing_album_preserved_but_not_recommended(self):
        self.add([track(album=""), track(album=" ")])
        self.assertEqual(self.db.status()["scrobbles"], 2)
        self.assertEqual(self.db.status()["albums"], 0)
        self.assertIsNone(self.db.recommend(0, 1, playable_only=False))

    def test_confirmed_only_and_exact_tags_and_sql_input(self):
        self.add([track(), track(artist="Other", album="Other")])
        self.assertIsNone(self.db.recommend(0, 1))
        album = self.db.albums(query="Illinois")[0]
        self.db.confirm_album(album["id"], URI, ["Indie Folk", "indie folk"])
        result = self.db.recommend(0, 1, genre="INDIE FOLK")
        self.assertEqual(result["id"], album["id"])
        self.assertEqual(result["tags"], ["indie folk"])
        self.assertIsNone(self.db.recommend(0, 1, genre="folk"))
        self.assertIsNone(self.db.recommend(0, 1, genre="' OR 1=1 --"))
        self.assertEqual(self.db.albums(query="%"), [])
        self.assertEqual(self.db.albums(query="ILLINOIS")[0]["album"], "Illinois")

    def test_timezone_dst_and_timezone_change(self):
        # Helsinki skips from 02:59 to 04:00 at 01:00 UTC.
        before = int(datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc).timestamp())
        after = before + 3600
        self.add([track(before), track(after)])
        with self.db.connect() as conn:
            self.assertEqual([r[0] for r in conn.execute("SELECT hour FROM scrobbles ORDER BY timestamp")], [2, 4])
        utc_db = Database(self.db.path, "UTC")
        with utc_db.connect() as conn:
            self.assertEqual([r[0] for r in conn.execute("SELECT hour FROM scrobbles ORDER BY timestamp")], [0, 1])
        self.assertEqual(utc_db.status()["timezone"], "UTC")

    def test_backup_restores_counts_and_confirmed_mapping(self):
        self.add([track()])
        self.db.confirm_album(self.db.albums()[0]["id"], URI)
        destination = Path(self.folder.name) / "backup.db"
        self.db.backup(destination)
        restored = Database(destination)
        self.assertEqual(restored.status(), self.db.status())
        self.assertEqual(restored.recommend(0, 1)["spotify_uri"], URI)

    def test_enrichment_never_confirms_or_overwrites_verified_uri(self):
        self.add([track()])
        album_id = self.db.albums()[0]["id"]
        candidate = {"uri": URI, "confidence": "unverified"}
        self.db.save_enrichment(album_id, ["Folk"], None, candidate)
        self.assertIsNone(self.db.recommend(0, 1))
        self.db.confirm_album(album_id, URI)
        self.db.save_enrichment(album_id, [], None, None)
        self.assertEqual(self.db.recommend(0, 1)["spotify_uri"], URI)

    def test_calendar_year_clamps_leap_day(self):
        now = datetime(2024, 2, 29, 12, tzinfo=timezone.utc)
        self.assertEqual(calendar_cutoff(1, now), int(datetime(2023, 2, 28, 12, tzinfo=timezone.utc).timestamp()))

    def test_album_uri_and_share_parameter(self):
        self.assertEqual(spotify_uri("https://open.spotify.com/album/0S2DmRfqWM51FUprHs0qil?si=wrongidentifier"), URI)
        for invalid in ("wrongidentifier", "spotify:track:0S2DmRfqWM51FUprHs0qil", "https://evil.test/album/0S2DmRfqWM51FUprHs0qil"):
            with self.assertRaises(ValueError):
                spotify_uri(invalid)


class ApiTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        settings = Settings("user", "secret", TOKEN)
        self.worker = Worker(self.db, settings, threading.Event())
        self.worker.pending = False
        self.server = make_server(("127.0.0.1", 0), self.db, self.worker, TOKEN, self.folder.name)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def request(self, path, method="GET", body=None, token=TOKEN):
        headers = {"Authorization": "Bearer " + token}
        encoded = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, headers=headers, data=encoded, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def test_auth_all_data_routes_and_health(self):
        self.assertEqual(self.request("/health", token="")[0], 200)
        for path, method in (("/api/status", "GET"), ("/api/albums", "GET"),
                             ("/api/recommend", "GET"), ("/api/backup", "GET"),
                             ("/api/sync", "POST"), ("/api/albums/1", "POST"),
                             ("/api/sync/reset", "POST")):
            self.assertEqual(self.request(path, method, token="wrong")[0], 401)

    def test_browser_assets_load(self):
        for path in ("/", "/app.js", "/style.css"):
            code, body = self.request(path, token="")
            self.assertEqual(code, 200)
            self.assertGreater(len(body), 100)

    def test_ha_contract_and_validation(self):
        self.add([track()])
        self.assertIsNone(json.loads(self.request("/api/recommend?min_total_scrobbles=1")[1])["album"])
        album_id = self.db.albums()[0]["id"]
        self.assertEqual(self.request(f"/api/albums/{album_id}", "POST", {"spotify_uri": URI})[0], 200)
        code, body = self.request("/api/recommend?min_total_scrobbles=1")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["album"]["spotify_uri"], URI)
        for path in ("/api/recommend?min_years_unheard=-1", "/api/recommend?playable_only=maybe",
                     "/api/albums?limit=10000", "/api/recommend?min_years_unheard=1&min_years_unheard=2"):
            self.assertEqual(self.request(path)[0], 400)
        self.assertEqual(self.request(f"/api/albums/{album_id}", "POST", {"spotify_uri": "bad"})[0], 400)
        self.assertEqual(self.request("/api/albums/999", "POST", {"spotify_uri": URI})[0], 404)

    def test_sync_serialized_and_reset_cannot_race_worker(self):
        self.assertEqual(self.request("/api/sync", "POST", {})[0], 202)
        self.assertEqual(self.request("/api/sync", "POST", {})[0], 409)
        self.assertEqual(self.request("/api/sync/reset", "POST", {})[0], 409)

    def test_http_backup_is_valid_sqlite(self):
        self.add([track()])
        code, payload = self.request("/api/backup")
        self.assertEqual(code, 200)
        path = Path(self.folder.name) / "download.db"
        path.write_bytes(payload)
        self.assertEqual(Database(path).status()["scrobbles"], 1)


class WorkerTests(DatabaseCase):
    def test_restart_after_last_page_finishes_without_fetching_again(self):
        job = self.db.begin_import(2000000000)
        self.db.save_page([track()], job, 1)
        class NoMorePages:
            def recent(self, job):
                raise AssertionError("Final page already committed")
        worker = Worker(self.db, Settings("u", "key", TOKEN), threading.Event(), lastfm=NoMorePages())
        worker.sync()
        self.assertIsNone(self.db.get_state("import"))
        self.assertEqual(self.db.status()["scrobbles"], 1)

    def test_sync_checkpoints_and_repeated_run(self):
        class FakeLastFM:
            def recent(self, job):
                return ([track()] if job["page"] == 1 else [track(name="Casimir Pulaski Day")]), 2
        worker = Worker(self.db, Settings("u", "key", TOKEN), threading.Event(), lastfm=FakeLastFM())
        worker.sync()
        worker.sync()
        self.assertEqual(self.db.status()["scrobbles"], 2)
        self.assertIsNone(self.db.get_state("import"))
        self.assertIsNotNone(self.db.status()["last_sync_at"])

    def test_changed_page_count_stops_without_advancing(self):
        job = self.db.begin_import(2000000000)
        self.db.save_page([track()], job, 3)
        class FakeLastFM:
            def recent(self, job):
                return [], 2
        worker = Worker(self.db, Settings("u", "key", TOKEN), threading.Event(), lastfm=FakeLastFM())
        with self.assertRaises(ServiceError):
            worker.sync()
        self.assertEqual(self.db.get_state("import")["page"], 2)

    def test_now_playing_excluded(self):
        client = LastFM(Settings("u", "key", TOKEN), threading.Event())
        payload = {"recenttracks": {"@attr": {"totalPages": "1"}, "track": [
            {"@attr": {"nowplaying": "true"}, "name": "Chicago"},
            {"artist": {"#text": "Sufjan Stevens"}, "album": {"#text": "Illinois"},
             "name": "Chicago", "date": {"uts": "1435705200"}}]}}
        with patch.object(client, "call", return_value=payload):
            tracks, pages = client.recent({"page": 1, "upper": 2000000000, "lower": 0})
        self.assertEqual(len(tracks), 1)
        self.assertEqual(pages, 1)


if __name__ == "__main__":
    unittest.main()
