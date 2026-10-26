"""Single worker serializes sync and enrichment; HTTP stays responsive."""
import logging
import threading
import time
import traceback
from pathlib import Path

from clients import LastFM, ServiceError, Spotify

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
                self.running = sync_due or enrichment_due or metadata_due
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
