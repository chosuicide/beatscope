"""Whole-song structure benchmark: arrangement metrics against known truth.

v0.7 plan sections 18/19: ten synthetic arrangements with independent
harmony/timbre/rhythm/energy knobs are run through ``analyze_track`` and
scored on

* boundary detection - one-to-one matching within ±1 bar, reported as
  precision / recall / F1 plus mean absolute error in bars;
* neutral repeat families - bar-pair F1 (two bars form a positive pair when
  truth and prediction place them in the same family), which stays stable
  when a boundary lands one bar early or late;
* coverage - predicted segments must tile the whole song exactly once.

Hard gates block on crashes, invalid schema, coverage gaps, false boundaries
on the monotony cases, and the family/boundary F1 floor. Run with
``beatscope benchmark-structure``.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .audio_io import load_analysis_audio
from .pipeline import analyze_track
from .schema import ANALYZER_VERSION, validate_rhythm_v4
from .structure import analyze_multiview_structure

STRUCTURE_TOLERANCE_BARS = 1
STRUCTURE_F1_FLOOR = 0.80
STRUCTURE_MAE_CEIL_BARS = 1.0
MONOTONY_FALSE_BOUNDARY_LIMIT = 0

V07_STRUCTURE_METHOD = "bar-multiview-ssm-v2"

_REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED_TRUTH_PATH = _REPO_ROOT / "tests" / "fixtures" / "structure" / "structure-truth.json"
COMMITTED_CHARACTERIZATION_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "structure" / "v06-characterization.json"
)


# ---------------------------------------------------------------- metrics

def match_boundaries(
    truth_bars: list[int],
    predicted_bars: list[int],
    tolerance: int = STRUCTURE_TOLERANCE_BARS,
) -> list[tuple[int, int]]:
    """One-to-one (truth, predicted) bar matches within ``tolerance``.

    Candidate pairs are consumed in ascending (distance, truth, predicted)
    order, so the assignment is deterministic and a predicted boundary can
    never be reused for a second truth boundary.
    """
    used_truth: set[int] = set()
    used_predicted: set[int] = set()
    candidates = sorted(
        (abs(t - p), t, p)
        for t in truth_bars
        for p in predicted_bars
        if abs(t - p) <= tolerance
    )
    pairs: list[tuple[int, int]] = []
    for _distance, truth_bar, predicted_bar in candidates:
        if truth_bar in used_truth or predicted_bar in used_predicted:
            continue
        used_truth.add(truth_bar)
        used_predicted.add(predicted_bar)
        pairs.append((truth_bar, predicted_bar))
    return sorted(pairs)


def boundary_metrics(
    truth_bars: list[int],
    predicted_bars: list[int],
    tolerance: int = STRUCTURE_TOLERANCE_BARS,
) -> dict[str, Any] | None:
    """Precision / recall / F1 / MAE for boundary bars. None when both empty."""
    if not truth_bars and not predicted_bars:
        return None
    pairs = match_boundaries(truth_bars, predicted_bars, tolerance)
    precision = len(pairs) / len(predicted_bars) if predicted_bars else 0.0
    recall = len(pairs) / len(truth_bars) if truth_bars else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    mae = (
        sum(abs(t - p) for t, p in pairs) / len(pairs)
        if pairs
        else None
    )
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "mae_bars": round(mae, 3) if mae is not None else None,
        "matched": len(pairs),
        "predicted": len(predicted_bars),
        "truth": len(truth_bars),
    }


def _families_by_bar(segments: list[dict[str, Any]], total_bars: int) -> list[str | None]:
    families: list[str | None] = [None] * (total_bars + 1)
    for segment in segments:
        try:
            start = int(segment["start_bar"])
            end = int(segment["end_bar"])
        except (KeyError, TypeError, ValueError):
            continue
        family = segment.get("family")
        for bar in range(max(1, start), min(total_bars, end) + 1):
            families[bar] = family if isinstance(family, str) else None
    return families


def _same_family_pairs(families: list[str | None]) -> set[tuple[int, int]]:
    total_bars = len(families) - 1
    pairs: set[tuple[int, int]] = set()
    for first in range(1, total_bars + 1):
        if families[first] is None:
            continue
        for second in range(first + 1, total_bars + 1):
            if families[second] == families[first]:
                pairs.add((first, second))
    return pairs


def bar_pair_family_f1(
    truth_segments: list[dict[str, Any]],
    predicted_segments: list[dict[str, Any]],
    total_bars: int,
) -> float | None:
    """F1 over bar pairs that share a family. None when not measurable."""
    if not truth_segments or not predicted_segments:
        return None
    truth_pairs = _same_family_pairs(_families_by_bar(truth_segments, total_bars))
    predicted_pairs = _same_family_pairs(_families_by_bar(predicted_segments, total_bars))
    if not truth_pairs and not predicted_pairs:
        return None
    true_positive = len(truth_pairs & predicted_pairs)
    precision = true_positive / len(predicted_pairs) if predicted_pairs else 0.0
    recall = true_positive / len(truth_pairs) if truth_pairs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return round(f1, 4)


def structure_coverage_errors(
    segments: list[dict[str, Any]],
    total_bars: int,
) -> list[str]:
    """Ways a segment list fails to tile bars 1..total_bars exactly once.

    Segment ends beyond ``total_bars`` (a trailing grid fragment the truth
    manifest does not count) clamp to the last truth bar.
    """
    errors: list[str] = []
    previous_end = 0
    for index, segment in enumerate(segments):
        try:
            start = int(segment["start_bar"])
            end = int(segment["end_bar"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"segment-{index}-invalid-range")
            continue
        if start < 1 or end < start:
            errors.append(f"segment-{index}-reversed-range")
            continue
        if start > total_bars:
            continue  # entirely beyond the truth bar count
        if start != previous_end + 1:
            errors.append(f"segment-{index}-gap-or-overlap")
        previous_end = min(end, total_bars)
    if not segments or previous_end != total_bars:
        errors.append("segments-do-not-cover-song")
    return errors


# -------------------------------------------------------------- case eval

def evaluate_structure_case(
    name: str,
    truth_case: dict[str, Any],
    project: dict[str, Any],
) -> dict[str, Any]:
    """Score one analyzed project against its arrangement truth."""
    patterns = project.get("patterns") or {}
    total_bars = int(truth_case.get("bars", 0))
    truth_bounds = [
        int(b["bar"]) for b in truth_case.get("boundaries", []) if isinstance(b, dict) and b.get("bar")
    ]
    predicted_bounds = [
        int(b["bar"]) for b in patterns.get("boundaries") or [] if isinstance(b, dict) and b.get("bar")
    ]
    predicted_segments = [s for s in patterns.get("segments") or [] if isinstance(s, dict)]

    case: dict[str, Any] = {
        "name": name,
        "purpose": truth_case.get("purpose", ""),
        "schema_errors": validate_rhythm_v4(project),
        "method": patterns.get("method"),
        "segment_count": len(predicted_segments),
        "boundaries": boundary_metrics(truth_bounds, predicted_bounds, STRUCTURE_TOLERANCE_BARS),
        "family_f1": bar_pair_family_f1(
            truth_case.get("segments") or [], predicted_segments, total_bars,
        ),
    }

    coverage: list[str] = []
    if predicted_segments:
        coverage = structure_coverage_errors(predicted_segments, total_bars)
    elif case["method"] == V07_STRUCTURE_METHOD:
        coverage = ["no-segments"]
    case["coverage_errors"] = coverage

    gates: list[str] = []
    if case["schema_errors"]:
        gates.append("invalid-schema")
    if truth_bounds:
        boundaries = case["boundaries"] or {}
        if boundaries.get("f1") is not None and boundaries["f1"] < STRUCTURE_F1_FLOOR:
            gates.append("structure-boundary-f1-floor")
        if (
            boundaries.get("mae_bars") is not None
            and boundaries["mae_bars"] > STRUCTURE_MAE_CEIL_BARS
        ):
            gates.append("structure-boundary-mae-ceiling")
    elif len(predicted_bounds) > MONOTONY_FALSE_BOUNDARY_LIMIT:
        gates.append("monotony-false-boundaries")
    if case["family_f1"] is not None and case["family_f1"] < STRUCTURE_F1_FLOOR:
        gates.append("structure-family-f1-floor")
    if coverage:
        gates.append("structure-coverage-gap")
    case["gates_failed"] = gates
    return case


# ---------------------------------------------------------------- runner

def load_structure_fixtures(fixtures_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Generate fixtures and verify the committed truth manifest bytes."""
    repo_root = _REPO_ROOT
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from tests.fixtures.structure import generate_structure
    except ImportError as exc:  # pragma: no cover - depends on checkout layout
        raise RuntimeError(
            "structure benchmark needs tests/fixtures/structure/generate_structure.py"
        ) from exc

    target = Path(fixtures_dir) if fixtures_dir else Path(tempfile.mkdtemp(prefix="beatscope-structure-"))
    generate_structure.generate_all(target)
    regenerated = (target / "structure-truth.json").read_bytes()
    committed = COMMITTED_TRUTH_PATH.read_bytes()
    if regenerated != committed:
        raise RuntimeError(
            "structure-truth.json drifted from the committed manifest; regenerate it with "
            "python -m fixtures.structure.generate_structure and review the diff"
        )
    return {"path": str(target), "fixtures": {
        name: {"audio": str(target / f"{name}.wav"), "truth": truth}
        for name, truth in generate_structure.build_manifest()["cases"].items()
    }}


