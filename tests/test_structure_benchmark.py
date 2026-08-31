"""Structure benchmark tests: fixture pinning, metrics, and characterization.

The fixture generator, truth manifest, and metric definitions land before the
v0.7 analyzer does, so the committed characterization file pins the analyzer's
structure slice (re-recorded at the v0.6 -> v0.7 handoff); the full v0.7 gates
(boundary F1, family F1, MAE) are asserted by test_structure_benchmark_gates
once the multiview segmenter exists (v0.7 plan section 22, commit 1).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from beatscope.pipeline import analyze_track
from beatscope.structure_benchmark import (
    COMMITTED_CHARACTERIZATION_PATH,
    COMMITTED_TRUTH_PATH,
    bar_pair_family_f1,
    boundary_metrics,
    characterization_entry,
    load_structure_fixtures,
    match_boundaries,
    run_structure_benchmark,
    structure_coverage_errors,
)

try:
    from tests.fixtures.structure import generate_structure
except ImportError:  # pragma: no cover - conftest-style checkout
    from fixtures.structure import generate_structure


@pytest.fixture(scope="module")
def structure_suite(tmp_path_factory):
    """All ten fixtures generated once and analyzed once for this module."""
    loaded = load_structure_fixtures(tmp_path_factory.mktemp("structure-fixtures"))
    projects = {
        name: analyze_track(Path(item["audio"]))
        for name, item in loaded["fixtures"].items()
    }
    return {"fixtures": loaded["fixtures"], "projects": projects}


# ------------------------------------------------------------ fixture pin

def test_truth_manifest_is_pinned():
    """The committed manifest must match the generator, byte for byte, LF-only."""
    raw = COMMITTED_TRUTH_PATH.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    manifest = json.loads(raw.decode("utf-8"))
    assert manifest["schema"] == generate_structure.TRUTH_SCHEMA
    assert manifest["generator_version"] == generate_structure.GENERATOR_VERSION
    assert set(manifest["cases"]) == set(generate_structure.CASES)
    canonical = json.dumps(generate_structure.build_manifest(), indent=2, ensure_ascii=False) + "\n"
    assert raw.decode("utf-8") == canonical


def test_generator_is_deterministic():
    """Re-rendering a case yields byte-identical PCM (flat and ramped)."""
    for name in ("structure-aba", "structure-drift", "structure-tempo-change-repeat"):
        first = generate_structure.float_to_pcm16(generate_structure.render_case(name))
        second = generate_structure.float_to_pcm16(generate_structure.render_case(name))
        assert first.tobytes() == second.tobytes(), name


def test_truth_spans_tile_every_case():
    for name in generate_structure.CASES:
        truth = generate_structure.case_truth(name)
        segments = truth["segments"]
        assert segments[0]["start_bar"] == 1, name
        assert segments[-1]["end_bar"] == truth["bars"], name
        for before, after in zip(segments, segments[1:]):
            assert after["start_bar"] == before["end_bar"] + 1, name
        boundary_bars = [b["bar"] for b in truth["boundaries"]]
        assert boundary_bars == [s["start_bar"] for s in segments[1:]], name


# ---------------------------------------------------------------- metrics

def test_match_boundaries_is_one_to_one():
    # Two predicted bars both sit within tolerance of the same truth bar;
    # only one may match, and the tie goes to the closer (then lower) bar.
    assert match_boundaries([10], [9, 11]) == [(10, 9)]
    assert match_boundaries([9, 17], [9, 17]) == [(9, 9), (17, 17)]
    assert match_boundaries([9, 17], [10, 16]) == [(9, 10), (17, 16)]
    assert match_boundaries([9, 17], [13]) == []
    assert match_boundaries([], [13]) == []


def test_boundary_metrics_extremes():
    assert boundary_metrics([], []) is None
    perfect = boundary_metrics([9, 17], [9, 17])
    assert perfect == {
        "precision": 1.0, "recall": 1.0, "f1": 1.0, "mae_bars": 0.0,
        "matched": 2, "predicted": 2, "truth": 2,
    }
    missed = boundary_metrics([9, 17], [9])
    assert missed["recall"] == 0.5 and missed["precision"] == 1.0
    assert missed["f1"] == round(2 * 0.5 / 1.5, 4)
    false_only = boundary_metrics([], [5, 6])
    assert false_only["precision"] == 0.0 and false_only["f1"] == 0.0


def test_bar_pair_family_f1():
    truth = [
        {"start_bar": 1, "end_bar": 8, "family": "A"},
        {"start_bar": 9, "end_bar": 16, "family": "B"},
        {"start_bar": 17, "end_bar": 24, "family": "A"},
    ]
    assert bar_pair_family_f1(truth, truth, 24) == 1.0
    assert bar_pair_family_f1(truth, [], 24) is None
    # One flat family recalls every repeat pair but adds ~150 false pairs.
    flat = [{"start_bar": 1, "end_bar": 24, "family": "A"}]
    flat_f1 = bar_pair_family_f1(truth, flat, 24)
    assert flat_f1 is not None and flat_f1 < 1.0
    # A one-segment truth (monotony) agrees perfectly with one flat family.
    assert bar_pair_family_f1([{"start_bar": 1, "end_bar": 24, "family": "A"}], flat, 24) == 1.0


def test_structure_coverage_errors():
    good = [
        {"start_bar": 1, "end_bar": 8},
        {"start_bar": 9, "end_bar": 16},
        {"start_bar": 17, "end_bar": 24},
    ]
    assert structure_coverage_errors(good, 24) == []
    assert "segment-1-gap-or-overlap" in structure_coverage_errors(
        good[:1] + [{"start_bar": 12, "end_bar": 16}] + good[2:], 24,
    )
    assert structure_coverage_errors(good[:2], 24) == ["segments-do-not-cover-song"]
    assert structure_coverage_errors([], 24) == ["segments-do-not-cover-song"]


# -------------------------------------------------------- characterization

def test_structure_characterization(structure_suite):
    """The analyzer's structure slice must stay exactly as recorded.

    Re-record with ``record_characterization()`` only when the analyzer's
    emitted structure legitimately changes (as at the v0.6 -> v0.7 handoff);
    any other drift is a regression.
    """
    committed = json.loads(COMMITTED_CHARACTERIZATION_PATH.read_text(encoding="utf-8"))
    for name, project in structure_suite["projects"].items():
        assert characterization_entry(project) == committed["cases"][name], name


def test_benchmark_runner_pre_v07_gates(structure_suite, tmp_path):
    """Runner-level gates that already hold before the v0.7 segmenter lands."""
    suite = structure_suite
    results = run_structure_benchmark(
        output_dir=tmp_path,
        fixtures=suite["fixtures"],
        analyze=lambda path: suite["projects"][Path(path).stem],
    )
    assert len(results["cases"]) == len(suite["fixtures"])
    for case in results["cases"]:
        assert "crash" not in case, case["name"]
        assert "invalid-schema" not in case.get("gates_failed", []), case["name"]
        assert "monotony-false-boundaries" not in case.get("gates_failed", []), case["name"]
    assert (Path(results["output_dir"]) / "structure-benchmark.json").is_file()
    assert (Path(results["output_dir"]) / "structure-benchmark.md").is_file()
