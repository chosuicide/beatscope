"""Ranker model tests: features, optimizer, contract, determinism (v0.11 R2).

The synthetic evaluation dataset is generated test material with fabricated
evidence records; it exercises machinery and contracts only and never backs a
model-quality claim (plan sections 3.3 and 22.5).
"""
from __future__ import annotations

import copy
import json
import math
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

from beatscope import event_ranker as er
from scripts.train_event_ranker import song_feature_map
from tests.fixtures.event_evidence.generate_event_evidence import REPO_ROOT
from tests.test_event_ranker_evaluation import build_synth_dataset

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def make_event(onset_id: int, contrast_all: float, rank_all: float = 0.5,
               strength: float = 0.5, *, with_metric: bool = True,
               with_structure: bool = True, with_group: int | None = None,
               previous_gap: float | None = 0.4) -> dict:
    return {
        "onset_id": onset_id,
        "local": {"sample_count": 9,
                  "rank": {"all": rank_all, "low": 0.4, "mid": 0.5, "high": 0.6},
                  "contrast": {"all": contrast_all, "low": 0.3, "mid": 0.2, "high": 0.1}},
        "spectral": {"share": {"low": 0.5, "mid": 0.3, "high": 0.2}, "focus": 0.2,
                     "active_band_count": 2, "dominant_band": "low"},
        "temporal": {"events_per_second": 2.5, "previous_gap_seconds": previous_gap,
                     "next_gap_seconds": 0.3, "isolatedness": 0.3},
        "metric": None if not with_metric else {
            "beat_index": onset_id, "beat_in_bar": 3, "downbeat": False,
            "offset_seconds": 0.02, "offset_ratio": 0.5},
        "structure": None if not with_structure else {
            "boundary_index": 1, "distance_seconds": 4.0, "novelty": 0.5},
        "group_id": with_group,
    }


# ------------------------------------------------------------------- features


def test_feature_order_is_the_frozen_plan_list():
    expected = [
        "onset_strength",
        "local_rank_all", "local_rank_low", "local_rank_mid", "local_rank_high",
        "local_contrast_all", "local_contrast_low", "local_contrast_mid", "local_contrast_high",
        "spectral_share_low", "spectral_share_mid", "spectral_share_high", "spectral_focus",
        "spectral_active_band_count_scaled",
        "spectral_dominant_low", "spectral_dominant_mid", "spectral_dominant_high",
        "spectral_dominant_mixed",
        "temporal_log_events_per_second", "temporal_previous_gap_clipped",
        "temporal_previous_gap_missing", "temporal_next_gap_clipped",
        "temporal_next_gap_missing", "temporal_isolatedness",
        "metric_available", "metric_abs_offset_ratio_clipped", "metric_downbeat",
        "structure_available", "structure_distance_clipped", "structure_novelty",
        "group_available", "group_member_count_log", "group_position_normalized",
        "group_span_seconds_clipped", "group_density_log", "group_interval_trend_clipped",
    ]
    assert list(er.BASE_FEATURE_ORDER) == expected
    assert list(er.FEATURE_ORDER[:len(expected)]) == expected
    assert list(er.FEATURE_ORDER[len(expected):]) == [
        f"{name}_squared" for name in er.SQUARED_SOURCE_NAMES
    ]
    assert len(er.FEATURE_ORDER) == 62


def test_feature_transform_boundaries_are_pinned():
    event = make_event(1, contrast_all=1.0)
    vector = dict(zip(er.FEATURE_ORDER, er.extract_features(event, [], 0.75)))
    assert vector["spectral_active_band_count_scaled"] == pytest.approx(2 / 3)
    assert vector["temporal_log_events_per_second"] == pytest.approx(math.log1p(2.5))
    assert vector["temporal_previous_gap_clipped"] == pytest.approx(0.4 / 2.0)
    assert vector["metric_abs_offset_ratio_clipped"] == pytest.approx(0.5)
    assert vector["structure_distance_clipped"] == pytest.approx(0.5)
    assert vector["onset_strength"] == pytest.approx(0.75)
    assert vector["onset_strength_squared"] == pytest.approx(0.75 ** 2)
    assert vector["spectral_focus_squared"] == pytest.approx(0.2 ** 2)


