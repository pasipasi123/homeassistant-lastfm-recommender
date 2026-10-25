"""Home Assistant app entrypoint; also supports an isolated local development run."""
import argparse
import logging
import signal
import threading
from pathlib import Path

from api import make_server
from database import Database
from settings import Settings
from worker import Worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--options", default="/data/options.json")
    parser.add_argument("--data", default="/data")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = Settings.read(args.options)
    except (ValueError, KeyError, TypeError, OSError):
        logging.error("Invalid app options: set Last.fm credentials, a 32+ character api_token, "
                      "a valid timezone, interval and matching optional Spotify credentials")
        return 1
    data = Path(args.data)
    data.mkdir(parents=True, exist_ok=True)
    db = Database(data / "scrobbles.db", settings.timezone)
    stored_user = db.get_state("lastfm_username")
    if stored_user and stored_user != settings.lastfm_username:
        logging.error("Last.fm username differs from database owner; use a separate data directory")
        return 1
    db.set_state("lastfm_username", settings.lastfm_username)
    stop = threading.Event()
    worker = Worker(db, settings, stop)
    server = make_server((args.host, args.port), db, worker, settings.api_token, data)
    server.timeout = 0.5

    def shutdown(_signum, _frame):
        stop.set()
        worker.wake.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    thread = threading.Thread(target=worker.run, name="sync", daemon=True)
    thread.start()
    logging.info("Last.fm Recommender listening on port %s", args.port)
    try:
        while not stop.is_set():
            server.handle_request()
    finally:
        stop.set()
        worker.wake.set()
        server.server_close()
        thread.join(timeout=35)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
