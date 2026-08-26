"""Schema definitions, validators, and migrations for BeatScope project data."""
from __future__ import annotations

import datetime
import hashlib
from typing import Any

SCHEMA_VERSION = "3.0"
ANALYZER_VERSION = "0.3.0"


def validate_rhythm_v3(data: dict[str, Any]) -> list[str]:
    """Validate a v3 rhythm dictionary. Returns a list of error messages (empty if valid)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Root must be a JSON object"]

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"Expected schema_version '{SCHEMA_VERSION}', got '{data.get('schema_version')}'")

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
        "schema_version": SCHEMA_VERSION,
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