def test_missing_context_uses_masks_not_fabricated_values():
    event = make_event(1, contrast_all=1.0, with_metric=False, with_structure=False,
                       previous_gap=None)
    vector = dict(zip(er.FEATURE_ORDER, er.extract_features(event, [], 0.5)))
    assert vector["metric_available"] == 0.0
    assert vector["metric_abs_offset_ratio_clipped"] == 0.0
    assert vector["structure_available"] == 0.0
    assert vector["structure_novelty"] == 0.0
    assert vector["temporal_previous_gap_clipped"] == 0.0
    assert vector["temporal_previous_gap_missing"] == 1.0
    assert vector["temporal_next_gap_missing"] == 0.0
    assert vector["group_available"] == 0.0


def test_group_context_transforms_are_clipped():
    groups = [{
        "id": 7, "onset_ids": [1, 2, 3], "span_seconds": 2.0,
        "intervals_seconds": [1.0, 0.5], "interval_trend": 5.0,
        "density_hz": 2.0, "dominant_band_path": ["low"] * 3,
    }]
    event = make_event(2, contrast_all=1.0, with_group=7)
    vector = dict(zip(er.FEATURE_ORDER, er.extract_features(event, groups, 0.5)))
    assert vector["group_available"] == 1.0
    assert vector["group_member_count_log"] == pytest.approx(math.log1p(3))
    assert vector["group_position_normalized"] == pytest.approx(0.5)
    assert vector["group_span_seconds_clipped"] == 1.0  # 2.0 clipped to 1.5 then /1.5
    assert vector["group_density_log"] == pytest.approx(math.log1p(2.0))
    assert vector["group_interval_trend_clipped"] == 1.0  # 5.0/0.18 clamped to +1


def test_non_finite_strength_is_rejected():
    event = make_event(1, contrast_all=1.0)
    with pytest.raises(er.RankerError) as error:
        er.extract_features(event, [], float("nan"))
    assert error.value.code == "non_finite_feature"


def test_ablation_index_sets_match_the_plan():
    non_metric = er.ablation_indices("non_metric")
    assert all(er.FEATURE_ORDER[index].split("_")[0] != "metric"
               or not er.FEATURE_ORDER[index].startswith("metric_") for index in non_metric)
    assert all(er.FEATURE_ORDER[index].startswith("metric_") is False for index in non_metric)
    assert er.ablation_indices("strength_only") == [0]
    assert len(er.ablation_indices("full")) == 62
    assert len(er.ablation_indices("local_spectral")) == 32
    assert len(er.ablation_indices("local_spectral_temporal")) == 42


# ------------------------------------------------------------------- optimizer


def test_toy_separable_pairs_receive_correct_ordering():
    pairs = []
    for index in range(6):
        plus = er.extract_features(make_event(index + 1, contrast_all=1.4), [], 0.5)
        minus = er.extract_features(make_event(index + 10, contrast_all=0.05), [], 0.5)
        pairs.append((plus, minus))
    weights, normalization, iterations = er.train_pair_weights(pairs, lam=0.1)
    margins = []
    for plus, minus in pairs:
        difference = (er.apply_normalization(np.array(plus)[None, :], normalization)
                      - er.apply_normalization(np.array(minus)[None, :], normalization))[0]
        margins.append(float(difference @ weights))
    assert all(margin > 0 for margin in margins)
    assert 0 < iterations < er.NEWTON_MAX_ITERATIONS


def test_reversed_preferences_reverse_the_learned_direction():
    pairs = []
    for index in range(6):
        plus = er.extract_features(make_event(index + 1, contrast_all=1.4), [], 0.5)
        minus = er.extract_features(make_event(index + 10, contrast_all=0.05), [], 0.5)
        pairs.append((plus, minus))
    weights, normalization, _ = er.train_pair_weights(pairs, lam=0.1)
    reversed_weights, _, _ = er.train_pair_weights([(m, p) for p, m in pairs], lam=0.1)
    difference = (er.apply_normalization(np.array(pairs[0][0])[None, :], normalization)
                  - er.apply_normalization(np.array(pairs[0][1])[None, :], normalization))[0]
    assert float(difference @ weights) > 0
    assert float(difference @ reversed_weights) < 0


def test_newton_reduces_penalized_loss_monotonically():
    pairs = []
    for index in range(8):
        plus = er.extract_features(make_event(index + 1, contrast_all=0.5 + 0.1 * index), [], 0.5)
        minus = er.extract_features(make_event(index + 10, contrast_all=0.5 - 0.04 * index), [], 0.5)
        pairs.append((plus, minus))
    positives = np.array([pair[0] for pair in pairs])
    negatives = np.array([pair[1] for pair in pairs])
    stacked = np.vstack([positives, negatives])
    normalization = er.fit_normalization(stacked)
    design = (er.apply_normalization(positives, normalization)
              - er.apply_normalization(negatives, normalization))
    weights, _ = er.newton_fit(design, 0.1)
    assert er._penalized_loss(np.zeros(design.shape[1]), design, 0.1) \
        > er._penalized_loss(weights, design, 0.1)
    # Constant columns stay finite under L2.
    design_with_constant = np.hstack([design, np.ones((design.shape[0], 1))])
    constant_weights, _ = er.newton_fit(design_with_constant, 0.1)
    assert np.all(np.isfinite(constant_weights))


