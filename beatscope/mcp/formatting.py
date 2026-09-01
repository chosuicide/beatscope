"""Output shaping for MCP responses (plan section 10).

Summaries stay small and factual: no energy arrays, no private audio paths,
and pagination metadata everywhere a list can grow.
"""
from __future__ import annotations

import json
import math
from typing import Any


def _beat_bars(rhythm: dict[str, Any]) -> int:
    grid = rhythm.get("grid")
    if isinstance(grid, dict):
        return int(grid.get("bars") or 0)
    return 0


def _cue_count(rhythm: dict[str, Any]) -> int:
    cues = rhythm.get("cues")
    if not isinstance(cues, dict):
        return 0
    total = 0
    for value in cues.values():
        if isinstance(value, list):
            total += len(value)
    return total


def provenance_methods(rhythm: dict[str, Any]) -> dict[str, str]:
    provenance = rhythm.get("analysis", {}).get("provenance")
    methods: dict[str, str] = {}
    if isinstance(provenance, dict):
        for fact, detail in provenance.items():
            if isinstance(detail, dict) and isinstance(detail.get("method"), str):
                methods[fact] = detail["method"]
    return methods


def segment_energy_summary(rhythm: dict[str, Any]) -> list[dict[str, Any]]:
    """Return compact, frame-weighted LOW/MID/HIGH means per structure segment.

    Energy frames are sampled at ``energy.start + index / energy.fps`` and
    segments use the same half-open ``[start_time, end_time)`` convention as
    the structure/runtime surfaces. This is an MCP view, not a Rhythm IR field.
    """
    energy = rhythm.get("energy") or {}
    bands = energy.get("bands") or {}
    patterns = rhythm.get("patterns") or {}
    segments = patterns.get("segments")
    fps = energy.get("fps")
    start = energy.get("start", 0.0)
    if (
        not isinstance(segments, list)
        or not isinstance(bands, dict)
        or not isinstance(fps, (int, float))
        or float(fps) <= 0
        or not isinstance(start, (int, float))
    ):
        return []

    series = {name: bands.get(name) for name in ("low", "mid", "high")}
    if any(not isinstance(values, list) for values in series.values()):
        return []
    frame_count = min(len(values) for values in series.values())
    if frame_count <= 0:
        return []

    result: list[dict[str, Any]] = []
    frame_rate = float(fps)
    energy_start = float(start)
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_start = segment.get("start_time")
        segment_end = segment.get("end_time")
        if not isinstance(segment_start, (int, float)) or not isinstance(segment_end, (int, float)):
            continue
        # Subtract a tiny epsilon so exact frame boundaries stay exact despite
        # floating-point multiplication (for example, 1.2 * 100).
        first = max(0, math.ceil((float(segment_start) - energy_start) * frame_rate - 1e-9))
        stop = min(frame_count, math.ceil((float(segment_end) - energy_start) * frame_rate - 1e-9))
        if stop <= first:
            continue
        means = {
            name: round(sum(float(value) for value in values[first:stop]) / (stop - first), 6)
            for name, values in series.items()
        }
        result.append({
            "segment_id": segment.get("id"),
            "label": segment.get("display_label"),
            "start_time": round(float(segment_start), 6),
            "end_time": round(float(segment_end), 6),
            "mean": means,
        })
    return result


def project_summary(
    project_id: str,
    rhythm: dict[str, Any],
    *,
    include_segment_energy: bool = False,
) -> dict[str, Any]:
    """The shared summary view: identity, tempo, counts, provenance, warnings."""
    analysis = rhythm.get("analysis") or {}
    tempo = rhythm.get("tempo") or {}
    source = rhythm.get("source") or {}
    bpm = tempo.get("global_bpm")
    duration = source.get("duration")
    summary = {
        "project_id": project_id,
        "display_name": source.get("display_name") or "unknown",
        "bpm": round(float(bpm), 2) if isinstance(bpm, (int, float)) else None,
        "bars": _beat_bars(rhythm),
        "duration": round(float(duration), 3) if isinstance(duration, (int, float)) else None,
        "backend": analysis.get("backend"),
        "pipeline_version": analysis.get("pipeline_version"),
        "beats": len(rhythm.get("beats") or []),
        "onsets": len(rhythm.get("onsets") or []),
        "cues": _cue_count(rhythm),
        "warnings": list(analysis.get("warnings") or []),
        "provenance": provenance_methods(rhythm),
    }
    # v0.7 whole-song structure summary (plan section 16): counts and the
    # neutral form string only - never matrices or feature vectors.
    patterns = rhythm.get("patterns") or {}
    segments = patterns.get("segments")
    if isinstance(segments, list) and segments:
        families: list[str] = []
        for segment in segments:
            family = segment.get("family") if isinstance(segment, dict) else None
            if isinstance(family, str) and family not in families:
                families.append(family)
        labels = [
            segment.get("display_label")
            for segment in segments
            if isinstance(segment, dict) and isinstance(segment.get("display_label"), str)
        ]
        structure = {
            "segment_count": len(segments),
            "families": families,
            "form": "-".join(labels),
            "method": patterns.get("method"),
        }
        if include_segment_energy:
            segment_energy = segment_energy_summary(rhythm)
            if segment_energy:
                structure["segment_energy"] = segment_energy
        summary["structure"] = structure
    return summary


def summary_line(summary: dict[str, Any]) -> str:
    parts = []
    if summary["bpm"] is not None:
        parts.append(f"{summary['bpm']:g} BPM")
    parts.append(f"{summary['bars']} bars")
    if summary["duration"] is not None:
        parts.append(f"{summary['duration']:.2f} s")
    if summary["backend"]:
        parts.append(f"backend {summary['backend']}")
    return " · ".join(parts)


def timing_view(rhythm: dict[str, Any]) -> dict[str, Any]:
    """Timing detail: beats, segments, patterns, cues - never energy arrays."""
    view = {
        "tempo": rhythm.get("tempo"),
        "meter": rhythm.get("meter"),
        "grid": rhythm.get("grid"),
        "beats": rhythm.get("beats"),
        "patterns": rhythm.get("patterns"),
        "cues": rhythm.get("cues"),
    }
    return {key: value for key, value in view.items() if value is not None}


def paginate(items: list[Any], limit: int, offset: int) -> tuple[list[Any], dict[str, Any]]:
    total = len(items)
    page = items[offset : offset + limit]
    has_more = offset + limit < total
    meta = {
        "total": total,
        "count": len(page),
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
    }
    return page, meta


def full_or_truncated(
    rhythm: dict[str, Any], max_chars: int
) -> tuple[dict[str, Any] | None, bool]:
    """Serialize the full project unless it would blow the response budget.

    Never cuts JSON mid-token: an oversized project returns ``None`` plus
    ``truncated=True`` so the caller can point at the resource instead.
    """
    payload = json.dumps(rhythm, ensure_ascii=False, allow_nan=False)
    if len(payload) <= max_chars:
        return rhythm, False
    return None, True


def finite_or_none(value: Any) -> Any:
    """JSON cannot carry Infinity: collapse non-finite numbers to null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
