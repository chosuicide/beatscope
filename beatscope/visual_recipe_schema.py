"""Schema validation for the v0.8 visual orchestration artifacts.

Two canonical artifacts hang off a validated Rhythm IR project:
``visual-recipe.json`` (stable family identities and design tokens) and
``visual-timeline.json`` (those identities instantiated on the real song
timeline). Both are presentation metadata, never audio-analysis facts, so
they live outside Rhythm IR v4 and carry their own schema identifiers.

Validation is the contract gate between the compiler, the persistence
layer, the web API, MCP, and the exporter:

* compilation bugs raise ``InvalidVisualRecipe`` before anything is written;
* existing artifacts stay untouched on failed regeneration;
* the frozen tables in this module (motif bank, driver order, treatment
  mapping, variant and motion bounds) are shared verbatim by the compiler,
  the JavaScript scene director, and the visual benchmark.

Every error message names the offending JSON path so a failure is
actionable without reading the validator.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from .schema import FORBIDDEN_V4_KEYS, _finite_number, validate_rhythm_v4

RECIPE_SCHEMA = "beatscope-visual-recipe-1"
TIMELINE_SCHEMA = "beatscope-visual-timeline-1"
SUPPORTED_RECIPE_VERSIONS = ("0.8.0",)
RECIPE_VERSION = "0.8.0"

MOTIF_BANK_VERSION = "motif-bank-1"
MOTIF_BANK = ("compact-triad", "open-triad", "axial-flow", "orbital-weave")
BREAK_FAMILY = "BREAK"
BREAK_MOTIF = "suspended-void"
LEGACY_FAMILY = "LEGACY"
LEGACY_MOTIF = "compact-triad"
VALID_MOTIFS = frozenset(MOTIF_BANK) | {BREAK_MOTIF}

PALETTE_KEYS = ("paper", "ink", "accent", "warm")
TRANSITION_TOKEN_KEYS = ("lead_beats", "settle_beats", "max_lead_seconds", "max_settle_seconds")
MOTION_TOKEN_KEYS = ("max_scene_spread", "max_scene_twist", "max_palette_mix")

COMPOSITION_KEYS = ("spread", "twist", "flow", "orbit", "void", "contrast")

# Frozen motion hard limits (v0.8 plan sections 5/7/10). Artifacts must not
# exceed them; the runtime may additionally scale them down.
HARD_LIMITS = {
    "max_scene_spread": 0.32,
    "max_scene_twist": 0.28,
    "max_palette_mix": 0.42,
    "max_lead_seconds": 0.8,
    "max_settle_seconds": 0.9,
}

PALETTE_SLOT_MIN = 0
PALETTE_SLOT_MAX = len(MOTIF_BANK) - 1

# Frozen driver -> treatment selection (v0.8 plan section 6.7). The driver
# is the strongest stored boundary driver with deterministic tie-breaking;
# it selects a visual treatment, never an emotion.
DRIVER_ORDER = ("harmony", "rhythm", "energy", "timbre")
DRIVERS = frozenset(DRIVER_ORDER) | {"neutral"}
TREATMENT_BY_DRIVER = {
    "harmony": "phase-turn",
    "rhythm": "radial-part",
    "energy": "aperture",
    "timbre": "flow-shear",
    "neutral": "cross-settle",
}
TREATMENTS = frozenset(TREATMENT_BY_DRIVER.values())

# Variant deltas (v0.8 plan section 6.6): a variant changes exactly one
# primary and one secondary composition property, by a bounded magnitude,
# and stays within the aggregate Euclidean distance from the family base.
VARIANT_PRIMARY = ("twist", "flow", "orbit")
VARIANT_SECONDARY = ("spread", "void", "contrast")
VARIANT_DELTA_MIN = 0.04
VARIANT_DELTA_MAX = 0.16
VARIANT_DISTANCE_MAX = 0.22

LEAD_RANGE = (0.25, 0.8)
SETTLE_RANGE = (0.35, 0.9)

# Scene and transition identifiers are deterministic and positional.
SCENE_ID_TEMPLATE = "scene-{position:03d}"
TRANSITION_ID_TEMPLATE = "transition-{position:03d}"

MODES = ("structure", "legacy")

_TIME_EPSILON = 1e-3
_DURATION_EPSILON = 1e-6
_ZERO_EPSILON = 1e-9

_PROJECT_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")

# Visual artifacts additionally ban emotion and musical-role fields: the
# driver selects a visual treatment, never a feeling or a function.
FORBIDDEN_VISUAL_KEYS = FORBIDDEN_V4_KEYS + ("emotion", "mood", "feeling", "instrument", "role")


def _find_forbidden_visual_keys(value: Any, path: str, errors: list[str]) -> None:
    """Recursively collect forbidden dict keys; lists of scalars are skipped."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_VISUAL_KEYS:
                errors.append(f"{path}.{key}: '{key}' is not allowed in visual artifacts")
            _find_forbidden_visual_keys(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, (dict, list)):
                _find_forbidden_visual_keys(item, f"{path}[{index}]", errors)


