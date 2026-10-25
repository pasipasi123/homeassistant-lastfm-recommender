"""Single worker serializes sync and enrichment; HTTP stays responsive."""
import logging
import threading
import time

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
        self.pending = True

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

    def enrich(self):
        self.db.set_state("enrichment_error", None)
        for album in self.db.enrichment_queue(self.settings.enrich_batch_size):
            if self.stop.is_set():
                return
            try:
                tags, image = self.lastfm.album(album)
            except ServiceError as error:
                # Code 6 means album metadata is missing; cache the negative result.
                if error.code != 6:
                    raise
                tags, image = [], None
            candidate = self.spotify.search_album(album)
            if candidate and candidate.get("image_url"):
                image = candidate["image_url"]
            self.db.save_enrichment(album["id"], tags, image, candidate)

    def run(self):
        while not self.stop.is_set():
            with self.lock:
                self.pending = False
                self.running = True
            try:
                self.sync()
                if not self.stop.is_set():
                    try:
                        self.enrich()
                    except Exception as error:
                        message = str(error) if isinstance(error, ServiceError) else type(error).__name__
                        self.db.set_state("enrichment_error", message)
                        LOG.warning("Enrichment stopped: %s", message)
            except Exception as error:
                message = str(error) if isinstance(error, ServiceError) else type(error).__name__
                self.db.set_state("last_error", message)
                LOG.warning("Sync stopped: %s", message)
            finally:
                with self.lock:
                    self.running = False
            self.wake.wait(self.settings.sync_interval_minutes * 60)
            self.wake.clear()

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