def test_newton_accepts_float_resolution_convergence_for_large_sparse_features():
    # IQR-clamped sparse evidence can normalize a present/absent feature to
    # 1e6.  The optimum is valid, but its final loss improvement is smaller
    # than float64 can represent at the aggregate-loss scale.
    design = np.full((1000, 1), 1_000_000.0, dtype=np.float64)
    weights, iterations = er.newton_fit(design, 0.01)
    assert np.all(np.isfinite(weights))
    assert 0 < iterations < er.NEWTON_MAX_ITERATIONS
    assert er._penalized_loss(weights, design, 0.01) \
        < er._penalized_loss(np.zeros(1), design, 0.01)


def test_train_only_normalization_is_respected_for_evaluation():
    train_stats = er.fit_normalization(np.array([[0.0], [1.0]]))
    weights, normalization, _ = er.train_pair_weights(
        [(np.array([0.0]), np.array([1.0])), (np.array([10.0]), np.array([0.0]))],
        lam=0.1, normalization=train_stats)
    assert normalization["center"] == train_stats["center"]
    assert normalization["scale"] == train_stats["scale"]


def test_optimizer_rejects_empty_pairs():
    with pytest.raises(er.RankerError) as error:
        er.train_pair_weights([], lam=0.1)
    assert error.value.code == "empty_training_pairs"


# ------------------------------------------------------------------- contract


def _valid_model() -> dict:
    pairs = []
    for index in range(4):
        pairs.append((er.extract_features(make_event(index + 1, contrast_all=1.2), [], 0.5),
                      er.extract_features(make_event(index + 10, contrast_all=0.1), [], 0.5)))
    weights, normalization, iterations = er.train_pair_weights(pairs, lam=0.1)
    return er.build_model_json(weights, normalization, lam=0.1, iterations=iterations,
                               train_song_count=3, validation_song_count=1,
                               preference_pair_count=len(pairs),
                               dataset_manifest_sha256="0" * 64,
                               evaluation_report_sha256="1" * 64, status="pending")


def test_canonical_model_refuses_contract_mismatch():
    model = _valid_model()
    assert er.validate_model_json(model) == []
    corrupted = copy.deepcopy(model)
    corrupted["feature_order"] = list(reversed(corrupted["feature_order"]))
    assert any("feature_order" in error for error in er.validate_model_json(corrupted))
    corrupted = copy.deepcopy(model)
    corrupted["weights"] = corrupted["weights"][:-1]
    assert any("weights" in error for error in er.validate_model_json(corrupted))
    corrupted = copy.deepcopy(model)
    corrupted["event_evidence_schema"] = "beatscope-event-evidence-0"
    assert any("event_evidence_schema" in error for error in er.validate_model_json(corrupted))
    corrupted = copy.deepcopy(model)
    corrupted["normalization"]["center"] = "not-a-vector"
    assert er.validate_model_json(corrupted)
    corrupted = copy.deepcopy(model)
    corrupted["training"]["train_song_count"] = 0
    assert any("train_song_count" in error for error in er.validate_model_json(corrupted))


def test_repeated_model_builds_are_byte_identical():
    first = er.canonical_model_bytes(_valid_model())
    second = er.canonical_model_bytes(_valid_model())
    assert first == second


