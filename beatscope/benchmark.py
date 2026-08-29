"""Algorithm-quality benchmark: analyzer output vs synthetic ground truth.

This is not a unit test suite (plan section 26): unit tests pin behaviour,
the benchmark measures how far analysis lands from known truth. Run it with
``beatscope benchmark``; it writes benchmark-results.json and
benchmark-results.md and exits non-zero when a hard gate fails (section 30).
"""
from __future__ import annotations

import datetime
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from .beatgrid import quantize_to_beat_grid
from .pipeline import analyze_track
from .schema import ANALYZER_VERSION, validate_rhythm_v4

# Plan section 28: suggested match tolerances.
BEAT_TOLERANCE_S = 0.070
ONSET_TOLERANCE_S = 0.050

# Plan section 30 hard gates ("must block the commit" category).
SILENCE_FALSE_EVENT_LIMIT = 20
FIXED_BPM_GATE_BPM = 5.0
BEAT_F1_FLOOR = 0.5
BEAT_F1_REGRESSION = 0.15


def match_events(
    reference: list[float], predicted: list[float], tolerance: float
) -> list[tuple[float, float]]:
    """Greedy two-pointer match of two sorted event lists (plan section 27).

    Returns (reference_time, predicted_time) pairs within ``tolerance``.
    Dense onset streams may admit a globally better assignment, but ordered
    synthetic events make the greedy result deterministic and explainable.
    """
    i = 0
    j = 0
    pairs: list[tuple[float, float]] = []

    while i < len(reference) and j < len(predicted):
        delta = predicted[j] - reference[i]

        if abs(delta) <= tolerance:
            pairs.append((reference[i], predicted[j]))
            i += 1
            j += 1
        elif predicted[j] < reference[i] - tolerance:
            j += 1
        else:
            i += 1

    return pairs


def _prf(matched: int, n_reference: int, n_predicted: int) -> dict[str, Any] | None:
    """Precision / Recall / F1 from match counts. None when both sides are empty."""
    if n_reference == 0 and n_predicted == 0:
        return None
    precision = matched / n_predicted if n_predicted else 0.0
    recall = matched / n_reference if n_reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "matched": matched,
        "predicted": n_predicted,
        "truth": n_reference,
    }


