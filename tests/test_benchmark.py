"""Benchmark module tests: matching, metrics, gates, and one end-to-end run."""
from __future__ import annotations

from pathlib import Path

import pytest

from beatscope.benchmark import (
    BEAT_TOLERANCE_S,
    SILENCE_FALSE_EVENT_LIMIT,
    apply_baseline_gate,
    evaluate_case,
    match_events,
    _prf,
)

try:
    import librosa  # noqa: F401
    _HAS_LIBROSA = True
except ImportError:
    _HAS_LIBROSA = False

requires_librosa = pytest.mark.skipif(not _HAS_LIBROSA, reason="librosa is not installed")


def test_match_events_pairs_within_tolerance():
    reference = [0.0, 0.5, 1.0]
    predicted = [0.01, 0.48, 0.97, 1.5]
    pairs = match_events(reference, predicted, 0.05)
    assert pairs == [(0.0, 0.01), (0.5, 0.48), (1.0, 0.97)]


def test_match_events_tolerance_boundary():
    # Exactly at the tolerance still matches; one microsecond beyond does not.
    assert match_events([0.0], [BEAT_TOLERANCE_S], BEAT_TOLERANCE_S) == [(0.0, BEAT_TOLERANCE_S)]
    assert match_events([0.0], [BEAT_TOLERANCE_S + 0.001], BEAT_TOLERANCE_S) == []


def test_match_events_skips_unmatched_sides():
    reference = [0.0, 1.0, 2.0]
    predicted = [0.01, 0.02, 1.01]
    pairs = match_events(reference, predicted, 0.05)
    assert pairs == [(0.0, 0.01), (1.0, 1.01)]


def test_prf_edges():
    assert _prf(0, 0, 0) is None  # silence on both sides: nothing to measure
    perfect = _prf(5, 5, 5)
    assert perfect["precision"] == 1.0 and perfect["recall"] == 1.0 and perfect["f1"] == 1.0
    false_positives = _prf(4, 5, 9)
    # _prf rounds to 4 decimals for stable reports.
    assert false_positives["precision"] == pytest.approx(4 / 9, abs=1e-4)
    assert false_positives["recall"] == pytest.approx(4 / 5, abs=1e-4)
    assert false_positives["f1"] == pytest.approx(2 * (4 / 9) * (4 / 5) / ((4 / 9) + (4 / 5)), abs=1e-4)


def test_apply_baseline_gate_flags_regression():
    baseline = {"cases": [{"name": "fixed-120", "beat": {"f1": 0.97}}]}
    cases = [{"name": "fixed-120", "beat": {"f1": 0.70}, "gates_failed": []}]
    apply_baseline_gate(cases, baseline)
    assert cases[0]["gates_failed"] == ["beat-f1-regression"]

    # Small drift within the regression window is report-only.
    cases = [{"name": "fixed-120", "beat": {"f1": 0.90}, "gates_failed": []}]
    apply_baseline_gate(cases, baseline)
    assert cases[0]["gates_failed"] == []


def _fixed_120_truth():
    beats = [round(i * 0.5, 6) for i in range(16)]
    return {
        "name": "fixed-120",
        "purpose": "test",
        "duration": 8.0,
        "bpm": 120.0,
        "beats": beats,
        "onsets": list(beats),
        "tempo_segments": [{"start": 0.0, "end": 8.0, "bpm": 120.0}],
    }


@requires_librosa
def test_evaluate_case_gates_fire_on_tampered_projects(fixed_120_audio):
    from beatscope.pipeline import analyze_track

    truth = _fixed_120_truth()
    project = analyze_track(fixed_120_audio)
    assert evaluate_case("fixed-120", truth, project)["gates_failed"] == []

    # Beats shifted beyond the match tolerance collapse F1 to zero.
    shifted = {**project, "beats": [{**b, "time": b["time"] + 0.4} for b in project["beats"]]}
    assert "beat-f1-floor" in evaluate_case("fixed-120", truth, shifted)["gates_failed"]

    # A grossly wrong global BPM trips the fixed-tempo gate.
    wrong_bpm = {**project, "tempo": {**project["tempo"], "global_bpm": 200.0}}
    assert "fixed-bpm-gross-error" in evaluate_case("fixed-120", truth, wrong_bpm)["gates_failed"]

    # Any forbidden key anywhere makes the project invalid -> schema gate.
    poisoned = {**project, "onsets": [{**project["onsets"][0], "accent": True}, *project["onsets"][1:]]}
    assert "invalid-schema" in evaluate_case("fixed-120", truth, poisoned)["gates_failed"]


def _silence_project(false_beats: int):
    beats = []
    for i in range(false_beats):
        beats.append({
            "time": round(i * 0.25, 4),
            "index": i,
            "bar": i // 4 + 1,
            "beat_in_bar": i % 4 + 1,
            "downbeat": i % 4 == 0,
        })
    return {
        "schema_version": "4.0",
        "project_id": "a1b2c3d4e5f6",
        "source": {"display_name": "s.wav", "duration": 12.0, "sample_rate": 44100, "channels": 2, "sha256": "ab" * 32},
        "analysis": {
            "backend": "lightweight",
            "pipeline_version": "0.4.0",
            "created_at": "2026-08-29T00:00:00Z",
            "warnings": [],
            "separation_used": False,
            "provenance": {"beats": {"method": "test"}, "onsets": {"method": "test"}},
        },
        "tempo": {"global_bpm": 120.0, "segments": [{"start": 0.0, "end": 12.0, "bpm": 120.0, "method": "test", "score": None}]},
        "meter": {"numerator": 4, "denominator": 4},
        "grid": {"origin": 0.0, "default_subdivision": 16, "bars": 3},
        "beats": beats,
        "onsets": [],
        "energy": {"fps": 100, "start": 0.0, "bands": {"all": [], "low": [], "mid": [], "high": []}},
        "patterns": {"method": "test", "bars": []},
        "cues": {"accent": [], "impact": [], "scale": [], "flow": [], "flash": [], "bloom": []},
        "exports": {},
    }


def test_evaluate_case_silence_gate():
    silence_truth = {"name": "silence", "purpose": "test", "duration": 4.0, "bpm": None,
                     "beats": [], "onsets": [], "tempo_segments": [{"start": 0.0, "end": 4.0, "bpm": None}]}
    quiet = evaluate_case("silence", silence_truth, _silence_project(2))
    assert quiet["gates_failed"] == []
    assert quiet["silence_false_events"] == 2

    loud = evaluate_case("silence", silence_truth, _silence_project(SILENCE_FALSE_EVENT_LIMIT + 1))
    assert "silence-false-events" in loud["gates_failed"]


@requires_librosa
def test_run_benchmark_end_to_end(tmp_path, synth_audio):
    from beatscope.benchmark import run_benchmark

    fixtures_dir = Path(synth_audio["fixed-120"]["audio"]).parent
    results = run_benchmark(output_dir=tmp_path / "results", fixtures_dir=fixtures_dir)

    assert results["gates"]["failed"] == []
    for case in results["cases"]:
        assert case["gates_failed"] == [], f"{case['name']}: {case['gates_failed']}"

    assert (tmp_path / "results" / "benchmark-results.json").is_file()
    markdown = (tmp_path / "results" / "benchmark-results.md").read_text(encoding="utf-8")
    assert "| fixed-120 |" in markdown
    assert "| silence |" in markdown
