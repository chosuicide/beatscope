"""Train the deterministic pairwise response ranker (v0.11 Round 2).

Reads the built dataset.jsonl, fits one candidate per frozen lambda on the
train split only, selects by validation macro pairwise accuracy then
validation macro NDCG@10 then larger lambda, refits once on
train+validation, and writes the selected candidate model plus a selection
summary. The test split is never read here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from beatscope import event_ranker as er  # noqa: E402


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


def song_feature_map(song: dict, ablation: str = "full") -> dict[int, np.ndarray]:
    indices = er.ablation_indices(ablation)
    feature_map: dict[int, np.ndarray] = {}
    for onset_id, event_line in song["events"].items():
        groups = [event_line["group"]] if event_line.get("group") is not None else []
        vector = er.extract_features(event_line["evidence"], groups, event_line["strength"])
        feature_map[int(onset_id)] = np.array(vector, dtype=np.float64)[indices]
    return feature_map


def pair_vectors(song: dict, feature_map: dict[int, np.ndarray]) -> list[tuple[np.ndarray, np.ndarray]]:
    vectors = []
    for pair in song["pairs"]:
        vectors.append((
            feature_map[pair["preferred_onset_id"]],
            feature_map[pair["other_onset_id"]],
        ))
    return vectors


def macro_pairwise(weights: np.ndarray, normalization: dict, songs: dict) -> dict[str, float]:
    per_song = {}
    for sha, song in songs.items():
        if not song["pairs"] or song["meta"] is None:
            continue
        feature_map = song_feature_map(song)
        per_song[sha] = er._song_pair_accuracy(weights, normalization, feature_map, song["pairs"])
    return per_song


def macro_ndcg(weights: np.ndarray, normalization: dict, songs: dict) -> dict[str, float]:
    per_song = {}
    for sha, song in songs.items():
        if song["meta"] is None:
            continue
        feature_map = song_feature_map(song)
        support = {int(onset_id): float(line["support_rate"])
                   for onset_id, line in song["events"].items()}
        scores = {
            int(onset_id): float(((vector - np.array(normalization["center"]))
                                  / np.array(normalization["scale"])) @ weights)
            for onset_id, vector in feature_map.items()
        }
        per_song[sha] = er._song_ndcg_at_10(scores, support)
    return per_song


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="built dataset.jsonl")
    parser.add_argument("--manifest", type=Path, required=True,
                        help="training-manifest.json for provenance hashing")
    parser.add_argument("--output", type=Path, required=True, help="candidates output directory")
    args = parser.parse_args(argv)

    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    dataset_bytes = args.dataset.read_bytes()
    if manifest.get("schema") != er.MANIFEST_SCHEMA \
            or manifest.get("dataset_schema") != er.DATASET_SCHEMA \
            or manifest.get("dataset_sha256") != hashlib.sha256(dataset_bytes).hexdigest():
        print("dataset/manifest provenance mismatch", file=sys.stderr)
        return 2
    lines = load_dataset(args.dataset)
    songs = group_by_song(lines)
    train_songs = {sha: song for sha, song in songs.items() if song["meta"]["split"] == "train"}
    validation_songs = {sha: song for sha, song in songs.items() if song["meta"]["split"] == "validation"}
    if not train_songs or not validation_songs:
        print("dataset must contain non-empty train and validation splits", file=sys.stderr)
        return 1

    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

    train_matrix = np.vstack([
        vector for song in train_songs.values() for vector in song_feature_map(song).values()
    ])
    train_normalization = er.fit_normalization(train_matrix)

    candidates = []
    for lam in er.LAMBDA_CANDIDATES:
        train_pairs = []
        for song in train_songs.values():
            feature_map = song_feature_map(song)
            train_pairs.extend(pair_vectors(song, feature_map))
        try:
            weights, normalization, iterations = er.train_pair_weights(
                train_pairs, lam, train_normalization)
        except er.RankerError as error:
            print(f"lambda {lam}: {error}", file=sys.stderr)
            return 1
        val_accuracy = er.macro_metric(macro_pairwise(weights, normalization, validation_songs))
        val_ndcg = er.macro_metric(macro_ndcg(weights, normalization, validation_songs))
        candidates.append({
            "lambda": lam,
            "weights": weights,
            "normalization": normalization,
            "iterations": iterations,
            "validation_pairwise_accuracy": val_accuracy,
            "validation_ndcg_at_10": val_ndcg,
        })

    # Selection order: validation pairwise accuracy, then validation NDCG@10,
    # then larger lambda (plan section 14.4).
    selected = max(candidates, key=lambda item: (
        -1.0 if math_isnan(item["validation_pairwise_accuracy"]) else item["validation_pairwise_accuracy"],
        -1.0 if math_isnan(item["validation_ndcg_at_10"]) else item["validation_ndcg_at_10"],
        item["lambda"],
    ))

    # Refit once on train+validation with the selected lambda.
    combined_songs = list(train_songs.values()) + list(validation_songs.values())
    combined_pairs = []
    combined_vectors = []
    for song in combined_songs:
        feature_map = song_feature_map(song)
        combined_vectors.extend(feature_map.values())
        combined_pairs.extend(pair_vectors(song, feature_map))
    combined_normalization = er.fit_normalization(np.vstack(combined_vectors))
    weights, normalization, iterations = er.train_pair_weights(
        combined_pairs, selected["lambda"], combined_normalization)

    args.output.mkdir(parents=True, exist_ok=True)
    for candidate in candidates:
        candidate_model = er.build_model_json(
            candidate["weights"], candidate["normalization"], lam=candidate["lambda"],
            iterations=candidate["iterations"], train_song_count=len(train_songs),
            validation_song_count=len(validation_songs),
            preference_pair_count=len(combined_pairs), dataset_manifest_sha256=manifest_sha,
            evaluation_report_sha256="", status="pending")
        (args.output / f"lambda-{candidate['lambda']}.json").write_bytes(
            er.canonical_model_bytes(candidate_model))
    selected_model = er.build_model_json(
        weights, normalization, lam=selected["lambda"], iterations=iterations,
        train_song_count=len(train_songs), validation_song_count=len(validation_songs),
        preference_pair_count=len(combined_pairs), dataset_manifest_sha256=manifest_sha,
        evaluation_report_sha256="", status="pending")
    (args.output / "selected.json").write_bytes(er.canonical_model_bytes(selected_model))
    summary = {
        "candidates": [
            {key: value for key, value in candidate.items() if key not in ("weights", "normalization")}
            for candidate in candidates
        ],
        "selected_lambda": selected["lambda"],
        "train_song_count": len(train_songs),
        "validation_song_count": len(validation_songs),
        "preference_pair_count": len(combined_pairs),
        "dataset_manifest_sha256": manifest_sha,
    }
    (args.output / "selection-summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"selected_lambda": selected["lambda"],
                      "validation_pairwise_accuracy": selected["validation_pairwise_accuracy"],
                      "validation_ndcg_at_10": selected["validation_ndcg_at_10"]}, indent=2))
    return 0


def math_isnan(value: float) -> bool:
    return isinstance(value, float) and value != value


if __name__ == "__main__":
    raise SystemExit(main())
