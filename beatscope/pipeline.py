"""The single analysis entry point for BeatScope.

Every surface (web upload, CLI, future backends) must produce its rhythm
project through ``analyze_track`` so there is only one source of truth.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from .backends import (
    AnalysisCancelled,
    AnalysisEvidence,
    AnalyzerBackend,
    BeatThisBackend,
    DemucsBackend,
    LightweightBackend,
    check_cancelled,
    never_cancelled,
    noop_progress,
)
from .backends.base import CancelCallback, ProgressCallback
from .models import AnalysisConfig
from .project import content_hash
from .schema import (
    ANALYZER_VERSION,
    SCHEMA_VERSION,
    InvalidRhythmProject,
    UnsupportedSchemaVersion,
    validate_rhythm_v4,
)
from .structure import analyze_song_structure


def resolve_backend(
    config: AnalysisConfig,
    beat_file: str | Path | None = None,
    drums_path: str | Path | None = None,
) -> AnalyzerBackend:
    """Map the config onto a concrete backend; raises for impossible routes."""
    if config.backend == "beat-this":
        if beat_file is None:
            raise ValueError("beat-this backend requires a Beat This beat file")
        return BeatThisBackend(beat_file, drums_path)
    if config.backend == "demucs":
        inner = BeatThisBackend(beat_file, drums_path) if beat_file is not None else LightweightBackend()
        return DemucsBackend(inner)
    return LightweightBackend()


def build_rhythm_project(
    source_path: Path,
    sha256: str,
    config: AnalysisConfig,
    backend: AnalyzerBackend,
    evidence: AnalysisEvidence,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Turn AnalysisEvidence into a validated RhythmProject (schema v4)."""
    overview = analyze_song_structure(
        evidence.onsets, evidence.beats, evidence.bars, subdivision=config.subdivision,
    )

    duration = round(float(evidence.duration), 4)
    diagnostics = dict(evidence.diagnostics)
    tempo_score = evidence.tempo_score

    # v0.4 emits a single full-length tempo segment; score exists only when a
    # real algorithm produced it (never a synthetic confidence value).
    segments = [{
        "start": 0.0,
        "end": duration,
        "bpm": round(float(evidence.tempo_bpm), 3),
        "method": str(diagnostics.get("tempo_method", "unknown")),
        "score": round(float(tempo_score), 4) if tempo_score is not None else None,
    }]

    # Facts and cues are separated: accents become cues, not onset identity.
    v4_onsets: list[dict[str, Any]] = []
    accent_cues: list[dict[str, Any]] = []
    for onset in evidence.onsets:
        entry: dict[str, Any] = {
            "id": int(onset["id"]),
            "time": round(float(onset.get("raw_time", onset.get("time", 0.0))), 4),
            "strength": float(onset.get("strength", 0.0)),
            "bands": {
                band: float(onset.get("bands", {}).get(band, 0.0))
                for band in ("all", "low", "mid", "high")
            },
        }
        if onset.get("quantized_time") is not None:
            entry["quantized_time"] = round(float(onset["quantized_time"]), 4)
        v4_onsets.append(entry)
        if onset.get("accent"):
            accent_cues.append({"time": entry["time"], "onset": entry["id"]})

    beats_v4: list[dict[str, Any]] = []
    pregrid_beats = 0
    for index, beat in enumerate(evidence.beats):
        bar = int(beat.get("bar", 1))
        if bar < 1:
            # Markers before the first downbeat join bar 1; the reassignment is
            # recorded instead of being silently dropped.
            bar = 1
            pregrid_beats += 1
        beats_v4.append({
            "time": round(float(beat["time"]), 4),
            "index": index,
            "bar": bar,
            "beat_in_bar": int(beat.get("beat", (index % 4) + 1)),
            "downbeat": bool(beat.get("downbeat", beat.get("beat") == 1)),
        })
    if pregrid_beats:
        diagnostics["pregrid_beats_merged"] = pregrid_beats

    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": sha256[:12],
        "source": {
            "display_name": display_name or source_path.name,
            "duration": duration,
            "sample_rate": evidence.sample_rate,
            "channels": evidence.channels,
            "sha256": sha256,
        },
        "analysis": {
            "backend": config.backend,
            "pipeline_version": ANALYZER_VERSION,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "warnings": list(evidence.warnings),
            "separation_used": bool(diagnostics.get("separated", False)),
            "parameters": {
                "subdivision": config.subdivision,
                "sample_rate": config.sample_rate,
                "hop_length": config.hop_length,
                "n_fft": config.n_fft,
            },
            "provenance": evidence.provenance,
            "diagnostics": diagnostics,
        },
        "tempo": {
            "global_bpm": round(float(evidence.tempo_bpm), 3),
            "segments": segments,
        },
        "meter": {"numerator": 4, "denominator": 4},
        "grid": {
            "origin": round(float(evidence.grid_origin), 4),
            "default_subdivision": config.subdivision,
            "bars": evidence.bars,
        },
        "beats": beats_v4,
        "onsets": v4_onsets,
        "energy": evidence.energy,
        "patterns": {"method": "bar-rhythm-cosine-v1", "bars": overview},
        "cues": {
            "accent": accent_cues,
            "impact": [],
            "scale": [],
            "flow": [],
            "flash": [],
            "bloom": [],
        },
        "exports": {},
    }


def analyze_track(
    audio_path: str | Path,
    config: AnalysisConfig | dict | None = None,
    *,
    beat_file: str | Path | None = None,
    drums_path: str | Path | None = None,
    display_name: str | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> dict[str, Any]:
    """Analyze one audio file and return a validated RhythmProject."""
    cfg = config if isinstance(config, AnalysisConfig) else AnalysisConfig.from_dict(config)
    cfg.validate()

    source_path = Path(audio_path)
    sha256 = content_hash(source_path)
    backend = resolve_backend(cfg, beat_file, drums_path)

    progress_cb = progress or noop_progress
    evidence = backend.analyze(source_path, cfg, progress_cb, cancelled or never_cancelled)

    check_cancelled(cancelled)
    progress_cb("structure", 0.90, "比对小节相似度与结构...")
    project = build_rhythm_project(source_path, sha256, cfg, backend, evidence, display_name)

    errors = validate_rhythm_v4(project)
    if errors:
        raise InvalidRhythmProject(errors)

    progress_cb("serialize", 0.98, "生成项目数据...")
    return project


__all__ = [
    "AnalysisCancelled",
    "InvalidRhythmProject",
    "analyze_track",
    "build_rhythm_project",
    "resolve_backend",
]
