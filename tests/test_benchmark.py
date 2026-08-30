"""Benchmark module tests: matching, metrics, gates, fixtures, baseline governance."""
from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np
import pytest

from beatscope.benchmark import (
    BASELINE_SCHEMA,
    BEAT_TOLERANCE_S,
    FIXED_F1_REGRESSION,
    SILENCE_FALSE_EVENT_LIMIT,
    apply_baseline_gates,
    baseline_manifest_mismatch,
    build_baseline_entry,
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

REPO_ROOT = Path(__file__).resolve().parent.parent
TRUTH_PATH = REPO_ROOT / "tests" / "fixtures" / "truth" / "ground-truth.json"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


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


def _case(name: str, f1: float | None, mae: float | None = None, **extra):
    case = {"name": name, "beat": {"f1": f1, "mae_ms": mae}, "gates_failed": []}
    case.update(extra)
    return case


def test_apply_baseline_gates_flags_f1_regression():
    baseline = {"cases": {"fixed-120": {"beat_f1": 0.97, "beat_mae_ms": 12.0, "gates": {}}}}
    cases = [_case("fixed-120", 0.70)]
    apply_baseline_gates(cases, baseline)
    assert cases[0]["gates_failed"] == ["beat-f1-regression"]

    # Small drift within the regression window is report-only.
    cases = [_case("fixed-120", 0.95)]
    apply_baseline_gates(cases, baseline)
    assert cases[0]["gates_failed"] == []


def test_apply_baseline_gates_flags_mae_regression():
    baseline = {"cases": {"fixed-120": {"beat_f1": 0.97, "beat_mae_ms": 12.0, "gates": {}}}}
    cases = [_case("fixed-120", 0.97, mae=12.0 + 16.0)]
    apply_baseline_gates(cases, baseline)
    assert cases[0]["gates_failed"] == ["beat-mae-regression"]

    cases = [_case("fixed-120", 0.97, mae=12.0 + 14.0)]
    apply_baseline_gates(cases, baseline)
    assert cases[0]["gates_failed"] == []


def test_apply_baseline_gates_enforce_declared_gates():
    baseline = {"cases": {
        "tempo-change": {
            "beat_f1": 0.7, "beat_mae_ms": 30.0,
            "gates": {
                "beat_f1_min": 0.55,
                "change_point_error_s_max": 1.0,
                "seam_missing_beats_max": 1,
                "seam_extra_beats_max": 1,
            },
        },
        "gradual-drift": {"beat_f1": 0.7, "gates": {"tempo_mae_bpm_max": 6.0}},
        "micro-drift": {"beat_f1": 0.9, "gates": {"segments_max": 3}},
        "octave-trap": {"beat_f1": 0.9, "gates": {"octave_errors_max": 0}},
    }}
    cases = [
        _case("tempo-change", 0.7, 30.0,
              tempo_segments={"change_point_error_s": 0.4},
              seams=[{"time": 8.0, "missing_beats": 1, "extra_beats": 0}]),
        _case("gradual-drift", 0.7, 40.0, tempo_curve={"tempo_mae_bpm": 5.0}),
        _case("micro-drift", 0.9, 10.0, segment_count=2),
        _case("octave-trap", 0.9, 10.0, octave_errors={"interval": 0, "tempo_path_switches": 0}),
    ]
    apply_baseline_gates(cases, baseline)
    assert all(case["gates_failed"] == [] for case in cases)

    # Now break each declared bound one at a time.
    cases[0] = _case("tempo-change", 0.5, 30.0,
                     tempo_segments={"change_point_error_s": 0.4}, seams=[])
    apply_baseline_gates(cases, baseline)
    assert "beat-f1-below-baseline-minimum" in cases[0]["gates_failed"]

    cases[0] = _case("tempo-change", 0.7, 30.0,
                     tempo_segments={"change_point_error_s": 1.5}, seams=[])
    apply_baseline_gates(cases, baseline)
    assert "change-point-error-above-baseline-maximum" in cases[0]["gates_failed"]

    cases[0] = _case("tempo-change", 0.7, 30.0,
                     tempo_segments={"change_point_error_s": 0.4},
                     seams=[{"time": 8.0, "missing_beats": 2, "extra_beats": 0},
                            {"time": 8.0, "missing_beats": 0, "extra_beats": 2}])
    apply_baseline_gates(cases, baseline)
    assert "seam-missing-beats-above-baseline-maximum" in cases[0]["gates_failed"]
    assert "seam-extra-beats-above-baseline-maximum" in cases[0]["gates_failed"]

    cases[1] = _case("gradual-drift", 0.7, 40.0, tempo_curve={"tempo_mae_bpm": 7.0})
    apply_baseline_gates(cases, baseline)
    assert "tempo-mae-above-baseline-maximum" in cases[1]["gates_failed"]

    cases[2] = _case("micro-drift", 0.9, 10.0, segment_count=4)
    apply_baseline_gates(cases, baseline)
    assert "excess-tempo-segments" in cases[2]["gates_failed"]

    cases[3] = _case("octave-trap", 0.9, 10.0, octave_errors={"interval": 1, "tempo_path_switches": 0})
    apply_baseline_gates(cases, baseline)
    assert "octave-errors-above-baseline-maximum" in cases[3]["gates_failed"]


def test_apply_baseline_gates_ignores_unknown_cases_and_none_values():
    baseline = {"cases": {"unknown-case": {"beat_f1": 0.9, "gates": {"beat_f1_min": 0.5}}}}
    cases = [_case("fixed-120", None)]
    apply_baseline_gates(cases, baseline)
    assert cases[0]["gates_failed"] == []


def test_baseline_manifest_mismatch():
    assert baseline_manifest_mismatch(None, "abc")
    assert not baseline_manifest_mismatch({"fixture_manifest_sha256": "abc"}, "abc")
    assert baseline_manifest_mismatch({"fixture_manifest_sha256": "abc"}, "xyz")
    assert baseline_manifest_mismatch({"fixture_manifest_sha256": ""}, "xyz")


def test_build_baseline_entry_records_values_and_preserves_declared_gates():
    entry = build_baseline_entry(_case("fixed-120", 0.97, 12.0, bpm_error=0.0, segment_count=1))
    assert entry == {
        "beat_f1": 0.97,
        "beat_mae_ms": 12.0,
        "bpm_error": 0.0,
        "segment_count": 1,
        "gates": {},
    }
    declared = {"beat_f1_min": 0.9, "segments_max": 2}
    preserved = build_baseline_entry(
        _case("fixed-120", 0.99, 5.0, bpm_error=0.0, segment_count=1),
        gates=declared,
    )
    assert preserved["gates"] == declared
    assert preserved["gates"] is not declared


def test_baseline_schema_constant():
    assert BASELINE_SCHEMA == "beatscope-benchmark-baseline-1"
    assert FIXED_F1_REGRESSION == 0.03


def test_pcm_conversion_rounds_half_to_even():
    from tests.fixtures.generate_audio import float_to_pcm16

    # 1.5 quantization units -> rounds to 2 (truncation would give 1).
    signal = np.array([1.5 / 32767.0, -1.5 / 32767.0])
    pcm = float_to_pcm16(signal)
    assert int(pcm[0]) == 2
    assert int(pcm[1]) == -2


def test_fixture_generation_is_byte_deterministic(tmp_path):
    from tests.fixtures.generate_audio import generate_all

    first = generate_all(tmp_path / "a")
    second = generate_all(tmp_path / "b")
    for name in first:
        assert Path(first[name]["audio"]).read_bytes() == Path(second[name]["audio"]).read_bytes()
        assert first[name]["truth"] == second[name]["truth"]


def test_fixture_truth_invariants(tmp_path):
    from tests.fixtures.generate_audio import generate_all

    fixtures = generate_all(tmp_path / "a")
    for name, item in fixtures.items():
        truth = item["truth"]
        beats = [float(t) for t in truth["beats"]]
        assert all(b2 > b1 for b1, b2 in zip(beats, beats[1:])), name
        assert all(0.0 <= t < truth["duration"] for t in beats), name

        beat_in_bar = truth["beat_in_bar"]
        assert beat_in_bar == [i % 4 + 1 for i in range(len(beats))], name
        downbeats = truth["downbeats"]
        assert downbeats == [t for i, t in enumerate(beats) if i % 4 == 0], name

        segments = truth["tempo_segments"]
        if segments:
            assert segments[0]["start"] == 0.0, name
            assert segments[-1]["end"] == truth["duration"], name
            for left, right in zip(segments, segments[1:]):
                assert left["end"] == right["start"], name

        with wave.open(str(item["audio"]), "rb") as handle:
            assert handle.getnframes() == truth["frame_count"], name
            assert handle.getframerate() == truth["sample_rate"], name
        assert math.isclose(
            truth["frame_count"] / truth["sample_rate"], truth["duration"], abs_tol=1e-9
        ), name
        assert truth["generator_version"] == "2", name
        assert truth["seed"] == 20260830, name


def test_variable_tempo_truth_curves(tmp_path):
    from tests.fixtures.generate_audio import generate_all

    fixtures = generate_all(tmp_path / "a")

    step = fixtures["tempo-change"]["truth"]
    anchor_at = {a["time"]: a["bpm"] for a in step["tempo_curve"]}
    assert anchor_at[0.0] == 120.0
    assert anchor_at[7.5] == 120.0
    assert anchor_at[8.5] == 140.0
    assert anchor_at[15.5] == 140.0
    assert 8.0 not in anchor_at  # boundary is excluded on purpose

    drift = fixtures["gradual-drift"]["truth"]
    assert drift["tempo_curve"][0]["bpm"] == 100.0
    assert drift["tempo_curve"][-1]["bpm"] == pytest.approx(100.0 + 40.0 * (23.5 / 24.0), abs=0.01)
    # Recurrence under a rising curve: intervals must shrink overall.
    intervals = [b - a for a, b in zip(drift["beats"], drift["beats"][1:])]
    assert intervals[-1] < intervals[0]

    micro = fixtures["micro-drift"]["truth"]
    micro_intervals = [b - a for a, b in zip(micro["beats"], micro["beats"][1:])]
    assert max(micro_intervals) - min(micro_intervals) < 0.05  # tiny wiggle only

    trap = fixtures["octave-trap"]["truth"]
    assert len(trap["onsets"]) > len(trap["beats"])  # half-beat transients exist


@requires_librosa
def test_committed_truth_matches_generator(tmp_path):
    from tests.fixtures.generate_audio import generate_all

    generate_all(tmp_path / "a")
    generated = (tmp_path / "a" / "ground-truth.json").read_bytes()
    assert TRUTH_PATH.read_bytes() == generated


def test_ci_workflow_never_accepts_baseline():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "--accept-baseline" not in workflow
    assert "beatscope.cli benchmark" in workflow


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

    # v4 forbids 'accent' on onsets (accents belong in cues) -> schema gate.
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


def test_evaluate_case_report_metrics_on_synthetic_project():
    truth = {
        "name": "tempo-change",
        "purpose": "test",
        "duration": 8.0,
        "bpm": None,
        "beats": [0.0, 0.5, 1.0, 1.5, 2.0],
        "downbeats": [0.0, 2.0],
        "beat_in_bar": [1, 2, 3, 4, 1],
        "onsets": [0.0, 0.5, 1.0, 1.5, 2.0],
        "tempo_segments": [
            {"start": 0.0, "end": 1.0, "bpm": 120.0},
            {"start": 1.0, "end": 8.0, "bpm": 150.0},
        ],
        "tempo_curve": [{"time": 0.0, "bpm": 120.0}, {"time": 2.0, "bpm": 150.0}],
    }
    project = _silence_project(0)
    project["beats"] = [
        {"time": t, "index": i, "bar": 1, "beat_in_bar": bib, "downbeat": bib == 1}
        for i, (t, bib) in enumerate([(0.0, 1), (0.5, 2), (1.0, 3), (1.5, 4), (2.0, 1)])
    ]
    project["onsets"] = [
        {"id": i + 1, "time": t, "strength": 0.8,
         "bands": {"all": 0.8, "low": 0.1, "mid": 0.5, "high": 0.2}}
        for i, t in enumerate([0.0, 0.5, 1.0, 1.5, 2.0])
    ]
    project["tempo"] = {
        "global_bpm": 120.0,
        "segments": [
            {"start": 0.0, "end": 1.2, "bpm": 121.0, "method": "m", "score": None},
            {"start": 1.2, "end": 8.0, "bpm": 149.0, "method": "m", "score": None},
        ],
    }
    case = evaluate_case("tempo-change", truth, project)
    assert case["gates_failed"] == []
    assert case["segment_count"] == 2
    assert case["tempo_segments"]["change_point_error_s"] == 0.2
    assert case["tempo_curve"]["tempo_mae_bpm"] == 1.0
    assert case["tempo_curve"]["direction_agreement"] == 1.0
    assert case["beat_in_bar_accuracy"] == 1.0
    assert case["octave_errors"]["interval"] == 0
    assert case["seams"] and case["seams"][0]["time"] == 1.0
    assert case["seams"][0]["missing_beats"] == 0
    assert case["downbeats"]["f1"] == 1.0


def _silence_only_fixtures(silence_audio):
    """A minimal fixture dict so baseline-governance tests skip real analysis."""
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))["silence"]
    return {"silence": {"audio": str(silence_audio), "truth": truth}}


