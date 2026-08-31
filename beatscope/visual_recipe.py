"""Deterministic v0.8 visual recipe and scene timeline compiler.

Pure functions over a validated Rhythm IR dictionary (plan section 6).  The
compiler turns the structural facts already stored in ``rhythm.json`` into
two presentation artifacts:

* ``visual-recipe.json`` — stable family identities (motif, palette slot,
  composition vector) plus frozen design tokens;
* ``visual-timeline.json`` — those identities instantiated on the real song
  timeline with transitions derived from stored boundaries.

Determinism rules enforced here:

* every hash is SHA-256 over UTF-8 text (never ``hash()``);
* family order is first occurrence order in ``patterns.segments``;
* motif selection uses the frozen bank with deterministic collision
  handling; ``BREAK`` always receives the reserved ``suspended-void`` motif;
* variant deltas are pure functions of ``(project_id, family, variant)``,
  so repeated occurrences compile to identical deltas;
* transition durations come from the real beats around each boundary, never
  from global BPM math;
* the same rhythm always compiles to byte-identical canonical JSON.

The compiler never reads audio, the filesystem, the clock, or the network;
it raises :class:`InvalidVisualRecipe` on malformed input before any caller
writes a file.
"""
from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left
from typing import Any

from .visual_recipe_schema import (
    BREAK_FAMILY,
    BREAK_MOTIF,
    COMPOSITION_KEYS,
    HARD_LIMITS,
    InvalidVisualRecipe,
    LEGACY_FAMILY,
    LEGACY_MOTIF,
    MOTIF_BANK,
    MOTIF_BANK_VERSION,
    PALETTE_SLOT_MAX,
    RECIPE_SCHEMA,
    RECIPE_VERSION,
    SCENE_ID_TEMPLATE,
    SETTLE_RANGE,
    LEAD_RANGE,
    TRANSITION_ID_TEMPLATE,
    VARIANT_DELTA_MAX,
    VARIANT_DELTA_MIN,
    VARIANT_DISTANCE_MAX,
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    TIMELINE_SCHEMA,
    dominant_driver,
    require_valid_visual_artifacts,
    rhythm_source_sha256,
    treatment_for_driver,
)

COMPILER_VERSION = "visual-recipe-compiler-1"

# Frozen design tokens (plan section 5.1).  Every compiled recipe shares
# them; the motion caps equal the hard limits validated by the schema.
DEFAULT_TOKENS = {
    "palette": {
        "paper": "#f4f1e9",
        "ink": "#171713",
        "accent": "#c65032",
        "warm": "#fff1ce",
    },
    "transition": {
        "lead_beats": 1.0,
        "settle_beats": 1.5,
        "max_lead_seconds": HARD_LIMITS["max_lead_seconds"],
        "max_settle_seconds": HARD_LIMITS["max_settle_seconds"],
    },
    "motion": {
        "max_scene_spread": HARD_LIMITS["max_scene_spread"],
        "max_scene_twist": HARD_LIMITS["max_scene_twist"],
        "max_palette_mix": HARD_LIMITS["max_palette_mix"],
    },
}

# Reviewed composition vectors, one per motif (plan section 6.4: "each motif
# is a complete, reviewed parameter vector").  The compiler never invents
# style values; it only selects among these presets.  Values are magnitudes
# in 0..1; the runtime derives signed directions from the recipe seed.
MOTIF_COMPOSITION_PRESETS = {
    "compact-triad": {
        "spread": 0.14,
        "twist": 0.08,
        "flow": 0.32,
        "orbit": 0.44,
        "void": 0.18,
        "contrast": 0.72,
    },
    "open-triad": {
        "spread": 0.3,
        "twist": 0.16,
        "flow": 0.24,
        "orbit": 0.52,
        "void": 0.22,
        "contrast": 0.66,
    },
    "axial-flow": {
        "spread": 0.2,
        "twist": 0.12,
        "flow": 0.56,
        "orbit": 0.3,
        "void": 0.24,
        "contrast": 0.7,
    },
    "orbital-weave": {
        "spread": 0.26,
        "twist": 0.1,
        "flow": 0.36,
        "orbit": 0.62,
        "void": 0.16,
        "contrast": 0.74,
    },
    "suspended-void": {
        "spread": 0.08,
        "twist": 0.04,
        "flow": 0.12,
        "orbit": 0.2,
        "void": 0.52,
        "contrast": 0.58,
    },
}

