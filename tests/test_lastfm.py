"""Last.fm's optional album metadata can use inconsistent empty JSON shapes."""
import threading
from unittest.mock import Mock, patch

from test_app import DatabaseCase, track
from clients import LastFM, ServiceError
from settings import Settings
from worker import Worker


class LastFMMetadataTests(DatabaseCase):
    def client(self):
        return LastFM(Settings("test-user", "test-secret"), threading.Event())

    def test_empty_and_null_tag_containers_do_not_raise_attribute_error(self):
        client = self.client()
        for tags in ("", None, {}, {"tag": None}, {"tag": ""}, {"tag": []}):
            with self.subTest(tags=tags), patch.object(client, "call", return_value={
                    "album": {"tags": tags, "image": [{"#text": "https://example.com/cover.jpg"}]}}):
                self.assertEqual(client.album(track()), ([], "https://example.com/cover.jpg"))

    def test_optional_images_and_single_tag_or_image_objects(self):
        client = self.client()
        for images in ("", None, [], {}, [None, "", {}, {"#text": None}]):
            with self.subTest(images=images), patch.object(client, "call", return_value={
                    "album": {"tags": {"tag": {"name": "Folk"}}, "image": images}}):
                self.assertEqual(client.album(track()), (["Folk"], None))
        with patch.object(client, "call", return_value={"album": {}}):
            self.assertEqual(client.album(track()), ([], None))
        with patch.object(client, "call", return_value={"album": {
                "tags": {"tag": [None, "", {"name": None}, {"name": ""}, {"name": "2005"}]},
                "image": {"#text": "https://example.com/cover.jpg"}}}):
            self.assertEqual(client.album(track()), (["2005"], "https://example.com/cover.jpg"))

    def test_invalid_required_album_data_is_a_clear_service_error(self):
        client = self.client()
        with patch.object(client, "call", return_value={"album": None}):
            with self.assertRaisesRegex(ServiceError, "Last.fm returned invalid album metadata"):
                client.album(track())

    def test_empty_tags_do_not_block_the_next_album_or_spotify_queue(self):
        self.add([track(), track(artist="Other", album="Other")])
        client = self.client()
        worker = Worker(self.db, client.settings, threading.Event(), lastfm=client)
        with patch.object(client, "call", side_effect=[
                {"album": {"tags": "", "image": None}},
                {"album": {"tags": {"tag": [{"name": "Folk"}]}}}]):
            worker.enrich()
        self.assertIsNone(self.db.get_state("enrichment_error"))
        self.assertEqual(self.db.enrichment_queue(10), [])
        self.assertEqual(self.db.albums(query="Other")[0]["tags"], ["folk"])

    def test_unexpected_failure_logs_location_without_exception_values(self):
        worker = Worker(self.db, Settings("test-user", "key"), threading.Event())
        with patch.object(worker, "enrich_metadata", side_effect=AttributeError("private-secret")), \
             self.assertLogs("worker", level="WARNING") as logs:
            worker.enrich()
        self.assertIn("Failure location:", " ".join(logs.output))
        self.assertNotIn("private-secret", " ".join(logs.output))
        self.assertEqual(self.db.get_state("enrichment_error"), "AttributeError")
