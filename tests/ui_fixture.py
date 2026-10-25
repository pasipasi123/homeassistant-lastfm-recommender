"""Offline server with synthetic data for the optional browser smoke test."""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lastfm_recommender/rootfs/app"))
from api import make_server
from database import Database
from settings import Settings
from worker import Worker

TOKEN = "browser-test-" + "x" * 32
with tempfile.TemporaryDirectory() as folder:
    db = Database(Path(folder) / "demo.db")
    job = db.begin_import(2000000000)
    tracks = [{"timestamp": 1435705200, "artist": "Sufjan Stevens", "album": "Illinois",
               "track": "Chicago"} for _ in range(20)]
    db.save_page(tracks, job, 1)
    db.finish_import(job["upper"])
    worker = Worker(db, Settings("demo", "not-a-real-key", TOKEN), threading.Event())
    worker.pending = False
    server = make_server(("127.0.0.1", 0), db, worker, TOKEN, folder)
    print(server.server_port, flush=True)
    server.serve_forever()
