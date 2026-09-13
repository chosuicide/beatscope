"""Deterministic pairwise chart-consensus response ranker (v0.11 Round 2).

A dormant module: it learns one narrow ordering - which of two detected
onsets from the same song is more consistently retained by human-authored
rhythm charts across difficulty densities - from the weak labels built by
``chart_labels.py``, using Round 1 event evidence as the only features.

Boundaries (v0.11 Round 2 plan sections 1, 13, 14):

- features come from ``beatscope/event_evidence.py`` records plus the
  published onset ``strength``; no timestamp, song position, filename,
  chart format, difficulty, or label count enters the vector;
- ``response_relevance`` is a logistic transform of the linear rank value
  for bounded portable ordering - it is NOT a calibrated probability, not
  importance, and not an instrument label;
- training is full-batch Newton on L2-regularized pairwise logistic loss
  with deterministic backtracking; no RNG, no wall clock;
- validation selects lambda; the test split is evaluated once by the
  caller; promotion gates live in this module so a failed candidate can
  never emit a promoted artifact.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

MODEL_SCHEMA = "beatscope-response-ranker-1"
MODEL_METHOD = "pairwise-logistic-chart-consensus-v2"
EVIDENCE_SCHEMA = "beatscope-event-evidence-1"
DATASET_SCHEMA = "beatscope-response-ranking-dataset-1"
MANIFEST_SCHEMA = "beatscope-response-ranking-manifest-1"

LAMBDA_CANDIDATES = (0.01, 0.1, 1.0, 10.0)
NEWTON_MAX_ITERATIONS = 50
NEWTON_GRADIENT_TOLERANCE = 1e-8
NEWTON_MIN_STEP = 2.0 ** -30
NEWTON_DECREMENT_TOLERANCE = 1e-12
BOOTSTRAP_REPLICATES = 10000
BOOTSTRAP_SEED = 20260906

# Frozen base evidence features (Round 2 v1); stored verbatim in the model.
BASE_FEATURE_ORDER = (
    "onset_strength",
    "local_rank_all",
    "local_rank_low",
    "local_rank_mid",
    "local_rank_high",
    "local_contrast_all",
    "local_contrast_low",
    "local_contrast_mid",
    "local_contrast_high",
    "spectral_share_low",
    "spectral_share_mid",
    "spectral_share_high",
    "spectral_focus",
    "spectral_active_band_count_scaled",
    "spectral_dominant_low",
    "spectral_dominant_mid",
    "spectral_dominant_high",
    "spectral_dominant_mixed",
    "temporal_log_events_per_second",
    "temporal_previous_gap_clipped",
    "temporal_previous_gap_missing",
    "temporal_next_gap_clipped",
    "temporal_next_gap_missing",
    "temporal_isolatedness",
    "metric_available",
    "metric_abs_offset_ratio_clipped",
    "metric_downbeat",
    "structure_available",
    "structure_distance_clipped",
    "structure_novelty",
    "group_available",
    "group_member_count_log",
    "group_position_normalized",
    "group_span_seconds_clipped",
    "group_density_log",
    "group_interval_trend_clipped",
)

# A small nonlinear basis for the second, independently-held-out method
# version.  Only continuous evidence values are squared: binary masks and
# one-hot categories remain single columns.  This lets the linear ranker
# express useful peaks/troughs without introducing a tree runtime or hidden
# interactions that are difficult for consumers to reproduce.
SQUARED_SOURCE_NAMES = (
    "onset_strength",
    "local_rank_all", "local_rank_low", "local_rank_mid", "local_rank_high",
    "local_contrast_all", "local_contrast_low", "local_contrast_mid",
    "local_contrast_high",
    "spectral_share_low", "spectral_share_mid", "spectral_share_high",
    "spectral_focus", "spectral_active_band_count_scaled",
    "temporal_log_events_per_second", "temporal_previous_gap_clipped",
    "temporal_next_gap_clipped", "temporal_isolatedness",
    "metric_abs_offset_ratio_clipped",
    "structure_distance_clipped", "structure_novelty",
    "group_member_count_log", "group_position_normalized",
    "group_span_seconds_clipped", "group_density_log",
    "group_interval_trend_clipped",
)
FEATURE_ORDER = BASE_FEATURE_ORDER + tuple(
    f"{name}_squared" for name in SQUARED_SOURCE_NAMES
)

_LOCAL_SPECTRAL_NAMES = (
    "local_rank_all", "local_rank_low", "local_rank_mid", "local_rank_high",
    "local_contrast_all", "local_contrast_low", "local_contrast_mid", "local_contrast_high",
    "spectral_share_low", "spectral_share_mid", "spectral_share_high", "spectral_focus",
    "spectral_active_band_count_scaled", "spectral_dominant_low",
    "spectral_dominant_mid", "spectral_dominant_high", "spectral_dominant_mixed",
)
_TEMPORAL_NAMES = (
    "temporal_log_events_per_second", "temporal_previous_gap_clipped",
    "temporal_previous_gap_missing", "temporal_next_gap_clipped",
    "temporal_next_gap_missing", "temporal_isolatedness",
)

def _with_squares(names: tuple[str, ...]) -> tuple[str, ...]:
    selected = set(names)
    return names + tuple(
        f"{name}_squared" for name in SQUARED_SOURCE_NAMES if name in selected
    )


# Fixed ablations (plan section 13.3), extended with the matching nonlinear
# columns so an ablation never borrows information from a removed view.
ABLATIONS: dict[str, tuple[str, ...]] = {
    "strength_only": ("onset_strength",),
    "local_spectral": _with_squares(("onset_strength",) + _LOCAL_SPECTRAL_NAMES),
    "local_spectral_temporal": _with_squares(
        ("onset_strength",) + _LOCAL_SPECTRAL_NAMES + _TEMPORAL_NAMES),
    "non_metric": tuple(name for name in FEATURE_ORDER if not name.startswith("metric_")),
    "full": tuple(FEATURE_ORDER),
}


class RankerError(ValueError):
    """Raised for dataset, optimizer, or contract failures with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _round6(value: float) -> float:
    parsed = round(float(value), 6)
    return 0.0 if parsed == 0.0 else parsed


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * values))


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


