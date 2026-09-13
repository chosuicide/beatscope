"""One-shot R2-D evaluation of the frozen cross-source response ranker."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import socket
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beatscope import event_ranker as er  # noqa: E402
from beatscope import event_ranker_boost as boost  # noqa: E402
from scripts.train_event_ranker_v3 import (  # noqa: E402
    group_by_song,
    pair_row_indices,
    song_ndcg_at_10,
    song_pair_accuracy,
    song_recall_at_k,
    view_matrix,
)

EVALUATION_CONTRACT = "beatscope-sealed-ranking-evaluation-v5"
BOOTSTRAP_SEED_V5 = 20260908
LOCK_SCHEMA = "beatscope-sealed-cross-source-candidate-lock-1"
REPORT_SCHEMA = "beatscope-response-ranking-evaluation-3"
MAX_ALIGNMENT_P95_SECONDS = 0.025


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def create_receipt(path: Path, payload: dict) -> None:
    """Atomically consume an evaluation attempt; there is intentionally no reset."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("evaluation_already_consumed") from exc
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_bytes(payload))
        stream.flush()
        os.fsync(stream.fileno())


def validate_lock(lock: object) -> list[str]:
    """Reject incomplete or surprising locks before consuming the holdout."""
    if not isinstance(lock, dict):
        return ["candidate lock must be an object"]
    required = {
        "schema", "method", "selection_policy", "candidate_sha256", "non_metric_candidate_sha256",
        "selection_report_sha256", "development_dataset_sha256",
        "development_manifest_sha256", "development_source_ids",
        "evaluation_dataset_sha256", "evaluation_manifest_sha256", "holdout",
        "timeline_audit",
    }
    errors = []
    if set(lock) != required:
        errors.append("candidate lock must hold exactly the frozen fields")
    if lock.get("schema") != LOCK_SCHEMA:
        errors.append(f"candidate lock schema must be {LOCK_SCHEMA!r}")
    if lock.get("method") != boost.MODEL_METHOD_V4:
        errors.append("candidate lock method mismatch")
    if lock.get("selection_policy") != "top-k-utility-with-pairwise-and-source-safety":
        errors.append("candidate lock selection policy mismatch")
    digest_fields = required - {"schema", "method", "selection_policy", "development_source_ids",
                                "holdout", "timeline_audit"}
    for name in sorted(digest_fields):
        value = lock.get(name)
        if not isinstance(value, str) or len(value) != 64 \
                or any(char not in "0123456789abcdef" for char in value):
            errors.append(f"{name} must be a lowercase SHA-256")
    sources = lock.get("development_source_ids")
    if not isinstance(sources, list) or not sources or sources != sorted(set(sources)):
        errors.append("development_source_ids must be a sorted unique non-empty list")
    holdout = lock.get("holdout")
    holdout_fields = {"source_id", "source_revision", "license",
                      "retained_song_count", "retained_chart_count",
                      "excluded_development_overlap_count", "excluded_audio_sha256s"}
    if not isinstance(holdout, dict) or set(holdout) != holdout_fields:
        errors.append("holdout lock must hold exactly the frozen provenance fields")
    elif (not isinstance(holdout["excluded_audio_sha256s"], list)
          or holdout["excluded_audio_sha256s"] != sorted(set(holdout["excluded_audio_sha256s"]))):
        errors.append("excluded_audio_sha256s must be a sorted unique list")
    timeline = lock.get("timeline_audit")
    timeline_fields = {"development_count", "holdout_count", "overlap_count",
                       "development_set_sha256", "holdout_set_sha256"}
    if not isinstance(timeline, dict) or set(timeline) != timeline_fields:
        errors.append("timeline audit must hold exactly the frozen fields")
    elif (timeline["development_count"] <= 0 or timeline["holdout_count"] <= 0
          or timeline["overlap_count"] != 0):
        errors.append("timeline audit must prove two non-empty disjoint sets")
    return errors


