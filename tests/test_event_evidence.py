"""Event-evidence contract tests (v0.11 Round 1, plan section 14).

Every formula, boundary condition, ablation, and failure mode of
``beatscope/event_evidence.py`` is pinned here, plus the frozen snapshots
for four representative fixture cases, the cross-process determinism proof,
and the 10,000-onset performance and allocation ceilings.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

from beatscope.event_evidence import (
    InvalidEventEvidenceSource,
    _round6,
    _sorted_quantile,
    _structure_view,
    build_event_evidence,
    canonical_event_evidence_bytes,
    contrast,
    midrank,
    validate_event_evidence,
)
from tests.fixtures.event_evidence import generate_event_evidence as gen

REPO_ROOT = Path(__file__).resolve().parents[1]

# ------------------------------------------------------------- project helpers


def make_onset(index: int, time_value: float, *, all_v: float = 0.5, low: float | None = None,
               mid: float | None = None, high: float | None = None) -> dict:
    return {
        "id": index,
        "time": round(time_value, 6),
        "strength": round(all_v, 4),
        "bands": {
            "all": round(all_v, 4),
            "low": round(all_v if low is None else low, 4),
            "mid": round(all_v if mid is None else mid, 4),
            "high": round(all_v if high is None else high, 4),
        },
    }


def beat_grid(times: list[float]) -> list[dict]:
    return [
        {
            "time": round(value, 6),
            "index": index,
            "bar": index // 4 + 1,
            "beat_in_bar": index % 4 + 1,
            "downbeat": index % 4 == 0,
        }
        for index, value in enumerate(times)
    ]


def rotate_downbeats(beats: list[dict], shift: int) -> list[dict]:
    rotated = []
    for beat in beats:
        in_bar = ((beat["beat_in_bar"] - 1 + shift) % 4) + 1
        rotated.append({**beat, "beat_in_bar": in_bar, "downbeat": in_bar == 1})
    return rotated


STRUCTURE_SEGMENTS = [
    (1, 2, "A"),
    (3, 4, "B"),
    (5, 6, "A"),
]
STRUCTURE_BOUNDARIES = [
    {"bar": 3, "time": 4.0, "novelty": 0.7},
    {"bar": 5, "time": 8.0, "novelty": 0.4},
]


def make_project(onsets: list[dict], *, beats: list[dict] | None = None,
                 with_structure: bool = False, duration: float | None = None) -> dict:
    duration = duration if duration is not None else (onsets[-1]["time"] + 1.0 if onsets else 1.0)
    patterns: dict = {"method": "fixture", "bars": []}
    if with_structure:
        patterns["segments"] = [
            {
                "id": f"segment-{index + 1:03d}",
                "index": index,
                "start_bar": start_bar,
                "end_bar": end_bar,
                "start_time": (start_bar - 1) * 2.0,
                "end_time": end_bar * 2.0,
                "family": family,
                "variant": 0,
                "display_label": family,
                "bar_count": end_bar - start_bar + 1,
                "descriptors": [],
                "mean_energy": 0.5,
            }
            for index, (start_bar, end_bar, family) in enumerate(STRUCTURE_SEGMENTS)
        ]
        patterns["boundaries"] = copy.deepcopy(STRUCTURE_BOUNDARIES)
    return {
        "schema_version": "4.0",
        "project_id": "a1b2c3d4e5f0",
        "source": {
            "display_name": "Event Evidence Test",
            "duration": duration,
            "sample_rate": 22050,
            "channels": 1,
            "sha256": "f" * 64,
        },
        "analysis": {
            "backend": "fixture",
            "pipeline_version": "event-evidence-test",
            "provenance": {"beats": {"method": "none"}, "onsets": {"method": "synthetic"}},
        },
        "tempo": {
            "global_bpm": 120.0,
            "segments": [{"start": 0.0, "end": duration, "bpm": 120.0, "method": "fixture", "score": None}],
        },
        "meter": {"numerator": 4, "denominator": 4},
        "grid": {"origin": 0.0, "default_subdivision": 16, "bars": max(1, int(math.ceil(duration / 2.0)))},
        "beats": list(beats or []),
        "onsets": onsets,
        "energy": {
            "fps": 20,
            "start": 0.0,
            "bands": {name: [0.0] * max(1, int(duration * 20)) for name in ("all", "low", "mid", "high")},
        },
        "patterns": patterns,
        "cues": {"accent": []},
        "exports": {},
    }


# ------------------------------------------------------------ formula tests

def test_midrank_of_tied_values_is_half():
    assert midrank(1.0, np.array([1.0, 1.0, 1.0])) == 0.5


def test_midrank_of_distinct_values_matches_definition():
    values = np.array([1.0, 2.0, 3.0])
    assert midrank(1.0, values) == pytest.approx(1.0 / 6.0)
    assert midrank(2.0, values) == pytest.approx(0.5)
    assert midrank(3.0, values) == pytest.approx(5.0 / 6.0)


def test_contrast_is_zero_at_or_below_median():
    values = np.array([0.1, 0.2, 0.3, 0.4, 0.9])
    median = float(np.quantile(values, 0.50))
    assert contrast(median, values) == 0.0
    assert contrast(median - 0.05, values) == 0.0


def test_contrast_uses_scale_floor_when_q90_equals_median():
    values = np.array([0.5, 0.5, 0.5, 0.5])
    assert contrast(0.58, values) == pytest.approx((0.58 - 0.5) / 0.08)
    assert contrast(0.90, values) == 4.0  # capped, not 5.0


def test_contrast_caps_at_four():
    values = np.array([0.1, 0.1, 0.1, 0.1])
    assert contrast(5.0, values) == 4.0


def test_sorted_quantile_matches_numpy_linear():
    values = np.array([3.0, 1.0, 4.0, 1.5, 2.5, 0.5, 2.0])
    ordered = np.sort(values)
    for quantile in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
        assert _sorted_quantile(ordered, quantile) == pytest.approx(float(np.quantile(values, quantile)))


def test_spectral_shares_sum_to_one():
    project = make_project([make_onset(1, 0.0, all_v=0.8, low=0.7, mid=0.2, high=0.1)])
    bundle = build_event_evidence(project)
    share = bundle["events"][0]["spectral"]["share"]
    assert abs(sum(share.values()) - 1.0) <= 1e-6


def test_equal_bands_have_zero_focus_and_mixed_dominance():
    project = make_project([make_onset(1, 0.0, all_v=0.6, low=0.6, mid=0.6, high=0.6)])
    spectral = build_event_evidence(project)["events"][0]["spectral"]
    assert spectral["focus"] == 0.0
    assert spectral["dominant_band"] == "mixed"
    assert spectral["active_band_count"] == 3


def test_dominant_band_needs_margin_over_runner_up():
    project = make_project([make_onset(1, 0.0, low=0.52, mid=0.48, high=0.0)])
    assert build_event_evidence(project)["events"][0]["spectral"]["dominant_band"] == "mixed"
    project = make_project([make_onset(1, 0.0, low=0.55, mid=0.45, high=0.0)])
    assert build_event_evidence(project)["events"][0]["spectral"]["dominant_band"] == "low"


def test_temporal_end_gaps_are_null():
    single = build_event_evidence(make_project([make_onset(1, 3.0)]))["events"][0]["temporal"]
    assert single["previous_gap_seconds"] is None
    assert single["next_gap_seconds"] is None
    pair = build_event_evidence(make_project(
        [make_onset(1, 3.0), make_onset(2, 3.4)], duration=6.0))["events"]
    assert pair[0]["temporal"]["previous_gap_seconds"] is None
    assert pair[0]["temporal"]["next_gap_seconds"] == 0.4
    assert pair[1]["temporal"]["previous_gap_seconds"] == 0.4
    assert pair[1]["temporal"]["next_gap_seconds"] is None


def test_simultaneous_events_have_zero_isolatedness():
    events = build_event_evidence(make_project(
        [make_onset(1, 1.0), make_onset(2, 1.0), make_onset(3, 2.0)],
        duration=4.0,
    ))["events"]
    assert events[0]["temporal"]["next_gap_seconds"] == 0.0
    assert events[1]["temporal"]["previous_gap_seconds"] == 0.0
    assert events[0]["temporal"]["isolatedness"] == 0.0
    assert events[1]["temporal"]["isolatedness"] == 0.0


def test_edge_windows_use_clamped_duration():
    onsets = [make_onset(1, 0.0), make_onset(2, 5.0), make_onset(3, 10.0)]
    events = build_event_evidence(make_project(onsets, duration=12.0))["events"]
    assert events[0]["temporal"]["events_per_second"] == pytest.approx(1.0 / 2.0)
    assert events[1]["temporal"]["events_per_second"] == pytest.approx(1.0 / 4.0)
    assert events[2]["temporal"]["events_per_second"] == pytest.approx(1.0 / 4.0)


# ------------------------------------------------------------- metric tests

GRID = beat_grid([index * 0.5 for index in range(12)])


def test_exact_beat_chooses_that_beat_with_zero_offset():
    project = make_project([make_onset(1, 1.0)], beats=GRID)
    metric = build_event_evidence(project)["events"][0]["metric"]
    assert metric["beat_index"] == 2
    assert metric["offset_seconds"] == 0.0
    assert metric["beat_in_bar"] == 3
    assert metric["downbeat"] is False


def test_exact_midpoint_chooses_earlier_beat():
    project = make_project([make_onset(1, 0.25)], beats=GRID)
    metric = build_event_evidence(project)["events"][0]["metric"]
    assert metric["beat_index"] == 0
    assert metric["offset_seconds"] == 0.25
    assert metric["offset_ratio"] == 0.5


def test_offset_signs_are_preserved():
    events = build_event_evidence(make_project(
        [make_onset(1, 0.4), make_onset(2, 0.6)], beats=GRID))["events"]
    assert events[0]["metric"]["offset_seconds"] == pytest.approx(-0.1)
    assert events[1]["metric"]["offset_seconds"] == pytest.approx(0.1)


def test_variable_tempo_offset_ratio_uses_adjacent_measured_span():
    variable_grid = beat_grid([0.0, 1.0, 1.5, 2.5])
    project = make_project([make_onset(1, 2.0)], beats=variable_grid)
    metric = build_event_evidence(project)["events"][0]["metric"]
    assert metric["beat_index"] == 2  # exact tie between 1.5 and 2.5 -> earlier beat
    assert metric["offset_seconds"] == 0.5
    assert metric["offset_ratio"] == 1.0  # 0.5 s offset over the 0.5 s previous span


def test_no_beats_produces_metric_null():
    project = make_project([make_onset(1, 1.0), make_onset(2, 2.0)])
    bundle = build_event_evidence(project)
    assert bundle["diagnostics"]["beat_context_available"] is False
    assert all(event["metric"] is None for event in bundle["events"])


def _non_metric_bytes(bundle: dict) -> str:
    """Canonical text of a bundle with metric context stripped for ablation diffs."""
    stripped = copy.deepcopy(bundle)
    for event in stripped["events"]:
        event.pop("metric")
    stripped["diagnostics"]["beat_context_available"] = False
    return json.dumps(stripped, sort_keys=True)


def test_removing_beats_changes_only_metric_context():
    with_beats = build_event_evidence(make_project(
        [make_onset(1, 1.0), make_onset(2, 2.0)], beats=GRID))
    without_beats = build_event_evidence(make_project(
        [make_onset(1, 1.0), make_onset(2, 2.0)], beats=[]))
    assert _non_metric_bytes(with_beats) == _non_metric_bytes(without_beats)


def test_shifting_beats_changes_only_metric_context():
    shifted = [{**beat, "time": round(beat["time"] + 0.25, 6)} for beat in GRID]
    original = build_event_evidence(make_project([make_onset(1, 1.0)], beats=GRID))
    moved = build_event_evidence(make_project([make_onset(1, 1.0)], beats=shifted))
    assert _non_metric_bytes(original) == _non_metric_bytes(moved)


def test_downbeat_rotation_changes_only_copied_metric_fields():
    rotated = rotate_downbeats(GRID, 2)
    original = build_event_evidence(make_project([make_onset(1, 1.0)], beats=GRID))
    rotated_bundle = build_event_evidence(make_project([make_onset(1, 1.0)], beats=rotated))
    for left, right in zip(original["events"], rotated_bundle["events"]):
        for field in ("beat_index", "offset_seconds", "offset_ratio"):
            assert left["metric"][field] == right["metric"][field]
        assert left["metric"]["beat_in_bar"] != right["metric"]["beat_in_bar"]
        assert left["metric"]["downbeat"] != right["metric"]["downbeat"]
    assert _non_metric_bytes(original) == _non_metric_bytes(rotated_bundle)


def test_metric_offset_ratio_null_with_single_beat():
    single = beat_grid([2.0])
    project = make_project([make_onset(1, 2.1)], beats=single)
    metric = build_event_evidence(project)["events"][0]["metric"]
    assert metric["beat_index"] == 0
    assert metric["offset_seconds"] == pytest.approx(0.1)
    assert metric["offset_ratio"] is None


# ---------------------------------------------------------- structure tests

def test_nearest_boundary_selection_is_deterministic():
    onsets = [make_onset(1, 4.0), make_onset(2, 6.0), make_onset(3, 7.9)]
    events = build_event_evidence(make_project(onsets, with_structure=True, duration=12.0))["events"]
    assert events[0]["structure"] == {"boundary_index": 0, "distance_seconds": 0.0, "novelty": 0.7}
    assert events[1]["structure"] == {"boundary_index": 0, "distance_seconds": 2.0, "novelty": 0.7}
    assert events[2]["structure"] == {"boundary_index": 1, "distance_seconds": 0.1, "novelty": 0.4}


def test_boundary_tie_chooses_earlier_boundary():
    view = _structure_view(6.0, copy.deepcopy(STRUCTURE_BOUNDARIES), [4.0, 8.0])
    assert view["boundary_index"] == 0


def test_missing_boundaries_produce_structure_null():
    project = make_project([make_onset(1, 1.0)], with_structure=False)
    bundle = build_event_evidence(project)
    assert bundle["events"][0]["structure"] is None
    assert bundle["diagnostics"]["structure_context_available"] is False


def test_boundary_without_novelty_yields_null_structure():
    assert _structure_view(5.0, [{"time": 4.0}], [4.0]) is None


def test_structure_family_labels_never_enter_the_bundle():
    project = make_project([make_onset(1, 5.0)], with_structure=True, duration=12.0)
    raw = canonical_event_evidence_bytes(build_event_evidence(project)).decode("utf-8")
    assert '"family"' not in raw
    assert '"display_label"' not in raw


def test_no_musical_role_name_is_introduced():
    project = make_project([make_onset(1, 1.0)], beats=GRID, with_structure=True, duration=12.0)
    raw = canonical_event_evidence_bytes(build_event_evidence(project)).decode("utf-8").lower()
    for role in ("verse", "chorus", "drop", "break", "kick", "snare", "hihat", "808",
                 "score", "confidence", "importance", "salience", "primary", "secondary", "texture"):
        assert f'"{role}"' not in raw


# ------------------------------------------------------------- group tests

def rapid_project(times: list[float]) -> dict:
    return make_project([make_onset(index + 1, value) for index, value in enumerate(times)], duration=4.0)


def test_two_rapid_events_do_not_form_a_group():
    bundle = build_event_evidence(rapid_project([1.0, 1.1]))
    assert bundle["groups"] == []
    assert all(event["group_id"] is None for event in bundle["events"])


def test_three_qualifying_events_form_one_group():
    bundle = build_event_evidence(rapid_project([1.0, 1.1, 1.2]))
    assert len(bundle["groups"]) == 1
    group = bundle["groups"][0]
    assert group["id"] == 1
    assert group["onset_ids"] == [1, 2, 3]
    assert group["span_seconds"] == pytest.approx(0.2)
    assert group["intervals_seconds"] == [0.1, 0.1]
    assert group["interval_trend"] == 0.0
    assert [event["group_id"] for event in bundle["events"]] == [1, 1, 1]


def test_gap_above_limit_splits_candidates():
    bundle = build_event_evidence(rapid_project([1.0, 1.1, 1.2, 1.39]))
    assert len(bundle["groups"]) == 1
    assert bundle["groups"][0]["onset_ids"] == [1, 2, 3]
    assert bundle["events"][3]["group_id"] is None


def test_span_above_limit_splits_a_long_run():
    times = [1.0 + 0.1 * index for index in range(20)]
    bundle = build_event_evidence(rapid_project(times))
    assert len(bundle["groups"]) == 2
    assert bundle["groups"][0]["onset_ids"] == list(range(1, 17))
    assert bundle["groups"][0]["span_seconds"] == pytest.approx(1.5)
    assert bundle["groups"][1]["onset_ids"] == [17, 18, 19, 20]


def test_accelerating_run_yields_negative_trend():
    times = [1.0]
    for gap in (0.16, 0.13, 0.10, 0.07):
        times.append(round(times[-1] + gap, 6))
    trend = build_event_evidence(rapid_project(times))["groups"][0]["interval_trend"]
    assert trend < 0


def test_decelerating_run_yields_positive_trend():
    times = [1.0]
    for gap in (0.07, 0.10, 0.13, 0.16):
        times.append(round(times[-1] + gap, 6))
    trend = build_event_evidence(rapid_project(times))["groups"][0]["interval_trend"]
    assert trend > 0


def test_members_survive_and_membership_is_exclusive():
    times = [1.0, 1.08, 1.16, 3.0, 3.08, 3.16, 3.24]
    bundle = build_event_evidence(rapid_project(times))
    assert [group["id"] for group in bundle["groups"]] == [1, 2]
    claimed = [event["group_id"] for event in bundle["events"]]
    assert claimed == [1, 1, 1, 2, 2, 2, 2]
    member_ids = [member for group in bundle["groups"] for member in group["onset_ids"]]
    assert len(member_ids) == len(set(member_ids)) == 7
    assert set(member_ids) == {event["onset_id"] for event in bundle["events"]}


# --------------------------------------------------------- immutability tests

def test_builder_never_mutates_the_source_project():
    project = make_project(
        [make_onset(1, 1.0), make_onset(2, 1.2)], beats=GRID, with_structure=True, duration=12.0)
    frozen = json.dumps(project, sort_keys=True)
    build_event_evidence(project)
    assert json.dumps(project, sort_keys=True) == frozen


def test_bundle_never_carries_a_timestamp_key():
    project = make_project([make_onset(1, 1.0)], beats=GRID, with_structure=True, duration=12.0)
    bundle = build_event_evidence(project)

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                assert key not in {"time", "raw_time", "quantized_time", "snapped_time", "created_at"}
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(bundle)
    assert "onset_time" not in json.dumps(bundle)


def test_canonical_serializer_refuses_invalid_bundle():
    bundle = build_event_evidence(make_project([make_onset(1, 1.0)]))
    corrupted = copy.deepcopy(bundle)
    corrupted["events"][0]["local"]["rank"]["all"] = float("nan")
    with pytest.raises(ValueError):
        canonical_event_evidence_bytes(corrupted)


def test_determinism_across_repeated_calls():
    project = make_project([make_onset(1, 1.0)], beats=GRID, with_structure=True, duration=12.0)
    first = canonical_event_evidence_bytes(build_event_evidence(project))
    second = canonical_event_evidence_bytes(build_event_evidence(copy.deepcopy(project)))
    assert first == second


def test_determinism_across_fresh_processes():
    script = (
        "import hashlib;"
        "from tests.fixtures.event_evidence.generate_event_evidence import build_no_grid_project;"
        "from beatscope.event_evidence import build_event_evidence, canonical_event_evidence_bytes;"
        "print(hashlib.sha256(canonical_event_evidence_bytes("
        "build_event_evidence(build_no_grid_project()))).hexdigest())"
    )
    hashes = []
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        hashes.append(completed.stdout.strip())
    assert hashes[0] == hashes[1]
    in_process = hashlib.sha256(
        canonical_event_evidence_bytes(build_event_evidence(gen.build_no_grid_project()))
    ).hexdigest()
    assert in_process == hashes[0]


# --------------------------------------------------------- validation tests

def _valid_bundle() -> tuple[dict, dict]:
    project = make_project(
        [make_onset(1, 1.0), make_onset(2, 1.1), make_onset(3, 1.2), make_onset(4, 5.0)],
        beats=GRID,
    )
    return build_event_evidence(project), project


def test_validator_accepts_a_valid_bundle():
    bundle, project = _valid_bundle()
    assert validate_event_evidence(bundle, project) == []


def test_validator_rejects_project_mismatch():
    bundle, project = _valid_bundle()
    other = make_project([])
    other["project_id"] = "ffffffffffff"
    errors = validate_event_evidence(bundle, other)
    assert any("project_id" in error for error in errors)


def test_validator_rejects_unexpected_root_fields():
    bundle, project = _valid_bundle()
    bundle["future_extension"] = {}
    errors = validate_event_evidence(bundle, project)
    assert any("bundle key set mismatch" in error for error in errors)


def test_validator_rejects_missing_or_reordered_events():
    bundle, project = _valid_bundle()
    missing = copy.deepcopy(bundle)
    missing["events"] = missing["events"][1:]
    assert validate_event_evidence(missing, project)
    reordered = copy.deepcopy(bundle)
    reordered["events"][0]["onset_id"], reordered["events"][1]["onset_id"] = (
        reordered["events"][1]["onset_id"],
        reordered["events"][0]["onset_id"],
    )
    assert validate_event_evidence(reordered, project)


def test_validator_rejects_unknown_and_duplicate_group_members():
    bundle, project = _valid_bundle()
    unknown = copy.deepcopy(bundle)
    unknown["groups"][0]["onset_ids"].append(99999)
    unknown["groups"][0]["intervals_seconds"].append(0.05)  # keep the shape valid
    unknown["groups"][0]["dominant_band_path"].append("mixed")
    assert any("unknown onset id" in error for error in validate_event_evidence(unknown, project))
    duplicate = copy.deepcopy(bundle)
    duplicate["groups"][0]["onset_ids"].append(duplicate["groups"][0]["onset_ids"][0])
    duplicate["groups"][0]["intervals_seconds"].append(0.05)
    duplicate["groups"][0]["dominant_band_path"].append("mixed")
    assert any("must not repeat" in error for error in validate_event_evidence(duplicate, project))


def test_validator_rejects_nonsequential_or_undersized_groups():
    bundle, project = _valid_bundle()
    nonsequential = copy.deepcopy(bundle)
    nonsequential["groups"][0]["id"] = 2
    for event in nonsequential["events"][:3]:
        event["group_id"] = 2
    errors = validate_event_evidence(nonsequential, project)
    assert any("one-based and sequential" in error for error in errors)

    undersized = copy.deepcopy(bundle)
    undersized["groups"][0]["onset_ids"] = undersized["groups"][0]["onset_ids"][:2]
    undersized["groups"][0]["intervals_seconds"] = undersized["groups"][0]["intervals_seconds"][:1]
    undersized["groups"][0]["dominant_band_path"] = undersized["groups"][0]["dominant_band_path"][:2]
    undersized["events"][2]["group_id"] = None
    errors = validate_event_evidence(undersized, project)
    assert any("at least 3" in error for error in errors)


def test_validator_rejects_one_sided_group_membership():
    bundle, project = _valid_bundle()
    missing_event_link = copy.deepcopy(bundle)
    missing_event_link["events"][0]["group_id"] = None
    errors = validate_event_evidence(missing_event_link, project)
    assert any("group_id must match group membership" in error for error in errors)

    missing_group_link = copy.deepcopy(bundle)
    missing_group_link["groups"][0]["onset_ids"] = missing_group_link["groups"][0]["onset_ids"][1:]
    missing_group_link["groups"][0]["intervals_seconds"] = missing_group_link["groups"][0]["intervals_seconds"][:1]
    missing_group_link["groups"][0]["dominant_band_path"] = missing_group_link["groups"][0]["dominant_band_path"][1:]
    errors = validate_event_evidence(missing_group_link, project)
    assert any("group_id must match group membership" in error for error in errors)


def test_validator_rejects_non_finite_values():
    bundle, project = _valid_bundle()
    broken = copy.deepcopy(bundle)
    broken["events"][0]["local"]["contrast"]["low"] = float("inf")
    errors = validate_event_evidence(broken, project)
    assert any("finite" in error for error in errors)


def test_validator_rejects_forbidden_keys_recursively():
    bundle, project = _valid_bundle()
    for forbidden, path in (
        ("score", ("events", 0, "spectral")),
        ("time", ("events", 0, "local")),
        ("primary", ("events", 0)),
        ("kick", ("groups", 0)),
    ):
        corrupted = copy.deepcopy(bundle)
        container = corrupted
        for key in path[:-1]:
            container = container[key]
        container[path[-1]][forbidden] = 1
        errors = validate_event_evidence(corrupted, project)
        assert any(forbidden in error for error in errors), forbidden


def test_validator_rejects_inconsistent_diagnostics():
    bundle, project = _valid_bundle()
    broken = copy.deepcopy(bundle)
    broken["diagnostics"]["onset_count"] = 99
    assert any("onset_count" in error for error in validate_event_evidence(broken, project))
    broken = copy.deepcopy(bundle)
    broken["diagnostics"]["beat_context_available"] = False
    assert any("beat_context_available" in error for error in validate_event_evidence(broken, project))


def test_valid_empty_project_succeeds():
    project = make_project([])
    bundle = build_event_evidence(project)
    assert bundle["events"] == []
    assert bundle["groups"] == []
    assert bundle["diagnostics"]["onset_count"] == 0
    assert validate_event_evidence(bundle, project) == []
    assert b'"events": []' in canonical_event_evidence_bytes(bundle)


def test_builder_rejects_invalid_sources():
    with pytest.raises(InvalidEventEvidenceSource):
        build_event_evidence("not a project")  # type: ignore[arg-type]
    with pytest.raises(InvalidEventEvidenceSource):
        build_event_evidence({"schema_version": "9.9"})
    project = make_project([make_onset(1, 1.0)])
    project["onsets"][0]["strength"] = 7.0
    with pytest.raises(InvalidEventEvidenceSource):
        build_event_evidence(project)


# ---------------------------------------------------------- snapshot tests

@pytest.fixture(scope="session")
def snapshot_audio_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("event-evidence-snapshots")


def test_frozen_snapshots_match_four_representative_cases(snapshot_audio_dir: Path) -> None:
    for name in gen.SNAPSHOT_CASES:
        project = gen.build_no_grid_project() if name == "no-grid" \
            else gen.analyze_case_cached(name, snapshot_audio_dir)
        raw = canonical_event_evidence_bytes(build_event_evidence(project))
        committed = (REPO_ROOT / "tests" / "snapshots" / "event-evidence" / f"{name}.json").read_bytes()
        if name == "no-grid":
            # The synthetic project bypasses DSP and remains a byte contract.
            assert raw == committed, f"event-evidence snapshot drifted for {name}"
            continue

        # FFT implementations and CPU math libraries can move derived
        # floating-point evidence by tiny amounts while preserving every
        # event, category and relationship.  Compare the portable semantic
        # contract here; formula-level tests above retain tighter coverage.
        actual = json.loads(raw)
        expected = json.loads(committed)

        def compare(left, right, path="root"):
            assert type(left) is type(right), path
            if isinstance(left, dict):
                assert left.keys() == right.keys(), path
                for key in left:
                    compare(left[key], right[key], f"{path}.{key}")
            elif isinstance(left, list):
                assert len(left) == len(right), path
                for index, (item, other) in enumerate(zip(left, right)):
                    compare(item, other, f"{path}[{index}]")
            elif isinstance(left, float):
                assert left == pytest.approx(right, abs=0.02), path
            else:
                assert left == right, path

        compare(actual, expected)


# ------------------------------------------------------- performance budgets

def _ten_thousand_onset_project() -> dict:
    onsets = []
    for index in range(10000):
        time_value = round(index * 0.05, 4)
        strength = round(0.4 + 0.1 * (index % 5), 4)
        onsets.append({
            "id": index + 1,
            "time": time_value,
            "strength": strength,
            "bands": {
                "all": strength,
                "low": round(strength * (0.8 if index % 3 else 0.2), 4),
                "mid": round(strength * 0.5, 4),
                "high": round(strength * (0.3 if index % 3 else 0.7), 4),
            },
        })
    beats = beat_grid([round(index * 0.5, 4) for index in range(1000)])
    project = make_project(onsets, beats=beats, duration=500.0)
    project["grid"]["bars"] = 250
    return project


def test_ten_thousand_onsets_meet_performance_and_memory_budgets():
    project = _ten_thousand_onset_project()
    build_event_evidence(project)  # warm-up

    timings = []
    for _ in range(3):
        started = time.perf_counter()
        bundle = build_event_evidence(project)
        timings.append(time.perf_counter() - started)
    median_seconds = sorted(timings)[1]
    assert median_seconds < 3.0, f"10k build took {median_seconds:.3f}s"

    tracemalloc.start()
    rebuilt = build_event_evidence(project)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert peak < 128 * 1024 * 1024, f"10k build peaked at {peak / 1048576:.1f} MiB"
    assert len(rebuilt["events"]) == 10000
    assert canonical_event_evidence_bytes(rebuilt) == canonical_event_evidence_bytes(bundle)


def test_bundle_round6_never_emits_negative_zero():
    assert _round6(-0.0000001) == 0.0
    assert str(_round6(-0.0)) == "0.0"
