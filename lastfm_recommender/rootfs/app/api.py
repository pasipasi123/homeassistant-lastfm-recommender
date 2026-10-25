"""Authenticated local REST API and static UI, without framework dependencies."""
import hmac
import json
import logging
import shutil
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from homeassistant import HomeAssistantError

LOG = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
INGRESS_PEER = "172.30.32.2"


def integer(value, name, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def make_server(address, db, worker, token, data_dir, *, home_assistant=None, ingress=False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LastfmRecommender"

        def log_message(self, _format, *_args):
            # Do not log query strings, Authorization or payloads.
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def respond_headers(self, status, content_type, length):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' https:; "
                             "frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
            self.end_headers()

        def send_json(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.respond_headers(status, "application/json; charset=utf-8", len(body))
            self.wfile.write(body)

        def authorized(self):
            if ingress:
                # Peer filtering happens before *any* routing, not via forwarded headers.
                return True
            actual = self.headers_in.get("Authorization", "")
            if not token or not hmac.compare_digest(actual.encode(), ("Bearer " + token).encode()):
                self.send_json(401, {"error": "Bearer API token required"})
                return False
            return True

        def do_GET(self):
            self.handle_api("GET")

        def do_POST(self):
            self.handle_api("POST")

        def handle_api(self, method):
            self.headers_in = self.headers
            if ingress and self.client_address[0] != INGRESS_PEER:
                self.send_json(403, {"error": "Ingress accepts connections from Supervisor only"})
                return
            try:
                self.route(method)
            except HomeAssistantError as error:
                self.send_json(503, {"error": str(error)})
            except (ValueError, TypeError, KeyError, OverflowError):
                self.send_json(400, {"error": "Invalid parameters, JSON body, album URI or filter range"})
            except LookupError:
                self.send_json(404, {"error": "Album not found"})
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except Exception as error:
                LOG.error("API request failed (%s)", type(error).__name__)
                self.send_json(500, {"error": "Internal server error"})

        def body(self):
            if self.headers_in.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("JSON Content-Type required")
            if self.headers_in.get("Transfer-Encoding"):
                raise ValueError("Unsupported transfer encoding")
            length = integer(self.headers_in.get("Content-Length", "0"), "body size", 0, 16384)
            raw = self.rfile.read(length)
            result = json.loads(raw) if raw else {}
            if not isinstance(result, dict):
                raise ValueError("Expected object")
            return result

        def selected_player(self):
            entity_id = db.get_state("spotifyplus_entity")
            if not entity_id:
                raise HomeAssistantError("Select and save your SpotifyPlus player in Settings first.")
            return entity_id

        def route(self, method):
            url = urlsplit(self.path)
            path = url.path
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if method == "GET" and path in static:
                name, mime = static[path]
                body = (STATIC / name).read_bytes()
                self.respond_headers(200, mime, len(body))
                self.wfile.write(body)
                return
            if path == "/health" and method == "GET":
                self.send_json(200, {"status": "ok"})
                return
            if path == "/api/session" and method == "GET":
                self.send_json(200, {"ingress": ingress,
                                     "volume": worker.settings.volume_options,
                                     "home_assistant_available": bool(home_assistant and home_assistant.available)})
                return
            if not self.authorized():
                return
            params = parse_qs(url.query, max_num_fields=20)

            def param(name, default):
                values = params.get(name, [default])
                if len(values) != 1:
                    raise ValueError("Duplicate parameter")
                return values[0]

            if path == "/api/status" and method == "GET":
                self.send_json(200, {**db.status(), "running": worker.running,
                                     "pending": worker.pending, "phase": worker.phase, "version": "0.2.3",
                                     "spotify_configured": bool(worker.settings.spotify_client_id),
                                     "spotify_market": worker.settings.spotify_market,
                                     "enrichment_enabled": worker.settings.enrich_batch_size > 0,
                                     "enrichment_pending": worker.enrichment_pending})
            elif path == "/api/players" and method == "GET":
                players = home_assistant.players() if home_assistant and home_assistant.available else []
                selected = db.get_state("spotifyplus_entity")
                self.send_json(200, {"players": players, "selected_entity": selected})
            elif path == "/api/player" and method == "POST":
                body = self.body()
                if not home_assistant:
                    raise HomeAssistantError("Home Assistant playback is unavailable")
                entity_id = body.get("entity_id")
                if not isinstance(entity_id, str):
                    raise ValueError("Expected entity ID")
                home_assistant.validate_player(entity_id)
                db.set_state("spotifyplus_entity", entity_id)
                self.send_json(200, {"saved": True})
            elif path == "/api/play" and method == "POST":
                body = self.body()
                if not home_assistant:
                    raise HomeAssistantError("Home Assistant playback is unavailable")
                album = db.album(integer(body.get("album_id"), "album_id", 1, 2**63-1))
                if not album:
                    raise LookupError("Album not found")
                if album["spotify_status"] != "confirmed" or not album["spotify_uri"]:
                    self.send_json(409, {"error": "Confirm this album's Spotify link before playback"})
                    return
                if body.get("spotify_uri") != album["spotify_uri"]:
                    self.send_json(409, {"error": "The album link changed. Refresh the recommendation before playback"})
                    return
                home_assistant.play(self.selected_player(), album["spotify_uri"])
                self.send_json(200, {"requested": True})
            elif path == "/api/player/control" and method == "POST":
                body = self.body()
                if not home_assistant:
                    raise HomeAssistantError("Home Assistant playback is unavailable")
                action = body.get("action")
                if not isinstance(action, str):
                    raise ValueError("Expected action")
                home_assistant.control(self.selected_player(), action, body.get("volume"))
                self.send_json(200, {"requested": True})
            elif path == "/api/genres" and method == "GET":
                self.send_json(200, db.genres(integer(param("limit", 200), "limit", 1, 500)))
            elif path == "/api/albums" and method == "GET":
                query = param("q", "")
                if len(query) > 200:
                    raise ValueError("Search too long")
                self.send_json(200, {"albums": db.albums(
                    integer(param("limit", 30), "limit", 1, 100), query)})
            elif path == "/api/recommend" and method == "GET":
                playable = param("playable_only", "true")
                genre = param("genre", "")
                if playable not in ("true", "false") or len(genre) > 100:
                    raise ValueError("Invalid filter")
                album = db.recommend(
                    integer(param("min_years_unheard", 3), "min_years_unheard", 0, 100),
                    integer(param("min_total_scrobbles", 10), "min_total_scrobbles", 1, 10000000),
                    genre, playable == "true")
                self.send_json(200, {"album": album})
            elif path == "/api/sync" and method == "POST":
                self.body()
                accepted = worker.request_sync()
                self.send_json(202 if accepted else 409, {"accepted": accepted})
            elif path == "/api/enrich" and method == "POST":
                self.body()
                accepted = worker.request_enrichment()
                self.send_json(202 if accepted else 409, {"accepted": accepted})
            elif path == "/api/sync/reset" and method == "POST":
                self.body()
                accepted = worker.reset_checkpoint()
                self.send_json(202 if accepted else 409, {"accepted": accepted})
            elif path.startswith("/api/albums/") and method == "POST":
                album_id = integer(path.removeprefix("/api/albums/"), "album id", 1, 2**63-1)
                body = self.body()
                uri = body["spotify_uri"]
                tags = body.get("tags")
                if not isinstance(uri, str) or len(uri) > 2048:
                    raise ValueError("Invalid URI")
                if tags is not None and (not isinstance(tags, list) or len(tags) > 50 or
                        any(not isinstance(t, str) or len(t) > 100 for t in tags)):
                    raise ValueError("Invalid tags")
                db.confirm_album(album_id, uri, tags)
                self.send_json(200, {"saved": True})
            elif path == "/api/backup" and method == "GET":
                with tempfile.TemporaryDirectory(dir=data_dir) as folder:
                    backup = Path(folder) / "scrobbles.db"
                    db.backup(backup)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", 'attachment; filename="scrobbles.db"')
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(backup.stat().st_size))
                    self.end_headers()
                    with backup.open("rb") as stream:
                        shutil.copyfileobj(stream, self.wfile)
            else:
                self.send_json(404, {"error": "Endpoint not found"})

    return ThreadingHTTPServer(address, Handler)
