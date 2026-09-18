"""Local HTTP server and REST API for BeatScope."""
from __future__ import annotations

import json
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

from .exports import generate_codex_export, generate_rhythm_csv, generate_rhythm_midi
from .jobs import JobManager
from .media_http import describe_media
from .midi import build_midi
from .pipeline import analyze_track
from .project import ProjectManager
from .response_relevance import build_response_relevance, canonical_response_relevance_bytes
from .schema import load_rhythm_project
from .web_api import MAX_UPLOAD_BYTES, WebApi

ROOT = Path(__file__).parent / "web"
RUNTIME_ROOT = Path(__file__).parent / "runtime"
PROJECT_FILE: Path | None = None
PROJECT_MAP: dict | None = None

PROJECT_MANAGER = ProjectManager()
JOB_MANAGER = JobManager(PROJECT_MANAGER)
WEB_API = WebApi(PROJECT_MANAGER, JOB_MANAGER)

# Deliberately below the managers: mv_jobs imports this module's peers, and
# hoisting it to the top creates an import cycle.
from .mv_jobs import MovieJobs, renderer_tools  # noqa: E402

MOVIE_JOBS = MovieJobs(PROJECT_MANAGER)


class Handler(BaseHTTPRequestHandler):
    def parse_request(self):
        if not super().parse_request():
            return False
        host = urlparse('//' + self.headers.get('Host', '')).hostname
        # BaseHTTPRequestHandler.server is typed as the BaseServer base class,
        # whose server_address is loose; this handler is only ever mounted on a
        # ThreadingHTTPServer, where it is the (host, port) pair we bound.
        bound = cast(ThreadingHTTPServer, self.server).server_address
        allowed = {'localhost', '127.0.0.1', '::1', bound[0]}
        if host and host not in allowed:
            self.send_error(403, "Unrecognized local host")
            return False
        return True

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if origin and origin != 'http://' + self.headers.get("Host", ""):
            self.close_connection = True
            self._send(403, b'{"message":"Cross-origin write refused"}', "application/json")
            return False
        return True

    def _send_media(self, target, extra=None):
        status, headers, start, length = describe_media(target, self.headers.get('Range'))
        headers.update(extra or {})
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command == 'HEAD':
            return
        try:
            with target.open('rb') as source:
                source.seek(start)
                while length:
                    chunk = source.read(min(length, 1024 * 1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    length -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # A media seek or closed tab may abandon the previous request.

    def do_HEAD(self):
        self.do_GET()

    def _send(self, status: int, data: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if headers:
            for k, v in headers.items():
                if k.lower() not in ("content-type", "content-length"):
                    self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def do_GET(self) -> None:
        route = urlparse(self.path)
        path = route.path
        query = parse_qs(route.query)

        if path == "/api/movies/capabilities":
            tools = renderer_tools()
            self._send(200, json.dumps({"available": tools["available"], "message": tools["message"]}).encode(), "application/json")
            return
        if path.startswith("/api/movies/"):
            parts = path.strip("/").split("/")
            job = MOVIE_JOBS.get(parts[2]) if len(parts) == 3 or (len(parts) == 4 and parts[3] == "video") else None
            if not job:
                self._send(404, b'{"message":"Movie not found"}', "application/json")
                return
            if len(parts) == 4 and parts[3] == "video":
                target = MOVIE_JOBS.video(parts[2])
                if not target:
                    self._send(404, b'{"message":"Movie not ready"}', "application/json")
                    return
                headers = {"Content-Type": "video/mp4"}
                if "download" in query:
                    headers["Content-Disposition"] = 'attachment; filename="beathi-music-video.mp4"'
                self._send_media(target, headers)
                return
            self._send(200, json.dumps(job, ensure_ascii=False).encode(), "application/json")
            return

        # Legacy /api/project route
        if path == "/api/project":
            if PROJECT_MAP is not None:
                self._send(200, json.dumps(PROJECT_MAP, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            # If a project is loaded in project_manager, return it
            projects = PROJECT_MANAGER.list_projects()
            if projects:
                latest_id = projects[-1].get("project_id")
                # A project entry without an id is not addressable; fall through
                # to the 404 rather than asking the manager for None.
                rhythm = PROJECT_MANAGER.get_project_rhythm(latest_id) if isinstance(latest_id, str) else None
                if rhythm:
                    self._send(200, json.dumps(rhythm, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                    return
            self._send(404, b"No project configured", "text/plain")
            return

        if path == "/api/project/response-relevance":
            rhythm = PROJECT_MAP
            if rhythm is None:
                projects = PROJECT_MANAGER.list_projects()
                if projects:
                    latest_id = projects[-1].get("project_id")
                    if isinstance(latest_id, str):
                        rhythm = PROJECT_MANAGER.get_project_rhythm(latest_id)
            if rhythm is None:
                self._send(404, b"No project configured", "text/plain")
                return
            try:
                body = canonical_response_relevance_bytes(build_response_relevance(rhythm))
            except (KeyError, TypeError, ValueError):
                self._send(
                    422,
                    b'{"error":"Response relevance is unavailable for this project"}',
                    "application/json",
                )
                return
            self._send(200, body, "application/json; charset=utf-8")
            return

        # Exports for a project supplied directly with `beatscope serve --project`.
        if path.startswith("/api/project/export/"):
            if PROJECT_MAP is None:
                self._send(404, b"No project configured", "text/plain")
                return
            export_name = path.rsplit("/", 1)[-1]
            subdivision = int(query.get("subdivision", [16])[0])
            source_name = Path(PROJECT_MAP.get("source", {}).get("file", "beatscope")).stem
            if export_name == "rhythm.mid":
                self._send(200, generate_rhythm_midi(PROJECT_MAP, subdivision), "audio/midi", {
                    "Content-Disposition": f'attachment; filename="{source_name}.rhythm.mid"'
                })
                return
            if export_name == "rhythm.csv":
                body = generate_rhythm_csv(PROJECT_MAP, subdivision).encode("utf-8")
                self._send(200, body, "text/csv; charset=utf-8", {
                    "Content-Disposition": f'attachment; filename="{source_name}.rhythm.csv"'
                })
                return
            if export_name == "codex.zip":
                self._send(200, generate_codex_export(PROJECT_MAP), "application/zip", {
                    "Content-Disposition": f'attachment; filename="{source_name}.beatscope-codex.zip"'
                })
                return
            self._send(404, b"Export not found", "text/plain")
            return

        if path in ("/api/project/audio", "/api/project/stem"):
            if PROJECT_MAP is not None:
                if path.endswith("/audio"):
                    target = Path(PROJECT_MAP.get("source", {}).get("path", ""))
                else:
                    name = query.get("name", [""])[0]
                    target = Path(PROJECT_MAP.get("analysis", {}).get("separation", {}).get(name, ""))
                if not target.is_file():
                    # check drums_path or sibling
                    drums = Path(PROJECT_MAP.get("source", {}).get("drums_path", ""))
                    if drums.is_file():
                        target = drums
                    else:
                        self._send(404, b"Project media not found", "text/plain")
                        return
                self._send_media(target)
                return
            # Fallback to latest project audio
            projects = PROJECT_MANAGER.list_projects()
            if projects:
                latest_id = projects[-1].get("project_id")
                audio_path = PROJECT_MANAGER.get_project_audio_path(latest_id) if isinstance(latest_id, str) else None
                if audio_path and audio_path.is_file():
                    self._send_media(audio_path)
                    return
            self._send(404, b"No project configured", "text/plain")
            return

        # Modern REST API routes
        if path.startswith("/api/"):
            parts = path.strip('/').split('/')
            if len(parts) == 4 and parts[:2] == ['api', 'projects'] and parts[3] == 'audio':
                valid_id = len(parts[2]) == 12 and all(c in '0123456789abcdef' for c in parts[2])
                target = PROJECT_MANAGER.get_project_audio_path(parts[2]) if valid_id else None
                if target and target.is_file():
                    self._send_media(target)
                    return
            headers_dict = {k: v for k, v in self.headers.items()}
            status, resp_headers, body = WEB_API.handle_get(path, query, headers_dict)
            ct = resp_headers.get("Content-Type", "application/json")
            self._send(status, body, ct, resp_headers)
            return

        # Static assets; /runtime/* maps to the shared JS runtime modules.
        # `/` routes to the Beathi studio build in web/app, the only page.
        if path == "/":
            self._send(302, b"", "text/plain", {"Location": "/app/"})
            return
        clean_path = path.lstrip("/") or "app/index.html"
        if clean_path in ("app", "app/"):
            clean_path = "app/index.html"
        if clean_path.startswith("runtime/"):
            asset_file = RUNTIME_ROOT / clean_path[len("runtime/"):]
            resolved_root = RUNTIME_ROOT.resolve()
        else:
            asset_file = ROOT / clean_path
            resolved_root = ROOT.resolve()
        resolved_asset = asset_file.resolve()
        if asset_file.is_file() and (resolved_root in resolved_asset.parents or resolved_asset == resolved_root):
            ext = asset_file.suffix.lower()
            kind_map = {
                ".html": "text/html; charset=utf-8",
                # .mjs must be a JavaScript MIME or browsers refuse to import
                # the shared template modules (mv-frame/mv-plan/mv-visual).
                ".mjs": "text/javascript; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".webp": "image/webp",
                ".mp4": "video/mp4",
                ".m4a": "audio/mp4",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".ico": "image/x-icon",
                ".woff2": "font/woff2",
                ".woff": "font/woff",
                ".mp3": "audio/mpeg",
            }
            kind = kind_map.get(ext, "application/octet-stream")
            self._send(200, asset_file.read_bytes(), kind)
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self) -> None:
        if not self._same_origin():
            return
        route = urlparse(self.path)
        path = route.path

        if path == "/api/movies":
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self._send(415, b'{"message":"JSON request required"}', "application/json")
                return
            # Kept as the raw header text: this is the only block that needs the
            # declared size, every other route below works with a parsed int.
            declared_size = self.headers.get("Content-Length", "0")
            if not declared_size.isdigit() or not 0 < int(declared_size) <= 1024:
                self._send(400, b'{"message":"Invalid request"}', "application/json")
                return
            try:
                data = json.loads(self.rfile.read(int(declared_size)))
                if not isinstance(data, dict) or not isinstance(data.get("project_id"), str):
                    raise ValueError("project_id required")
                job = MOVIE_JOBS.submit(data["project_id"], seed=data.get("seed"))
                self._send(202, json.dumps(job).encode(), "application/json")
            except RuntimeError as exc:
                self._send(409, json.dumps({"message": str(exc)}).encode(), "application/json")
            except (ValueError, OSError) as exc:
                self._send(422, json.dumps({"message": str(exc)}).encode(), "application/json")
            return
        if path.startswith("/api/movies/") and path.endswith("/cancel"):
            job_id = path.strip("/").split("/")[2]
            ok = MOVIE_JOBS.cancel(job_id)
            self._send(200 if ok else 409, json.dumps({"cancelled": ok}).encode(), "application/json")
            return

        # 1. Modern /api/jobs/analyze
        if path == "/api/jobs/analyze":
            raw_size = self.headers.get("Content-Length")
            if raw_size is None:
                self._send(411, b"Content-Length required", "text/plain")
                return
            try:
                size = int(raw_size)
            except ValueError:
                self._send(400, b"Invalid Content-Length", "text/plain")
                return
            if size <= 0:
                self._send(400, b"Audio upload is empty", "text/plain")
                return
            if size > MAX_UPLOAD_BYTES:
                self._send(413, b"Audio upload is too large", "text/plain")
                return

            raw_fname = self.headers.get("X-Filename", "audio.wav")
            # Decode URL encoded filename if needed
            from urllib.parse import unquote
            filename = Path(unquote(raw_fname)).name
            suffix = Path(filename).suffix[:12] or ".wav"

            temp_handle = tempfile.NamedTemporaryFile(prefix=".beatscope-upload-", suffix=suffix, delete=False)
            temp_path = Path(temp_handle.name)
            try:
                with temp_handle:
                    remaining = size
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("Upload ended before Content-Length")
                        temp_handle.write(chunk)
                        remaining -= len(chunk)

                # Parse optional query parameters for config
                query = parse_qs(route.query)
                subdiv = int(query.get("subdivision", [16])[0])
                config = {"subdivision": subdiv, "separation": "auto"}

                job = JOB_MANAGER.submit_analysis(temp_path, filename, config)
                self._send(200, json.dumps({"job_id": job.id}).encode("utf-8"), "application/json; charset=utf-8")
                return
            except Exception as exc:
                temp_path.unlink(missing_ok=True)
                self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return

        # 2. Modern POST /api/projects/<id>/adjustments
        if path.startswith("/api/projects/") and path.endswith("/adjustments"):
            raw_size = self.headers.get("Content-Length", "0")
            size = int(raw_size) if raw_size.isdigit() else 0
            body = self.rfile.read(size) if size else b"{}"
            status, resp_headers, body_bytes = WEB_API.handle_post_adjustments(path, body)
            self._send(status, body_bytes, resp_headers.get("Content-Type", "application/json"))
            return

        # 2b. POST /api/projects/<id>/assets (raw media bytes, bounded)
        if path.startswith("/api/projects/") and path.endswith("/assets"):
            raw_size = self.headers.get("Content-Length")
            if raw_size is None:
                self._send(411, b"Content-Length required", "text/plain")
                return
            try:
                size = int(raw_size)
            except ValueError:
                self._send(400, b"Invalid Content-Length", "text/plain")
                return
            if size <= 0:
                self._send(400, json.dumps({"error": "asset/empty"}).encode(), "application/json")
                return
            from .web_api import MAX_ASSET_BYTES

            if size > MAX_ASSET_BYTES:
                self._send(413, json.dumps({"error": "asset/too-large"}).encode(), "application/json")
                return
            body = b""
            remaining = size
            while remaining:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    self._send(400, json.dumps({"error": "asset/truncated"}).encode(), "application/json")
                    return
                body += chunk
                remaining -= len(chunk)
            headers_dict = {k: v for k, v in self.headers.items()}
            status, resp_headers, body_bytes = WEB_API.handle_post_assets(path, body, headers_dict)
            self._send(status, body_bytes, resp_headers.get("Content-Type", "application/json"))
            return

        # 3. Legacy /api/midi
        if path == "/api/midi":
            raw_size = self.headers.get("Content-Length")
            try:
                size = int(raw_size or 0)
            except ValueError:
                size = 0
            if size <= 0 or size > MAX_UPLOAD_BYTES:
                self._send(413 if size > MAX_UPLOAD_BYTES else 400, b"Invalid beatmap size", "text/plain")
                return
            try:
                payload = json.loads(self.rfile.read(size))
                kind = parse_qs(route.query).get("kind", ["combined"])[0]
                if kind not in ("drums", "808", "combined"):
                    raise ValueError("invalid MIDI kind")
                self._send(200, build_midi(payload, kind), "audio/midi")
            except Exception as exc:
                self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            return

        # 4. Legacy /api/analyze
        if path == "/api/analyze":
            raw_size = self.headers.get("Content-Length")
            if raw_size is None:
                self._send(411, b"Content-Length required", "text/plain")
                return
            try:
                size = int(raw_size)
            except ValueError:
                self._send(400, b"Invalid Content-Length", "text/plain")
                return
            if size <= 0:
                self._send(400, b"Audio upload is empty", "text/plain")
                return
            if size > MAX_UPLOAD_BYTES:
                self._send(413, b"Audio upload is too large", "text/plain")
                return
            filename = Path(self.headers.get("X-Filename", "audio")).name
            suffix = Path(filename).suffix[:12] or ".audio"
            temp_handle = tempfile.NamedTemporaryFile(prefix=".beatscope-", suffix=suffix, delete=False)
            temp = Path(temp_handle.name)
            try:
                with temp_handle:
                    remaining = size
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("Upload ended before Content-Length")
                        temp_handle.write(chunk)
                        remaining -= len(chunk)
                result = analyze_track(temp, display_name=filename)
                self._send(200, json.dumps(result).encode("utf-8"), "application/json; charset=utf-8")
            except Exception as exc:
                self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            finally:
                temp.unlink(missing_ok=True)
            return

        self._send(404, b"Not found", "text/plain")

    def do_PUT(self) -> None:
        if not self._same_origin():
            return
        route = urlparse(self.path)
        path = route.path
        if path.startswith("/api/projects/") and path.endswith("/composition"):
            from .composition import MAX_COMPOSITION_BYTES

            raw_size = self.headers.get("Content-Length", "")
            if not raw_size.isdigit() or int(raw_size) > MAX_COMPOSITION_BYTES:
                self.close_connection = True
                self._send(413 if raw_size.isdigit() else 400, b'{"error":"composition/body-length"}', "application/json")
                return
            body = self.rfile.read(int(raw_size))
            status, response_headers, response_body = WEB_API.handle_put_composition(path, body, dict(self.headers.items()))
            self._send(status, response_body, "application/json", response_headers)
            return
        if path.startswith("/api/projects/") and (path.endswith("/direction") or path.endswith("/workspace")):
            raw_size = self.headers.get("Content-Length", "0")
            size = int(raw_size) if raw_size.isdigit() else 0
            body = self.rfile.read(size) if size else b""
            headers_dict = {k: v for k, v in self.headers.items()}
            handler = WEB_API.handle_put_workspace if path.endswith("/workspace") else WEB_API.handle_put_direction
            status, resp_headers, body_bytes = handler(path, body, headers_dict)
            self._send(status, body_bytes, resp_headers.get("Content-Type", "application/json"), resp_headers)
            return
        self._send(404, b"Not found", "text/plain")

    def do_DELETE(self) -> None:
        if not self._same_origin():
            return
        route = urlparse(self.path)
        query = parse_qs(route.query)
        status, resp_headers, body = WEB_API.handle_delete(route.path, query)
        self._send(status, body, resp_headers.get("Content-Type", "application/json"))

    def log_message(self, fmt: str, *args: object) -> None:
        return


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    project: str | Path | None = None,
    *,
    open_browser: bool = False,
) -> None:
    global PROJECT_FILE, PROJECT_MAP
    if project:
        PROJECT_FILE = Path(project).resolve()
        PROJECT_MAP = load_rhythm_project(PROJECT_FILE)
    server = ThreadingHTTPServer((host, port), Handler)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}"
    print(f"BeatScope running at {url}")
    if open_browser:
        opener = threading.Timer(0.35, webbrowser.open, args=(url,))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
