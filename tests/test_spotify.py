"""Offline catalogue matching, upgrade and independent lookup queue tests."""
import json
import threading
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from test_app import DatabaseCase, URI, TOKEN, track
from clients import Spotify, ServiceError
from database import Database
from settings import Settings
from worker import Worker

OTHER_URI = "spotify:album:" + "A" * 22


def item(uri=URI, name="Illinois", artist="Sufjan Stevens", **fields):
    return {"uri": uri, "name": name, "artists": [{"name": artist}], "images": [], **fields}


class SpotifyMatchingTests(DatabaseCase):
    def client(self):
        stop = Mock(spec=threading.Event)
        stop.wait.return_value = False
        stop.is_set.return_value = False
        return Spotify(Settings("user", "key", spotify_client_id="client",
                                spotify_client_secret="secret"), stop)

    def search(self, items, **page):
        with patch("clients.request_json", side_effect=[
                {"access_token": "private", "expires_in": 3600},
                {"albums": {"items": items, "next": None, **page}}]) as request:
            result = self.client().search_album(track())
        query = parse_qs(urlsplit(request.call_args.args[0]).query)
        self.assertEqual(query["market"], ["FI"])
        self.assertEqual(query["limit"], ["10"])
        return result

    def test_unique_exact_match_is_selected_ahead_of_other_editions(self):
        result = self.search([item(OTHER_URI, "Illinois (Deluxe Edition)"), item()])
        self.assertEqual(result["uri"], URI)
        self.assertEqual(result["confidence"], "exact_unique")
        self.assertEqual(len(result["alternatives"]), 2)

    def test_ambiguous_versions_collaborations_and_suffixes_need_review(self):
        for items in ([item(), item(OTHER_URI)], [item(name="Illinois (Remastered)")],
                      [item(artists=[{"name": "Sufjan Stevens"}, {"name": "Other"}])],
                      [item(restrictions={"reason": "market"})]):
            with self.subTest(items=items):
                self.assertEqual(self.search(items)["confidence"], "unverified")

    def test_wrong_artists_and_substring_names_are_excluded(self):
        self.assertIsNone(self.search([item(artist="Other Artist")]))
        self.assertIsNone(self.search([item(artist="Sufjan Stevens Orchestra")]))
        with patch("clients.request_json", side_effect=[
                {"access_token": "private", "expires_in": 3600},
                {"albums": {"items": [item(name="Arca", artist="Arca"),
                                        item(OTHER_URI, name="Arcane", artist="Arcane, League of Legends")], "next": None}}]):
            result = self.client().search_album(track(artist="Arca", album="Arca"))
        self.assertEqual(len(result["alternatives"]), 1)
        self.assertEqual(result["confidence"], "exact_unique")

    def test_cached_candidates_are_filtered_without_changing_the_confirmed_link(self):
        self.add([track(artist="Arca", album="Arca")])
        album_id = self.db.albums()[0]["id"]
        good = {"uri": URI, "name": "Arca", "artists": ["Arca"], "exact": True}
        wrong = {"uri": OTHER_URI, "name": "Arcane", "artists": ["Arcane, League of Legends"], "exact": False}
        candidate = {**good, "confidence": "exact_unique", "alternatives": [good, wrong]}
        self.db.save_spotify_match(album_id, candidate, "FI")
        album = self.db.album(album_id)
        self.assertEqual(album["spotify_uri"], URI)
        self.assertEqual(json.loads(album["spotify_candidate"])["alternatives"], [good])
        self.db.save_enrichment(album_id, [], None, {**wrong, "alternatives": [wrong]})
        album = self.db.album(album_id)
        self.assertIsNone(album["spotify_candidate"])
        self.assertEqual(album["spotify_uri"], URI)

    def test_case_spacing_and_unicode_are_normalized_but_punctuation_is_kept(self):
        self.assertEqual(self.search([item(name="  ILLINOIS  ", artist="Ｓufjan Stevens")])["confidence"], "exact_unique")
        self.assertEqual(self.search([item(name="Illinois!")])["confidence"], "unverified")

    def test_duplicate_uris_do_not_create_ambiguity(self):
        self.assertEqual(self.search([item(), item()])["confidence"], "exact_unique")

    def test_later_page_prevents_false_unique_match(self):
        with patch("clients.request_json", side_effect=[
                {"access_token": "private", "expires_in": 3600},
                {"albums": {"items": [item()], "next": "not-followed-directly"}},
                {"albums": {"items": [item(OTHER_URI)], "next": None}}]) as request:
            result = self.client().search_album(track())
        self.assertEqual(result["confidence"], "unverified")
        self.assertIn("offset=10", request.call_args.args[0])
        self.assertTrue(request.call_args.args[0].startswith("https://api.spotify.com/v1/search?"))

    def test_capped_search_is_never_automatically_accepted(self):
        with patch("clients.request_json", side_effect=[
                {"access_token": "private", "expires_in": 3600},
                *[{"albums": {"items": [item()], "next": "more"}}] * 3]):
            result = self.client().search_album(track())
        self.assertFalse(result["complete"])
        self.assertEqual(result["confidence"], "unverified")

    def test_no_credentials_or_no_results(self):
        with patch("clients.request_json") as request:
            self.assertIsNone(Spotify(Settings("u", "key"), threading.Event()).search_album(track()))
            request.assert_not_called()
        self.assertIsNone(self.search([]))

    def test_api_failure_does_not_produce_a_match(self):
        with patch("clients.request_json", side_effect=ServiceError("API HTTP 403")):
            with self.assertRaises(ServiceError):
                self.client().search_album(track())


