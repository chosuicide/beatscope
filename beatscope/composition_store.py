"""Atomic single-artwork sidecars; legacy direction documents are never touched."""
from __future__ import annotations

import hashlib
import json
from threading import RLock

from .composition import composition_bytes, new_composition, validate_composition, MAX_COMPOSITION_BYTES
from .project import _atomic_write_bytes

# Serialize the entire compare-and-replace, including lazy creation, across API instances.
_LOCK = RLock()


def composition_request(manager, project_id, body=None, if_match=None, asset_ids=None):
    headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}

    def error(status, code):
        return status, headers, json.dumps({"error": code}).encode()

    if len(project_id) != 12 or any(c not in "0123456789abcdef" for c in project_id):
        return error(404, "composition/project-not-found")
    if body is not None and len(body) > MAX_COMPOSITION_BYTES:
        return error(413, "composition/too-large")
    with _LOCK:
        rhythm = manager.get_project_rhythm(project_id)
        if rhythm is None:
            return error(404, "composition/project-not-found")
        source_hash = rhythm.get("source", {}).get("sha256", "")
        path = manager.get_project_dir(project_id) / "composition.json"
        try:
            if path.exists():
                if path.stat().st_size > MAX_COMPOSITION_BYTES:
                    return error(422, "composition/stored-document-too-large")
                current = path.read_bytes()
                saved = json.loads(current)
                if validate_composition(saved):
                    return error(422, "composition/stored-document-invalid")
                if saved["project_id"] != project_id or saved["source_rhythm_sha256"] != source_hash:
                    return error(409, "composition/source-changed")
            else:
                current = composition_bytes(new_composition(project_id, source_hash, "Untitled composition"))
                _atomic_write_bytes(path, current)
        except (ValueError, UnicodeError):
            return error(422, "composition/stored-document-invalid")
        etag = '"' + hashlib.sha256(current).hexdigest() + '"'
        headers["ETag"] = etag
        if body is None:
            return 200, headers, current
        if not if_match:
            return error(428, "composition/precondition-required")
        # A wildcard cannot protect an editor against overwriting another editor.
        if if_match != etag:
            return 409, headers, json.dumps({"error": "composition/conflict", "current": json.loads(current)}).encode()
        try:
            document = json.loads(body)
            errors = validate_composition(document, asset_ids)
            if errors:
                return error(422, "; ".join(errors))
            if document["project_id"] != project_id or document["source_rhythm_sha256"] != source_hash:
                return error(422, "composition/source-mismatch")
            canonical = composition_bytes(document)
        except (ValueError, UnicodeError, RecursionError):
            return error(422, "composition/invalid-json")
        _atomic_write_bytes(path, canonical)
        headers["ETag"] = '"' + hashlib.sha256(canonical).hexdigest() + '"'
        return 200, headers, canonical
