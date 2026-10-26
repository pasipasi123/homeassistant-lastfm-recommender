"""Bounded artist lookup, meaningful listening thresholds, and safe partial results."""
import threading
from unittest.mock import Mock, patch

from test_app import DatabaseCase, PLAYER, URI, track
from settings import Settings
from worker import Worker
from homeassistant import HomeAssistant, HomeAssistantError


def album_uri(n):
    return "spotify:album:" + str(n).zfill(22)


class ArtistLookupTests(DatabaseCase):
    def artist(self, name="Artist", count=3, listens=20):
        rows = [track(artist=name, album=f"Album {n}", name=f"Track {t}") for n in range(count) for t in range(listens)]
        rows.append(track(artist=name, album="Known"))
        self.add(rows)
        seed = self.db.albums(query="Known")
        seed = next(a for a in seed if a["artist"] == name)
        self.db.confirm_album(seed["id"], URI)

    def worker(self):
        self.db.set_state("spotifyplus_entity", PLAYER)
        worker = Worker(self.db, Settings("u", "key"), threading.Event())
        worker.home_assistant = Mock()
        worker.pending = False
        self.assertTrue(worker.request_artists(PLAYER))
        return worker

    def test_thresholds_and_seed_and_batch_limit(self):
        self.artist("Too few listens", listens=19)
        self.artist("Too few albums", count=2)
        for n in range(6):
            self.artist(f"Artist {n}")
        self.db.set_state("spotifyplus_entity", PLAYER)
        queue = self.db.artist_queue(PLAYER)
        self.assertEqual(len(queue), 5)
        self.assertTrue(all(a["missing_albums"] == 3 and a["artist"].startswith("Artist ") for a in queue))
        self.db.mark_artist_checked(PLAYER, queue[0]["artist_search"], "A" * 22)
        self.assertNotIn(queue[0]["artist_search"], [a["artist_search"] for a in self.db.artist_queue(PLAYER)])

    def test_recommendation_default_excludes_nineteen_scrobbles(self):
        self.artist("Nineteen", count=1, listens=19)
        self.assertIsNone(self.db.recommend(min_years=0, playable_only=False))
        self.artist("Twenty", count=1, listens=20)
        self.assertEqual(self.db.recommend(min_years=0, playable_only=False)["artist"], "Twenty")

    def test_incomplete_results_are_review_only_and_requests_never_exceed_twenty(self):
        for n in range(6):
            self.artist(f"Artist {n}")
        worker = self.worker()
        worker.home_assistant.artist_id_for_album.side_effect = lambda _e, _u, name: name.split()[-1].zfill(22)
        def page(_entity, artist_id, _market, offset):
            name = "Artist " + str(int(artist_id))
            albums = [{"uri": album_uri(int(artist_id) * 100 + offset + n), "name": f"Album {offset + n}",
                       "artists": [name], "restricted": False} for n in range(10)]
            return {"albums": albums, "count": 10, "total": 40, "has_more": True}
        worker.home_assistant.artist_albums.side_effect = page
        with patch.object(worker.stop, "wait", return_value=False):
            worker.import_artists()
        job = self.db.get_state("spotify_artist_import")
        self.assertEqual((job["artists"], job["requests"], job["truncated"], job["linked"], job["review"]), (5, 20, 5, 0, 15))
        self.assertEqual(worker.home_assistant.artist_albums.call_count, 15)
        self.assertEqual([a["artist"] for a in self.db.artist_queue(PLAYER)], ["Artist 5"])

    def test_complete_exact_matches_link_but_under_twenty_stays_unlinked(self):
        self.artist()
        self.add([track(artist="Artist", album="Low", name=f"Track {n}") for n in range(19)])
        worker = self.worker()
        worker.home_assistant.artist_id_for_album.return_value = "A" * 22
        albums = [{"uri": album_uri(n), "name": name, "artists": ["Artist"], "restricted": False}
                  for n, name in enumerate(["Album 0", "Album 1", "Album 2", "Low"])]
        worker.home_assistant.artist_albums.return_value = {"albums": albums, "count": 4, "total": 4, "has_more": False}
        with patch.object(worker.stop, "wait", return_value=False):
            worker.import_artists()
        job = self.db.get_state("spotify_artist_import")
        self.assertEqual((job["linked"], job["review"], job["requests"]), (3, 0, 2))
        self.assertEqual(self.db.albums(query="Low")[0]["spotify_status"], "missing")
        self.assertEqual(self.db.albums(query="Album 0")[0]["spotify_match_source"], "artist_catalog")

    def test_page_failure_keeps_current_artist_unmodified_and_adds_retry_deadline(self):
        self.artist()
        worker = self.worker()
        worker.home_assistant.artist_id_for_album.return_value = "A" * 22
        worker.home_assistant.artist_albums.side_effect = HomeAssistantError("Service unavailable")
        with patch.object(worker.stop, "wait", return_value=False), patch("worker.LOG.warning"):
            worker.import_artists()
        self.assertEqual(self.db.albums(query="Album 0")[0]["spotify_status"], "missing")
        self.assertEqual(self.db.get_state("spotify_artist_import")["status"], "error")
        worker.artist_pending = False
        self.assertFalse(worker.request_artists(PLAYER))

    def test_artist_identity_and_page_use_only_fixed_services_and_bounded_page_size(self):
        client = HomeAssistant("secret")
        identity = {"service_response": {"result": {"artists": [{"id": "A" * 22, "name": "Artist"}]}}}
        with patch.object(client, "_request", return_value=identity) as request:
            self.assertEqual(client.artist_id_for_album(PLAYER, URI, "ARTIST"), "A" * 22)
            self.assertIsNone(client.artist_id_for_album(PLAYER, URI, "Other Artist"))
            self.assertEqual(request.call_args.args[0], "/services/spotifyplus/get_album?return_response")
        page = {"service_response": {"result": {"items": [], "total": 0, "next": None, "offset": 0}}}
        with patch.object(client, "_request", return_value=page) as request:
            client.artist_albums(PLAYER, "A" * 22, "FI")
        self.assertEqual(request.call_args.args[1]["limit"], 10)
        self.assertNotIn("limit_total", request.call_args.args[1])