# v0.7 projects without structure keep neutral composition values.
LEGACY_COMPOSITION = {key: 0.0 for key in COMPOSITION_KEYS}

# No stored beats at all: fall back to a 120 BPM beat length for transition
# durations instead of failing an otherwise valid project.
_FALLBACK_BEAT_SECONDS = 0.5

_LEGACY_WARNING = (
    "no patterns.segments; visual recipe compiled in legacy mode "
    "with the neutral LEGACY family"
)


def stable_hash(text: str) -> int:
    """First 8 bytes of SHA-256 as a big-endian integer."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def stable_unit(text: str) -> float:
    """Deterministic unit interval derived from SHA-256 (plan section 6.5)."""
    return stable_hash(text) / ((1 << 64) - 1)


def _r6(value: float) -> float:
    """Round to the canonical 6-decimal artifact precision (never -0.0)."""
    return round(float(value), 6) + 0.0


def _structural_families(segments: list[dict[str, Any]]) -> list[str]:
    """First-occurrence family order (plan section 6.3)."""
    families: list[str] = []
    for segment in segments:
        family = segment.get("family")
        if isinstance(family, str) and family and family not in families:
            families.append(family)
    return families


def _required_segments(rhythm: dict[str, Any]) -> list[dict[str, Any]]:
    patterns = rhythm.get("patterns")
    segments = patterns.get("segments") if isinstance(patterns, dict) else None
    if segments is None:
        return []
    if not isinstance(segments, list):
        raise InvalidVisualRecipe("patterns.segments must be a list when present")
    for segment in segments:
        if not isinstance(segment, dict):
            raise InvalidVisualRecipe("patterns.segments must hold segment objects")
    return segments


def _segment_field(segment: dict[str, Any], key: str, position: int) -> Any:
    value = segment.get(key)
    if value is None:
        raise InvalidVisualRecipe(
            f"patterns.segments[{position}] is missing '{key}'; "
            "visual artifacts require complete structural segments"
        )
    return value


def _segment_number(segment: dict[str, Any], key: str, position: int) -> float:
    value = _segment_field(segment, key, position)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InvalidVisualRecipe(
            f"patterns.segments[{position}].{key} must be a finite number"
        )
    return float(value)


def _segment_text(segment: dict[str, Any], key: str, position: int) -> str:
    value = _segment_field(segment, key, position)
    if not isinstance(value, str) or not value:
        raise InvalidVisualRecipe(
            f"patterns.segments[{position}].{key} must be a non-empty string"
        )
    return value


def _segment_int(segment: dict[str, Any], key: str, position: int) -> int:
    value = _segment_field(segment, key, position)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidVisualRecipe(
            f"patterns.segments[{position}].{key} must be an integer"
        )
    return value


def _assign_identities(project_id: str, families: list[str]) -> dict[str, tuple[str, int]]:
    """Deterministic (motif, palette_slot) per family (plan sections 6.3/6.4).

    Normal families hash into the motif bank; while an unused motif remains
    the scan prefers it, so the first four normal families always cover all
    four motifs.  Once the bank is exhausted, later families reuse the
    hash-selected motif under a different palette slot.  ``BREAK`` stays
    outside the rotation with the reserved motif.
    """
    assignments: dict[str, tuple[str, int]] = {}
    used_motifs: set[str] = set()
    used_pairs: set[tuple[str, int]] = set()
    for position, family in enumerate(families):
        if family == BREAK_FAMILY:
            motif = BREAK_MOTIF
        else:
            preferred = stable_hash(f"{project_id}:{family}:{MOTIF_BANK_VERSION}") % len(MOTIF_BANK)
            motif_index = preferred
            if MOTIF_BANK[preferred] in used_motifs:
                for offset in range(1, len(MOTIF_BANK)):
                    candidate = MOTIF_BANK[(preferred + offset) % len(MOTIF_BANK)]
                    if candidate not in used_motifs:
                        motif_index = MOTIF_BANK.index(candidate)
                        break
            motif = MOTIF_BANK[motif_index]
        slot = position % (PALETTE_SLOT_MAX + 1)
        for _ in range(PALETTE_SLOT_MAX + 1):
            if (motif, slot) not in used_pairs:
                break
            slot = (slot + 1) % (PALETTE_SLOT_MAX + 1)
        used_motifs.add(motif)
        used_pairs.add((motif, slot))
        assignments[family] = (motif, slot)
    return assignments


def _variant_delta(
    project_id: str,
    family: str,
    variant: int,
    base: dict[str, Any],
) -> dict[str, float]:
    """Pure per-(family, variant) delta (plan section 6.6).

    Changes exactly one primary (twist/flow/orbit) and one secondary
    (spread/void/contrast) property by a magnitude in 0.04..0.16, keeping
    the final value in 0..1 and the aggregate Euclidean distance within
    0.22 of the family base.
    """
    delta = {key: 0.0 for key in COMPOSITION_KEYS}
    if variant <= 0:
        return delta
    stem = f"{project_id}:{family}:{variant}"
    primary = VARIANT_PRIMARY[stable_hash(f"{stem}:primary") % len(VARIANT_PRIMARY)]
    secondary = VARIANT_SECONDARY[stable_hash(f"{stem}:secondary") % len(VARIANT_SECONDARY)]
    if primary == secondary:  # disjoint sets; kept as an invariant guard
        raise InvalidVisualRecipe("variant delta sets must stay disjoint")

    magnitude_primary = VARIANT_DELTA_MIN + stable_unit(
        f"{stem}:{primary}-magnitude"
    ) * (VARIANT_DELTA_MAX - VARIANT_DELTA_MIN)
    magnitude_primary = _r6(magnitude_primary)
    # Keep sqrt(primary^2 + secondary^2) within the aggregate cap even after
    # the 6-decimal rounding of the secondary magnitude.
    secondary_cap = min(
        VARIANT_DELTA_MAX,
        math.sqrt(max(VARIANT_DISTANCE_MAX ** 2 - magnitude_primary ** 2, 0.0)) - 1e-6,
    )
    magnitude_secondary = VARIANT_DELTA_MIN + stable_unit(
        f"{stem}:{secondary}-magnitude"
    ) * (secondary_cap - VARIANT_DELTA_MIN)
    magnitude_secondary = _r6(magnitude_secondary)

    for key, magnitude in ((primary, magnitude_primary), (secondary, magnitude_secondary)):
        value = float(base.get(key, 0.0))
        sign = 1.0 if stable_unit(f"{stem}:{key}-sign") < 0.5 else -1.0
        if not 0.0 <= value + sign * magnitude <= 1.0:
            sign = -sign
        if not 0.0 <= value + sign * magnitude <= 1.0:
            raise InvalidVisualRecipe(
                f"variant delta for ({family}, variant {variant}) cannot keep "
                f"'{key}' within 0..1"
            )
        delta[key] = _r6(sign * magnitude)
    return delta


def _source_duration(rhythm: dict[str, Any]) -> float:
    source = rhythm.get("source")
    duration = source.get("duration") if isinstance(source, dict) else None
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
        raise InvalidVisualRecipe("source.duration must be a non-negative finite number")
    return float(duration)


def _beat_times(rhythm: dict[str, Any]) -> list[float]:
    beats = rhythm.get("beats")
    times: list[float] = []
    if isinstance(beats, list):
        for beat in beats:
            time = beat.get("time") if isinstance(beat, dict) else None
            if isinstance(time, (int, float)) and not isinstance(time, bool) and math.isfinite(time):
                times.append(float(time))
    return times


def _adjacent_beat_intervals(times: list[float], boundary_time: float) -> list[float]:
    """The two inter-beat intervals adjacent to ``boundary_time``.

    The previous interval spans the last two beats before the boundary; the
    next interval spans the first two beats at or after it.  A beat exactly
    on the boundary belongs to the "next" side.
    """
    next_index = bisect_left(times, boundary_time)
    previous_index = next_index - 1
    intervals: list[float] = []
    if previous_index >= 1:
        intervals.append(times[previous_index] - times[previous_index - 1])
    if 0 <= next_index < len(times) - 1:
        intervals.append(times[next_index + 1] - times[next_index])
    return [interval for interval in intervals if interval > 1e-9]


def _all_beat_intervals(times: list[float]) -> list[float]:
    return [
        times[index] - times[index - 1]
        for index in range(1, len(times))
        if times[index] - times[index - 1] > 1e-9
    ]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _local_beat_seconds(rhythm: dict[str, Any], boundary_time: float) -> float:
    times = _beat_times(rhythm)
    intervals = _adjacent_beat_intervals(times, boundary_time) or _all_beat_intervals(times)
    if intervals:
        return _median(intervals)
    tempo = rhythm.get("tempo")
    bpm = tempo.get("global_bpm") if isinstance(tempo, dict) else None
    if isinstance(bpm, (int, float)) and not isinstance(bpm, bool) and bpm > 0:
        return 60.0 / float(bpm)
    return _FALLBACK_BEAT_SECONDS


def _transition_durations(
    rhythm: dict[str, Any],
    boundary_time: float,
    previous_boundary_time: float | None,
    next_boundary_time: float | None,
    duration: float,
) -> tuple[float, float]:
    """Real-beat lead/settle with gap clamping (plan section 6.8)."""
    local_beat = _local_beat_seconds(rhythm, boundary_time)
    lead = min(max(1.0 * local_beat, LEAD_RANGE[0]), LEAD_RANGE[1])
    settle = min(max(1.5 * local_beat, SETTLE_RANGE[0]), SETTLE_RANGE[1])

    available_lead = boundary_time - (previous_boundary_time if previous_boundary_time is not None else 0.0)
    if available_lead < lead:
        lead = available_lead / 2.0
    available_settle = (next_boundary_time if next_boundary_time is not None else duration) - boundary_time
    if settle > available_settle:
        settle = available_settle / 2.0
    return _r6(max(lead, 0.0)), _r6(max(settle, 0.0))


def visual_artifact_fingerprint(rhythm: dict[str, Any]) -> str:
    """Deterministic identity of the compiled visual artifacts.

    Covers the project id, the canonical Rhythm IR digest, the visual recipe
    schema and version, the motif bank version, and the compiler version.
    Any change regenerates the artifacts; paths, timestamps, machine and
    browser information, and random values never enter the digest.
    """
    payload = {
        "project_id": rhythm.get("project_id") if isinstance(rhythm, dict) else None,
        "rhythm_sha256": rhythm_source_sha256(rhythm),
        "recipe_schema": RECIPE_SCHEMA,
        "recipe_version": RECIPE_VERSION,
        "motif_bank_version": MOTIF_BANK_VERSION,
        "compiler_version": COMPILER_VERSION,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compile_visual_recipe(rhythm: dict[str, Any]) -> dict[str, Any]:
    """Compile the visual recipe for a Rhythm IR dictionary (plan section 6)."""
    if not isinstance(rhythm, dict):
        raise InvalidVisualRecipe("rhythm must be a dictionary")
    project_id = rhythm.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise InvalidVisualRecipe("rhythm project_id must be a non-empty string")

    segments = _required_segments(rhythm)
    legacy = not segments
    if legacy:
        families = [LEGACY_FAMILY]
    else:
        families = _structural_families(segments)
        if not families:
            raise InvalidVisualRecipe(
                "patterns.segments must provide at least one valid family; "
                "malformed structure must not downgrade to legacy mode"
            )

    identities = _assign_identities(project_id, families)
    family_entries: dict[str, dict[str, Any]] = {}
    for family in families:
        if legacy:
            motif, slot = LEGACY_MOTIF, 0
        else:
            motif, slot = identities[family]
        if legacy:
            composition = dict(LEGACY_COMPOSITION)
        elif family == BREAK_FAMILY:
            composition = dict(MOTIF_COMPOSITION_PRESETS[BREAK_MOTIF])
        else:
            composition = dict(MOTIF_COMPOSITION_PRESETS[motif])
        family_entries[family] = {
            "motif": motif,
            "palette_slot": slot,
            "composition": {key: composition[key] for key in COMPOSITION_KEYS},
        }

    recipe = {
        "schema": RECIPE_SCHEMA,
        "recipe_version": RECIPE_VERSION,
        "project_id": project_id,
        "source_rhythm_sha256": rhythm_source_sha256(rhythm),
        "seed": f"{project_id}:visual-recipe-1",
        "mode": "legacy" if legacy else "structure",
        "tokens": json.loads(json.dumps(DEFAULT_TOKENS)),
        "families": family_entries,
        "diagnostics": {
            "family_count": len(family_entries),
            "motif_bank_version": MOTIF_BANK_VERSION,
            "artifact_fingerprint": visual_artifact_fingerprint(rhythm),
            "warnings": [_LEGACY_WARNING] if legacy else [],
        },
    }
    return recipe


def compile_visual_timeline(rhythm: dict[str, Any], recipe: dict[str, Any]) -> dict[str, Any]:
    """Compile the scene timeline for a rhythm and its recipe (plan section 6)."""
    if not isinstance(recipe, dict):
        raise InvalidVisualRecipe("recipe must be a dictionary")
    project_id = recipe.get("project_id")
    families = recipe.get("families")
    if not isinstance(project_id, str) or not isinstance(families, dict):
        raise InvalidVisualRecipe("recipe must carry project_id and families")
    duration = _source_duration(rhythm)
    segments = _required_segments(rhythm)
    legacy = not segments

    scenes: list[dict[str, Any]] = []
    if legacy:
        legacy_entry = families.get(LEGACY_FAMILY)
        legacy_motif = legacy_entry.get("motif") if isinstance(legacy_entry, dict) else LEGACY_MOTIF
        scenes.append(
            {
                "id": SCENE_ID_TEMPLATE.format(position=1),
                "segment_id": None,
                "segment_index": 0,
                "family": LEGACY_FAMILY,
                "variant": 0,
                "label": LEGACY_FAMILY,
                "start_time": 0.0,
                "end_time": _r6(duration),
                "motif": legacy_motif,
                "variant_delta": {key: 0.0 for key in COMPOSITION_KEYS},
            }
        )
    else:
        for index, segment in enumerate(segments):
            family = _segment_text(segment, "family", index)
            entry = families.get(family)
            if not isinstance(entry, dict):
                raise InvalidVisualRecipe(
                    f"recipe families must declare segment family '{family}'"
                )
            variant = _segment_int(segment, "variant", index)
            scenes.append(
                {
                    "id": SCENE_ID_TEMPLATE.format(position=index + 1),
                    "segment_id": _segment_text(segment, "id", index),
                    "segment_index": index,
                    "family": family,
                    "variant": variant,
                    "label": _segment_text(segment, "display_label", index),
                    "start_time": _r6(_segment_number(segment, "start_time", index)),
                    "end_time": _r6(_segment_number(segment, "end_time", index)),
                    "motif": entry.get("motif"),
                    "variant_delta": _variant_delta(
                        project_id, family, variant, entry.get("composition") or {}
                    ),
                }
            )

    transitions: list[dict[str, Any]] = []
    if not legacy:
        patterns = rhythm.get("patterns") if isinstance(rhythm.get("patterns"), dict) else {}
        boundaries = patterns.get("boundaries") if isinstance(patterns.get("boundaries"), list) else []
        boundaries_by_bar: dict[int, dict[str, Any]] = {}
        for boundary in boundaries:
            if isinstance(boundary, dict) and isinstance(boundary.get("bar"), int):
                boundaries_by_bar[boundary["bar"]] = boundary
        boundary_times: list[float] = []
        for boundary in boundaries:
            if isinstance(boundary, dict):
                time = boundary.get("time")
                if isinstance(time, (int, float)) and not isinstance(time, bool):
                    boundary_times.append(float(time))
        boundary_times.sort()

        for index in range(len(scenes) - 1):
            next_segment = segments[index + 1]
            bar = _segment_int(next_segment, "start_bar", index + 1)
            boundary = boundaries_by_bar.get(bar)
            if boundary is None:
                raise InvalidVisualRecipe(
                    f"patterns.boundaries has no boundary for bar {bar}; every "
                    "segment start needs one"
                )
            boundary_time = boundary.get("time")
            if isinstance(boundary_time, bool) or not isinstance(boundary_time, (int, float)) or not math.isfinite(boundary_time):
                raise InvalidVisualRecipe(f"patterns.boundaries bar {bar} needs a finite time")
            boundary_time = float(boundary_time)
            novelty = boundary.get("novelty")
            if isinstance(novelty, bool) or not isinstance(novelty, (int, float)) or not math.isfinite(novelty):
                raise InvalidVisualRecipe(f"patterns.boundaries bar {bar} needs a finite novelty")
            previous_time = max(
                (value for value in boundary_times if value < boundary_time), default=None
            )
            next_time = min(
                (value for value in boundary_times if value > boundary_time), default=None
            )
            lead, settle = _transition_durations(
                rhythm, boundary_time, previous_time, next_time, duration
            )
            driver = dominant_driver(boundary.get("drivers"))
            transitions.append(
                {
                    "id": TRANSITION_ID_TEMPLATE.format(position=index + 1),
                    "boundary_bar": bar,
                    "time": _r6(boundary_time),
                    "from_scene": scenes[index]["id"],
                    "to_scene": scenes[index + 1]["id"],
                    "treatment": treatment_for_driver(driver),
                    "strength": _r6(novelty),
                    "driver": driver,
                    "lead_seconds": lead,
                    "settle_seconds": settle,
                }
            )

    timeline = {
        "schema": TIMELINE_SCHEMA,
        "recipe_version": RECIPE_VERSION,
        "project_id": project_id,
        "duration": _r6(duration),
        "mode": "legacy" if legacy else "structure",
        "scenes": scenes,
        "transitions": transitions,
        "diagnostics": {
            "scene_count": len(scenes),
            "transition_count": len(transitions),
            "warnings": [],
        },
    }
    return timeline


def _round_for_canonical(value: Any) -> Any:
    if isinstance(value, float):
        return _r6(value)
    if isinstance(value, dict):
        return {key: _round_for_canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_for_canonical(item) for item in value]
    return value


def canonical_visual_bytes(value: dict[str, Any]) -> bytes:
    """Canonical UTF-8/LF JSON bytes with 6-decimal float precision."""
    canonical = json.dumps(
        _round_for_canonical(value), indent=2, ensure_ascii=False, allow_nan=False
    )
    return (canonical + "\n").encode("utf-8")


def compile_visual_artifacts(rhythm: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile both artifacts and validate them before anything is written."""
    recipe = compile_visual_recipe(rhythm)
    timeline = compile_visual_timeline(rhythm, recipe)
    require_valid_visual_artifacts(rhythm, recipe, timeline)
    return recipe, timeline