def cross_corpus_leakage_errors(development: dict, holdout: dict) -> list[str]:
    """Compare every frozen identity class before a receipt consumes the holdout."""
    errors = []
    for field in ("audio_sha256", "fingerprint"):
        left = {str(song.get(field)) for song in development.get("songs", []) if song.get(field)}
        right = {str(song.get(field)) for song in holdout.get("songs", []) if song.get(field)}
        if left & right:
            errors.append(f"cross_corpus_{field}")
    left_charts = {digest for song in development.get("songs", [])
                   for digest in song.get("chart_sha256s", [])}
    right_charts = {digest for song in holdout.get("songs", [])
                    for digest in song.get("chart_sha256s", [])}
    if left_charts & right_charts:
        errors.append("cross_corpus_chart_sha256")
    left_timelines = {str(chart.get("timeline_sha256")) for chart in development.get("charts", [])
                      if chart.get("timeline_sha256")}
    right_timelines = {str(chart.get("timeline_sha256")) for chart in holdout.get("charts", [])
                       if chart.get("timeline_sha256")}
    if left_timelines & right_timelines:
        errors.append("cross_corpus_timeline_sha256")
    return errors


def leakage_errors(manifest: dict) -> list[str]:
    """Recheck manifest-visible identities across development and test partitions."""
    errors = []
    for field in ("audio_sha256", "fingerprint"):
        owners: dict[str, set[str]] = {}
        for song in manifest.get("songs", []):
            owners.setdefault(str(song.get(field)), set()).add(str(song.get("split")))
        if any(len(partitions) > 1 for partitions in owners.values()):
            errors.append(f"cross_partition_{field}")
    chart_owners: dict[str, set[str]] = {}
    for song in manifest.get("songs", []):
        for digest in song.get("chart_sha256s", []):
            chart_owners.setdefault(digest, set()).add(str(song.get("split")))
    if any(len(partitions) > 1 for partitions in chart_owners.values()):
        errors.append("cross_partition_chart_sha256")
    return errors


def score_song(song: dict, model: dict) -> tuple[dict[int, float], list[int], np.ndarray]:
    matrix, ordered_ids, _ = view_matrix(song, model["feature_view"])
    anchor = model["anchor"]
    values = boost.boost_score(
        matrix, model["trees"], model["base_value"], model["learning_rate"],
        anchor["feature_index"], anchor["weight"],
    )
    return {onset_id: float(values[row]) for row, onset_id in enumerate(ordered_ids)}, ordered_ids, matrix


def metric_bundle(song: dict, scores: dict[int, float], ordered_ids: list[int]) -> dict[str, float]:
    rows = pair_row_indices(song, {onset_id: row for row, onset_id in enumerate(ordered_ids)})
    score_array = np.array([scores[onset_id] for onset_id in ordered_ids], dtype=np.float64)
    strength_array = np.array([song["events"][onset_id]["strength"] for onset_id in ordered_ids])
    support = {int(onset_id): float(line["support_rate"])
               for onset_id, line in song["events"].items()}
    supported = set(map(int, song["meta"].get("sparsest_supported_onset_ids", [])))
    budget = len(supported) or int(song["meta"].get("sparsest_matched_count", 0))
    if not supported:
        supported = set(sorted(support, key=lambda key: (-support[key], key))[:budget])
    return {
        "pairwise_accuracy": song_pair_accuracy(score_array, rows, strength_array),
        "ndcg_at_10": song_ndcg_at_10(score_array, ordered_ids, support),
        "recall_at_k": song_recall_at_k(score_array, ordered_ids, support, supported, budget),
        "top_support_precision_at_k": sum(
            support[ordered_ids[row]] for row in sorted(
                range(len(ordered_ids)), key=lambda row: (-score_array[row], ordered_ids[row]))[:budget]
        ) / budget if budget else float("nan"),
    }


def macro(per_song: dict[str, dict[str, float]], key: str, ids: set[str] | None = None) -> float:
    values = [metrics[key] for sha, metrics in per_song.items()
              if (ids is None or sha in ids) and math.isfinite(metrics[key])]
    return sum(values) / len(values) if values else float("nan")


def rounded(value: float) -> float | None:
    return er._round6(value) if math.isfinite(value) else None


def song_slice(model_metrics: dict, baseline_metrics: dict, ids: set[str]) -> dict:
    model_value = macro(model_metrics, "pairwise_accuracy", ids)
    baseline_value = macro(baseline_metrics, "pairwise_accuracy", ids)
    return {"song_count": len(ids), "pairwise_accuracy": rounded(model_value),
            "pairwise_delta_vs_strength": rounded(model_value - baseline_value)}