class SpotifyQueueTests(DatabaseCase):
    def test_market_setting_defaults_for_existing_options_and_validates_country_format(self):
        path = self.db.path + ".json"
        from pathlib import Path
        options = {"lastfm_username": "user", "lastfm_api_key": "key"}
        Path(path).write_text(json.dumps(options), encoding="utf-8")
        self.assertEqual(Settings.read(path).spotify_market, "FI")
        for market in ("fi", "Finland", "", "F1"):
            Path(path).write_text(json.dumps({**options, "spotify_market": market}), encoding="utf-8")
            with self.assertRaises(ValueError):
                Settings.read(path)

    def test_new_credentials_search_already_enriched_albums_and_cache_negatives(self):
        self.add([track()])
        album_id = self.db.albums()[0]["id"]
        self.db.save_enrichment(album_id, ["folk"], None, None)
        self.assertEqual(len(self.db.spotify_queue(10, "FI")), 1)
        self.db.save_spotify_match(album_id, None, "FI")
        self.assertEqual(self.db.spotify_queue(10, "FI"), [])
        self.assertEqual(len(self.db.spotify_queue(10, "SE")), 1)
        with self.db.connect() as conn:
            conn.execute("UPDATE albums SET spotify_checked_at=1")
        self.assertEqual(len(self.db.spotify_queue(10, "FI")), 1)

    def test_automatic_links_are_playable_manual_edits_survive_inflight_search(self):
        self.add([track()])
        album_id = self.db.albums()[0]["id"]
        candidate = {"uri": URI, "confidence": "exact_unique"}
        self.db.save_spotify_match(album_id, candidate, "FI")
        self.assertEqual(self.db.recommend(0, 1)["spotify_uri"], URI)
        self.assertEqual(self.db.status()["automatic_albums"], 1)
        self.assertEqual(self.db.spotify_queue(10, "FI"), [])
        self.db.confirm_album(album_id, OTHER_URI)
        self.db.save_spotify_match(album_id, candidate, "FI")
        self.db.save_enrichment(album_id, ["folk"], None, None)
        album = self.db.album(album_id)
        self.assertEqual(album["spotify_uri"], OTHER_URI)
        self.assertEqual(album["spotify_match_source"], "manual")
        self.assertEqual(self.db.status()["automatic_albums"], 0)

    def test_ambiguous_match_remains_unplayable_and_metadata_preserves_options(self):
        self.add([track()])
        album_id = self.db.albums()[0]["id"]
        candidate = {"uri": URI, "confidence": "unverified", "alternatives": [item()]}
        self.db.save_spotify_match(album_id, candidate, "FI")
        self.db.save_enrichment(album_id, [], None, None)
        self.assertIsNone(self.db.recommend(0, 1))
        album = self.db.album(album_id)
        self.assertEqual(json.loads(album["spotify_candidate"]), candidate)
        self.assertEqual(album["spotify_status"], "candidate")

    def test_schema_one_upgrade_preserves_history_confirmed_links_and_suggestions(self):
        self.add([track()])
        album_id = self.db.albums()[0]["id"]
        self.db.confirm_album(album_id, URI)
        with self.db.connect() as conn:
            conn.executemany("INSERT INTO album_tags VALUES (?, ?)", [(album_id, "2005"), (album_id, "folk")])
            for name in ("spotify_checked_at", "spotify_checked_market", "spotify_match_source", "release_year"):
                conn.execute(f"ALTER TABLE albums DROP COLUMN {name}")
            conn.execute("PRAGMA user_version=1")
        restored = Database(self.db.path)
        self.assertEqual(restored.status()["scrobbles"], 1)
        self.assertEqual(restored.album(album_id)["spotify_uri"], URI)
        self.assertEqual(restored.album(album_id)["release_year"], 2005)
        self.assertEqual(restored.album(album_id)["tags"], ["folk"])
        self.assertEqual(restored.spotify_queue(10, "FI"), [])
        Database(self.db.path)  # Repeated initialization remains safe.

    def test_spotify_and_metadata_failures_are_independent_and_not_cached(self):
        self.add([track()])
        lastfm, spotify = Mock(), Mock()
        lastfm.album.side_effect = ServiceError("Last.fm unavailable")
        spotify.search_album.return_value = {"uri": URI, "confidence": "exact_unique"}
        worker = Worker(self.db, Settings("u", "key", TOKEN, spotify_client_id="client",
                        spotify_client_secret="secret"), threading.Event(), lastfm=lastfm, spotify=spotify)
        worker.enrich()
        self.assertEqual(self.db.recommend(0, 1)["spotify_uri"], URI)
        self.assertEqual(self.db.get_state("enrichment_error"), "Last.fm unavailable")
        self.db.confirm_album(self.db.albums()[0]["id"], URI)
        self.add([track(artist="Other", album="Other")])
        lastfm.album.side_effect = None
        lastfm.album.return_value = (["folk"], None)
        spotify.search_album.side_effect = ServiceError("Spotify unavailable")
        with patch("worker.time.time", return_value=self.db.get_state("lastfm_retry_at") + 1):
            worker.enrich()
        self.assertEqual(len(self.db.spotify_queue(10, "FI")), 1)
        self.assertEqual(self.db.get_state("spotify_error"), "Spotify unavailable")
        self.assertEqual(self.db.albums(query="Other")[0]["tags"], ["folk"])

    def test_without_credentials_lookup_remains_pending(self):
        self.add([track()])
        lastfm, spotify = Mock(), Mock()
        lastfm.album.return_value = ([], None)
        Worker(self.db, Settings("u", "key"), threading.Event(), lastfm=lastfm, spotify=spotify).enrich()
        spotify.search_album.assert_not_called()
        self.assertEqual(len(self.db.spotify_queue(10, "FI")), 1)


