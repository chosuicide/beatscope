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


def project_summary(project_id: str, rhythm: dict[str, Any]) -> dict[str, Any]:
    """The shared summary view: identity, tempo, counts, provenance, warnings."""
    analysis = rhythm.get("analysis") or {}
    tempo = rhythm.get("tempo") or {}
    source = rhythm.get("source") or {}
    bpm = tempo.get("global_bpm")
    duration = source.get("duration")
    return {
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
