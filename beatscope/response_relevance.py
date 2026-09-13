"""Public, deterministic response ranking over existing Rhythm IR onsets.

The promoted model never creates, removes, moves, or quantizes an onset.  It
only adds an optional ordering value for consumers that need to spend a
limited animation or edit budget.  ``response_relevance`` is deliberately not
a probability, confidence score, instrument label, or claim of musical truth.
"""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from importlib import resources
from typing import Any

from .event_evidence import EVENT_EVIDENCE_SCHEMA, build_event_evidence
from .event_ranker import boost_score_rows, canonical_boost_model_bytes, validate_boost_model_json

RESPONSE_RELEVANCE_SCHEMA = "beatscope-response-relevance-1"
RESPONSE_RELEVANCE_SEMANTICS = "bounded-ranking-value-not-probability-or-confidence"
MODEL_RESOURCE = "response-ranker-v3.json"


class ResponseRelevanceError(ValueError):
    """Stable public failure for an unusable project, model, or sidecar."""


@lru_cache(maxsize=1)
def load_promoted_response_model() -> dict[str, Any]:
    """Load and validate the frozen promoted model shipped in the wheel."""
    raw = (resources.files("beatscope") / "data" / MODEL_RESOURCE).read_bytes()
    model = json.loads(raw.decode("utf-8"))
    errors = validate_boost_model_json(model)
    if errors:
        raise ResponseRelevanceError("model_contract_mismatch: " + "; ".join(errors))
    if model["promotion"]["status"] != "passed":
        raise ResponseRelevanceError("model_not_promoted: packaged ranker is not approved for use")
    return model


def _model_digest(model: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_boost_model_bytes(model)).hexdigest()


def validate_response_relevance(document: Any, project: dict[str, Any] | None = None) -> list[str]:
    """Return sidecar contract violations without mutating either input."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["document must be an object"]
    expected = {
        "schema", "method", "evidence_schema", "semantics", "project_id",
        "model_sha256", "events",
    }
    if set(document) != expected:
        errors.append("document must hold exactly the response-relevance fields")
    if document.get("schema") != RESPONSE_RELEVANCE_SCHEMA:
        errors.append(f"schema must be {RESPONSE_RELEVANCE_SCHEMA!r}")
    if document.get("evidence_schema") != EVENT_EVIDENCE_SCHEMA:
        errors.append(f"evidence_schema must be {EVENT_EVIDENCE_SCHEMA!r}")
    if document.get("semantics") != RESPONSE_RELEVANCE_SEMANTICS:
        errors.append("semantics must state that values are ranking-only")
    digest = document.get("model_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        errors.append("model_sha256 must be lowercase SHA-256 hex")
    rows = document.get("events")
    if not isinstance(rows, list):
        errors.append("events must be a list")
        rows = []
    seen: set[int] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"onset_id", "response_relevance"}:
            errors.append(f"events[{index}] must hold onset_id and response_relevance")
            continue
        onset_id = row.get("onset_id")
        relevance = row.get("response_relevance")
        if not isinstance(onset_id, int) or isinstance(onset_id, bool) or onset_id in seen:
            errors.append(f"events[{index}].onset_id must be a unique integer")
        else:
            seen.add(onset_id)
        if (not isinstance(relevance, (int, float)) or isinstance(relevance, bool)
                or not math.isfinite(float(relevance)) or not 0.0 <= float(relevance) <= 1.0):
            errors.append(f"events[{index}].response_relevance must be finite in [0, 1]")
    if project is not None:
        expected_ids = [int(onset["id"]) for onset in project.get("onsets", [])]
        actual_ids = [row.get("onset_id") for row in rows if isinstance(row, dict)]
        if document.get("project_id") != project.get("project_id"):
            errors.append("project_id must match the source project")
        if actual_ids != expected_ids:
            errors.append("events must cover source onsets once and in source order")
    return errors


def build_response_relevance(
    project: dict[str, Any], model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score every existing onset while preserving its identity and timestamp."""
    chosen = load_promoted_response_model() if model is None else model
    model_errors = validate_boost_model_json(chosen)
    if model_errors:
        raise ResponseRelevanceError("model_contract_mismatch: " + "; ".join(model_errors))
    if chosen["promotion"]["status"] != "passed":
        raise ResponseRelevanceError("model_not_promoted: response ranking requires a passed model")
    evidence = build_event_evidence(project)
    strengths = {int(onset["id"]): float(onset["strength"]) for onset in project["onsets"]}
    rows = boost_score_rows(evidence["events"], evidence["groups"], strengths, chosen)
    document = {
        "schema": RESPONSE_RELEVANCE_SCHEMA,
        "method": chosen["method"],
        "evidence_schema": evidence["schema"],
        "semantics": RESPONSE_RELEVANCE_SEMANTICS,
        "project_id": project["project_id"],
        "model_sha256": _model_digest(chosen),
        "events": rows,
    }
    errors = validate_response_relevance(document, project)
    if errors:
        raise ResponseRelevanceError("sidecar_contract_mismatch: " + "; ".join(errors))
    return document


def canonical_response_relevance_bytes(document: dict[str, Any]) -> bytes:
    """Serialize a valid response sidecar to deterministic UTF-8 JSON."""
    errors = validate_response_relevance(document)
    if errors:
        raise ResponseRelevanceError("sidecar_contract_mismatch: " + "; ".join(errors))
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def select_response_onsets(
    onsets: list[dict[str, Any]], document: dict[str, Any] | None, budget: int,
) -> dict[str, Any]:
    """Select existing onset objects by rank, then restore chronological order.

    If no valid sidecar is available, the budget is applied chronologically
    and the response says so.  This preserves a usable, non-deceptive path for
    older projects and for callers that explicitly disable the model.
    """
    limit = max(0, min(int(budget), len(onsets)))
    if document is None or validate_response_relevance(document):
        return {
            "available": False,
            "semantics": None,
            "strategy": "chronological-fallback",
            "total": len(onsets),
            "selected": limit,
            "events": [dict(onset) for onset in onsets[:limit]],
        }
    relevance = {
        int(row["onset_id"]): float(row["response_relevance"])
        for row in document["events"]
    }
    ranked = [
        {**onset, "response_relevance": relevance.get(int(onset["id"]))}
        for onset in onsets
        if int(onset["id"]) in relevance
    ]
    ranked.sort(key=lambda onset: (-float(onset["response_relevance"]), int(onset["id"])))
    ranked = ranked[:limit]
    ranked.sort(key=lambda onset: (
        float(onset.get("time", onset.get("raw_time", 0))), int(onset["id"]),
    ))
    return {
        "available": True,
        "semantics": RESPONSE_RELEVANCE_SEMANTICS,
        "strategy": "top-response-relevance-then-time-order",
        "total": len(onsets),
        "selected": len(ranked),
        "events": ranked,
    }


__all__ = [
    "MODEL_RESOURCE",
    "RESPONSE_RELEVANCE_SCHEMA",
    "RESPONSE_RELEVANCE_SEMANTICS",
    "ResponseRelevanceError",
    "build_response_relevance",
    "canonical_response_relevance_bytes",
    "load_promoted_response_model",
    "select_response_onsets",
    "validate_response_relevance",
]
