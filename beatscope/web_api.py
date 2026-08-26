"""HTTP API route handlers for BeatScope server."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import parse_qs, urlparse

from .exports import generate_rhythm_midi, generate_rhythm_csv, generate_codex_export
from .jobs import JobManager
from .project import ProjectManager


MAX_UPLOAD_BYTES = 500 * 1024 * 1024


class WebApi:
    """Handles REST API routing and responses."""

    def __init__(self, project_manager: ProjectManager | None = None, job_manager: JobManager | None = None):
        self.project_manager = project_manager or ProjectManager()
        self.job_manager = job_manager or JobManager(self.project_manager)

    def handle_get(self, path: str, query: dict[str, list[str]], headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        """Handle GET requests. Returns (status_code, headers_dict, body_bytes)."""
        parts = [p for p in path.strip("/").split("/") if p]

        # 1. GET /api/jobs/<job_id>
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "jobs":
            job_id = parts[2]
            job = self.job_manager.get_job(job_id)
            if not job:
                return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Job not found"}).encode()
            return 200, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(job.to_dict()).encode()

        # 2. GET /api/projects
        if len(parts) == 2 and parts[0] == "api" and parts[1] == "projects":
            projects = self.project_manager.list_projects()
            return 200, {"Content-Type": "application/json; charset=utf-8"}, json.dumps({"projects": projects}).encode()

        # 3. GET /api/projects/<id>
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "projects":
            project_id = parts[2]
            rhythm = self.project_manager.get_project_rhythm(project_id)
            if not rhythm:
                return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Project not found"}).encode()
            return 200, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(rhythm).encode()

        # 4. GET /api/projects/<id>/audio
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "audio":
            project_id = parts[2]
            audio_path = self.project_manager.get_project_audio_path(project_id)
            if not audio_path or not audio_path.is_file():
                # Check source.audio inside project dir
                fallback = self.project_manager.get_project_dir(project_id) / "source.audio"
                if fallback.is_file():
                    audio_path = fallback
                else:
                    return 404, {"Content-Type": "text/plain"}, b"Audio file not found"
            return self._serve_file_range(audio_path, headers.get("Range") or headers.get("range"))

        # 5. GET /api/projects/<id>/export/rhythm.mid
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "export" and parts[4] == "rhythm.mid":
            project_id = parts[2]
            rhythm = self.project_manager.get_project_rhythm(project_id)
            if not rhythm:
                return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Project not found"}).encode()
            subdivision = int(query.get("subdivision", [16])[0])
            midi_bytes = generate_rhythm_midi(rhythm, subdivision=subdivision)
            return 200, {"Content-Type": "audio/midi", "Content-Disposition": f'attachment; filename="{project_id}.rhythm.mid"'}, midi_bytes

        # 6. GET /api/projects/<id>/export/rhythm.csv
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "export" and parts[4] == "rhythm.csv":
            project_id = parts[2]
            rhythm = self.project_manager.get_project_rhythm(project_id)
            if not rhythm:
                return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Project not found"}).encode()
            subdivision = int(query.get("subdivision", [16])[0])
            csv_str = generate_rhythm_csv(rhythm, subdivision=subdivision)
            return 200, {"Content-Type": "text/csv; charset=utf-8", "Content-Disposition": f'attachment; filename="{project_id}.rhythm.csv"'}, csv_str.encode("utf-8")

        # 7. GET /api/projects/<id>/export/codex.zip
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "export" and parts[4] == "codex.zip":
            project_id = parts[2]
            rhythm = self.project_manager.get_project_rhythm(project_id)
            if not rhythm:
                return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Project not found"}).encode()
            archive = generate_codex_export(rhythm)
            return 200, {
                "Content-Type": "application/zip",
                "Content-Disposition": f'attachment; filename="{project_id}.beatscope-codex.zip"',
            }, archive

        return 404, {"Content-Type": "text/plain"}, b"Not found"

    def handle_delete(self, path: str) -> tuple[int, dict[str, str], bytes]:
        """Handle DELETE /api/jobs/<job_id> cancellation."""
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "jobs":
            job_id = parts[2]
            cancelled = self.job_manager.cancel_job(job_id)
            if cancelled:
                return 200, {"Content-Type": "application/json"}, json.dumps({"status": "cancelled"}).encode()
            return 400, {"Content-Type": "application/json"}, json.dumps({"error": "Could not cancel job"}).encode()
        return 404, {"Content-Type": "text/plain"}, b"Not found"

    def handle_post_adjustments(self, path: str, body: bytes) -> tuple[int, dict[str, str], bytes]:
        """Handle POST /api/projects/<id>/adjustments."""
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "adjustments":
            project_id = parts[2]
            try:
                adj = json.loads(body.decode("utf-8"))
                self.project_manager.save_adjustments(project_id, adj)
                return 200, {"Content-Type": "application/json"}, json.dumps({"status": "ok"}).encode()
            except Exception as exc:
                return 400, {"Content-Type": "application/json"}, json.dumps({"error": str(exc)}).encode()
        return 404, {"Content-Type": "text/plain"}, b"Not found"

    def _serve_file_range(self, file_path: Path, range_header: str | None) -> tuple[int, dict[str, str], bytes]:
        """Serve media file supporting HTTP 206 Byte Ranges for audio seeking."""
        file_size = file_path.stat().st_size
        content_type = "audio/wav"
        if file_path.suffix.lower() == ".mp3":
            content_type = "audio/mpeg"
        elif file_path.suffix.lower() == ".ogg":
            content_type = "audio/ogg"
        elif file_path.suffix.lower() == ".flac":
            content_type = "audio/flac"

        if not range_header or not range_header.startswith("bytes="):
            return 200, {
                "Content-Type": content_type,
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            }, file_path.read_bytes()

        # Parse range like 'bytes=0-1000' or 'bytes=1000-'
        try:
            byte_range = range_header.split("=")[1].strip()
            parts = byte_range.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
            if start >= file_size or end >= file_size or start > end:
                return 416, {"Content-Range": f"bytes */{file_size}"}, b""

            length = end - start + 1
            with file_path.open("rb") as f:
                f.seek(start)
                chunk = f.read(length)

            return 206, {
                "Content-Type": content_type,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(len(chunk)),
                "Accept-Ranges": "bytes",
            }, chunk
        except Exception:
            return 200, {
                "Content-Type": content_type,
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            }, file_path.read_bytes()
