"""Train the Round 2-B strength-anchored response scorer (development only).

Reads the cross-corpus development dataset, enforces the section 3.2
minimums, trains exactly the frozen 12-candidate grid on the train split,
evaluates every candidate on validation only, and applies the frozen
eligibility and lexicographic selection. Test-split rows are refused: B1
never reads them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from beatscope import event_ranker as er  # noqa: E402
from beatscope import event_ranker_boost as boost  # noqa: E402
from beatscope.chart_labels import (  # noqa: E402
    MIN_DEV_CHARTS,
    MIN_DEV_SONGS,
    MIN_DEV_SOURCES,
    MIN_DEV_VALIDATION_SONGS,
)


def load_dataset(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def group_by_song(lines: list[dict]) -> dict[str, dict]:
    songs: dict[str, dict] = {}
    for line in lines:
        sha = line["audio_sha256"]
        songs.setdefault(sha, {"events": {}, "pairs": [], "meta": None})
        if line["kind"] == "song":
            songs[sha]["meta"] = line
        elif line["kind"] == "event":
            songs[sha]["events"][line["onset_id"]] = line
        elif line["kind"] == "pair":
            songs[sha]["pairs"].append(line)
    return songs


def view_matrix(song: dict, view: str) -> tuple[np.ndarray, list[int], dict[int, int]]:
    """Feature matrix in view order, the onset-id order, and an id->row map."""
    indices = er.boost_feature_indices(view)
    ordered_ids = sorted(song["events"], key=int)
    rows = []
    for onset_id in ordered_ids:
        event_line = song["events"][onset_id]
        groups = [event_line["group"]] if event_line.get("group") is not None else []
        vector = er.extract_features(event_line["evidence"], groups, event_line["strength"])
        rows.append([vector[position] for position in indices])
    id_to_row = {int(onset_id): row for row, onset_id in enumerate(ordered_ids)}
    return np.array(rows, dtype=np.float64), [int(onset_id) for onset_id in ordered_ids], id_to_row


def pair_row_indices(song: dict, id_to_row: dict[int, int]) -> list[tuple[int, int]]:
    return [(id_to_row[pair["preferred_onset_id"]], id_to_row[pair["other_onset_id"]])
            for pair in song["pairs"]]


def song_pair_accuracy(scores: np.ndarray, rows: list[tuple[int, int]],
                       strength_scores: np.ndarray) -> float:
    """Pairwise accuracy of the model against the strength baseline."""
    if not rows:
        return float("nan")
    credit = 0.0
    baseline_credit = 0.0
    for preferred, other in rows:
        margin = float(scores[preferred] - scores[other])
        credit += 1.0 if margin > 0 else (0.0 if margin < 0 else 0.5)
        strength_margin = float(strength_scores[preferred] - strength_scores[other])
        baseline_credit += 1.0 if strength_margin > 0 else (0.0 if strength_margin < 0 else 0.5)
    return credit / len(rows)


def song_ndcg_at_10(scores: np.ndarray, ordered_ids: list[int],
                    support: dict[int, float]) -> float:
    order = sorted(range(len(ordered_ids)), key=lambda row: (-scores[row], ordered_ids[row]))
    gains = [support.get(ordered_ids[row], 0.0) for row in order[:10]]
    dcg = sum(rel / math.log2(position + 2) for position, rel in enumerate(gains))
    ideal = sorted(support.values(), reverse=True)[:10]
    idcg = sum(rel / math.log2(position + 2) for position, rel in enumerate(ideal))
    if idcg <= 0.0:
        return 0.0
    return dcg / idcg


def song_recall_at_k(scores: np.ndarray, ordered_ids: list[int], support: dict[int, float],
                     supported_ids: set[int], budget: int) -> float:
    if budget <= 0:
        return float("nan")
    order = sorted(range(len(ordered_ids)), key=lambda row: (-scores[row], ordered_ids[row]))[:budget]
    return sum(1 for row in order if ordered_ids[row] in supported_ids) / budget


def macro(values: dict[str, float]) -> float:
    finite = [value for value in values.values() if math.isfinite(value)]
    if not finite:
        return float("nan")
    return sum(finite) / len(finite)


def slice_delta(model_values: dict[str, float], baseline_values: dict[str, float],
                song_ids: set[str]) -> float:
    """Macro delta over the same song IDs on both sides of a slice."""
    return macro({sha: model_values[sha] for sha in sorted(song_ids) if sha in model_values}) \
        - macro({sha: baseline_values[sha] for sha in sorted(song_ids) if sha in baseline_values})


def assemble_training_rows(songs: dict[str, dict], view: str) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Concatenate songs while translating each pair to global row indices."""
    matrices: list[np.ndarray] = []
    pairs: list[tuple[int, int]] = []
    event_offset = 0
    for sha in sorted(songs):
        matrix, _ids, id_to_row = view_matrix(songs[sha], view)
        pairs.extend((preferred + event_offset, other + event_offset)
                     for preferred, other in pair_row_indices(songs[sha], id_to_row))
        matrices.append(matrix)
        event_offset += len(matrix)
    if not matrices:
        return np.empty((0, len(er.boost_feature_indices(view))), dtype=np.float64), []
    return np.vstack(matrices), pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    dataset_bytes = args.dataset.read_bytes()
    dataset_sha = hashlib.sha256(dataset_bytes).hexdigest()
    if manifest.get("schema") != er.MANIFEST_SCHEMA \
            or manifest.get("dataset_schema") != er.DATASET_SCHEMA \
            or manifest.get("dataset_sha256") != dataset_sha:
        print("dataset/manifest provenance mismatch", file=sys.stderr)
        return 2
    if any(song.get("split") == "test" for song in manifest.get("songs", [])):
        print("refusing to train: the manifest carries test-split songs; "
              "Round 2-B1 accepts development data only", file=sys.stderr)
        return 2

    lines = [json.loads(line) for line in dataset_bytes.decode("utf-8").splitlines() if line.strip()]
    songs = group_by_song(lines)
    if any(song["meta"] is not None and song["meta"]["split"] == "test" for song in songs.values()):
        print("refusing to train: the dataset carries test-split rows; "
              "Round 2-B1 accepts development data only", file=sys.stderr)
        return 2

    readiness = manifest.get("development_readiness", {})
    minimum_failures = []
    if readiness.get("song_count", 0) < MIN_DEV_SONGS:
        minimum_failures.append(f"songs {readiness.get('song_count', 0)} < {MIN_DEV_SONGS}")
    if readiness.get("source_count", 0) < MIN_DEV_SOURCES:
        minimum_failures.append(f"sources {readiness.get('source_count', 0)} < {MIN_DEV_SOURCES}")
    if readiness.get("chart_count", 0) < MIN_DEV_CHARTS:
        minimum_failures.append(f"charts {readiness.get('chart_count', 0)} < {MIN_DEV_CHARTS}")
    if readiness.get("validation_song_count", 0) < MIN_DEV_VALIDATION_SONGS:
        minimum_failures.append(
            f"validation songs {readiness.get('validation_song_count', 0)} < {MIN_DEV_VALIDATION_SONGS}")
    if minimum_failures:
        print("development corpus does not meet the section 3.2 minimums: "
              + "; ".join(minimum_failures), file=sys.stderr)
        return 1

    train_songs = {sha: song for sha, song in songs.items() if song["meta"]["split"] == "train"}
    validation_songs = {sha: song for sha, song in songs.items()
                        if song["meta"]["split"] == "validation"}
    if not train_songs or not validation_songs:
        print("development corpus needs both train and validation songs", file=sys.stderr)
        return 1

    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

    source_by_song = {
        song["audio_sha256"]: song["source_ids"][0] if song.get("source_ids") else "unknown"
        for song in manifest.get("songs", [])
    }
    validation_sources = sorted({source_by_song.get(sha, "unknown") for sha in validation_songs})
    validation_densities = sorted(
        (song["meta"]["onset_count"] / max(song["meta"]["duration"], 1e-9), sha)
        for sha, song in validation_songs.items())
    third = max(1, len(validation_densities) // 3)
    dense_ids = {sha for _, sha in validation_densities[-third:]}

    strength_ndcg = _strength_ndcg_delta(validation_songs)
    strength_recall = _strength_recall(validation_songs)
    candidates: list[dict] = []
    candidate_models: dict[str, dict] = {}
    for trees, depth, learning_rate, min_leaf_events, leaf_l2, max_leaf_value in boost.CANDIDATE_GRID:
        for view in boost.FEATURE_VIEWS:
            name = f"{view}-t{trees}-d{depth}-lr{learning_rate}-ml{min_leaf_events}-l2{leaf_l2}-mv{max_leaf_value}"
            full_matrix, train_pairs = assemble_training_rows(train_songs, view)
            if not train_pairs:
                print("development dataset carries no training pairs", file=sys.stderr)
                return 1
            fit = boost.boost_train(
                full_matrix, train_pairs, trees=trees, depth=depth,
                learning_rate=learning_rate, min_leaf_events=min_leaf_events,
                leaf_l2=leaf_l2, max_leaf_value=max_leaf_value)

            per_song_pairwise: dict[str, float] = {}
            per_song_strength: dict[str, float] = {}
            per_song_ndcg: dict[str, float] = {}
            per_song_recall: dict[str, float] = {}
            dense_pairwise: dict[str, float] = {}
            source_pairwise: dict[str, dict[str, float]] = {
                source: {} for source in validation_sources}
            for sha, song in validation_songs.items():
                matrix, ordered_ids, _ = view_matrix(song, view)
                rows = pair_row_indices(song, {onset_id: row for row, onset_id in enumerate(ordered_ids)})
                scores = boost.boost_score(
                    matrix, fit["trees"], fit["base_value"], fit["learning_rate"],
                    fit["anchor_feature_index"], fit["anchor_weight"])
                strength_scores = np.array([
                    float(song["events"][onset_id]["strength"]) for onset_id in ordered_ids])
                support = {int(onset_id): float(line["support_rate"])
                           for onset_id, line in song["events"].items()}
                supported_ids = {onset_id for onset_id, rate in support.items() if rate > 0.0}
                budget = int(song["meta"].get("sparsest_matched_count", 0))
                per_song_pairwise[sha] = song_pair_accuracy(scores, rows, strength_scores)
                per_song_strength[sha] = song_pair_accuracy(strength_scores, rows, strength_scores)
                per_song_ndcg[sha] = song_ndcg_at_10(scores, ordered_ids, support)
                per_song_recall[sha] = song_recall_at_k(
                    scores, ordered_ids, support, supported_ids, budget)
                if sha in dense_ids:
                    dense_pairwise[sha] = per_song_pairwise[sha]
                source = source_by_song.get(sha, "unknown")
                source_pairwise.setdefault(source, {})[sha] = per_song_pairwise[sha]

            overall_delta = macro(per_song_pairwise) - macro(per_song_strength)
            source_deltas = {
                source: slice_delta(per_song_pairwise, per_song_strength, set(values))
                for source, values in source_pairwise.items()
            }
            model_json = er.build_boost_model_json(
                view, fit, train_song_count=len(train_songs),
                validation_song_count=len(validation_songs),
                preference_pair_count=len(train_pairs),
                dataset_sha256=dataset_sha, manifest_sha256=manifest_sha, status="pending")
            model_bytes = len(er.canonical_boost_model_bytes(model_json))
            candidates.append({
                "name": name,
                "feature_view": view,
                "trees": trees,
                "depth": depth,
                "learning_rate": learning_rate,
                "min_leaf_events": min_leaf_events,
                "leaf_l2": leaf_l2,
                "max_leaf_value": max_leaf_value,
                "model_bytes": model_bytes,
                "overall_pairwise_delta": er._round6(overall_delta),
                "dense_tertile_delta": er._round6(
                    slice_delta(per_song_pairwise, per_song_strength, dense_ids)),
                "ndcg_delta": er._round6(macro(per_song_ndcg) - strength_ndcg),
                "recall_delta": er._round6(macro(per_song_recall) - strength_recall),
                "source_deltas": {source: er._round6(delta)
                                  for source, delta in source_deltas.items()},
                "non_metric_pairwise_delta": None,
                "validation_pairwise": macro(per_song_pairwise),
            })
            candidate_models[name] = model_json

    # Attach each full-view candidate's non-metric counterpart overall delta.
    for candidate in candidates:
        if candidate["feature_view"] == "full":
            counterpart = _matching_non_metric(candidates, candidate)
            candidate["non_metric_pairwise_delta"] = (
                counterpart["overall_pairwise_delta"] if counterpart is not None else None)

    selected = er.select_boosted_candidate(candidates)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "beatscope-response-ranking-selection-1",
        "method": boost.MODEL_METHOD_V4,
        "dataset_sha256": dataset_sha,
        "manifest_sha256": manifest_sha,
        "train_song_count": len(train_songs),
        "validation_song_count": len(validation_songs),
        "candidates": [
            {key: value for key, value in candidate.items() if key != "validation_pairwise"}
            for candidate in candidates
        ],
        "selected": selected["name"] if selected else None,
        "selection_status": "selected" if selected else "rejected",
    }
    (args.output / "selection-report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    for name, model_json in candidate_models.items():
        (args.output / f"candidate-{name}.json").write_bytes(
            er.canonical_boost_model_bytes(model_json))
    if selected is None:
        print(json.dumps({"selection_status": "rejected",
                          "candidates": len(candidates)}, indent=2))
        return 1
    selected_model = candidate_models[selected["name"]]
    (args.output / "selected.json").write_bytes(er.canonical_boost_model_bytes(selected_model))
    print(json.dumps({
        "selected": selected["name"],
        "overall_pairwise_delta": selected["overall_pairwise_delta"],
        "dense_tertile_delta": selected["dense_tertile_delta"],
    }, indent=2))
    return 0


def _matching_non_metric(candidates: list[dict], full_candidate: dict) -> dict | None:
    configuration_keys = (
        "trees", "depth", "learning_rate", "min_leaf_events", "leaf_l2", "max_leaf_value")
    for candidate in candidates:
        if candidate["feature_view"] == "non_metric" \
                and all(candidate[key] == full_candidate[key] for key in configuration_keys):
            return candidate
    return None


def _strength_ndcg_delta(validation_songs: dict) -> float:
    """Macro NDCG@10 of the raw-strength baseline over validation songs."""
    values = []
    for song in validation_songs.values():
        ordered_ids = sorted(song["events"], key=int)
        scores = np.array([float(song["events"][onset_id]["strength"]) for onset_id in ordered_ids])
        support = {int(onset_id): float(line["support_rate"])
                   for onset_id, line in song["events"].items()}
        values.append(song_ndcg_at_10(scores, ordered_ids, support))
    finite = [value for value in values if math.isfinite(value)]
    return sum(finite) / len(finite) if finite else float("nan")


def _strength_recall(validation_songs: dict) -> float:
    values = []
    for song in validation_songs.values():
        ordered_ids = sorted(song["events"], key=int)
        scores = np.array([float(song["events"][onset_id]["strength"]) for onset_id in ordered_ids])
        support = {int(onset_id): float(line["support_rate"])
                   for onset_id, line in song["events"].items()}
        supported_ids = {onset_id for onset_id, rate in support.items() if rate > 0.0}
        budget = int(song["meta"].get("sparsest_matched_count", 0))
        values.append(song_recall_at_k(scores, ordered_ids, support, supported_ids, budget))
    finite = [value for value in values if math.isfinite(value)]
    return sum(finite) / len(finite) if finite else float("nan")


if __name__ == "__main__":
    raise SystemExit(main())
