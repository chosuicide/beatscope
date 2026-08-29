"""Canonical snapshot helpers for pinning current analyzer behavior.

Snapshots must be stable across machines and runs: timestamps, absolute
paths and long energy arrays are reduced to comparable summaries.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

SUMMARY_HEAD = 8
ROUND_DIGITS = 4


def _round_floats(obj: Any, digits: int = ROUND_DIGITS) -> Any:
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return round(obj, digits)
    if isinstance(obj, dict):
        return {key: _round_floats(value, digits) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(value, digits) for value in obj]
    return obj


def _hash_values(values: list[float]) -> str:
    payload = json.dumps([round(float(v), ROUND_DIGITS) for v in values], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _summarize(values: list[Any]) -> dict[str, Any]:
    rounded = [round(float(v), ROUND_DIGITS) for v in values]
    return {
        "length": len(rounded),
        "head": rounded[:SUMMARY_HEAD],
        "tail": rounded[-SUMMARY_HEAD:],
        "sha256": _hash_values(rounded),
    }


def _compact_energy(data: dict[str, Any]) -> None:
    energy = data.get("energy")
    if not isinstance(energy, dict):
        return
    bands = energy.get("bands")
    if isinstance(bands, dict):
        energy["bands"] = {
            name: _summarize(values) if isinstance(values, list) else values
            for name, values in bands.items()
        }
    frames = energy.get("frames")
    if isinstance(frames, list) and frames and isinstance(frames[0], dict):
        names = [key for key in frames[0] if key != "time"]
        energy["frames"] = {
            "count": len(frames),
            "time_head": [frame.get("time") for frame in frames[:3]],
            "bands": {name: _summarize([frame.get(name, 0.0) for frame in frames]) for name in names},
        }


def canonical_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    """Reduce a project dict to a machine-stable snapshot representation."""
    data = copy.deepcopy(project)

    analysis = data.get("analysis")
    if isinstance(analysis, dict):
        analysis.pop("created_at", None)
        separation = analysis.get("separation")
        if isinstance(separation, dict):
            analysis["separation"] = sorted(separation)

    source = data.get("source")
    if isinstance(source, dict):
        for key in ("path", "drums_path", "beat_this", "audio_path"):
            source.pop(key, None)

    _compact_energy(data)
    return _round_floats(data)


def diff_snapshots(expected: Any, actual: Any, path: str = "$") -> list[str]:
    """Return human-readable paths where two snapshots differ."""
    diffs: list[str] = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            diffs += diff_snapshots(expected.get(key), actual.get(key), f"{path}.{key}")
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            diffs.append(f"{path}: length {len(expected)} -> {len(actual)}")
        else:
            for index, (exp_item, act_item) in enumerate(zip(expected, actual)):
                diffs += diff_snapshots(exp_item, act_item, f"{path}[{index}]")
    elif expected != actual:
        diffs.append(f"{path}: {expected!r} -> {actual!r}")
    return diffs
