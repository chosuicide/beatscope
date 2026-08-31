"""Visual recipe/timeline schema validation tests (v0.8 plan sections 5/7/19.1).

The validator is the gate between the compiler and every consumer, so these
tests pin the frozen invariants: schema identifiers, family/motif rules,
variant delta bounds, timeline tiling, transition adjacency and driver
mapping, forbidden semantic fields, and cross-artifact agreement. Every
failure must carry an actionable JSON path.
"""
from __future__ import annotations

import json

import pytest

from beatscope.visual_recipe_schema import (
    BREAK_FAMILY,
    BREAK_MOTIF,
    InvalidVisualRecipe,
    LEGACY_FAMILY,
    RECIPE_SCHEMA,
    RECIPE_VERSION,
    TIMELINE_SCHEMA,
    dominant_driver,
    require_valid_visual_artifacts,
    rhythm_source_sha256,
    validate_visual_recipe,
    validate_visual_timeline,
)

PROJECT_ID = "a1b2c3d4e5f6"

ZERO_DELTA = {"spread": 0.0, "twist": 0.0, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0}


def make_rhythm() -> dict:
    """Minimal valid two-segment v4 project: A (bars 1-4) and B (bars 5-8)."""
    return {
        "schema_version": "4.0",
        "project_id": PROJECT_ID,
        "source": {
            "display_name": "unit.wav",
            "duration": 16.0,
            "sample_rate": 22050,
            "channels": 1,
            "sha256": "0" * 64,
        },
        "analysis": {
            "backend": "lightweight",
            "pipeline_version": "0.7.0",
            "provenance": {"beats": {"method": "test"}, "onsets": {"method": "test"}},
        },
        "tempo": {"global_bpm": 120.0, "segments": [{"start": 0.0, "end": 16.0, "bpm": 120.0}]},
        "meter": {"numerator": 4, "denominator": 4},
        "grid": {"origin": 0.0, "default_subdivision": 16, "bars": 8},
        "beats": [
            {"time": i * 0.5, "index": i, "bar": i // 4 + 1, "beat_in_bar": i % 4 + 1, "downbeat": i % 4 == 0}
            for i in range(32)
        ],
        "onsets": [],
        "energy": {"fps": 10, "bands": {"all": [0.1] * 160, "low": [0.1] * 160, "mid": [0.1] * 160, "high": [0.1] * 160}},
        "cues": {},
        "exports": {},
        "patterns": {
            "method": "bar-multiview-ssm-v2",
            "bars": [
                {"bar": bar, "label": "section", "group": "A" if bar <= 4 else "B", "mean_strength": 0.2,
                 "similarity_previous": 0.5, "vector": [0.0] * 16}
                for bar in range(1, 9)
            ],
            "segments": [
                {"id": "segment-001", "index": 0, "start_bar": 1, "end_bar": 4, "start_time": 0.0,
                 "end_time": 8.0, "bar_count": 4, "family": "A", "variant": 0, "descriptors": ["opening"],
                 "mean_energy": 0.1, "display_label": "A"},
                {"id": "segment-002", "index": 1, "start_bar": 5, "end_bar": 8, "start_time": 8.0,
                 "end_time": 16.0, "bar_count": 4, "family": "B", "variant": 0, "descriptors": ["opening"],
                 "mean_energy": 0.1, "display_label": "B"},
            ],
            "boundaries": [
                {"bar": 5, "time": 8.0, "novelty": 0.8,
                 "drivers": {"harmony": 0.9, "rhythm": 0.2, "energy": 0.1, "timbre": 0.3}},
            ],
        },
    }


def make_recipe(rhythm: dict) -> dict:
    return {
        "schema": RECIPE_SCHEMA,
        "recipe_version": RECIPE_VERSION,
        "project_id": rhythm["project_id"],
        "source_rhythm_sha256": rhythm_source_sha256(rhythm),
        "seed": f"{rhythm['project_id']}:visual-recipe-1",
        "mode": "structure",
        "tokens": {
            "palette": {"paper": "#f4f1e9", "ink": "#171713", "accent": "#c65032", "warm": "#fff1ce"},
            "transition": {"lead_beats": 1.0, "settle_beats": 1.5, "max_lead_seconds": 0.8, "max_settle_seconds": 0.9},
            "motion": {"max_scene_spread": 0.32, "max_scene_twist": 0.28, "max_palette_mix": 0.42},
        },
        "families": {
            "A": {"motif": "compact-triad", "palette_slot": 0,
                  "composition": {"spread": 0.14, "twist": 0.08, "flow": 0.32, "orbit": 0.44, "void": 0.18, "contrast": 0.72}},
            "B": {"motif": "orbital-weave", "palette_slot": 1,
                  "composition": {"spread": 0.26, "twist": 0.18, "flow": 0.55, "orbit": 0.78, "void": 0.30, "contrast": 0.84}},
        },
        "diagnostics": {"family_count": 2, "motif_bank_version": "motif-bank-1", "warnings": []},
    }


def make_timeline(rhythm: dict, recipe: dict) -> dict:
    return {
        "schema": TIMELINE_SCHEMA,
        "recipe_version": RECIPE_VERSION,
        "project_id": rhythm["project_id"],
        "duration": rhythm["source"]["duration"],
        "scenes": [
            {"id": "scene-001", "segment_id": "segment-001", "segment_index": 0, "family": "A", "variant": 0,
             "label": "A", "start_time": 0.0, "end_time": 8.0, "motif": "compact-triad", "variant_delta": dict(ZERO_DELTA)},
            {"id": "scene-002", "segment_id": "segment-002", "segment_index": 1, "family": "B", "variant": 0,
             "label": "B", "start_time": 8.0, "end_time": 16.0, "motif": "orbital-weave", "variant_delta": dict(ZERO_DELTA)},
        ],
        "transitions": [
            {"id": "transition-001", "boundary_bar": 5, "time": 8.0, "from_scene": "scene-001",
             "to_scene": "scene-002", "treatment": "phase-turn", "strength": 0.8, "driver": "harmony",
             "lead_seconds": 0.5, "settle_seconds": 0.75},
        ],
        "diagnostics": {"scene_count": 2, "transition_count": 1, "warnings": []},
    }


@pytest.fixture()
def artifacts():
    rhythm = make_rhythm()
    recipe = make_recipe(rhythm)
    timeline = make_timeline(rhythm, recipe)
    return rhythm, recipe, timeline


# ---------------------------------------------------------------- recipe


def test_valid_artifacts_pass(artifacts):
    rhythm, recipe, timeline = artifacts
    assert validate_visual_recipe(recipe) == []
    assert validate_visual_timeline(timeline, rhythm, recipe) == []
    require_valid_visual_artifacts(rhythm, recipe, timeline)


def test_rhythm_source_sha256_is_deterministic(artifacts):
    rhythm, _, _ = artifacts
    other = json.loads(json.dumps(rhythm))
    assert rhythm_source_sha256(rhythm) == rhythm_source_sha256(other)
    other["source"]["duration"] = 17.0
    assert rhythm_source_sha256(rhythm) != rhythm_source_sha256(other)


@pytest.mark.parametrize(
    "mutate, expected_fragment",
    [
        (lambda r: r.update(schema="beatscope-visual-recipe-0"), "$.schema"),
        (lambda r: r.update(recipe_version="0.7.0"), "$.recipe_version"),
        (lambda r: r.update(project_id="NOT-A-HASH"), "$.project_id"),
        (lambda r: r.update(source_rhythm_sha256="deadbeef"), "$.source_rhythm_sha256"),
        (lambda r: r.update(seed=""), "$.seed"),
        (lambda r: r.update(mode="cinematic"), "$.mode"),
        (lambda r: r["tokens"]["palette"].update(ink="#FFFFFF"), "$.tokens.palette.ink"),
        (lambda r: r["tokens"]["transition"].update(max_lead_seconds=1.4), "$.tokens.transition.max_lead_seconds"),
        (lambda r: r["tokens"]["transition"].update(max_settle_seconds=1.4), "$.tokens.transition.max_settle_seconds"),
        (lambda r: r["tokens"]["transition"].update(lead_beats=-1.0), "$.tokens.transition.lead_beats"),
        (lambda r: r["tokens"]["motion"].update(max_scene_spread=0.5), "$.tokens.motion.max_scene_spread"),
        (lambda r: r["tokens"]["motion"].update(max_palette_mix=0), "$.tokens.motion.max_palette_mix"),
        (lambda r: r["families"]["A"].update(motif="swirling-chaos"), "$.families.A.motif"),
        (lambda r: r["families"]["A"].update(motif=BREAK_MOTIF), "reserved"),
        (lambda r: r["families"]["A"].update(palette_slot=4), "$.families.A.palette_slot"),
        (lambda r: r["families"]["A"]["composition"].pop("void"), "$.families.A.composition"),
        (lambda r: r["families"]["A"]["composition"].update(spread=1.4), "$.families.A.composition.spread"),
        (lambda r: r["families"]["A"]["composition"].update(twist=-0.08), "$.families.A.composition.twist"),
        (lambda r: r["families"].pop("B"), "$.diagnostics.family_count"),
        (lambda r: r["diagnostics"].update(family_count=5), "$.diagnostics.family_count"),
        (lambda r: r["diagnostics"].update(motif_bank_version="motif-bank-2"), "$.diagnostics.motif_bank_version"),
        (lambda r: r.update(confidence=0.9), "confidence"),
    ],
)
def test_recipe_failures_name_actionable_paths(artifacts, mutate, expected_fragment):
    rhythm, recipe, _ = artifacts
    mutate(recipe)
    errors = validate_visual_recipe(recipe)
    assert errors, "expected the mutated recipe to fail validation"
    assert any(expected_fragment in error for error in errors), errors


def test_recipe_forbidden_keys_are_recursive(artifacts):
    _, recipe, _ = artifacts
    recipe["families"]["A"]["composition"]["confidence"] = 0.5
    errors = validate_visual_recipe(recipe)
    assert any("$.families.A.composition.confidence" in error for error in errors)


def test_break_family_must_use_reserved_motif(artifacts):
    rhythm, recipe, _ = artifacts
    rhythm["patterns"]["segments"] = [
        rhythm["patterns"]["segments"][0],
        {**rhythm["patterns"]["segments"][1], "family": BREAK_FAMILY, "display_label": "BREAK"},
    ]
    recipe["families"][BREAK_FAMILY] = recipe["families"].pop("B")
    errors = validate_visual_recipe(recipe)
    assert any(BREAK_MOTIF in error for error in errors)
    recipe["families"][BREAK_FAMILY]["motif"] = BREAK_MOTIF
    assert validate_visual_recipe(recipe) == []


def test_legacy_recipe_accepts_only_legacy_family(artifacts):
    rhythm, recipe, _ = artifacts
    recipe["mode"] = "legacy"
    recipe["families"] = {
        LEGACY_FAMILY: {"motif": "compact-triad", "palette_slot": 0,
                        "composition": {"spread": 0.0, "twist": 0.0, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0}},
    }
    recipe["diagnostics"]["family_count"] = 1
    errors = validate_visual_recipe(recipe)
    assert errors == []
    recipe["families"]["A"] = recipe["families"][LEGACY_FAMILY]
    recipe["diagnostics"]["family_count"] = 2
    errors = validate_visual_recipe(recipe)
    assert any(LEGACY_FAMILY in error for error in errors)


def test_non_finite_values_are_rejected(artifacts):
    _, recipe, _ = artifacts
    recipe["families"]["A"]["composition"]["flow"] = float("inf")
    errors = validate_visual_recipe(recipe)
    assert any("$.families.A.composition.flow" in error and "finite" in error for error in errors)


# --------------------------------------------------------------- timeline


def test_timeline_failures_name_actionable_paths(artifacts):
    rhythm, recipe, timeline = artifacts
    cases = [
        (lambda t: t.update(schema="beatscope-visual-timeline-0"), "$.schema"),
        (lambda t: t.update(recipe_version="0.9.0"), "$.recipe_version"),
        (lambda t: t.update(project_id="000000000000"), "$.project_id"),
        (lambda t: t.update(duration=15.0), "$.duration"),
        (lambda t: t["scenes"][1].update(start_time=8.5), "$.scenes[1].start_time"),
        (lambda t: t["scenes"][1].update(end_time=17.0), "$.scenes[1].end_time"),
        (lambda t: t["scenes"][1].update(family="C"), "$.scenes[1].family"),
        (lambda t: t["scenes"][1].update(variant=3), "$.scenes[1].variant"),
        (lambda t: t["scenes"][1].update(label="B-prime"), "$.scenes[1].label"),
        (lambda t: t["scenes"][1].update(motif="compact-triad"), "$.scenes[1].motif"),
        (lambda t: t["scenes"][1].update(segment_id="segment-009"), "$.scenes[1].segment_id"),
        (lambda t: t["scenes"][1].update(segment_index=7), "$.scenes[1].segment_index"),
        (lambda t: t["scenes"][1].update(id="scene-009"), "$.scenes[1].id"),
        (lambda t: t["scenes"][1]["variant_delta"].update(spread=0.1), "$.scenes[1].variant_delta"),
        (lambda t: t["transitions"].pop(), "$.transitions"),
        (lambda t: t["transitions"][0].update(id="transition-009"), "$.transitions[0].id"),
        (lambda t: t["transitions"][0].update(boundary_bar=7), "$.transitions[0].boundary_bar"),
        (lambda t: t["transitions"][0].update(time=8.4), "$.transitions[0].time"),
        (lambda t: t["transitions"][0].update(from_scene="scene-002"), "$.transitions[0].from_scene"),
        (lambda t: t["transitions"][0].update(to_scene="scene-001"), "$.transitions[0].to_scene"),
        (lambda t: t["transitions"][0].update(strength=0.11), "$.transitions[0].strength"),
        (lambda t: t["transitions"][0].update(driver="timbre"), "$.transitions[0].driver"),
        (lambda t: t["transitions"][0].update(treatment="radial-part"), "$.transitions[0].treatment"),
        (lambda t: t["transitions"][0].update(driver="fictional"), "$.transitions[0].driver"),
        (lambda t: t["transitions"][0].update(lead_seconds=0.1), "$.transitions[0].lead_seconds"),
        (lambda t: t["transitions"][0].update(settle_seconds=1.2), "$.transitions[0].settle_seconds"),
        (lambda t: t["diagnostics"].update(scene_count=9), "$.diagnostics.scene_count"),
        (lambda t: t["diagnostics"].update(transition_count=9), "$.diagnostics.transition_count"),
        (lambda t: t.update(emotion="epic"), "emotion"),
    ]
    for mutate, expected_fragment in cases:
        probe = json.loads(json.dumps(timeline))
        mutate(probe)
        errors = validate_visual_timeline(probe, rhythm, recipe)
        assert errors, f"expected mutation to fail: {expected_fragment}"
        assert any(expected_fragment in error for error in errors), (expected_fragment, errors)


def test_timeline_scene_count_must_match_segments(artifacts):
    rhythm, recipe, timeline = artifacts
    timeline["scenes"] = timeline["scenes"][:1]
    errors = validate_visual_timeline(timeline, rhythm, recipe)
    assert any("$.scenes must hold 2 scene(s)" in error for error in errors)


def test_timeline_lead_must_respect_recipe_token(artifacts):
    rhythm, recipe, timeline = artifacts
    recipe["tokens"]["transition"]["max_lead_seconds"] = 0.4
    timeline["transitions"][0]["lead_seconds"] = 0.5
    errors = validate_visual_timeline(timeline, rhythm, recipe)
    assert any("exceeds the recipe token" in error for error in errors)


def test_timeline_driver_must_be_dominant_stored_driver(artifacts):
    rhythm, recipe, timeline = artifacts
    rhythm["patterns"]["boundaries"][0]["drivers"] = {"harmony": 0.1, "rhythm": 0.2, "energy": 0.1, "timbre": 0.9}
    errors = validate_visual_timeline(timeline, rhythm, recipe)
    assert any("'timbre'" in error and "dominant" in error for error in errors)
    timeline["transitions"][0]["driver"] = "timbre"
    timeline["transitions"][0]["treatment"] = "flow-shear"
    assert validate_visual_timeline(timeline, rhythm, recipe) == []


def test_timeline_neutral_boundary_uses_cross_settle(artifacts):
    rhythm, recipe, timeline = artifacts
    rhythm["patterns"]["boundaries"][0]["drivers"] = {}
    timeline["transitions"][0]["driver"] = "neutral"
    timeline["transitions"][0]["treatment"] = "cross-settle"
    assert validate_visual_timeline(timeline, rhythm, recipe) == []


def test_timeline_legacy_shape(artifacts):
    rhythm, recipe, timeline = artifacts
    legacy_rhythm = make_rhythm()
    del legacy_rhythm["patterns"]["segments"]
    del legacy_rhythm["patterns"]["boundaries"]
    legacy_recipe = make_recipe(legacy_rhythm)
    legacy_recipe["mode"] = "legacy"
    legacy_recipe["families"] = {
        LEGACY_FAMILY: {"motif": "compact-triad", "palette_slot": 0,
                        "composition": {"spread": 0.0, "twist": 0.0, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0}},
    }
    legacy_recipe["diagnostics"]["family_count"] = 1
    legacy_timeline = {
        "schema": TIMELINE_SCHEMA,
        "recipe_version": RECIPE_VERSION,
        "project_id": legacy_rhythm["project_id"],
        "duration": 16.0,
        "scenes": [
            {"id": "scene-001", "segment_id": None, "segment_index": 0, "family": LEGACY_FAMILY, "variant": 0,
             "label": LEGACY_FAMILY, "start_time": 0.0, "end_time": 16.0, "motif": "compact-triad",
             "variant_delta": dict(ZERO_DELTA)},
        ],
        "transitions": [],
        "diagnostics": {"scene_count": 1, "transition_count": 0, "warnings": []},
    }
    assert validate_visual_timeline(legacy_timeline, legacy_rhythm, legacy_recipe) == []
    require_valid_visual_artifacts(legacy_rhythm, legacy_recipe, legacy_timeline)


# ---------------------------------------------------------- variant deltas


def make_variant_artifacts(delta: dict) -> tuple:
    """Two-scene project where scene 2 is A variant 1 carrying ``delta``."""
    rhythm = make_rhythm()
    rhythm["patterns"]["segments"] = [
        rhythm["patterns"]["segments"][0],
        {**rhythm["patterns"]["segments"][1], "family": "A", "variant": 1, "display_label": "A′"},
    ]
    recipe = make_recipe(rhythm)
    recipe["families"] = {"A": recipe["families"]["A"]}
    recipe["diagnostics"]["family_count"] = 1
    timeline = make_timeline(rhythm, recipe)
    timeline["scenes"][1].update(family="A", variant=1, label="A′", motif="compact-triad")
    timeline["scenes"][1]["variant_delta"] = delta
    return rhythm, recipe, timeline


VALID_DELTA = {"spread": -0.06, "twist": 0.08, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0}


def test_valid_variant_delta_passes():
    rhythm, recipe, timeline = make_variant_artifacts(VALID_DELTA)
    assert validate_visual_timeline(timeline, rhythm, recipe) == []


@pytest.mark.parametrize(
    "delta, expected_fragment",
    [
        # only one property changed
        ({"spread": -0.06, "twist": 0.0, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0}, "exactly one"),
        # two primaries, no secondary
        ({"spread": 0.0, "twist": 0.08, "flow": 0.06, "orbit": 0.0, "void": 0.0, "contrast": 0.0}, "exactly one"),
        # magnitude below the floor
        ({"spread": -0.03, "twist": 0.08, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0}, "magnitude"),
        # magnitude above the ceiling
        ({"spread": -0.06, "twist": 0.20, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0}, "magnitude"),
        # pushes a property out of 0..1
        ({"spread": 0.9, "twist": 0.08, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0}, "out of 0..1"),
        # aggregate Euclidean distance above 0.22
        ({"spread": -0.16, "twist": 0.16, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0}, "aggregate distance"),
    ],
)
def test_invalid_variant_deltas_fail(delta, expected_fragment):
    rhythm, recipe, timeline = make_variant_artifacts(delta)
    errors = validate_visual_timeline(timeline, rhythm, recipe)
    assert any(expected_fragment in error for error in errors), errors


def test_same_family_variant_requires_identical_deltas():
    rhythm, recipe, timeline = make_variant_artifacts(VALID_DELTA)
    rhythm["patterns"]["segments"] = rhythm["patterns"]["segments"] + [
        {**rhythm["patterns"]["segments"][1], "id": "segment-003", "index": 2, "start_bar": 9,
         "end_bar": 12, "start_time": 16.0, "end_time": 24.0},
    ]
    rhythm["patterns"]["boundaries"] = rhythm["patterns"]["boundaries"] + [
        {"bar": 9, "time": 16.0, "novelty": 0.5,
         "drivers": {"harmony": 0.4, "rhythm": 0.2, "energy": 0.1, "timbre": 0.3}},
    ]
    rhythm["source"]["duration"] = 24.0
    rhythm["grid"]["bars"] = 12
    recipe["source_rhythm_sha256"] = rhythm_source_sha256(rhythm)
    timeline["duration"] = 24.0
    timeline["scenes"][1]["end_time"] = 16.0
    second = json.loads(json.dumps(timeline["scenes"][1]))
    second.update(id="scene-003", segment_id="segment-003", segment_index=2, start_time=16.0, end_time=24.0)
    timeline["scenes"].append(second)
    timeline["transitions"].append(
        {"id": "transition-002", "boundary_bar": 9, "time": 16.0, "from_scene": "scene-002",
         "to_scene": "scene-003", "treatment": "phase-turn", "strength": 0.5, "driver": "harmony",
         "lead_seconds": 0.5, "settle_seconds": 0.75}
    )
    timeline["diagnostics"] = {"scene_count": 3, "transition_count": 2, "warnings": []}
    errors = validate_visual_timeline(timeline, rhythm, recipe)
    assert errors == []
    timeline["scenes"][2]["variant_delta"] = {**VALID_DELTA, "twist": 0.10}
    errors = validate_visual_timeline(timeline, rhythm, recipe)
    assert any("identical for every" in error for error in errors)


# ------------------------------------------------------- require_valid


def test_require_valid_reports_every_artifact_and_path(artifacts):
    rhythm, recipe, timeline = artifacts
    recipe["schema"] = "nope"
    timeline["duration"] = 3.0
    rhythm["tempo"]["global_bpm"] = 999.0
    with pytest.raises(InvalidVisualRecipe) as excinfo:
        require_valid_visual_artifacts(rhythm, recipe, timeline)
    message = str(excinfo.value)
    assert "rhythm: tempo.global_bpm" in message
    assert "recipe: $.schema" in message
    assert "timeline: $.duration" in message


def test_require_valid_rejects_sha_mismatch(artifacts):
    rhythm, recipe, timeline = artifacts
    recipe["source_rhythm_sha256"] = "f" * 64
    with pytest.raises(InvalidVisualRecipe) as excinfo:
        require_valid_visual_artifacts(rhythm, recipe, timeline)
    assert "source_rhythm_sha256" in str(excinfo.value)


def test_require_valid_without_timeline(artifacts):
    rhythm, recipe, _ = artifacts
    require_valid_visual_artifacts(rhythm, recipe, None)
    recipe["families"]["B"]["composition"]["orbit"] = 2.0
    with pytest.raises(InvalidVisualRecipe):
        require_valid_visual_artifacts(rhythm, recipe, None)