# ------------------------------------------------------------------ features


def extract_features(event: dict[str, Any], groups: list[dict[str, Any]],
                     onset_strength: float) -> list[float]:
    """The frozen 62-value vector from one evidence event record.

    Values are emitted in FEATURE_ORDER; optional context contributes an
    explicit availability flag plus zeroed value fields when absent.
    """
    if not math.isfinite(float(onset_strength)):
        raise RankerError("non_finite_feature", "onset strength must be finite")
    local = event["local"]
    spectral = event["spectral"]
    temporal = event["temporal"]
    metric = event.get("metric")
    structure = event.get("structure")
    group_id = event.get("group_id")
    group = None
    if group_id is not None:
        group = next((item for item in groups if item["id"] == group_id), None)

    previous_gap = temporal["previous_gap_seconds"]
    next_gap = temporal["next_gap_seconds"]
    dominant = spectral["dominant_band"]

    vector = [
        float(onset_strength),
        local["rank"]["all"], local["rank"]["low"], local["rank"]["mid"], local["rank"]["high"],
        local["contrast"]["all"], local["contrast"]["low"], local["contrast"]["mid"],
        local["contrast"]["high"],
        spectral["share"]["low"], spectral["share"]["mid"], spectral["share"]["high"],
        spectral["focus"], spectral["active_band_count"] / 3.0,
        1.0 if dominant == "low" else 0.0,
        1.0 if dominant == "mid" else 0.0,
        1.0 if dominant == "high" else 0.0,
        1.0 if dominant == "mixed" else 0.0,
        math.log1p(temporal["events_per_second"]),
        0.0 if previous_gap is None else min(previous_gap, 2.0) / 2.0,
        1.0 if previous_gap is None else 0.0,
        0.0 if next_gap is None else min(next_gap, 2.0) / 2.0,
        1.0 if next_gap is None else 0.0,
        temporal["isolatedness"],
        0.0 if metric is None else 1.0,
        (min(abs(metric["offset_ratio"]), 1.0)
         if metric is not None and metric["offset_ratio"] is not None else 0.0),
        1.0 if metric is not None and metric["downbeat"] else 0.0,
        0.0 if structure is None else 1.0,
        (min(structure["distance_seconds"], 8.0) / 8.0) if structure is not None else 0.0,
        structure["novelty"] if structure is not None else 0.0,
    ]
    if group is not None:
        member_count = len(group["onset_ids"])
        vector.extend([
            1.0,
            math.log1p(member_count),
            group["onset_ids"].index(event["onset_id"]) / max(member_count - 1, 1),
            min(group["span_seconds"], 1.5) / 1.5,
            math.log1p(group["density_hz"]),
            max(-1.0, min(1.0, group["interval_trend"] / 0.18)),
        ])
    else:
        vector.extend((0.0,) * 6)
    by_name = dict(zip(BASE_FEATURE_ORDER, vector, strict=True))
    vector.extend(by_name[name] ** 2 for name in SQUARED_SOURCE_NAMES)
    return vector


