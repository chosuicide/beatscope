"""Multiview segmenter tests: pure-synthetic units plus the ten-fixture gates.

Unit tests feed hand-built view matrices through the segmenter so every
constant (kernels, DP bounds, family thresholds) is exercised against known
geometry. The gate fixture runs the full serialized-project path
(``analyze_with_structure``) over all ten arrangement fixtures and requires
every benchmark gate to pass - that is the v0.7 plan's commit-3 acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from beatscope.structure_benchmark import (
    evaluate_structure_case,
    load_structure_fixtures,
    analyze_with_structure,
)
from beatscope.structure_features import BarSpan, StructureFeatures
from beatscope.structure_segments import (
    FAMILY_JOIN_THRESHOLD,
    MIN_SEGMENT_BARS,
    analyze_structure_segments,
    assign_families,
    checkerboard_novelty,
    combine_views,
    cosine_matrix,
    segment_similarity,
    segment_with_dp,
    select_boundary_candidates,
    _family_letter,
)


# ------------------------------------------------------------ similarity

def test_cosine_matrix_properties():
    features = np.array([[1.0, 0.0], [2.0, 0.0], [0.0, 3.0]])
    sim = cosine_matrix(features)
    assert sim.shape == (3, 3)
    assert np.allclose(np.diag(sim), 1.0)
    assert np.allclose(sim, sim.T)
    assert sim[0, 1] == pytest.approx(1.0)  # same direction, magnitude ignored
    assert sim[0, 2] == pytest.approx(0.0)
    assert (sim >= 0.0).all() and (sim <= 1.0).all()


def test_combine_views_renormalizes_missing_views():
    rows = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
    full = combine_views({"harmony": rows, "timbre": rows, "rhythm": rows, "energy": rows})
    partial = combine_views({"rhythm": rows})
    # A single view's weight cancels after renormalization.
    assert np.allclose(full, partial)
    combined = combine_views({"harmony": rows, "timbre": rows})
    assert np.allclose(np.diag(combined), 1.0)
    assert combined[0, 2] == pytest.approx(1.0)
    assert combined[0, 1] == pytest.approx(0.0)


# --------------------------------------------------------------- novelty

def _block_sim(blocks: list[int], within: float = 1.0) -> np.ndarray:
    size = sum(blocks)
    sim = np.zeros((size, size))
    start = 0
    for length in blocks:
        sim[start:start + length, start:start + length] = within
        start += length
    np.fill_diagonal(sim, 1.0)
    return sim


def test_checkerboard_novelty_peaks_at_block_edge():
    sim = _block_sim([8, 8])
    novelty = checkerboard_novelty(sim, 4)
    assert int(np.argmax(novelty)) == 8
    assert novelty[8] == pytest.approx(1.0)
    # Far from the edge, identical surroundings give no novelty.
    assert novelty[13] == pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------------------ candidates

def test_select_boundary_candidates_find_planted_cut():
    sim = _block_sim([8, 8], within=0.9)
    curve = np.zeros(16)
    curve[8] = 1.0
    candidates, novelty_map, driver_map = select_boundary_candidates(
        sim, {"harmony": curve}
    )
    assert candidates == [8]
    assert novelty_map[8] == pytest.approx(1.0)
    assert driver_map[8]["harmony"] == pytest.approx(1.0)


def test_select_boundary_candidates_reject_flat_similarities():
    sim = np.full((24, 24), 0.5)
    np.fill_diagonal(sim, 1.0)
    curve = np.zeros(24)
    candidates, _, _ = select_boundary_candidates(sim, {"harmony": curve})
    assert candidates == []


def test_select_boundary_candidates_need_driver_corroboration():
    sim = _block_sim([8, 8], within=0.9)
    candidates, _, _ = select_boundary_candidates(sim, {"harmony": np.zeros(16)})
    assert candidates == []  # no view supports the combined peak


# --------------------------------------------------------------- segments

def test_segment_with_dp_honors_candidates():
    sim = _block_sim([8, 8])
    assert segment_with_dp(sim, [8], {8: 1.0}) == [0, 8, 16]


def test_segment_with_dp_respects_minimum_length():
    sim = _block_sim([3, 13])
    # A three-bar first segment is illegal; the candidate must be ignored.
    assert segment_with_dp(sim, [3], {3: 1.0}) == [0, 16]


def test_segment_with_dp_falls_back_to_single_segment():
    sim = _block_sim([36, 4])
    # Both legal routes from bar 0 overshoot MAX_SEGMENT_BARS.
    assert segment_with_dp(sim, [36], {36: 1.0}) == [40]


# --------------------------------------------------------------- families

def test_family_letters_bijective():
    assert _family_letter(0) == "A"
    assert _family_letter(25) == "Z"
    assert _family_letter(26) == "AA"


def test_segment_similarity_duration_normalized():
    rows = np.concatenate([np.tile([1.0, 0.0], (8, 1)), np.tile([0.0, 1.0], (8, 1))])
    views = {"harmony": rows}
    assert segment_similarity(views, (0, 8), (8, 16)) == pytest.approx(0.0)
    assert segment_similarity(views, (0, 8), (0, 8)) == pytest.approx(1.0)
    # Identical content but 4 bars vs 12 bars: the ratio floor caps at 0.75.
    flat = {"harmony": np.tile([1.0, 0.0], (16, 1))}
    assert segment_similarity(flat, (0, 4), (4, 16)) == pytest.approx(0.75)


def _segments_from_spans(spans: list[BarSpan], cuts: list[int]) -> list[dict]:
    return [
        {
            "_start": start,
            "_end": end,
            "_entry_novelty": 0.9,
            "start_bar": spans[start].bar,
            "end_bar": spans[end - 1].bar,
            "bar_count": end - start,
        }
        for start, end in zip(cuts, cuts[1:])
    ]


def _fake_spans(count: int, seconds_per_bar: float = 2.0) -> list[BarSpan]:
    return [
        BarSpan(
            bar=index + 1,
            start_time=index * seconds_per_bar,
            end_time=(index + 1) * seconds_per_bar,
            start_frame=index * 100,
            end_frame=(index + 1) * 100,
        )
        for index in range(count)
    ]


def test_assign_families_repeat_variant_and_break():
    spans = _fake_spans(24)
    third = 0.85  # cosine vs A sits between JOIN (0.82) and VARIANT (0.88)
    harmony = np.concatenate([
        np.tile([1.0, 0.0], (8, 1)),
        np.tile([0.0, 1.0], (8, 1)),
        np.tile([third, np.sqrt(1.0 - third**2)], (8, 1)),
    ])
    segments = _segments_from_spans(spans, [0, 8, 16, 24])
    energy = np.ones(24)
    density = np.full(24, 8.0)
    assign_families({"harmony": harmony}, segments, density, energy)
    assert [s["family"] for s in segments] == ["A", "B", "A"]
    assert [s["variant"] for s in segments] == [0, 0, 1]
    assert segments[0]["descriptors"] == ["opening"]


def test_assign_families_break_family_beats_lettering():
    spans = _fake_spans(20)
    harmony = np.tile([1.0, 0.0], (20, 1))  # all identical content
    segments = _segments_from_spans(spans, [0, 8, 12, 20])
    energy = np.concatenate([np.ones(8), np.full(4, 0.1), np.ones(8)])
    density = np.concatenate([np.full(8, 10.0), np.full(4, 1.0), np.full(8, 10.0)])
    assign_families({"harmony": harmony}, segments, density, energy)
    assert [s["family"] for s in segments] == ["A", "BREAK", "A"]
    assert "break-like" in segments[1]["descriptors"]
    assert "low-energy" in segments[1]["descriptors"]


def test_assign_families_transition_descriptor():
    spans = _fake_spans(12)
    harmony = np.tile([1.0, 0.0], (12, 1))
    segments = _segments_from_spans(spans, [0, 4, 8, 12])
    for segment in segments:
        segment["_entry_novelty"] = 0.9  # p75 of [0.9, 0.9] is 0.9
    assign_families({"harmony": harmony}, segments, np.ones(12), np.ones(12))
    assert "transition-like" in segments[1]["descriptors"]


# ------------------------------------------------------- payload assembly

def _aba_features() -> StructureFeatures:
    spans = _fake_spans(24)
    block = np.concatenate([
        np.tile([1.0, 0.0], (8, 1)),
        np.tile([0.0, 1.0], (8, 1)),
        np.tile([1.0, 0.0], (8, 1)),
    ]).astype(np.float32)
    views = {name: block.copy() for name in ("harmony", "timbre", "rhythm", "energy")}
    return StructureFeatures(spans, views, {
        "feature_version": "structure-features-v2", "warnings": [],
    })


def test_payload_boundaries_families_and_repetitions():
    features = _aba_features()
    payload = analyze_structure_segments(
        features, 48.0, 24, np.ones(24), np.full(24, 8.0),
    )
    assert payload is not None
    assert payload["method"] == "bar-multiview-ssm-v2"
    assert [s["start_bar"] for s in payload["segments"]] == [1, 9, 17]
    assert [s["end_bar"] for s in payload["segments"]] == [8, 16, 24]
    assert [b["bar"] for b in payload["boundaries"]] == [9, 17]
    assert all(b["drivers"] for b in payload["boundaries"])
    assert [s["family"] for s in payload["segments"]] == ["A", "B", "A"]
    assert payload["form"] == "A-B-A"
    repetitions = {r["family"]: r for r in payload["repetitions"]}
    assert set(repetitions) == {"A"}  # A-B-A: only A repeats
    assert repetitions["A"]["segment_ids"] == ["segment-001", "segment-003"]
    assert repetitions["A"]["mean_similarity"] == pytest.approx(1.0, abs=1e-3)
    assert len(payload["bar_families"]) == 24
    assert payload["bar_families"][0] == "A"
    assert payload["bar_families"][8] == "B"
    assert payload["diagnostics"]["feature_version"] == "structure-features-v2"


def test_payload_extends_final_segment_to_grid_bars():
    payload = analyze_structure_segments(
        _aba_features(), 48.0, 25, np.ones(24), np.full(24, 8.0),
    )
    assert payload is not None
    last = payload["segments"][-1]
    assert last["end_bar"] == 25
    assert last["end_time"] == pytest.approx(48.0)
    assert len(payload["bar_families"]) == 25
    assert payload["bar_families"][24] == "A"


def test_payload_first_segment_covers_leading_audio():
    features = _aba_features()
    shifted = StructureFeatures(
        [
            BarSpan(
                span.bar,
                span.start_time + 0.25,
                span.end_time + 0.25,
                span.start_frame,
                span.end_frame,
            )
            for span in features.bar_spans
        ],
        features.views,
        features.diagnostics,
    )
    payload = analyze_structure_segments(
        shifted, 48.25, 24, np.ones(24), np.full(24, 8.0),
    )
    assert payload is not None
    assert payload["segments"][0]["start_time"] == 0.0


def test_payload_is_deterministic():
    first = analyze_structure_segments(
        _aba_features(), 48.0, 24, np.ones(24), np.full(24, 8.0),
    )
    second = analyze_structure_segments(
        _aba_features(), 48.0, 24, np.ones(24), np.full(24, 8.0),
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_payload_refuses_nonfinite_views():
    features = _aba_features()
    features.views["harmony"] = features.views["harmony"].copy()
    features.views["harmony"][3, 0] = np.nan
    payload = analyze_structure_segments(
        features, 48.0, 24, np.ones(24), np.full(24, 8.0),
    )
    assert payload is None


def test_payload_none_without_spans():
    features = StructureFeatures([], {
        name: np.zeros((0, 2), dtype=np.float32)
        for name in ("harmony", "timbre", "rhythm", "energy")
    }, {"feature_version": "structure-features-v2", "warnings": []})
    assert analyze_structure_segments(features, 0.0, 0, np.zeros(0), np.zeros(0)) is None


def test_five_section_rondo_synthetic():
    spans = _fake_spans(30)
    a = np.tile([1.0, 0.0, 0.0], (6, 1))
    b = np.tile([0.0, 1.0, 0.0], (6, 1))
    c = np.tile([0.0, 0.0, 1.0], (6, 1))
    block = np.concatenate([a, b, a, c, b]).astype(np.float32)
    views = {name: block.copy() for name in ("harmony", "timbre", "rhythm", "energy")}
    features = StructureFeatures(spans, views, {
        "feature_version": "structure-features-v2", "warnings": [],
    })
    payload = analyze_structure_segments(
        features, 60.0, 30, np.ones(30), np.full(30, 8.0),
    )
    assert payload is not None
    assert [s["start_bar"] for s in payload["segments"]] == [1, 7, 13, 19, 25]
    assert [b["bar"] for b in payload["boundaries"]] == [7, 13, 19, 25]
    assert [s["family"] for s in payload["segments"]] == ["A", "B", "A", "C", "B"]
    repetitions = {r["family"] for r in payload["repetitions"]}
    assert repetitions == {"A", "B"}


# --------------------------------------------------------- fixture gates

@pytest.fixture(scope="module")
def v07_suite(tmp_path_factory):
    """All ten fixtures analyzed once through the v0.7 injection path."""
    loaded = load_structure_fixtures(tmp_path_factory.mktemp("structure-fixtures-v07"))
    projects = {
        name: analyze_with_structure(Path(item["audio"]))
        for name, item in loaded["fixtures"].items()
    }
    return {"fixtures": loaded["fixtures"], "projects": projects}


def test_all_fixture_cases_pass_all_gates(v07_suite):
    failures = {}
    for name, item in v07_suite["fixtures"].items():
        case = evaluate_structure_case(name, item["truth"], v07_suite["projects"][name])
        if case["gates_failed"]:
            failures[name] = {
                "gates": case["gates_failed"],
                "boundaries": case["boundaries"],
                "family_f1": case["family_f1"],
                "coverage": case["coverage_errors"],
                "segments": [
                    (s.get("start_bar"), s.get("end_bar"), s.get("family"))
                    for s in v07_suite["projects"][name]["patterns"].get("segments") or []
                ],
            }
    assert not failures, json.dumps(failures, indent=2)[:4000]


def test_break_fixture_gets_break_family(v07_suite):
    segments = v07_suite["projects"]["structure-break"]["patterns"]["segments"]
    assert "BREAK" in [s["family"] for s in segments]


def test_tempo_change_repeat_stays_one_family(v07_suite):
    segments = v07_suite["projects"]["structure-tempo-change-repeat"]["patterns"]["segments"]
    assert len({s["family"] for s in segments}) == 1


def test_flat_arrangements_stay_single_segment(v07_suite):
    for name in ("structure-monotony", "structure-short", "structure-drift"):
        segments = v07_suite["projects"][name]["patterns"]["segments"]
        assert len(segments) == 1, name
