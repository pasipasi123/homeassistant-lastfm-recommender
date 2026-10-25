"""Offline direct + prefixed ingress servers with synthetic history and a fake HA."""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lastfm_recommender/rootfs/app"))
import api
from api import make_server
from database import Database
from homeassistant import HomeAssistantError
from settings import Settings
from worker import Worker

TOKEN = "browser-test-" + "x" * 32
PLAYER = "media_player.demo_music"
PREFIX = "/api/hassio_ingress/test-session/"


class FakeHA:
    available = True
    state = "idle"
    title = None
    volume = 0.2

    def players(self):
        return [{"entity_id": PLAYER, "name": "Demo SpotifyPlus", "state": self.state,
                 "title": self.title, "artist": "Sufjan Stevens" if self.title else None,
                 "source": "Demo receiver", "volume_level": self.volume}]

    def validate_player(self, entity_id):
        if entity_id != PLAYER:
            raise HomeAssistantError("Select a SpotifyPlus player")

    def play(self, entity_id, uri):
        self.validate_player(entity_id)
        if uri != "spotify:album:0S2DmRfqWM51FUprHs0qil":
            raise ValueError("Unexpected URI")
        self.state, self.title = "playing", "Chicago"

    def control(self, entity_id, action, volume=None):
        self.validate_player(entity_id)
        if action == "pause":
            self.state = "paused"
        elif action == "resume":
            self.state = "playing"
        elif action == "next":
            self.title = "Next track"
        elif action == "volume":
            self.volume = volume
        else:
            raise ValueError("Unsupported action")


with tempfile.TemporaryDirectory() as folder:
    db = Database(Path(folder) / "demo.db")
    job = db.begin_import(2000000000)
    tracks = [{"timestamp": 1435705200, "artist": "Sufjan Stevens", "album": "Illinois",
               "track": "Chicago"} for _ in range(20)]
    db.save_page(tracks, job, 1)
    db.finish_import(job["upper"])
    worker = Worker(db, Settings("demo", "not-a-real-key", TOKEN), threading.Event())
    worker.pending = False
    ha = FakeHA()
    server = make_server(("127.0.0.1", 0), db, worker, TOKEN, folder, home_assistant=ha)
    # Only this isolated test process treats loopback as the Supervisor proxy.
    api.INGRESS_PEER = "127.0.0.1"
    ingress = make_server(("127.0.0.1", 0), db, worker, "", folder, home_assistant=ha, ingress=True)
    threading.Thread(target=ingress.serve_forever, daemon=True).start()

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def proxy(self):
            if not self.path.startswith(PREFIX):
                self.send_error(404)
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))) if self.command == "POST" else None
            request = Request(f"http://127.0.0.1:{ingress.server_port}/" + self.path[len(PREFIX):],
                              data=body, method=self.command,
                              headers={"Content-Type": self.headers.get("Content-Type", ""),
                                       "X-Ingress-Path": PREFIX.rstrip("/")})
            try:
                response = urlopen(request, timeout=10)
            except HTTPError as error:
                response = error
            with response:
                payload = response.read()
                self.send_response(response.status)
                for name in ("Content-Type", "Content-Disposition", "Content-Security-Policy"):
                    if name in response.headers:
                        self.send_header(name, response.headers[name])
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        do_GET = proxy
        do_POST = proxy

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    print(json.dumps({"direct": server.server_port, "ingress": proxy.server_port}), flush=True)
    server.serve_forever()