def ablation_indices(ablation: str) -> list[int]:
    names = ABLATIONS[ablation]
    return [FEATURE_ORDER.index(name) for name in names]


# ----------------------------------------------------------------- optimizer


def fit_normalization(matrix: np.ndarray) -> dict[str, list[float]]:
    """Train-only median/IQR standardization statistics (plan section 14.2)."""
    center = np.median(matrix, axis=0)
    q75 = np.quantile(matrix, 0.75, axis=0)
    q25 = np.quantile(matrix, 0.25, axis=0)
    scale = np.maximum(q75 - q25, 1e-6)
    return {
        "center": [_round6(value) for value in center],
        "scale": [_round6(value) for value in scale],
    }


def apply_normalization(matrix: np.ndarray, normalization: dict[str, list[float]]) -> np.ndarray:
    center = np.array(normalization["center"], dtype=np.float64)
    scale = np.array(normalization["scale"], dtype=np.float64)
    return (matrix - center) / scale


def _penalized_loss(weights: np.ndarray, design: np.ndarray, lam: float) -> float:
    margins = design @ weights
    loss = float(np.sum(np.logaddexp(0.0, -margins)))
    return loss + 0.5 * lam * float(weights @ weights)


def newton_fit(design: np.ndarray, lam: float) -> tuple[np.ndarray, int]:
    """Full-batch Newton with deterministic backtracking (plan section 14.3)."""
    rows = design.shape[0]
    weights = np.zeros(design.shape[1], dtype=np.float64)
    identity = np.eye(design.shape[1]) * lam
    for iteration in range(1, NEWTON_MAX_ITERATIONS + 1):
        margins = design @ weights
        probabilities = _sigmoid(margins)
        gradient = design.T @ (probabilities - 1.0) + lam * weights
        if float(np.max(np.abs(gradient))) < NEWTON_GRADIENT_TOLERANCE:
            return weights, iteration - 1
        curvature = probabilities * (1.0 - probabilities)
        hessian = design.T @ (design * curvature[:, None]) + identity
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError as error:
            raise RankerError("optimizer_failed", "singular Hessian after L2") from error
        base_loss = _penalized_loss(weights, design, lam)
        # With highly sparse evidence, an IQR-clamped feature can legitimately
        # produce a large raw gradient and an almost-zero Newton step.  At that
        # point the predicted loss reduction is below float64 resolution even
        # though the absolute-gradient test has not fired.  Treat the standard
        # Newton decrement as the second convergence criterion instead of
        # misreporting a line-search failure on an already-converged solution.
        decrement = float(gradient @ step)
        if not math.isfinite(decrement) or decrement < 0.0:
            raise RankerError("optimizer_failed", "invalid Newton decrement")
        if decrement <= NEWTON_DECREMENT_TOLERANCE * max(1.0, abs(base_loss)):
            return weights, iteration - 1
        alpha = 1.0
        while alpha >= NEWTON_MIN_STEP:
            candidate = weights - alpha * step
            if _penalized_loss(candidate, design, lam) < base_loss:
                weights = candidate
                break
            alpha /= 2.0
        else:
            raise RankerError("optimizer_failed", "line search could not decrease the loss")
    final_gradient = design.T @ (_sigmoid(design @ weights) - 1.0) + lam * weights
    if float(np.max(np.abs(final_gradient))) < NEWTON_GRADIENT_TOLERANCE:
        return weights, NEWTON_MAX_ITERATIONS
    return weights, NEWTON_MAX_ITERATIONS