def _timing_mae_ms(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    return round(sum(abs(predicted - reference) for reference, predicted in pairs) / len(pairs) * 1000.0, 2)


def _evaluate_tempo_segments(truth_segments: list[dict[str, Any]], project: dict[str, Any]) -> dict[str, Any]:
    """Change-point error, per-segment BPM error, and merge detection (section 28)."""
    predicted_segments = project.get("tempo", {}).get("segments", [])
    merged = len(predicted_segments) < 2

    change_point_error = None
    if not merged and truth_segments:
        truth_change = truth_segments[0].get("end")
        if truth_change is not None:
            change_point_error = round(abs(float(predicted_segments[0]["end"]) - float(truth_change)), 4)

    segment_bpm_errors: list[float | None] = []
    for segment in truth_segments:
        bpm = segment.get("bpm")
        if bpm is None:
            continue
        middle = (float(segment["start"]) + float(segment["end"])) / 2.0
        for predicted_segment in predicted_segments:
            if float(predicted_segment["start"]) <= middle <= float(predicted_segment["end"]):
                segment_bpm_errors.append(round(abs(float(predicted_segment["bpm"]) - float(bpm)), 3))
                break
        else:
            segment_bpm_errors.append(None)

    return {
        "change_point_error_s": change_point_error,
        "segment_bpm_errors": segment_bpm_errors,
        "merged_single_segment": merged,
    }


def evaluate_case(name: str, truth: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    """Score one case's project against its ground truth (plan section 28)."""
    case: dict[str, Any] = {
        "name": name,
        "purpose": truth.get("purpose", ""),
        "schema_errors": validate_rhythm_v4(project),
    }

    bpm_error = None
    if truth.get("bpm") is not None:
        bpm_error = round(abs(float(project["tempo"]["global_bpm"]) - float(truth["bpm"])), 3)
    case["bpm_error"] = bpm_error

    truth_beats = [float(t) for t in truth.get("beats", [])]
    predicted_beats = [float(beat["time"]) for beat in project.get("beats", [])]
    beat_pairs = match_events(truth_beats, predicted_beats, BEAT_TOLERANCE_S)
    case["beat"] = {
        **(_prf(len(beat_pairs), len(truth_beats), len(predicted_beats)) or {}),
        "mae_ms": _timing_mae_ms(beat_pairs),
    }

    truth_onsets = [float(t) for t in truth.get("onsets", [])]
    predicted_onsets = [float(onset["time"]) for onset in project.get("onsets", [])]
    onset_pairs = match_events(truth_onsets, predicted_onsets, ONSET_TOLERANCE_S)
    case["onset"] = {
        **(_prf(len(onset_pairs), len(truth_onsets), len(predicted_onsets)) or {}),
        "mae_ms": _timing_mae_ms(onset_pairs),
    }

    # Quantization offset error: how far the snapped predicted onset lands
    # from the true event time. Only measurable with a predicted grid.
    case["quantization"] = None
    if predicted_beats and truth_onsets and onset_pairs:
        matched_truth_times = {reference for reference, _ in onset_pairs}
        errors = []
        for onset in project.get("onsets", []):
            onset_time = float(onset["time"])
            hit = min(truth_onsets, key=lambda t: abs(t - onset_time))
            if abs(hit - onset_time) > ONSET_TOLERANCE_S or hit not in matched_truth_times:
                continue
            quantized = quantize_to_beat_grid(
                onset_time, project.get("beats", []),
                subdivision=int(project.get("grid", {}).get("default_subdivision", 16)),
                default_bpm=float(project["tempo"]["global_bpm"]),
                default_origin=float(project.get("grid", {}).get("origin", 0.0)),
            )
            errors.append(abs(float(quantized["quantized_time"]) - hit))
        if errors:
            case["quantization"] = {"offset_mae_ms": round(sum(errors) / len(errors) * 1000.0, 2), "measured": len(errors)}

    truth_segments = truth.get("tempo_segments", [])
    case["tempo_segments"] = None
    if len(truth_segments) >= 2:
        case["tempo_segments"] = _evaluate_tempo_segments(truth_segments, project)

    case["silence_false_events"] = None
    if not truth_beats and not truth_onsets:
        case["silence_false_events"] = len(predicted_beats) + len(predicted_onsets)

    gates: list[str] = []
    multi_segment_truth = len(truth.get("tempo_segments", [])) >= 2
    if case["schema_errors"]:
        gates.append("invalid-schema")
    if bpm_error is not None and bpm_error > FIXED_BPM_GATE_BPM:
        gates.append("fixed-bpm-gross-error")
    # Section 30: tempo-change precision is report-only until segment
    # detection lands, so the F1 floor only guards fixed-tempo cases.
    if truth_beats and not multi_segment_truth and case["beat"].get("f1", 0.0) < BEAT_F1_FLOOR:
        gates.append("beat-f1-floor")
    if case["silence_false_events"] is not None and case["silence_false_events"] > SILENCE_FALSE_EVENT_LIMIT:
        gates.append("silence-false-events")
    case["gates_failed"] = gates
    return case


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def write_markdown(results: dict[str, Any]) -> str:
    """Render the section 29 markdown report."""
    lines: list[str] = [
        "# BeatScope v0.4 Benchmark",
        "",
        f"- analyzer: pipeline {results['pipeline_version']}",
        f"- tolerances: beat {results['tolerances']['beat_ms']} ms, onset {results['tolerances']['onset_ms']} ms",
        f"- gates failed: {_fmt(len(results['gates']['failed']))}",
        "",
        "| Case | BPM error | Beat MAE | Beat F1 | Onset F1 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for case in results["cases"]:
        beat = case.get("beat") or {}
        onset = case.get("onset") or {}
        bpm_cell = "CRASH" if case.get("crash") else _fmt(case.get("bpm_error"), " BPM")
        lines.append(
            f"| {case['name']} | {bpm_cell} "
            f"| {_fmt(beat.get('mae_ms'), ' ms')} | {_fmt(beat.get('f1'))} | {_fmt(onset.get('f1'))} |"
        )

    detail = []
    for case in results["cases"]:
        if case.get("crash"):
            detail.append(f"- **{case['name']}**: CRASHED: {case['crash']}")
    for case in results["cases"]:
        if case.get("tempo_segments"):
            detail.append(
                f"- **{case['name']}**: change-point error "
                f"{_fmt(case['tempo_segments']['change_point_error_s'], ' s')}, "
                f"segment BPM errors {case['tempo_segments']['segment_bpm_errors']}, "
                f"merged into single segment: {case['tempo_segments']['merged_single_segment']}"
            )
        if case.get("quantization"):
            detail.append(
                f"- **{case['name']}**: quantization offset MAE "
                f"{case['quantization']['offset_mae_ms']} ms over {case['quantization']['measured']} onsets"
            )
        if case.get("silence_false_events") is not None:
            detail.append(f"- **{case['name']}**: {case['silence_false_events']} false events on silence")
        if case.get("gates_failed"):
            detail.append(f"- **{case['name']}**: GATES FAILED: {', '.join(case['gates_failed'])}")
    if detail:
        lines.extend(["", "## Notes", *detail])
    return "\n".join(lines) + "\n"


def apply_baseline_gate(cases: list[dict[str, Any]], baseline: dict[str, Any] | None) -> None:
    """Flag cases whose beat F1 fell far below a recorded baseline (section 30)."""
    if not baseline:
        return
    baseline_f1 = {
        case["name"]: case["beat"]["f1"]
        for case in baseline.get("cases", [])
        if case.get("beat", {}).get("f1") is not None
    }
    for case in cases:
        reference = baseline_f1.get(case["name"])
        current = case.get("beat", {}).get("f1")
        if reference is not None and current is not None and current < reference - BEAT_F1_REGRESSION:
            case.setdefault("gates_failed", []).append("beat-f1-regression")


def _load_fixtures(fixtures_dir: str | Path | None) -> dict[str, dict[str, Any]]:
    """Generate fixtures (code-only audio + truth) into a scratch directory."""
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from tests.fixtures.generate_audio import generate_all
    except ImportError as exc:  # pragma: no cover - depends on checkout layout
        raise RuntimeError(
            "benchmark needs the synthetic fixture generator (tests/fixtures/generate_audio.py); "
            "pass --fixtures-dir pointing at a directory that already contains the case WAVs"
        ) from exc

    target = Path(fixtures_dir) if fixtures_dir else Path(tempfile.mkdtemp(prefix="beatscope-benchmark-"))
    return generate_all(target)


def run_benchmark(
    output_dir: str | Path | None = None,
    fixtures_dir: str | Path | None = None,
    baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run every fixture through analyze_track and score it against truth.

    Writes benchmark-results.json / benchmark-results.md into ``output_dir``
    (default ``build/benchmark``) and returns the full results dict.
    """
    fixtures = _load_fixtures(fixtures_dir)

    baseline: dict[str, Any] | None = None
    if baseline_path is not None:
        baseline_file = Path(baseline_path)
        if baseline_file.is_file():
            baseline = json.loads(baseline_file.read_text(encoding="utf-8"))

    cases: list[dict[str, Any]] = []
    for name, item in fixtures.items():
        truth = item["truth"]
        try:
            project = analyze_track(Path(item["audio"]))
            case = evaluate_case(name, truth, project)
        except Exception as exc:  # noqa: BLE001 - a crash is itself a gate failure
            case = {
                "name": name,
                "purpose": truth.get("purpose", ""),
                "crash": str(exc),
                "gates_failed": ["crash"],
            }
        cases.append(case)
    apply_baseline_gate(cases, baseline)

    failed = sorted({gate for case in cases for gate in case.get("gates_failed", [])})
    results: dict[str, Any] = {
        "schema": "beatscope-benchmark-1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "pipeline_version": ANALYZER_VERSION,
        "backend": "lightweight",
        "tolerances": {"beat_ms": int(BEAT_TOLERANCE_S * 1000), "onset_ms": int(ONSET_TOLERANCE_S * 1000)},
        "gates": {
            "failed": failed,
            "policy": {
                "blocking": [
                    "crash",
                    "invalid-schema",
                    "fixed-bpm-gross-error (>5 BPM)",
                    "beat-f1-floor (<0.5)",
                    "silence-false-events (>20)",
                    "beat-f1-regression (vs baseline)",
                ],
                "report_only": ["dense/onset F1 drift", "section boundaries", "tempo-change precision", "quantization offset"],
            },
        },
        "cases": cases,
    }

    out = Path(output_dir) if output_dir else Path("build") / "benchmark"
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark-results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "benchmark-results.md").write_text(write_markdown(results), encoding="utf-8")
    results["output_dir"] = str(out)
    return results
