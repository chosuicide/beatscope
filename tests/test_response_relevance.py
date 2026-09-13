from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from beatscope.response_relevance import (
    RESPONSE_RELEVANCE_SCHEMA,
    RESPONSE_RELEVANCE_SEMANTICS,
    ResponseRelevanceError,
    build_response_relevance,
    canonical_response_relevance_bytes,
    load_promoted_response_model,
    select_response_onsets,
    validate_response_relevance,
)


def _project() -> dict:
    path = Path(__file__).parent / "fixtures" / "runtime" / "characterization-project.json"
    project = json.loads(path.read_text(encoding="utf-8"))
    project["project_id"] = "0a1b2c3d4e5f"
    return project


def test_packaged_model_is_promoted_and_valid():
    model = load_promoted_response_model()
    assert model["promotion"]["status"] == "passed"
    assert model["schema"] == "beatscope-response-ranker-3"


def test_build_response_relevance_is_complete_deterministic_and_non_mutating():
    project = _project()
    before = copy.deepcopy(project)
    first = build_response_relevance(project)
    second = build_response_relevance(project)

    assert project == before
    assert first == second
    assert first["schema"] == RESPONSE_RELEVANCE_SCHEMA
    assert first["semantics"] == RESPONSE_RELEVANCE_SEMANTICS
    assert first["project_id"] == project["project_id"]
    assert [row["onset_id"] for row in first["events"]] == [o["id"] for o in project["onsets"]]
    assert all(0 <= row["response_relevance"] <= 1 for row in first["events"])
    assert canonical_response_relevance_bytes(first) == canonical_response_relevance_bytes(second)
    assert validate_response_relevance(first, project) == []


def test_response_sidecar_contains_no_timestamps_or_claimed_confidence():
    document = json.loads(canonical_response_relevance_bytes(build_response_relevance(_project())))

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()), set())
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value), set())
        return set()

    assert keys(document).isdisjoint({
        "time", "raw_time", "quantized_time", "confidence", "importance", "instrument",
    })


def test_rejects_unpromoted_model():
    model = copy.deepcopy(load_promoted_response_model())
    model["promotion"] = {"status": "pending", "evaluation_report_sha256": None}
    with pytest.raises(ResponseRelevanceError, match="model_not_promoted"):
        build_response_relevance(_project(), model)


def test_validator_rejects_missing_and_duplicate_onsets():
    project = _project()
    document = build_response_relevance(project)
    document["events"][1]["onset_id"] = document["events"][0]["onset_id"]
    errors = validate_response_relevance(document, project)
    assert any("unique integer" in error for error in errors)
    assert any("cover source onsets" in error for error in errors)


def test_budget_selection_ranks_then_restores_time_order_and_has_honest_fallback():
    project = _project()
    sidecar = build_response_relevance(project)
    selected = select_response_onsets(project["onsets"], sidecar, 3)
    assert selected["available"] is True
    assert selected["selected"] == 3
    assert [event["time"] for event in selected["events"]] == sorted(
        event["time"] for event in selected["events"]
    )
    assert all("response_relevance" in event for event in selected["events"])
    assert [event["time"] for event in project["onsets"]] == [i * 0.5 for i in range(8)]

    fallback = select_response_onsets(project["onsets"], None, 2)
    assert fallback["available"] is False
    assert fallback["strategy"] == "chronological-fallback"
    assert fallback["events"] == project["onsets"][:2]