def pair_slice(song: dict, model_scores: dict[int, float], predicate) -> tuple[float, float, int]:
    pairs = [pair for pair in song["pairs"] if predicate(song, pair)]
    if not pairs:
        return float("nan"), float("nan"), 0
    model_credit = strength_credit = 0.0
    for pair in pairs:
        preferred, other = pair["preferred_onset_id"], pair["other_onset_id"]
        model_margin = model_scores[preferred] - model_scores[other]
        strength_margin = song["events"][preferred]["strength"] - song["events"][other]["strength"]
        model_credit += 1.0 if model_margin > 0 else (0.0 if model_margin < 0 else 0.5)
        strength_credit += 1.0 if strength_margin > 0 else (0.0 if strength_margin < 0 else 0.5)
    return model_credit / len(pairs), strength_credit / len(pairs), len(pairs)


def pair_slice_report(songs: dict, score_maps: dict, predicate) -> dict:
    model_values, baseline_values = [], []
    count = 0
    for sha, song in songs.items():
        model_value, baseline_value, pair_count = pair_slice(song, score_maps[sha], predicate)
        if pair_count:
            model_values.append(model_value)
            baseline_values.append(baseline_value)
            count += pair_count
    if not model_values:
        return {"pair_count": 0, "song_count": 0, "pairwise_accuracy": None,
                "pairwise_delta_vs_strength": None}
    model_macro = sum(model_values) / len(model_values)
    baseline_macro = sum(baseline_values) / len(baseline_values)
    return {"pair_count": count, "song_count": len(model_values),
            "pairwise_accuracy": rounded(model_macro),
            "pairwise_delta_vs_strength": rounded(model_macro - baseline_macro)}


def _both(song: dict, pair: dict, predicate) -> bool:
    return all(predicate(song["events"][pair[key]])
               for key in ("preferred_onset_id", "other_onset_id"))