def train_pair_weights(pair_vectors: list[tuple[list[float], list[float]]], lam: float,
                       normalization: dict[str, list[float]] | None = None) -> tuple[np.ndarray, dict[str, list[float]], int]:
    """Fit weights on preference pairs; returns weights, normalization, iterations."""
    if not pair_vectors:
        raise RankerError("empty_training_pairs", "no preference pairs to train on")
    positives = np.array([pair[0] for pair in pair_vectors], dtype=np.float64)
    negatives = np.array([pair[1] for pair in pair_vectors], dtype=np.float64)
    if normalization is None:
        stacked = np.vstack([positives, negatives])
        normalization = fit_normalization(stacked)
    design = apply_normalization(positives, normalization) - apply_normalization(negatives, normalization)
    if not np.all(np.isfinite(design)):
        raise RankerError("non_finite_feature", "standardized pair design is not finite")
    weights, iterations = newton_fit(design, lam)
    return weights, normalization, iterations


# -------------------------------------------------------------- model artifact


def build_model_json(weights: np.ndarray, normalization: dict[str, list[float]], *,
                     lam: float, iterations: int, train_song_count: int,
                     validation_song_count: int, preference_pair_count: int,
                     dataset_manifest_sha256: str, evaluation_report_sha256: str,
                     status: str) -> dict[str, Any]:
    return {
        "schema": MODEL_SCHEMA,
        "method": MODEL_METHOD,
        "event_evidence_schema": EVIDENCE_SCHEMA,
        "feature_order": list(FEATURE_ORDER),
        "normalization": normalization,
        "weights": [_round6(value) for value in weights],
        "training": {
            "lambda": lam,
            "iterations": iterations,
            "train_song_count": train_song_count,
            "validation_song_count": validation_song_count,
            "preference_pair_count": preference_pair_count,
            "dataset_manifest_sha256": dataset_manifest_sha256,
        },
        "promotion": {
            "status": status,
            "evaluation_report_sha256": evaluation_report_sha256,
        },
    }


def validate_model_json(model: Any) -> list[str]:
    """Contract validation for the portable model JSON (plan section 15)."""
    errors: list[str] = []
    if not isinstance(model, dict):
        return ["model must be a JSON object"]
    if model.get("schema") != MODEL_SCHEMA:
        errors.append(f"schema must be {MODEL_SCHEMA!r}")
    if model.get("method") != MODEL_METHOD:
        errors.append(f"method must be {MODEL_METHOD!r}")
    if model.get("event_evidence_schema") != EVIDENCE_SCHEMA:
        errors.append(f"event_evidence_schema must be {EVIDENCE_SCHEMA!r}")
    if model.get("feature_order") != list(FEATURE_ORDER):
        errors.append("feature_order must equal the frozen feature order")
    normalization = model.get("normalization")
    weights = model.get("weights")
    if not isinstance(normalization, dict) or set(normalization) != {"center", "scale"}:
        errors.append("normalization must hold exactly center and scale")
    else:
        count = len(FEATURE_ORDER)
        center = normalization.get("center")
        scale = normalization.get("scale")
        if not isinstance(weights, list) or not isinstance(center, list) or not isinstance(scale, list):
            errors.append("weights, center, and scale must be lists")
        elif len(weights) != count or len(center) != count or len(scale) != count:
            errors.append(f"weights/center/scale must each hold {count} values")
        else:
            if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                       and math.isfinite(float(value)) for value in weights + center):
                errors.append("weights must be finite")
            if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                       and math.isfinite(float(value)) and float(value) > 0 for value in scale):
                errors.append("normalization scale values must be positive finite numbers")
    training = model.get("training")
    training_keys = {"lambda", "iterations", "train_song_count", "validation_song_count",
                     "preference_pair_count", "dataset_manifest_sha256"}
    if not isinstance(training, dict) or set(training) != training_keys:
        errors.append("training must hold exactly the six provenance fields")
    else:
        if training.get("lambda") not in LAMBDA_CANDIDATES:
            errors.append("training lambda must be one of the frozen candidates")
        for key in ("iterations", "train_song_count", "validation_song_count", "preference_pair_count"):
            if not isinstance(training.get(key), int) or isinstance(training.get(key), bool) \
                    or training[key] < 0:
                errors.append(f"training {key} must be a non-negative integer")
        for key in ("train_song_count", "validation_song_count", "preference_pair_count"):
            if isinstance(training.get(key), int) and not isinstance(training.get(key), bool) \
                    and training[key] == 0:
                errors.append(f"training {key} must be positive")
        digest = training.get("dataset_manifest_sha256")
        if not isinstance(digest, str) or len(digest) != 64 \
                or any(char not in "0123456789abcdef" for char in digest):
            errors.append("dataset_manifest_sha256 must be a lowercase SHA-256")
    promotion = model.get("promotion")
    if not isinstance(promotion, dict) or set(promotion) != {"status", "evaluation_report_sha256"}:
        errors.append("promotion must hold exactly status and evaluation_report_sha256")
    elif promotion.get("status") not in ("passed", "rejected", "pending"):
        errors.append("promotion status must be passed, rejected, or pending")
    elif promotion["status"] == "passed":
        digest = promotion.get("evaluation_report_sha256")
        if not isinstance(digest, str) or len(digest) != 64 \
                or any(char not in "0123456789abcdef" for char in digest):
            errors.append("passed models require an evaluation report SHA-256")
    raw = json.dumps(model)
    for forbidden in ("pickle", "eval(", "exec(", "subprocess", "os.system"):
        if forbidden in raw:
            errors.append(f"model bytes must not contain {forbidden!r}")
    return errors


