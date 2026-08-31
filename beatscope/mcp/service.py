"""Protocol-independent BeatScope workflows (plan section 20).

Everything here works without an MCP connection so it can be unit-tested
directly; ``server.py`` only adapts between protocol and service. Queries
that need runtime semantics (position, phases, energy, onset impulse) go
through ``RuntimeBridge`` to the shared JavaScript runtime - they are never
recomputed in Python (plan section 19.1).
"""
from __future__ import annotations

import bisect
import hashlib
import io
import json
import os
import shutil
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

import anyio

from ..exports import generate_codex_export
from ..models import AnalysisConfig
from ..pipeline import AnalysisCancelled as PipelineAnalysisCancelled
from ..pipeline import analyze_track
from ..project import ProjectManager, compute_cache_key, content_hash
from ..schema import validate_rhythm_v4
from .errors import (
    AnalysisCancelledError,
    AnalysisFailed,
    ExportTargetExists,
    ProjectNotFound,
    RuntimeUnavailable,
)
from .formatting import full_or_truncated, paginate, project_summary, summary_line, timing_view
from .models import AnalyzeAudioInput, EventsInput, GetProjectInput, ListProjectsInput
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

    def _rhythm_path(self, project_id: str) -> Path:
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

    # ------------------------------------------------------------ analysis

    async def analyze_audio(
        self,
        request: AnalyzeAudioInput,
        progress: Callable[[float, str | None], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Analyze audio into a validated project with multi-config caching.

        The pipeline runs in a worker thread (never the event loop); thread
        progress hops back through ``anyio.from_thread``. Cancellation sets
        a threading.Event the pipeline checks, and persistence happens only
        after the schema v4 validation at the save boundary (plan 12.3).
        """
        audio_path = self.paths.resolve_audio(request.audio_path)
        beat_file = self.paths.resolve_beat_file(request.beat_file) if request.beat_file else None
        drums_path = self.paths.resolve_audio(request.drums_path) if request.drums_path else None
        cfg = AnalysisConfig(backend=request.backend, subdivision=request.subdivision, separation="auto")

        display_name = audio_path.name
        sha256 = await anyio.to_thread.run_sync(content_hash, audio_path)
        cache_config = cfg.to_dict()
        # External timing/stem evidence changes the analysis just as much as a
        # backend option does. Address it by content, not by path, so renamed
        # identical files hit the cache while changed files never reuse stale
        # rhythm data.
        if beat_file is not None:
            cache_config["beat_file_sha256"] = await anyio.to_thread.run_sync(
                content_hash, beat_file
            )
        if drums_path is not None:
            cache_config["drums_sha256"] = await anyio.to_thread.run_sync(
                content_hash, drums_path
            )
        cache_key = compute_cache_key(sha256, cache_config)
        project_id = sha256[:12]

        if not request.force and self.projects.find_cached_rhythm(sha256, cache_key) is not None:
            if progress is not None:
                await progress(1.0, "Loaded from cache")
            return _analyze_summary(project_id, self.load_validated_rhythm(project_id), cache_hit=True)

        cancel_event = threading.Event()

        def pipeline_progress(stage: str, value: float, message: str) -> None:
            if progress is None or cancel_event.is_set():
                return
            try:
                anyio.from_thread.run(progress, float(value), message)
            except Exception:
                pass  # progress reporting must never kill the analysis

        def run_analysis() -> dict[str, Any]:
            return analyze_track(
                audio_path,
                cfg,
                beat_file=beat_file,
                drums_path=drums_path,
                display_name=display_name,
                progress=pipeline_progress,
                cancelled=cancel_event.is_set,
            )

        try:
            rhythm = await anyio.to_thread.run_sync(run_analysis, abandon_on_cancel=True)
        except PipelineAnalysisCancelled:
            raise AnalysisCancelledError(
                "Analysis was cancelled; nothing was written to the cache."
            ) from None
        except (ValueError, OSError) as exc:
            raise AnalysisFailed(f"BeatScope could not analyze '{display_name}': {exc}") from exc
        except BaseException:
            cancel_event.set()  # the await was cancelled: stop the worker thread
            raise

        errors = validate_rhythm_v4(rhythm)
        if errors:
            raise AnalysisFailed("Analyzer produced an invalid project: " + "; ".join(errors[:5]))

        def persist() -> None:
            project_dir = self.projects.save_project(
                project_id, audio_path, rhythm, cache_config, cache_key,
            )
            audio_dst = project_dir / "source.audio"
            if not audio_dst.is_file():
                shutil.copy2(audio_path, audio_dst)
            meta_file = project_dir / "project.json"
            if meta_file.is_file():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["audio_path"] = str(audio_dst.resolve())
                meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

        await anyio.to_thread.run_sync(persist)
        if progress is not None:
            await progress(1.0, "Analysis complete")
        return _analyze_summary(project_id, rhythm, cache_hit=False)

    # ------------------------------------------------------------- export

    def export_package(self, request) -> dict[str, Any]:
        """Export one project as the portable agent ZIP (plan section 17).

        The ZIP is written to a sibling temp file first and moved into place
        with ``Path.replace()`` so a crash can never leave a truncated ZIP
        at the destination. The binary itself stays out of the MCP response;
        callers get the path, size, SHA-256, and ZIP manifest instead.
        """
        rhythm = self.load_validated_rhythm(request.project_id)
        target = self.paths.resolve_export_target(request.destination)
        existed = target.is_file()
        if existed and not request.overwrite:
            raise ExportTargetExists(
                f"Export destination already exists: {target}. "
                "Pass overwrite=true to replace it."
            )

        payload = generate_codex_export(rhythm)
        tmp_target = target.with_name(f"{target.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        try:
            tmp_target.write_bytes(payload)
            tmp_target.replace(target)
        finally:
            tmp_target.unlink(missing_ok=True)  # no-op once replace() succeeded

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            files = [
                {"name": info.filename, "size_bytes": info.file_size}
                for info in archive.infolist()
            ]
        return {
            "ok": True,
            "project_id": request.project_id,
            "summary": f"Exported {len(files)} file(s) to {target.name} ({len(payload)} bytes)",
            "destination": str(target),
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "overwritten": bool(existed),
            "files": files,
        }

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
        if "segments" in request.include:
            events += _segment_events(rhythm, request.start, request.end)
        if "boundaries" in request.include:
            events += [
                {"kind": "boundary", **boundary}
                for boundary in _time_slice(
                    (rhythm.get("patterns") or {}).get("boundaries") or [],
                    request.start, request.end,
                )
            ]

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


def _analyze_summary(project_id: str, rhythm: dict[str, Any], *, cache_hit: bool) -> dict[str, Any]:
    """The plan section 12.4 response view for one analysis."""
    tempo = rhythm.get("tempo") or {}
    grid = rhythm.get("grid") or {}
    source = rhythm.get("source") or {}
    analysis = rhythm.get("analysis") or {}
    cue_items = rhythm.get("cues") or {}
    return {
        "ok": True,
        "project_id": project_id,
        "cache_hit": cache_hit,
        "source": {
            "display_name": source.get("display_name") or "unknown",
            "duration": source.get("duration"),
        },
        "tempo": {
            "global_bpm": tempo.get("global_bpm"),
            "segments": len(tempo.get("segments") or []),
        },
        "grid": {
            "bars": grid.get("bars"),
            "subdivision": grid.get("default_subdivision"),
        },
        "counts": {
            "beats": len(rhythm.get("beats") or []),
            "onsets": len(rhythm.get("onsets") or []),
            "cues": sum(len(v) for v in cue_items.values() if isinstance(v, list)),
        },
        "analysis": {
            "backend": analysis.get("backend"),
            "separation_used": bool(analysis.get("separation_used")),
        },
        "warnings": list(analysis.get("warnings") or []),
    }


def _time_slice(items: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    """Items with start < time <= end, via bisect (no full scans)."""
    times = [float(item.get("time") or 0) for item in items]
    lo = bisect.bisect_right(times, start)
    hi = bisect.bisect_right(times, end)
    return items[lo:hi]


def _segment_events(rhythm: dict[str, Any], start: float, end: float) -> list[dict[str, Any]]:
    """Structural segments overlapping the query window (plan section 16).

    A segment is a span, not an instant, so it is included when its
    [start_time, end_time) overlaps (start, end]. Only identity, family, and
    span facts ride along - never feature matrices.
    """
    segments = (rhythm.get("patterns") or {}).get("segments") or []
    events: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        seg_start = float(segment.get("start_time") or 0)
        seg_end = float(segment.get("end_time") or 0)
        if seg_start < end and seg_end > start:
            events.append({
                "kind": "segment",
                "time": seg_start,
                "end": seg_end,
                "family": segment.get("family"),
                "label": segment.get("display_label"),
                "index": segment.get("index"),
            })
    return events


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
