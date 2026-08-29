"""Fact-based rhythm map orchestration built from Beat This timing and stem transients."""
from __future__ import annotations

import datetime
import hashlib
import json
import struct
from pathlib import Path
from typing import Any
import numpy as np

from .audio_io import load_analysis_audio
from .beatgrid import BeatGridAnalyzer, parse_beat_this, quantize_to_beat_grid
from .features import compute_multiband_novelty, extract_onsets
from .structure import analyze_song_structure
from .schema import V3_SCHEMA_VERSION, ANALYZER_VERSION, validate_rhythm_v3, migrate_v2_to_v3


def analyze_rhythm(
    original: str | Path,
    drums: str | Path,
    beat_this: str | Path,
    subdivision: int = 16,
) -> dict[str, Any]:
    """Orchestrate factual rhythm analysis and produce a standard v3 rhythm project dictionary."""
    if subdivision not in (16, 32):
        raise ValueError("subdivision must be 16 or 32")

    orig_path = Path(original)
    drums_path = Path(drums)
    beat_this_path = Path(beat_this)

    # 1. Load audio for analysis
    y, sr, duration, audio_warnings = load_analysis_audio(drums_path, target_sr=44100)

    # 2. Beat grid analysis
    grid_analyzer = BeatGridAnalyzer()
    grid_res = grid_analyzer.analyze_beats(beat_this_path, duration=duration, subdivision=subdivision)

    # 3. Multiband novelty and onsets
    hop = 256
    times, novelty = compute_multiband_novelty(y, sr=sr, hop=hop)
    onsets = extract_onsets(times, novelty, sr=sr, hop=hop, bpm=grid_res.bpm)

    # 4. Song structure analysis
    overview = analyze_song_structure(onsets, grid_res.beats, grid_res.bars, subdivision=subdivision)

    # 5. Energy compression
    dt = hop / sr
    fps = int(round(1.0 / dt)) if dt > 0 else 100
    energy_data = {
        "fps": fps,
        "start": 0.0,
        "bands": {
            "all": [round(float(v), 4) for v in novelty["all"]],
            "low": [round(float(v), 4) for v in novelty["low"]],
            "mid": [round(float(v), 4) for v in novelty["mid"]],
            "high": [round(float(v), 4) for v in novelty["high"]],
        },
    }

    # Generate deterministic project_id
    sha256_hash = hashlib.sha256(orig_path.read_bytes() if orig_path.is_file() else b"").hexdigest()
    project_id = sha256_hash[:12] if sha256_hash else hashlib.sha256(orig_path.name.encode()).hexdigest()[:12]

    warnings = list(audio_warnings) + list(grid_res.warnings)

    result: dict[str, Any] = {
        "schema_version": V3_SCHEMA_VERSION,
        "project_id": project_id,
        "source": {
            "display_name": orig_path.name,
            "duration": round(duration, 4),
            "sample_rate": sr,
            "channels": 2,
            "sha256": sha256_hash,
        },
        "analysis": {
            "pipeline": "beat-this+demucs-drums+multiband-novelty",
            "analyzer_version": ANALYZER_VERSION,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "warnings": warnings,
            "separation_used": True,
        },
        "tempo": {
            "global_bpm": grid_res.bpm,
            "confidence": grid_res.confidence,
            "variable_tempo": grid_res.variable_tempo,
        },
        "grid": {
            "time_signature": [4, 4],
            "origin": grid_res.origin,
            "default_subdivision": subdivision,
            "bars": grid_res.bars,
        },
        "beats": grid_res.beats,
        "onsets": onsets,
        "energy": energy_data,
        "overview": overview,
        "exports": {},
    }

    # Validate output schema
    errs = validate_rhythm_v3(result)
    if errs:
        raise ValueError(f"Generated rhythm.json failed schema validation: {errs}")

    return result