@requires_librosa
def test_accept_baseline_writes_then_compares(tmp_path, monkeypatch, silence_audio):
    from beatscope import benchmark as benchmark_module

    baseline_path = tmp_path / "baseline.json"
    fixtures = _silence_only_fixtures(silence_audio)
    monkeypatch.setattr(benchmark_module, "_load_fixtures", lambda _: fixtures)

    results = benchmark_module.run_benchmark(
        output_dir=tmp_path / "out", baseline_path=baseline_path, accept_baseline=True,
    )
    assert results["baseline"]["accepted"] is True
    document = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert document["schema"] == BASELINE_SCHEMA
    assert document["analyzer_version"]
    assert "silence" in document["cases"]
    assert document["fixture_manifest_sha256"]

    # A normal run against the just-accepted baseline must pass cleanly.
    compare = benchmark_module.run_benchmark(output_dir=tmp_path / "out2", baseline_path=baseline_path)
    assert compare["gates"]["failed"] == []
    assert compare["baseline"]["manifest_match"] is True


@requires_librosa
def test_normal_benchmark_fails_closed_without_baseline(tmp_path, monkeypatch, silence_audio):
    from beatscope import benchmark as benchmark_module

    missing = tmp_path / "missing-baseline.json"
    monkeypatch.setattr(
        benchmark_module, "_load_fixtures", lambda _: _silence_only_fixtures(silence_audio)
    )

    results = benchmark_module.run_benchmark(
        output_dir=tmp_path / "out", baseline_path=missing,
    )
    assert results["baseline"]["valid"] is False
    assert results["baseline"]["manifest_match"] is False
    assert "baseline-missing" in results["gates"]["failed"]


