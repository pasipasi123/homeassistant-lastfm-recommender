"""Saved SpotifyPlus library paging and conservative, local album matching."""
import json
import threading
from unittest.mock import Mock, patch

from test_app import DatabaseCase, PLAYER, URI, track
from homeassistant import HomeAssistant, HomeAssistantError
from settings import Settings
from worker import Worker


def saved(name="Illinois", uri=URI, **extra):
    return {"name": name, "artists": ["Sufjan Stevens"], "uri": uri, "restricted": False, **extra}


class SavedLibraryTests(DatabaseCase):
    def test_only_exact_names_link_and_confirmed_editions_are_preserved(self):
        self.add([track(), track(album="Carrie & Lowell"), track(album="Illinois (Deluxe)"), track(album="Seven Swans")])
        original = self.db.albums(query="Seven Swans")[0]["id"]
        self.db.confirm_album(original, URI)
        self.db.set_state("spotifyplus_entity", PLAYER)
        albums = [saved(), saved("Carrie & Lowell", "spotify:album:" + "A" * 22),
                  saved("Carrie & Lowell", "spotify:album:" + "B" * 22),
                  saved("Seven Swans", "spotify:album:" + "C" * 22)]
        result = self.db.match_saved_albums(albums, PLAYER)
        self.assertEqual(result, {"linked": 1, "review": 1})
        illinois = self.db.album(self.db.albums(query="Illinois")[0]["id"])
        self.assertEqual(illinois["spotify_status"], "confirmed")
        self.assertEqual(illinois["spotify_match_source"], "saved_library")
        self.assertEqual(self.db.album(original)["spotify_uri"], URI)
        self.assertEqual(self.db.albums(query="Deluxe")[0]["spotify_status"], "missing")
        candidate = self.db.albums(query="Carrie")[0]
        self.assertEqual(candidate["spotify_status"], "candidate")
        self.assertEqual(len(json.loads(candidate["spotify_candidate"])["alternatives"]), 2)

    def test_restricted_editions_need_review_and_account_changes_cannot_write(self):
        self.add([track()])
        self.db.set_state("spotifyplus_entity", PLAYER)
        self.assertEqual(self.db.match_saved_albums([saved(restricted=True)], PLAYER)["review"], 1)
        with self.assertRaises(ValueError):
            self.db.match_saved_albums([saved()], "media_player.other")
        self.assertEqual(self.db.albums()[0]["spotify_status"], "candidate")

    def worker(self, pages):
        self.db.set_state("spotifyplus_entity", PLAYER)
        worker = Worker(self.db, Settings("u", "key"), threading.Event())
        worker.home_assistant = Mock()
        worker.home_assistant.saved_albums.side_effect = pages
        worker.pending = False
        self.assertTrue(worker.request_library(PLAYER))
        return worker

    def test_paging_waits_for_all_editions_and_keeps_only_sanitized_metadata(self):
        self.add([track()])
        pages = [{"albums": [saved()], "count": 1, "total": 2, "has_more": True},
                 {"albums": [saved(uri="spotify:album:" + "A" * 22)], "count": 1, "total": 2, "has_more": False}]
        worker = self.worker(pages)
        worker.import_library()
        self.assertEqual(worker.home_assistant.saved_albums.call_args_list[1].args, (PLAYER, 1))
        self.assertEqual(self.db.albums()[0]["spotify_status"], "candidate")
        job = self.db.get_state("spotify_library_import")
        self.assertEqual((job["status"], job["fetched"], job["linked"], job["review"]), ("complete", 2, 0, 1))

    def test_failed_second_page_does_not_link_partial_results_and_blocks_immediate_retry(self):
        self.add([track()])
        worker = self.worker([{"albums": [saved()], "count": 1, "total": 2, "has_more": True},
                              HomeAssistantError("Service unavailable")])
        with patch("worker.LOG.warning"):
            worker.import_library()
        self.assertEqual(self.db.albums()[0]["spotify_status"], "missing")
        self.assertEqual(self.db.get_state("spotify_library_import")["status"], "error")
        worker.library_pending = False
        self.assertFalse(worker.request_library(PLAYER))

    def test_restart_marks_pending_import_interrupted(self):
        self.db.set_state("spotify_library_import", {"status": "running", "fetched": 50, "total": 961})
        Worker(self.db, Settings("u", "key"), threading.Event())
        self.assertEqual(self.db.get_state("spotify_library_import")["status"], "interrupted")

    def test_ha_service_response_uses_fixed_paging_and_discards_personal_profile(self):
        client = HomeAssistant("secret")
        page = {"service_response": {"user_profile": {"email": "private@example.com"},
                "result": {"items": [{"album": {**saved(), "artists": [{"name": "Sufjan Stevens"}], "tracks": {"items": ["unneeded"]}}}],
                           "total": 1, "offset": 0, "next": None}}}
        with patch.object(client, "_request", return_value=page) as request:
            result = client.saved_albums(PLAYER)
        request.assert_called_once_with("/services/spotifyplus/get_album_favorites?return_response",
                                        {"entity_id": PLAYER, "limit": 50, "offset": 0, "sort_result": False})
        self.assertEqual(result["albums"][0]["uri"], URI)
        self.assertNotIn("private@example.com", json.dumps(result))
        self.assertNotIn("tracks", result["albums"][0])
        self.assertNotIn("unneeded", json.dumps(result))
        page["service_response"]["result"]["offset"] = 50
        with patch.object(client, "_request", return_value=page), self.assertRaises(HomeAssistantError):
            client.saved_albums(PLAYER)

    def test_changed_library_count_cannot_confirm_first_page(self):
        self.add([track()])
        worker = self.worker([{"albums": [saved()], "count": 1, "total": 2, "has_more": True},
                              {"albums": [], "count": 0, "total": 1, "has_more": False}])
        with patch("worker.LOG.warning"):
            worker.import_library()
        self.assertEqual(self.db.albums()[0]["spotify_status"], "missing")
        self.assertEqual(self.db.get_state("spotify_library_import")["status"], "error")
