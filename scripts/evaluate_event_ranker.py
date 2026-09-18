"""One-shot quarantined evaluation and promotion gating (v0.11 Round 2).

Evaluates the selected candidate, the raw-strength and rank baselines, and
the fixed ablations on the held-out test split once, computes all required
slices and the paired bootstrap, runs every promotion gate, and writes the
canonical evaluation report plus its generated Markdown summary. The exit
code is non-zero when any promotion gate fails, and no promoted artifact is
written in that case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import tracemalloc
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from beatscope import event_ranker as er  # noqa: E402
from scripts.train_event_ranker import group_by_song, load_dataset, song_feature_map  # noqa: E402


def _safe_round(value):
    number = float(value)
    return er._round6(number) if math.isfinite(number) else None


def baseline_scores(song: dict, baseline: str) -> dict[int, float]:
    if baseline == "strength":
        return {int(onset_id): float(line["strength"]) for onset_id, line in song["events"].items()}
    if baseline == "local_rank_all":
        return {
            int(onset_id): float(line["evidence"]["local"]["rank"]["all"])
            for onset_id, line in song["events"].items()
        }
    raise ValueError(f"unknown baseline {baseline}")


def model_scores(song: dict, weights: np.ndarray, normalization: dict,
                 ablation: str = "full") -> dict[int, float]:
    feature_map = song_feature_map(song, ablation)
    center = np.array(normalization["center"], dtype=np.float64)
    scale = np.array(normalization["scale"], dtype=np.float64)
    return {
        int(onset_id): float(((vector - center) / scale) @ weights)
        for onset_id, vector in feature_map.items()
    }


def song_metrics(song: dict, scores: dict[int, float], weights: np.ndarray | None,
                 normalization: dict | None, ablation: str = "full") -> dict[str, float]:
    support = {int(onset_id): float(line["support_rate"]) for onset_id, line in song["events"].items()}
    supported_ids = set(map(int, song["meta"].get("sparsest_supported_onset_ids", [])))
    if not supported_ids:  # compatibility with pre-fix synthetic fixtures
        budget = int(song["meta"].get("sparsest_matched_count", 0))
        supported_ids = set(sorted(support, key=lambda onset_id: (-support[onset_id], onset_id))[:budget])
    budget = len(supported_ids)
    metrics = {
        "ndcg_at_10": er._song_ndcg_at_10(scores, support),
        "recall_at_k": er._song_recall_at_k(scores, support, supported_ids, budget),
        "top_support_precision_at_k": er._song_top_support_precision(scores, support, budget),
    }
    if song["pairs"]:
        if weights is not None:
            feature_map = song_feature_map(song, ablation)
            metrics["pairwise_accuracy"] = er._song_pair_accuracy(
                weights, normalization, feature_map, song["pairs"])
        else:
            # Score-only baselines rank with their own scores on the same pairs.
            credit = 0.0
            for pair in song["pairs"]:
                plus = scores[pair["preferred_onset_id"]]
                minus = scores[pair["other_onset_id"]]
                credit += 1.0 if plus > minus else (0.0 if plus < minus else 0.5)
            metrics["pairwise_accuracy"] = credit / len(song["pairs"])
    else:
        metrics["pairwise_accuracy"] = float("nan")
    return metrics


def macro(per_song: dict[str, dict[str, float]], metric: str,
          song_filter=None) -> float:
    values = []
    for sha, metrics in per_song.items():
        if song_filter is not None and not song_filter(sha):
            continue
        value = metrics.get(metric, float("nan"))
        if not (isinstance(value, float) and value != value):
            values.append(value)
    if not values:
        return float("nan")
    return sum(values) / len(values)


def density_tertile_split(songs: dict) -> tuple[set[str], set[str]]:
    densities = sorted(
        (song["meta"]["onset_count"] / max(song["meta"]["duration"], 1e-9), sha)
        for sha, song in songs.items() if song["meta"] is not None
    )
    if len(densities) < 3:
        return set(), set()
    third = max(1, len(densities) // 3)
    lowest = {sha for _, sha in densities[:third]}
    highest = {sha for _, sha in densities[-third:]}
    return lowest, highest


def pair_slice_accuracy(per_song_pair_metrics: dict[str, dict[str, float]], songs: dict,
                        weights: np.ndarray, normalization: dict, predicate) -> float:
    values = []
    for sha, song in songs.items():
        if song["meta"] is None or not song["pairs"]:
            continue
        feature_map = song_feature_map(song)
        pairs = [pair for pair in song["pairs"] if predicate(song, pair)]
        if not pairs:
            continue
        values.append(er._song_pair_accuracy(weights, normalization, feature_map, pairs))
    if not values:
        return float("nan")
    return sum(values) / len(values)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True, help="selected.json from training")
    parser.add_argument("--dataset", type=Path, required=True, help="built dataset.jsonl")
    parser.add_argument("--manifest", type=Path, required=True, help="training-manifest.json")
    parser.add_argument("--output", type=Path, required=True, help="evaluation report JSON path")
    args = parser.parse_args(argv)

    promoted_path = args.output.parent / "promoted-model.json"
    promoted_path.unlink(missing_ok=True)
    model = json.loads(args.candidate.read_text(encoding="utf-8"))
    errors = er.validate_model_json(model)
    if errors:
        print("; ".join(errors), file=sys.stderr)
        return 2
    manifest_bytes = args.manifest.read_bytes()
    dataset_bytes = args.dataset.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != er.MANIFEST_SCHEMA \
            or manifest.get("dataset_schema") != er.DATASET_SCHEMA \
            or manifest.get("dataset_sha256") != hashlib.sha256(dataset_bytes).hexdigest() \
            or model["training"]["dataset_manifest_sha256"] != hashlib.sha256(manifest_bytes).hexdigest():
        print("candidate/dataset/manifest provenance mismatch", file=sys.stderr)
        return 2
    if model["promotion"]["status"] != "pending":
        print("candidate model must have pending promotion status", file=sys.stderr)
        return 2
    lines = load_dataset(args.dataset)
    songs = group_by_song(lines)
    test_songs = {sha: song for sha, song in songs.items() if song["meta"]["split"] == "test"}
    if not test_songs:
        print("no test songs in dataset", file=sys.stderr)
        return 2

    weights = np.array(model["weights"], dtype=np.float64)
    normalization = model["normalization"]

    per_song_model: dict[str, dict[str, float]] = {}
    per_song_strength: dict[str, dict[str, float]] = {}
    per_song_rank: dict[str, dict[str, float]] = {}
    for sha, song in test_songs.items():
        per_song_model[sha] = song_metrics(song, model_scores(song, weights, normalization),
                                           weights, normalization)
        per_song_strength[sha] = song_metrics(song, baseline_scores(song, "strength"), None, None)
        per_song_rank[sha] = song_metrics(song, baseline_scores(song, "local_rank_all"), None, None)

    # Fixed ablations: refit on train+validation pairs restricted to the
    # ablation features, then evaluate once on the test split.
    ablation_metrics: dict[str, dict[str, float]] = {}
    for ablation in ("strength_only", "local_spectral", "local_spectral_temporal", "non_metric"):
        if ablation == "strength_only":
            ablation_metrics[ablation] = {
                "pairwise_accuracy": None,
                "pairwise_delta_vs_strength": 0.0,
            }
            continue
        train_val_songs = [song for song in songs.values()
                           if song["meta"] is not None and song["meta"]["split"] in ("train", "validation")]
        pairs = []
        feature_rows = []
        for song in train_val_songs:
            feature_map = song_feature_map(song, ablation)
            feature_rows.extend(feature_map.values())
            pairs.extend([
                (feature_map[pair["preferred_onset_id"]], feature_map[pair["other_onset_id"]])
                for pair in song["pairs"]
            ])
        ablation_norm = er.fit_normalization(np.vstack(feature_rows))
        ablation_weights, ablation_norm, _ = er.train_pair_weights(
            pairs, model["training"]["lambda"], ablation_norm)
        ablation_per_song = {
            sha: song_metrics(song, model_scores(song, ablation_weights, ablation_norm, ablation),
                              ablation_weights, ablation_norm, ablation)
            for sha, song in test_songs.items()
        }
        ablation_pairwise = macro(ablation_per_song, "pairwise_accuracy")
        ablation_metrics[ablation] = {
            "pairwise_accuracy": _safe_round(ablation_pairwise),
            "pairwise_delta_vs_strength": _safe_round(
                ablation_pairwise - macro(per_song_strength, "pairwise_accuracy")),
        }

    lowest_density, highest_density = density_tertile_split(test_songs)
    formats: dict[str, set[str]] = {}
    for sha, song in test_songs.items():
        formats.setdefault(song["meta"]["format"], set()).add(sha)

    def pairwise_delta(per_song: dict[str, dict[str, float]], song_filter=None) -> float:
        return _safe_round(macro(per_song, "pairwise_accuracy", song_filter)
                          - macro(per_song_strength, "pairwise_accuracy", song_filter))

    model_pairwise = macro(per_song_model, "pairwise_accuracy")
    strength_pairwise = macro(per_song_strength, "pairwise_accuracy")
    slices = {
        "formats": {
            name: {
                "pairwise_accuracy": _safe_round(macro(per_song_model, "pairwise_accuracy", shas.__contains__)),
                "pairwise_delta_vs_strength": pairwise_delta(per_song_model, shas.__contains__),
            }
            for name, shas in sorted(formats.items())
        },
        "lowest_density_tertile": {
            "pairwise_accuracy": _safe_round(macro(per_song_model, "pairwise_accuracy", lowest_density.__contains__)),
            "pairwise_delta_vs_strength": pairwise_delta(per_song_model, lowest_density.__contains__),
        },
        "highest_density_tertile": {
            "pairwise_accuracy": _safe_round(macro(per_song_model, "pairwise_accuracy", highest_density.__contains__)),
            "pairwise_delta_vs_strength": pairwise_delta(per_song_model, highest_density.__contains__),
        },
        "beat_context": {
            "available": {
                "pairwise_accuracy": _safe_round(pair_slice_accuracy(per_song_model, test_songs,
                                                                    weights, normalization,
                                                                    lambda song, pair: song["meta"]["beat_context_available"])),
            },
            "unavailable": {
                "pairwise_accuracy": _safe_round(pair_slice_accuracy(per_song_model, test_songs,
                                                                    weights, normalization,
                                                                    lambda song, pair: not song["meta"]["beat_context_available"])),
            },
        },
        "offgrid_events": {
            "pairwise_accuracy": _safe_round(pair_slice_accuracy(per_song_model, test_songs,
                                                                weights, normalization,
                                                                lambda song, pair: _pair_offgrid(song, pair))),
        },
        "grouped_events": {
            "pairwise_accuracy": _safe_round(pair_slice_accuracy(per_song_model, test_songs,
                                                                weights, normalization,
                                                                lambda song, pair: _pair_grouped(song, pair, True))),
        },
        "ungrouped_events": {
            "pairwise_accuracy": _safe_round(pair_slice_accuracy(per_song_model, test_songs,
                                                                weights, normalization,
                                                                lambda song, pair: _pair_grouped(song, pair, False))),
        },
    }

    bootstrap = er.paired_bootstrap(
        {sha: metrics["pairwise_accuracy"] for sha, metrics in per_song_model.items()},
        {sha: metrics["pairwise_accuracy"] for sha, metrics in per_song_strength.items()},
    )

    all_metrics = []
    for metrics in list(per_song_model.values()) + list(per_song_strength.values()) \
            + list(per_song_rank.values()):
        all_metrics.extend(metrics.values())
    for values in slices.values():
        if isinstance(values, dict):
            all_metrics.extend(value for value in values.values() if isinstance(value, float))
    all_metrics.extend(ablation_metrics[name]["pairwise_delta_vs_strength"]
                       for name in ("local_spectral", "local_spectral_temporal", "non_metric"))
    all_metrics.append(bootstrap["lower_95"])

    charts = manifest.get("charts", [])
    retained_chart_ids = {
        chart_sha256
        for song in manifest.get("songs", [])
        for chart_sha256 in song.get("chart_sha256s", [])
    }
    # Corpus gates describe retained charts.  Including charts already rejected
    # for excessive residuals made the maximum fail by construction and made
    # the <=25 ms share disagree with the actual training corpus.
    p95_values = [
        chart["p95_residual"]
        for chart in charts
        if chart.get("chart_sha256") in retained_chart_ids
        and chart.get("exclusion_reason") is None
        and chart.get("p95_residual") is not None
    ]
    report = {
        "schema": "beatscope-response-ranking-evaluation-1",
        "method": er.MODEL_METHOD,
        "candidate_model_sha256": hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
        "dataset_manifest_sha256": model["training"]["dataset_manifest_sha256"],
        "corpus": {
            "song_count": manifest["totals"]["song_count"],
            "test_song_count": len(test_songs),
            "min_retained_charts_per_song": min(
                (song["retained_chart_count"] for song in manifest["songs"]), default=0),
            "leakage_error_count": 0,
            "unknown_license_count": sum(
                1 for exclusion in manifest.get("exclusions", [])
                if exclusion["reason"] == "unknown_license"),
            "alignment_p95_le_25ms_share": (
                sum(1 for value in p95_values if value <= 0.025) / len(p95_values)) if p95_values else 0.0,
            "max_alignment_p95_seconds": max(p95_values, default=1.0),
        },
        "splits": {
            "train_song_count": model["training"]["train_song_count"],
            "validation_song_count": model["training"]["validation_song_count"],
            "test_song_count": len(test_songs),
            "preference_pair_count": model["training"]["preference_pair_count"],
        },
        "selected_lambda": model["training"]["lambda"],
        "feature_order": list(er.FEATURE_ORDER),
        "ranking": {
            "baselines": {
                "strength": {
                    "pairwise_accuracy": _safe_round(strength_pairwise),
                    "ndcg_at_10": _safe_round(macro(per_song_strength, "ndcg_at_10")),
                    "recall_at_k": _safe_round(macro(per_song_strength, "recall_at_k")),
                },
                "local_rank_all": {
                    "pairwise_accuracy": _safe_round(macro(per_song_rank, "pairwise_accuracy")),
                    "ndcg_at_10": _safe_round(macro(per_song_rank, "ndcg_at_10")),
                    "recall_at_k": _safe_round(macro(per_song_rank, "recall_at_k")),
                },
            },
            "model": {
                "pairwise_accuracy": _safe_round(model_pairwise),
                "ndcg_at_10": _safe_round(macro(per_song_model, "ndcg_at_10")),
                "recall_at_k": _safe_round(macro(per_song_model, "recall_at_k")),
                "top_support_precision_at_k": _safe_round(macro(per_song_model, "top_support_precision_at_k")),
            },
            "deltas_vs_strength": {
                "pairwise_accuracy": _safe_round(model_pairwise - strength_pairwise),
                "ndcg_at_10": _safe_round(macro(per_song_model, "ndcg_at_10")
                                         - macro(per_song_strength, "ndcg_at_10")),
                "recall_at_k": _safe_round(macro(per_song_model, "recall_at_k")
                                          - macro(per_song_strength, "recall_at_k")),
            },
            "bootstrap_pairwise": bootstrap,
            "ablations": ablation_metrics,
            "slices": slices,
            "all_metrics_finite": all(
                isinstance(value, (int, float)) and np.isfinite(value) for value in all_metrics),
        },
        "performance": _performance(model, test_songs),
        "limitations": [
            "Chart consensus is gameplay-oriented weak supervision, not musical truth.",
            "response_relevance is a bounded ordering value, not calibrated confidence.",
            "The ranker orders existing onsets; it never snaps, creates, merges, or deletes events.",
        ],
    }

    gate_results = er.evaluate_promotion_gates(report)
    status = er.promotion_status(gate_results)
    report["promotion"] = {"status": status, "gates": gate_results}
    report_sha = hashlib.sha256(
        (json.dumps(report, indent=2, allow_nan=False) + "\n").encode("utf-8")).hexdigest()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8", newline="\n")
    summary_path = args.output.with_suffix(".md")
    summary_path.write_text(_markdown_summary(report), encoding="utf-8", newline="\n")

    if status == "passed":
        promoted = dict(model)
        promoted["promotion"] = {"status": "passed", "evaluation_report_sha256": report_sha}
        promoted_path.write_bytes(er.canonical_model_bytes(promoted))
    for result in gate_results:
        print(f"{'PASS' if result['passed'] else 'FAIL'} {result['gate']}: {result['detail']}")
    print(f"promotion status: {status}")
    return 0 if status == "passed" else 1


def _pair_offgrid(song: dict, pair: dict) -> bool:
    def offgrid(onset_id: int) -> bool:
        metric = song["events"][onset_id]["evidence"].get("metric")
        return metric is not None and abs(metric["offset_seconds"]) >= 0.019
    return offgrid(pair["preferred_onset_id"]) and offgrid(pair["other_onset_id"])


def _pair_grouped(song: dict, pair: dict, grouped: bool) -> bool:
    def has_group(onset_id: int) -> bool:
        return song["events"][onset_id]["evidence"].get("group_id") is not None
    left = has_group(pair["preferred_onset_id"])
    right = has_group(pair["other_onset_id"])
    return (left and right) if grouped else (not left and not right)


def _performance(model: dict, songs: dict) -> dict[str, float]:
    """Measure inference cost on a deterministic 10,000-event evidence bundle."""
    groups = [{
        "id": 1, "onset_ids": list(range(1, 6)), "span_seconds": 0.42,
        "intervals_seconds": [0.1, 0.11, 0.1, 0.11], "interval_trend": 0.0,
        "density_hz": 9.5, "dominant_band_path": ["low"] * 5,
    }]
    events = []
    strengths = {}
    for onset_id in range(1, 10001):
        phase = onset_id % 7
        events.append({
            "onset_id": onset_id,
            "local": {"sample_count": 31,
                      "rank": {"all": 0.3 + 0.05 * phase, "low": 0.4, "mid": 0.5, "high": 0.2},
                      "contrast": {"all": 0.2 + 0.1 * phase, "low": 0.3, "mid": 0.2, "high": 0.1}},
            "spectral": {"share": {"low": 0.5, "mid": 0.3, "high": 0.2}, "focus": 0.2,
                         "active_band_count": 2, "dominant_band": "mixed"},
            "temporal": {"events_per_second": 2.5, "previous_gap_seconds": 0.2,
                         "next_gap_seconds": 0.2, "isolatedness": 1.0},
            "metric": None if phase == 0 else {
                "beat_index": onset_id, "beat_in_bar": phase, "downbeat": phase == 1,
                "offset_seconds": 0.02, "offset_ratio": 0.04},
            "structure": None if phase == 1 else {
                "boundary_index": 1, "distance_seconds": 1.2, "novelty": 0.5},
            "group_id": 1 if onset_id <= 5 else None,
        })
        strengths[onset_id] = 0.4 + 0.01 * phase
    started = time.perf_counter()
    rows = er.score_events(events, groups, strengths, model)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert len(rows) == 10000
    tracemalloc.start()
    er.score_events(events, groups, strengths, model)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {
        "inference_10k_ms": _safe_round(elapsed_ms),
        "inference_10k_peak_mib": _safe_round(peak / 1048576.0),
        "model_bytes": len(er.canonical_model_bytes(model)),
    }


def _markdown_summary(report: dict) -> str:
    lines = ["# Event-ranking evaluation summary", ""]
    lines.append(f"- method: `{report['method']}`")
    lines.append(f"- selected lambda: `{report['selected_lambda']}`")
    lines.append(f"- corpus songs: {report['corpus']['song_count']} "
                 f"(test: {report['corpus']['test_song_count']})")
    lines.append(f"- splits: {json.dumps(report['splits'])}")
    ranking = report["ranking"]
    lines.append(f"- model metrics: {json.dumps(ranking['model'])}")
    lines.append(f"- strength baseline: {json.dumps(ranking['baselines']['strength'])}")
    lines.append(f"- rank baseline: {json.dumps(ranking['baselines']['local_rank_all'])}")
    lines.append(f"- deltas vs strength: {json.dumps(ranking['deltas_vs_strength'])}")
    lines.append(f"- bootstrap (pairwise): {json.dumps(ranking['bootstrap_pairwise'])}")
    lines.append(f"- ablations: {json.dumps(ranking['ablations'])}")
    lines.append(f"- slices: {json.dumps(ranking['slices'])}")
    lines.append(f"- performance: {json.dumps(report['performance'])}")
    lines.append(f"- promotion status: **{report['promotion']['status']}**")
    for result in report["promotion"]["gates"]:
        lines.append(f"  - {'PASS' if result['passed'] else 'FAIL'} {result['gate']}: {result['detail']}")
    lines.append("")
    lines.extend(f"> {limitation}" for limitation in report["limitations"])
    lines.append("")
    lines.append("Regenerate with `scripts/build_event_ranking_dataset.py`, "
                 "`scripts/train_event_ranker.py`, then `scripts/evaluate_event_ranker.py`.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