@requires_librosa
def test_normal_benchmark_rejects_invalid_and_incomplete_baseline(
    tmp_path, monkeypatch, silence_audio,
):
    from beatscope import benchmark as benchmark_module

    fixtures = _silence_only_fixtures(silence_audio)
    monkeypatch.setattr(benchmark_module, "_load_fixtures", lambda _: fixtures)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{broken", encoding="utf-8")
    invalid_results = benchmark_module.run_benchmark(
        output_dir=tmp_path / "invalid-out", baseline_path=invalid,
    )
    assert "baseline-invalid" in invalid_results["gates"]["failed"]

    incomplete = tmp_path / "incomplete.json"
    truth_sha = benchmark_module._truth_manifest_sha(fixtures)
    incomplete.write_text(json.dumps({
        "schema": BASELINE_SCHEMA,
        "fixture_manifest_sha256": truth_sha,
        "analyzer_version": "0.6.0",
        "cases": {},
    }), encoding="utf-8")
    incomplete_results = benchmark_module.run_benchmark(
        output_dir=tmp_path / "incomplete-out", baseline_path=incomplete,
    )
    assert "baseline-incomplete" in incomplete_results["gates"]["failed"]


@requires_librosa
def test_accept_baseline_preserves_and_enforces_declared_gates(
    tmp_path, monkeypatch, silence_audio,
):
    from beatscope import benchmark as benchmark_module

    fixtures = _silence_only_fixtures(silence_audio)
    monkeypatch.setattr(benchmark_module, "_load_fixtures", lambda _: fixtures)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({
        "schema": BASELINE_SCHEMA,
        "fixture_generator_version": "2",
        "fixture_manifest_sha256": benchmark_module._truth_manifest_sha(fixtures),
        "analyzer_version": "0.4.0",
        "cases": {
            "silence": {
                "beat_f1": 0.0,
                "beat_mae_ms": None,
                "bpm_error": None,
                "segment_count": 1,
                "gates": {"segments_max": 1},
            }
        },
    }), encoding="utf-8")

    accepted = benchmark_module.run_benchmark(
        output_dir=tmp_path / "accepted", baseline_path=baseline_path,
        accept_baseline=True,
    )
    assert accepted["baseline"]["accepted"] is True
    document = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert document["cases"]["silence"]["gates"] == {"segments_max": 1}

    document["cases"]["silence"]["gates"] = {"segments_max": 0}
    baseline_path.write_text(json.dumps(document), encoding="utf-8")
    refused = benchmark_module.run_benchmark(
        output_dir=tmp_path / "refused", baseline_path=baseline_path,
        accept_baseline=True,
    )
    assert refused["baseline"]["accepted"] is False
    assert "excess-tempo-segments" in refused["baseline"]["gates_failed"]