def canonical_model_bytes(model: dict[str, Any]) -> bytes:
    errors = validate_model_json(model)
    if errors:
        raise RankerError("model_contract_mismatch", "; ".join(errors))
    return (json.dumps(model, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


# ------------------------------------------------------------------ inference


def score_events(events: list[dict[str, Any]], groups: list[dict[str, Any]],
                 strengths: dict[int, float], model: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank every event; returns one row per event with a bounded relevance.

    The ranked ID set is exactly the input ID set - nothing is added,
    removed, merged, or duplicated, and no timestamp is emitted.
    """
    errors = validate_model_json(model)
    if errors:
        raise RankerError("model_contract_mismatch", "; ".join(errors))
    weights = np.asarray(model["weights"], dtype=np.float64)
    center = np.asarray(model["normalization"]["center"], dtype=np.float64)
    scale = np.asarray(model["normalization"]["scale"], dtype=np.float64)
    matrix = np.array(
        [extract_features(event, groups, strengths[event["onset_id"]]) for event in events],
        dtype=np.float64,
    )
    if not np.isfinite(matrix).all():
        raise RankerError("non_finite_feature", "feature matrix contains a non-finite value")
    values = ((matrix - center) / scale) @ weights
    relevances = 0.5 * (1.0 + np.tanh(0.5 * values))
    return [
        {"onset_id": int(event["onset_id"]), "response_relevance": _round6(float(relevance))}
        for event, relevance in zip(events, relevances)
    ]


def ranked_ids(rows: list[dict[str, Any]]) -> list[int]:
    """Total order: relevance descending, then onset ID ascending."""
    return [row["onset_id"] for row in sorted(rows, key=lambda row: (-row["response_relevance"], row["onset_id"]))]


# -------------------------------------------------------------------- metrics


def _song_pair_accuracy(weights: np.ndarray, normalization: dict[str, list[float]],
                        feature_map: dict[int, np.ndarray], pairs: list[dict[str, int]]) -> float:
    if not pairs:
        return float("nan")
    credit = 0.0
    for pair in pairs:
        difference = (apply_normalization(feature_map[pair["preferred_onset_id"]][None, :], normalization)
                      - apply_normalization(feature_map[pair["other_onset_id"]][None, :], normalization))[0]
        margin = float(difference @ weights)
        credit += 1.0 if margin > 0 else (0.0 if margin < 0 else 0.5)
    return credit / len(pairs)


def _song_ndcg_at_10(scores: dict[int, float], support: dict[int, float]) -> float:
    if not scores:
        return float("nan")
    ordered = sorted(scores, key=lambda onset_id: (-scores[onset_id], onset_id))
    gains = [support.get(onset_id, 0.0) for onset_id in ordered[:10]]
    dcg = sum(rel / math.log2(position + 2) for position, rel in enumerate(gains))
    ideal = sorted(support.values(), reverse=True)[:10]
    idcg = sum(rel / math.log2(position + 2) for position, rel in enumerate(ideal))
    if idcg <= 0.0:
        return 0.0  # zero-relevance song: handled explicitly, never hidden
    return dcg / idcg


def _song_recall_at_k(scores: dict[int, float], support: dict[int, float],
                      supported_ids: set[int], budget: int) -> float:
    if budget <= 0:
        return float("nan")
    ordered = sorted(scores, key=lambda onset_id: (-scores[onset_id], onset_id))[:budget]
    hits = sum(1 for onset_id in ordered if onset_id in supported_ids)
    return hits / budget


def _song_top_support_precision(scores: dict[int, float], support: dict[int, float],
                                budget: int) -> float:
    if budget <= 0:
        return float("nan")
    ordered = sorted(scores, key=lambda onset_id: (-scores[onset_id], onset_id))[:budget]
    return sum(support.get(onset_id, 0.0) for onset_id in ordered) / budget


def macro_metric(per_song: dict[str, float]) -> float:
    values = [value for value in per_song.values() if not math.isnan(value)]
    if not values:
        return float("nan")
    return sum(values) / len(values)


def paired_bootstrap(per_song_model: dict[str, float], per_song_baseline: dict[str, float],
                     replicates: int = BOOTSTRAP_REPLICATES,
                     seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Deterministic paired song-level bootstrap (plan section 16.5)."""
    shared = sorted(set(per_song_model) & set(per_song_baseline))
    finite = [
        key for key in shared
        if math.isfinite(float(per_song_model[key])) and math.isfinite(float(per_song_baseline[key]))
    ]
    if not finite:
        return {"lower_95": None, "upper_95": None, "indices_sha256": ""}
    shared = finite
    model_values = np.array([per_song_model[key] for key in shared], dtype=np.float64)
    baseline_values = np.array([per_song_baseline[key] for key in shared], dtype=np.float64)
    deltas = model_values - baseline_values
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(shared), size=(replicates, len(shared)))
    means = deltas[indices].mean(axis=1)
    lower, upper = np.percentile(means, [2.5, 97.5])
    digest = hashlib.sha256(indices.astype("<i8").tobytes()).hexdigest()
    return {
        "lower_95": _round6(lower),
        "upper_95": _round6(upper),
        "indices_sha256": digest,
        "replicates": replicates,
        "seed": seed,
    }


# ----------------------------------------------------------- promotion gates


CORPUS_GATES: dict[str, Any] = {
    "min_songs": 24,
    "min_test_songs": 4,
    "min_charts_per_song": 3,
    "min_alignment_p95_le_25ms_share": 0.80,
    "max_alignment_p95_seconds": 0.040,
}

RANKING_GATES: dict[str, float] = {
    "min_pairwise_delta": 0.02,
    "min_ndcg_delta": -0.005,
    "min_recall_delta": -0.01,
    "min_non_metric_delta": 0.01,
    "max_format_slice_loss": 0.02,
}


def _meets(value: Any, threshold: float) -> bool:
    """None-tolerant threshold check: a missing metric fails the gate."""
    return value is not None and float(value) >= threshold


def _above(value: Any, threshold: float) -> bool:
    return value is not None and float(value) > threshold


def evaluate_promotion_gates(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Every promotion gate with a pass/fail verdict (plan section 17)."""
    results: list[dict[str, Any]] = []

    def gate(name: str, passed: bool, detail: str) -> None:
        results.append({"gate": name, "passed": bool(passed), "detail": detail})

    corpus = report.get("corpus", {})
    gate("corpus_min_songs", _meets(corpus.get("song_count", 0), CORPUS_GATES["min_songs"]),
         f"song_count={corpus.get('song_count', 0)}")
    gate("corpus_min_test_songs", _meets(corpus.get("test_song_count", 0), CORPUS_GATES["min_test_songs"]),
         f"test_song_count={corpus.get('test_song_count', 0)}")
    charts_per_song = corpus.get("min_retained_charts_per_song", 0)
    gate("corpus_charts_per_song", _meets(charts_per_song, CORPUS_GATES["min_charts_per_song"]),
         f"min_retained_charts_per_song={charts_per_song}")
    gate("corpus_zero_leakage", corpus.get("leakage_error_count", 1) == 0,
         f"leakage_error_count={corpus.get('leakage_error_count', 1)}")
    gate("corpus_licenses_known", corpus.get("unknown_license_count", 1) == 0,
         f"unknown_license_count={corpus.get('unknown_license_count', 1)}")
    share = corpus.get("alignment_p95_le_25ms_share", 0.0)
    max_p95 = corpus.get("max_alignment_p95_seconds")
    gate("corpus_alignment_residuals",
         _meets(share, CORPUS_GATES["min_alignment_p95_le_25ms_share"])
         and max_p95 is not None and max_p95 <= CORPUS_GATES["max_alignment_p95_seconds"],
         f"p95_le_25ms_share={share}, max_p95={max_p95}")

    ranking = report.get("ranking", {})
    deltas = ranking.get("deltas_vs_strength", {})
    gate("pairwise_improvement",
         _meets(deltas.get("pairwise_accuracy"), RANKING_GATES["min_pairwise_delta"]),
         f"delta={deltas.get('pairwise_accuracy')}")
    bootstrap = ranking.get("bootstrap_pairwise", {})
    gate("bootstrap_lower_bound_positive", _above(bootstrap.get("lower_95"), 0.0),
         f"lower_95={bootstrap.get('lower_95')}")
    gate("ndcg_not_worse", _meets(deltas.get("ndcg_at_10"), RANKING_GATES["min_ndcg_delta"]),
         f"delta={deltas.get('ndcg_at_10')}")
    gate("sparse_recall_not_worse", _meets(deltas.get("recall_at_k"), RANKING_GATES["min_recall_delta"]),
         f"delta={deltas.get('recall_at_k')}")
    dense = ranking.get("slices", {}).get("highest_density_tertile", {})
    gate("dense_tertile_improvement", _above(dense.get("pairwise_delta_vs_strength"), 0.0),
         f"dense_delta={dense.get('pairwise_delta_vs_strength')}")
    non_metric = ranking.get("ablations", {}).get("non_metric", {})
    gate("non_metric_improvement",
         _meets(non_metric.get("pairwise_delta_vs_strength"), RANKING_GATES["min_non_metric_delta"]),
         f"delta={non_metric.get('pairwise_delta_vs_strength')}")
    format_slices = ranking.get("slices", {}).get("formats", {})
    format_slices_ok = bool(format_slices) and all(
        _meets(values.get("pairwise_delta_vs_strength"), -RANKING_GATES["max_format_slice_loss"])
        for values in format_slices.values()
    )
    gate("format_slices_not_lost", format_slices_ok,
         f"formats={ {name: values.get('pairwise_delta_vs_strength') for name, values in format_slices.items()} }")
    gate("metrics_finite", bool(ranking.get("all_metrics_finite", False)),
         f"all_metrics_finite={ranking.get('all_metrics_finite', False)}")
    performance = report.get("performance", {})
    gate("inference_budget", _meets(performance.get("inference_10k_ms"), 0.0)
         and performance.get("inference_10k_ms", 1e9) < 250.0,
         f"inference_10k_ms={performance.get('inference_10k_ms')}")
    gate("model_size_budget", _meets(performance.get("model_bytes"), 0.0)
         and performance.get("model_bytes", 1 << 20) < 64 * 1024,
         f"model_bytes={performance.get('model_bytes')}")
    gate("inference_memory_budget",
         _meets(performance.get("inference_10k_peak_mib"), 0.0)
         and performance.get("inference_10k_peak_mib", 1e9) < 64.0,
         f"peak_mib={performance.get('inference_10k_peak_mib')}")
    return results


def promotion_status(gate_results: list[dict[str, Any]]) -> str:
    return "passed" if all(result["passed"] for result in gate_results) else "rejected"
