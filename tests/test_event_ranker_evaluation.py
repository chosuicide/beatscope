"""Evaluation, slice, bootstrap, and promotion-gate tests (v0.11 Round 2).

The synthetic dataset here is fabricated test material: its numbers exercise
the evaluation machinery and gates, and its deliberately tiny corpus is
expected to FAIL the corpus gates, proving that a failed candidate cannot
emit a promoted artifact.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from beatscope import event_ranker as er
from tests.fixtures.event_evidence.generate_event_evidence import REPO_ROOT


def _evidence_event(onset_id: int, contrast_all: float) -> dict:
    return {
        "onset_id": onset_id,
        "local": {"sample_count": 9,
                  "rank": {"all": 0.5, "low": 0.4, "mid": 0.5, "high": 0.6},
                  "contrast": {"all": contrast_all, "low": 0.3, "mid": 0.2, "high": 0.1}},
        "spectral": {"share": {"low": 0.5, "mid": 0.3, "high": 0.2}, "focus": 0.2,
                     "active_band_count": 2, "dominant_band": "low"},
        "temporal": {"events_per_second": 2.5, "previous_gap_seconds": 0.4,
                     "next_gap_seconds": 0.4, "isolatedness": 0.3},
        "metric": {"beat_index": onset_id, "beat_in_bar": 1, "downbeat": True,
                   "offset_seconds": 0.02, "offset_ratio": 0.04},
        "structure": {"boundary_index": 0, "distance_seconds": 1.0, "novelty": 0.5},
        "group_id": None,
    }


def build_synth_dataset(tmp_path: Path) -> tuple[Path, Path]:
    """Six one-minute songs: high-contrast events carry the chart consensus."""
    splits = ["train", "train", "train", "validation", "validation", "test"]
    lines: list[str] = []
    manifest_songs = []
    for song_index in range(6):
        sha = f"{song_index + 1:064x}"
        split = splits[song_index]
        lines.append(json.dumps({
            "kind": "song", "dataset_schema": er.DATASET_SCHEMA, "audio_sha256": sha,
            "split": split, "format": "stepmania", "source_id": "synthetic",
            "onset_count": 12, "duration": 60.0,
            "beat_context_available": True, "structure_context_available": True,
            "sparsest_matched_count": 6, "evidence_schema": er.EVIDENCE_SCHEMA,
            "eligible_chart_count": 3,
        }, separators=(",", ":")))
        pairs = []
        for onset_id in range(1, 13):
            high_support = onset_id <= 6
            contrast = 1.4 if high_support else 0.05
            lines.append(json.dumps({
                "kind": "event", "audio_sha256": sha, "split": split,
                "onset_id": onset_id, "strength": 0.5,
                "support_rate": 1.0 if high_support else 0.0,
                "chart_support_count": 3 if high_support else 0, "eligible_chart_count": 3,
                "evidence": _evidence_event(onset_id, contrast),
            }, separators=(",", ":")))
            if high_support:
                pairs.append((onset_id, onset_id + 6))
        for preferred, other in pairs:
            lines.append(json.dumps({
                "kind": "pair", "audio_sha256": sha, "split": split,
                "preferred_onset_id": preferred, "other_onset_id": other,
                "support_gap": 1.0,
            }, separators=(",", ":")))
        manifest_songs.append({
            "audio_sha256": sha, "split": split, "format": "stepmania",
            "license": "synthetic-original", "fingerprint": sha[:16],
            "retained_chart_count": 3, "chart_sha256s": [], "onset_count": 12,
            "supported_event_count": 6, "preference_pair_count": 6,
        })
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    manifest = {
        "schema": "beatscope-response-ranking-manifest-1",
        "dataset_schema": er.DATASET_SCHEMA,
        "totals": {"song_count": 6, "chart_count": 18, "event_row_count": 72,
                   "event_label_count": 36, "preference_pair_count": 36, "exclusion_count": 0},
        "songs": manifest_songs,
        "charts": [
            {"chart_sha256": f"{index:064x}", "audio_sha256": f"{index % 6 + 1:064x}",
             "format": "stepmania", "difficulty_name": "D", "declared_meter": 4,
             "marker_count": 10, "matched_marker_count": 9, "unmatched_marker_count": 1,
             "matched_cluster_count": 9, "covered_onset_count": 9, "median_residual": 0.004,
             "p95_residual": 0.012, "max_residual": 0.02, "ambiguous_component_count": 0,
             "exclusion_reason": None}
            for index in range(1, 19)
        ],
        "exclusions": [],
    }
    manifest["dataset_sha256"] = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / "training-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return dataset_path, manifest_path


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )


def test_evaluation_runs_once_and_rejects_the_tiny_corpus(tmp_path: Path):
    dataset_path, manifest_path = build_synth_dataset(tmp_path)
    candidates = tmp_path / "candidates"
    trained = _run("train_event_ranker.py", "--dataset", str(dataset_path),
                   "--manifest", str(manifest_path), "--output", str(candidates))
    assert trained.returncode == 0, trained.stderr
    report_path = tmp_path / "evaluation-report.json"
    (report_path.parent / "promoted-model.json").write_text("stale", encoding="utf-8")
    evaluated = _run("evaluate_event_ranker.py", "--candidate", str(candidates / "selected.json"),
                     "--dataset", str(dataset_path), "--manifest", str(manifest_path),
                     "--output", str(report_path))
    assert evaluated.returncode == 1  # corpus gates fail on a six-song synthetic corpus
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["promotion"]["status"] == "rejected"
    failed = {result["gate"] for result in report["promotion"]["gates"] if not result["passed"]}
    assert "corpus_min_songs" in failed
    assert "corpus_min_test_songs" in failed
    # Ranking machinery itself worked: the model separates the toy signal.
    assert report["ranking"]["deltas_vs_strength"]["pairwise_accuracy"] > 0.0
    assert not (report_path.parent / "promoted-model.json").exists()
    summary_path = report_path.with_suffix(".md")
    assert summary_path.exists()
    summary = summary_path.read_text(encoding="utf-8")
    assert f"{report['ranking']['model']['pairwise_accuracy']}" in summary
    assert "**rejected**" in summary


def test_provenance_mismatch_is_rejected_and_removes_stale_promotion(tmp_path: Path):
    dataset_path, manifest_path = build_synth_dataset(tmp_path)
    candidates = tmp_path / "candidates"
    assert _run("train_event_ranker.py", "--dataset", str(dataset_path),
                "--manifest", str(manifest_path), "--output", str(candidates)).returncode == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["totals"]["song_count"] += 1
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    report_path = tmp_path / "evaluation-report.json"
    stale = tmp_path / "promoted-model.json"
    stale.write_text("stale", encoding="utf-8")
    result = _run("evaluate_event_ranker.py", "--candidate", str(candidates / "selected.json"),
                  "--dataset", str(dataset_path), "--manifest", str(manifest_path),
                  "--output", str(report_path))
    assert result.returncode == 2
    assert "provenance mismatch" in result.stderr
    assert not stale.exists()


def test_density_slices_are_ordered_by_density_not_sha():
    from scripts.evaluate_event_ranker import density_tertile_split

    songs = {
        "0": {"meta": {"onset_count": 300, "duration": 10.0}},
        "1": {"meta": {"onset_count": 10, "duration": 10.0}},
        "2": {"meta": {"onset_count": 100, "duration": 10.0}},
    }
    lowest, highest = density_tertile_split(songs)
    assert lowest == {"1"}
    assert highest == {"0"}


def test_corpus_alignment_summary_uses_only_retained_charts(tmp_path: Path):
    dataset_path, manifest_path = build_synth_dataset(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    retained_id = "a" * 64
    manifest["songs"] = [{
        **manifest["songs"][0],
        "chart_sha256s": [retained_id],
        "retained_chart_count": 1,
    }]
    manifest["charts"] = [
        {"chart_sha256": retained_id, "p95_residual": 0.020,
         "exclusion_reason": None},
        {"chart_sha256": "f" * 64, "p95_residual": 0.049,
         "exclusion_reason": "alignment_residual_too_high"},
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # Re-hash the modified manifest into an otherwise valid candidate.
    candidates = tmp_path / "candidates"
    trained = _run("train_event_ranker.py", "--dataset", str(dataset_path),
                   "--manifest", str(manifest_path), "--output", str(candidates))
    assert trained.returncode == 0, trained.stderr
    report_path = tmp_path / "evaluation-report.json"
    _run("evaluate_event_ranker.py", "--candidate", str(candidates / "selected.json"),
         "--dataset", str(dataset_path), "--manifest", str(manifest_path),
         "--output", str(report_path))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["corpus"]["alignment_p95_le_25ms_share"] == 1.0
    assert report["corpus"]["max_alignment_p95_seconds"] == 0.020


def test_report_contains_every_required_slice(tmp_path: Path):
    dataset_path, manifest_path = build_synth_dataset(tmp_path)
    candidates = tmp_path / "candidates"
    assert _run("train_event_ranker.py", "--dataset", str(dataset_path),
                "--manifest", str(manifest_path), "--output", str(candidates)).returncode == 0
    report_path = tmp_path / "evaluation-report.json"
    _run("evaluate_event_ranker.py", "--candidate", str(candidates / "selected.json"),
         "--dataset", str(dataset_path), "--manifest", str(manifest_path),
         "--output", str(report_path))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    slices = report["ranking"]["slices"]
    assert set(slices["formats"]) == {"stepmania"}
    assert "lowest_density_tertile" in slices and "highest_density_tertile" in slices
    assert "available" in slices["beat_context"] and "unavailable" in slices["beat_context"]
    assert "offgrid_events" in slices
    assert "grouped_events" in slices and "ungrouped_events" in slices
    assert report["ranking"]["bootstrap_pairwise"]["indices_sha256"]


def test_baselines_share_the_event_universe(tmp_path: Path):
    dataset_path, manifest_path = build_synth_dataset(tmp_path)
    candidates = tmp_path / "candidates"
    _run("train_event_ranker.py", "--dataset", str(dataset_path),
         "--manifest", str(manifest_path), "--output", str(candidates))
    report_path = tmp_path / "evaluation-report.json"
    _run("evaluate_event_ranker.py", "--candidate", str(candidates / "selected.json"),
         "--dataset", str(dataset_path), "--manifest", str(manifest_path),
         "--output", str(report_path))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["splits"]["test_song_count"] == 1
    model = report["ranking"]["model"]
    strength = report["ranking"]["baselines"]["strength"]
    for metric in ("ndcg_at_10", "recall_at_k"):
        assert metric in model and metric in strength


def test_ndcg_handles_zero_relevance_songs_explicitly():
    scores = {1: 0.9, 2: 0.1}
    assert er._song_ndcg_at_10(scores, {1: 0.0, 2: 0.0}) == 0.0
    assert er._song_ndcg_at_10(scores, {1: 1.0, 2: 0.0}) > 0.0


def test_bootstrap_is_stable_across_calls():
    model = {"a": 0.8, "b": 0.7, "c": 0.6, "d": 0.9}
    baseline = {"a": 0.6, "b": 0.7, "c": 0.5, "d": 0.8}
    first = er.paired_bootstrap(model, baseline, replicates=2000)
    second = er.paired_bootstrap(model, baseline, replicates=2000)
    assert first == second
    assert first["seed"] == er.BOOTSTRAP_SEED


def _passing_report() -> dict:
    return {
        "corpus": {"song_count": 30, "test_song_count": 5, "min_retained_charts_per_song": 3,
                   "leakage_error_count": 0, "unknown_license_count": 0,
                   "alignment_p95_le_25ms_share": 0.9, "max_alignment_p95_seconds": 0.03},
        "ranking": {
            "deltas_vs_strength": {"pairwise_accuracy": 0.05, "ndcg_at_10": 0.01, "recall_at_k": 0.0},
            "bootstrap_pairwise": {"lower_95": 0.01, "upper_95": 0.1, "indices_sha256": "ab" * 32},
            "ablations": {"non_metric": {"pairwise_delta_vs_strength": 0.02}},
            "slices": {
                "formats": {"stepmania": {"pairwise_delta_vs_strength": 0.03},
                            "osu": {"pairwise_delta_vs_strength": 0.04}},
                "highest_density_tertile": {"pairwise_delta_vs_strength": 0.06},
            },
            "all_metrics_finite": True,
        },
        "performance": {"inference_10k_ms": 120.0, "model_bytes": 4096,
                        "inference_10k_peak_mib": 20.0},
    }


def test_every_key_gate_has_a_pass_and_fail_verdict():
    passed = er.promotion_status(er.evaluate_promotion_gates(_passing_report()))
    assert passed == "passed"

    failing_variants = [
        ("corpus_min_songs", lambda report: report["corpus"].update(song_count=10)),
        ("pairwise_improvement", lambda report: report["ranking"]["deltas_vs_strength"].update(pairwise_accuracy=0.01)),
        ("bootstrap_lower_bound_positive", lambda report: report["ranking"]["bootstrap_pairwise"].update(lower_95=-0.01)),
        ("dense_tertile_improvement", lambda report: report["ranking"]["slices"]["highest_density_tertile"].update(pairwise_delta_vs_strength=-0.01)),
        ("non_metric_improvement", lambda report: report["ranking"]["ablations"]["non_metric"].update(pairwise_delta_vs_strength=0.0)),
        ("format_slices_not_lost", lambda report: report["ranking"]["slices"]["formats"]["osu"].update(pairwise_delta_vs_strength=-0.5)),
        ("corpus_zero_leakage", lambda report: report["corpus"].update(leakage_error_count=2)),
        ("corpus_alignment_residuals", lambda report: report["corpus"].update(alignment_p95_le_25ms_share=0.5)),
        ("inference_budget", lambda report: report["performance"].update(inference_10k_ms=900.0)),
        ("metrics_finite", lambda report: report["ranking"].update(all_metrics_finite=False)),
    ]
    for expected_gate, mutate in failing_variants:
        report = _passing_report()
        mutate(report)
        results = er.evaluate_promotion_gates(report)
        failed = {result["gate"] for result in results if not result["passed"]}
        assert expected_gate in failed, expected_gate
        assert er.promotion_status(results) == "rejected"


def test_ndcg_and_recall_gates_do_not_hide_failures():
    report = _passing_report()
    report["ranking"]["deltas_vs_strength"]["ndcg_at_10"] = -0.01
    results = er.evaluate_promotion_gates(report)
    assert any(result["gate"] == "ndcg_not_worse" and not result["passed"] for result in results)
    report = _passing_report()
    report["ranking"]["deltas_vs_strength"]["recall_at_k"] = -0.02
    results = er.evaluate_promotion_gates(report)
    assert any(result["gate"] == "sparse_recall_not_worse" and not result["passed"] for result in results)
