"""Boosted scorer, v2 model contract, and selection tests (Round 2-B1).

Synthetic fixtures exercise machinery and contracts only; they never back a
model-quality claim (plan sections 3.3 and 10).
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from beatscope import event_ranker as er
from beatscope import event_ranker_boost as boost
from scripts.train_event_ranker_v3 import (
    _matching_non_metric,
    assemble_training_rows,
    slice_delta,
    view_matrix,
)
from tests.fixtures.event_evidence.generate_event_evidence import REPO_ROOT
from tests.test_event_ranker import make_event
from tests.test_event_ranker_evaluation import build_synth_dataset


def _fit_setup(count: int = 60, split_at: int = 30,
               view: str = "full") -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Events where high local contrast is the learnable separation."""
    events = [make_event(index, contrast_all=1.4 if index <= split_at else 0.05)
              for index in range(1, count + 1)]
    indices = er.boost_feature_indices(view)
    features = np.array([
        np.array(er.extract_features(event, [], 0.5))[indices] for event in events
    ])
    pairs = [(low, high) for high in range(split_at) for low in range(split_at, count)]
    # preferred = high contrast (first block), other = low contrast.
    pairs = [(preferred, other) for preferred in range(split_at) for other in range(split_at, count)]
    return features, pairs


def test_zero_gradients_create_no_tree():
    features, pairs = _fit_setup()
    # A perfectly ordered score vector leaves no residual gradient, so the
    # boosting loop must break and store no further trees.
    scores = np.zeros(len(features))
    scores[:30] = 100.0
    scores[30:] = -100.0
    gradient, hessian = boost.aggregate_gradients(scores, pairs)
    assert float(np.max(np.abs(gradient))) < 1e-12
    tree = boost.fit_tree(features, gradient, hessian, depth=2, min_leaf_events=2,
                          leaf_l2=1.0, max_leaf_value=0.5)
    assert tree == {"value": 0.0}


def test_one_useful_split_is_chosen_exactly():
    features = np.array([[0.0], [0.1], [0.9], [1.0]], dtype=np.float64)
    # Gradient wants rows 0-1 up and rows 2-3 down; the exact split is x <= 0.5.
    gradient = np.array([1.0, 1.0, -1.0, -1.0])
    hessian = np.ones(4)
    tree = boost.fit_tree(features, gradient, hessian, depth=1, min_leaf_events=1,
                          leaf_l2=1.0, max_leaf_value=10.0)
    assert tree["feature_index"] == 0
    assert 0.1 < tree["threshold"] < 0.9


def test_depth_never_exceeds_two():
    features, pairs = _fit_setup(count=40, split_at=20)
    gradient, hessian = boost.aggregate_gradients(np.zeros(len(features)), pairs)
    tree = boost.fit_tree(features, gradient, hessian, depth=2, min_leaf_events=2,
                          leaf_l2=1.0, max_leaf_value=0.5)

    def depth_of(node: dict) -> int:
        if "value" in node:
            return 0
        return 1 + max(depth_of(node["left"]), depth_of(node["right"]))

    assert depth_of(tree) <= 2


def test_min_leaf_constraint_is_exact():
    features = np.array([[0.0], [0.2], [0.4], [0.6], [0.8], [1.0]], dtype=np.float64)
    gradient = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
    hessian = np.ones(6)
    tree = boost.fit_tree(features, gradient, hessian, depth=1, min_leaf_events=4,
                          leaf_l2=1.0, max_leaf_value=10.0)
    # Every split leaves a side with fewer than 4 rows, so no split happens.
    assert "value" in tree


def test_gain_ties_follow_feature_then_threshold_order():
    # Two identical features: the tie must choose the lower feature index.
    column = np.array([[0.0], [0.2], [0.8], [1.0]], dtype=np.float64)
    features = np.hstack([column, column.copy()])
    gradient = np.array([1.0, 1.0, -1.0, -1.0])
    hessian = np.ones(4)
    tree = boost.fit_tree(features, gradient, hessian, depth=1, min_leaf_events=1,
                          leaf_l2=1.0, max_leaf_value=10.0)
    assert tree["feature_index"] == 0


