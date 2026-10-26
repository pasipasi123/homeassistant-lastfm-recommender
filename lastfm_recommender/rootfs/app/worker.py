"""Single worker serializes sync and enrichment; HTTP stays responsive."""
import logging
import threading
import time
import traceback
from pathlib import Path

from clients import LastFM, ServiceError, Spotify
from homeassistant import HomeAssistantError

LOG = logging.getLogger(__name__)


class Worker:
    def __init__(self, db, settings, stop, lastfm=None, spotify=None):
        self.db, self.settings, self.stop = db, settings, stop
        self.lastfm = lastfm or LastFM(settings, stop)
        self.spotify = spotify or Spotify(settings, stop)
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.running = False
        self.phase = "idle"
        self.pending = True
        self.enrichment_pending = False
        self.metadata_pending = False
        self.home_assistant = None
        self.library_pending = False
        self.artist_pending = False
        previous_artists = self.db.get_state("spotify_artist_import")
        if previous_artists and previous_artists.get("status") in ("queued", "running"):
            self.db.set_state("spotify_artist_import", {**previous_artists, "status": "interrupted"})
        previous_library = self.db.get_state("spotify_library_import")
        if previous_library and previous_library.get("status") in ("queued", "running"):
            self.db.set_state("spotify_library_import", {**previous_library, "status": "interrupted"})

    def request_library(self, entity_id):
        with self.lock:
            previous = self.db.get_state("spotify_library_import") or {}
            if (self.running or self.pending or self.library_pending or self.artist_pending or not self.home_assistant or
                    not self.home_assistant.available or (previous.get("retry_at") or 0) > time.time()):
                return False
            self.db.set_state("spotify_library_import", {"status": "queued", "entity_id": entity_id,
                              "fetched": 0, "total": None})
            self.library_pending = True
            self.wake.set()
            return True

    def request_artists(self, entity_id):
        with self.lock:
            previous = self.db.get_state("spotify_artist_import") or {}
            if (self.running or self.pending or self.library_pending or self.artist_pending or not self.home_assistant or
                    not self.home_assistant.available or (previous.get("retry_at") or 0) > time.time()):
                return False
            self.db.set_state("spotify_artist_import", {"status": "queued", "entity_id": entity_id,
                              "artists": 0, "requests": 0, "linked": 0, "review": 0, "truncated": 0})
            self.artist_pending = True
            self.wake.set()
            return True

    def import_artists(self):
        job = self.db.get_state("spotify_artist_import")
        entity_id = job["entity_id"]
        try:
            self.home_assistant.validate_player(entity_id)
            queue = self.db.artist_queue(entity_id)
            job = {**job, "status": "running", "selected": len(queue)}
            self.db.set_state("spotify_artist_import", job)
            for artist in queue:
                albums, total, offset, complete = [], None, 0, False
                if self.stop.is_set():
                    self.db.set_state("spotify_artist_import", {**job, "status": "interrupted"})
                    return
                if self.db.get_state("spotifyplus_entity") != entity_id:
                    raise HomeAssistantError("SpotifyPlus account changed. Start a new artist batch for the selected account.")
                artist_id = artist["artist_id"]
                if not artist_id:
                    job["requests"] += 1
                    artist_id = self.home_assistant.artist_id_for_album(entity_id, artist["reference_uri"], artist["artist"])
                if artist_id:
                    for _page in range(3):
                        if self.stop.wait(0.5):
                            self.db.set_state("spotify_artist_import", {**job, "status": "interrupted"})
                            return
                        job["requests"] += 1
                        page = self.home_assistant.artist_albums(entity_id, artist_id, self.settings.spotify_market, offset)
                        if total is not None and total != page["total"]:
                            raise HomeAssistantError("An artist's release list changed during lookup. Try again later.")
                        total = page["total"]
                        albums.extend(page["albums"])
                        offset += page["count"]
                        if len({album["uri"] for album in albums}) != len(albums):
                            raise HomeAssistantError("Duplicate releases appeared during paging. Artist lookup stopped safely.")
                        complete = offset == total and not page["has_more"]
                        if complete or not page["has_more"] or not page["count"]:
                            break
                    if self.stop.is_set():
                        self.db.set_state("spotify_artist_import", {**job, "status": "interrupted"})
                        return
                    result = self.db.match_saved_albums(albums, entity_id, source="artist_catalog", complete=complete,
                                                       artist_search=artist["artist_search"])
                    job["linked"] += result["linked"]
                    job["review"] += result["review"]
                    job["truncated"] += int(not complete)
                self.db.mark_artist_checked(entity_id, artist["artist_search"], artist_id)
                job["artists"] += 1
                self.db.set_state("spotify_artist_import", job)
            self.db.set_state("spotify_artist_import", {**job, "status": "complete", "finished_at": int(time.time())})
        except Exception as error:
            message = str(error) if isinstance(error, HomeAssistantError) else "Artist lookup stopped. Earlier completed artists were kept; try again later."
            self.db.set_state("spotify_artist_import", {**job, "status": "error", "error": message,
                              "retry_at": int(time.time()) + 900})
            LOG.warning("Spotify artist lookup stopped (%s)", type(error).__name__)

    def import_library(self):
        job = self.db.get_state("spotify_library_import")
        entity_id = job["entity_id"]
        albums, total, offset = [], None, 0
        try:
            self.home_assistant.validate_player(entity_id)
            while offset <= 10000:
                if self.stop.is_set():
                    self.db.set_state("spotify_library_import", {**job, "status": "interrupted"})
                    return
                if self.db.get_state("spotifyplus_entity") != entity_id:
                    raise HomeAssistantError("SpotifyPlus account changed. Start the import again for the selected account.")
                page = self.home_assistant.saved_albums(entity_id, offset)
                if total is not None and total != page["total"]:
                    raise HomeAssistantError("Your saved album count changed during import. Try again when library edits are finished.")
                total = page["total"]
                albums.extend(page["albums"])
                offset += page["count"]
                job = {**job, "status": "running", "fetched": offset, "total": total}
                self.db.set_state("spotify_library_import", job)
                if not page["has_more"]:
                    if offset != total:
                        raise HomeAssistantError("SpotifyPlus returned an incomplete library. Try the import again.")
                    if len({album["uri"] for album in albums}) != len(albums):
                        raise HomeAssistantError("Your saved library changed during paging. Try the import again when library edits are finished.")
                    # Compare only after every page was read: later pages may
                    # contain another edition with the same exact title.
                    if self.stop.is_set():
                        self.db.set_state("spotify_library_import", {**job, "status": "interrupted"})
                        return
                    result = self.db.match_saved_albums(albums, entity_id)
                    self.db.set_state("spotify_library_import", {**job, **result, "status": "complete", "finished_at": int(time.time())})
                    return
                if not page["count"]:
                    raise HomeAssistantError("SpotifyPlus returned an empty page before the end of your library.")
                if self.stop.wait(0.5):
                    self.db.set_state("spotify_library_import", {**job, "status": "interrupted"})
                    return
            raise HomeAssistantError("Saved library exceeds the supported paging range. No links were changed.")
        except Exception as error:
            message = str(error) if isinstance(error, HomeAssistantError) else "Saved album import stopped. Check the selected SpotifyPlus account and try again later."
            self.db.set_state("spotify_library_import", {**job, "status": "error", "error": message,
                              "retry_at": int(time.time()) + 900})
            LOG.warning("Spotify saved album import stopped (%s)", type(error).__name__)

    def request_metadata(self):
        with self.lock:
            if self.running or self.pending or self.metadata_pending or not self.settings.lastfm_batch_size or self.lastfm_paused():
                return False
            self.metadata_pending = True
            self.wake.set()
            return True

    def request_enrichment(self):
        with self.lock:
            if self.running or self.pending or self.enrichment_pending or not self.settings.enrich_batch_size:
                return False
            self.enrichment_pending = True
            self.wake.set()
            return True

    def request_sync(self):
        with self.lock:
            if self.running or self.pending:
                return False
            self.pending = True
            self.wake.set()
            return True

    def sync(self):
        # Delay the upper boundary to avoid importing the current minute.
        job = self.db.begin_import(int(time.time()) - 60)
        while not self.stop.is_set():
            if job["total_pages"] is not None and job["page"] > job["total_pages"]:
                # A restart can happen after committing the final page but before
                # marking the window complete. Do not request a nonexistent page.
                self.db.finish_import(job["upper"])
                return
            tracks, total = self.lastfm.recent(job)
            # Page count changes for a fixed range mean the user edited history.
            # Stop rather than silently advancing an unreliable checkpoint.
            if job["total_pages"] is not None and total != job["total_pages"]:
                raise ServiceError("History changed during import; reset the checkpoint with POST /api/sync/reset")
            job = self.db.save_page(tracks, job, total)
            if job["page"] > total:
                self.db.finish_import(job["upper"])
                return

    def enrich(self, *, metadata=True, spotify=True):
        for method, error_key in ((self.enrich_metadata, "enrichment_error"),
                                  (self.enrich_spotify, "spotify_error")):
            if error_key == "enrichment_error" and (not metadata or not self.settings.lastfm_batch_size or self.lastfm_paused()):
                continue
            if error_key == "spotify_error" and (not spotify or not self.settings.enrich_batch_size):
                continue
            if error_key == "spotify_error" and self.spotify_paused():
                continue
            self.db.set_state(error_key, None)
            try:
                method()
            except Exception as error:
                message = str(error) if isinstance(error, ServiceError) else type(error).__name__
                with self.db.connect() as conn:
                    self.db.set_state(error_key, message, conn)
                    if error_key == "spotify_error" and isinstance(error, ServiceError) and error.retry_after is not None:
                        self.db.set_state("spotify_retry_at", int(time.time()) + error.retry_after + 1, conn)
                    if error_key == "enrichment_error":
                        delay = error.retry_after if isinstance(error, ServiceError) and error.retry_after is not None else 900
                        self.db.set_state("lastfm_retry_at", int(time.time()) + delay + 1, conn)
                LOG.warning("Album update stopped (%s): %s", error_key, message)
                if not isinstance(error, ServiceError):
                    # Keep values, source lines, URLs and credentials out of logs.
                    frames = traceback.extract_tb(error.__traceback__)
                    LOG.warning("Failure location: %s", " -> ".join(
                        f"{Path(frame.filename).name}:{frame.lineno} ({frame.name})" for frame in frames[-3:]))

    def enrich_metadata(self):
        if self.lastfm_paused() or not self.settings.lastfm_batch_size:
            return
        self.db.set_state("enrichment_error", None)
        self.db.set_state("lastfm_retry_at", None)
        for album in self.db.enrichment_queue(self.settings.lastfm_batch_size):
            if self.stop.is_set():
                return
            try:
                tags, image = self.lastfm.album(album)
            except ServiceError as error:
                # Code 6 means album metadata is missing; cache the negative result.
                if error.code != 6:
                    raise
                tags, image = [], None
            self.db.save_enrichment(album["id"], tags, image, None)

    def lastfm_paused(self):
        return (self.db.get_state("lastfm_retry_at") or 0) > time.time()

    def spotify_paused(self):
        return (self.db.get_state("spotify_retry_at") or 0) > time.time()

    def enrich_spotify(self):
        if not self.settings.spotify_client_id or self.spotify_paused():
            return
        self.db.set_state("spotify_retry_at", None)
        for album in self.db.spotify_queue(self.settings.enrich_batch_size, self.settings.spotify_market):
            if self.stop.is_set():
                return
            candidate = self.spotify.search_album(album)
            self.db.save_spotify_match(album["id"], candidate, self.settings.spotify_market)

    def run(self):
        next_sync, next_enrichment, next_metadata = 0, 0, 0
        while not self.stop.is_set():
            now = time.monotonic()
            with self.lock:
                sync_due = self.pending or now >= next_sync
                library_due = self.library_pending
                artist_due = self.artist_pending
                if artist_due:
                    self.artist_pending = False
                if library_due:
                    self.library_pending = False
                enrichment_due = self.settings.enrich_batch_size > 0 and (
                    self.enrichment_pending or now >= next_enrichment)
                metadata_due = self.settings.lastfm_batch_size > 0 and (
                    self.metadata_pending or now >= next_metadata)
                if metadata_due:
                    self.metadata_pending = False
                if enrichment_due:
                    self.enrichment_pending = False
                if sync_due:
                    self.pending = False
                self.running = sync_due or enrichment_due or metadata_due or library_due or artist_due
            if not self.running:
                deadlines = [next_sync]
                if self.settings.enrich_batch_size:
                    deadlines.append(next_enrichment)
                if self.settings.lastfm_batch_size:
                    deadlines.append(next_metadata)
                deadline = min(deadlines)
                self.wake.wait(max(0, deadline - now))
                self.wake.clear()
                continue
            try:
                if library_due:
                    self.phase = "spotify_library"
                    self.import_library()
                if artist_due:
                    self.phase = "spotify_artists"
                    self.import_artists()
                if sync_due:
                    self.phase = "sync"
                    try:
                        self.sync()
                    except Exception as error:
                        message = str(error) if isinstance(error, ServiceError) else type(error).__name__
                        self.db.set_state("last_error", message)
                        LOG.warning("Sync stopped: %s", message)
                    finally:
                        next_sync = time.monotonic() + self.settings.sync_interval_minutes * 60
                if not self.stop.is_set() and (enrichment_due or metadata_due):
                    self.phase = "enrichment"
                    try:
                        self.enrich(metadata=metadata_due, spotify=enrichment_due)
                    except Exception as error:
                        message = str(error) if isinstance(error, ServiceError) else type(error).__name__
                        self.db.set_state("enrichment_error", message)
                        LOG.warning("Enrichment stopped: %s", message)
                    finally:
                        if enrichment_due:
                            next_enrichment = time.monotonic() + self.settings.enrich_interval_minutes * 60
                        if metadata_due:
                            next_metadata = time.monotonic() + self.settings.lastfm_interval_minutes * 60
            finally:
                with self.lock:
                    self.running = False
                    self.phase = "idle"

    def reset_checkpoint(self):
        with self.lock:
            if self.running or self.pending:
                return False
            with self.db.connect() as conn:
                self.db.set_state("import", None, conn)
                conn.execute("DELETE FROM import_seen")
            self.pending = True
            self.wake.set()
            return True
