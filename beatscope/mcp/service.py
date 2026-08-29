"""Protocol-independent BeatScope workflows (plan section 20).

Everything here works without an MCP connection so it can be unit-tested
directly; ``server.py`` only adapts between protocol and service. Queries
that need runtime semantics (position, phases, energy, onset impulse) go
through ``RuntimeBridge`` to the shared JavaScript runtime - they are never
recomputed in Python (plan section 19.1).
"""
from __future__ import annotations

import bisect
import json
import sys
from typing import Any

from ..project import ProjectManager, content_hash
from ..schema import validate_rhythm_v4
from .errors import ProjectNotFound, RuntimeUnavailable
from .formatting import full_or_truncated, paginate, project_summary, summary_line, timing_view
from .models import EventsInput, GetProjectInput, ListProjectsInput
from .paths import PathPolicy
from .runtime_bridge import file_fingerprint

RESOURCE_BASE = "beatscope://projects"

# Cue types the events tool understands; kept beside the models for slicing.
CUE_TYPE_ORDER = ("accent", "impact", "scale", "flow", "flash", "bloom")


class BeatScopeService:
    def __init__(
        self,
        projects: ProjectManager,
        paths: PathPolicy,
        runtime: Any | None = None,
        max_response_chars: int = 25000,
    ) -> None:
        self.projects = projects
        self.paths = paths
        self.runtime = runtime
        self.max_response_chars = max(1000, max_response_chars)

    # ------------------------------------------------------------- loading

    def _rhythm_path(self, project_id: str):
        from pathlib import Path

        return self.projects.projects_dir / project_id[:12] / "rhythm.json"

    def load_validated_rhythm(self, project_id: str) -> dict[str, Any]:
        """Read through ProjectManager so stored v3 projects migrate on load."""
        if not self._rhythm_path(project_id).is_file():
            raise ProjectNotFound(
                f"Project {project_id} does not exist. Run beatscope_list_projects "
                "to see available projects, or beatscope_analyze_audio to create one."
            )
        try:
            rhythm = self.projects.get_project_rhythm(project_id)
        except (OSError, ValueError, TypeError) as exc:
            raise ProjectNotFound(
                f"Stored project {project_id} cannot be read as a Rhythm Project: "
                f"{exc}. Re-run beatscope_analyze_audio to regenerate it."
            ) from None
        if rhythm is None:
            raise ProjectNotFound(f"Project {project_id} does not exist.")
        errors = validate_rhythm_v4(rhythm)
        if errors:
            raise ProjectNotFound(
                f"Stored project {project_id} fails schema v4 validation: " + "; ".join(errors[:5])
            )
        return rhythm

    # --------------------------------------------------------------- tools

    def list_projects(self, request: ListProjectsInput) -> dict[str, Any]:
        entries = []
        for meta in self.projects.list_projects():
            project_id = str(meta.get("project_id") or "")
            rhythm_file = self._rhythm_path(project_id)
            if not project_id or not rhythm_file.is_file():
                print(f"beatscope-mcp: skipping cache entry without rhythm.json: {meta}", file=sys.stderr)
                continue
            try:
                rhythm = json.loads(rhythm_file.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                print(f"beatscope-mcp: unreadable rhythm.json for {project_id}: {exc}", file=sys.stderr)
                continue
            entries.append((project_id, rhythm, str(rhythm.get("analysis", {}).get("created_at") or "")))

        query = (request.query or "").lower()
        summaries = []
        for project_id, rhythm, created_at in entries:
            summary = project_summary(project_id, rhythm)
            if request.backend and summary["backend"] != request.backend:
                continue
            if query and query not in summary["display_name"].lower() and query not in project_id:
                continue
            summaries.append((created_at, summary))

        summaries.sort(key=lambda item: item[0], reverse=True)
        page, meta = paginate([item[1] for item in summaries], request.limit, request.offset)
        head = page[0] if page else None
        return {
            "ok": True,
            "summary": (
                f"{meta['total']} project(s)"
                + (f"; newest: {summary_line(head)}" if head else "")
            ),
            **meta,
            "projects": page,
        }

    def get_project(self, request: GetProjectInput) -> dict[str, Any]:
        rhythm = self.load_validated_rhythm(request.project_id)
        base = project_summary(request.project_id, rhythm)
        line = summary_line(base)
        result: dict[str, Any] = {
            "ok": True,
            "project_id": request.project_id,
            "summary": line,
            "detail": request.detail,
            "truncated": False,
            "resource": None,
            "note": None,
            "data": None,
        }
        if request.detail == "summary":
            result["data"] = base
        elif request.detail == "timing":
            result["data"] = {**base, "timing": timing_view(rhythm)}
        else:
            payload, truncated = full_or_truncated(rhythm, self.max_response_chars)
            if truncated:
                result["truncated"] = True
                result["resource"] = f"{RESOURCE_BASE}/{request.project_id}/rhythm"
                result["note"] = (
                    "The full project exceeds the response character budget, so no data "
                    "is returned here. Read the resource for the complete schema v4 JSON, "
                    "or use beatscope_get_events and beatscope_get_visual_state for "
                    "targeted slices."
                )
            else:
                result["data"] = payload
        return result

    # ---------------------------------------------------- runtime queries

    def _require_runtime(self):
        if self.runtime is None:
            raise RuntimeUnavailable(
                "The JavaScript runtime bridge is not available in this server "
                "instance, so position/energy/impulse queries cannot be served."
            )
        return self.runtime

    async def get_visual_state(self, request) -> dict[str, Any]:
        """Visual state at one instant, computed by the shared runtime."""
        runtime = self._require_runtime()
        self.load_validated_rhythm(request.project_id)  # existence + schema check
        rhythm_path = self._rhythm_path(request.project_id)
        state = await runtime.call(
            "at",
            project=request.project_id,
            path=str(rhythm_path),
            fingerprint=file_fingerprint(rhythm_path),
            time=request.time,
        )
        return {"ok": True, "project_id": request.project_id, **state}

    async def get_events(self, request: EventsInput) -> dict[str, Any]:
        """Events in (start, end] - the runtime's boundary semantics.

        Onsets come from the runtime ``between`` op; beats, cues, and patterns
        are binary-sliced facts in the same half-open window (plan section 16).
        """
        events: list[dict[str, Any]] = []
        rhythm = self.load_validated_rhythm(request.project_id)
        if "onsets" in request.include:
            runtime = self._require_runtime()
            rhythm_path = self._rhythm_path(request.project_id)
            onsets = await runtime.call(
                "between",
                project=request.project_id,
                path=str(rhythm_path),
                fingerprint=file_fingerprint(rhythm_path),
                start=request.start,
                end=request.end,
            )
            events += [{"kind": "onset", **onset} for onset in onsets]

        if "beats" in request.include:
            events += [
                {"kind": "beat", **beat}
                for beat in _time_slice(rhythm.get("beats") or [], request.start, request.end)
            ]
        if "cues" in request.include:
            cues = rhythm.get("cues") or {}
            for cue_type in CUE_TYPE_ORDER:
                if cue_type not in request.cue_types:
                    continue
                events += [
                    {"kind": "cue", "type": cue_type, **cue}
                    for cue in _time_slice(cues.get(cue_type) or [], request.start, request.end)
                ]
        if "patterns" in request.include:
            events += _pattern_events(rhythm, request.start, request.end)

        events.sort(key=lambda event: (float(event.get("time") or 0), event["kind"]))
        page, meta = paginate(events, request.limit, request.offset)
        return {
            "ok": True,
            "project_id": request.project_id,
            "summary": (
                f"{meta['total']} event(s) between {request.start:g} s and {request.end:g} s"
            ),
            "start": request.start,
            "end": request.end,
            "include": sorted(request.include),
            **meta,
            "events": page,
        }


def _time_slice(items: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    """Items with start < time <= end, via bisect (no full scans)."""
    times = [float(item.get("time") or 0) for item in items]
    lo = bisect.bisect_right(times, start)
    hi = bisect.bisect_right(times, end)
    return items[lo:hi]


def _pattern_events(rhythm: dict[str, Any], start: float, end: float) -> list[dict[str, Any]]:
    """Pattern bars whose (start, end) span overlaps the query window.

    Bar spans come from stored downbeat times (facts, not BPM math); the
    final bar extrapolates with the previous bar's length like the runtime.
    """
    bars = (rhythm.get("patterns") or {}).get("bars") or []
    if not bars:
        return []
    starts: dict[int, float] = {}
    for beat in rhythm.get("beats") or []:
        bar = int(beat.get("bar") or 0)
        if bar and bar not in starts:
            starts[bar] = float(beat.get("time") or 0)
    events: list[dict[str, Any]] = []
    for entry in bars:
        bar = int(entry.get("bar") or 0)
        span_start = starts.get(bar)
        if span_start is None:
            continue
        next_start = starts.get(bar + 1)
        if next_start is not None:
            span_end = next_start
        else:
            previous = starts.get(bar - 1)
            span_end = span_start + (span_start - previous) if previous is not None else float("inf")
        if span_start < end and span_end > start:
            events.append({"kind": "pattern", "time": span_start, **entry})
    return events


__all__ = ["BeatScopeService", "RESOURCE_BASE", "content_hash"]