def required_slices(songs: dict, score_maps: dict, model_metrics: dict,
                    baseline_metrics: dict) -> dict:
    by_source: dict[str, set[str]] = {}
    by_format: dict[str, set[str]] = {}
    for sha, song in songs.items():
        by_source.setdefault(song["meta"].get("source_id", "unknown"), set()).add(sha)
        by_format.setdefault(song["meta"]["format"], set()).add(sha)
    densities = sorted((song["meta"]["onset_count"] / max(song["meta"]["duration"], 1e-9), sha)
                       for sha, song in songs.items())
    third = max(1, len(densities) // 3)
    low_ids = {sha for _, sha in densities[:third]}
    high_ids = {sha for _, sha in densities[-third:]}
    dominant = lambda band: pair_slice_report(  # noqa: E731
        songs, score_maps,
        lambda song, pair: _both(song, pair, lambda event: event["evidence"]["spectral"]["dominant_band"] == band))
    return {
        "sources": {key: song_slice(model_metrics, baseline_metrics, ids)
                    for key, ids in sorted(by_source.items())},
        "formats": {key: song_slice(model_metrics, baseline_metrics, ids)
                    for key, ids in sorted(by_format.items())},
        "lowest_density_tertile": song_slice(model_metrics, baseline_metrics, low_ids),
        "highest_density_tertile": song_slice(model_metrics, baseline_metrics, high_ids),
        "beat_context": {
            "available": pair_slice_report(songs, score_maps, lambda song, pair: _both(
                song, pair, lambda event: event["evidence"].get("metric") is not None)),
            "unavailable": pair_slice_report(songs, score_maps, lambda song, pair: _both(
                song, pair, lambda event: event["evidence"].get("metric") is None)),
        },
        "offgrid_events": pair_slice_report(songs, score_maps, lambda song, pair: _both(
            song, pair, lambda event: event["evidence"].get("metric") is not None
            and abs(event["evidence"]["metric"]["offset_seconds"]) >= 0.019)),
        "grouped_events": pair_slice_report(songs, score_maps, lambda song, pair: _both(
            song, pair, lambda event: event.get("group") is not None)),
        "ungrouped_events": pair_slice_report(songs, score_maps, lambda song, pair: _both(
            song, pair, lambda event: event.get("group") is None)),
        "spectral_band": {band: dominant(band) for band in ("low", "mid", "high", "mixed")},
        "short_groups_or_fills": pair_slice_report(songs, score_maps, lambda song, pair: _both(
            song, pair, lambda event: event.get("group") is not None
            and len(event["group"].get("onset_ids", [])) <= 8)),
        "isolated_events": pair_slice_report(songs, score_maps, lambda song, pair: _both(
            song, pair, lambda event: event.get("group") is None)),
    }


def evaluate_gates(report: dict) -> list[dict]:
    results = []
    def gate(name, passed, detail):
        results.append({"gate": name, "passed": bool(passed), "detail": detail})
    corpus, ranking, performance = report["corpus"], report["ranking"], report["performance"]
    deltas, slices = ranking["deltas_vs_strength"], ranking["slices"]
    gate("holdout_min_songs", corpus["test_song_count"] >= 12, f"test_songs={corpus['test_song_count']}")
    gate("holdout_min_charts", corpus["test_chart_count"] >= 36, f"test_charts={corpus['test_chart_count']}")
    gate("holdout_min_charts_per_song", corpus["min_test_charts_per_song"] >= 3,
         f"minimum={corpus['min_test_charts_per_song']}")
    gate("holdout_fresh_source", corpus["fresh_source_count"] >= 1,
         f"fresh_sources={corpus['fresh_source_count']}")
    gate("holdout_zero_leakage", corpus["leakage_error_count"] == 0,
         f"errors={corpus['leakage_error_count']}")
    gate("holdout_licenses_known", corpus["unknown_license_count"] == 0,
         f"unknown={corpus['unknown_license_count']}")
    gate("holdout_alignment_residuals",
         corpus["max_alignment_p95_seconds"] is not None
         and corpus["max_alignment_p95_seconds"] <= MAX_ALIGNMENT_P95_SECONDS,
         f"max_p95={corpus['max_alignment_p95_seconds']}")
    gate("pairwise_safety_improvement", deltas["pairwise_accuracy"] is not None
         and deltas["pairwise_accuracy"] >= 0.005, f"delta={deltas['pairwise_accuracy']}")
    gate("bootstrap_lower_bound_positive", ranking["bootstrap_pairwise"]["lower_95"] is not None
         and ranking["bootstrap_pairwise"]["lower_95"] > 0,
         f"lower_95={ranking['bootstrap_pairwise']['lower_95']}")
    gate("ndcg_improvement", deltas["ndcg_at_10"] is not None and deltas["ndcg_at_10"] > 0,
         f"delta={deltas['ndcg_at_10']}")
    gate("sparse_recall_improvement", deltas["recall_at_k"] is not None
         and deltas["recall_at_k"] > 0, f"delta={deltas['recall_at_k']}")
    gate("top_support_precision_improvement", deltas["top_support_precision_at_k"] is not None
         and deltas["top_support_precision_at_k"] > 0,
         f"delta={deltas['top_support_precision_at_k']}")
    gate("dense_tertile_improvement",
         slices["highest_density_tertile"]["pairwise_delta_vs_strength"] > 0,
         f"delta={slices['highest_density_tertile']['pairwise_delta_vs_strength']}")
    gate("non_metric_improvement", ranking["non_metric_delta_vs_strength"] >= 0.005,
         f"delta={ranking['non_metric_delta_vs_strength']}")
    source_values = {key: value["pairwise_delta_vs_strength"] for key, value in slices["sources"].items()}
    gate("source_slices_not_lost", bool(source_values)
         and all(value is not None and value >= 0 for value in source_values.values()),
         f"sources={source_values}")
    format_values = {key: value["pairwise_delta_vs_strength"] for key, value in slices["formats"].items()}
    gate("format_slices_not_lost", bool(format_values)
         and all(value is not None and value >= 0 for value in format_values.values()),
         f"formats={format_values}")
    gate("metrics_finite", ranking["all_required_metrics_finite"],
         f"finite={ranking['all_required_metrics_finite']}")
    gate("inference_budget", performance["inference_10k_ms"] < 250,
         f"milliseconds={performance['inference_10k_ms']}")
    gate("inference_memory_budget", performance["inference_10k_peak_mib"] < 64,
         f"peak_mib={performance['inference_10k_peak_mib']}")
    gate("model_size_budget", performance["model_bytes"] < 65536,
         f"bytes={performance['model_bytes']}")
    gate("cross_process_deterministic_output", performance["cross_process_deterministic_output"],
         f"sha256={performance['output_sha256']}")
    gate("repeated_call_deterministic", performance["repeated_call_deterministic"],
         f"sha256={performance['output_sha256']}")
    gate("input_immutable", performance["input_immutable"], "evidence bytes unchanged")
    gate("runtime_purity", performance["runtime_purity"],
         "scoring completed with filesystem, network, RNG, and clock blocked")
    return results


def _probe_payload(model: dict, event_lines: list[dict]) -> dict:
    return {"model": model, "event_lines": event_lines}


def cross_process_hashes(model: dict, event_lines: list[dict], output_dir: Path) -> list[str]:
    """Score the same 10k rows in two fresh interpreters and return their hashes."""
    probe_code = """
import hashlib, json, sys
from beatscope import event_ranker as er
payload = json.load(open(sys.argv[1], encoding='utf-8'))
events, strengths = [], {}
source_rows = payload['event_lines']
for onset_id in range(1, 10001):
    source = source_rows[(onset_id - 1) % len(source_rows)]
    item = json.loads(json.dumps(source['evidence']))
    item['onset_id'] = onset_id
    item['group_id'] = None
    events.append(item)
    strengths[onset_id] = float(source['strength'])
rows = er.boost_score_rows(events, [], strengths, payload['model'])
raw = json.dumps(rows, separators=(',', ':')).encode()
print(hashlib.sha256(raw).hexdigest())
"""
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="determinism-", dir=output_dir) as temp_name:
        payload_path = Path(temp_name) / "probe.json"
        payload_path.write_bytes(canonical_bytes(_probe_payload(model, event_lines)))
        hashes = []
        for _ in range(2):
            completed = subprocess.run(
                [sys.executable, "-c", probe_code, str(payload_path)],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
            hashes.append(completed.stdout.strip())
    return hashes


def runtime_purity(model: dict, evidence: list[dict], strengths: dict[int, float]) -> bool:
    """Exercise the public scorer while external effects are blocked."""
    blocked = RuntimeError("runtime_side_effect")
    targets = (
        patch("builtins.open", side_effect=blocked),
        patch.object(Path, "open", side_effect=blocked),
        patch("os.open", side_effect=blocked),
        patch.object(socket, "socket", side_effect=blocked),
        patch.object(random, "random", side_effect=blocked),
        patch.object(np.random, "default_rng", side_effect=blocked),
        patch.object(time, "time", side_effect=blocked),
        patch.object(time, "monotonic", side_effect=blocked),
        patch.object(time, "perf_counter", side_effect=blocked),
    )
    try:
        for target in targets:
            target.start()
        er.boost_score_rows(evidence, [], strengths, model)
    except RuntimeError:
        return False
    finally:
        for target in reversed(targets):
            target.stop()
    return True


def performance(model: dict, sample_song: dict, output_dir: Path) -> dict:
    event_lines = [sample_song["events"][key] for key in sorted(sample_song["events"], key=int)]
    evidence, strengths = [], {}
    for onset_id in range(1, 10001):
        source = event_lines[(onset_id - 1) % len(event_lines)]
        item = json.loads(json.dumps(source["evidence"]))
        item["onset_id"] = onset_id
        item["group_id"] = None
        evidence.append(item)
        strengths[onset_id] = float(source["strength"])
    frozen = json.dumps(evidence, sort_keys=True)
    started = time.perf_counter()
    first = er.boost_score_rows(evidence, [], strengths, model)
    elapsed = (time.perf_counter() - started) * 1000
    tracemalloc.start()
    second = er.boost_score_rows(evidence, [], strengths, model)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    first_bytes = json.dumps(first, separators=(",", ":")).encode()
    second_bytes = json.dumps(second, separators=(",", ":")).encode()
    process_hashes = cross_process_hashes(model, event_lines, output_dir)
    return {"inference_10k_ms": rounded(elapsed),
            "inference_10k_peak_mib": rounded(peak / 1048576),
            "model_bytes": len(er.canonical_boost_model_bytes(model)),
            "repeated_call_deterministic": first_bytes == second_bytes,
            "cross_process_deterministic_output": len(set(process_hashes)) == 1
            and process_hashes[0] == sha256(first_bytes),
            "output_sha256": sha256(first_bytes),
            "input_immutable": frozen == json.dumps(evidence, sort_keys=True),
            "runtime_purity": runtime_purity(model, evidence, strengths)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--non-metric-candidate", type=Path, required=True)
    parser.add_argument("--selection-report", type=Path, required=True)
    parser.add_argument("--candidate-lock", type=Path, required=True)
    parser.add_argument("--development-manifest", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    candidate_bytes = args.candidate.read_bytes()
    non_metric_bytes = args.non_metric_candidate.read_bytes()
    selection_report_bytes = args.selection_report.read_bytes()
    development_manifest_bytes = args.development_manifest.read_bytes()
    dataset_bytes = args.dataset.read_bytes()
    manifest_bytes = args.manifest.read_bytes()
    lock = json.loads(args.candidate_lock.read_text(encoding="utf-8"))
    model = json.loads(candidate_bytes)
    non_metric = json.loads(non_metric_bytes)
    errors = (validate_lock(lock) + er.validate_boost_model_json(model)
              + er.validate_boost_model_json(non_metric))
    if errors:
        print("; ".join(errors), file=sys.stderr)
        return 2
    actual = {"candidate_sha256": sha256(candidate_bytes),
              "non_metric_candidate_sha256": sha256(non_metric_bytes),
              "selection_report_sha256": sha256(selection_report_bytes),
              "development_manifest_sha256": sha256(development_manifest_bytes),
              "evaluation_dataset_sha256": sha256(dataset_bytes),
              "evaluation_manifest_sha256": sha256(manifest_bytes)}
    if any(lock.get(key) != value for key, value in actual.items()):
        print("candidate/dataset/manifest lock mismatch", file=sys.stderr)
        return 2
    if (model["training"]["dataset_sha256"] != lock.get("development_dataset_sha256")
            or model["training"]["manifest_sha256"] != lock.get("development_manifest_sha256")
            or non_metric["training"] != model["training"]
            or model["feature_view"] != "full" or non_metric["feature_view"] != "non_metric"
            or model["promotion"]["status"] != "pending"
            or non_metric["promotion"]["status"] != "pending"):
        print("candidate development provenance mismatch", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_bytes)
    development_manifest = json.loads(development_manifest_bytes)
    if (manifest.get("schema") != er.MANIFEST_SCHEMA
            or manifest.get("dataset_schema") != er.DATASET_SCHEMA
            or manifest.get("dataset_sha256") != sha256(dataset_bytes)):
        print("evaluation dataset provenance mismatch", file=sys.stderr)
        return 2
    test_manifest = [song for song in manifest.get("songs", []) if song.get("split") == "test"]
    test_sources = {source for song in test_manifest for source in song.get("source_ids", [])}
    dev_sources = set(lock.get("development_source_ids", []))
    test_chart_count = sum(song.get("retained_chart_count", 0) for song in test_manifest)
    holdout = lock["holdout"]
    source_rows = {source["id"]: source for source in manifest.get("sources", [])}
    fresh_sources = test_sources - dev_sources
    if (len(test_manifest) < 12 or test_chart_count < 36
            or not fresh_sources
            or any(not song.get("license") for song in test_manifest)):
        print("sealed holdout does not meet frozen corpus minimums", file=sys.stderr)
        return 2
    if (fresh_sources != {holdout["source_id"]}
            or holdout["retained_song_count"] != len(test_manifest)
            or holdout["retained_chart_count"] != test_chart_count
            or holdout["source_id"] not in source_rows
            or source_rows[holdout["source_id"]].get("source_revision") != holdout["source_revision"]
            or source_rows[holdout["source_id"]].get("license") != holdout["license"]):
        print("sealed holdout provenance mismatch", file=sys.stderr)
        return 2
    visible_leakage = leakage_errors(manifest) + cross_corpus_leakage_errors(
        development_manifest, manifest)
    if lock["timeline_audit"]["overlap_count"] != 0:
        visible_leakage.append("cross_corpus_timeline_sha256")
    if visible_leakage:
        print("; ".join(visible_leakage), file=sys.stderr)
        return 2
    promoted_path = args.output.parent / "promoted-model.json"
    if promoted_path.exists():
        print("stale promoted-model.json must be removed before evaluation", file=sys.stderr)
        return 2

    attempt_id = sha256((actual["candidate_sha256"] + "\n" + actual["evaluation_dataset_sha256"]
                         + "\n" + actual["evaluation_manifest_sha256"] + "\n"
                         + EVALUATION_CONTRACT).encode())
    receipt = {"schema": "beatscope-evaluation-receipt-1", "attempt_id": attempt_id,
               "evaluation_contract": EVALUATION_CONTRACT, **actual}
    try:
        create_receipt(args.receipt, receipt)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2

    # No test event row is parsed before the receipt exists.
    lines = [json.loads(line) for line in dataset_bytes.decode().splitlines() if line.strip()]
    all_songs = group_by_song(lines)
    songs = {sha: song for sha, song in all_songs.items() if song["meta"]["split"] == "test"}
    score_maps, non_metric_maps, strength_maps = {}, {}, {}
    model_metrics, non_metric_metrics, strength_metrics = {}, {}, {}
    for sha, song in songs.items():
        score_maps[sha], ids, _ = score_song(song, model)
        non_metric_maps[sha], non_ids, _ = score_song(song, non_metric)
        strength_maps[sha] = {onset_id: float(song["events"][onset_id]["strength"])
                              for onset_id in ids}
        model_metrics[sha] = metric_bundle(song, score_maps[sha], ids)
        non_metric_metrics[sha] = metric_bundle(song, non_metric_maps[sha], non_ids)
        strength_metrics[sha] = metric_bundle(song, strength_maps[sha], ids)

    keys = ("pairwise_accuracy", "ndcg_at_10", "recall_at_k", "top_support_precision_at_k")
    model_summary = {key: rounded(macro(model_metrics, key)) for key in keys}
    strength_summary = {key: rounded(macro(strength_metrics, key)) for key in keys}
    deltas = {key: rounded(macro(model_metrics, key) - macro(strength_metrics, key)) for key in keys}
    non_metric_delta = rounded(macro(non_metric_metrics, "pairwise_accuracy")
                               - macro(strength_metrics, "pairwise_accuracy"))
    bootstrap_result = er.paired_bootstrap(
        {sha: value["pairwise_accuracy"] for sha, value in model_metrics.items()},
        {sha: value["pairwise_accuracy"] for sha, value in strength_metrics.items()},
        replicates=10000, seed=BOOTSTRAP_SEED_V5)
    slices = required_slices(songs, score_maps, model_metrics, strength_metrics)
    required = list(model_summary.values()) + list(strength_summary.values()) + list(deltas.values())
    required += [non_metric_delta, bootstrap_result["lower_95"], bootstrap_result["upper_95"]]
    required += [entry["pairwise_delta_vs_strength"] for entry in slices["sources"].values()]
    required += [entry["pairwise_delta_vs_strength"] for entry in slices["formats"].values()]

    retained_ids = {chart for song in test_manifest for chart in song.get("chart_sha256s", [])}
    retained_charts = [chart for chart in manifest.get("charts", [])
                       if chart.get("chart_sha256") in retained_ids and chart.get("exclusion_reason") is None]
    report = {
        "schema": REPORT_SCHEMA,
        "method": boost.MODEL_METHOD_V4,
        "attempt_id": attempt_id,
        "locks": actual,
        "corpus": {"test_song_count": len(test_manifest), "test_chart_count": test_chart_count,
                   "min_test_charts_per_song": min(song["retained_chart_count"] for song in test_manifest),
                   "fresh_source_count": len(test_sources - dev_sources),
                   "test_source_ids": sorted(test_sources),
                   "leakage_error_count": len(visible_leakage),
                   "unknown_license_count": sum(not bool(song.get("license")) for song in test_manifest),
                   "max_alignment_p95_seconds": max(
                       (chart["p95_residual"] for chart in retained_charts), default=None)},
        "ranking": {"model": model_summary, "strength_baseline": strength_summary,
                    "deltas_vs_strength": deltas,
                    "non_metric_delta_vs_strength": non_metric_delta,
                    "bootstrap_pairwise": bootstrap_result, "slices": slices,
                    "all_required_metrics_finite": all(
                        isinstance(value, (int, float)) and math.isfinite(value) for value in required)},
        "performance": performance(model, next(iter(songs.values())), args.output.parent),
        "limitations": ["Chart consensus is gameplay-oriented weak supervision, not musical truth.",
                        "response_relevance is an ordering value, not confidence."]}
    gates = evaluate_gates(report)
    report["promotion"] = {"status": "passed" if all(gate["passed"] for gate in gates) else "rejected",
                           "gates": gates}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(report))
    for gate in gates:
        print(f"{'PASS' if gate['passed'] else 'FAIL'} {gate['gate']}: {gate['detail']}")
    print(f"promotion status: {report['promotion']['status']}")
    if report["promotion"]["status"] == "passed":
        promoted = dict(model)
        promoted["promotion"] = {"status": "passed",
                                 "evaluation_report_sha256": sha256(canonical_bytes(report))}
        (args.output.parent / "promoted-model.json").write_bytes(
            er.canonical_boost_model_bytes(promoted))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
