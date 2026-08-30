"""Tests for the unified analysis pipeline (contract, backends, tempo segments)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from beatscope.backends import (
    AnalysisCancelled,
    AnalysisEvidence,
    BeatThisBackend,
    DemucsBackend,
    LightweightBackend,
)
from beatscope.models import AnalysisConfig
from beatscope.pipeline import (
    InvalidRhythmProject,
    analyze_track,
    build_rhythm_project,
    resolve_backend,
)
from beatscope.schema import ANALYZER_VERSION, validate_rhythm_v4
from fixtures.generate_audio import beats_file_content

try:
    import demucs  # noqa: F401
    _HAS_DEMUCS = True
except ImportError:
    _HAS_DEMUCS = False


def _no_op_progress(*_args: Any) -> None:
    return None


def _never_cancelled() -> bool:
    return False


def test_lightweight_backend_produces_evidence(fixed_120_audio):
    evidence = LightweightBackend().analyze(fixed_120_audio, AnalysisConfig(), _no_op_progress, _never_cancelled)
    assert isinstance(evidence, AnalysisEvidence)
    assert abs(evidence.tempo_bpm - 120.0) < 1.5
    assert evidence.bars == 4
    assert 15 <= len(evidence.beats) <= 17  # tracked beats, not a forced uniform count
    assert all(beat["time"] < evidence.duration for beat in evidence.beats)
    assert evidence.provenance["beats"]["method"] == "novelty-guided-dynamic-programming"
    assert evidence.tempo_score is not None and evidence.tempo_score > 0.5
    assert evidence.channels == 1


def test_lightweight_evidence_contains_tempo_segments(fixed_120_audio):
    evidence = LightweightBackend().analyze(fixed_120_audio, AnalysisConfig(), _no_op_progress, _never_cancelled)
    assert len(evidence.tempo_segments) == 1
    segment = evidence.tempo_segments[0]
    assert segment["start"] == 0.0
    assert abs(segment["end"] - evidence.duration) < 1e-6
    assert abs(segment["bpm"] - 120.0) < 2.0
    assert segment["method"] == "local-autocorrelation-viterbi+beat-dp"
    assert segment["score"] is not None
    assert evidence.diagnostics["variable_tempo"] is False


def test_tempo_change_produces_multiple_segments_that_survive_the_pipeline(synth_audio):
    audio = synth_audio["tempo-change"]["audio"]
    evidence = LightweightBackend().analyze(audio, AnalysisConfig(), _no_op_progress, _never_cancelled)
    assert evidence.diagnostics["variable_tempo"] is True
    assert len(evidence.tempo_segments) >= 2
    bpms = [segment["bpm"] for segment in evidence.tempo_segments]
    assert any(abs(bpm - 120.0) < 5.0 for bpm in bpms)
    assert any(abs(bpm - 140.0) < 5.0 for bpm in bpms)

    project = analyze_track(audio)
    assert validate_rhythm_v4(project) == []
    # The pipeline must carry backend segments through untouched, not flatten
    # them into one full-length segment (plan section 16.2).
    assert len(project["tempo"]["segments"]) == len(evidence.tempo_segments)
    assert [round(s["bpm"], 3) for s in project["tempo"]["segments"]] == [
        round(s["bpm"], 3) for s in evidence.tempo_segments
    ]


def test_no_track_fallback_keeps_schema_legal(silence_audio):
    evidence = LightweightBackend().analyze(silence_audio, AnalysisConfig(), _no_op_progress, _never_cancelled)
    assert evidence.beats == []
    assert evidence.tempo_segments == []
    assert evidence.bars == 1
    assert "Insufficient rhythmic evidence; no tracked beats emitted" in evidence.warnings
    assert evidence.provenance["beats"]["method"] == "no-track-global-tempo-fallback"

    project = analyze_track(silence_audio)
    assert validate_rhythm_v4(project) == []
    assert project["beats"] == []
    assert project["grid"]["bars"] == 1
    assert project["tempo"]["segments"] == [{
        "start": 0.0,
        "end": project["source"]["duration"],
        "bpm": 120.0,
        "method": "no-track-global-tempo-fallback",
        "score": None,
    }]


def _evidence_with_segments(
    segments: list[dict[str, Any]],
    duration: float = 16.0,
    **overrides: Any,
) -> AnalysisEvidence:
    fields: dict[str, Any] = {
        "duration": duration,
        "sample_rate": 44100,
        "channels": 1,
        "tempo_bpm": 120.0,
        "grid_origin": 0.0,
        "bars": 1,
        "beats": [],
        "onsets": [],
        "energy": {"fps": 100, "start": 0.0, "bands": {"all": [], "low": [], "mid": [], "high": []}},
        "provenance": {"beats": {"method": "test"}, "onsets": {"method": "test"}},
    }
    fields.update(overrides)
    return AnalysisEvidence(tempo_segments=segments, **fields)


def _step_segment_evidence() -> AnalysisEvidence:
    return _evidence_with_segments([
        {"start": 0.0, "end": 8.0, "bpm": 120.0, "method": "test-tracker", "score": 0.5},
        {"start": 8.0, "end": 12.0, "bpm": 139.9999, "method": "test-tracker", "score": None},
        {"start": 12.0, "end": 16.0, "bpm": 90.0, "method": "test-tracker", "score": 0.75},
    ])


def test_pipeline_preserves_backend_segments_without_flattening():
    project = build_rhythm_project(
        Path("x.wav"), "a" * 64, AnalysisConfig(), LightweightBackend(), _step_segment_evidence(),
    )
    assert validate_rhythm_v4(project) == []
    segments = project["tempo"]["segments"]
    assert [ (s["start"], s["end"], s["bpm"]) for s in segments ] == [
        (0.0, 8.0, 120.0), (8.0, 12.0, 140.0), (12.0, 16.0, 90.0),
    ]
    assert segments[1]["score"] is None and segments[2]["score"] == 0.75


def test_illegal_evidence_segments_raise_instead_of_being_repaired():
    cases = [
        # overlapping coverage
        [
            {"start": 0.0, "end": 9.0, "bpm": 120.0, "method": "m", "score": None},
            {"start": 8.0, "end": 16.0, "bpm": 140.0, "method": "m", "score": None},
        ],
        # gap in coverage
        [{"start": 0.5, "end": 16.0, "bpm": 120.0, "method": "m", "score": None}],
        # illegal BPM
        [{"start": 0.0, "end": 16.0, "bpm": 500.0, "method": "m", "score": None}],
        # does not reach the duration
        [{"start": 0.0, "end": 15.0, "bpm": 120.0, "method": "m", "score": None}],
        # unordered
        [
            {"start": 4.0, "end": 8.0, "bpm": 120.0, "method": "m", "score": None},
            {"start": 0.0, "end": 4.0, "bpm": 120.0, "method": "m", "score": None},
        ],
        # missing method
        [{"start": 0.0, "end": 16.0, "bpm": 120.0, "score": None}],
    ]
    for segments in cases:
        evidence = _evidence_with_segments(segments)
        with pytest.raises(ValueError):
            build_rhythm_project(
                Path("x.wav"), "a" * 64, AnalysisConfig(), LightweightBackend(), evidence,
            )


def test_beat_this_markers_keep_tempo_changes(synth_audio, tmp_path):
    case = synth_audio["tempo-change"]
    beats_path = tmp_path / "tempo-change.beats"
    beats_path.write_text(beats_file_content(case["truth"]["beats"]), encoding="utf-8")
    evidence = BeatThisBackend(beats_path, drums_path=case["audio"]).analyze(
        case["audio"], AnalysisConfig(), _no_op_progress, _never_cancelled,
    )
    assert len(evidence.tempo_segments) == 2
    assert abs(evidence.tempo_segments[0]["bpm"] - 120.0) < 1.0
    assert abs(evidence.tempo_segments[1]["bpm"] - 140.0) < 1.0
    assert evidence.diagnostics["variable_tempo"] is True
    assert evidence.tempo_segments[0]["method"] == "beat-marker-intervals"


def test_lightweight_provenance_and_diagnostics_are_real(fixed_120_audio):
    project = analyze_track(fixed_120_audio)
    provenance = project["analysis"]["provenance"]
    assert provenance["beats"]["tempo_source"] == "local-autocorrelation-viterbi"
    assert provenance["beats"]["onset_alignment"] == "bounded-local-maximum"
    assert provenance["meter_phase"]["method"] == "four-four-cycle-from-first-tracked-beat"
    assert provenance["meter_phase"]["inferred"] is True

    diagnostics = project["analysis"]["diagnostics"]
    assert diagnostics["beat_method"] == "novelty-guided-dynamic-programming"
    assert diagnostics["candidate_windows"] > 0
    assert diagnostics["tracked_beats"] == len(project["beats"])
    assert diagnostics["tempo_path_changes"] == len(project["tempo"]["segments"]) - 1
    assert diagnostics["score_semantics"] == "normalized path support; not probability"
    assert diagnostics["tracking_parameters"]["min_bpm"] == 50.0
    assert diagnostics["tracking_parameters"]["max_bpm"] == 220.0
    assert diagnostics["tracking_parameters"]["tempo_window_seconds"] == 6.0
    assert LightweightBackend.version == "2.0"
    # No absolute paths or debug arrays leak into diagnostics.
    serialized = str(diagnostics)
    assert str(fixed_120_audio) not in serialized


def test_analyzer_version_bump_changes_cache_key():
    from beatscope.project import compute_cache_key

    assert ANALYZER_VERSION == "0.6.0"
    sha = "0" * 64
    config = {"subdivision": 16}
    assert (
        compute_cache_key(sha, config, analyzer_ver="0.4.0")
        != compute_cache_key(sha, config, analyzer_ver=ANALYZER_VERSION)
    )


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
