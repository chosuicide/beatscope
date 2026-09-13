"""Select a response ranker by leave-one-source-out development validation.

Round 2-C uses every development song exactly once as validation, always in
an entire held-out source.  It never accepts test rows and never reads an
evaluation receipt.  Candidate choice prioritizes sparse top-event utility
while retaining pairwise, dense-mixture, non-metric, and per-source safety.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beatscope import event_ranker as er  # noqa: E402
from beatscope import event_ranker_boost as boost  # noqa: E402
from scripts.train_event_ranker_v3 import (  # noqa: E402
    assemble_training_rows,
    group_by_song,
    pair_row_indices,
    song_ndcg_at_10,
    song_pair_accuracy,
    song_recall_at_k,
    view_matrix,
)

REPORT_SCHEMA = "beatscope-response-ranking-cross-source-selection-1"
MIN_SOURCES = 4


def canonical_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def source_groups(songs: dict[str, dict]) -> dict[str, dict[str, dict]]:
    groups: dict[str, dict[str, dict]] = {}
    for sha, song in songs.items():
        source = song["meta"].get("source_id")
        if not isinstance(source, str) or not source or source == "mixed":
            raise ValueError("every development song must belong to exactly one named source")
        groups.setdefault(source, {})[sha] = song
    return {source: groups[source] for source in sorted(groups)}


def fold_partitions(songs: dict[str, dict]) -> list[tuple[str, set[str], set[str]]]:
    """Return deterministic source-disjoint train/validation ID sets."""
    groups = source_groups(songs)
    return [
        (held, {sha for source, items in groups.items() if source != held for sha in items},
         set(groups[held]))
        for held in groups
    ]


def _credit(scores: np.ndarray, ordered_ids: list[int], song: dict) -> dict[str, float]:
    id_to_row = {onset_id: row for row, onset_id in enumerate(ordered_ids)}
    rows = pair_row_indices(song, id_to_row)
    strengths = np.array([song["events"][onset_id]["strength"] for onset_id in ordered_ids])
    support = {int(onset_id): float(line["support_rate"])
               for onset_id, line in song["events"].items()}
    supported = set(map(int, song["meta"].get("sparsest_supported_onset_ids", [])))
    budget = len(supported) or int(song["meta"].get("sparsest_matched_count", 0))
    if not supported:
        supported = set(sorted(support, key=lambda key: (-support[key], key))[:budget])
    selected = sorted(range(len(ordered_ids)),
                      key=lambda row: (-scores[row], ordered_ids[row]))[:budget]
    return {
        "pairwise_accuracy": song_pair_accuracy(scores, rows, strengths),
        "ndcg_at_10": song_ndcg_at_10(scores, ordered_ids, support),
        "recall_at_k": song_recall_at_k(scores, ordered_ids, support, supported, budget),
        "top_support_precision_at_k": (
            sum(support[ordered_ids[row]] for row in selected) / budget
            if budget else float("nan")),
    }


def _baseline(song: dict) -> dict[str, float]:
    ordered_ids = sorted(song["events"], key=int)
    strengths = np.array([song["events"][onset_id]["strength"] for onset_id in ordered_ids])
    return _credit(strengths, ordered_ids, song)


def _macro(metrics: dict[str, dict[str, float]], key: str,
           ids: set[str] | None = None) -> float:
    values = [row[key] for sha, row in metrics.items()
              if (ids is None or sha in ids) and math.isfinite(row[key])]
    return sum(values) / len(values) if values else float("nan")


def _delta(model: dict[str, dict[str, float]], baseline: dict[str, dict[str, float]],
           key: str, ids: set[str] | None = None) -> float:
    return _macro(model, key, ids) - _macro(baseline, key, ids)


def configuration_name(view: str, config: tuple[int, int, float, int, float, float]) -> str:
    trees, depth, rate, min_leaf, leaf_l2, max_leaf = config
    return f"{view}-t{trees}-d{depth}-lr{rate}-ml{min_leaf}-l2{leaf_l2}-mv{max_leaf}"


def train_configuration(songs: dict[str, dict], view: str,
                        config: tuple[int, int, float, int, float, float]) -> dict:
    trees, depth, rate, min_leaf, leaf_l2, max_leaf = config
    matrix, pairs = assemble_training_rows(songs, view)
    if not pairs:
        raise ValueError("development fold carries no preference pairs")
    return boost.boost_train(
        matrix, pairs, trees=trees, depth=depth, learning_rate=rate,
        min_leaf_events=min_leaf, leaf_l2=leaf_l2, max_leaf_value=max_leaf,
    )


def cross_source_evaluate(songs: dict[str, dict], view: str,
                          config: tuple[int, int, float, int, float, float]) -> dict:
    groups = source_groups(songs)
    if len(groups) < MIN_SOURCES:
        raise ValueError(f"cross-source selection requires at least {MIN_SOURCES} sources")
    model_metrics: dict[str, dict[str, float]] = {}
    baseline_metrics = {sha: _baseline(song) for sha, song in songs.items()}
    fold_rows = []
    for held, train_ids, validation_ids in fold_partitions(songs):
        if train_ids & validation_ids or train_ids | validation_ids != set(songs):
            raise AssertionError("source fold leakage")
        fit = train_configuration({sha: songs[sha] for sha in sorted(train_ids)}, view, config)
        for sha in sorted(validation_ids):
            matrix, ordered_ids, _ = view_matrix(songs[sha], view)
            scores = boost.boost_score(
                matrix, fit["trees"], fit["base_value"], fit["learning_rate"],
                fit["anchor_feature_index"], fit["anchor_weight"],
            )
            if sha in model_metrics:
                raise AssertionError("a development song was validated more than once")
            model_metrics[sha] = _credit(scores, ordered_ids, songs[sha])
        fold_rows.append({"held_source": held, "train_song_count": len(train_ids),
                          "validation_song_count": len(validation_ids)})
    if set(model_metrics) != set(songs):
        raise AssertionError("cross-source validation did not cover every song exactly once")

    densities = sorted((song["meta"]["onset_count"]
                        / max(song["meta"]["duration"], 1e-9), sha)
                       for sha, song in songs.items())
    dense_ids = {sha for _, sha in densities[-max(1, len(densities) // 3):]}
    source_deltas = {
        source: er._round6(_delta(model_metrics, baseline_metrics, "pairwise_accuracy", set(items)))
        for source, items in groups.items()
    }
    metric_names = ("pairwise_accuracy", "ndcg_at_10", "recall_at_k",
                    "top_support_precision_at_k")
    deltas = {name: er._round6(_delta(model_metrics, baseline_metrics, name))
              for name in metric_names}
    bootstrap = er.paired_bootstrap(
        {sha: row["pairwise_accuracy"] for sha, row in model_metrics.items()},
        {sha: row["pairwise_accuracy"] for sha, row in baseline_metrics.items()},
        replicates=10000, seed=20260908,
    )
    return {
        "name": configuration_name(view, config), "feature_view": view,
        "trees": config[0], "depth": config[1], "learning_rate": config[2],
        "min_leaf_events": config[3], "leaf_l2": config[4],
        "max_leaf_value": config[5], "folds": fold_rows,
        "deltas_vs_strength": deltas,
        "dense_tertile_delta": er._round6(
            _delta(model_metrics, baseline_metrics, "pairwise_accuracy", dense_ids)),
        "source_deltas": source_deltas, "bootstrap_pairwise": bootstrap,
        "validated_song_count": len(model_metrics),
    }


def eligible(candidate: dict) -> bool:
    deltas = candidate["deltas_vs_strength"]
    counterpart = candidate.get("non_metric_pairwise_delta")
    return (
        candidate["feature_view"] == "full"
        and deltas["pairwise_accuracy"] > 0.0
        and candidate["bootstrap_pairwise"]["lower_95"] > 0.0
        and deltas["ndcg_at_10"] >= 0.0
        and deltas["recall_at_k"] >= 0.0
        and deltas["top_support_precision_at_k"] >= 0.0
        and candidate["dense_tertile_delta"] > 0.0
        and min(candidate["source_deltas"].values()) >= -0.005
        and counterpart is not None and counterpart > 0.0
    )


def select_candidate(candidates: list[dict]) -> dict | None:
    qualified = [candidate for candidate in candidates if eligible(candidate)]
    if not qualified:
        return None
    return sorted(qualified, key=lambda candidate: (
        -candidate["deltas_vs_strength"]["top_support_precision_at_k"],
        -candidate["deltas_vs_strength"]["ndcg_at_10"],
        -candidate["deltas_vs_strength"]["recall_at_k"],
        -min(candidate["source_deltas"].values()),
        -candidate["deltas_vs_strength"]["pairwise_accuracy"],
        candidate["trees"], candidate["name"],
    ))[0]


def _matching(candidates: list[dict], full: dict) -> dict | None:
    keys = ("trees", "depth", "learning_rate", "min_leaf_events", "leaf_l2",
            "max_leaf_value")
    return next((candidate for candidate in candidates
                 if candidate["feature_view"] == "non_metric"
                 and all(candidate[key] == full[key] for key in keys)), None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    dataset_bytes = args.dataset.read_bytes()
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    dataset_sha = hashlib.sha256(dataset_bytes).hexdigest()
    if (manifest.get("schema") != er.MANIFEST_SCHEMA
            or manifest.get("dataset_schema") != er.DATASET_SCHEMA
            or manifest.get("dataset_sha256") != dataset_sha):
        print("dataset/manifest provenance mismatch", file=sys.stderr)
        return 2
    if any(song.get("split") == "test" for song in manifest.get("songs", [])):
        print("Round 2-C refuses test-split songs", file=sys.stderr)
        return 2
    lines = [json.loads(line) for line in dataset_bytes.decode().splitlines() if line.strip()]
    songs = group_by_song(lines)
    if len(source_groups(songs)) < MIN_SOURCES:
        print(f"Round 2-C requires at least {MIN_SOURCES} independent sources", file=sys.stderr)
        return 1

    candidates = []
    for config in boost.CANDIDATE_GRID:
        for view in boost.FEATURE_VIEWS:
            candidate = cross_source_evaluate(songs, view, config)
            candidates.append(candidate)
            print(f"validated {candidate['name']}", flush=True)
    for candidate in candidates:
        if candidate["feature_view"] == "full":
            counterpart = _matching(candidates, candidate)
            candidate["non_metric_pairwise_delta"] = (
                counterpart["deltas_vs_strength"]["pairwise_accuracy"]
                if counterpart is not None else None)
        else:
            candidate["non_metric_pairwise_delta"] = None
    selected = select_candidate(candidates)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": REPORT_SCHEMA, "method": boost.MODEL_METHOD_V4,
        "dataset_sha256": dataset_sha,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_ids": sorted(source_groups(songs)), "song_count": len(songs),
        "selection_policy": "top-k-utility-with-pairwise-and-source-safety",
        "candidates": candidates, "selected": selected["name"] if selected else None,
        "selection_status": "selected" if selected else "rejected",
    }
    (args.output / "selection-report.json").write_bytes(canonical_bytes(report))
    if selected is None:
        print(json.dumps({"selection_status": "rejected"}, indent=2))
        return 1

    config = (selected["trees"], selected["depth"], selected["learning_rate"],
              selected["min_leaf_events"], selected["leaf_l2"], selected["max_leaf_value"])
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    for view, filename in (("full", "selected.json"),
                           ("non_metric", "selected-non-metric.json")):
        fit = train_configuration(songs, view, config)
        _, pairs = assemble_training_rows(songs, view)
        model = er.build_boost_model_json(
            view, fit, train_song_count=len(songs), validation_song_count=len(songs),
            preference_pair_count=len(pairs), dataset_sha256=dataset_sha,
            manifest_sha256=manifest_sha, status="pending",
        )
        (args.output / filename).write_bytes(er.canonical_boost_model_bytes(model))
    print(json.dumps({"selected": selected["name"],
                      "deltas_vs_strength": selected["deltas_vs_strength"],
                      "source_deltas": selected["source_deltas"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