# ------------------------------------------------------- v0.7 analyze path

def structure_payload_for_project(
    audio_path: str | Path,
    project: dict[str, Any],
    target_sr: int = 44100,
) -> dict[str, Any] | None:
    """Run the multiview segmenter on a serialized project's own facts.

    Decodes the audio fresh and pulls beats/onsets/energy/duration/bars from
    the finished project, so the benchmark exercises exactly the facts the
    pipeline publishes. Used until the pipeline emits structure itself.
    """
    beats = project.get("beats") or []
    downbeats = [b for b in beats if b.get("downbeat")]
    total_bars = int((project.get("grid") or {}).get("bars") or 0)
    if len(downbeats) < 2 or total_bars <= 0:
        return None
    y, sr, decoded_duration, _channels, _warnings = load_analysis_audio(
        audio_path, target_sr=target_sr,
    )
    duration = float((project.get("source") or {}).get("duration") or decoded_duration)
    return analyze_multiview_structure(
        y,
        sr,
        beats,
        project.get("onsets") or [],
        project.get("energy") or {},
        duration,
        total_bars,
    )


def analyze_with_structure(audio_path: str | Path) -> dict[str, Any]:
    """analyze_track plus the v0.7 structure payload injected into patterns.

    Once build_rhythm_project emits segments natively (commit 4) the
    injection becomes a no-op because the method already matches.
    """
    project = analyze_track(audio_path)
    patterns = project.get("patterns") or {}
    if patterns.get("method") != V07_STRUCTURE_METHOD:
        payload = structure_payload_for_project(audio_path, project)
        if payload is not None:
            patterns["method"] = payload["method"]
            patterns["segments"] = payload["segments"]
            patterns["boundaries"] = payload["boundaries"]
            patterns["repetitions"] = payload["repetitions"]
            patterns["diagnostics"] = payload["diagnostics"]
    return project