class InvalidVisualRecipe(ValueError):
    """Raised when visual artifacts fail validation, before anything is written."""


def dominant_driver(drivers: dict[str, Any] | None) -> str:
    """Strongest stored boundary driver with deterministic tie-breaking.

    Ties resolve by the frozen ``DRIVER_ORDER``; unknown or absent drivers
    fall back to ``"neutral"``. Only values greater than zero can win, so an
    all-zero or missing driver map stays neutral.
    """
    if not isinstance(drivers, dict):
        return "neutral"
    best_name, best_value = "neutral", 0.0
    for name in DRIVER_ORDER:
        value = drivers.get(name)
        if not _finite_number(value) or value <= 0.0:
            continue
        if value > best_value or (value == best_value and best_name == "neutral"):
            best_name, best_value = name, float(value)
    return best_name


def treatment_for_driver(driver: str) -> str:
    """Frozen driver -> treatment mapping (plan section 6.7)."""
    return TREATMENT_BY_DRIVER.get(driver, TREATMENT_BY_DRIVER["neutral"])


def variant_distance(variant_delta: dict[str, Any]) -> float:
    """Euclidean norm of the six-dimensional variant delta."""
    return math.sqrt(sum(float(variant_delta.get(key, 0.0)) ** 2 for key in COMPOSITION_KEYS))


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    """Deterministic UTF-8/LF JSON form used for the source Rhythm digest."""
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def rhythm_source_sha256(rhythm: dict[str, Any]) -> str:
    """Canonical SHA-256 of the Rhythm IR a visual artifact was compiled from."""
    return hashlib.sha256(_canonical_json_bytes(rhythm)).hexdigest()


