"""HTTP API route handlers for BeatScope server."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .assets import (
    VIDEO_MAX_BYTES,
    AssetError,
    AssetStore,
)
from .composition_store import composition_lock, composition_request, locked_composition_request
from .direction import (
    build_direction_document,
    canonical_direction_bytes,
    canonical_workspace_bytes,
    derive_scenes_from_structure,
    direction_etag,
    migrate_round2_draft,
    validate_direction,
    validate_workspace,
)
from .exports import generate_codex_export, generate_rhythm_csv, generate_rhythm_midi
from .jobs import JobManager
from .media_http import describe_media
from .project import ProjectManager
from .response_relevance import build_response_relevance, canonical_response_relevance_bytes
from .routing import Route, match_route

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
MAX_DIRECTION_BYTES = 8 * 1024 * 1024
MAX_ASSET_BYTES = VIDEO_MAX_BYTES

# Declared once, matched by the tiny router in beatscope.routing. A ':name'
# segment captures one path segment; the table is read in order, and because a
# pattern must match the segment count exactly, no entry can shadow another.
GET_ROUTES: list[Route] = [
    ("GET", ("api", "projects", ":id", "composition"), "_get_composition"),
    ("GET", ("api", "projects", ":id", "export", "composition.zip"), "_get_composition_export"),
    ("GET", ("api", "jobs", ":id"), "_get_job"),
    ("GET", ("api", "projects",), "_get_projects"),
    ("GET", ("api", "projects", ":id"), "_get_project"),
    ("GET", ("api", "projects", ":id", "audio"), "_get_audio"),
    ("GET", ("api", "projects", ":id", "export", "rhythm.mid"), "_get_midi"),
    ("GET", ("api", "projects", ":id", "export", "rhythm.csv"), "_get_csv"),
    ("GET", ("api", "projects", ":id", "export", "codex.zip"), "_get_codex_export"),
    ("GET", ("api", "projects", ":id", "response-relevance"), "_get_response_relevance"),
    ("GET", ("api", "projects", ":id", "direction"), "_get_direction"),
    ("GET", ("api", "projects", ":id", "workspace"), "_get_workspace"),
    ("GET", ("api", "projects", ":id", "assets"), "_get_assets"),
    ("GET", ("api", "projects", ":id", "assets", ":asset_id"), "_get_asset"),
]

DELETE_ROUTES: list[Route] = [
    ("DELETE", ("api", "jobs", ":id"), "_delete_job"),
    ("DELETE", ("api", "projects", ":id", "assets", ":asset_id"), "_delete_asset"),
]


class WebApi:
    """Handles REST API routing and responses."""

    def __init__(self, project_manager: ProjectManager | None = None, job_manager: JobManager | None = None):
        self.project_manager = project_manager or ProjectManager()
        self.job_manager = job_manager or JobManager(self.project_manager)

    def handle_get(self, path: str, query: dict[str, list[str]], headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        """Handle GET requests. Returns (status_code, headers_dict, body_bytes)."""
        parts = [p for p in path.strip("/").split("/") if p]
        # A malformed project id is answered before any project route runs; the
        # handlers below may then assume a well-formed id.
        if len(parts) >= 3 and parts[:2] == ["api", "projects"] and (len(parts[2]) != 12 or any(c not in "0123456789abcdef" for c in parts[2])):
            return 404, {"Content-Type": "application/json"}, b'{"error":"Project not found"}'

        handler, params = match_route(GET_ROUTES, "GET", parts)
        if handler is None:
            return 404, {"Content-Type": "text/plain"}, b"Not found"
        return getattr(self, handler)(params, query, headers)

    # --- GET handlers, one per entry in GET_ROUTES --------------------------

    def _get_composition(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        return composition_request(self.project_manager, params["id"])

    def _get_composition_export(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        from .composition_export import composition_archive

        status, version_headers, document_bytes = composition_request(self.project_manager, params["id"])
        if status != 200:
            return status, version_headers, document_bytes
        expected = headers.get("If-Match") or headers.get("if-match")
        if expected and expected != version_headers["ETag"]:
            return 409, version_headers, b'{"error":"composition/export-version-changed"}'
        # composition_request above already answered 404 for an unknown project,
        # so the store exists here; without this guard a missing store would
        # surface as an AttributeError inside composition_archive and escape as
        # a 500.
        store = self._asset_store(params["id"])
        if store is None:
            return 404, {"Content-Type": "application/json"}, b'{"error":"Project not found"}'
        try:
            archive = composition_archive(json.loads(document_bytes), self.project_manager.get_project_rhythm(params["id"]), store)
        except (ValueError, OSError) as exc:
            return 422, {"Content-Type": "application/json"}, json.dumps({"error": "composition/export-failed", "message": str(exc)}).encode()
        return 200, {"Content-Type": "application/zip", "Content-Disposition": 'attachment; filename="beatscope-composition.zip"'}, archive

    def _get_job(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        job = self.job_manager.get_job(params["id"])
        if not job:
            return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Job not found"}).encode()
        return 200, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(job.to_dict()).encode()

    def _get_projects(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        projects = self.project_manager.list_projects()
        return 200, {"Content-Type": "application/json; charset=utf-8"}, json.dumps({"projects": projects}).encode()

    def _get_project(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        project_id = params["id"]
        rhythm = self.project_manager.get_project_rhythm(project_id)
        if not rhythm:
            return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Project not found"}).encode()
        return 200, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(rhythm).encode()

    def _get_audio(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        # The resolver owns the source.audio fallback, so a missing answer here
        # means the project has no audio at all.
        audio_path = self.project_manager.get_project_audio_path(params["id"])
        if not audio_path:
            return 404, {"Content-Type": "text/plain"}, b"Audio file not found"
        return self._serve_file_range(audio_path, headers.get("Range") or headers.get("range"))

    def _get_midi(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        project_id = params["id"]
        rhythm = self.project_manager.get_project_rhythm(project_id)
        if not rhythm:
            return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Project not found"}).encode()
        subdivision = int(query.get("subdivision", [16])[0])
        midi_bytes = generate_rhythm_midi(rhythm, subdivision=subdivision)
        return 200, {"Content-Type": "audio/midi", "Content-Disposition": f'attachment; filename="{project_id}.rhythm.mid"'}, midi_bytes

    def _get_csv(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        project_id = params["id"]
        rhythm = self.project_manager.get_project_rhythm(project_id)
        if not rhythm:
            return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Project not found"}).encode()
        subdivision = int(query.get("subdivision", [16])[0])
        csv_str = generate_rhythm_csv(rhythm, subdivision=subdivision)
        return 200, {"Content-Type": "text/csv; charset=utf-8", "Content-Disposition": f'attachment; filename="{project_id}.rhythm.csv"'}, csv_str.encode("utf-8")

    def _get_codex_export(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        project_id = params["id"]
        rhythm = self.project_manager.get_project_rhythm(project_id)
        if not rhythm:
            return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Project not found"}).encode()
        # The handoff carries timing facts only; the visual layer is the
        # consumer decision, so nothing is compiled into the package here.
        archive = generate_codex_export(rhythm)
        return 200, {
            "Content-Type": "application/zip",
            "Content-Disposition": f'attachment; filename="{project_id}.beatscope-codex.zip"',
        }, archive

    def _get_response_relevance(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        return self._serve_response_relevance(params["id"], headers)

    def _get_direction(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        return self._serve_direction(params["id"], headers)

    def _get_workspace(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        return self._serve_workspace(params["id"], headers)

    def _get_assets(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        store = self._asset_store(params["id"])
        if store is None:
            return 404, {"Content-Type": "application/json"}, b'{"error":"Project not found"}'
        return 200, {"Content-Type": "application/json; charset=utf-8"}, json.dumps({
            "assets": store.manifest(),
            "budget_bytes": 500 * 1024 * 1024,
            "used_bytes": store.total_bytes(),
        }).encode("utf-8")

    def _get_asset(self, params, query, headers) -> tuple[int, dict[str, str], bytes]:
        return self._serve_asset(params["id"], params["asset_id"])

    def handle_delete(self, path: str, query: dict[str, list[str]] | None = None) -> tuple[int, dict[str, str], bytes]:
        """Handle DELETE /api/jobs/<job_id> and project asset deletion."""
        parts = [p for p in path.strip("/").split("/") if p]
        handler, params = match_route(DELETE_ROUTES, "DELETE", parts)
        if handler is None:
            return 404, {"Content-Type": "text/plain"}, b"Not found"
        return getattr(self, handler)(params, query or {})

    def _delete_job(self, params, query) -> tuple[int, dict[str, str], bytes]:
        cancelled = self.job_manager.cancel_job(params["id"])
        if cancelled:
            return 200, {"Content-Type": "application/json"}, json.dumps({"status": "cancelled"}).encode()
        return 400, {"Content-Type": "application/json"}, json.dumps({"error": "Could not cancel job"}).encode()

    def _delete_asset(self, params, query) -> tuple[int, dict[str, str], bytes]:
        return self.handle_delete_asset(f"/api/projects/{params['id']}/assets/{params['asset_id']}", query)

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

    def _serve_response_relevance(
        self, project_id: str, headers: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        """Serve optional ranking evidence without modifying Rhythm IR."""
        rhythm = self.project_manager.get_project_rhythm(project_id)
        if rhythm is None:
            return 404, {"Content-Type": "application/json"}, json.dumps({"error": "Project not found"}).encode()
        try:
            document = build_response_relevance(rhythm)
            body = canonical_response_relevance_bytes(document)
        except (KeyError, TypeError, ValueError):
            return 422, {"Content-Type": "application/json"}, json.dumps({
                "error": "Response relevance is unavailable for this project"
            }).encode()
        etag = f'"{hashlib.sha256(body).hexdigest()}"'
        response_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "ETag": etag,
        }
        if_none_match = headers.get("If-None-Match") or headers.get("if-none-match")
        if if_none_match:
            candidates = {candidate.strip() for candidate in if_none_match.split(",")}
            if etag in candidates or "*" in candidates:
                return 304, response_headers, b""
        return 200, response_headers, body

    def _direction_bytes_or_error(
        self, project_id: str
    ) -> tuple[bytes | None, str | None, tuple[int, dict[str, str], bytes] | None]:
        """Stored direction bytes, deriving + persisting them when absent.

        The three slots are independent - ``(body, derived_mode, error_response)``
        - so callers check the error first and then use the other two without
        casting. Exactly one of ``body`` and ``error_response`` is set, and
        ``derived_mode`` is only meaningful alongside a body.
        """
        if len(project_id) != 12 or any(ch not in "0123456789abcdef" for ch in project_id):
            return None, None, (404, {"Content-Type": "application/json"}, b'{"error":"Project not found"}')
        rhythm = self.project_manager.get_project_rhythm(project_id)
        if rhythm is None:
            return None, None, (
                404,
                {"Content-Type": "application/json"},
                json.dumps({"error": "Project not found"}).encode(),
            )
        body = self.project_manager.get_project_direction_bytes(project_id)
        if body is None:
            try:
                scenes, mode = derive_scenes_from_structure(rhythm)
                document = build_direction_document(rhythm, scenes)
                body = canonical_direction_bytes(document)
            except (KeyError, TypeError, ValueError) as exc:
                return None, None, (
                    422,
                    {"Content-Type": "application/json"},
                    json.dumps({
                        "error": "direction/derive-failed",
                        "message": str(exc),
                    }).encode(),
                )
            self.project_manager.save_project_direction_bytes(project_id, body)
            return body, mode, None
        return body, None, None

    def _serve_direction(
        self, project_id: str, headers: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        """Serve the canonical project direction document.

        The body is the stored canonical byte-for-byte document; a first
        GET derives the initial scenes from the Rhythm IR, persists the
        sidecar and reports the derivation mode in ``X-Direction-Derived``.
        The ETag is the SHA-256 of the exact bytes so ``If-None-Match``
        answers 304. A stored document that no longer validates still
        carries its ETag so clients can reconcile via If-Match PUT.
        """
        body, derived_mode, error = self._direction_bytes_or_error(project_id)
        if error is not None:
            return error
        assert body is not None

        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            document = None
        stored_errors: list[str] = []
        if not isinstance(document, dict):
            stored_errors.append("direction/schema: stored direction sidecar is not a JSON object")
        else:
            migrated = migrate_round2_draft(document)
            stored_errors, _ = validate_direction(migrated)
            if not stored_errors and migrated != document:
                body = canonical_direction_bytes(migrated)
                self.project_manager.save_project_direction_bytes(project_id, body)
                document = migrated

        etag = direction_etag(body)
        response_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "ETag": etag,
        }
        if derived_mode:
            response_headers["X-Direction-Derived"] = derived_mode
        if stored_errors:
            response_headers["X-Direction-Invalid"] = "1"
            return 422, response_headers, json.dumps({
                "error": "direction/invalid",
                "errors": stored_errors,
            }).encode("utf-8")

        if_none_match = headers.get("If-None-Match") or headers.get("if-none-match")
        if if_none_match:
            candidates = {candidate.strip() for candidate in if_none_match.split(",")}
            if etag in candidates or "*" in candidates:
                return 304, response_headers, b""
        return 200, response_headers, body

    def handle_put_direction(
        self, path: str, body: bytes, headers: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        """PUT /api/projects/<id>/direction with optimistic concurrency.

        Requires ``If-Match`` carrying the ETag from a prior GET/PUT; a
        stale or missing precondition refuses the write (412/428) instead
        of clobbering the other editor's state. Invalid documents are
        refused with the stable ``direction/invalid`` code and the full
        error list; accepted bodies are re-canonicalized so the stored
        bytes (and therefore the ETag) are deterministic.
        """
        parts = [p for p in path.strip("/").split("/") if p]
        if not (len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "direction"):
            return 404, {"Content-Type": "text/plain"}, b"Not found"
        project_id = parts[2]

        if len(body) > MAX_DIRECTION_BYTES:
            return 413, {"Content-Type": "application/json"}, json.dumps({
                "error": "direction/too-large",
                "message": f"direction document exceeds {MAX_DIRECTION_BYTES} bytes",
            }).encode()

        current_bytes, _, error = self._direction_bytes_or_error(project_id)
        if error is not None:
            return error
        current_etag = direction_etag(current_bytes or b"")

        if_match = headers.get("If-Match") or headers.get("if-match")
        if not if_match:
            return 428, {"Content-Type": "application/json"}, json.dumps({
                "error": "direction/precondition-required",
                "message": "PUT direction requires an If-Match ETag from a prior GET or PUT",
                "current_etag": current_etag,
            }).encode()
        candidates = {candidate.strip() for candidate in if_match.split(",")}
        if current_etag not in candidates and "*" not in candidates:
            try:
                current_document = json.loads((current_bytes or b"{}").decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                current_document = None
            return 409, {"Content-Type": "application/json"}, json.dumps({
                "error": "direction_conflict",
                "message": "the direction document changed since your last read",
                "current_etag": current_etag,
                "current_document": current_document,
            }).encode()

        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            return 422, {"Content-Type": "application/json"}, json.dumps({
                "error": "direction/invalid",
                "errors": [f"direction/schema: body is not valid JSON ({exc})"],
            }).encode()
        if not isinstance(document, dict):
            return 422, {"Content-Type": "application/json"}, json.dumps({
                "error": "direction/invalid",
                "errors": ["direction/schema: document must be an object"],
            }).encode()
        errors, _ = validate_direction(document, self._asset_ids(project_id))
        rhythm = self.project_manager.get_project_rhythm(project_id)
        if document.get("project_id") != project_id:
            errors.append("direction/project-mismatch: project_id does not match route")
        if rhythm and document.get("source_rhythm_sha256") != rhythm.get("source", {}).get("sha256"):
            errors.append("direction/source-mismatch: source_rhythm_sha256 does not match project")
        if errors:
            return 422, {"Content-Type": "application/json"}, json.dumps({
                "error": "direction/invalid",
                "errors": errors,
            }).encode("utf-8")

        canonical = canonical_direction_bytes(document)
        self.project_manager.save_project_direction_bytes(project_id, canonical)
        return 200, {"Content-Type": "application/json"}, json.dumps({
            "status": "ok",
            "etag": direction_etag(canonical),
        }).encode()

    def handle_put_composition(self, path: str, body: bytes, headers: dict[str, str]):
        parts = path.strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["api", "projects"] or parts[3] != "composition":
            return 404, {"Content-Type": "text/plain"}, b"Not found"
        return locked_composition_request(
            self.project_manager, parts[2], body,
            headers.get("If-Match") or headers.get("if-match"), self._asset_ids(parts[2]),
        )

    def _asset_ids(self, project_id: str) -> set[str] | None:
        """Manifest asset ids for reference validation, or None when the
        project itself is unknown (validation is skipped in that case)."""
        store = self._asset_store(project_id)
        if store is None:
            return None
        return {entry["asset_id"] for entry in store.manifest()}

    def _asset_store(self, project_id: str) -> AssetStore | None:
        """Asset store for an existing project; None when the route is unknown."""
        if len(project_id) != 12 or any(ch not in "0123456789abcdef" for ch in project_id):
            return None
        if self.project_manager.get_project_rhythm(project_id) is None:
            return None
        return AssetStore(self.project_manager.get_project_dir(project_id), project_id)

    def _serve_asset(self, project_id: str, asset_id: str) -> tuple[int, dict[str, str], bytes]:
        store = self._asset_store(project_id)
        if store is None:
            return 404, {"Content-Type": "application/json"}, b'{"error":"Project not found"}'
        found = store.get(asset_id)
        if found is None:
            return 404, {"Content-Type": "application/json"}, b'{"error":"Asset not found"}'
        mime, data = found
        return 200, {
            "Content-Type": mime,
            "Cache-Control": "private, max-age=31536000, immutable",
        }, data

    def handle_post_assets(
        self, path: str, body: bytes, headers: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        """POST /api/projects/<id>/assets — raw bytes, decoded-type validated."""
        parts = [p for p in path.strip("/").split("/") if p]
        if not (len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "assets"):
            return 404, {"Content-Type": "text/plain"}, b"Not found"
        project_id = parts[2]
        if len(body) > MAX_ASSET_BYTES:
            return 413, {"Content-Type": "application/json"}, json.dumps({
                "error": "asset/too-large",
                "message": f"asset exceeds {MAX_ASSET_BYTES} bytes",
            }).encode()
        store = self._asset_store(project_id)
        if store is None:
            return 404, {"Content-Type": "application/json"}, b'{"error":"Project not found"}'
        raw_name = headers.get("X-Filename") or headers.get("x-filename") or "asset"
        from urllib.parse import unquote

        display_name = Path(unquote(raw_name)).name
        try:
            entry = store.add(display_name, body)
        except AssetError as exc:
            status = 413 if exc.code in ("asset/too-large", "asset/budget") else 422
            return status, {"Content-Type": "application/json"}, json.dumps({
                "error": exc.code,
                "message": str(exc),
            }).encode("utf-8")
        return 201, {"Content-Type": "application/json; charset=utf-8"}, json.dumps({"asset": entry}).encode("utf-8")

    def handle_delete_asset(
        self, path: str, query: dict[str, list[str]]
    ) -> tuple[int, dict[str, str], bytes]:
        with composition_lock():
            return self._delete_asset_locked(path, query)

    def _delete_asset_locked(
        self, path: str, query: dict[str, list[str]]
    ) -> tuple[int, dict[str, str], bytes]:
        """DELETE /api/projects/<id>/assets/<asset_id>[?confirm=1].

        Deleting an in-use asset requires explicit confirmation and reports
        the exact scene/layer references so the client can convert them to
        missing-asset placeholders in one undoable transaction (§6.2).
        """
        parts = [p for p in path.strip("/").split("/") if p]
        if not (len(parts) == 5 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "assets"):
            return 404, {"Content-Type": "text/plain"}, b"Not found"
        store = self._asset_store(parts[2])
        if store is None:
            return 404, {"Content-Type": "application/json"}, b'{"error":"Project not found"}'
        asset_id = parts[4]
        if not store.get(asset_id):
            return 404, {"Content-Type": "application/json"}, b'{"error":"Asset not found"}'
        direction = None
        body = self.project_manager.get_project_direction_bytes(parts[2])
        if body is not None:
            try:
                direction = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                direction = None
        in_use = AssetStore.referenced_by(direction, asset_id)
        composition_path = self.project_manager.get_project_dir(parts[2]) / "composition.json"
        if composition_path.exists():
            from .composition import MAX_COMPOSITION_BYTES, validate_composition

            try:
                if composition_path.stat().st_size > MAX_COMPOSITION_BYTES:
                    raise ValueError("composition too large")
                composition = json.loads(composition_path.read_bytes())
                if validate_composition(composition):
                    raise ValueError("invalid composition")
                in_use.extend("composition/" + obj["id"] for obj in composition["objects"] if obj["asset_id"] == asset_id)
            except (ValueError, UnicodeError):
                return 409, {"Content-Type": "application/json"}, b'{"error":"asset/composition-unreadable"}'
        confirm = (query.get("confirm", ["0"])[0] or "0") not in ("0", "false", "")
        if in_use and not confirm:
            return 409, {"Content-Type": "application/json"}, json.dumps({
                "error": "asset/in-use",
                "message": "this asset is referenced by the direction document",
                "in_use": in_use,
            }).encode("utf-8")
        store.delete(asset_id)
        return 200, {"Content-Type": "application/json"}, json.dumps({"deleted": True, "in_use": in_use}).encode("utf-8")

    def _workspace_bytes(self, project_id: str) -> bytes | None:
        if len(project_id) != 12 or any(ch not in "0123456789abcdef" for ch in project_id):
            return None
        rhythm = self.project_manager.get_project_rhythm(project_id)
        if rhythm is None:
            return None
        body = self.project_manager.get_project_workspace_bytes(project_id)
        if body is None:
            document = {
                "schema": "beathi-workspace-1",
                "version": "0.12.0",
                "project_id": project_id,
                "source_rhythm_sha256": rhythm.get("source", {}).get("sha256", ""),
                "layout": {"boards": {}},
                "camera": {"x": 0, "y": 0, "zoom": 1},
                "selection": {"sceneId": None, "layerId": None, "responseId": None},
                "panels": {"dockOpen": True, "inspectorOpen": True, "packageOpen": False},
            }
            body = canonical_workspace_bytes(document)
            self.project_manager.save_project_workspace_bytes(project_id, body)
        return body

    def _serve_workspace(self, project_id: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        body = self._workspace_bytes(project_id)
        if body is None:
            return 404, {"Content-Type": "application/json"}, b'{"error":"Project not found"}'
        etag = direction_etag(body)
        response_headers = {"Content-Type": "application/json; charset=utf-8", "ETag": etag}
        if_none_match = headers.get("If-None-Match") or headers.get("if-none-match")
        if if_none_match and (etag in {v.strip() for v in if_none_match.split(",")} or "*" in if_none_match):
            return 304, response_headers, b""
        return 200, response_headers, body

    def handle_put_workspace(self, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        parts = [p for p in path.strip("/").split("/") if p]
        if not (len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "workspace"):
            return 404, {"Content-Type": "text/plain"}, b"Not found"
        project_id = parts[2]
        current = self._workspace_bytes(project_id)
        if current is None:
            return 404, {"Content-Type": "application/json"}, b'{"error":"Project not found"}'
        current_etag = direction_etag(current)
        if_match = headers.get("If-Match") or headers.get("if-match")
        if not if_match:
            return 428, {"Content-Type": "application/json"}, json.dumps({
                "error": "workspace/precondition-required", "current_etag": current_etag,
            }).encode()
        if current_etag not in {v.strip() for v in if_match.split(",")} and "*" not in if_match:
            return 409, {"Content-Type": "application/json"}, json.dumps({
                "error": "workspace_conflict", "current_etag": current_etag,
            }).encode()
        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            return 422, {"Content-Type": "application/json"}, json.dumps({
                "error": "workspace/invalid", "errors": [f"workspace/schema: invalid JSON ({exc})"],
            }).encode()
        errors = validate_workspace(document)
        rhythm = self.project_manager.get_project_rhythm(project_id)
        if isinstance(document, dict) and document.get("project_id") != project_id:
            errors.append("workspace/project-mismatch: project_id does not match route")
        if isinstance(document, dict) and rhythm and document.get("source_rhythm_sha256") != rhythm.get("source", {}).get("sha256"):
            errors.append("workspace/source-mismatch: source_rhythm_sha256 does not match project")
        if errors:
            return 422, {"Content-Type": "application/json"}, json.dumps({
                "error": "workspace/invalid", "errors": errors,
            }).encode()
        canonical = canonical_workspace_bytes(document)
        self.project_manager.save_project_workspace_bytes(project_id, canonical)
        return 200, {"Content-Type": "application/json"}, json.dumps({
            "status": "ok", "etag": direction_etag(canonical),
        }).encode()

    def _serve_file_range(self, file_path: Path, range_header: str | None) -> tuple[int, dict[str, str], bytes]:
        """Byte-returning adapter for in-process callers; HTTP streams media."""
        status, headers, start, length = describe_media(file_path, range_header)
        with file_path.open("rb") as source:
            source.seek(start)
            return status, headers, source.read(length)