@requires_librosa
def test_accept_baseline_refuses_on_absolute_gate(tmp_path, monkeypatch, silence_audio):
    from beatscope import benchmark as benchmark_module

    baseline_path = tmp_path / "baseline.json"

    def broken_analyze(_path):
        raise RuntimeError("synthetic analyzer crash")

    monkeypatch.setattr(benchmark_module, "_load_fixtures", lambda _: _silence_only_fixtures(silence_audio))
    monkeypatch.setattr(benchmark_module, "analyze_track", broken_analyze)

    results = benchmark_module.run_benchmark(
        output_dir=tmp_path / "out", baseline_path=baseline_path, accept_baseline=True,
    )
    assert results["baseline"]["accepted"] is False
    assert "crash" in results["baseline"]["gates_failed"]
    assert not baseline_path.exists()  # the swap must not happen


@requires_librosa
def test_baseline_fixture_mismatch_blocks_run(tmp_path, monkeypatch, silence_audio):
    from beatscope import benchmark as benchmark_module

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({
        "schema": BASELINE_SCHEMA,
        "fixture_manifest_sha256": "0" * 64,
        "analyzer_version": "0.4.0",
        "cases": {},
    }), encoding="utf-8")

    monkeypatch.setattr(benchmark_module, "_load_fixtures", lambda _: _silence_only_fixtures(silence_audio))
    results = benchmark_module.run_benchmark(output_dir=tmp_path / "out", baseline_path=baseline_path)
    assert results["baseline"]["manifest_match"] is False
    assert "baseline-fixture-mismatch" in results["gates"]["failed"]