def _walk_numbers(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _walk_numbers(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_numbers(item, f"{path}[{index}]", errors)
    elif isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path} must be finite")


def _require_object(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return False
    return True


def _require_keys(container: dict[str, Any], keys: tuple[str, ...], path: str, errors: list[str]) -> None:
    for key in keys:
        if key not in container:
            errors.append(f"{path} is missing '{key}'")


def _validate_tokens(tokens: Any, errors: list[str]) -> None:
    if not _require_object(tokens, "$.tokens", errors):
        return
    palette = tokens.get("palette")
    if _require_object(palette, "$.tokens.palette", errors):
        _require_keys(palette, PALETTE_KEYS, "$.tokens.palette", errors)
        for key in PALETTE_KEYS:
            color = palette.get(key)
            if color is None:
                continue
            if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
                errors.append(f"$.tokens.palette.{key} {color!r} must be a lowercase six-digit hex color")
    transition = tokens.get("transition")
    if _require_object(transition, "$.tokens.transition", errors):
        _require_keys(transition, TRANSITION_TOKEN_KEYS, "$.tokens.transition", errors)
        for key in ("lead_beats", "settle_beats"):
            value = transition.get(key)
            if value is None:
                continue
            if not _finite_number(value) or value <= 0.0:
                errors.append(f"$.tokens.transition.{key} must be a positive finite number")
        for key, limit in (("max_lead_seconds", HARD_LIMITS["max_lead_seconds"]),
                           ("max_settle_seconds", HARD_LIMITS["max_settle_seconds"])):
            value = transition.get(key)
            if value is None:
                continue
            if not _finite_number(value) or not 0.0 < float(value) <= limit:
                errors.append(f"$.tokens.transition.{key} must be a positive number <= {limit}")
    motion = tokens.get("motion")
    if _require_object(motion, "$.tokens.motion", errors):
        _require_keys(motion, MOTION_TOKEN_KEYS, "$.tokens.motion", errors)
        for key in MOTION_TOKEN_KEYS:
            value = motion.get(key)
            if value is None:
                continue
            limit = HARD_LIMITS[key]
            if not _finite_number(value) or not 0.0 < float(value) <= limit:
                errors.append(f"$.tokens.motion.{key} must be a positive number <= {limit}")


def _validate_family_entry(family: str, entry: Any, errors: list[str]) -> None:
    path = f"$.families.{family}"
    if not _require_object(entry, path, errors):
        return
    motif = entry.get("motif")
    if family == BREAK_FAMILY:
        if motif != BREAK_MOTIF:
            errors.append(f"{path}.motif must be the reserved '{BREAK_MOTIF}' for the BREAK family")
    elif family == LEGACY_FAMILY:
        if motif != LEGACY_MOTIF:
            errors.append(f"{path}.motif must be '{LEGACY_MOTIF}' for the LEGACY family")
    elif motif not in MOTIF_BANK:
        errors.append(f"{path}.motif {motif!r} must be one of {', '.join(MOTIF_BANK)}")
    if motif == BREAK_MOTIF and family != BREAK_FAMILY:
        errors.append(f"{path}.motif '{BREAK_MOTIF}' is reserved for the BREAK family")

    slot = entry.get("palette_slot")
    if not isinstance(slot, int) or isinstance(slot, bool) or not PALETTE_SLOT_MIN <= slot <= PALETTE_SLOT_MAX:
        errors.append(f"{path}.palette_slot must be an integer in {PALETTE_SLOT_MIN}..{PALETTE_SLOT_MAX}")

    composition = entry.get("composition")
    if _require_object(composition, f"{path}.composition", errors):
        _require_keys(composition, COMPOSITION_KEYS, f"{path}.composition", errors)
        for key in COMPOSITION_KEYS:
            value = composition.get(key)
            if value is None:
                continue
            if not _finite_number(value) or not 0.0 <= float(value) <= 1.0:
                errors.append(f"{path}.composition.{key} must be a number in 0..1")


def validate_visual_recipe(recipe: dict[str, Any]) -> list[str]:
    """Validate one visual recipe dictionary; returns actionable error paths."""
    errors: list[str] = []
    if not _require_object(recipe, "$", errors):
        return errors
    _find_forbidden_visual_keys(recipe, "$", errors)

    if recipe.get("schema") != RECIPE_SCHEMA:
        errors.append(f"$.schema must be '{RECIPE_SCHEMA}', got {recipe.get('schema')!r}")
    if recipe.get("recipe_version") not in SUPPORTED_RECIPE_VERSIONS:
        errors.append(
            f"$.recipe_version must be one of {', '.join(SUPPORTED_RECIPE_VERSIONS)}, "
            f"got {recipe.get('recipe_version')!r}"
        )
    project_id = recipe.get("project_id")
    if not isinstance(project_id, str) or not _PROJECT_ID_RE.match(project_id):
        errors.append("$.project_id must be 12 lowercase hex characters")
    if not isinstance(recipe.get("source_rhythm_sha256"), str) or not _SHA256_RE.match(
        recipe.get("source_rhythm_sha256") or ""
    ):
        errors.append("$.source_rhythm_sha256 must be a lowercase SHA-256 hex digest")
    if not isinstance(recipe.get("seed"), str) or not recipe["seed"]:
        errors.append("$.seed must be a non-empty string")
    if recipe.get("mode") not in MODES:
        errors.append(f"$.mode must be one of {', '.join(MODES)}, got {recipe.get('mode')!r}")

    _validate_tokens(recipe.get("tokens"), errors)

    families = recipe.get("families")
    if _require_object(families, "$.families", errors):
        if not families:
            errors.append("$.families must not be empty")
        mode = recipe.get("mode")
        if mode == "legacy" and set(families) != {LEGACY_FAMILY}:
            errors.append(f"legacy mode recipes must declare only the '{LEGACY_FAMILY}' family")
        if mode == "structure" and LEGACY_FAMILY in families:
            errors.append(f"structure mode recipes must not declare the '{LEGACY_FAMILY}' family")
        for family in families:
            _validate_family_entry(family, families[family], errors)

    diagnostics = recipe.get("diagnostics")
    if _require_object(diagnostics, "$.diagnostics", errors):
        _require_keys(diagnostics, ("family_count", "motif_bank_version", "warnings"), "$.diagnostics", errors)
        if isinstance(diagnostics.get("family_count"), int) and isinstance(families, dict):
            if diagnostics["family_count"] != len(families):
                errors.append(
                    f"$.diagnostics.family_count {diagnostics['family_count']} must equal "
                    f"the {len(families)} declared families"
                )
        if "motif_bank_version" in diagnostics and diagnostics["motif_bank_version"] != MOTIF_BANK_VERSION:
            errors.append(f"$.diagnostics.motif_bank_version must be '{MOTIF_BANK_VERSION}'")
        if "warnings" in diagnostics and not isinstance(diagnostics["warnings"], list):
            errors.append("$.diagnostics.warnings must be a list")

    _walk_numbers(recipe, "$", errors)
    return errors


def _structural_families(rhythm: dict[str, Any]) -> list[str]:
    """First-occurrence family order in the Rhythm IR segments."""
    families: list[str] = []
    segments = (rhythm.get("patterns") or {}).get("segments") or []
    for segment in segments:
        family = segment.get("family") if isinstance(segment, dict) else None
        if isinstance(family, str) and family and family not in families:
            families.append(family)
    return families


def _validate_variant_delta(
    family: str,
    variant: int,
    delta: Any,
    base: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    if not _require_object(delta, path, errors):
        return
    _require_keys(delta, COMPOSITION_KEYS, path, errors)
    changed = [key for key in COMPOSITION_KEYS if _finite_number(delta.get(key)) and abs(float(delta[key])) > _ZERO_EPSILON]
    if variant == 0:
        if changed:
            errors.append(f"{path} must be all zeros for variant 0")
        return
    primary_changed = [key for key in changed if key in VARIANT_PRIMARY]
    secondary_changed = [key for key in changed if key in VARIANT_SECONDARY]
    if len(changed) != 2 or len(primary_changed) != 1 or len(secondary_changed) != 1:
        errors.append(
            f"{path} must change exactly one of {', '.join(VARIANT_PRIMARY)} and exactly one of "
            f"{', '.join(VARIANT_SECONDARY)}; changed {sorted(changed)}"
        )
    for key in changed:
        magnitude = abs(float(delta[key]))
        if not VARIANT_DELTA_MIN <= magnitude <= VARIANT_DELTA_MAX:
            errors.append(
                f"{path}.{key} magnitude {magnitude:.4f} must be within "
                f"{VARIANT_DELTA_MIN}..{VARIANT_DELTA_MAX}"
            )
        final = float(base.get(key, 0.0)) + float(delta[key])
        if not 0.0 <= final <= 1.0:
            errors.append(f"{path}.{key} pushes {key} out of 0..1 (final {final:.4f})")
    distance = variant_distance({key: float(delta.get(key, 0.0) or 0.0) for key in COMPOSITION_KEYS})
    if distance > VARIANT_DISTANCE_MAX:
        errors.append(f"{path} aggregate distance {distance:.4f} exceeds {VARIANT_DISTANCE_MAX}")


def validate_visual_timeline(
    timeline: dict[str, Any],
    rhythm: dict[str, Any],
    recipe: dict[str, Any],
) -> list[str]:
    """Validate a timeline against its Rhythm IR and recipe; actionable paths."""
    errors: list[str] = []
    if not _require_object(timeline, "$", errors):
        return errors
    _find_forbidden_visual_keys(timeline, "$", errors)

    if timeline.get("schema") != TIMELINE_SCHEMA:
        errors.append(f"$.schema must be '{TIMELINE_SCHEMA}', got {timeline.get('schema')!r}")
    if timeline.get("recipe_version") not in SUPPORTED_RECIPE_VERSIONS:
        errors.append(
            f"$.recipe_version must be one of {', '.join(SUPPORTED_RECIPE_VERSIONS)}, "
            f"got {timeline.get('recipe_version')!r}"
        )

    recipe_project = recipe.get("project_id") if isinstance(recipe, dict) else None
    rhythm_project = rhythm.get("project_id") if isinstance(rhythm, dict) else None
    timeline_project = timeline.get("project_id")
    if recipe_project is not None and timeline_project != recipe_project:
        errors.append(f"$.project_id {timeline_project!r} does not match the recipe project {recipe_project!r}")
    if rhythm_project is not None and timeline_project != rhythm_project:
        errors.append(f"$.project_id {timeline_project!r} does not match the Rhythm IR project {rhythm_project!r}")

    mode = recipe.get("mode") if isinstance(recipe, dict) else None
    duration = (rhythm.get("source") or {}).get("duration") if isinstance(rhythm.get("source"), dict) else None
    timeline_duration = timeline.get("duration")
    if not _finite_number(timeline_duration) or timeline_duration < 0:
        errors.append("$.duration must be a non-negative finite number")
        timeline_duration = None
    elif _finite_number(duration) and abs(float(timeline_duration) - float(duration)) > _DURATION_EPSILON:
        errors.append(
            f"$.duration {timeline_duration} must equal the Rhythm IR duration {duration}"
        )

    segments = (rhythm.get("patterns") or {}).get("segments") if isinstance(rhythm, dict) else None
    has_segments = isinstance(segments, list) and bool(segments)
    families_declared = recipe.get("families") if isinstance(recipe.get("families"), dict) else {}
    if mode == "structure":
        if not has_segments:
            errors.append("recipe mode 'structure' requires Rhythm IR patterns.segments")
        structural = _structural_families(rhythm) if has_segments else []
        if set(families_declared) != set(structural):
            errors.append(
                "$.families must exactly match the structural families "
                f"{sorted(structural)}, got {sorted(families_declared)}"
            )
    elif mode == "legacy" and has_segments:
        errors.append("recipe mode 'legacy' is only valid for Rhythm IR without patterns.segments")

    scenes = timeline.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        errors.append("$.scenes must be a non-empty list")
        scenes = []
    else:
        expected_count = 1 if mode == "legacy" else len(segments or [])
        if len(scenes) != expected_count:
            errors.append(
                f"$.scenes must hold {expected_count} scene(s) for this project, got {len(scenes)}"
            )

    previous_end: float | None = None
    seen_variant_deltas: dict[tuple[str, int], dict[str, Any]] = {}
    for position, scene in enumerate(scenes):
        path = f"$.scenes[{position}]"
        if not _require_object(scene, path, errors):
            continue
        expected_id = SCENE_ID_TEMPLATE.format(position=position + 1)
        if scene.get("id") != expected_id:
            errors.append(f"{path}.id must be '{expected_id}'")
        family = scene.get("family")
        if not isinstance(family, str) or not family:
            errors.append(f"{path}.family must be a non-empty string")
        elif family not in families_declared:
            errors.append(f"{path}.family {family!r} is not declared in the recipe families")
        else:
            family_entry = families_declared[family]
            if isinstance(family_entry, dict) and scene.get("motif") != family_entry.get("motif"):
                errors.append(
                    f"{path}.motif must copy the family motif "
                    f"'{family_entry.get('motif')}', got {scene.get('motif')!r}"
                )

        start_time = scene.get("start_time")
        end_time = scene.get("end_time")
        for key, value in (("start_time", start_time), ("end_time", end_time)):
            if not _finite_number(value) or value < 0:
                errors.append(f"{path}.{key} must be a non-negative finite number")
        if _finite_number(start_time) and _finite_number(end_time) and end_time <= start_time:
            errors.append(f"{path} times must increase")
        if position == 0 and _finite_number(start_time) and abs(float(start_time)) > _DURATION_EPSILON:
            errors.append("$.scenes[0].start_time must be 0")
        if previous_end is not None and _finite_number(start_time) and abs(float(start_time) - previous_end) > _DURATION_EPSILON:
            errors.append(f"{path}.start_time must continue the previous scene exactly")
        previous_end = float(end_time) if _finite_number(end_time) else None

        variant = scene.get("variant")
        if not isinstance(variant, int) or isinstance(variant, bool) or variant < 0:
            errors.append(f"{path}.variant must be a non-negative integer")
            variant = None

        if mode == "legacy":
            if family != LEGACY_FAMILY:
                errors.append(f"{path}.family must be '{LEGACY_FAMILY}' in legacy mode")
            if scene.get("segment_id") is not None:
                errors.append(f"{path}.segment_id must be null in legacy mode")
            if scene.get("segment_index") != 0:
                errors.append(f"{path}.segment_index must be 0 in legacy mode")
            if scene.get("label") != LEGACY_FAMILY:
                errors.append(f"{path}.label must be '{LEGACY_FAMILY}' in legacy mode")
        else:
            segment_index = position
            if scene.get("segment_index") != segment_index:
                errors.append(f"{path}.segment_index must equal its position {segment_index}")
            source_segment = (segments or [])[segment_index] if segment_index < len(segments or []) else None
            if isinstance(source_segment, dict):
                if scene.get("segment_id") != source_segment.get("id"):
                    errors.append(
                        f"{path}.segment_id must reference '{source_segment.get('id')}', "
                        f"got {scene.get('segment_id')!r}"
                    )
                if family is not None and family != source_segment.get("family"):
                    errors.append(
                        f"{path}.family must copy the segment family "
                        f"'{source_segment.get('family')}', got {family!r}"
                    )
                if variant is not None and variant != source_segment.get("variant"):
                    errors.append(
                        f"{path}.variant must copy the segment variant "
                        f"{source_segment.get('variant')}, got {variant!r}"
                    )
                expected_label = source_segment.get("display_label")
                if scene.get("label") != expected_label:
                    errors.append(
                        f"{path}.label must copy the segment display label "
                        f"'{expected_label}', got {scene.get('label')!r}"
                    )

        if position == len(scenes) - 1:
            if _finite_number(end_time) and _finite_number(timeline_duration) and abs(
                float(end_time) - float(timeline_duration)
            ) > _DURATION_EPSILON:
                errors.append(f"{path}.end_time must equal the timeline duration")

        if isinstance(families_declared.get(family), dict):
            base = families_declared[family].get("composition")
            if isinstance(base, dict):
                delta_path = f"{path}.variant_delta"
                delta = scene.get("variant_delta")
                if isinstance(delta, dict):
                    if variant is not None:
                        key = (family, variant)
                        if key in seen_variant_deltas:
                            if seen_variant_deltas[key] != delta:
                                errors.append(
                                    f"{path}.variant_delta must be identical for every "
                                    f"({family}, variant {variant}) scene"
                                )
                        else:
                            seen_variant_deltas[key] = delta
                _validate_variant_delta(family, variant if variant is not None else 0, delta, base, delta_path, errors)

    transitions = timeline.get("transitions")
    if not isinstance(transitions, list):
        errors.append("$.transitions must be a list")
        transitions = []
    expected_transitions = max(0, len(scenes) - 1)
    if len(transitions) != expected_transitions:
        errors.append(
            f"$.transitions must hold exactly {expected_transitions} transition(s) "
            f"for {len(scenes)} scene(s), got {len(transitions)}"
        )

    boundaries = (rhythm.get("patterns") or {}).get("boundaries") or []
    boundaries_by_bar: dict[int, dict[str, Any]] = {}
    if isinstance(boundaries, list):
        for boundary in boundaries:
            if isinstance(boundary, dict) and isinstance(boundary.get("bar"), int):
                boundaries_by_bar[boundary["bar"]] = boundary

    transition_tokens = (recipe.get("tokens") or {}).get("transition") or {}
    max_lead = transition_tokens.get("max_lead_seconds")
    max_settle = transition_tokens.get("max_settle_seconds")
    for position, transition in enumerate(transitions):
        path = f"$.transitions[{position}]"
        if not _require_object(transition, path, errors):
            continue
        expected_id = TRANSITION_ID_TEMPLATE.format(position=position + 1)
        if transition.get("id") != expected_id:
            errors.append(f"{path}.id must be '{expected_id}'")
        if position < len(scenes) - 1:
            from_scene = scenes[position].get("id") if isinstance(scenes[position], dict) else None
            to_scene = scenes[position + 1].get("id") if isinstance(scenes[position + 1], dict) else None
            if transition.get("from_scene") != from_scene:
                errors.append(f"{path}.from_scene must be '{from_scene}', got {transition.get('from_scene')!r}")
            if transition.get("to_scene") != to_scene:
                errors.append(f"{path}.to_scene must be '{to_scene}', got {transition.get('to_scene')!r}")

        boundary_bar = transition.get("boundary_bar")
        boundary = boundaries_by_bar.get(boundary_bar) if isinstance(boundary_bar, int) else None
        if boundary is None:
            errors.append(f"{path}.boundary_bar {boundary_bar!r} must reference exactly one stored Rhythm IR boundary")
        else:
            expected_segment = (segments or [])[position + 1] if position + 1 < len(segments or []) else None
            if isinstance(expected_segment, dict) and expected_segment.get("start_bar") != boundary_bar:
                errors.append(
                    f"{path}.boundary_bar {boundary_bar} must equal the next scene's segment start bar "
                    f"{expected_segment.get('start_bar')}"
                )
            time = transition.get("time")
            if not _finite_number(time):
                errors.append(f"{path}.time must be a finite number")
            else:
                if abs(float(time) - float(boundary.get("time", 0.0))) > _TIME_EPSILON:
                    errors.append(
                        f"{path}.time {time} must equal the boundary time {boundary.get('time')}"
                    )
                to_start = scenes[position + 1].get("start_time") if position + 1 < len(scenes) else None
                if _finite_number(to_start) and abs(float(time) - float(to_start)) > _TIME_EPSILON:
                    errors.append(f"{path}.time must equal the next scene's start_time {to_start}")
            strength = transition.get("strength")
            if not _finite_number(strength) or not 0.0 <= float(strength) <= 1.0:
                errors.append(f"{path}.strength must be a number in 0..1")
            elif _finite_number(boundary.get("novelty")) and abs(
                float(strength) - float(boundary["novelty"])
            ) > _TIME_EPSILON:
                errors.append(
                    f"{path}.strength must copy the boundary novelty {boundary.get('novelty')}"
                )
            driver = transition.get("driver")
            expected_driver = dominant_driver(boundary.get("drivers"))
            if driver not in DRIVERS:
                errors.append(f"{path}.driver {driver!r} must be one of {', '.join(sorted(DRIVERS))}")
            elif driver != expected_driver:
                errors.append(
                    f"{path}.driver must be the dominant stored driver '{expected_driver}', got {driver!r}"
                )
            treatment = transition.get("treatment")
            expected_treatment = treatment_for_driver(driver if driver in DRIVERS else "neutral")
            if treatment not in TREATMENTS:
                errors.append(f"{path}.treatment {treatment!r} must be one of {', '.join(sorted(TREATMENTS))}")
            elif treatment != expected_treatment:
                errors.append(
                    f"{path}.treatment must be '{expected_treatment}' for driver '{driver}', got {treatment!r}"
                )

        for key, bounds in (("lead_seconds", LEAD_RANGE), ("settle_seconds", SETTLE_RANGE)):
            value = transition.get(key)
            if not _finite_number(value):
                errors.append(f"{path}.{key} must be a finite number")
                continue
            low, high = bounds
            if not low <= float(value) <= high:
                errors.append(f"{path}.{key} {value} must be within {low}..{high}")
            token_limit = max_lead if key == "lead_seconds" else max_settle
            if _finite_number(token_limit) and float(value) > float(token_limit):
                errors.append(f"{path}.{key} {value} exceeds the recipe token {token_limit}")

    diagnostics = timeline.get("diagnostics")
    if _require_object(diagnostics, "$.diagnostics", errors):
        if "scene_count" in diagnostics and diagnostics["scene_count"] != len(scenes):
            errors.append(
                f"$.diagnostics.scene_count {diagnostics['scene_count']} must equal the {len(scenes)} scenes"
            )
        if "transition_count" in diagnostics and diagnostics["transition_count"] != len(transitions):
            errors.append(
                f"$.diagnostics.transition_count {diagnostics['transition_count']} must equal "
                f"the {len(transitions)} transitions"
            )
        if "warnings" in diagnostics and not isinstance(diagnostics["warnings"], list):
            errors.append("$.diagnostics.warnings must be a list")

    _walk_numbers(timeline, "$", errors)
    return errors


def require_valid_visual_artifacts(
    rhythm: dict[str, Any],
    recipe: dict[str, Any],
    timeline: dict[str, Any] | None = None,
) -> None:
    """Validate everything cross-artifact; raise ``InvalidVisualRecipe`` on failure.

    Callers persist, serve, or package visual artifacts only after this
    passes, so present-but-invalid artifacts can never reach a consumer.
    """
    errors: list[str] = [f"rhythm: {message}" for message in validate_rhythm_v4(rhythm)]
    errors.extend(f"recipe: {message}" for message in validate_visual_recipe(recipe))
    if timeline is not None:
        errors.extend(f"timeline: {message}" for message in validate_visual_timeline(timeline, rhythm, recipe))

    expected_sha = rhythm_source_sha256(rhythm)
    if isinstance(recipe, dict) and recipe.get("source_rhythm_sha256") != expected_sha:
        errors.append(
            "recipe: source_rhythm_sha256 does not match the canonical Rhythm IR digest "
            f"{expected_sha}"
        )

    if errors:
        raise InvalidVisualRecipe(
            "invalid visual artifacts:\n" + "\n".join(f"- {message}" for message in errors)
        )
