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


# --------------------------------------------------------------------------
# Deterministic compiler (v0.8 plan section 6)
# --------------------------------------------------------------------------

import copy
import hashlib
from pathlib import Path

import beatscope.visual_recipe as visual_recipe_module
from beatscope.cli import main as cli_main
from beatscope.project import RECIPE_FILENAME, TIMELINE_FILENAME, ProjectManager
from beatscope.visual_recipe import (
    COMPILER_VERSION,
    canonical_visual_bytes,
    compile_visual_artifacts,
    compile_visual_recipe,
    compile_visual_timeline,
    stable_hash,
    stable_unit,
    visual_artifact_fingerprint,
    _variant_delta,
)
from beatscope.visual_recipe_schema import (
    COMPOSITION_KEYS,
    MOTIF_BANK,
    VARIANT_DELTA_MAX,
    VARIANT_DELTA_MIN,
    VARIANT_DISTANCE_MAX,
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    variant_distance,
)

BAR_SECONDS = 2.0
BARS_PER_SEGMENT = 4


def build_rhythm(
    project_id: str = PROJECT_ID,
    families: tuple[str, ...] = ("A", "B"),
    variants: tuple[int, ...] | None = None,
    beat_times: list[float] | None = None,
    boundaries: list[dict] | None = None,
    global_bpm: float = 120.0,
) -> dict:
    """Flexible valid v4 project: 4-bar segments of the given families."""
    variants = list(variants) if variants is not None else [0] * len(families)
    total_bars = len(families) * BARS_PER_SEGMENT
    duration = total_bars * BAR_SECONDS
    segments = []
    for index, family in enumerate(families):
        start_bar = index * BARS_PER_SEGMENT + 1
        start_time = (start_bar - 1) * BAR_SECONDS
        segments.append(
            {
                "id": f"segment-{index + 1:03d}",
                "index": index,
                "start_bar": start_bar,
                "end_bar": start_bar + BARS_PER_SEGMENT - 1,
                "start_time": start_time,
                "end_time": start_time + BARS_PER_SEGMENT * BAR_SECONDS,
                "bar_count": BARS_PER_SEGMENT,
                "family": family,
                "variant": variants[index],
                "descriptors": ["opening"],
                "mean_energy": 0.1,
                "display_label": family if variants[index] == 0 else f"{family}\u2032",
            }
        )
    if boundaries is None:
        boundaries = [
            {
                "bar": (index + 1) * BARS_PER_SEGMENT + 1,
                "time": (index + 1) * BARS_PER_SEGMENT * BAR_SECONDS,
                "novelty": 0.5,
                "drivers": {"harmony": 0.9, "rhythm": 0.2, "energy": 0.1, "timbre": 0.3},
            }
            for index in range(len(families) - 1)
        ]
    if beat_times is None:
        beat_times = [i * 0.5 for i in range(int(duration / 0.5))]
    # Bars follow the beat rank so arbitrary (off-grid) beat spacings keep
    # beat_in_bar within 1..4; the transition compiler only reads times.
    beats = []
    for index, time in enumerate(beat_times):
        beats.append(
            {
                "time": time,
                "index": index,
                "bar": index // 4 + 1,
                "beat_in_bar": index % 4 + 1,
                "downbeat": index % 4 == 0,
            }
        )
    energy_samples = int(duration * 10)
    rhythm = {
        "schema_version": "4.0",
        "project_id": project_id,
        "source": {
            "display_name": "unit.wav",
            "duration": duration,
            "sample_rate": 22050,
            "channels": 1,
            "sha256": "0" * 64,
        },
        "analysis": {
            "backend": "lightweight",
            "pipeline_version": "0.7.0",
            "provenance": {"beats": {"method": "test"}, "onsets": {"method": "test"}},
        },
        "tempo": {
            "global_bpm": global_bpm,
            "segments": [{"start": 0.0, "end": duration, "bpm": global_bpm}],
        },
        "meter": {"numerator": 4, "denominator": 4},
        "grid": {"origin": 0.0, "default_subdivision": 16, "bars": total_bars},
        "beats": beats,
        "onsets": [],
        "energy": {
            "fps": 10,
            "bands": {
                "all": [0.1] * energy_samples,
                "low": [0.1] * energy_samples,
                "mid": [0.1] * energy_samples,
                "high": [0.1] * energy_samples,
            },
        },
        "cues": {},
        "exports": {},
        "patterns": {
            "method": "bar-multiview-ssm-v2",
            "bars": [
                {
                    "bar": bar,
                    "label": "section",
                    "group": families[(bar - 1) // BARS_PER_SEGMENT],
                    "mean_strength": 0.2,
                    "similarity_previous": 0.5,
                    "vector": [0.0] * 16,
                }
                for bar in range(1, total_bars + 1)
            ],
            "segments": segments,
            "boundaries": boundaries,
        },
    }
    from beatscope.schema import validate_rhythm_v4

    errors = validate_rhythm_v4(rhythm)
    assert not errors, errors
    return rhythm


def test_stable_hash_uses_sha256_not_python_hash():
    assert stable_hash("abc") == int.from_bytes(hashlib.sha256(b"abc").digest()[:8], "big")
    assert stable_hash("abc") == stable_hash("abc")
    unit = stable_unit("abc")
    assert 0.0 <= unit < 1.0
    assert unit == stable_hash("abc") / ((1 << 64) - 1)


def test_compile_recipe_family_order_is_first_occurrence():
    recipe = compile_visual_recipe(build_rhythm(families=("B", "A", "B")))
    assert list(recipe["families"]) == ["B", "A"]
    assert recipe["diagnostics"]["family_count"] == 2


def test_compile_recipe_is_deterministic_and_banked():
    rhythm = build_rhythm()
    first = compile_visual_recipe(rhythm)
    second = compile_visual_recipe(copy.deepcopy(rhythm))
    assert first == second
    for entry in first["families"].values():
        assert entry["motif"] in MOTIF_BANK
        assert 0 <= entry["palette_slot"] <= 3
    # The first family always receives its hash-selected motif: nothing is
    # assigned before it, so the collision scan can never move it.
    preferred = stable_hash(f"{PROJECT_ID}:A:motif-bank-1") % len(MOTIF_BANK)
    assert first["families"]["A"]["motif"] == MOTIF_BANK[preferred]
    assert first["families"]["A"]["motif"] != first["families"]["B"]["motif"]


def test_motif_collision_prefers_unused_motifs():
    def preferred(project_id: str, family: str) -> int:
        return stable_hash(f"{project_id}:{family}:motif-bank-1") % len(MOTIF_BANK)

    colliding_id = None
    for index in range(100000):
        candidate = f"{index:012x}"
        if preferred(candidate, "A") == preferred(candidate, "B"):
            colliding_id = candidate
            break
    assert colliding_id is not None

    recipe = compile_visual_recipe(build_rhythm(project_id=colliding_id))
    motifs = {family: entry["motif"] for family, entry in recipe["families"].items()}
    assert motifs["A"] == MOTIF_BANK[preferred(colliding_id, "A")]
    assert motifs["A"] != motifs["B"], "colliding families must split across the bank"


def test_motif_reuse_after_bank_exhaustion_uses_fresh_slot():
    recipe = compile_visual_recipe(build_rhythm(families=("A", "B", "C", "D", "E")))
    entries = recipe["families"]
    assert list(entries) == ["A", "B", "C", "D", "E"]
    first_four = [entries[name]["motif"] for name in ("A", "B", "C", "D")]
    assert sorted(first_four) == sorted(MOTIF_BANK), "four families must cover the bank"
    fifth = entries["E"]
    assert fifth["motif"] in first_four, "bank exhausted; the hash-selected motif is reused"
    same_motif_slots = [
        entry["palette_slot"] for entry in entries.values() if entry["motif"] == fifth["motif"]
    ]
    assert len(same_motif_slots) == len(set(same_motif_slots)), "reuse needs a different slot"
    pairs = {(entry["motif"], entry["palette_slot"]) for entry in entries.values()}
    assert len(pairs) == 5


def test_break_family_receives_reserved_motif():
    recipe = compile_visual_recipe(build_rhythm(families=("A", "BREAK", "A")))
    assert recipe["families"]["BREAK"]["motif"] == "suspended-void"
    others = {entry["motif"] for family, entry in recipe["families"].items() if family != "BREAK"}
    assert "suspended-void" not in others


def test_legacy_recipe_and_timeline_shape():
    rhythm = build_rhythm(families=("A",))
    rhythm["patterns"].pop("segments")
    rhythm["patterns"].pop("boundaries")
    recipe, timeline = compile_visual_artifacts(rhythm)
    assert recipe["mode"] == "legacy"
    assert recipe["diagnostics"]["warnings"], "legacy compilation must warn, not error"
    legacy = recipe["families"]["LEGACY"]
    assert legacy["motif"] == "compact-triad"
    assert legacy["palette_slot"] == 0
    assert legacy["composition"] == {key: 0.0 for key in COMPOSITION_KEYS}
    assert timeline["mode"] == "legacy"
    assert timeline["transitions"] == []
    assert len(timeline["scenes"]) == 1
    scene = timeline["scenes"][0]
    assert scene["start_time"] == 0.0
    assert scene["end_time"] == rhythm["source"]["duration"]
    assert scene["segment_id"] is None
    assert scene["label"] == "LEGACY"
    assert scene["variant_delta"] == {key: 0.0 for key in COMPOSITION_KEYS}


def test_malformed_segments_fail_loudly():
    rhythm = build_rhythm()
    rhythm["patterns"]["segments"] = ["not-a-segment"]
    with pytest.raises(InvalidVisualRecipe, match="segment objects"):
        compile_visual_artifacts(rhythm)

    rhythm = build_rhythm()
    rhythm["patterns"]["boundaries"] = []
    with pytest.raises(InvalidVisualRecipe, match="no boundary for bar"):
        compile_visual_artifacts(rhythm)


def test_variant_deltas_obey_generation_rules():
    rhythm = build_rhythm(families=("A", "A"), variants=(0, 1))
    recipe, timeline = compile_visual_artifacts(rhythm)
    base = recipe["families"]["A"]["composition"]
    zero_scene, primed_scene = timeline["scenes"]
    assert zero_scene["variant_delta"] == {key: 0.0 for key in COMPOSITION_KEYS}

    delta = primed_scene["variant_delta"]
    changed = [key for key in COMPOSITION_KEYS if delta[key] != 0.0]
    assert len(changed) == 2
    assert len([key for key in changed if key in VARIANT_PRIMARY]) == 1
    assert len([key for key in changed if key in VARIANT_SECONDARY]) == 1
    for key in changed:
        assert VARIANT_DELTA_MIN <= abs(delta[key]) <= VARIANT_DELTA_MAX
        assert 0.0 <= base[key] + delta[key] <= 1.0
    assert variant_distance(delta) <= VARIANT_DISTANCE_MAX


def test_variant_delta_is_pure_per_family_and_variant():
    base = compile_visual_recipe(build_rhythm())["families"]["A"]["composition"]
    first = _variant_delta(PROJECT_ID, "A", 1, base)
    assert first == _variant_delta(PROJECT_ID, "A", 1, base)
    second = _variant_delta(PROJECT_ID, "A", 2, base)
    assert second != first
    for delta in (first, second):
        assert variant_distance(delta) <= VARIANT_DISTANCE_MAX


def test_repeated_family_variant_receives_identical_delta():
    rhythm = build_rhythm(families=("A", "A", "A"), variants=(0, 1, 1))
    _, timeline = compile_visual_artifacts(rhythm)
    deltas = [scene["variant_delta"] for scene in timeline["scenes"][1:]]
    assert deltas[0] == deltas[1]


def test_transition_durations_come_from_adjacent_real_beats():
    # 0.5s beat spacing before the boundary at 8.0, 0.4s after it: the beat
    # exactly on the boundary belongs to the "next" side.  localBeat is the
    # median of the two adjacent intervals: median(0.5, 0.4) = 0.45.
    before = [i * 0.5 for i in range(16)]
    after = [8.0, 8.4] + [8.4 + i * 0.5 for i in range(1, 16)]
    rhythm = build_rhythm(families=("A", "B"), beat_times=before + after)
    _, timeline = compile_visual_artifacts(rhythm)
    transition = timeline["transitions"][0]
    assert transition["lead_seconds"] == pytest.approx(0.45)
    assert transition["settle_seconds"] == pytest.approx(0.675)


@pytest.mark.parametrize(
    "spacing, expected_lead, expected_settle",
    [
        (2.0, 0.8, 0.9),  # long beats clamp to the token maxima
        (0.2, 0.25, 0.35),  # short beats clamp to the range minima
    ],
)
def test_transition_durations_clamp_to_contract(spacing, expected_lead, expected_settle):
    beat_times = [i * spacing for i in range(64) if i * spacing < 16.0]
    rhythm = build_rhythm(families=("A", "B"), beat_times=beat_times)
    _, timeline = compile_visual_artifacts(rhythm)
    transition = timeline["transitions"][0]
    assert transition["lead_seconds"] == pytest.approx(expected_lead)
    assert transition["settle_seconds"] == pytest.approx(expected_settle)


def test_dense_boundaries_clamp_to_half_the_available_gap():
    # Boundaries 0.35s apart: lead/settle clamp to half the gap.  Rhythm v4
    # pins boundary times to segment starts, so such gaps cannot appear in a
    # validated project; the clamp itself is pinned on the pure helper.  The
    # clamped values fall below the artifact range floor, which full
    # validation would reject.
    from beatscope.visual_recipe import _transition_durations

    rhythm = build_rhythm()  # 0.5s beats: localBeat 0.5, lead 0.5, settle 0.75
    lead, settle = _transition_durations(rhythm, 8.35, 8.0, None, 16.0)
    assert lead == pytest.approx(0.35 / 2)
    assert settle == pytest.approx(0.75)


def test_canonical_bytes_round_and_normalize():
    data = canonical_visual_bytes({"a": 0.1 + 0.2, "b": [-0.0, 1, "é"], "c": {"d": 2.0}})
    assert data.endswith(b"\n")
    assert data.startswith(b'{\n  "a": 0.3,')
    assert b"-0.0" not in data
    assert "é".encode("utf-8") in data
    reparsed = json.loads(data.decode("utf-8"))
    assert canonical_visual_bytes(reparsed) == data, "canonical bytes are idempotent"
    with pytest.raises(ValueError):
        canonical_visual_bytes({"x": float("inf")})


def test_compiled_artifacts_survive_canonical_round_trip():
    rhythm = build_rhythm(families=("A", "A"), variants=(0, 1))
    recipe, timeline = compile_visual_artifacts(rhythm)
    assert json.loads(canonical_visual_bytes(recipe).decode("utf-8")) == recipe
    assert json.loads(canonical_visual_bytes(timeline).decode("utf-8")) == timeline


def test_fingerprint_covers_compiler_identity_and_rhythm():
    rhythm = build_rhythm()
    fingerprint = visual_artifact_fingerprint(rhythm)
    assert fingerprint == visual_artifact_fingerprint(copy.deepcopy(rhythm))
    changed = copy.deepcopy(rhythm)
    changed["tempo"]["global_bpm"] = 140.0
    assert visual_artifact_fingerprint(changed) != fingerprint

    renamed = copy.deepcopy(rhythm)
    renamed["project_id"] = "b2c3d4e5f6a1"
    assert visual_artifact_fingerprint(renamed) != fingerprint

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(visual_recipe_module, "COMPILER_VERSION", "visual-recipe-compiler-0")
        assert visual_artifact_fingerprint(rhythm) != fingerprint
    finally:
        monkey.undo()


def test_artifact_fingerprint_is_stored_in_the_recipe():
    recipe, _ = compile_visual_artifacts(build_rhythm())
    assert recipe["diagnostics"]["artifact_fingerprint"] == visual_artifact_fingerprint(
        build_rhythm()
    )


# --------------------------------------------------------------------------
# Project persistence (v0.8 plan section 8)
# --------------------------------------------------------------------------

@pytest.fixture()
def manager(tmp_path):
    return ProjectManager(cache_root=tmp_path / "cache")


def _saved_rhythm(manager: ProjectManager, **kwargs) -> dict:
    rhythm = build_rhythm(**kwargs)
    manager.save_project(rhythm["project_id"], Path("unused.wav"), rhythm, {}, "cache-key")
    return rhythm


def _artifact_bytes(p_dir: Path) -> tuple[bytes, bytes]:
    return (
        (p_dir / RECIPE_FILENAME).read_bytes(),
        (p_dir / TIMELINE_FILENAME).read_bytes(),
    )


def test_save_project_writes_visual_artifacts(manager):
    rhythm = _saved_rhythm(manager)
    p_dir = manager.get_project_dir(PROJECT_ID)
    recipe_bytes, timeline_bytes = _artifact_bytes(p_dir)
    recipe = json.loads(recipe_bytes.decode("utf-8"))
    timeline = json.loads(timeline_bytes.decode("utf-8"))
    require_valid_visual_artifacts(rhythm, recipe, timeline)
    assert recipe["diagnostics"]["artifact_fingerprint"] == visual_artifact_fingerprint(rhythm)
    assert timeline["duration"] == rhythm["source"]["duration"]


def test_saved_artifacts_are_canonical_bytes(manager):
    rhythm = _saved_rhythm(manager)
    p_dir = manager.get_project_dir(PROJECT_ID)
    recipe, timeline = compile_visual_artifacts(rhythm)
    assert _artifact_bytes(p_dir) == (canonical_visual_bytes(recipe), canonical_visual_bytes(timeline))


def test_ensure_visual_artifacts_is_lazy(manager):
    rhythm = _saved_rhythm(manager)
    p_dir = manager.get_project_dir(PROJECT_ID)
    before = _artifact_bytes(p_dir)
    result = manager.ensure_visual_artifacts(rhythm)
    assert result["regenerated"] is False
    assert _artifact_bytes(p_dir) == before


def test_ensure_regenerates_on_fingerprint_mismatch(manager):
    rhythm = _saved_rhythm(manager)
    p_dir = manager.get_project_dir(PROJECT_ID)
    recipe = json.loads((p_dir / RECIPE_FILENAME).read_text(encoding="utf-8"))
    recipe["diagnostics"]["artifact_fingerprint"] = "0" * 64
    (p_dir / RECIPE_FILENAME).write_text(json.dumps(recipe), encoding="utf-8")

    result = manager.ensure_visual_artifacts(rhythm)
    assert result["regenerated"] is True
    stored = json.loads((p_dir / RECIPE_FILENAME).read_text(encoding="utf-8"))
    assert stored["diagnostics"]["artifact_fingerprint"] == visual_artifact_fingerprint(rhythm)


def test_ensure_regenerates_on_compiler_version_change(manager, monkeypatch):
    rhythm = _saved_rhythm(manager)
    monkeypatch.setattr(visual_recipe_module, "COMPILER_VERSION", "visual-recipe-compiler-0")
    result = manager.ensure_visual_artifacts(rhythm)
    assert result["regenerated"] is True


def test_ensure_regenerates_when_rhythm_changes(manager):
    rhythm = _saved_rhythm(manager)
    updated = copy.deepcopy(rhythm)
    updated["tempo"]["global_bpm"] = 140.0
    result = manager.ensure_visual_artifacts(updated)
    assert result["regenerated"] is True
    assert result["recipe"]["source_rhythm_sha256"] == rhythm_source_sha256(updated)


def test_failed_regeneration_keeps_existing_artifacts(manager, monkeypatch):
    rhythm = _saved_rhythm(manager)
    p_dir = manager.get_project_dir(PROJECT_ID)
    before = _artifact_bytes(p_dir)

    def broken_compile(_rhythm):
        raise InvalidVisualRecipe("simulated compiler bug")

    monkeypatch.setattr(visual_recipe_module, "compile_visual_artifacts", broken_compile)
    with pytest.raises(InvalidVisualRecipe, match="simulated compiler bug"):
        manager.ensure_visual_artifacts(rhythm, force=True)
    assert _artifact_bytes(p_dir) == before, "valid artifacts must stay untouched"


def test_interrupted_regeneration_recovers_on_next_load(manager, monkeypatch):
    rhythm = _saved_rhythm(manager)
    p_dir = manager.get_project_dir(PROJECT_ID)

    import beatscope.project as project_module

    calls = {"count": 0}

    def crashing_replace(path, data):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated crash between files")
        project_module._atomic_write_bytes(path, data)

    monkeypatch.setattr(project_module, "_atomic_write_bytes", crashing_replace)
    with pytest.raises(OSError, match="simulated crash"):
        manager.ensure_visual_artifacts(rhythm, force=True)
    monkeypatch.undo()

    result = manager.ensure_visual_artifacts(rhythm, force=True)
    assert result["regenerated"] is True
    recipe, timeline = compile_visual_artifacts(rhythm)
    assert _artifact_bytes(p_dir) == (canonical_visual_bytes(recipe), canonical_visual_bytes(timeline))


def test_regeneration_never_touches_audio(manager):
    rhythm = _saved_rhythm(manager)  # audio file 'unused.wav' never existed
    p_dir = manager.get_project_dir(PROJECT_ID)
    (p_dir / RECIPE_FILENAME).unlink()
    (p_dir / TIMELINE_FILENAME).unlink()
    assert manager.get_project_audio_path(PROJECT_ID) is None
    result = manager.ensure_visual_artifacts(rhythm)
    assert result["regenerated"] is True


def test_structural_change_does_not_share_artifacts(manager):
    first = _saved_rhythm(manager, global_bpm=120.0)
    updated = copy.deepcopy(first)
    updated["tempo"]["global_bpm"] = 140.0

    result = manager.ensure_visual_artifacts(updated)
    assert result["regenerated"] is True
    assert result["recipe"]["source_rhythm_sha256"] == rhythm_source_sha256(updated)
    back = manager.ensure_visual_artifacts(first, force=True)
    assert back["recipe"]["source_rhythm_sha256"] == rhythm_source_sha256(first)


def test_get_project_visual_artifacts_upgrades_v07_cache_lazily(manager):
    _saved_rhythm(manager)
    p_dir = manager.get_project_dir(PROJECT_ID)
    (p_dir / RECIPE_FILENAME).unlink()
    (p_dir / TIMELINE_FILENAME).unlink()

    loaded = manager.get_project_visual_artifacts(PROJECT_ID)
    assert loaded is not None
    assert loaded["regenerated"] is True
    require_valid_visual_artifacts(loaded["rhythm"], loaded["recipe"], loaded["timeline"])
    assert manager.get_project_visual_artifacts(PROJECT_ID)["regenerated"] is False
    assert manager.get_project_visual_artifacts("no-such-project") is None


# --------------------------------------------------------------------------
# visual-build CLI (v0.8 plan section 8)
# --------------------------------------------------------------------------


def test_visual_build_file_mode_writes_siblings(tmp_path):
    source = tmp_path / "song.rhythm.json"
    source.write_text(json.dumps(build_rhythm()), encoding="utf-8")
    assert cli_main(["visual-build", str(source)]) == 0
    assert (tmp_path / RECIPE_FILENAME).is_file()
    assert (tmp_path / TIMELINE_FILENAME).is_file()


def test_visual_build_file_mode_honors_output_dir(tmp_path):
    source = tmp_path / "song.rhythm.json"
    source.write_text(json.dumps(build_rhythm()), encoding="utf-8")
    out_dir = tmp_path / "artifacts"
    assert cli_main(["visual-build", str(source), "--output-dir", str(out_dir)]) == 0
    assert (out_dir / RECIPE_FILENAME).is_file()
    assert (out_dir / TIMELINE_FILENAME).is_file()
    assert not (tmp_path / RECIPE_FILENAME).exists()


def test_visual_build_project_mode_is_lazy_and_forceable(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    manager = ProjectManager()
    _saved_rhythm(manager)
    p_dir = manager.get_project_dir(PROJECT_ID)

    # save_project already compiled the artifacts, so the first run is a
    # fingerprint hit; deleting the recipe forces regeneration, --force
    # always regenerates.
    assert cli_main(["visual-build", PROJECT_ID]) == 0
    assert "already current" in capsys.readouterr().out
    (p_dir / RECIPE_FILENAME).unlink()
    assert cli_main(["visual-build", PROJECT_ID]) == 0
    assert "regenerated" in capsys.readouterr().out
    assert cli_main(["visual-build", PROJECT_ID]) == 0
    assert "already current" in capsys.readouterr().out
    assert cli_main(["visual-build", PROJECT_ID, "--force"]) == 0
    assert "regenerated" in capsys.readouterr().out


def test_visual_build_project_mode_output_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = ProjectManager()
    _saved_rhythm(manager)
    out_dir = tmp_path / "standalone"
    assert cli_main(["visual-build", PROJECT_ID, "--output-dir", str(out_dir)]) == 0
    assert (out_dir / RECIPE_FILENAME).is_file()
    # save_project already placed the canonical copies in the project dir.
    assert (manager.get_project_dir(PROJECT_ID) / RECIPE_FILENAME).is_file()


def test_visual_build_reports_legacy_mode(tmp_path, capsys):
    source = tmp_path / "legacy.rhythm.json"
    rhythm = build_rhythm(families=("A",))
    rhythm["patterns"].pop("segments")
    rhythm["patterns"].pop("boundaries")
    source.write_text(json.dumps(rhythm), encoding="utf-8")
    assert cli_main(["visual-build", str(source)]) == 0
    captured = capsys.readouterr().out
    assert "mode: legacy" in captured
    assert "warning: no patterns.segments" in captured


def test_visual_build_rejects_bad_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    missing = tmp_path / "missing.rhythm.json"
    assert cli_main(["visual-build", str(missing)]) == 1

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert cli_main(["visual-build", str(broken)]) == 1

    invalid = tmp_path / "invalid.rhythm.json"
    rhythm = build_rhythm()
    rhythm["schema_version"] = "3.0"
    invalid.write_text(json.dumps(rhythm), encoding="utf-8")
    assert cli_main(["visual-build", str(invalid)]) == 1

    # A 12-hex ID without a cached project fails cleanly; a path-looking
    # argument never reaches the project cache.
    assert cli_main(["visual-build", "0" * 12]) == 1
    assert not (tmp_path / ".beatscope-cache" / "projects" / "missing.rhyt").exists()
