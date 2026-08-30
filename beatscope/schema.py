"""Schema definitions, validators, and migrations for BeatScope project data."""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "4.0"
V3_SCHEMA_VERSION = "3.0"
ANALYZER_VERSION = "0.6.0"


class InvalidRhythmProject(ValueError):
    """Raised when a rhythm document fails schema validation."""

    def __init__(self, errors: list[str]):
        super().__init__(f"invalid rhythm project: {errors}")
        self.errors = errors


class UnsupportedSchemaVersion(ValueError):
    """Raised when a rhythm document's schema version cannot be migrated."""

# Field names that must never appear anywhere in a v4 project: instrument
# identity labels and uncalibrated certainty claims.
FORBIDDEN_V4_KEYS = ("kick", "snare", "hihat", "bass_808", "confidence")

_PROJECT_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _find_forbidden_keys(value: Any, path: str, errors: list[str]) -> None:
    """Recursively collect forbidden dict keys; lists of scalars are skipped."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_V4_KEYS:
                errors.append(f"{path}.{key}: '{key}' is not allowed in schema v4")
            _find_forbidden_keys(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            if isinstance(item, (dict, list)):
                _find_forbidden_keys(item, f"{path}[{idx}]", errors)


def validate_rhythm_v3(data: dict[str, Any]) -> list[str]:
    """Validate a v3 rhythm dictionary. Returns a list of error messages (empty if valid)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Root must be a JSON object"]

    if data.get("schema_version") != V3_SCHEMA_VERSION:
        errors.append(f"Expected schema_version '{V3_SCHEMA_VERSION}', got '{data.get('schema_version')}'")

    project_id = data.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        errors.append("Missing or invalid project_id")

    source = data.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        for req in ("display_name", "duration", "sample_rate"):
            if req not in source:
                errors.append(f"source missing '{req}'")
        if "duration" in source and (not isinstance(source["duration"], (int, float)) or source["duration"] < 0):
            errors.append("source.duration must be a non-negative number")

    analysis = data.get("analysis")
    if not isinstance(analysis, dict):
        errors.append("analysis must be an object")
    else:
        if "pipeline" not in analysis:
            errors.append("analysis missing 'pipeline'")

    tempo = data.get("tempo")
    if not isinstance(tempo, dict):
        errors.append("tempo must be an object")
    else:
        if "global_bpm" not in tempo or not isinstance(tempo["global_bpm"], (int, float)):
            errors.append("tempo.global_bpm must be a number")

    grid = data.get("grid")
    if not isinstance(grid, dict):
        errors.append("grid must be an object")
    else:
        if "time_signature" not in grid or not (
            isinstance(grid["time_signature"], list) and len(grid["time_signature"]) == 2
        ):
            errors.append("grid.time_signature must be a [num, den] list")
        if "origin" not in grid or not isinstance(grid["origin"], (int, float)):
            errors.append("grid.origin must be a number")
        if "default_subdivision" not in grid or grid["default_subdivision"] not in (16, 32):
            errors.append("grid.default_subdivision must be 16 or 32")
        if "bars" not in grid or not isinstance(grid["bars"], int) or grid["bars"] < 0:
            errors.append("grid.bars must be a non-negative integer")

    beats = data.get("beats")
    if not isinstance(beats, list):
        errors.append("beats must be a list")
    else:
        prev_time = -1.0
        for idx, beat in enumerate(beats):
            if not isinstance(beat, dict):
                errors.append(f"beats[{idx}] must be an object")
                break
            b_time = beat.get("time")
            if not isinstance(b_time, (int, float)) or b_time < prev_time:
                errors.append(f"beats[{idx}].time must be strictly non-decreasing, got {b_time} after {prev_time}")
                break
            prev_time = float(b_time)
            if beat.get("beat") not in (1, 2, 3, 4):
                errors.append(f"beats[{idx}].beat must be 1, 2, 3, or 4")
                break

    onsets = data.get("onsets")
    if not isinstance(onsets, list):
        errors.append("onsets must be a list")
    else:
        for idx, onset in enumerate(onsets):
            if not isinstance(onset, dict):
                errors.append(f"onsets[{idx}] must be an object")
                break
            for req in ("raw_time", "strength", "bands", "accent", "confidence"):
                if req not in onset:
                    errors.append(f"onsets[{idx}] missing '{req}'")
                    break
            bands = onset.get("bands")
            if isinstance(bands, dict):
                for b_name in ("all", "low", "mid", "high"):
                    if b_name not in bands:
                        errors.append(f"onsets[{idx}].bands missing '{b_name}'")
                        break

    energy = data.get("energy")
    if not isinstance(energy, dict):
        errors.append("energy must be an object")
    else:
        if "fps" not in energy or "bands" not in energy:
            errors.append("energy missing 'fps' or 'bands'")
        elif isinstance(energy["bands"], dict):
            for b_name in ("all", "low", "mid", "high"):
                if b_name not in energy["bands"] or not isinstance(energy["bands"][b_name], list):
                    errors.append(f"energy.bands missing array '{b_name}'")
                    break

    if "overview" not in data or not isinstance(data["overview"], list):
        errors.append("overview must be a list")

    if "exports" not in data or not isinstance(data["exports"], dict):
        errors.append("exports must be an object")

    return errors


