"""Small authored timing sidecar. Measured rhythm documents are never edited."""
from __future__ import annotations

import hashlib
import json
import math

from .composition_store import composition_lock
from .project import _atomic_write_bytes

MAX_EDIT_PLAN_BYTES = 512 * 1024


def default_edit_plan(rhythm):
    duration = rhythm.get("source", {}).get("duration", 0)
    times = sorted({s["start_time"] for s in rhythm.get("patterns", {}).get("segments", [])
                    if isinstance(s.get("start_time"), (int, float)) and 0 < s["start_time"] < duration})
    return {"schema": "beatscope-edit-plan-1", "source_sha256": rhythm.get("source", {}).get("sha256", ""),
            "duration": duration, "boundaries": [{"id": f"s:{i}", "time": t} for i, t in enumerate(times)],
            "cues": []}


def validate_edit_plan(plan, rhythm):
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)

    if not isinstance(plan, dict) or set(plan) != {"schema", "source_sha256", "duration", "boundaries", "cues"}:
        raise ValueError("edit-plan/schema")
    if plan["schema"] != "beatscope-edit-plan-1":
        raise ValueError("edit-plan/schema")
    expected = default_edit_plan(rhythm)
    duration = expected["duration"]
    if not number(plan["duration"]) or plan["duration"] != duration or plan["source_sha256"] != expected["source_sha256"]:
        raise ValueError("edit-plan/source-changed")
    onsets = rhythm.get("onsets", [])
    for name in ("boundaries", "cues"):
        rows = plan[name]
        if not isinstance(rows, list) or len(rows) > 5000:
            raise ValueError(f"edit-plan/{name}-limit")
        ids, previous = set(), 0
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not 1 <= len(row["id"]) <= 80 or row["id"] in ids:
                raise ValueError(f"edit-plan/{name}-id")
            ids.add(row["id"])
            if name == "boundaries":
                if set(row) != {"id", "time"} or not number(row["time"]) or not previous < row["time"] < duration:
                    raise ValueError("edit-plan/boundary-order")
                previous = row["time"]
            else:
                original = row["id"].startswith("o:") and row["id"][2:].isdigit()
                if original and (int(row["id"][2:]) >= len(onsets) or row["id"] != f'o:{int(row["id"][2:])}'):
                    raise ValueError("edit-plan/unknown-onset")
                if not original and not row["id"].startswith("u:"):
                    raise ValueError("edit-plan/cue-id")
                if set(row) == {"id", "deleted"} and row["deleted"] is True and original:
                    continue
                if set(row) != {"id", "time"} or not number(row["time"]) or not 0 <= row["time"] < duration:
                    raise ValueError("edit-plan/cue-time")
    return plan


def edit_plan_bytes(plan):
    return (json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def load_edit_plan(manager, project_id, rhythm=None):
    rhythm = rhythm if rhythm is not None else manager.get_project_rhythm(project_id)
    if rhythm is None:
        raise FileNotFoundError("edit-plan/project-not-found")
    path = manager.get_project_dir(project_id) / "edit-plan.json"
    if not path.exists():
        return default_edit_plan(rhythm)
    if path.stat().st_size > MAX_EDIT_PLAN_BYTES:
        raise ValueError("edit-plan/stored-document-too-large")
    return validate_edit_plan(json.loads(path.read_bytes()), rhythm)


def edit_plan_request(manager, project_id, body=None, if_match=None):
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}

    def error(status, code):
        return status, headers, json.dumps({"error": code}).encode()

    if len(project_id) != 12 or any(c not in "0123456789abcdef" for c in project_id):
        return error(404, "edit-plan/project-not-found")
    if body is not None and len(body) > MAX_EDIT_PLAN_BYTES:
        return error(413, "edit-plan/too-large")
    with composition_lock():
        try:
            rhythm = manager.get_project_rhythm(project_id)
            current = edit_plan_bytes(load_edit_plan(manager, project_id, rhythm))
            headers["ETag"] = '"' + hashlib.sha256(current).hexdigest() + '"'
            if body is None:
                return 200, headers, current
            if not if_match:
                return error(428, "edit-plan/precondition-required")
            if if_match != headers["ETag"]:
                return error(409, "edit-plan/conflict")
            document = validate_edit_plan(json.loads(body), rhythm)
            canonical = edit_plan_bytes(document)
            _atomic_write_bytes(manager.get_project_dir(project_id) / "edit-plan.json", canonical)
            headers["ETag"] = '"' + hashlib.sha256(canonical).hexdigest() + '"'
            return 200, headers, canonical
        except FileNotFoundError:
            return error(404, "edit-plan/project-not-found")
        except (ValueError, TypeError, UnicodeError) as exc:
            return error(422, str(exc))