def test_pair_orientation_reverses_the_learned_order():
    features, pairs = _fit_setup(count=40, split_at=20)
    forward = boost.boost_train(features, pairs, trees=8, depth=2, learning_rate=0.05,
                                min_leaf_events=2, leaf_l2=1.0, max_leaf_value=0.5)
    reversed_pairs = [(other, preferred) for preferred, other in pairs]
    backward = boost.boost_train(features, reversed_pairs, trees=8, depth=2,
                                 learning_rate=0.05, min_leaf_events=2, leaf_l2=1.0,
                                 max_leaf_value=0.5)
    forward_scores = boost.boost_score(
        features, forward["trees"], 0.0, forward["learning_rate"],
        forward["anchor_feature_index"], forward["anchor_weight"])
    backward_scores = boost.boost_score(
        features, backward["trees"], 0.0, backward["learning_rate"],
        backward["anchor_feature_index"], backward["anchor_weight"])
    preferred_mean = float(forward_scores[:20].mean())
    other_mean = float(forward_scores[20:].mean())
    assert preferred_mean > other_mean
    assert float(backward_scores[:20].mean()) < float(backward_scores[20:].mean())


def test_duplicated_pair_order_does_not_change_canonical_bytes():
    features, pairs = _fit_setup(count=40, split_at=20)
    reordered = list(reversed(pairs))
    first = boost.boost_train(features, pairs, trees=6, depth=2, learning_rate=0.05,
                              min_leaf_events=2, leaf_l2=1.0, max_leaf_value=0.5)
    second = boost.boost_train(features, reordered, trees=6, depth=2, learning_rate=0.05,
                               min_leaf_events=2, leaf_l2=1.0, max_leaf_value=0.5)
    # Aggregated gradients are additive, so pair order cannot change the fit.
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_two_fresh_processes_produce_identical_models(tmp_path: Path):
    probe = tmp_path / "probe_boost.py"
    probe.write_text(
        "\n".join([
            "import hashlib, json, sys",
            "sys.path.insert(0, '.')",
            "import numpy as np",
            "from beatscope import event_ranker as er",
            "from beatscope import event_ranker_boost as boost",
            "from tests.test_event_ranker import make_event",
            "events = [make_event(i, 1.4 if i <= 20 else 0.05) for i in range(1, 41)]",
            "idx = er.boost_feature_indices('full')",
            "features = np.array([np.array(er.extract_features(e, [], 0.5))[idx] for e in events])",
            "pairs = [(p, o) for p in range(20) for o in range(20, 40)]",
            "fit = boost.boost_train(features, pairs, trees=6, depth=2, learning_rate=0.05,"
            " min_leaf_events=2, leaf_l2=1.0, max_leaf_value=0.5)",
            "print(hashlib.sha256(json.dumps(fit, sort_keys=True).encode()).hexdigest())",
        ]),
        encoding="utf-8",
    )
    hashes = []
    for _ in range(2):
        completed = subprocess.run([sys.executable, str(probe)], cwd=str(REPO_ROOT),
                                   capture_output=True, text=True, check=True)
        hashes.append(completed.stdout.strip())
    assert hashes[0] == hashes[1]


# --------------------------------------------------------- v2 model contract


def _boost_model(view: str = "full", trees: int = 3) -> dict:
    features, pairs = _fit_setup(count=40, split_at=20, view=view)
    fit = boost.boost_train(features, pairs, trees=trees, depth=2, learning_rate=0.05,
                            min_leaf_events=2, leaf_l2=1.0, max_leaf_value=0.5)
    return er.build_boost_model_json(
        view, fit, train_song_count=3, validation_song_count=1,
        preference_pair_count=len(pairs), dataset_sha256="0" * 64,
        manifest_sha256="1" * 64, status="pending")


def test_valid_boost_model_round_trips():
    model = _boost_model()
    assert er.validate_boost_model_json(model) == []
    assert model["schema"] == boost.MODEL_SCHEMA_V3
    assert model["method"] == boost.MODEL_METHOD_V4
    assert model["feature_order"] == list(er.BASE_FEATURE_ORDER)
    assert len(model["feature_order"]) == 36
    assert model["anchor"] == {"feature_index": 0, "weight": 1.0}
    assert er.canonical_boost_model_bytes(model) == er.canonical_boost_model_bytes(model)


def test_non_metric_view_cannot_access_metric_columns():
    model = _boost_model("non_metric")
    assert er.validate_boost_model_json(model) == []
    assert all(not name.startswith("metric_") for name in model["feature_order"])
    corrupted = copy.deepcopy(model)
    corrupted["feature_order"] = list(model["feature_order"]) + ["metric_downbeat"]
    corrupted["feature_view"] = "non_metric"
    assert any("non_metric boosted view" in error
               for error in er.validate_boost_model_json(corrupted))


