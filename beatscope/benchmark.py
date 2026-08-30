"""Algorithm-quality benchmark: analyzer output vs synthetic ground truth.

This is not a unit test suite (plan section 26): unit tests pin behaviour,
the benchmark measures how far analysis lands from known truth. Run it with
``beatscope benchmark``; it writes benchmark-results.json and
benchmark-results.md and exits non-zero when a hard gate fails (section 30).

Baseline governance (tempo-tracking plan sections 9/21): the committed
``tests/fixtures/benchmark-baseline.json`` records accepted metric values.
A normal run only compares and never writes. Regressions beyond the fixed
tolerances fail the run. The baseline may only be replaced through an
explicit ``--accept-baseline``, which refuses to run while any absolute
gate (crash, invalid schema, silence explosion, ...) fails, prints the
old -> new metric diff, and swaps the file atomically.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import sys
import tempfile
import time
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

# Baseline regression windows (tempo plan section 21.1): fixed-tempo cases
# must not degrade beyond these values relative to the accepted baseline.
FIXED_F1_REGRESSION = 0.03
FIXED_MAE_REGRESSION_MS = 15.0

BASELINE_SCHEMA = "beatscope-benchmark-baseline-1"
DEFAULT_BASELINE_PATH = Path("tests/fixtures/benchmark-baseline.json")
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Absolute gates are evaluated in evaluate_case and can never be overridden
# by baseline acceptance: acceptance re-records values, it never legalizes a
# crash, an invalid schema, or a silence explosion.


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


def _predicted_segment_bpm_at(segments: list[dict[str, Any]], t: float) -> float | None:
    for segment in segments:
        start, end = float(segment["start"]), float(segment["end"])
        if start <= t <= end:
            return float(segment["bpm"])
    return None


def _evaluate_tempo_curve(truth: dict[str, Any], project: dict[str, Any]) -> dict[str, Any] | None:
    """Local tempo accuracy against truth curve anchors (tempo plan 20.4).

    Public evaluation uses only the exported tempo segments; the tracker's
    internal path stays a diagnostic so the IR is never asked to carry it.
    """
    anchors = truth.get("tempo_curve") or []
    if not anchors:
        return None
    segments = project.get("tempo", {}).get("segments", [])
    errors: list[float] = []
    direction_total = 0
    direction_ok = 0
    max_log_dev = 0.0
    prev_truth: float | None = None
    prev_pred: float | None = None
    for anchor in anchors:
        t = float(anchor["time"])
        truth_bpm = float(anchor["bpm"])
        predicted_bpm = _predicted_segment_bpm_at(segments, t)
        if predicted_bpm is None:
            continue
        errors.append(abs(predicted_bpm - truth_bpm))
        max_log_dev = max(max_log_dev, abs(math.log2(predicted_bpm / truth_bpm)))
        if prev_truth is not None and prev_pred is not None and abs(truth_bpm - prev_truth) >= 0.5:
            direction_total += 1
            if (truth_bpm - prev_truth) * (predicted_bpm - prev_pred) > 0:
                direction_ok += 1
        prev_truth = truth_bpm
        prev_pred = predicted_bpm
    if not errors:
        return None
    return {
        "tempo_mae_bpm": round(sum(errors) / len(errors), 3),
        "direction_agreement": round(direction_ok / direction_total, 4) if direction_total else None,
        "max_octave_deviation": round(max_log_dev, 4),
        "anchors_measured": len(errors),
    }


def _count_interval_octave_errors(
    truth_beats: list[float], pairs: list[tuple[float, float]]
) -> int:
    """Count matched-adjacent beat intervals whose ratio sits near 0.5 or 2.0."""
    if len(pairs) < 2:
        return 0
    truth_index = {round(t, 6): i for i, t in enumerate(truth_beats)}
    count = 0
    for (ref_a, pred_a), (ref_b, pred_b) in zip(pairs, pairs[1:]):
        idx_a = truth_index.get(round(ref_a, 6))
        idx_b = truth_index.get(round(ref_b, 6))
        if idx_a is None or idx_b != idx_a + 1:
            continue
        truth_interval = ref_b - ref_a
        if truth_interval <= 0:
            continue
        ratio = (pred_b - pred_a) / truth_interval
        if ratio > 0 and abs(math.log2(ratio)) > 0.75:
            count += 1
    return count


def _evaluate_seams(
    truth: dict[str, Any], project: dict[str, Any]
) -> list[dict[str, Any]]:
    """Metrics inside a narrow window around each truth tempo change point.

    The window is defined by truth beat indices (2 bars before, 4 bars after)
    so a wrong prediction can never define its own exam (tempo plan 20.2).
    """
    truth_beats = [float(t) for t in truth.get("beats", [])]
    truth_bib = {round(t, 6): int(v) for t, v in zip(truth_beats, truth.get("beat_in_bar", []))}
    predicted_times = [float(b["time"]) for b in project.get("beats", [])]
    predicted_bib = {
        round(float(b["time"]), 6): int(b.get("beat_in_bar", 0))
        for b in project.get("beats", [])
    }
    segments = truth.get("tempo_segments", [])
    seams: list[dict[str, Any]] = []
    for segment in segments[1:]:
        change = segment.get("start")
        if change is None or not truth_beats:
            continue
        change = float(change)
        before = [t for t in truth_beats if t < change]
        after = [t for t in truth_beats if t >= change]
        window = before[-8:] + after[:16]
        if len(window) < 2:
            continue
        window_start = window[0] - BEAT_TOLERANCE_S
        window_end = window[-1] + BEAT_TOLERANCE_S
        pairs = match_events(window, predicted_times, BEAT_TOLERANCE_S)
        bib_total = 0
        bib_correct = 0
        for ref_time, pred_time in pairs:
            expected = truth_bib.get(round(ref_time, 6))
            actual = predicted_bib.get(round(pred_time, 6))
            if expected is None or actual is None:
                continue
            bib_total += 1
            if expected == actual:
                bib_correct += 1
        predicted_in_window = sum(window_start <= t <= window_end for t in predicted_times)
        seams.append({
            "time": round(change, 4),
            "beat_f1": (_prf(len(pairs), len(window), predicted_in_window) or {}).get("f1"),
            "mae_ms": _timing_mae_ms(pairs),
            "missing_beats": len(window) - len(pairs),
            "extra_beats": max(0, predicted_in_window - len(pairs)),
            "beat_in_bar_accuracy": round(bib_correct / bib_total, 4) if bib_total else None,
        })
    return seams


def _evaluate_downbeats(truth: dict[str, Any], project: dict[str, Any]) -> dict[str, Any] | None:
    truth_downbeats = [float(t) for t in truth.get("downbeats", [])]
    if not truth_downbeats:
        return None
    predicted_downbeats = [
        float(b["time"]) for b in project.get("beats", []) if b.get("downbeat")
    ]
    pairs = match_events(truth_downbeats, predicted_downbeats, BEAT_TOLERANCE_S)
    return {
        **(_prf(len(pairs), len(truth_downbeats), len(predicted_downbeats)) or {}),
        "mae_ms": _timing_mae_ms(pairs),
    }


def _beat_in_bar_accuracy(
    truth: dict[str, Any], pairs: list[tuple[float, float]], project: dict[str, Any]
) -> float | None:
    truth_bib = {round(t, 6): int(v) for t, v in zip(truth.get("beats", []), truth.get("beat_in_bar", []))}
    predicted_bib = {
        round(float(b["time"]), 6): int(b.get("beat_in_bar", 0))
        for b in project.get("beats", [])
    }
    total = 0
    correct = 0
    for ref_time, pred_time in pairs:
        expected = truth_bib.get(round(ref_time, 6))
        actual = predicted_bib.get(round(pred_time, 6))
        if expected is None or actual is None:
            continue
        total += 1
        if expected == actual:
            correct += 1
    return round(correct / total, 4) if total else None


def evaluate_case(
    name: str,
    truth: dict[str, Any],
    project: dict[str, Any],
    *,
    analysis_seconds: float | None = None,
) -> dict[str, Any]:
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
    case["beat_in_bar_accuracy"] = _beat_in_bar_accuracy(truth, beat_pairs, project)

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

    predicted_segments = project.get("tempo", {}).get("segments", [])
    case["segment_count"] = len(predicted_segments)
    truth_segments = truth.get("tempo_segments", [])
    case["tempo_segments"] = None
    if len(truth_segments) >= 2:
        case["tempo_segments"] = _evaluate_tempo_segments(truth_segments, project)

    case["tempo_curve"] = _evaluate_tempo_curve(truth, project)
    case["seams"] = _evaluate_seams(truth, project) or None
    case["downbeats"] = _evaluate_downbeats(truth, project)
    case["octave_errors"] = {
        "interval": _count_interval_octave_errors(truth_beats, beat_pairs),
        "tempo_path_switches": project.get("analysis", {}).get("diagnostics", {}).get("tempo_path_octave_switches"),
    }

    case["silence_false_events"] = None
    if not truth_beats and not truth_onsets:
        case["silence_false_events"] = len(predicted_beats) + len(predicted_onsets)

    case["analysis_seconds"] = round(analysis_seconds, 3) if analysis_seconds is not None else None

    gates: list[str] = []
    if case["schema_errors"]:
        gates.append("invalid-schema")
    if bpm_error is not None and bpm_error > FIXED_BPM_GATE_BPM:
        gates.append("fixed-bpm-gross-error")
    # The F1 floor guards constant-tempo cases only; variable-tempo cases
    # are judged against the accepted baseline instead (tempo plan 21.2).
    fixed_tempo_truth = truth.get("bpm") is not None
    if truth_beats and fixed_tempo_truth and case["beat"].get("f1", 0.0) < BEAT_F1_FLOOR:
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
        "# BeatScope Benchmark",
        "",
        f"- analyzer: pipeline {results['pipeline_version']}",
        f"- tolerances: beat {results['tolerances']['beat_ms']} ms, onset {results['tolerances']['onset_ms']} ms",
        f"- baseline: {_fmt((results.get('baseline') or {}).get('path') or 'none')}"
        f" (manifest match: {_fmt((results.get('baseline') or {}).get('manifest_match'))})",
        f"- gates failed: {_fmt(len(results['gates']['failed']))}",
        "",
        "| Case | BPM error | Beat MAE | Beat F1 | Tempo MAE | Segments | Onset F1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in results["cases"]:
        beat = case.get("beat") or {}
        onset = case.get("onset") or {}
        curve = case.get("tempo_curve") or {}
        bpm_cell = "CRASH" if case.get("crash") else _fmt(case.get("bpm_error"), " BPM")
        lines.append(
            f"| {case['name']} | {bpm_cell} "
            f"| {_fmt(beat.get('mae_ms'), ' ms')} | {_fmt(beat.get('f1'))} "
            f"| {_fmt(curve.get('tempo_mae_bpm'), ' BPM')} | {_fmt(case.get('segment_count'))} "
            f"| {_fmt(onset.get('f1'))} |"
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
        for seam in case.get("seams") or []:
            detail.append(
                f"- **{case['name']}** seam @{seam['time']} s: F1 {_fmt(seam.get('beat_f1'))}, "
                f"MAE {_fmt(seam.get('mae_ms'), ' ms')}, missing {seam['missing_beats']}, "
                f"extra {seam['extra_beats']}, beat-in-bar {_fmt(seam.get('beat_in_bar_accuracy'))}"
            )
        if case.get("octave_errors") is not None:
            detail.append(
                f"- **{case['name']}**: octave errors {case['octave_errors']['interval']}"
                f", path switches {_fmt(case['octave_errors'].get('tempo_path_switches'))}"
            )
        if case.get("downbeats"):
            detail.append(
                f"- **{case['name']}**: downbeat F1 {_fmt(case['downbeats'].get('f1'))}"
                f", MAE {_fmt(case['downbeats'].get('mae_ms'), ' ms')}"
            )
        if case.get("quantization"):
            detail.append(
                f"- **{case['name']}**: quantization offset MAE "
                f"{case['quantization']['offset_mae_ms']} ms over {case['quantization']['measured']} onsets"
            )
        if case.get("silence_false_events") is not None:
            detail.append(f"- **{case['name']}**: {case['silence_false_events']} false events on silence")
        if case.get("analysis_seconds") is not None:
            detail.append(f"- **{case['name']}**: analyzed in {case['analysis_seconds']} s")
        if case.get("gates_failed"):
            detail.append(f"- **{case['name']}**: GATES FAILED: {', '.join(case['gates_failed'])}")
    if detail:
        lines.extend(["", "## Notes", *detail])
    return "\n".join(lines) + "\n"


def apply_baseline_gates(
    cases: list[dict[str, Any]],
    baseline: dict[str, Any] | None,
    *,
    include_regressions: bool = True,
) -> None:
    """Append baseline-derived gates to each case (tempo plan section 9/21).

    Absolute gates are evaluated in ``evaluate_case``; everything here comes
    from the explicitly accepted baseline and is therefore a recorded human
    decision, never something the benchmark may relax on its own.
    """
    if not baseline:
        return
    entries = baseline.get("cases", {})
    for case in cases:
        entry = entries.get(case["name"])
        if not entry:
            continue
        gates = case.setdefault("gates_failed", [])
        beat = case.get("beat") or {}
        current_f1 = beat.get("f1")
        reference_f1 = entry.get("beat_f1")
        if include_regressions and (
            current_f1 is not None
            and reference_f1 is not None
            and current_f1 < reference_f1 - FIXED_F1_REGRESSION
        ):
            gates.append("beat-f1-regression")
        current_mae = beat.get("mae_ms")
        reference_mae = entry.get("beat_mae_ms")
        if include_regressions and (
            current_mae is not None
            and reference_mae is not None
            and current_mae > reference_mae + FIXED_MAE_REGRESSION_MS
        ):
            gates.append("beat-mae-regression")
        declared = entry.get("gates") or {}
        minimum_f1 = declared.get("beat_f1_min")
        if minimum_f1 is not None and current_f1 is not None and current_f1 < minimum_f1:
            gates.append("beat-f1-below-baseline-minimum")
        curve = case.get("tempo_curve") or {}
        tempo_mae = curve.get("tempo_mae_bpm")
        tempo_mae_max = declared.get("tempo_mae_bpm_max")
        if tempo_mae is not None and tempo_mae_max is not None and tempo_mae > tempo_mae_max:
            gates.append("tempo-mae-above-baseline-maximum")
        segments_max = declared.get("segments_max")
        if segments_max is not None and case.get("segment_count", 0) > segments_max:
            gates.append("excess-tempo-segments")
        octave_max = declared.get("octave_errors_max")
        octave_errors = (case.get("octave_errors") or {}).get("interval")
        if octave_max is not None and octave_errors is not None and octave_errors > octave_max:
            gates.append("octave-errors-above-baseline-maximum")
        change_point_max = declared.get("change_point_error_s_max")
        change_point_error = (case.get("tempo_segments") or {}).get("change_point_error_s")
        if change_point_max is not None and change_point_error is not None and change_point_error > change_point_max:
            gates.append("change-point-error-above-baseline-maximum")
        seam_missing_max = declared.get("seam_missing_beats_max")
        for seam in case.get("seams") or []:
            if seam_missing_max is not None and seam["missing_beats"] > seam_missing_max:
                gates.append("seam-missing-beats-above-baseline-maximum")
                break
        seam_extra_max = declared.get("seam_extra_beats_max")
        for seam in case.get("seams") or []:
            if seam_extra_max is not None and seam["extra_beats"] > seam_extra_max:
                gates.append("seam-extra-beats-above-baseline-maximum")
                break


def baseline_manifest_mismatch(baseline: dict[str, Any] | None, truth_sha256: str) -> bool:
    """True when the baseline was accepted against different fixture bytes."""
    if not baseline:
        return True
    recorded = baseline.get("fixture_manifest_sha256")
    return not isinstance(recorded, str) or not recorded or recorded != truth_sha256


def baseline_structure_errors(baseline: Any) -> list[str]:
    """Validate policy-bearing baseline structure without checking fixture identity."""
    if not isinstance(baseline, dict):
        return ["baseline-invalid"]
    if baseline.get("schema") != BASELINE_SCHEMA:
        return ["baseline-invalid"]
    if not isinstance(baseline.get("analyzer_version"), str) or not baseline["analyzer_version"]:
        return ["baseline-invalid"]
    entries = baseline.get("cases")
    if not isinstance(entries, dict):
        return ["baseline-invalid"]
    for entry in entries.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("gates", {}), dict):
            return ["baseline-invalid"]
    return []


def validate_baseline_for_run(
    baseline: Any,
    truth_sha256: str,
    fixture_names: set[str],
) -> list[str]:
    """Fail-closed validation for a normal benchmark comparison run."""
    if baseline is None:
        return ["baseline-missing"]
    errors = baseline_structure_errors(baseline)
    if errors:
        return errors
    recorded = baseline.get("fixture_manifest_sha256")
    if not isinstance(recorded, str) or not recorded:
        return ["baseline-invalid"]
    if recorded != truth_sha256:
        return ["baseline-fixture-mismatch"]
    entries = baseline["cases"]
    if fixture_names - set(entries):
        return ["baseline-incomplete"]
    return []


def build_baseline_entry(
    case: dict[str, Any],
    *,
    gates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Distill one evaluated case into the accepted baseline record.

    Only gate-relevant values are stored. Existing declared gates are copied
    forward because they are explicit human policy, not measured values.
    """
    beat = case.get("beat") or {}
    return {
        "beat_f1": beat.get("f1"),
        "beat_mae_ms": beat.get("mae_ms"),
        "bpm_error": case.get("bpm_error"),
        "segment_count": case.get("segment_count"),
        "gates": dict(gates or {}),
    }


