"""Tests for the unified analysis pipeline (commit a: contract + backends)."""
from __future__ import annotations

from pathlib import Path

import pytest

from beatscope.backends import (
    AnalysisCancelled,
    AnalysisEvidence,
    BeatThisBackend,
    DemucsBackend,
    LightweightBackend,
)
from beatscope.models import AnalysisConfig
from beatscope.pipeline import InvalidRhythmProject, analyze_track, resolve_backend
from beatscope.schema import validate_rhythm_v4

try:
    import demucs  # noqa: F401
    _HAS_DEMUCS = True
except ImportError:
    _HAS_DEMUCS = False


def test_lightweight_backend_produces_evidence(fixed_120_audio):
    evidence = LightweightBackend().analyze(fixed_120_audio, AnalysisConfig(), lambda *a: None, lambda: False)
    assert isinstance(evidence, AnalysisEvidence)
    assert abs(evidence.tempo_bpm - 120.0) < 1.5
    assert evidence.bars == 4
    step = 60.0 / evidence.tempo_bpm
    expected = int((evidence.duration - evidence.grid_origin) / step) + 1
    assert len(evidence.beats) == expected
    assert all(beat["time"] < evidence.duration for beat in evidence.beats)
    assert evidence.provenance["beats"]["method"] == "uniform-grid-from-global-bpm"
    assert evidence.tempo_score is None
    assert evidence.channels == 1


def test_beat_this_backend_uses_real_markers(fixed_120_audio, beat_file, synth_audio):
    truth = synth_audio["fixed-120"]["truth"]
    backend = BeatThisBackend(beat_file, drums_path=fixed_120_audio)
    evidence = backend.analyze(fixed_120_audio, AnalysisConfig(), lambda *a: None, lambda: False)
    assert [b["time"] for b in evidence.beats] == [round(t, 4) for t in truth["beats"]]
    assert evidence.tempo_bpm == 120.0
    assert evidence.tempo_score is not None and evidence.tempo_score > 0.9
    assert evidence.provenance["beats"]["method"] == "beat-this-markers"
    assert evidence.diagnostics["separated"] is True


def test_analyze_track_lightweight_validates(fixed_120_audio):
    project = analyze_track(fixed_120_audio)
    assert validate_rhythm_v4(project) == []
    assert project["analysis"]["backend"] == "lightweight"
    assert project["schema_version"] == "4.0"
    assert project["grid"]["bars"] == 4
    assert "confidence" not in project["tempo"]
    assert project["meter"] == {"numerator": 4, "denominator": 4}
    assert project["patterns"]["method"] == "bar-rhythm-cosine-v1"
    assert set(project["cues"]) == {"accent", "impact", "scale", "flow", "flash", "bloom"}
    assert all("confidence" not in onset for onset in project["onsets"])
    assert all("accent" not in onset for onset in project["onsets"])


def test_analyze_track_is_deterministic(fixed_120_audio):
    from snapshot_utils import canonical_snapshot

    first = canonical_snapshot(analyze_track(fixed_120_audio))
    second = canonical_snapshot(analyze_track(fixed_120_audio))
    assert first == second


def test_analyze_track_beat_this_route(fixed_120_audio, beat_file):
    project = analyze_track(
        fixed_120_audio,
        AnalysisConfig(backend="beat-this"),
        beat_file=beat_file,
    )
    assert validate_rhythm_v4(project) == []
    assert len(project["beats"]) == 16
    assert project["tempo"]["global_bpm"] == 120.0
    assert project["analysis"]["separation_used"] is False
    assert project["source"]["channels"] == 1
    assert project["analysis"]["provenance"]["beats"]["method"] == "beat-this-markers"
    assert project["beats"][0]["beat_in_bar"] == 1 and project["beats"][0]["downbeat"] is True


def test_project_id_is_content_addressed(fixed_120_audio):
    from beatscope.project import content_hash

    project = analyze_track(fixed_120_audio)
    assert project["project_id"] == content_hash(fixed_120_audio)[:12]


def test_beat_this_requires_beat_file(fixed_120_audio):
    with pytest.raises(ValueError, match="beat file"):
        analyze_track(fixed_120_audio, AnalysisConfig(backend="beat-this"))


def test_invalid_config_rejected(fixed_120_audio):
    with pytest.raises(ValueError):
        AnalysisConfig(subdivision=20).validate()
    with pytest.raises(ValueError):
        AnalysisConfig(backend="magic").validate()
    # from_dict is lenient: unknown keys are dropped so older clients keep working.
    cfg = AnalysisConfig.from_dict({"subdivision": 32, "unknown_key": 1})
    assert cfg.subdivision == 32
    assert AnalysisConfig.from_dict(None) == AnalysisConfig()


def test_resolve_backend_routing(beat_file):
    assert isinstance(resolve_backend(AnalysisConfig()), LightweightBackend)
    assert isinstance(resolve_backend(AnalysisConfig(backend="beat-this"), beat_file), BeatThisBackend)
    demucs_backend = resolve_backend(AnalysisConfig(backend="demucs"))
    assert isinstance(demucs_backend, DemucsBackend)
    assert isinstance(demucs_backend.inner, LightweightBackend)
    routed = resolve_backend(AnalysisConfig(backend="demucs"), beat_file)
    assert isinstance(routed.inner, BeatThisBackend)


@pytest.mark.skipif(_HAS_DEMUCS, reason="demucs is installed")
def test_demucs_backend_surfaces_missing_dependency(fixed_120_audio, tmp_path):
    backend = DemucsBackend(stems_dir=tmp_path / "stems")
    with pytest.raises(RuntimeError):
        backend.analyze(fixed_120_audio, AnalysisConfig(), lambda *a: None, lambda: False)


def test_cancel_callback_stops_analysis(fixed_120_audio):
    with pytest.raises(AnalysisCancelled):
        analyze_track(fixed_120_audio, cancelled=lambda: True)


def test_progress_stages_reported(fixed_120_audio):
    stages: list[str] = []
    analyze_track(fixed_120_audio, progress=lambda stage, value, message: stages.append(stage))
    assert "beatgrid" in stages and "structure" in stages


def test_invalid_rhythm_project_raises(fixed_120_audio, monkeypatch):
    from beatscope import pipeline

    original_builder = pipeline.build_rhythm_project

    def bad_builder(*args, **kwargs):
        project = original_builder(*args, **kwargs)
        project["tempo"].pop("global_bpm")
        return project

    monkeypatch.setattr(pipeline, "build_rhythm_project", bad_builder)
    with pytest.raises(InvalidRhythmProject):
        analyze_track(fixed_120_audio)