def test_invalid_trees_are_rejected_by_the_validator():
    model = _boost_model()

    deep = copy.deepcopy(model)
    if "value" in deep["trees"][0]:
        return  # a degenerate one-leaf forest has nothing to deepen
    # A split at depth 2 (its children would sit at depth 3) is illegal.
    deep["trees"][0] = {
        "feature_index": 0, "threshold": 0.5,
        "left": {
            "feature_index": 1, "threshold": 0.6,
            "left": {"feature_index": 2, "threshold": 0.7,
                     "left": {"value": 0.0}, "right": {"value": 0.0}},
            "right": {"value": 0.0},
        },
        "right": {"value": 0.0},
    }
    errors = er.validate_boost_model_json(deep)
    assert any("depth-2" in error for error in errors)

    unknown = copy.deepcopy(model)
    unknown["feature_order"] = ["not_a_feature"] + list(model["feature_order"])
    # Shift one tree's index so it points at the renamed slot, then expect the
    # unknown-name error regardless.
    errors = er.validate_boost_model_json(unknown)
    assert any("unknown features" in error for error in errors)

    nonfinite = copy.deepcopy(model)
    nonfinite["trees"][0]["threshold"] = float("nan")
    assert any("threshold" in error for error in er.validate_boost_model_json(nonfinite))

    wrong_type = copy.deepcopy(model)
    wrong_type["trees"][0]["threshold"] = None
    assert any("threshold" in error for error in er.validate_boost_model_json(wrong_type))

    executable = copy.deepcopy(model)
    executable["training"]["dataset_sha256"] = "eval(1)"
    assert any("eval(" in error for error in er.validate_boost_model_json(executable))

    oversize = copy.deepcopy(model)
    oversize["trees"] = model["trees"] * 30  # > 72 trees once validated
    errors = er.validate_boost_model_json(oversize)
    assert any("72" in error for error in errors)


def test_strength_anchor_is_frozen_and_rejects_invalid_configuration():
    features, pairs = _fit_setup(count=40, split_at=20)
    with pytest.raises(ValueError, match="address"):
        boost.boost_train(
            features, pairs, trees=1, depth=1, learning_rate=0.05,
            min_leaf_events=2, leaf_l2=1.0, max_leaf_value=0.5,
            anchor_feature_index=features.shape[1])
    with pytest.raises(ValueError, match="positive finite"):
        boost.boost_train(
            features, pairs, trees=1, depth=1, learning_rate=0.05,
            min_leaf_events=2, leaf_l2=1.0, max_leaf_value=0.5,
            anchor_weight=0.0)

    model = _boost_model()
    wrong_index = copy.deepcopy(model)
    wrong_index["anchor"]["feature_index"] = 1
    assert any("onset_strength" in error
               for error in er.validate_boost_model_json(wrong_index))
    wrong_weight = copy.deepcopy(model)
    wrong_weight["anchor"]["weight"] = 0.5
    assert any("frozen value" in error
               for error in er.validate_boost_model_json(wrong_weight))
    bool_index = copy.deepcopy(model)
    bool_index["anchor"]["feature_index"] = False
    assert any("onset_strength" in error
               for error in er.validate_boost_model_json(bool_index))
    bool_weight = copy.deepcopy(model)
    bool_weight["anchor"]["weight"] = True
    assert any("frozen value" in error
               for error in er.validate_boost_model_json(bool_weight))


def test_zero_residual_trees_reproduce_raw_onset_strength_exactly():
    features, pairs = _fit_setup(count=40, split_at=20)
    fit = boost.boost_train(
        features, pairs, trees=0, depth=1, learning_rate=0.05,
        min_leaf_events=2, leaf_l2=1.0, max_leaf_value=0.5)
    scores = boost.boost_score(
        features, fit["trees"], fit["base_value"], fit["learning_rate"],
        fit["anchor_feature_index"], fit["anchor_weight"])
    assert np.array_equal(scores, features[:, 0])


def test_scoring_preserves_ids_and_never_mutates_evidence():
    model = _boost_model()
    events = [make_event(index, contrast_all=0.2 + 0.05 * (index % 5)) for index in range(1, 31)]
    strengths = {event["onset_id"]: 0.5 for event in events}
    frozen = json.dumps(events, sort_keys=True)
    rows = er.boost_score_rows(events, [], strengths, model)
    assert json.dumps(events, sort_keys=True) == frozen
    assert sorted(row["onset_id"] for row in rows) == sorted(strengths)
    assert all(0.0 <= row["response_relevance"] <= 1.0 for row in rows)


