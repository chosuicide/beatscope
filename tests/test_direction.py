"""Direction contract tests (v0.12 Round 2 Commit 1).

Covers the four contract layers from the plan test matrix (§10.1):

- validator stability (stable error codes, notices for unknown kinds),
- canonical bytes (deterministic, pinned against the hand-written corpus),
- derive semantics (segments / bars / time fallback, Rhythm IR untouched,
  bar<->time boundary agreement),
- sidecar persistence round-trip.

Cross-language equality with web-src/src/direction/contract.ts lives in
tests/test_direction_contract.js against the same fixture file.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from beatscope.direction import (
    DIRECTION_SCHEMA,
    _canonical_number,
    build_direction_document,
    canonical_direction_bytes,
    derive_scenes_from_structure,
    direction_etag,
    resolve_anchor_times,
    validate_direction,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = json.loads((ROOT / "tests" / "fixtures" / "direction" / "contract-corpus.json").read_text(encoding="utf-8"))
ABA_RHYTHM = json.loads((ROOT / "tests" / "fixtures" / "visual" / "visual-aba.rhythm.json").read_text(encoding="utf-8"))


def _codes(messages: list[str]) -> list[str]:
    return [msg.split(": ", 1)[0] for msg in messages]


# ---------------------------------------------------------------------------
# number formatter


def test_canonical_number_matches_corpus():
    for value, expected in CORPUS["number_cases"]:
        assert _canonical_number(value) == expected, f"{value!r}"


def test_canonical_number_rejects_non_finite():
    with pytest.raises((ValueError, OverflowError)):
        _canonical_number(float("nan"))


# ---------------------------------------------------------------------------
# validator vs corpus


@pytest.mark.parametrize("case", CORPUS["doc_cases"], ids=lambda c: c["name"])
def test_validator_matches_corpus(case):
    asset_ids = set(case["asset_ids"]) if "asset_ids" in case else None
    errors, notices = validate_direction(case["doc"], asset_ids)
    assert _codes(errors) == case["expected_error_codes"]
    assert _codes(notices) == case["expected_notice_codes"]


def test_formatting_props_appear_verbatim():
    case = next(c for c in CORPUS["doc_cases"] if c["name"] == "formatting")
    body = canonical_direction_bytes(case["doc"]).decode("utf-8")
    assert CORPUS["expected_props_canonical"] in body


def test_canonical_bytes_are_deterministic():
    case = next(c for c in CORPUS["doc_cases"] if c["name"] == "full-valid")
    body = canonical_direction_bytes(case["doc"])
    reparsed = json.loads(body.decode("utf-8"))
    assert canonical_direction_bytes(reparsed) == body
    assert direction_etag(body) == f'"{__import__("hashlib").sha256(body).hexdigest()}"'


def test_regenerated_corpus_matches_checked_in_fixture():
    """The checked-in corpus must correspond to the current module behavior."""
    for case in CORPUS["doc_cases"]:
        asset_ids = set(case["asset_ids"]) if "asset_ids" in case else None
        errors, _ = validate_direction(case["doc"], asset_ids)
        assert _codes(errors) == case["expected_error_codes"], case["name"]
        if not errors:
            body = canonical_direction_bytes(case["doc"])
            assert body.decode("utf-8") == case["canonical"], case["name"]
            assert direction_etag(body) == f'"{case["canonical_sha256"]}"', case["name"]


def test_canonicalize_refuses_invalid_document():
    case = next(c for c in CORPUS["doc_cases"] if c["name"] == "bad-ratio")
    with pytest.raises(ValueError, match="direction/ratio"):
        canonical_direction_bytes(case["doc"])


# ---------------------------------------------------------------------------
# derive semantics


def test_derive_prefers_patterns_segments():
    rhythm = copy.deepcopy(ABA_RHYTHM)
    rhythm["patterns"]["segments"] = [
        {"id": "segment-001", "index": 0, "start_bar": 1, "end_bar": 8, "start_time": 0.0, "end_time": 16.0, "bar_count": 8, "family": "intro", "variant": 0, "display_label": "Opening"},
        {"id": "segment-002", "index": 1, "start_bar": 9, "end_bar": 16, "start_time": 16.0, "end_time": 32.0, "bar_count": 8, "family": "verse", "variant": 0, "display_label": "Verse A"},
        {"id": "segment-003", "index": 2, "start_bar": 17, "end_bar": 24, "start_time": 32.0, "end_time": 48.0, "bar_count": 8, "family": "chorus", "variant": 0, "display_label": "Lift"},
    ]
    before = json.dumps(rhythm, sort_keys=True)
    scenes, mode = derive_scenes_from_structure(rhythm)
    assert mode == "segments"
    assert [s["id"] for s in scenes] == ["scene-01", "scene-02", "scene-03"]
    assert scenes[0]["anchor"] == {"kind": "bars", "start_bar": 1, "end_bar": 9}
    assert scenes[0]["title"] == "Opening"
    assert scenes[0]["family"] == "intro"
    assert [s["transition_out"] for s in scenes] == ["cut", "cut", "hold-through"]
    assert all(s["layers"] == [] and s["responses"] == [] for s in scenes)
    # the Rhythm IR is never touched by derivation
    assert json.dumps(rhythm, sort_keys=True) == before


def test_derive_bars_fallback_chunks_eight_bars():
    rhythm = copy.deepcopy(ABA_RHYTHM)
    rhythm["patterns"].pop("segments", None)  # force the no-segmentation fallback
    scenes, mode = derive_scenes_from_structure(rhythm)
    assert mode == "bars"
    assert len(scenes) == 3  # 24 grid bars / 8
    assert scenes[0]["anchor"] == {"kind": "bars", "start_bar": 1, "end_bar": 9}
    assert scenes[1]["anchor"] == {"kind": "bars", "start_bar": 9, "end_bar": 17}
    assert scenes[2]["anchor"] == {"kind": "bars", "start_bar": 17, "end_bar": 25}
    assert scenes[-1]["end_time"] == 48.0
    assert scenes[0]["end_time"] == scenes[1]["start_time"]


def test_derive_time_fallback_without_grid():
    rhythm = copy.deepcopy(ABA_RHYTHM)
    rhythm.pop("grid")
    rhythm["patterns"].pop("segments", None)
    scenes, mode = derive_scenes_from_structure(rhythm)
    assert mode == "time"
    assert scenes[0]["anchor"]["kind"] == "time"
    assert scenes[0]["anchor"] == {"kind": "time", "start_seconds": 0.0, "end_seconds": 30.0}
    assert scenes[-1]["anchor"]["end_seconds"] == 48.0
    anchors = [s["anchor"] for s in scenes]
    assert anchors[0]["end_seconds"] == anchors[1]["start_seconds"]


def test_bar_and_time_anchors_agree_at_exact_boundaries():
    """§10.1: one boundary resolution rule for both anchor kinds.

    Consecutive bar-anchored scenes resolve to exactly shared boundaries
    (same origin + (bar-1) * bar_seconds formula), time anchors pass
    through untouched, and documents authored either way validate as
    continuous (the corpus 'time-anchors' case pins the touching edges).
    """
    scenes, mode = derive_scenes_from_structure(copy.deepcopy(ABA_RHYTHM))
    assert mode == "segments"
    grid = ABA_RHYTHM["grid"]
    bar_seconds = 60.0 / ABA_RHYTHM["tempo"]["global_bpm"] * ABA_RHYTHM["meter"]["numerator"]
    resolved = [resolve_anchor_times(s["anchor"], grid, bar_seconds) for s in scenes]
    for (_, prev_end), (next_start, _) in zip(resolved, resolved[1:]):
        assert next_start == prev_end  # exact, not approximate
    # time anchors are their own resolution (identity)
    assert resolve_anchor_times({"kind": "time", "start_seconds": resolved[0][0], "end_seconds": resolved[0][1]}, grid, bar_seconds) == resolved[0]


def test_resolve_anchor_times_half_open_bar_semantics():
    grid = {"origin": 0.0058}
    start, end = resolve_anchor_times({"kind": "bars", "start_bar": 1, "end_bar": 9}, grid, 2.0)
    assert start == pytest.approx(0.0058, abs=1e-9)
    assert end == pytest.approx(16.0058, abs=1e-9)
    start2, _ = resolve_anchor_times({"kind": "bars", "start_bar": 9, "end_bar": 17}, grid, 2.0)
    assert start2 == pytest.approx(end, abs=1e-9)  # neighbor ownership at the boundary
    assert resolve_anchor_times({"kind": "time", "start_seconds": 3.5, "end_seconds": 7.25}, grid, 2.0) == (3.5, 7.25)


def test_derive_requires_something_to_chunk():
    rhythm = {"project_id": "0" * 12, "source": {"duration": 0.0}, "tempo": {}, "meter": {}}
    with pytest.raises(ValueError, match="no duration and no grid"):
        derive_scenes_from_structure(rhythm)


def test_build_direction_document_carries_project_facts():
    scenes, _ = derive_scenes_from_structure(copy.deepcopy(ABA_RHYTHM))
    doc = build_direction_document(ABA_RHYTHM, scenes)
    assert doc["schema"] == DIRECTION_SCHEMA
    assert doc["project_id"] == ABA_RHYTHM["project_id"]
    assert doc["source_rhythm_sha256"] == ABA_RHYTHM["source"]["sha256"]
    assert doc["composition"] == {"primary_ratio": "16:9", "width": 1920, "height": 1080, "background": "#F5F1E8"}
    assert doc["theme"] == {} and doc["assets"] == []
    assert doc["transitions"] == [] and doc["diagnostics"] == {}
    errors, _ = validate_direction(doc)
    assert errors == []
    assert canonical_direction_bytes(doc)


# ---------------------------------------------------------------------------
# validator behaviors worth pinning directly


def test_unknown_kinds_are_notices_not_errors():
    doc = json.loads(json.dumps(next(c for c in CORPUS["doc_cases"] if c["name"] == "full-valid")["doc"]))
    doc["scenes"][0]["layers"][0]["kind"] = "hologram"
    doc["scenes"][0]["layers"][0]["props"]["custom"] = "kept"
    errors, notices = validate_direction(doc)
    assert errors == []
    assert _codes(notices) == ["direction/layer-kind-unknown"]
    # preserved as authored through canonicalization
    body = json.loads(canonical_direction_bytes(doc).decode("utf-8"))
    assert body["scenes"][0]["layers"][0]["kind"] == "hologram"
    assert body["scenes"][0]["layers"][0]["props"]["custom"] == "kept"


def test_scene_boundary_contact_is_not_overlap():
    """Scenes that touch exactly (±1ms) are continuous, not overlapping."""
    doc = json.loads(json.dumps(next(c for c in CORPUS["doc_cases"] if c["name"] == "time-anchors")["doc"]))
    doc["scenes"][1]["start_time"] = doc["scenes"][0]["end_time"] + 0.0005
    errors, _ = validate_direction(doc)
    assert [c for c in _codes(errors) if c == "direction/scene-continuity"] == []