class AlbumYearTests(DatabaseCase):
    def test_years_are_album_metadata_and_never_genre_cloud_entries(self):
        self.add([track()])
        album_id = self.db.albums()[0]["id"]
        self.db.save_enrichment(album_id, ["2005", "Folk", "2005", "2000s"], None, None)
        self.assertEqual(self.db.album(album_id)["release_year"], 2005)
        self.assertEqual(self.db.album(album_id)["tags"], ["2000s", "folk"])
        self.assertNotIn("2005", [tag["name"] for tag in self.db.genres()["genres"]])
        self.db.confirm_album(album_id, URI, ["2005", "Indie Folk"])
        self.assertEqual(self.db.album(album_id)["tags"], ["indie folk"])
        self.db.save_enrichment(album_id, ["folk"], None, None)
        self.assertEqual(self.db.album(album_id)["release_year"], 2005)

    def test_conflicting_years_are_not_guessed(self):
        self.add([track()])
        album_id = self.db.albums()[0]["id"]
        self.db.save_enrichment(album_id, ["2005"], None, None)
        self.db.save_enrichment(album_id, ["2005", "2015", "folk"], None, None)
        self.assertIsNone(self.db.album(album_id)["release_year"])
        self.assertEqual(self.db.album(album_id)["tags"], ["folk"])