def run_structure_benchmark(
    output_dir: str | Path | None = None,
    fixtures_dir: str | Path | None = None,
    case_names: set[str] | None = None,
    *,
    analyze: Callable[[Path], dict[str, Any]] = analyze_with_structure,
    fixtures: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze every fixture and score it; writes JSON + markdown reports."""
    if fixtures is None:
        loaded = load_structure_fixtures(fixtures_dir)
        fixtures = loaded["fixtures"]

    cases: list[dict[str, Any]] = []
    for name, item in sorted(fixtures.items()):
        if case_names is not None and name not in case_names:
            continue
        truth = item["truth"]
        try:
            started = time.perf_counter()
            project = analyze(Path(item["audio"]))
            elapsed = time.perf_counter() - started
            case = evaluate_structure_case(name, truth, project)
            case["analysis_seconds"] = round(elapsed, 3)
        except Exception as exc:  # noqa: BLE001 - a crash is itself a gate failure
            case = {
                "name": name,
                "purpose": truth.get("purpose", ""),
                "crash": str(exc),
                "gates_failed": ["crash"],
            }
        cases.append(case)

    failed = sorted({gate for case in cases for gate in case.get("gates_failed", [])})
    results: dict[str, Any] = {
        "schema": "beatscope-structure-benchmark-1",
        "pipeline_version": ANALYZER_VERSION,
        "tolerance_bars": STRUCTURE_TOLERANCE_BARS,
        "gates": {
            "failed": failed,
            "policy": {
                "blocking": [
                    "crash",
                    "invalid-schema",
                    "monotony-false-boundaries",
                    "structure-boundary-f1-floor",
                    "structure-boundary-mae-ceiling",
                    "structure-family-f1-floor",
                    "structure-coverage-gap",
                ],
            },
        },
        "cases": cases,
    }

    out = Path(output_dir) if output_dir else Path("build") / "structure-benchmark"
    out.mkdir(parents=True, exist_ok=True)
    (out / "structure-benchmark.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n",
    )
    (out / "structure-benchmark.md").write_text(write_markdown(results), encoding="utf-8", newline="\n")
    results["output_dir"] = str(out)
    return results


def write_markdown(results: dict[str, Any]) -> str:
    """Render the structure benchmark report."""
    lines: list[str] = [
        "# BeatScope Structure Benchmark",
        "",
        f"- analyzer: pipeline {results['pipeline_version']}",
        f"- boundary tolerance: ±{results['tolerance_bars']} bar(s)",
        f"- gates failed: {len(results['gates']['failed'])}",
        "",
        "| Case | Boundaries (truth/pred) | F1 | MAE (bars) | Family F1 | Segments | Gates |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for case in results["cases"]:
        if case.get("crash"):
            lines.append(f"| {case['name']} | CRASH | — | — | — | — | crash |")
            continue
        boundaries = case.get("boundaries") or {}
        truth = boundaries.get("truth", 0)
        predicted = boundaries.get("predicted", 0)
        gates = ", ".join(case.get("gates_failed") or []) or "—"
        lines.append(
            f"| {case['name']} | {truth}/{predicted} "
            f"| {boundaries.get('f1', '—')} | {boundaries.get('mae_bars', '—')} "
            f"| {case.get('family_f1', '—')} | {case.get('segment_count', 0)} | {gates} |"
        )
    return "\n".join(lines) + "\n"


# ------------------------------------------------------- characterization

def characterization_entry(project: dict[str, Any]) -> dict[str, Any]:
    """The small behavior slice pinned by the pre-v0.7 characterization."""
    patterns = project.get("patterns") or {}
    return {
        "method": patterns.get("method"),
        "bar_count": len(patterns.get("bars") or []),
        "segment_count": len(patterns.get("segments") or []),
        "boundary_count": len(patterns.get("boundaries") or []),
        "repetition_count": len(patterns.get("repetitions") or []),
    }


def record_characterization(output_path: str | Path = COMMITTED_CHARACTERIZATION_PATH) -> dict[str, Any]:
    """Record the current analyzer's per-case structure slice to JSON."""
    loaded = load_structure_fixtures()
    cases: dict[str, Any] = {}
    for name, item in sorted(loaded["fixtures"].items()):
        project = analyze_track(Path(item["audio"]))
        cases[name] = characterization_entry(project)
    document = {
        "schema": "beatscope-structure-characterization-1",
        "pipeline_version": ANALYZER_VERSION,
        "cases": cases,
    }
    Path(output_path).write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    return document


__all__ = [
    "MONOTONY_FALSE_BOUNDARY_LIMIT",
    "STRUCTURE_F1_FLOOR",
    "STRUCTURE_MAE_CEIL_BARS",
    "STRUCTURE_TOLERANCE_BARS",
    "analyze_with_structure",
    "bar_pair_family_f1",
    "boundary_metrics",
    "characterization_entry",
    "evaluate_structure_case",
    "load_structure_fixtures",
    "match_boundaries",
    "record_characterization",
    "run_structure_benchmark",
    "structure_coverage_errors",
    "structure_payload_for_project",
    "write_markdown",
]