@requires_librosa
def test_run_benchmark_end_to_end(tmp_path, synth_audio):
    from beatscope.benchmark import run_benchmark

    fixtures_dir = Path(synth_audio["fixed-120"]["audio"]).parent
    results = run_benchmark(output_dir=tmp_path / "results", fixtures_dir=fixtures_dir)

    assert results["gates"]["failed"] == []
    assert results["baseline"]["manifest_match"] is True
    assert len(results["cases"]) == 11
    for case in results["cases"]:
        assert case["gates_failed"] == [], f"{case['name']}: {case['gates_failed']}"

    by_name = {case["name"]: case for case in results["cases"]}
    assert by_name["tempo-change"]["seams"], "tempo-change must report seam metrics"
    assert by_name["tempo-change"]["seams"][0]["time"] == 8.0
    assert by_name["gradual-drift"]["tempo_curve"]["anchors_measured"] > 0
    assert by_name["micro-drift"]["tempo_curve"]["anchors_measured"] > 0
    assert by_name["fixed-120"]["downbeats"]["f1"] is not None

    assert (tmp_path / "results" / "benchmark-results.json").is_file()
    markdown = (tmp_path / "results" / "benchmark-results.md").read_text(encoding="utf-8")
    assert "| fixed-120 |" in markdown
    assert "| silence |" in markdown
    assert "| gradual-drift |" in markdown
