"""Local HTTP server and REST API for BeatScope."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
from urllib.parse import parse_qs, urlparse

from .analysis import analyze_audio
from .midi import build_midi
from .project import ProjectManager
from .jobs import JobManager
from .web_api import WebApi, MAX_UPLOAD_BYTES
from .exports import generate_rhythm_midi, generate_rhythm_csv, generate_codex_export

ROOT = Path(__file__).parent / "web"
PROJECT_FILE: Path | None = None
PROJECT_MAP: dict | None = None

PROJECT_MANAGER = ProjectManager()
JOB_MANAGER = JobManager(PROJECT_MANAGER)
WEB_API = WebApi(PROJECT_MANAGER, JOB_MANAGER)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, data: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if headers:
            for k, v in headers.items():
                if k.lower() not in ("content-type", "content-length"):
                    self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        route = urlparse(self.path)
        path = route.path
        query = parse_qs(route.query)

        # Legacy /api/project route
        if path == "/api/project":
            if PROJECT_MAP is not None:
                self._send(200, json.dumps(PROJECT_MAP, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            # If a project is loaded in project_manager, return it
            projects = PROJECT_MANAGER.list_projects()
            if projects:
                latest_id = projects[-1].get("project_id")
                rhythm = PROJECT_MANAGER.get_project_rhythm(latest_id)
                if rhythm:
                    self._send(200, json.dumps(rhythm, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                    return
            self._send(404, b"No project configured", "text/plain")
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
                status, resp_headers, body = WEB_API._serve_file_range(target, self.headers.get("Range"))
                ct = resp_headers.get("Content-Type", "audio/wav")
                self._send(status, body, ct, resp_headers)
                return
            # Fallback to latest project audio
            projects = PROJECT_MANAGER.list_projects()
            if projects:
                latest_id = projects[-1].get("project_id")
                audio_path = PROJECT_MANAGER.get_project_audio_path(latest_id)
                if audio_path and audio_path.is_file():
                    status, resp_headers, body = WEB_API._serve_file_range(audio_path, self.headers.get("Range"))
                    ct = resp_headers.get("Content-Type", "audio/wav")
                    self._send(status, body, ct, resp_headers)
                    return
            self._send(404, b"No project configured", "text/plain")
            return

        # Modern REST API routes
        if path.startswith("/api/"):
            headers_dict = {k: v for k, v in self.headers.items()}
            status, resp_headers, body = WEB_API.handle_get(path, query, headers_dict)
            ct = resp_headers.get("Content-Type", "application/json")
            self._send(status, body, ct, resp_headers)
            return

        # Static assets
        clean_path = path.lstrip("/") or "index.html"
        asset_file = ROOT / clean_path
        resolved_asset = asset_file.resolve()
        resolved_root = ROOT.resolve()
        if asset_file.is_file() and (resolved_root in resolved_asset.parents or resolved_asset == resolved_root):
            ext = asset_file.suffix.lower()
            kind_map = {
                ".html": "text/html; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".ico": "image/x-icon",
            }
            kind = kind_map.get(ext, "application/octet-stream")
            self._send(200, asset_file.read_bytes(), kind)
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self) -> None:
        route = urlparse(self.path)
        path = route.path

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
                result = analyze_audio(temp)
                result["source"]["file"] = filename
                self._send(200, json.dumps(result).encode("utf-8"), "application/json; charset=utf-8")
            except Exception as exc:
                self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            finally:
                temp.unlink(missing_ok=True)
            return

        self._send(404, b"Not found", "text/plain")

    def do_DELETE(self) -> None:
        route = urlparse(self.path)
        status, resp_headers, body = WEB_API.handle_delete(route.path)
        self._send(status, body, resp_headers.get("Content-Type", "application/json"))

    def log_message(self, fmt: str, *args: object) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8765, project: str | Path | None = None) -> None:
    global PROJECT_FILE, PROJECT_MAP
    if project:
        PROJECT_FILE = Path(project).resolve()
        PROJECT_MAP = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"BeatScope running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