def save_rhythm(result: dict[str, Any], destination: str | Path) -> None:
    out = Path(destination)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def write_rhythm_midi(result: dict[str, Any], destination: str | Path) -> None:
    """Write a portable rhythm-reference Standard MIDI File (SMF), note 60, not a drum transcription."""
    from .midi import TPQ, _meta_track, _track
    bpm = float(result.get("tempo", {}).get("global_bpm") or result.get("tempo", {}).get("bpm") or 120.0)
    origin = float(result.get("grid", {}).get("origin", 0.0))
    events: list[tuple[int, int, bytes]] = []

    for onset in result.get("onsets", []):
        raw_t = float(onset.get("raw_time", 0.0))
        quantized_t = float(onset.get("quantized_time", raw_t))
        tick = max(0, int(round((quantized_t - origin) * bpm / 60.0 * TPQ)))
        velocity = min(127, max(1, int(round(float(onset.get("strength", 0.8)) * 126.0)) + 1))
        events += [(tick, 1, bytes((0x90, 60, velocity))), (tick + 30, 0, bytes((0x80, 60, 0)))]

    track = _track(events, "BeatScope Rhythm Reference")
    header = b"MThd" + struct.pack(">IHHH", 6, 1, 2, TPQ)
    Path(destination).write_bytes(header + _meta_track(bpm) + track)


# Backwards compatibility helpers for legacy tests and older code
def _grid_event(time: float, origin: float, bpm: float, subdivision: int, strength: float, raw: dict[str, float]) -> dict[str, Any]:
    step = 60 / bpm / (subdivision / 4) if bpm else 0.0
    nearest = int(round((time - origin) / step)) if step else 0
    quantized = origin + nearest * step if step else time
    in_grid = nearest >= 0
    return {
        "raw_time": round(float(time), 4),
        "quantized_time": round(float(quantized), 4),
        "nearest_step": nearest,
        "bar": nearest // subdivision + 1 if in_grid else 0,
        "beat": nearest % subdivision // (subdivision // 4) + 1 if in_grid else 0,
        "step_in_bar": nearest % subdivision + 1 if in_grid else 0,
        "offset_ms": round((time - quantized) * 1000, 3),
        "strength": round(float(strength), 4),
        "bands": {k: round(float(v), 4) for k, v in raw.items()},
        "accent": bool(strength >= 0.72),
        "confidence": round(float(min(1, max(0.05, strength))), 3),
        "pre_grid": not in_grid,
    }


def _overview(onsets: list[dict[str, Any]], bars: int, subdivision: int) -> list[dict[str, Any]]:
    from .structure import cosine_similarity
    vectors: list[np.ndarray] = []
    for bar in range(1, bars + 1):
        vector = np.zeros(subdivision, dtype=np.float32)
        for event in onsets:
            if event.get("bar") == bar:
                step = event.get("step_in_bar", 1) - 1
                if 0 <= step < subdivision:
                    vector[step] = max(vector[step], float(event.get("strength", 0.0)))
        vectors.append(vector)
    labels: list[dict[str, Any]] = []
    for i, vector in enumerate(vectors):
        previous = cosine_similarity(vector, vectors[i - 1]) if i else 0.0
        mean = float(vector.mean())
        last_beat = float(vector[-4:].mean()) if subdivision >= 4 else 0.0
        if mean < 0.05:
            group = "BREAK"
        else:
            representatives = [(entry["group"], np.array(entry["vector"], dtype=np.float32)) for entry in labels if entry["group"] != "BREAK"]
            matches = [(name, cosine_similarity(vector, representative)) for name, representative in representatives]
            group = max(matches, key=lambda item: item[1])[0] if matches and max(matches, key=lambda item: item[1])[1] >= 0.82 else chr(65 + len({entry["group"] for entry in labels if entry["group"] != "BREAK"}))
        if mean < 0.05:
            label = "break"
        elif last_beat > max(0.12, float(vector[:-4].mean() if len(vector) > 4 else 0.0) * 1.6):
            label = "fill"
        elif previous >= 0.82:
            label = "repeat"
        else:
            label = "change"
        labels.append({
            "bar": i + 1,
            "label": label,
            "group": group,
            "mean_strength": round(mean, 4),
            "similarity_previous": round(previous, 4),
            "vector": [round(float(x), 4) for x in vector],
        })
    return labels
