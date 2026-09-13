"""Deterministic strength-anchored pairwise scorer (v0.11 Round 2-B).

A small additive ensemble of depth-2 regression trees trained with
second-order (Newton) leaf values on aggregated pairwise gradients - the
same weak supervision as the linear ranker, but able to learn thresholds
and limited interactions itself. NumPy only: no scikit-learn, XGBoost,
LightGBM, pickle, or native model dependency.

Determinism contract (plan section 5.4):

- thresholds come from fixed training-only quantiles (0.10 .. 0.90),
  deduplicated;
- splits maximize second-order gain, breaking ties by lower feature
  index then lower threshold;
- no random sampling, no wall-clock stopping, no unordered iteration;
- all accumulation is float64 over a stable event ordering, and
  serialized floats use the repository's six-decimal policy, so two
  fresh processes produce byte-identical model JSON.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

MODEL_SCHEMA_V3 = "beatscope-response-ranker-3"
MODEL_METHOD_V4 = "strength-anchored-pairwise-boosted-chart-consensus-v4"

BOOSTING_QUANTILES = tuple(q / 10.0 for q in range(1, 10))
MAX_TREES = 72
MAX_TREE_DEPTH = 2

# Frozen B1 candidate grid (plan section 5.5): trees, depth, learning rate,
# min leaf events, leaf L2, max leaf value.
CANDIDATE_GRID: tuple[tuple[int, int, float, int, float, float], ...] = (
    (24, 1, 0.05, 32, 1.0, 0.5),
    (24, 2, 0.05, 32, 1.0, 0.5),
    (48, 2, 0.05, 32, 1.0, 0.5),
    (72, 2, 0.03, 32, 1.0, 0.4),
    (48, 2, 0.05, 64, 2.0, 0.4),
    (72, 2, 0.03, 64, 2.0, 0.4),
)
FEATURE_VIEWS = ("full", "non_metric")


def _round6(value: float) -> float:
    parsed = round(float(value), 6)
    return 0.0 if parsed == 0.0 else parsed


def _sigmoid_scalar(margin: float) -> float:
    if margin >= 0.0:
        return 1.0 / (1.0 + math.exp(-margin))
    exponential = math.exp(margin)
    return exponential / (1.0 + exponential)


def aggregate_gradients(scores: np.ndarray, pairs: list[tuple[int, int]]) -> tuple[np.ndarray, np.ndarray]:
    """Event-level gradient/hessian sums for the pairwise logistic loss.

    ``pairs`` holds (preferred_index, other_index) into the score vector.
    The stored gradient is the Newton step direction (+q on the preferred
    side, -q on the other), exactly as plan section 5.3 defines it.
    """
    gradient = np.zeros(len(scores), dtype=np.float64)
    hessian = np.zeros(len(scores), dtype=np.float64)
    for preferred, other in sorted(pairs):
        margin = float(scores[preferred] - scores[other])
        q = _sigmoid_scalar(-margin)
        curvature = q * (1.0 - q)
        gradient[preferred] += q
        gradient[other] -= q
        hessian[preferred] += curvature
        hessian[other] += curvature
    return gradient, hessian


def _leaf_value(gradient_sum: float, hessian_sum: float, leaf_l2: float,
                max_leaf_value: float) -> float:
    value = gradient_sum / (hessian_sum + leaf_l2)
    return max(-max_leaf_value, min(max_leaf_value, value))


def _best_split(features: np.ndarray, node_indices: np.ndarray, gradient: np.ndarray,
                hessian: np.ndarray, min_leaf_events: int, leaf_l2: float,
                max_leaf_value: float) -> dict[str, Any] | None:
    """Maximum-gain split over the frozen quantile thresholds."""
    total_gradient = float(gradient[node_indices].sum())
    total_hessian = float(hessian[node_indices].sum())
    parent_score = total_gradient * total_gradient / (total_hessian + leaf_l2)
    best: dict[str, Any] | None = None
    best_gain = 0.0  # non-positive gains never split (plan section 5.4)
    for feature_index in range(features.shape[1]):
        values = features[node_indices, feature_index]
        thresholds: list[float] = []
        for quantile in BOOSTING_QUANTILES:
            threshold = _round6(float(np.quantile(values, quantile)))
            if threshold not in thresholds:
                thresholds.append(threshold)
        for threshold in thresholds:
            mask = values <= threshold
            left_count = int(mask.sum())
            right_count = len(node_indices) - left_count
            if left_count < min_leaf_events or right_count < min_leaf_events:
                continue
            left_gradient = float(gradient[node_indices[mask]].sum())
            left_hessian = float(hessian[node_indices[mask]].sum())
            right_gradient = total_gradient - left_gradient
            right_hessian = total_hessian - left_hessian
            gain = 0.5 * (
                left_gradient * left_gradient / (left_hessian + leaf_l2)
                + right_gradient * right_gradient / (right_hessian + leaf_l2)
                - parent_score
            )
            if gain > best_gain + 1e-12:
                best_gain = gain
                best = {"feature_index": feature_index, "threshold": threshold,
                        "left_indices": node_indices[mask], "right_indices": node_indices[~mask]}
            elif abs(gain - best_gain) <= 1e-12 and best is not None:
                # Exact tie: prefer the lower feature index, then lower threshold.
                if feature_index < best["feature_index"] or (
                        feature_index == best["feature_index"] and threshold < best["threshold"]):
                    best = {"feature_index": feature_index, "threshold": threshold,
                            "left_indices": node_indices[mask], "right_indices": node_indices[~mask]}
    return best


def fit_tree(features: np.ndarray, gradient: np.ndarray, hessian: np.ndarray, *,
             depth: int, min_leaf_events: int, leaf_l2: float,
             max_leaf_value: float) -> dict[str, Any]:
    """Fit one depth-``depth`` tree; serializes to the portable node shape."""
    all_indices = np.arange(len(gradient), dtype=np.int64)

    def grow(node_indices: np.ndarray, remaining_depth: int) -> dict[str, Any]:
        if remaining_depth == 0:
            return {"value": _round6(_leaf_value(
                float(gradient[node_indices].sum()), float(hessian[node_indices].sum()),
                leaf_l2, max_leaf_value))}
        split = _best_split(features, node_indices, gradient, hessian,
                            min_leaf_events, leaf_l2, max_leaf_value)
        if split is None:
            return {"value": _round6(_leaf_value(
                float(gradient[node_indices].sum()), float(hessian[node_indices].sum()),
                leaf_l2, max_leaf_value))}
        left = grow(split["left_indices"], remaining_depth - 1)
        right = grow(split["right_indices"], remaining_depth - 1)
        return {
            "feature_index": split["feature_index"],
            "threshold": split["threshold"],
            "left": left,
            "right": right,
        }

    return grow(all_indices, depth)


def tree_predict(tree: dict[str, Any], features: np.ndarray) -> np.ndarray:
    """Vectorized prediction for one serialized tree."""
    output = np.zeros(len(features), dtype=np.float64)

    def descend(node: dict[str, Any], indices: np.ndarray) -> None:
        if "value" in node:
            output[indices] = node["value"]
            return
        mask = features[indices, node["feature_index"]] <= node["threshold"]
        descend(node["left"], indices[mask])
        descend(node["right"], indices[~mask])

    descend(tree, np.arange(len(features), dtype=np.int64))
    return output


def boost_train(features: np.ndarray, pairs: list[tuple[int, int]], *, trees: int, depth: int,
                learning_rate: float, min_leaf_events: int, leaf_l2: float,
                max_leaf_value: float, anchor_feature_index: int = 0,
                anchor_weight: float = 1.0) -> dict[str, Any]:
    """Fit residual trees while preserving the raw onset-strength baseline."""
    if not pairs:
        raise ValueError("boost_train needs at least one preference pair")
    if (not isinstance(anchor_feature_index, int) or isinstance(anchor_feature_index, bool)
            or not 0 <= anchor_feature_index < features.shape[1]):
        raise ValueError("anchor_feature_index must address the feature matrix")
    if (not isinstance(anchor_weight, (int, float)) or isinstance(anchor_weight, bool)
            or not math.isfinite(float(anchor_weight)) or anchor_weight <= 0.0):
        raise ValueError("anchor_weight must be a positive finite number")
    scores = anchor_weight * np.asarray(
        features[:, anchor_feature_index], dtype=np.float64)
    serialized_trees: list[dict[str, Any]] = []
    for _round in range(trees):
        gradient, hessian = aggregate_gradients(scores, pairs)
        if float(np.max(np.abs(gradient))) < 1e-12:
            break  # zero gradients create no tree
        tree = fit_tree(features, gradient, hessian, depth=depth,
                        min_leaf_events=min_leaf_events, leaf_l2=leaf_l2,
                        max_leaf_value=max_leaf_value)
        update = tree_predict(tree, features)
        if float(np.max(np.abs(update))) < 1e-12:
            break
        serialized_trees.append(tree)
        scores += learning_rate * update
    return {
        "base_value": 0.0,
        "anchor_feature_index": anchor_feature_index,
        "anchor_weight": anchor_weight,
        "learning_rate": learning_rate,
        "trees": serialized_trees,
    }


def boost_score(features: np.ndarray, model_trees: list[dict[str, Any]],
                base_value: float, learning_rate: float, anchor_feature_index: int,
                anchor_weight: float) -> np.ndarray:
    """score(event) = strength anchor + base + residual tree corrections."""
    scores = (np.full(len(features), float(base_value), dtype=np.float64)
              + anchor_weight * features[:, anchor_feature_index])
    for tree in model_trees:
        scores += learning_rate * tree_predict(tree, features)
    return scores
