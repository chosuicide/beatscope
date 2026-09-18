from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from beatscope import event_ranker as er
from beatscope import event_ranker_boost as boost
from scripts import evaluate_event_ranker_v4 as evaluation
from tests.test_event_ranker_boost import _boost_model

ROOT = Path(__file__).resolve().parents[1]


def _bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def test_receipt_is_create_once_and_never_reset(tmp_path: Path):
    receipt = tmp_path / "receipt.json"
    payload = {"schema": "test", "attempt_id": "a" * 64}
    evaluation.create_receipt(receipt, payload)
    assert json.loads(receipt.read_text()) == payload
    with pytest.raises(RuntimeError, match="evaluation_already_consumed"):
        evaluation.create_receipt(receipt, payload)


def test_lock_contract_rejects_unknown_fields():
    lock = {
        "schema": evaluation.LOCK_SCHEMA,
        "method": boost.MODEL_METHOD_V4,
        "candidate_sha256": "0" * 64,
        "non_metric_candidate_sha256": "1" * 64,
        "selection_report_sha256": "2" * 64,
        "development_dataset_sha256": "3" * 64,
        "development_manifest_sha256": "4" * 64,
        "development_source_ids": ["development"],
        "evaluation_dataset_sha256": "5" * 64,
        "evaluation_manifest_sha256": "6" * 64,
        "holdout": {
            "source_id": "holdout", "source_revision": "sha256:fixture",
            "license": "synthetic-original", "retained_song_count": 12,
            "retained_chart_count": 36,
        },
        "surprise": True,
    }
    assert "exactly" in "; ".join(evaluation.validate_lock(lock))


def _sealed_fixture(tmp_path: Path, *, corrupt_lock: bool = False) -> dict[str, Path]:
    candidate = _boost_model("full")
    non_metric = _boost_model("non_metric")
    candidate_path = tmp_path / "candidate.json"
    non_metric_path = tmp_path / "non-metric.json"
    candidate_path.write_bytes(_bytes(candidate))
    non_metric_path.write_bytes(_bytes(non_metric))
    selection_path = tmp_path / "selection-report.json"
    selection_path.write_bytes(_bytes({"schema": "synthetic-selection-report"}))

    # Deliberately malformed: preflight can authenticate it, but parsing must
    # happen only after the irreversible receipt has been created.
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_bytes(b"{not-json}\n")
    songs = []
    charts = []
    for index in range(12):
        audio = f"{index:064x}"
        chart_hashes = [hashlib.sha256(f"{index}-{chart}".encode()).hexdigest()
                        for chart in range(3)]
        songs.append({
            "audio_sha256": audio, "split": "test", "format": "stepmania",
            "license": "synthetic-original", "source_ids": ["holdout"],
            "fingerprint": hashlib.sha256(f"fingerprint-{index}".encode()).hexdigest(),
            "retained_chart_count": 3, "chart_sha256s": chart_hashes,
        })
        charts.extend({"chart_sha256": digest, "audio_sha256": audio,
                       "p95_residual": 0.005, "exclusion_reason": None}
                      for digest in chart_hashes)
    manifest = {
        "schema": er.MANIFEST_SCHEMA, "dataset_schema": er.DATASET_SCHEMA,
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "sources": [{"id": "holdout", "format": "stepmania",
                     "license": "synthetic-original", "source_revision": "sha256:fixture",
                     "partition": "test"}],
        "songs": songs, "charts": charts,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(_bytes(manifest))
    lock = {
        "schema": evaluation.LOCK_SCHEMA, "method": boost.MODEL_METHOD_V4,
        "candidate_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        "non_metric_candidate_sha256": hashlib.sha256(non_metric_path.read_bytes()).hexdigest(),
        "selection_report_sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        "development_dataset_sha256": candidate["training"]["dataset_sha256"],
        "development_manifest_sha256": candidate["training"]["manifest_sha256"],
        "development_source_ids": ["development"],
        "evaluation_dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "evaluation_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "holdout": {"source_id": "holdout", "source_revision": "sha256:fixture",
                    "license": "synthetic-original", "retained_song_count": 12,
                    "retained_chart_count": 36},
    }
    if corrupt_lock:
        lock["candidate_sha256"] = "f" * 64
    lock_path = tmp_path / "lock.json"
    lock_path.write_bytes(_bytes(lock))
    return {"candidate": candidate_path, "non_metric": non_metric_path,
            "selection": selection_path,
            "dataset": dataset_path, "manifest": manifest_path, "lock": lock_path,
            "receipt": tmp_path / "receipt.json", "output": tmp_path / "report.json"}


def _run(paths: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([
        sys.executable, str(ROOT / "scripts" / "evaluate_event_ranker_v4.py"),
        "--candidate", str(paths["candidate"]),
        "--non-metric-candidate", str(paths["non_metric"]),
        "--selection-report", str(paths["selection"]),
        "--candidate-lock", str(paths["lock"]),
        "--dataset", str(paths["dataset"]), "--manifest", str(paths["manifest"]),
        "--receipt", str(paths["receipt"]), "--output", str(paths["output"]),
    ], cwd=ROOT, capture_output=True, text=True)


def test_preflight_failure_does_not_consume_attempt(tmp_path: Path):
    paths = _sealed_fixture(tmp_path, corrupt_lock=True)
    result = _run(paths)
    assert result.returncode == 2
    assert "lock mismatch" in result.stderr
    assert not paths["receipt"].exists()


def test_failure_after_opening_holdout_consumes_attempt(tmp_path: Path):
    paths = _sealed_fixture(tmp_path)
    first = _run(paths)
    assert first.returncode != 0
    assert paths["receipt"].exists()
    second = _run(paths)
    assert second.returncode == 2
    assert "evaluation_already_consumed" in second.stderr


def test_b2_gates_include_safety_and_quality_requirements():
    report = {
        "corpus": {"test_song_count": 12, "test_chart_count": 36,
                   "min_test_charts_per_song": 3, "fresh_source_count": 1,
                   "leakage_error_count": 0, "unknown_license_count": 0,
                   "max_alignment_p95_seconds": 0.025},
        "ranking": {
            "deltas_vs_strength": {"pairwise_accuracy": 0.02, "ndcg_at_10": -0.01,
                                    "recall_at_k": -0.015},
            "bootstrap_pairwise": {"lower_95": 0.000001},
            "non_metric_delta_vs_strength": 0.01,
            "all_required_metrics_finite": True,
            "slices": {"highest_density_tertile": {"pairwise_delta_vs_strength": 0.001},
                       "sources": {"fresh": {"pairwise_delta_vs_strength": -0.01}},
                       "formats": {"stepmania": {"pairwise_delta_vs_strength": -0.01}}},
        },
        "performance": {"inference_10k_ms": 249.9, "inference_10k_peak_mib": 63.9,
                        "model_bytes": 65535, "cross_process_deterministic_output": True,
                        "repeated_call_deterministic": True, "output_sha256": "a" * 64,
                        "input_immutable": True, "runtime_purity": True},
    }
    gates = evaluation.evaluate_gates(report)
    assert len(gates) == 23
    assert all(gate["passed"] for gate in gates)
    report["corpus"]["max_alignment_p95_seconds"] = 0.025001
    failed = {gate["gate"]: gate["passed"] for gate in evaluation.evaluate_gates(report)}
    assert failed["holdout_alignment_residuals"] is False