def test_model_build_is_byte_identical_in_fresh_processes(tmp_path: Path):
    probe = tmp_path / "probe_model.py"
    probe.write_text(
        "\n".join([
            "import hashlib",
            "import sys",
            "sys.path.insert(0, '.')",
            "from beatscope import event_ranker as er",
            "",
            "def make_event(i, c):",
            "    return {'onset_id': i, 'local': {'sample_count': 9, 'rank': {'all': 0.5,"
            " 'low': 0.4, 'mid': 0.5, 'high': 0.6}, 'contrast': {'all': c, 'low': 0.3,"
            " 'mid': 0.2, 'high': 0.1}}, 'spectral': {'share': {'low': 0.5, 'mid': 0.3,"
            " 'high': 0.2}, 'focus': 0.2, 'active_band_count': 2, 'dominant_band': 'low'},"
            " 'temporal': {'events_per_second': 2.5, 'previous_gap_seconds': 0.4,"
            " 'next_gap_seconds': 0.3, 'isolatedness': 0.3}, 'metric': None,"
            " 'structure': None, 'group_id': None}",
            "",
            "pairs = [(er.extract_features(make_event(i, 1.2), [], 0.5),"
            " er.extract_features(make_event(i + 10, 0.1), [], 0.5)) for i in range(1, 5)]",
            "weights, normalization, iterations = er.train_pair_weights(pairs, 0.1)",
            "model = er.build_model_json(weights, normalization, lam=0.1, iterations=iterations,"
            " train_song_count=3, validation_song_count=1, preference_pair_count=4,"
            " dataset_manifest_sha256='0' * 64, evaluation_report_sha256='1' * 64,"
            " status='pending')",
            "print(hashlib.sha256(er.canonical_model_bytes(model)).hexdigest())",
        ]),
        encoding="utf-8",
    )
    hashes = []
    for _ in range(2):
        completed = subprocess.run([sys.executable, str(probe)], cwd=str(REPO_ROOT),
                                   capture_output=True, text=True, check=True)
        hashes.append(completed.stdout.strip())
    assert hashes[0] == hashes[1]


# ------------------------------------------------------------------- inference


def test_inference_preserves_exact_onset_id_set_and_never_mutates():
    model = _valid_model()
    events = [make_event(index, contrast_all=0.2 + 0.05 * index,
                         with_metric=index % 2 == 0, with_structure=index % 3 == 0)
              for index in range(1, 21)]
    strengths = {event["onset_id"]: 0.5 for event in events}
    frozen = json.dumps(events, sort_keys=True)
    rows = er.score_events(events, [], strengths, model)
    assert json.dumps(events, sort_keys=True) == frozen
    assert sorted(row["onset_id"] for row in rows) == sorted(strengths)
    assert all(0.0 <= row["response_relevance"] <= 1.0 for row in rows)
    assert er.ranked_ids(rows) == [row["onset_id"] for row in sorted(
        rows, key=lambda row: (-row["response_relevance"], row["onset_id"]))]


def test_inference_meets_the_ten_thousand_event_budget():
    model = _valid_model()
    events = [make_event(index, contrast_all=0.2 + 0.05 * (index % 7)) for index in range(1, 10001)]
    strengths = {event["onset_id"]: 0.5 for event in events}
    started = time.perf_counter()
    rows = er.score_events(events, [], strengths, model)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert len(rows) == 10000
    tracemalloc.start()
    er.score_events(events, [], strengths, model)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert elapsed_ms < 250.0, f"inference took {elapsed_ms:.1f} ms"
    assert peak < 64 * 1024 * 1024, f"peak {peak / 1048576:.1f} MiB"
    assert len(er.canonical_model_bytes(model)) < 64 * 1024


# ----------------------------------------------------------------- dataset use


def test_training_and_selection_run_on_synth_dataset(tmp_path: Path):
    dataset_path, manifest_path = build_synth_dataset(tmp_path)
    output = tmp_path / "candidates"
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "train_event_ranker.py"),
         "--dataset", str(dataset_path), "--manifest", str(manifest_path),
         "--output", str(output)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    selected = json.loads((output / "selected.json").read_text(encoding="utf-8"))
    assert er.validate_model_json(selected) == []
    summary = json.loads((output / "selection-summary.json").read_text(encoding="utf-8"))
    assert summary["selected_lambda"] in er.LAMBDA_CANDIDATES
    assert summary["selected_lambda"] == selected["training"]["lambda"]
    # All lambdas separate the toy signal, so the tie-break must pick 10.0.
    assert summary["selected_lambda"] == 10.0


def test_dataset_group_descriptor_reaches_group_features():
    event = make_event(2, contrast_all=0.5, with_group=7)
    group = {
        "id": 7, "onset_ids": [1, 2, 3], "span_seconds": 0.4,
        "intervals_seconds": [0.2, 0.2], "interval_trend": 0.0,
        "density_hz": 7.5, "dominant_band_path": ["low", "mid", "high"],
    }
    song = {"events": {2: {"evidence": event, "strength": 0.5, "group": group}}}
    vector = dict(zip(er.FEATURE_ORDER, song_feature_map(song)[2]))
    assert vector["group_available"] == 1.0
    assert vector["group_position_normalized"] == 0.5