def _load_fixtures(fixtures_dir: str | Path | None) -> dict[str, dict[str, Any]]:
    """Generate fixtures (code-only audio + truth) into a scratch directory."""
    repo_root = _REPO_ROOT
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


def _truth_manifest_sha(fixtures: dict[str, dict[str, Any]]) -> str:
    truth_path = Path(list(fixtures.values())[0]["audio"]).parent / "ground-truth.json"
    return hashlib.sha256(truth_path.read_bytes()).hexdigest()


def run_benchmark(
    output_dir: str | Path | None = None,
    fixtures_dir: str | Path | None = None,
    baseline_path: str | Path | None = None,
    *,
    accept_baseline: bool = False,
) -> dict[str, Any]:
    """Run every fixture through analyze_track and score it against truth.

    Writes benchmark-results.json / benchmark-results.md into ``output_dir``
    (default ``build/benchmark``) and returns the full results dict. With
    ``accept_baseline`` the accepted baseline file is replaced atomically
    instead of compared against; the swap refuses to happen while any
    absolute gate fails.
    """
    fixtures = _load_fixtures(fixtures_dir)
    truth_sha = _truth_manifest_sha(fixtures)

    baseline: dict[str, Any] | None = None
    baseline_load_error = False
    if baseline_path is not None:
        baseline_file = Path(baseline_path)
    else:
        baseline_file = _REPO_ROOT / DEFAULT_BASELINE_PATH
    baseline_existed = baseline_file.is_file()
    if baseline_existed:
        try:
            loaded = json.loads(baseline_file.read_text(encoding="utf-8"))
            baseline = loaded if isinstance(loaded, dict) else None
            baseline_load_error = not isinstance(loaded, dict)
        except (OSError, ValueError, TypeError):
            baseline_load_error = True

    cases: list[dict[str, Any]] = []
    for name, item in fixtures.items():
        truth = item["truth"]
        try:
            started = time.perf_counter()
            project = analyze_track(Path(item["audio"]))
            elapsed = time.perf_counter() - started
            case = evaluate_case(name, truth, project, analysis_seconds=elapsed)
        except Exception as exc:  # noqa: BLE001 - a crash is itself a gate failure
            case = {
                "name": name,
                "purpose": truth.get("purpose", ""),
                "crash": str(exc),
                "gates_failed": ["crash"],
            }
        cases.append(case)

    baseline_section: dict[str, Any] = {"path": str(baseline_file)}
    if accept_baseline:
        # Metric regression windows may be intentionally re-recorded, but
        # declared human policy (tempo/seam/octave bounds) must still pass and
        # must survive the replacement. A malformed existing file cannot be
        # replaced because its policy cannot be recovered safely.
        structure_failures = (
            ["baseline-invalid"]
            if baseline_existed and baseline_load_error
            else baseline_structure_errors(baseline) if baseline_existed else []
        )
        if not structure_failures and baseline is not None:
            apply_baseline_gates(cases, baseline, include_regressions=False)
        any_failures = sorted({gate for case in cases for gate in case.get("gates_failed", [])})
        any_failures = sorted(set(any_failures) | set(structure_failures))
        if any_failures:
            baseline_section.update({
                "valid": False,
                "accepted": False,
                "reason": "cases still fail gates; fix the analyzer before accepting a baseline",
                "gates_failed": any_failures,
            })
        else:
            old_cases = (baseline or {}).get("cases", {})
            diff = []
            for case in cases:
                old = old_cases.get(case["name"], {})
                old_f1 = old.get("beat_f1")
                new_f1 = (case.get("beat") or {}).get("f1")
                diff.append({
                    "name": case["name"],
                    "beat_f1": [old_f1, new_f1],
                    "beat_mae_ms": [old.get("beat_mae_ms"), (case.get("beat") or {}).get("mae_ms")],
                })
            document = {
                "schema": BASELINE_SCHEMA,
                "fixture_generator_version": fixtures[next(iter(fixtures))]["truth"]["generator_version"],
                "fixture_manifest_sha256": truth_sha,
                "analyzer_version": ANALYZER_VERSION,
                "cases": {
                    case["name"]: build_baseline_entry(
                        case,
                        gates=(old_cases.get(case["name"], {}).get("gates") or {}),
                    )
                    for case in cases
                },
            }
            baseline_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_target = baseline_file.with_name(
                f"{baseline_file.name}.tmp-{time.time_ns()}"
            )
            try:
                tmp_target.write_text(
                    json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                tmp_target.replace(baseline_file)
            finally:
                tmp_target.unlink(missing_ok=True)
            baseline_section.update({
                "valid": True,
                "accepted": True,
                "analyzer_version": ANALYZER_VERSION,
                "fixture_manifest_sha256": truth_sha,
                "diff": diff,
            })
            baseline = document
    else:
        validation_failures = (
            ["baseline-invalid"]
            if baseline_load_error
            else validate_baseline_for_run(baseline, truth_sha, set(fixtures))
        )
        baseline_section["valid"] = not validation_failures
        baseline_section["manifest_match"] = (
            not validation_failures and not baseline_manifest_mismatch(baseline, truth_sha)
        )
        if validation_failures:
            baseline_section["gates_failed"] = validation_failures
            for case in cases:
                case.setdefault("gates_failed", []).extend(validation_failures)
        else:
            apply_baseline_gates(cases, baseline)

    failed = sorted({gate for case in cases for gate in case.get("gates_failed", [])})
    results: dict[str, Any] = {
        "schema": "beatscope-benchmark-1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "pipeline_version": ANALYZER_VERSION,
        "backend": "lightweight",
        "tolerances": {"beat_ms": int(BEAT_TOLERANCE_S * 1000), "onset_ms": int(ONSET_TOLERANCE_S * 1000)},
        "baseline": baseline_section,
        "gates": {
            "failed": failed,
            "policy": {
                "blocking": [
                    "crash",
                    "invalid-schema",
                    "fixed-bpm-gross-error (>5 BPM)",
                    "beat-f1-floor (<0.5, fixed-tempo cases)",
                    "silence-false-events (>20)",
                    "beat-f1-regression (vs accepted baseline)",
                    "beat-mae-regression (vs accepted baseline)",
                    "baseline-declared gates (explicit minimums/maximums)",
                ],
                "report_only": ["dense/onset F1 drift", "section boundaries", "quantization offset", "analysis_seconds"],
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
