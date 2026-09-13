from __future__ import annotations

import hashlib
import json
from pathlib import Path

from beatscope import event_ranker as er
from scripts import evaluate_event_ranker_v5 as evaluation


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "event_ranking_v6"
MODEL = ROOT / "beatscope" / "data" / "response-ranker-v3.json"


def _sha256(path: Path) -> str:
    """Hash the canonical LF text artifact, independent of checkout policy."""
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_promoted_model_and_evidence_are_cryptographically_linked():
    manifest = json.loads((FIXTURES / "promotion-manifest.json").read_text())
    report = json.loads((FIXTURES / "evaluation-report.json").read_text())
    receipt = json.loads((FIXTURES / "evaluation-receipt.json").read_text())
    model = json.loads(MODEL.read_text())

    artifacts = manifest["artifacts"]
    assert _sha256(MODEL) == artifacts["promoted_model_sha256"]
    assert _sha256(FIXTURES / "evaluation-report.json") == artifacts["evaluation_report_sha256"]
    assert _sha256(FIXTURES / "evaluation-receipt.json") == artifacts["evaluation_receipt_sha256"]
    assert report["attempt_id"] == receipt["attempt_id"] == manifest["attempt_id"]
    assert model["promotion"] == {
        "status": "passed",
        "evaluation_report_sha256": artifacts["evaluation_report_sha256"],
    }
    assert er.validate_boost_model_json(model) == []


def test_every_frozen_r2d_gate_passed_without_rounded_rescue():
    report = json.loads((FIXTURES / "evaluation-report.json").read_text())
    frozen = report["promotion"]["gates"]
    recomputed = evaluation.evaluate_gates(report)
    assert frozen == recomputed
    assert len(frozen) == 24
    assert all(gate["passed"] for gate in frozen)
    assert report["promotion"]["status"] == "passed"


def test_round3_activates_ranker_only_through_the_response_adapter():
    production_files = [
        path for path in (ROOT / "beatscope").rglob("*.py")
        if path != MODEL and "__pycache__" not in path.parts
    ]
    imports = [path for path in production_files
               if "response-ranker-v3.json" in path.read_text(encoding="utf-8")]
    assert imports == [ROOT / "beatscope" / "response_relevance.py"]