def validate_rhythm_v4(data: dict[str, Any]) -> list[str]:
    """Validate a v4 rhythm project, including nested field semantics (plan §22)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Root must be a JSON object"]

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"Expected schema_version '{SCHEMA_VERSION}', got '{data.get('schema_version')}'")

    project_id = data.get("project_id")
    if not isinstance(project_id, str) or not _PROJECT_ID_RE.match(project_id):
        errors.append("project_id must be 12 lowercase hex characters")

    source = data.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        name = source.get("display_name")
        if not isinstance(name, str) or not name:
            errors.append("source.display_name must be a non-empty string")
        duration = source.get("duration")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
            errors.append("source.duration must be a non-negative number")
        if not isinstance(source.get("sample_rate"), int) or source["sample_rate"] <= 0:
            errors.append("source.sample_rate must be a positive integer")
        if not isinstance(source.get("channels"), int) or source["channels"] < 1:
            errors.append("source.channels must be a positive integer")
        if not isinstance(source.get("sha256"), str):
            errors.append("source.sha256 must be a string")

    analysis = data.get("analysis")
    if not isinstance(analysis, dict):
        errors.append("analysis must be an object")
    else:
        if not isinstance(analysis.get("backend"), str) or not analysis["backend"]:
            errors.append("analysis.backend must be a non-empty string")
        if not isinstance(analysis.get("pipeline_version"), str) or not analysis["pipeline_version"]:
            errors.append("analysis.pipeline_version must be a non-empty string")
        provenance = analysis.get("provenance")
        if not isinstance(provenance, dict):
            errors.append("analysis.provenance must be an object")
        else:
            for req in ("beats", "onsets"):
                fact = provenance.get(req)
                if not isinstance(fact, dict) or not isinstance(fact.get("method"), str):
                    errors.append(f"analysis.provenance.{req} must declare a 'method'")
        if "diagnostics" in analysis and not isinstance(analysis["diagnostics"], dict):
            errors.append("analysis.diagnostics must be an object when present")

    tempo = data.get("tempo")
    if not isinstance(tempo, dict):
        errors.append("tempo must be an object")
    else:
        bpm = tempo.get("global_bpm")
        if not isinstance(bpm, (int, float)) or isinstance(bpm, bool) or not (20 < bpm < 400):
            errors.append("tempo.global_bpm must be a number in (20, 400)")
        segments = tempo.get("segments")
        if not isinstance(segments, list) or not segments:
            errors.append("tempo.segments must be a non-empty list")
        else:
            previous_end = -1.0
            for idx, segment in enumerate(segments):
                if not isinstance(segment, dict):
                    errors.append(f"tempo.segments[{idx}] must be an object")
                    break
                start, end = segment.get("start"), segment.get("end")
                seg_bpm = segment.get("bpm")
                if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                    errors.append(f"tempo.segments[{idx}].start/end must be numbers")
                    break
                if start > end:
                    errors.append(f"tempo.segments[{idx}] start must not exceed end")
                    break
                if start < previous_end:
                    errors.append(f"tempo.segments[{idx}] overlaps the previous segment")
                    break
                if not isinstance(seg_bpm, (int, float)) or not (20 < seg_bpm < 400):
                    errors.append(f"tempo.segments[{idx}].bpm must be a number in (20, 400)")
                    break
                previous_end = float(end)
            if isinstance(segments[0], dict) and isinstance(segments[0].get("start"), (int, float)):
                if segments[0]["start"] > 0.001:
                    errors.append("tempo.segments must start at 0")

    meter = data.get("meter")
    if not isinstance(meter, dict):
        errors.append("meter must be an object")
    else:
        numerator, denominator = meter.get("numerator"), meter.get("denominator")
        if not isinstance(numerator, int) or not 1 <= numerator <= 16:
            errors.append("meter.numerator must be an integer in 1..16")
        if not isinstance(denominator, int) or not 1 <= denominator <= 16:
            errors.append("meter.denominator must be an integer in 1..16")

    duration = source.get("duration") if isinstance(source, dict) else 0.0
    duration = duration if isinstance(duration, (int, float)) else 0.0

    grid = data.get("grid")
    if not isinstance(grid, dict):
        errors.append("grid must be an object")
    else:
        if not isinstance(grid.get("origin"), (int, float)):
            errors.append("grid.origin must be a number")
        if grid.get("default_subdivision") not in (16, 32):
            errors.append("grid.default_subdivision must be 16 or 32")
        if not isinstance(grid.get("bars"), int) or grid["bars"] < 1:
            errors.append("grid.bars must be a positive integer")

    beats = data.get("beats")
    onset_ids: set[int] = set()
    if not isinstance(beats, list):
        errors.append("beats must be a list")
    else:
        numerator = meter["numerator"] if isinstance(meter, dict) and isinstance(meter.get("numerator"), int) else 4
        prev_time: float | None = None
        for idx, beat in enumerate(beats):
            if not isinstance(beat, dict):
                errors.append(f"beats[{idx}] must be an object")
                break
            b_time = beat.get("time")
            if not isinstance(b_time, (int, float)) or isinstance(b_time, bool):
                errors.append(f"beats[{idx}].time must be a number")
                break
            if prev_time is not None and b_time <= prev_time:
                errors.append(f"beats[{idx}].time must be strictly increasing")
                break
            prev_time = float(b_time)
            if beat.get("index") != idx:
                errors.append(f"beats[{idx}].index must equal its list position")
                break
            if not isinstance(beat.get("bar"), int) or beat["bar"] < 1:
                errors.append(f"beats[{idx}].bar must be a positive integer")
                break
            beat_in_bar = beat.get("beat_in_bar")
            if not isinstance(beat_in_bar, int) or not 1 <= beat_in_bar <= numerator:
                errors.append(f"beats[{idx}].beat_in_bar must be an integer in 1..{numerator}")
                break
            if beat.get("downbeat") != (beat_in_bar == 1):
                errors.append(f"beats[{idx}].downbeat must match beat_in_bar == 1")
                break

    onsets = data.get("onsets")
    if not isinstance(onsets, list):
        errors.append("onsets must be a list")
    else:
        prev_onset_time: float | None = None
        for idx, onset in enumerate(onsets):
            if not isinstance(onset, dict):
                errors.append(f"onsets[{idx}] must be an object")
                break
            if "accent" in onset:
                errors.append(f"onsets[{idx}] must not carry 'accent'; accents belong in cues.accent")
                break
            onset_id = onset.get("id")
            if not isinstance(onset_id, int) or onset_id < 1:
                errors.append(f"onsets[{idx}].id must be a positive integer")
                break
            if onset_id in onset_ids:
                errors.append(f"onsets[{idx}].id {onset_id} is duplicated")
                break
            onset_ids.add(onset_id)
            o_time = onset.get("time")
            if not isinstance(o_time, (int, float)) or isinstance(o_time, bool):
                errors.append(f"onsets[{idx}].time must be a number")
                break
            if prev_onset_time is not None and o_time < prev_onset_time:
                errors.append(f"onsets[{idx}].time must be non-decreasing")
                break
            prev_onset_time = float(o_time)
            if o_time > duration + 0.05:
                errors.append(f"onsets[{idx}].time {o_time} is beyond the audio duration")
                break
            strength = onset.get("strength")
            if not isinstance(strength, (int, float)) or isinstance(strength, bool) or not (0.0 <= strength <= 1.0):
                errors.append(f"onsets[{idx}].strength must be in 0..1")
                break
            bands = onset.get("bands")
            if not isinstance(bands, dict):
                errors.append(f"onsets[{idx}].bands must be an object")
                break
            bad_band = False
            for b_name in ("all", "low", "mid", "high"):
                b_val = bands.get(b_name)
                if not isinstance(b_val, (int, float)) or isinstance(b_val, bool) or not (0.0 <= b_val <= 1.0):
                    errors.append(f"onsets[{idx}].bands.{b_name} must be a number in 0..1")
                    bad_band = True
                    break
            if bad_band:
                break

    energy = data.get("energy")
    if not isinstance(energy, dict):
        errors.append("energy must be an object")
    else:
        if not isinstance(energy.get("fps"), (int, float)) or energy["fps"] <= 0:
            errors.append("energy.fps must be a positive number")
        bands = energy.get("bands")
        if not isinstance(bands, dict):
            errors.append("energy.bands must be an object")
        else:
            lengths: set[int] = set()
            for b_name in ("all", "low", "mid", "high"):
                arr = bands.get(b_name)
                if not isinstance(arr, list):
                    errors.append(f"energy.bands.{b_name} must be an array")
                    break
                lengths.add(len(arr))
            else:
                if len(lengths) > 1:
                    errors.append("energy.bands arrays must all have the same length")

    patterns = data.get("patterns")
    if not isinstance(patterns, dict):
        errors.append("patterns must be an object")
    else:
        if not isinstance(patterns.get("method"), str) or not patterns["method"]:
            errors.append("patterns.method must be a non-empty string")
        bars_list = patterns.get("bars")
        if not isinstance(bars_list, list):
            errors.append("patterns.bars must be a list")
        else:
            for idx, item in enumerate(bars_list):
                if not isinstance(item, dict) or not isinstance(item.get("bar"), int) or item["bar"] < 1:
                    errors.append(f"patterns.bars[{idx}] must declare a positive integer 'bar'")
                    break

    cues = data.get("cues")
    if not isinstance(cues, dict):
        errors.append("cues must be an object")
    else:
        for cue_name, items in cues.items():
            if not isinstance(items, list):
                errors.append(f"cues.{cue_name} must be a list")
                continue
            for idx, cue in enumerate(items):
                if not isinstance(cue, dict):
                    errors.append(f"cues.{cue_name}[{idx}] must be an object")
                    break
                ref = cue.get("onset")
                if ref is not None and (not isinstance(ref, int) or ref not in onset_ids):
                    errors.append(f"cues.{cue_name}[{idx}] references unknown onset id {ref}")
                    break

    if not isinstance(data.get("exports"), dict):
        errors.append("exports must be an object")

    _find_forbidden_keys(data, "$", errors)
    return errors


def migrate_v2_to_v3(v2_data: dict[str, Any], project_id: str | None = None) -> dict[str, Any]:
    """Migrate a v2.0 rhythm.json dictionary to the v3.0 schema."""
    src = v2_data.get("source", {})
    display_name = src.get("file") or src.get("display_name") or "unknown.wav"
    duration = float(src.get("duration", 0.0))
    sample_rate = int(src.get("sample_rate", 44100))
    channels = int(src.get("channels", 2))
    sha256 = src.get("sha256", "")

    if not project_id:
        seed = f"{display_name}:{duration}:{sha256}"
        project_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]

    # Grid & Tempo
    v2_grid = v2_data.get("grid", {})
    v2_tempo = v2_data.get("tempo", {})
    bpm = float(v2_tempo.get("bpm", 120.0))
    origin = float(v2_grid.get("origin", 0.0))
    default_subdivision = int(v2_grid.get("subdivision", 16))
    bars = int(v2_grid.get("bars", 1))

    time_sig_raw = v2_grid.get("time_signature", "4/4")
    if isinstance(time_sig_raw, str) and "/" in time_sig_raw:
        parts = time_sig_raw.split("/")
        time_signature = [int(parts[0]), int(parts[1])]
    elif isinstance(time_sig_raw, list) and len(time_sig_raw) == 2:
        time_signature = [int(time_sig_raw[0]), int(time_sig_raw[1])]
    else:
        time_signature = [4, 4]

    # Beats
    v3_beats = []
    for beat in v2_data.get("beats", []):
        v3_beats.append({
            "time": round(float(beat.get("time", 0.0)), 4),
            "beat": int(beat.get("beat", 1)),
            "bar": int(beat.get("bar", 1)),
            "downbeat": bool(beat.get("beat") == 1),
            "confidence": round(float(beat.get("confidence", 0.9)), 2),
            "sequence_gap": bool(beat.get("sequence_gap", False)),
        })

    # Onsets: keep factual raw fields, omit ephemeral grid subdivision fields
    v3_onsets = []
    for idx, onset in enumerate(v2_data.get("onsets", []), 1):
        raw_time = float(onset.get("raw_time", onset.get("time", 0.0)))
        strength = float(onset.get("strength", 0.0))
        bands_data = onset.get("bands", {})
        bands = {
            "all": round(float(bands_data.get("all", strength)), 4),
            "low": round(float(bands_data.get("low", 0.0)), 4),
            "mid": round(float(bands_data.get("mid", 0.0)), 4),
            "high": round(float(bands_data.get("high", 0.0)), 4),
        }
        v3_onsets.append({
            "id": int(onset.get("id", idx)),
            "raw_time": round(raw_time, 4),
            "strength": round(strength, 4),
            "bands": bands,
            "accent": bool(onset.get("accent", strength >= 0.72)),
            "confidence": round(float(onset.get("confidence", min(1.0, max(0.05, strength)))), 3),
        })

    # Energy
    v2_energy = v2_data.get("energy", {})
    frames = v2_energy.get("frames", [])
    if frames:
        t0 = frames[0].get("time", 0.0)
        t1 = frames[1].get("time", 0.01) if len(frames) > 1 else t0 + 0.01
        dt = max(1e-4, t1 - t0)
        fps = round(1.0 / dt, 1)
        if abs(fps - round(fps)) < 0.01:
            fps = int(round(fps))
        start = round(float(t0), 4)
        all_band = [round(float(f.get("all", 0.0)), 4) for f in frames]
        low_band = [round(float(f.get("low", 0.0)), 4) for f in frames]
        mid_band = [round(float(f.get("mid", 0.0)), 4) for f in frames]
        high_band = [round(float(f.get("high", 0.0)), 4) for f in frames]
    else:
        fps = int(v2_energy.get("fps", 100))
        start = float(v2_energy.get("start", 0.0))
        b_dict = v2_energy.get("bands", {})
        all_band = b_dict.get("all", [])
        low_band = b_dict.get("low", [])
        mid_band = b_dict.get("mid", [])
        high_band = b_dict.get("high", [])

    v3_energy = {
        "fps": fps,
        "start": start,
        "bands": {
            "all": all_band,
            "low": low_band,
            "mid": mid_band,
            "high": high_band,
        },
    }

    # Analysis
    v2_analysis = v2_data.get("analysis", {})
    pipeline = v2_analysis.get("method") or v2_analysis.get("pipeline") or "beat-this+demucs-drums+multiband-novelty"
    warnings = v2_analysis.get("warnings", [])

    v3_data: dict[str, Any] = {
        "schema_version": V3_SCHEMA_VERSION,
        "project_id": project_id,
        "source": {
            "display_name": display_name,
            "duration": round(duration, 4),
            "sample_rate": sample_rate,
            "channels": channels,
            "sha256": sha256,
        },
        "analysis": {
            "pipeline": pipeline,
            "analyzer_version": ANALYZER_VERSION,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "warnings": warnings,
            "separation_used": bool("demucs" in pipeline or v2_analysis.get("separation_used")),
        },
        "tempo": {
            "global_bpm": round(bpm, 3),
            "confidence": 0.91,
            "variable_tempo": False,
        },
        "grid": {
            "time_signature": time_signature,
            "origin": round(origin, 4),
            "default_subdivision": default_subdivision,
            "bars": bars,
        },
        "beats": v3_beats,
        "onsets": v3_onsets,
        "energy": v3_energy,
        "overview": v2_data.get("overview", []),
        "exports": {},
    }

    return v3_data


def migrate_v3_to_v4(v3_data: dict[str, Any], project_id: str | None = None) -> dict[str, Any]:
    """Migrate a v3.0 rhythm dictionary to the v4.0 schema (plan section 23).

    Facts stay facts: v3 confidence fields are dropped and the legacy tempo
    confidence is preserved only as ``analysis.diagnostics.legacy_tempo_score``.
    Accent moves from each onset into ``cues.accent``.
    """
    if not isinstance(v3_data, dict):
        raise UnsupportedSchemaVersion("v3 document must be a JSON object")

    src = v3_data.get("source") if isinstance(v3_data.get("source"), dict) else {}
    duration = float(src.get("duration", 0.0) or 0.0)
    sha256 = src.get("sha256", "")
    if not isinstance(sha256, str):
        sha256 = ""

    if not project_id:
        pid = v3_data.get("project_id")
        if isinstance(pid, str) and _PROJECT_ID_RE.match(pid):
            project_id = pid
        else:
            seed = f"{src.get('display_name')}:{duration}:{sha256}"
            project_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]

    v3_analysis = v3_data.get("analysis") if isinstance(v3_data.get("analysis"), dict) else {}
    v3_tempo = v3_data.get("tempo") if isinstance(v3_data.get("tempo"), dict) else {}
    v3_grid = v3_data.get("grid") if isinstance(v3_data.get("grid"), dict) else {}

    meter_raw = v3_grid.get("time_signature", [4, 4])
    numerator, denominator = 4, 4
    if isinstance(meter_raw, (list, tuple)) and len(meter_raw) == 2:
        try:
            numerator, denominator = int(meter_raw[0]), int(meter_raw[1])
        except (TypeError, ValueError):
            pass
    elif isinstance(meter_raw, str) and "/" in meter_raw:
        try:
            numerator, denominator = (int(part) for part in meter_raw.split("/", 1))
        except (TypeError, ValueError):
            pass
    numerator = min(max(numerator, 1), 16)
    denominator = min(max(denominator, 1), 16)

    diagnostics: dict[str, Any] = {
        "migrated_from": str(v3_analysis.get("pipeline") or "unknown"),
    }
    if v3_tempo.get("confidence") is not None:
        try:
            diagnostics["legacy_tempo_score"] = round(float(v3_tempo["confidence"]), 4)
        except (TypeError, ValueError):
            pass
    if v3_tempo.get("variable_tempo") is not None:
        diagnostics["variable_tempo"] = bool(v3_tempo["variable_tempo"])

    # v3 kept pre-grid beats at bar 0; clamp them into bar 1 and record the
    # merge so the migrated grid stays honest about what moved.
    pregrid_merged = 0
    v4_beats: list[dict[str, Any]] = []
    for beat in v3_data.get("beats", []):
        if not isinstance(beat, dict):
            continue
        try:
            beat_time = round(float(beat.get("time", 0.0) or 0.0), 4)
        except (TypeError, ValueError):
            continue
        bar = beat.get("bar", 1)
        beat_in_bar = beat.get("beat", 1)
        bar = int(bar) if isinstance(bar, (int, float)) and not isinstance(bar, bool) else 1
        beat_in_bar = int(beat_in_bar) if isinstance(beat_in_bar, (int, float)) and not isinstance(beat_in_bar, bool) else 1
        if bar < 1 or beat_in_bar < 1:
            pregrid_merged += 1
            bar = max(bar, 1)
            beat_in_bar = max(beat_in_bar, 1)
        beat_in_bar = min(beat_in_bar, numerator)
        v4_beats.append({
            "time": beat_time,
            "index": len(v4_beats),
            "bar": bar,
            "beat_in_bar": beat_in_bar,
            "downbeat": beat_in_bar == 1,
        })
    if pregrid_merged:
        diagnostics["pregrid_beats_merged"] = pregrid_merged

    accent_cues: list[dict[str, Any]] = []
    v4_onsets: list[dict[str, Any]] = []
    for onset in v3_data.get("onsets", []):
        if not isinstance(onset, dict):
            continue
        onset_id = int(onset.get("id", len(v4_onsets) + 1))
        raw_time = float(onset.get("raw_time", onset.get("time", 0.0)) or 0.0)
        strength = min(max(float(onset.get("strength", 0.0) or 0.0), 0.0), 1.0)
        bands_raw = onset.get("bands") if isinstance(onset.get("bands"), dict) else {}
        entry: dict[str, Any] = {
            "id": onset_id,
            "time": round(raw_time, 4),
            "strength": round(strength, 4),
            "bands": {
                "all": round(float(bands_raw.get("all", strength) or 0.0), 4),
                "low": round(float(bands_raw.get("low", 0.0) or 0.0), 4),
                "mid": round(float(bands_raw.get("mid", 0.0) or 0.0), 4),
                "high": round(float(bands_raw.get("high", 0.0) or 0.0), 4),
            },
        }
        if onset.get("quantized_time") is not None:
            entry["quantized_time"] = round(float(onset["quantized_time"]), 4)
        v4_onsets.append(entry)
        if onset.get("accent"):
            accent_cues.append({"time": round(raw_time, 4), "onset": onset_id})

    try:
        bpm = float(v3_tempo.get("global_bpm", 120.0) or 120.0)
    except (TypeError, ValueError):
        bpm = 120.0

    v3_provenance = v3_analysis.get("provenance") if isinstance(v3_analysis.get("provenance"), dict) else {}
    beats_prov = v3_provenance.get("beats") if isinstance(v3_provenance.get("beats"), dict) else {}
    onsets_prov = v3_provenance.get("onsets") if isinstance(v3_provenance.get("onsets"), dict) else {}
    overview = v3_data.get("overview")
    pattern_bars = [item for item in overview if isinstance(item, dict) and isinstance(item.get("bar"), int)] if isinstance(overview, list) else []

    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "source": {
            "display_name": src.get("display_name") or "unknown.wav",
            "duration": round(duration, 4),
            "sample_rate": int(src.get("sample_rate", 44100) or 44100),
            "channels": int(src.get("channels", 2) or 2),
            "sha256": sha256,
        },
        "analysis": {
            "backend": str(v3_analysis.get("backend") or "legacy"),
            "pipeline_version": str(v3_analysis.get("analyzer_version") or "unknown"),
            "created_at": v3_analysis.get("created_at") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "warnings": list(v3_analysis.get("warnings", []) or []),
            "separation_used": bool(v3_analysis.get("separation_used")),
            "provenance": {
                "beats": {"method": str(beats_prov.get("method") or "unknown"), "backend": "legacy"},
                "onsets": {"method": str(onsets_prov.get("method") or "unknown"), "backend": "legacy"},
            },
            "diagnostics": diagnostics,
        },
        "tempo": {
            "global_bpm": round(bpm, 3),
            "segments": [{
                "start": 0.0,
                "end": round(duration, 4),
                "bpm": round(bpm, 3),
                "method": "migrated-global-bpm",
                "score": None,
            }],
        },
        "meter": {"numerator": numerator, "denominator": denominator},
        "grid": {
            "origin": float(v3_grid.get("origin", 0.0) or 0.0),
            "default_subdivision": int(v3_grid.get("default_subdivision", 16) or 16),
            "bars": int(v3_grid.get("bars", 1) or 1),
        },
        "beats": v4_beats,
        "onsets": v4_onsets,
        "energy": v3_data.get("energy", {}),
        "patterns": {"method": "migrated-from-v3-overview", "bars": pattern_bars},
        "cues": {
            "accent": accent_cues,
            "impact": [],
            "scale": [],
            "flow": [],
            "flash": [],
            "bloom": [],
        },
        "exports": v3_data.get("exports", {}) if isinstance(v3_data.get("exports"), dict) else {},
    }


def normalize_rhythm(data: dict[str, Any], project_id: str | None = None) -> dict[str, Any]:
    """Return the document as v4: v4 passes through, older versions migrate."""
    if not isinstance(data, dict):
        raise UnsupportedSchemaVersion("rhythm document must be a JSON object")
    # v2 documents carry "version"; v3/v4 carry "schema_version".
    version = data.get("schema_version", data.get("version"))
    if version == SCHEMA_VERSION:
        return data
    if version == V3_SCHEMA_VERSION:
        return migrate_v3_to_v4(data, project_id)
    if isinstance(version, str) and version.startswith("2."):
        return migrate_v3_to_v4(migrate_v2_to_v3(data, project_id), project_id)
    raise UnsupportedSchemaVersion(f"unsupported rhythm schema_version: {version!r}")


def load_rhythm_project(path: str | Path) -> dict[str, Any]:
    """Load a rhythm.json from disk and return a validated v4 project.

    Old projects migrate in memory; the file on disk is never rewritten
    (plan section 24: read-time migration, write-always-v4).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    project = normalize_rhythm(data)
    errors = validate_rhythm_v4(project)
    if errors:
        raise InvalidRhythmProject(errors)
    return project