def test_boost_inference_meets_the_budget():
    model = _boost_model("full", trees=24)
    events = [make_event(index, contrast_all=0.2 + 0.05 * (index % 7)) for index in range(1, 10001)]
    strengths = {event["onset_id"]: 0.5 for event in events}
    import time

    started = time.perf_counter()
    rows = er.boost_score_rows(events, [], strengths, model)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert len(rows) == 10000
    # Shared Windows runners regularly add 5-15% scheduling noise around the
    # former 250 ms edge.  400 ms still scores 25k events/s—orders of
    # magnitude above a song-sized workload—without turning CI load into a
    # product regression.
    assert elapsed_ms < 400.0, f"inference took {elapsed_ms:.1f} ms"
    assert len(er.canonical_boost_model_bytes(model)) < 64 * 1024


# ------------------------------------------------------------------ selection


def _candidate(name: str, *, overall=0.05, dense=0.02, ndcg=0.01, recall=0.0,
               sources=None, view="full", trees=24, depth=2, model_bytes=4096,
               non_metric_delta=0.02) -> dict:
    return {
        "name": name,
        "feature_view": view,
        "trees": trees,
        "depth": depth,
        "model_bytes": model_bytes,
        "overall_pairwise_delta": overall,
        "dense_tertile_delta": dense,
        "ndcg_delta": ndcg,
        "recall_delta": recall,
        "source_deltas": sources if sources is not None else {"pack-one": 0.05, "pack-two": 0.04},
        "non_metric_pairwise_delta": non_metric_delta if view == "full" else None,
    }


def test_every_eligibility_condition_is_isolated():
    assert er.select_boosted_candidate([_candidate("ok")]) is not None
    assert er.select_boosted_candidate([_candidate("low-overall", overall=0.01)]) is None
    assert er.select_boosted_candidate([_candidate("dense-regress", dense=-0.01)]) is None
    assert er.select_boosted_candidate([_candidate("ndcg-loss", ndcg=-0.02)]) is None
    assert er.select_boosted_candidate([_candidate("recall-loss", recall=-0.02)]) is None
    assert er.select_boosted_candidate([
        _candidate("source-loss", sources={"pack-one": 0.05, "pack-two": -0.02})]) is None
    assert er.select_boosted_candidate([
        _candidate("nonfinite-source", sources={"pack-one": 0.05, "pack-two": float("nan")})]) is None
    assert er.select_boosted_candidate([
        _candidate("weak-counterpart", non_metric_delta=0.005)]) is None


def test_every_lexicographic_tie_break_is_isolated():
    # 1: larger minimum source delta wins.
    winner = er.select_boosted_candidate([
        _candidate("a", sources={"p": 0.05, "q": 0.03}),
        _candidate("b", sources={"p": 0.05, "q": 0.04}),
    ])
    assert winner["name"] == "b"
    # 2: larger dense delta.
    winner = er.select_boosted_candidate([_candidate("a", dense=0.02), _candidate("b", dense=0.03)])
    assert winner["name"] == "b"
    # 3: larger overall delta.
    winner = er.select_boosted_candidate([_candidate("a", overall=0.05), _candidate("b", overall=0.06)])
    assert winner["name"] == "b"
    # 4: larger NDCG.
    winner = er.select_boosted_candidate([_candidate("a", ndcg=0.01), _candidate("b", ndcg=0.02)])
    assert winner["name"] == "b"
    # 5: fewer trees.
    winner = er.select_boosted_candidate([_candidate("a", trees=48), _candidate("b", trees=24)])
    assert winner["name"] == "b"
    # 6: shallower depth.
    winner = er.select_boosted_candidate([_candidate("a", depth=2), _candidate("b", depth=1)])
    assert winner["name"] == "b"
    # 7: smaller serialized model.
    winner = er.select_boosted_candidate([_candidate("a", model_bytes=8192),
                                          _candidate("b", model_bytes=4096)])
    assert winner["name"] == "b"
    # 8: feature view name - "full" wins the final tie.
    full = _candidate("a", view="full")
    non_metric = _candidate("b", view="non_metric", non_metric_delta=None)
    winner = er.select_boosted_candidate([full, non_metric])
    assert winner["name"] == "a"


def test_slice_delta_uses_the_same_song_subset_for_the_baseline():
    model = {"dense": 0.8, "sparse": 0.9}
    baseline = {"dense": 0.7, "sparse": 0.1}
    assert slice_delta(model, baseline, {"dense"}) == pytest.approx(0.1)


def test_non_metric_counterpart_matches_every_hyperparameter():
    common = {
        "feature_view": "non_metric", "trees": 48, "depth": 2,
        "learning_rate": 0.05, "min_leaf_events": 32,
        "leaf_l2": 1.0, "max_leaf_value": 0.5,
    }
    wrong = {**common, "name": "wrong", "min_leaf_events": 64}
    right = {**common, "name": "right"}
    full = {**common, "feature_view": "full"}
    assert _matching_non_metric([wrong, right], full)["name"] == "right"


def test_training_rows_keep_pair_indices_inside_each_song_and_group_features():
    def song(first_id: int, group_id: int) -> dict:
        events = {}
        for offset in range(3):
            onset_id = first_id + offset
            evidence = make_event(onset_id, contrast_all=1.0, with_group=group_id)
            events[onset_id] = {
                "onset_id": onset_id, "strength": 0.5, "evidence": evidence,
                "group": {
                    "id": group_id, "onset_ids": [first_id, first_id + 1, first_id + 2],
                    "span_seconds": 0.42, "density_hz": 4.8, "interval_trend": 0.0,
                },
            }
        return {
            "events": events,
            "pairs": [{"preferred_onset_id": first_id,
                       "other_onset_id": first_id + 2}],
            "meta": {"split": "train"},
        }

    songs = {"b": song(11, 2), "a": song(1, 1)}
    matrix, pairs = assemble_training_rows(songs, "full")
    assert pairs == [(0, 2), (3, 5)]
    group_position = er.boost_feature_names("full").index("group_available")
    assert np.all(matrix[:, group_position] == 1.0)
    second_matrix, _, _ = view_matrix(songs["b"], "full")
    assert second_matrix[0, group_position] == 1.0


# ------------------------------------------------------- trainer integration


def test_training_refuses_development_corpora_below_the_minimums(tmp_path: Path):
    dataset_path, manifest_path = build_synth_dataset(tmp_path)
    # Fold the one test song into validation so only the size minimums fail.
    rows = []
    for line in dataset_path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if payload.get("kind") == "song" and payload.get("split") == "test":
            payload["split"] = "validation"
        if payload.get("kind") == "event" and payload.get("split") == "test":
            payload["split"] = "validation"
        if payload.get("kind") == "pair" and payload.get("split") == "test":
            payload["split"] = "validation"
        rows.append(json.dumps(payload, separators=(",", ":")))
    development = tmp_path / "development.jsonl"
    development.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for song in manifest["songs"]:
        if song["split"] == "test":
            song["split"] = "validation"
    manifest["dataset_sha256"] = hashlib.sha256(development.read_bytes()).hexdigest()
    manifest["development_readiness"] = {
        "song_count": 6, "source_count": 1, "chart_count": 18,
        "validation_song_count": 3,
    }
    development_manifest = tmp_path / "development-manifest.json"
    development_manifest.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "train_event_ranker_v3.py"),
         "--dataset", str(development), "--manifest", str(development_manifest),
         "--output", str(tmp_path / "candidates")],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert completed.returncode == 1
    assert "section 3.2 minimums" in completed.stderr


def test_trainer_refuses_test_split_rows(tmp_path: Path):
    dataset_path, manifest_path = build_synth_dataset(tmp_path)
    poisoned = tmp_path / "with-test.jsonl"
    rows = dataset_path.read_text(encoding="utf-8").splitlines()
    flipped = []
    for line in rows:
        payload = json.loads(line)
        if payload.get("kind") == "song" and payload.get("split") == "validation":
            payload["split"] = "test"
        flipped.append(json.dumps(payload, separators=(",", ":")))
    poisoned.write_text("\n".join(flipped) + "\n", encoding="utf-8", newline="\n")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dataset_sha256"] = hashlib.sha256(poisoned.read_bytes()).hexdigest()
    poisoned_manifest = tmp_path / "with-test-manifest.json"
    poisoned_manifest.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "train_event_ranker_v3.py"),
         "--dataset", str(poisoned), "--manifest", str(poisoned_manifest),
         "--output", str(tmp_path / "candidates")],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert completed.returncode == 2
    assert "test-split" in completed.stderr
