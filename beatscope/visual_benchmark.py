"""Visual orchestration benchmark: frozen acceptance gates (v0.8 plan section 18).

The v0.8 promise is that the same project and the same audio time produce
the same scene state across pause, seek, replay, offline analysis, MCP, and
export. The gates here freeze that promise as named, blocking checks:

* determinism - identical bytes across builds, order-independent scene
  state, cross-surface parity (direct Node runtime vs the MCP worker),
  seek determinism;
* identity - family motif/palette stability, bounded variant deltas,
  reserved BREAK treatment;
* timeline - exact tiling, adjacency, driver/treatment mapping, finite
  values, no forbidden semantic fields;
* motion - sampled per transition at the plan 18.4 instants: composition
  continuity around boundaries, only the boundary impulse (and its
  contrast accent) may jump, reduced-motion scale, dense-onset stage
  stability, combined spread cap, settle exactness;
* performance - pure-query budgets enforced with generous thresholds on
  the dense fixture, WebGL draw-call count against an inline stub, and a
  director allocation smoke; browser frame rates are recorded as
  characterization, never gated.

Probes run through one generated Node driver per benchmark pass (the same
runtime modules the web player, the MCP worker, and the Codex export run).
Without Node the probe gates are reported as ``unavailable`` - never as
failures. Run with ``beatscope benchmark-visual``.
"""
from __future__ import annotations

import asyncio
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .schema import ANALYZER_VERSION
from .visual_recipe_schema import (
    BREAK_FAMILY,
    BREAK_MOTIF,
    COMPOSITION_KEYS,
    FORBIDDEN_VISUAL_KEYS,
    InvalidVisualRecipe,
    MOTIF_BANK_VERSION,
    RECIPE_VERSION,
    VARIANT_DISTANCE_MAX,
    dominant_driver,
    require_valid_visual_artifacts,
    treatment_for_driver,
    validate_visual_recipe,
    validate_visual_timeline,
)

VISUAL_BENCHMARK_SCHEMA = "beatscope-visual-benchmark-1"
VISUAL_CHECKPOINTS_SCHEMA = "beatscope-visual-checkpoints-1"

# ---------------------------------------------------------------- gates
# Frozen gate names (v0.8 plan section 18). Names are contract: reports,
# tests, and CI policy refer to them verbatim.

GATE_POLICY: dict[str, tuple[str, ...]] = {
    "determinism": (
        "recipe-bytes-identical",
        "timeline-bytes-identical",
        "scene-state-order-independent",
        "cross-surface-parity",
        "seek-determinism",
    ),
    "identity": (
        "family-motif-equality",
        "family-palette-equality",
        "variant-motif-stability",
        "variant-property-count",
        "variant-distance-bounds",
        "break-reserved-motif",
    ),
    "timeline": (
        "duration-coverage",
        "scene-tiling",
        "transition-count",
        "transition-time-tolerance",
        "driver-treatment-mapping",
        "finite-values",
        "forbidden-fields",
    ),
    "motion": (
        "composition-continuity",
        "impulse-only-jump",
        "reduced-motion-scale",
        "dense-onset-stage-stability",
        "combined-spread-cap",
        "settle-target-exactness",
    ),
    "performance": (
        "scene-query-p95",
        "director-query-p95",
        "renderer-cpu-p95",
        "frame-budget-p95",
        "draw-call-count",
        "director-allocation",
    ),
}

# Browser-side characterization is recorded, never blocking (plan 18.5):
# CI cannot enforce machine-sensitive frame times.
RECORDED_ONLY_GATES = ("renderer-cpu-p95", "frame-budget-p95")

BLOCKING_GATES: tuple[str, ...] = tuple(
    gate
    for gates in GATE_POLICY.values()
    for gate in gates
    if gate not in RECORDED_ONLY_GATES
)

# Every blocking gate has a probe since the commit-6 probes landed; the
# tuple stays a distinct name so reports keep talking about "enforced"
# gates even when a run lacks the probe runtime (they become unavailable).
ENFORCED_GATES: tuple[str, ...] = BLOCKING_GATES

# Gates that need the Node probe driver per case (absent Node => these are
# unavailable for every case) and the run-scoped performance probes.
CASE_PROBE_GATES: tuple[str, ...] = (
    "scene-state-order-independent",
    "cross-surface-parity",
    "seek-determinism",
    "composition-continuity",
    "impulse-only-jump",
    "reduced-motion-scale",
    "dense-onset-stage-stability",
    "combined-spread-cap",
    "settle-target-exactness",
)
PERF_PROBE_GATES: tuple[str, ...] = (
    "scene-query-p95",
    "director-query-p95",
    "draw-call-count",
    "director-allocation",
)

# ----------------------------------------------------------- thresholds

TRANSITION_TIME_TOLERANCE_SECONDS = 1e-3  # <= 1 ms (plan 18.3)
COMPOSITION_CONTINUITY_EPS = 1e-5
SETTLE_EXACTNESS = 1e-6
REDUCED_MOTION_POSITION_MAX = 0.20
SCENE_QUERY_P95_MS = 0.10
DIRECTOR_QUERY_P95_MS = 0.35
RENDERER_CPU_P95_MS = 2.0
FRAME_BUDGET_P95_MS = 18.0
MAX_DRAW_CALLS = 1

# Reduced-motion impulse scale mirrors the runtime contract (plan 9.5):
# spread/twist/flow and the treatment channels scale to 20%, the impulse
# to 15%, while the contrast accent keeps crossfading.
REDUCED_IMPUSE_SCALE_MAX = 0.15

# Allocation smoke budget: after gc() the scene director must not retain
# per-query state; the returned frozen frame is the only sanctioned
# allocation and it is dropped by the probe. The budget is deliberately
# generous - an unbounded per-query leak (one object per query) blows
# through it by orders of magnitude.
DIRECTOR_ALLOCATION_SMOKE_BYTES = 262_144

# Plan 18.5 probes run on the existing dense 30-second fixture.
PERF_FIXTURE_NAME = "visual-dense"
PERF_SCENE_QUERIES = 3000
PERF_DIRECTOR_QUERIES = 2000
PERF_ALLOCATION_QUERIES = 8000

# Plan 18.4 motion sampling: eight instants per transition (see
# transition_sample_times).
TRANSITION_SAMPLE_COUNT = 8

# Motion combination caps shared with the runtime (plan section 10).
SCENE_STEADY_SPREAD_CAP = 0.32
HEAVY_BEAT_ADDITIVE_CAP = 0.28
COMBINED_SPREAD_CAP = 0.46
SCENE_TWIST_CAP = 0.28
TRANSITION_TWIST_CAP = 0.12

# Channels allowed to jump at the exact boundary instant: the impulse and
# its contrast accent (the contrast hit *is* the impulse rendered through
# the contrast channel; both mark the boundary and both stay unscaled by
# reduced motion). Everything else must be continuous within 1e-5.
_BOUNDARY_JUMP_CHANNELS = frozenset({"impulse", "contrastHit"})

_FORBIDDEN_FIELDS = FORBIDDEN_VISUAL_KEYS

_REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "visual"
COMMITTED_CHECKPOINT_PATH = COMMITTED_FIXTURE_DIR / "visual-checkpoints.json"
_MODULE_ROOT = _REPO_ROOT / "beatscope"


# ------------------------------------------------------------ fixtures


def load_visual_fixtures(fixtures_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load the frozen visual fixture projects, keyed by fixture name."""
    directory = Path(fixtures_dir) if fixtures_dir else COMMITTED_FIXTURE_DIR
    fixtures: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.rhythm.json")):
        fixtures[path.name[: -len(".rhythm.json")]] = json.loads(path.read_bytes().decode("utf-8"))
    return fixtures


def load_visual_checkpoints(path: str | Path | None = None) -> dict[str, Any] | None:
    """Load the committed golden scene states, or None when unavailable."""
    checkpoint_path = Path(path) if path else COMMITTED_CHECKPOINT_PATH
    try:
        return json.loads(checkpoint_path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None


# -------------------------------------------------------------- metrics


def _finite_violations(value: Any, path: str = "$") -> list[str]:
    """JSON paths of non-finite numbers inside an artifact."""
    violations: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            violations.extend(_finite_violations(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            violations.extend(_finite_violations(item, f"{path}[{index}]"))
    elif isinstance(value, float) and not math.isfinite(value):
        violations.append(path)
    return violations


def _forbidden_field_violations(value: Any, path: str = "$") -> list[str]:
    """JSON paths of forbidden semantic fields inside an artifact."""
    violations: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in _FORBIDDEN_FIELDS:
                violations.append(f"{path}.{key}")
            violations.extend(_forbidden_field_violations(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            violations.extend(_forbidden_field_violations(item, f"{path}[{index}]"))
    return violations


def scene_tiling_report(timeline: dict[str, Any]) -> dict[str, Any]:
    """Coverage/tiling facts for one timeline."""
    scenes = timeline.get("scenes") or []
    duration = timeline.get("duration")
    gaps = 0
    overlaps = 0
    previous_end: float | None = None
    starts_at_zero = bool(scenes) and abs(float(scenes[0].get("start_time", -1.0))) <= 1e-6
    for scene in scenes:
        start = scene.get("start_time")
        end = scene.get("end_time")
        if previous_end is not None and isinstance(start, (int, float)):
            delta = float(start) - previous_end
            if delta > 1e-6:
                gaps += 1
            elif delta < -1e-6:
                overlaps += 1
        previous_end = float(end) if isinstance(end, (int, float)) else previous_end
    ends_at_duration = bool(scenes) and isinstance(previous_end, float) and isinstance(
        duration, (int, float)
    ) and abs(previous_end - float(duration)) <= 1e-6
    return {
        "scene_count": len(scenes),
        "starts_at_zero": starts_at_zero,
        "ends_at_duration": ends_at_duration,
        "gaps": gaps,
        "overlaps": overlaps,
    }


def identity_report(recipe: dict[str, Any], timeline: dict[str, Any]) -> dict[str, Any]:
    """Identity facts for one compiled pair (motifs, palettes, variants, BREAK)."""
    families = recipe.get("families") or {}
    scenes = timeline.get("scenes") or []
    motif_by_family: dict[str, set[str]] = {}
    variant_property_counts: list[int] = []
    variant_distances: list[float] = []
    variant_motif_changes = 0
    for scene in scenes:
        family = scene.get("family")
        motif_by_family.setdefault(family, set()).add(scene.get("motif"))
        delta = scene.get("variant_delta") or {}
        changed = [key for key in COMPOSITION_KEYS if abs(float(delta.get(key, 0.0) or 0.0)) > 1e-9]
        if scene.get("variant", 0) != 0:
            variant_property_counts.append(len(changed))
            variant_distances.append(
                math.sqrt(sum((float(delta.get(key, 0.0) or 0.0)) ** 2 for key in COMPOSITION_KEYS))
            )
            family_motif = (families.get(family) or {}).get("motif")
            if scene.get("motif") != family_motif:
                variant_motif_changes += 1
    break_scenes = [scene for scene in scenes if scene.get("family") == BREAK_FAMILY]
    break_motif = (families.get(BREAK_FAMILY) or {}).get("motif") if BREAK_FAMILY in families else BREAK_MOTIF
    break_reserved = break_motif == BREAK_MOTIF and all(
        (entry or {}).get("motif") != BREAK_MOTIF
        for family, entry in families.items()
        if family != BREAK_FAMILY
    )
    # Family palette equality (plan 18.2): every family carries one valid
    # palette slot (0..3) and every scene references a known family, so a
    # family always renders from the same palette band.
    palette_slots: dict[str, int] = {}
    palette_violations: list[str] = []
    for family, entry in families.items():
        slot = (entry or {}).get("palette_slot")
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot <= 3:
            palette_violations.append(f"family:{family}:palette_slot:{slot!r}")
        else:
            palette_slots[family] = slot
    for scene in scenes:
        if scene.get("family") not in families:
            palette_violations.append(f"scene:{scene.get('id')}:unknown_family:{scene.get('family')!r}")
    return {
        "family_motif_sets": {family: sorted(motifs) for family, motifs in motif_by_family.items()},
        "family_palette_slots": palette_slots,
        "palette_violations": palette_violations,
        "variant_property_counts": variant_property_counts,
        "variant_distances": variant_distances,
        "variant_motif_changes": variant_motif_changes,
        "break_scenes": len(break_scenes),
        "break_reserved": break_reserved,
    }


def transition_report(timeline: dict[str, Any], rhythm: dict[str, Any]) -> dict[str, Any]:
    """Transition mapping/timing facts against the stored Rhythm IR boundaries."""
    boundaries = {
        boundary.get("bar"): boundary
        for boundary in ((rhythm.get("patterns") or {}).get("boundaries") or [])
        if isinstance(boundary, dict) and isinstance(boundary.get("bar"), int)
    }
    scenes = timeline.get("scenes") or []
    mismatches = 0
    max_time_error = 0.0
    count_mismatch = len(timeline.get("transitions") or []) != max(0, len(scenes) - 1)
    for transition in timeline.get("transitions") or []:
        boundary = boundaries.get(transition.get("boundary_bar"))
        if boundary is None:
            mismatches += 1
            continue
        driver = dominant_driver(boundary.get("drivers"))
        if transition.get("treatment") != treatment_for_driver(driver):
            mismatches += 1
        time_error = abs(float(transition.get("time", 0.0)) - float(boundary.get("time", 0.0)))
        max_time_error = max(max_time_error, time_error)
    return {
        "transition_count": len(timeline.get("transitions") or []),
        "count_mismatch": count_mismatch,
        "driver_treatment_mismatches": mismatches,
        "max_time_error_seconds": max_time_error,
    }


# ------------------------------------------------------- motion sampling


def _onset_stripped_rhythm(rhythm: dict[str, Any]) -> dict[str, Any]:
    """The same project with the densest onset window stripped out.

    Cue references stay valid: onsets referenced by any cue are kept, so
    the variant only removes unreferenced onsets from the two-second
    window with the highest onset count. Everything the visual compiler
    reads (``patterns.segments``/``patterns.boundaries``) is untouched.
    """
    onsets = rhythm.get("onsets") or []
    if not onsets:
        return rhythm
    referenced = {
        cue.get("onset")
        for group in (rhythm.get("cues") or {}).values()
        if isinstance(group, list)
        for cue in group
        if isinstance(cue, dict)
    }
    best_center = 0.0
    best_count = -1
    for anchor in onsets:
        center = float(anchor.get("time") or 0.0)
        count = sum(
            1
            for onset in onsets
            if abs(float(onset.get("time") or 0.0) - center) <= 1.0
        )
        if count > best_count:
            best_count, best_center = count, center
    stripped = [
        onset
        for onset in onsets
        if not (
            abs(float(onset.get("time") or 0.0) - best_center) <= 1.0
            and onset.get("id") not in referenced
        )
    ]
    if len(stripped) == len(onsets):
        return rhythm
    return {**rhythm, "onsets": stripped}


def transition_sample_times(timeline: dict[str, Any]) -> dict[str, list[float]]:
    """Plan 18.4 sampling instants per transition id.

    ``boundary - lead - 1ms, boundary - lead, boundary - 1ms, boundary,
    boundary + 1ms, boundary + settle/2, boundary + settle,
    boundary + settle + 1ms``.
    """
    samples: dict[str, list[float]] = {}
    for transition in timeline.get("transitions") or []:
        boundary = float(transition["time"])
        lead = float(transition.get("lead_seconds") or 0.0)
        settle = float(transition.get("settle_seconds") or 0.0)
        samples[str(transition["id"])] = [
            boundary - lead - 0.001,
            boundary - lead,
            boundary - 0.001,
            boundary,
            boundary + 0.001,
            boundary + settle / 2.0,
            boundary + settle,
            boundary + settle + 0.001,
        ]
    return samples


def scene_composition_base(recipe: dict[str, Any], scene: dict[str, Any]) -> dict[str, float]:
    """The runtime's sceneComposition: family base plus variant delta, clamped."""
    family = (recipe.get("families") or {}).get(scene.get("family")) or {}
    base = family.get("composition") or {}
    delta = scene.get("variant_delta") or {}
    return {
        key: min(1.0, max(0.0, float(base.get(key, 0.0) or 0.0) + float(delta.get(key, 0.0) or 0.0)))
        for key in COMPOSITION_KEYS
    }


def _boundary_scene_pair(timeline: dict[str, Any], boundary: float) -> tuple[dict | None, dict | None]:
    """The scenes owning [.., boundary) and [boundary, ..] (1 us tolerance)."""
    from_scene = to_scene = None
    for scene in timeline.get("scenes") or []:
        if abs(float(scene.get("end_time", -1.0)) - boundary) <= 1e-6:
            from_scene = scene
        if abs(float(scene.get("start_time", -1.0)) - boundary) <= 1e-6:
            to_scene = scene
    return from_scene, to_scene


_POSITION_KEYS = ("spread", "twist", "flow")
_MOTION_CHANNEL_KEYS = ("phaseTurn", "radialPart", "aperture", "flowShear")


def motion_report(
    recipe: dict[str, Any],
    timeline: dict[str, Any],
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate the plan 18.4 motion gates over sampled director frames.

    ``samples`` entries: {"transition": id, "time": t, "full": frame|null,
    "reduced": frame|null, "beat": frame|null, "scene_spread": float|null}.
    Null frames mean the sample time sits past the timeline duration.
    """
    transitions = {
        str(transition.get("id")): transition
        for transition in timeline.get("transitions") or []
        if isinstance(transition, dict) and transition.get("id")
    }
    palette_mix_cap = float(
        ((recipe.get("tokens") or {}).get("motion") or {}).get("max_palette_mix") or 0.0
    )
    report: dict[str, Any] = {
        "sample_count": len(samples),
        "past_end_samples": 0,
        "bounds_violations": [],
        "continuity_violations": [],
        "impulse_violations": [],
        "reduced_motion_violations": [],
        "settle_exactness_violations": [],
        "combined_spread_violations": [],
        "combined_spread_max": 0.0,
    }
    by_transition: dict[str, dict[float, dict[str, Any]]] = {}
    for sample in samples:
        by_transition.setdefault(str(sample.get("transition")), {})[
            float(sample.get("time") or 0.0)
        ] = sample

    for transition_id, group in by_transition.items():
        transition = transitions.get(transition_id)
        if transition is None:
            continue
        boundary = float(transition["time"])
        lead = float(transition.get("lead_seconds") or 0.0)
        settle = float(transition.get("settle_seconds") or 0.0)
        from_scene, to_scene = _boundary_scene_pair(timeline, boundary)
        from_base = scene_composition_base(recipe, from_scene) if from_scene else None
        to_base = scene_composition_base(recipe, to_scene) if to_scene else None

        for time in sorted(group):
            frame = group[time].get("full")
            if frame is None:
                report["past_end_samples"] += 1
                continue
            composition = frame.get("composition") or {}
            for key in (*COMPOSITION_KEYS, "paletteMix"):
                value = composition.get(key)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    report["bounds_violations"].append(f"{transition_id}@{time:.6f}:{key}:missing")
                elif not 0.0 <= float(value) <= 1.0:
                    report["bounds_violations"].append(f"{transition_id}@{time:.6f}:{key}:range")
            if "paletteMix" in composition and float(composition["paletteMix"]) > palette_mix_cap + 1e-9:
                report["bounds_violations"].append(f"{transition_id}@{time:.6f}:paletteMix:cap")
            transition_block = frame.get("transition") or {}
            impulse = transition_block.get("impulse")
            if not isinstance(impulse, (int, float)) or isinstance(impulse, bool) or not 0.0 <= float(impulse) <= 1.0:
                report["impulse_violations"].append(f"{transition_id}@{time:.6f}:impulse:bounds")
            channels = transition_block.get("channels") or {}
            for key, value in channels.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                if key == "flowShear":
                    if not -1.0 <= float(value) <= 1.0:
                        report["bounds_violations"].append(f"{transition_id}@{time:.6f}:{key}:range")
                elif not 0.0 <= float(value) <= 1.0:
                    report["bounds_violations"].append(f"{transition_id}@{time:.6f}:{key}:range")
            spread = group[time].get("sceneSpread")
            if spread is None:
                spread = group[time].get("scene_spread")
            if spread is not None:
                report["combined_spread_max"] = max(report["combined_spread_max"], float(spread))
                if float(spread) > COMBINED_SPREAD_CAP + 1e-9:
                    report["combined_spread_violations"].append(f"{transition_id}@{time:.6f}")

        # Continuity across the three structural edges; only the impulse and
        # its contrast accent may jump at the exact boundary instant. The
        # third edge also hands the palette over: scene ownership flips to
        # the target scene the moment the settle window closes, so the
        # paletteMix scalar resets while the rendered palette stays
        # continuous - the composition keys remain continuous there.
        edges = (
            (boundary - lead - 0.001, boundary - lead, True),
            (boundary - 0.001, boundary + 0.001, True),
            (boundary + settle, boundary + settle + 0.001, False),
        )
        for left_time, right_time, include_palette in edges:
            left, right = group.get(left_time), group.get(right_time)
            if not left or not right:
                continue
            left_frame, right_frame = left.get("full"), right.get("full")
            if left_frame is None or right_frame is None:
                continue
            left_comp, right_comp = left_frame.get("composition") or {}, right_frame.get("composition") or {}
            scalar_keys = (*COMPOSITION_KEYS, "paletteMix") if include_palette else COMPOSITION_KEYS
            for key in scalar_keys:
                if isinstance(left_comp.get(key), (int, float)) and isinstance(right_comp.get(key), (int, float)):
                    if abs(float(left_comp[key]) - float(right_comp[key])) > COMPOSITION_CONTINUITY_EPS:
                        report["continuity_violations"].append(f"{transition_id}:{key}:{left_time}->{right_time}")
            left_channels = (left_frame.get("transition") or {}).get("channels") or {}
            right_channels = (right_frame.get("transition") or {}).get("channels") or {}
            for key in _MOTION_CHANNEL_KEYS:
                if isinstance(left_channels.get(key), (int, float)) and isinstance(right_channels.get(key), (int, float)):
                    if abs(float(left_channels[key]) - float(right_channels[key])) > COMPOSITION_CONTINUITY_EPS:
                        report["continuity_violations"].append(f"{transition_id}:channels.{key}:{left_time}->{right_time}")

        # The exact-boundary instant: impulse equals the stored strength and
        # both sanctioned jump channels stay zero on either side of it.
        exact = group.get(boundary)
        if exact is not None and exact.get("full") is not None:
            block = exact["full"].get("transition") or {}
            if block.get("stage") != "cross":
                report["impulse_violations"].append(f"{transition_id}:boundary:stage:{block.get('stage')!r}")
            elif abs(float(block.get("impulse") or 0.0) - float(transition.get("strength") or 0.0)) > 1e-9:
                report["impulse_violations"].append(f"{transition_id}:boundary:impulse")
            elif abs(float((block.get("channels") or {}).get("contrastHit") or 0.0) - float(transition.get("strength") or 0.0)) > 1e-9:
                report["impulse_violations"].append(f"{transition_id}:boundary:contrastHit")
            for neighbor_time in (boundary - 0.001, boundary + 0.001):
                neighbor = group.get(neighbor_time)
                neighbor_frame = (neighbor or {}).get("full")
                if neighbor_frame is None:
                    continue
                neighbor_block = neighbor_frame.get("transition") or {}
                if abs(float(neighbor_block.get("impulse") or 0.0)) > 1e-9:
                    report["impulse_violations"].append(f"{transition_id}:neighbor:{neighbor_time}:impulse")

        # Reduced motion: position channels at/below the frozen scale.
        for time in sorted(group):
            entry = group[time]
            full, reduced = entry.get("full"), entry.get("reduced")
            if full is None or reduced is None:
                continue
            full_block = full.get("transition") or {}
            reduced_block = reduced.get("transition") or {}
            if float(reduced_block.get("impulse") or 0.0) > float(full_block.get("impulse") or 0.0) * REDUCED_IMPUSE_SCALE_MAX + 1e-9:
                report["reduced_motion_violations"].append(f"{transition_id}@{time:.6f}:impulse")
            full_channels, reduced_channels = full_block.get("channels") or {}, reduced_block.get("channels") or {}
            for key in _MOTION_CHANNEL_KEYS:
                if isinstance(full_channels.get(key), (int, float)) and isinstance(reduced_channels.get(key), (int, float)):
                    if abs(float(reduced_channels[key])) > abs(float(full_channels[key])) * REDUCED_MOTION_POSITION_MAX + 1e-9:
                        report["reduced_motion_violations"].append(f"{transition_id}@{time:.6f}:channels.{key}")
            if from_base is not None and full_block.get("stage") != "idle":
                # While the transition is actively interpolating, reduced
                # motion may close at most 20% of the distance the full
                # crossfade covers (plan 18.4). Idle samples are excluded:
                # after the settle window both modes sit exactly on the
                # owning scene's base - ownership is structure, not motion.
                full_comp, reduced_comp = full.get("composition") or {}, reduced.get("composition") or {}
                for key in _POSITION_KEYS:
                    if all(isinstance(comp.get(key), (int, float)) for comp in (full_comp, reduced_comp)):
                        full_deviation = abs(float(full_comp[key]) - from_base[key])
                        reduced_deviation = abs(float(reduced_comp[key]) - from_base[key])
                        if reduced_deviation > full_deviation * REDUCED_MOTION_POSITION_MAX + 1e-9:
                            report["reduced_motion_violations"].append(f"{transition_id}@{time:.6f}:{key}")

        # Settlement lands exactly on the target scene base (full motion).
        if to_base is not None:
            settle_end = group.get(boundary + settle)
            settle_frame = (settle_end or {}).get("full")
            if settle_frame is not None:
                composition = settle_frame.get("composition") or {}
                for key in COMPOSITION_KEYS:
                    value = composition.get(key)
                    if not isinstance(value, (int, float)) or abs(float(value) - to_base[key]) > SETTLE_EXACTNESS:
                        report["settle_exactness_violations"].append(f"{transition_id}:{key}")
                mix_value = composition.get("paletteMix")
                if not isinstance(mix_value, (int, float)) or abs(float(mix_value) - palette_mix_cap) > SETTLE_EXACTNESS:
                    report["settle_exactness_violations"].append(f"{transition_id}:paletteMix")
    return report


def checkpoint_mismatches(expected_states: list[Any], actual_states: list[Any]) -> list[str]:
    """Indices where sampled scene states diverge from the golden file."""
    problems: list[str] = []
    if len(expected_states) != len(actual_states):
        return [f"count:{len(actual_states)}!={len(expected_states)}"]
    for index, (expected, actual) in enumerate(zip(expected_states, actual_states)):
        if actual != expected:
            problems.append(f"state[{index}]")
    return problems


# --------------------------------------------------------- case scoring


def evaluate_visual_case(
    name: str,
    rhythm: dict[str, Any],
    recipe: dict[str, Any] | None,
    timeline: dict[str, Any] | None,
    *,
    recipe_bytes_again: bytes | None = None,
    timeline_bytes_again: bytes | None = None,
    canonical_bytes: Callable[[dict[str, Any]], bytes] | None = None,
    motion_samples: list[dict[str, Any]] | None = None,
    driver_checks: dict[str, Any] | None = None,
    perf_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one compiled fixture against every frozen gate.

    ``motion_samples``/``driver_checks``/``perf_results`` carry the Node
    probe outputs; ``None`` means the probe did not run, which records the
    corresponding enforced gates as unavailable instead of failing them.
    """
    failed: list[str] = []
    unavailable: list[str] = []
    metrics: dict[str, Any] = {}

    if recipe is None or timeline is None:
        return {"name": name, "gates_failed": ["compiler-unavailable"], "gates_unavailable": [], "metrics": {}}

    try:
        require_valid_visual_artifacts(rhythm, recipe, timeline)
    except InvalidVisualRecipe as error:
        failed.append("invalid-artifacts")
        metrics["validation"] = str(error).splitlines()[1:6]

    metrics["finite_violations"] = len(_finite_violations(recipe)) + len(_finite_violations(timeline))
    if metrics["finite_violations"]:
        failed.append("finite-values")
    forbidden = _forbidden_field_violations(recipe) + _forbidden_field_violations(timeline)
    metrics["forbidden_fields"] = len(forbidden)
    if forbidden:
        failed.append("forbidden-fields")

    tiling = scene_tiling_report(timeline)
    metrics["tiling"] = tiling
    if not tiling["starts_at_zero"] or not tiling["ends_at_duration"] or tiling["gaps"] or tiling["overlaps"]:
        failed.append("scene-tiling")
        failed.append("duration-coverage")

    transitions = transition_report(timeline, rhythm)
    metrics["transitions"] = transitions
    if transitions["count_mismatch"]:
        failed.append("transition-count")
    if transitions["driver_treatment_mismatches"]:
        failed.append("driver-treatment-mapping")
    if transitions["max_time_error_seconds"] > TRANSITION_TIME_TOLERANCE_SECONDS:
        failed.append("transition-time-tolerance")

    identity = identity_report(recipe, timeline)
    metrics["identity"] = identity
    for family, motifs in identity["family_motif_sets"].items():
        if len(motifs) > 1:
            failed.append("family-motif-equality")
            break
    if identity["palette_violations"]:
        failed.append("family-palette-equality")
    if any(count != 2 for count in identity["variant_property_counts"]):
        failed.append("variant-property-count")
    for distance in identity["variant_distances"]:
        if not 0.0 < distance <= VARIANT_DISTANCE_MAX:
            failed.append("variant-distance-bounds")
            break
    if identity["variant_motif_changes"]:
        failed.append("variant-motif-stability")
    if not identity["break_reserved"]:
        failed.append("break-reserved-motif")

    if canonical_bytes is not None and recipe_bytes_again is not None:
        if canonical_bytes(recipe) != recipe_bytes_again:
            failed.append("recipe-bytes-identical")
    if canonical_bytes is not None and timeline_bytes_again is not None:
        if canonical_bytes(timeline) != timeline_bytes_again:
            failed.append("timeline-bytes-identical")

    # ---- determinism probes (direct runtime vs MCP worker) ----
    if driver_checks is None:
        unavailable.extend(
            (
                "scene-state-order-independent",
                "cross-surface-parity",
                "seek-determinism",
                "dense-onset-stage-stability",
            )
        )
    else:
        metrics["determinism"] = {
            "order_checked": bool(driver_checks.get("order_count")),
            "seek_checked": True,
            "parity_checked": driver_checks.get("parity_equal") is not None,
            "dense_checked": driver_checks.get("dense_count"),
        }
        if not driver_checks.get("order_equal", False):
            failed.append("scene-state-order-independent")
        if not driver_checks.get("seek_equal", False):
            failed.append("seek-determinism")
        parity = driver_checks.get("parity_equal")
        if parity is None:
            unavailable.append("cross-surface-parity")
        elif not parity:
            failed.append("cross-surface-parity")
        dense = driver_checks.get("dense_equal")
        if dense is None:
            unavailable.append("dense-onset-stage-stability")
        elif not dense:
            failed.append("dense-onset-stage-stability")

    # ---- motion probes (plan 18.4) ----
    if motion_samples is None:
        unavailable.extend(
            (
                "composition-continuity",
                "impulse-only-jump",
                "reduced-motion-scale",
                "combined-spread-cap",
                "settle-target-exactness",
            )
        )
    else:
        motion = motion_report(recipe, timeline, motion_samples)
        metrics["motion"] = motion
        if motion["bounds_violations"] or motion["continuity_violations"]:
            failed.append("composition-continuity")
        if motion["impulse_violations"]:
            failed.append("impulse-only-jump")
        if motion["reduced_motion_violations"]:
            failed.append("reduced-motion-scale")
        if motion["combined_spread_violations"]:
            failed.append("combined-spread-cap")
        if motion["settle_exactness_violations"]:
            failed.append("settle-target-exactness")

    # ---- performance probes (plan 18.5; run-scoped on the dense fixture) ----
    if perf_results is not None:
        performance: dict[str, Any] = {}
        scene_p95 = perf_results.get("scene_query_p95_ms")
        performance["scene_query_p95_ms"] = scene_p95
        if scene_p95 is None:
            unavailable.append("scene-query-p95")
        elif scene_p95 >= SCENE_QUERY_P95_MS:
            failed.append("scene-query-p95")
        director_p95 = perf_results.get("director_query_p95_ms")
        performance["director_query_p95_ms"] = director_p95
        if director_p95 is None:
            unavailable.append("director-query-p95")
        elif director_p95 >= DIRECTOR_QUERY_P95_MS:
            failed.append("director-query-p95")
        allocation = perf_results.get("allocation") or {}
        retained_bytes = allocation.get("retainedBytes", allocation.get("retained_bytes"))
        performance["allocation_retained_bytes"] = retained_bytes
        if not allocation.get("available") or retained_bytes is None:
            unavailable.append("director-allocation")
        elif retained_bytes > DIRECTOR_ALLOCATION_SMOKE_BYTES:
            failed.append("director-allocation")
        draw_calls = perf_results.get("draw_calls") or {}
        performance["draw_call_renders"] = draw_calls.get("renders")
        performance["particle_count"] = draw_calls.get("particle_count")
        if not draw_calls.get("available") or not draw_calls.get("renders"):
            unavailable.append("draw-call-count")
        elif any(count != MAX_DRAW_CALLS for count in draw_calls["renders"]):
            failed.append("draw-call-count")
        performance["recorded_only"] = {
            "renderer-cpu-p95": perf_results.get("renderer_cpu_p95_ms"),
            "frame-budget-p95": perf_results.get("frame_budget_p95_ms"),
            "note": "browser smoke characterization (plan 18.5); never gating in CI",
        }
        metrics["performance"] = performance

    recipe_errors = validate_visual_recipe(recipe)
    timeline_errors = validate_visual_timeline(timeline, rhythm, recipe)
    metrics["validator_errors"] = len(recipe_errors) + len(timeline_errors)

    return {
        "name": name,
        "gates_failed": sorted(set(failed)),
        "gates_unavailable": sorted(set(unavailable)),
        "metrics": metrics,
    }


def _default_compiler() -> tuple[
    Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]] | None,
    Callable[[dict[str, Any]], bytes] | None,
]:
    """``(compile_artifacts, canonical_bytes)`` from the v0.8 compiler.

    ``compile_visual_artifacts`` validates before returning and compiles
    legacy projects into the neutral LEGACY family, so every frozen fixture
    flows through the exact path the service and the export use. Returns
    ``(None, None)`` before the compiler exists.
    """
    try:
        from .visual_recipe import canonical_visual_bytes, compile_visual_artifacts
    except ImportError:
        return None, None
    return compile_visual_artifacts, canonical_visual_bytes


# ---------------------------------------------------------- node driver

_DRIVER_SOURCE = r'''/**
 * BeatScope visual benchmark probe driver (plan sections 18.4/18.5).
 * Generated at runtime by beatscope/visual_benchmark.py; argv[2] holds the
 * task JSON path and one JSON result object is printed to stdout. The
 * WebGL2 draw-call probe runs against an inline stub so the count is
 * enforceable in headless CI; the browser smoke keeps the real GPU path.
 */
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const task = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const moduleURL = (relative) => pathToFileURL(task.moduleRoot + '/' + relative).href;

const { createTrack } = await import(moduleURL('runtime/runtime.js'));
const { createMotionDirector, combinedSpread } = await import(moduleURL('runtime/visual-profile.js'));
const { createSceneDirector } = await import(moduleURL('runtime/scene-director.js'));

function p95(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil(0.95 * sorted.length) - 1)];
}

// Deterministic stride traversal (coprime step): no RNG anywhere.
function shuffledOrder(count) {
  const gcd = (a, b) => (b === 0 ? a : gcd(b, a % b));
  let step = 7;
  while (gcd(step, count) !== 1) step += 1;
  const order = [];
  for (let index = 0; index < count; index += 1) order.push((index * step) % count);
  return order;
}

function runCase(entry) {
  const rhythm = JSON.parse(readFileSync(entry.rhythm, 'utf8'));
  const recipe = JSON.parse(readFileSync(entry.recipe, 'utf8'));
  const timeline = JSON.parse(readFileSync(entry.timeline, 'utf8'));
  const track = createTrack(rhythm);
  const motion = createMotionDirector(track);
  const scene = createSceneDirector(recipe, timeline);
  const sceneReduced = createSceneDirector(recipe, timeline, { reducedMotion: true });

  const samples = [];
  for (const [transitionId, times] of Object.entries(entry.sampleTimes || {})) {
    for (const time of times) {
      const full = scene.at(time);
      const reduced = sceneReduced.at(time);
      const beat = motion.at(time);
      samples.push({
        transition: transitionId,
        time,
        full,
        reduced,
        beat,
        sceneSpread: full && beat ? combinedSpread(full, beat).sceneSpread : null,
      });
    }
  }

  const orderTimes = entry.orderTimes || [];
  const sequential = orderTimes.map((time) => JSON.stringify(scene.at(time)));
  let orderEqual = orderTimes.length > 0;
  for (const index of shuffledOrder(orderTimes.length)) {
    if (JSON.stringify(scene.at(orderTimes[index])) !== sequential[index]) {
      orderEqual = false;
      break;
    }
  }

  // Seek determinism (plan 18.1): 1s -> 40s -> 3s versus a fresh 3s query.
  scene.at(1);
  scene.at(40);
  const seekState = JSON.stringify(scene.at(3));
  const freshState = JSON.stringify(createSceneDirector(recipe, timeline).at(3));

  // Dense onsets never move the stage sequence: the same structure with
  // every onset stripped compiles to identical scene/transition blocks, so
  // the full frames must match exactly.
  let dense = null;
  if (entry.dense) {
    const strippedRecipe = JSON.parse(readFileSync(entry.dense.recipe, 'utf8'));
    const strippedTimeline = JSON.parse(readFileSync(entry.dense.timeline, 'utf8'));
    const stripped = createSceneDirector(strippedRecipe, strippedTimeline);
    const denseTimes = entry.dense.times || [];
    let denseEqual = denseTimes.length > 0;
    for (let index = 0; index < denseTimes.length; index += 1) {
      if (JSON.stringify(scene.at(denseTimes[index])) !== JSON.stringify(stripped.at(denseTimes[index]))) {
        denseEqual = false;
        break;
      }
    }
    dense = { equal: denseEqual, count: denseTimes.length };
  }

  const checkpoints = (entry.checkpointTimes || []).map((time) => scene.at(time));
  const parity = (entry.parityTimes || []).map((time) => ({
    time,
    at: track.at(time),
    scene: scene.at(time),
  }));

  return {
    samples,
    order: { equal: orderEqual, count: orderTimes.length },
    seek: { equal: seekState === freshState },
    dense,
    checkpoints,
    parity,
  };
}

function createGLStub() {
  const calls = { drawArrays: 0 };
  const gl = {
    VERTEX_SHADER: 1,
    FRAGMENT_SHADER: 2,
    COMPILE_STATUS: 3,
    LINK_STATUS: 4,
    POINTS: 5,
    FLOAT: 6,
    ARRAY_BUFFER: 7,
    STATIC_DRAW: 8,
    BLEND: 9,
    DEPTH_TEST: 10,
    SCISSOR_TEST: 11,
    COLOR_BUFFER_BIT: 12,
    drawingBufferWidth: 640,
    drawingBufferHeight: 360,
    createShader: () => ({}),
    shaderSource: () => {},
    compileShader: () => {},
    getShaderParameter: () => true,
    getShaderInfoLog: () => '',
    deleteShader: () => {},
    createProgram: () => ({}),
    attachShader: () => {},
    linkProgram: () => {},
    getProgramParameter: () => true,
    getProgramInfoLog: () => '',
    deleteProgram: () => {},
    useProgram: () => {},
    getAttribLocation: () => 0,
    getUniformLocation: (program, name) => ({ name }),
    getUniform: () => [1, 0, 0, 0, 1, 0, 0, 0, 1],
    uniform1f: () => {},
    uniform2f: () => {},
    uniform3f: () => {},
    uniform1i: () => {},
    uniform3fv: () => {},
    uniformMatrix3fv: () => {},
    uniformMatrix4fv: () => {},
    createBuffer: () => ({}),
    bindBuffer: () => {},
    bufferData: () => {},
    deleteBuffer: () => {},
    createVertexArray: () => ({}),
    bindVertexArray: () => {},
    deleteVertexArray: () => {},
    enableVertexAttribArray: () => {},
    vertexAttribPointer: () => {},
    enable: () => {},
    disable: () => {},
    blendFuncSeparate: () => {},
    clearColor: () => {},
    clear: () => {},
    viewport: () => {},
    scissor: () => {},
    drawArrays: () => { calls.drawArrays += 1; },
  };
  const canvas = {
    width: 640,
    height: 360,
    style: {},
    getContext: (type) => (type === 'webgl2' ? gl : null),
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  return { canvas, calls };
}

async function probeDrawCalls(entry, motion, scene) {
  const { createParticleField } = await import(moduleURL('web/particle-field.js'));
  const { createParticleGeometry } = await import(moduleURL('web/particle-geometry.js'));
  const { canvas, calls } = createGLStub();
  const geometry = createParticleGeometry({ count: 600, rings: 3 });
  const field = createParticleField({ canvas, geometry });
  if (!field.available) {
    return { available: false, reason: field.reason, renders: [], particleCount: 0 };
  }
  const renders = [];
  for (const time of entry.drawCallTimes || []) {
    calls.drawArrays = 0;
    field.render({ motion: motion.at(time), scene: scene.at(time) }, {
      quality: 1,
      reducedMotion: false,
      radiusPx: 40,
      viewportRect: { x: 0, y: 0, width: 640, height: 360 },
    });
    renders.push(calls.drawArrays);
  }
  const particleCount = field.count;
  field.dispose();
  return { available: true, reason: null, renders, particleCount };
}

async function runPerf(entry) {
  const rhythm = JSON.parse(readFileSync(entry.rhythm, 'utf8'));
  const recipe = JSON.parse(readFileSync(entry.recipe, 'utf8'));
  const timeline = JSON.parse(readFileSync(entry.timeline, 'utf8'));
  const track = createTrack(rhythm);
  const motion = createMotionDirector(track);
  const scene = createSceneDirector(recipe, timeline);
  const duration = Number(timeline.duration) || 1;
  const spreadTime = (index, total) => (((index + 0.5) * 0.6180339887498949) % 1) * duration;

  for (let index = 0; index < 200; index += 1) scene.at(spreadTime(index, 200));
  const sceneSamples = [];
  for (let index = 0; index < entry.sceneQueries; index += 1) {
    const started = performance.now();
    scene.at(spreadTime(index, entry.sceneQueries));
    sceneSamples.push(performance.now() - started);
  }

  for (let index = 0; index < 100; index += 1) {
    const time = spreadTime(index, 100);
    track.at(time);
    motion.at(time);
    scene.at(time);
  }
  // The full director query is the browser's per-frame path (plan 7.1):
  // signal, beat motion, scene frame, combined spread.
  const directorSamples = [];
  for (let index = 0; index < entry.directorQueries; index += 1) {
    const time = spreadTime(index, entry.directorQueries);
    const started = performance.now();
    track.at(time);
    const motionFrame = motion.at(time);
    const sceneFrame = scene.at(time);
    if (sceneFrame && motionFrame) combinedSpread(sceneFrame, motionFrame);
    directorSamples.push(performance.now() - started);
  }

  // Allocation smoke (plan 18.5): after gc(), retained heap must not grow
  // beyond the smoke budget; the returned frozen frame is dropped each
  // iteration, so any surviving growth is director-internal state.
  let allocation = { available: false, retainedBytes: null, queries: 0 };
  if (typeof globalThis.gc === 'function') {
    for (let index = 0; index < 500; index += 1) {
      globalThis.__beatScopeFrame = scene.at(spreadTime(index, 500));
    }
    globalThis.gc();
    const baseline = process.memoryUsage().heapUsed;
    for (let index = 0; index < entry.allocationQueries; index += 1) {
      globalThis.__beatScopeFrame = scene.at(spreadTime(index, entry.allocationQueries));
    }
    globalThis.gc();
    allocation = {
      available: true,
      retainedBytes: process.memoryUsage().heapUsed - baseline,
      queries: entry.allocationQueries,
    };
  }

  const drawCalls = await probeDrawCalls(entry, motion, scene);

  return {
    scene_query_p95_ms: p95(sceneSamples),
    director_query_p95_ms: p95(directorSamples),
    allocation,
    draw_calls: drawCalls,
    renderer_cpu_p95_ms: null,
    frame_budget_p95_ms: null,
  };
}

const result = { cases: {}, perf: null };
for (const entry of task.cases || []) {
  try {
    result.cases[entry.name] = runCase(entry);
  } catch (error) {
    result.cases[entry.name] = { error: String(error && error.message ? error.message : error) };
  }
}
if (task.perf) {
  try {
    result.perf = await runPerf(task.perf);
  } catch (error) {
    result.perf = { error: String(error && error.message ? error.message : error) };
  }
}
process.stdout.write(JSON.stringify(result));
'''


def _write_json_file(path: Path, payload: Any, *, canonical: bool = False) -> None:
    text = json.dumps(payload, indent=2 if canonical else None, ensure_ascii=False, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _order_times(timeline: dict[str, Any]) -> list[float]:
    """Deterministic probe grid: start, end, scene midpoints, boundaries."""
    times = {0.0, round(float(timeline.get("duration") or 0.0), 6)}
    for scene in timeline.get("scenes") or []:
        middle = (float(scene.get("start_time", 0.0)) + float(scene.get("end_time", 0.0))) / 2.0
        times.add(round(middle, 6))
    for transition in timeline.get("transitions") or []:
        boundary = float(transition.get("time", 0.0))
        times.add(round(boundary, 6))
        times.add(round(boundary + float(transition.get("settle_seconds") or 0.0), 6))
    return sorted(times)


def _run_node_driver(task: dict[str, Any], workdir: str | Path) -> dict[str, Any]:
    """Run the generated driver once for the whole task; never raises."""
    work = Path(workdir)
    driver_path = work / "visual-benchmark-driver.mjs"
    task_path = work / "visual-benchmark-task.json"
    driver_path.write_text(_DRIVER_SOURCE, encoding="utf-8", newline="\n")
    task_path.write_text(
        json.dumps(task, ensure_ascii=False, allow_nan=False), encoding="utf-8", newline="\n",
    )
    try:
        completed = subprocess.run(
            ["node", "--expose-gc", str(driver_path), str(task_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            cwd=str(work),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"driver launch failed: {exc}"}
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "driver exited non-zero").strip()
        return {"error": f"driver failed: {detail[-1500:]}"}
    try:
        return json.loads(completed.stdout)
    except ValueError:
        return {"error": "driver printed unparsable output"}


def _parity_flags(task_cases: list[dict[str, Any]], driver_result: dict[str, Any]) -> dict[str, bool]:
    """Cross-surface parity (plan 18.1): MCP worker vs direct runtime states."""
    try:
        from .mcp.runtime_bridge import RuntimeBridge, file_fingerprint
    except ImportError:
        return {}

    async def _collect() -> dict[str, bool]:
        bridge = RuntimeBridge()
        flags: dict[str, bool] = {}
        try:
            await bridge.start()
            for case in task_cases:
                entries = ((driver_result.get("cases") or {}).get(case["name"]) or {}).get("parity") or []
                if not entries:
                    continue
                matches = True
                for entry in entries:
                    result = await bridge.call(
                        "visual_state",
                        project=case["name"],
                        path=case["rhythm"],
                        fingerprint=file_fingerprint(Path(case["rhythm"])),
                        recipe_path=case["recipe"],
                        timeline_path=case["timeline"],
                        time=entry["time"],
                    )
                    if result.get("at") != entry.get("at") or result.get("scene") != entry.get("scene"):
                        matches = False
                        break
                flags[case["name"]] = matches
        finally:
            await bridge.close()
        return flags

    try:
        return asyncio.run(_collect())
    except Exception:  # noqa: BLE001 - parity stays unavailable, never crashes the run
        return {}


def _run_visual_probes(
    compiled_cases: list[dict[str, Any]],
    *,
    compiler: Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]],
    canonical: Callable[[dict[str, Any]], bytes] | None,
    want_perf: bool = True,
    want_parity: bool = True,
) -> dict[str, Any]:
    """One Node driver pass over every compiled case plus the perf fixture."""
    probed = [case for case in compiled_cases if case.get("recipe") is not None and case.get("timeline") is not None]
    if not probed or shutil.which("node") is None:
        return {"driver": None, "parity": {}, "perf_case": None, "task": None, "error": "node-unavailable"}

    with tempfile.TemporaryDirectory(prefix="beatscope-visual-probe-") as tmp:
        root = Path(tmp)
        task_cases: list[dict[str, Any]] = []
        perf_case_name = None
        for case in probed:
            name = case["name"]
            case_dir = root / name
            case_dir.mkdir()
            rhythm_path = case_dir / "rhythm.json"
            recipe_path = case_dir / "visual-recipe.json"
            timeline_path = case_dir / "visual-timeline.json"
            _write_json_file(rhythm_path, case["rhythm"])
            recipe_path.write_bytes(canonical(case["recipe"]) if canonical else _canonical_fallback(case["recipe"]))
            timeline_path.write_bytes(canonical(case["timeline"]) if canonical else _canonical_fallback(case["timeline"]))
            timeline = case["timeline"]
            order = _order_times(timeline)
            entry: dict[str, Any] = {
                "name": name,
                "rhythm": str(rhythm_path),
                "recipe": str(recipe_path),
                "timeline": str(timeline_path),
                "sampleTimes": transition_sample_times(timeline),
                "orderTimes": order,
                "checkpointTimes": order,
                "parityTimes": order[:4],
                "dense": None,
            }
            # Dense-onset probe: identical structure with the densest onset
            # window stripped must compile to identical scene/transition
            # blocks and produce identical director frames.
            stripped = _onset_stripped_rhythm(case["rhythm"])
            try:
                stripped_recipe, stripped_timeline = compiler(stripped)
                stripped_dir = case_dir / "dense"
                stripped_dir.mkdir()
                stripped_recipe_path = stripped_dir / "visual-recipe.json"
                stripped_timeline_path = stripped_dir / "visual-timeline.json"
                stripped_recipe_path.write_bytes(
                    canonical(stripped_recipe) if canonical else _canonical_fallback(stripped_recipe)
                )
                stripped_timeline_path.write_bytes(
                    canonical(stripped_timeline) if canonical else _canonical_fallback(stripped_timeline)
                )
                entry["dense"] = {
                    "recipe": str(stripped_recipe_path),
                    "timeline": str(stripped_timeline_path),
                    "times": order,
                }
            except InvalidVisualRecipe:
                entry["dense"] = None
            task_cases.append(entry)
            if want_perf and perf_case_name is None and name == PERF_FIXTURE_NAME:
                perf_case_name = name

        perf_entry = None
        if want_perf and perf_case_name is not None:
            perf_case = next(case for case in probed if case["name"] == perf_case_name)
            perf_dir = root / perf_case_name
            sample_times = transition_sample_times(perf_case["timeline"])
            first = next(iter(sample_times.values()), [])
            perf_entry = {
                "name": perf_case_name,
                "rhythm": str(perf_dir / "rhythm.json"),
                "recipe": str(perf_dir / "visual-recipe.json"),
                "timeline": str(perf_dir / "visual-timeline.json"),
                "drawCallTimes": [0.0, *first],
                "sceneQueries": PERF_SCENE_QUERIES,
                "directorQueries": PERF_DIRECTOR_QUERIES,
                "allocationQueries": PERF_ALLOCATION_QUERIES,
            }

        task = {"moduleRoot": str(_MODULE_ROOT), "cases": task_cases, "perf": perf_entry}
        driver_result = _run_node_driver(task, root)
        parity: dict[str, bool] = {}
        if want_parity and driver_result is not None and "error" not in driver_result:
            parity = _parity_flags(task_cases, driver_result)
    return {
        "driver": driver_result,
        "parity": parity,
        "perf_case": perf_case_name,
        "task": task,
        "error": driver_result.get("error") if isinstance(driver_result, dict) else None,
    }


def _canonical_fallback(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def collect_visual_checkpoints(fixtures_dir: str | Path | None = None) -> dict[str, Any]:
    """Regenerate the golden scene-state checkpoints through the live runtime.

    Raises when Node or the compiler is unavailable; the committed file at
    ``tests/fixtures/visual/visual-checkpoints.json`` is produced exactly
    by this function and never edited by hand.
    """
    fixtures = load_visual_fixtures(fixtures_dir)
    compiler, canonical = _default_compiler()
    if compiler is None:
        raise RuntimeError("visual compiler unavailable; checkpoints cannot be collected")
    compiled = []
    for name, rhythm in sorted(fixtures.items()):
        recipe, timeline = compiler(rhythm)
        compiled.append({"name": name, "rhythm": rhythm, "recipe": recipe, "timeline": timeline})
    probes = _run_visual_probes(compiled, compiler=compiler, canonical=canonical, want_perf=False, want_parity=False)
    driver_result = probes["driver"]
    if not isinstance(driver_result, dict) or "error" in driver_result:
        raise RuntimeError(f"probe driver unavailable: {probes['error']}")
    times_by_case = {
        entry["name"]: entry["checkpointTimes"] for entry in (probes["task"] or {}).get("cases", [])
    }
    document: dict[str, Any] = {
        "schema": VISUAL_CHECKPOINTS_SCHEMA,
        "recipe_version": RECIPE_VERSION,
        "fixtures": {},
    }
    for case in compiled:
        payload = driver_result["cases"][case["name"]]
        if "error" in payload:
            raise RuntimeError(f"probe failed for {case['name']}: {payload['error']}")
        document["fixtures"][case["name"]] = {
            "times": times_by_case[case["name"]],
            "states": payload["checkpoints"],
        }
    return document


def run_visual_benchmark(
    output_dir: str | Path | None = None,
    fixtures_dir: str | Path | None = None,
    *,
    cases: list[dict[str, Any]] | None = None,
    compile_artifacts: Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]] | None = None,
    canonical_bytes: Callable[[dict[str, Any]], bytes] | None = None,
) -> dict[str, Any]:
    """Analyze every fixture and score it; writes JSON + markdown reports.

    ``cases`` injects precompiled fixtures for tests (no probes run).
    Otherwise each frozen fixture is compiled twice for the determinism
    gates and sampled once through the generated Node driver for the
    motion, determinism, and performance probes.
    """
    if cases is not None:
        evaluated = list(cases)
        probes: dict[str, Any] | None = None
        perf_case_name = None
    else:
        default_compiler, default_canonical = _default_compiler()
        compiler = compile_artifacts if compile_artifacts is not None else default_compiler
        canonical = canonical_bytes if canonical_bytes is not None else default_canonical
        compiled_cases: list[dict[str, Any]] = []
        for name, rhythm in sorted(load_visual_fixtures(fixtures_dir).items()):
            recipe = timeline = None
            recipe_bytes_again = timeline_bytes_again = None
            if compiler is not None:
                try:
                    recipe, timeline = compiler(rhythm)
                    recipe_again, timeline_again = compiler(rhythm)
                    if canonical is not None:
                        recipe_bytes_again = canonical(recipe_again)
                        timeline_bytes_again = canonical(timeline_again)
                except InvalidVisualRecipe:
                    recipe = timeline = None
            compiled_cases.append({
                "name": name,
                "rhythm": rhythm,
                "recipe": recipe,
                "timeline": timeline,
                "recipe_bytes_again": recipe_bytes_again,
                "timeline_bytes_again": timeline_bytes_again,
            })

        probes = _run_visual_probes(compiled_cases, compiler=compiler, canonical=canonical)
        driver_result = probes["driver"]
        parity_flags = probes["parity"]
        perf_case_name = probes["perf_case"]
        checkpoint_doc = load_visual_checkpoints()
        evaluated = []
        case_unavailable: set[str] = set()
        perf_case_compiled = any(
            case["name"] == PERF_FIXTURE_NAME and case["recipe"] is not None
            for case in compiled_cases
        )
        perf_results_attached = False
        for case in compiled_cases:
            if case["recipe"] is None or case["timeline"] is None:
                evaluated.append({
                    "name": case["name"],
                    "gates_failed": ["compiler-unavailable"],
                    "gates_unavailable": [],
                    "metrics": {},
                })
                continue
            payload = {}
            if isinstance(driver_result, dict):
                payload = (driver_result.get("cases") or {}).get(case["name"]) or {}
            probe_ok = isinstance(driver_result, dict) and "error" not in driver_result and payload and "error" not in payload
            motion_samples = payload.get("samples") if probe_ok else None
            checks = None
            if motion_samples is not None:
                dense = payload.get("dense")
                checks = {
                    "order_equal": bool((payload.get("order") or {}).get("equal")),
                    "order_count": (payload.get("order") or {}).get("count"),
                    "seek_equal": bool((payload.get("seek") or {}).get("equal")),
                    "parity_equal": parity_flags.get(case["name"]),
                    "dense_equal": dense.get("equal") if isinstance(dense, dict) else None,
                    "dense_count": dense.get("count") if isinstance(dense, dict) else None,
                }
            perf_results = None
            if probe_ok and case["name"] == perf_case_name and isinstance(driver_result.get("perf"), dict):
                perf_results = driver_result["perf"] if "error" not in driver_result["perf"] else None
            result = evaluate_visual_case(
                case["name"],
                case["rhythm"],
                case["recipe"],
                case["timeline"],
                recipe_bytes_again=case["recipe_bytes_again"],
                timeline_bytes_again=case["timeline_bytes_again"],
                canonical_bytes=canonical,
                motion_samples=motion_samples,
                driver_checks=checks,
                perf_results=perf_results,
            )
            if checkpoint_doc and motion_samples is not None:
                expected = (checkpoint_doc.get("fixtures") or {}).get(case["name"])
                actual = payload.get("checkpoints")
                if expected and isinstance(actual, list):
                    problems = checkpoint_mismatches(expected.get("states") or [], actual)
                    result["metrics"]["checkpoint_mismatches"] = len(problems)
                    if problems:
                        result["metrics"]["checkpoint_first_mismatch"] = problems[0]
            if not probe_ok:
                result["metrics"]["probe_error"] = (
                    payload.get("error") or probes["error"] or "probe unavailable"
                )
            case_unavailable.update(result.get("gates_unavailable") or [])
            if case["name"] == perf_case_name:
                perf_case_compiled = True
                perf_results_attached = perf_results is not None
            evaluated.append(result)
        # The performance probes are run-scoped: when the perf fixture
        # compiled but its probe could not run, record those gates once at
        # run level instead of per case.
        if perf_case_compiled and not perf_results_attached:
            case_unavailable.update(PERF_PROBE_GATES)

    failed = sorted({gate for case in evaluated for gate in case.get("gates_failed", [])})
    unavailable = sorted(case_unavailable) if cases is None else sorted(
        {gate for case in evaluated for gate in case.get("gates_unavailable", [])}
    )
    results: dict[str, Any] = {
        "schema": VISUAL_BENCHMARK_SCHEMA,
        "pipeline_version": ANALYZER_VERSION,
        "recipe_version": RECIPE_VERSION,
        "motif_bank_version": MOTIF_BANK_VERSION,
        "gates": {
            "failed": failed,
            "pending": sorted(gate for gate in BLOCKING_GATES if gate not in ENFORCED_GATES),
            "unavailable": unavailable,
            "recorded_only": list(RECORDED_ONLY_GATES),
            "policy": {"blocking": list(BLOCKING_GATES)},
        },
        "probes": {
            "node": shutil.which("node") is not None,
            "driver": (probes or {}).get("error") or ("ok" if (probes or {}).get("driver") else None),
            "parity": "checked" if (probes or {}).get("parity") else None,
            "perf_case": (probes or {}).get("perf_case"),
        },
        "cases": evaluated,
    }

    out = Path(output_dir) if output_dir else Path("build") / "visual-benchmark"
    out.mkdir(parents=True, exist_ok=True)
    (out / "visual-benchmark.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n",
    )
    (out / "visual-benchmark.md").write_text(write_markdown(results), encoding="utf-8", newline="\n")
    results["output_dir"] = str(out)
    return results


def write_markdown(results: dict[str, Any]) -> str:
    """Render the visual benchmark report."""
    gates = results["gates"]
    lines: list[str] = [
        "# BeatScope Visual Benchmark",
        "",
        f"- analyzer: pipeline {results['pipeline_version']}",
        f"- recipe version: {results['recipe_version']}",
        f"- gates failed: {len(gates['failed'])}",
        f"- gates unavailable: {len(gates.get('unavailable', []))}",
        f"- gates pending (later v0.8 commits): {len(gates['pending'])}",
        f"- probes: node={results.get('probes', {}).get('node')} driver={results.get('probes', {}).get('driver')}",
        "",
        "| fixture | scenes | transitions | gates failed | gates unavailable |",
        "|---|---|---|---|---|",
    ]
    for case in results["cases"]:
        metrics = case.get("metrics") or {}
        tiling = metrics.get("tiling") or {}
        transitions = metrics.get("transitions") or {}
        lines.append(
            f"| {case['name']} | {tiling.get('scene_count', '-')} "
            f"| {transitions.get('transition_count', '-')} "
            f"| {', '.join(case.get('gates_failed', [])) or 'none'} "
            f"| {', '.join(case.get('gates_unavailable', [])) or 'none'} |"
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "BLOCKING_GATES",
    "CASE_PROBE_GATES",
    "COMBINED_SPREAD_CAP",
    "COMPOSITION_CONTINUITY_EPS",
    "DIRECTOR_ALLOCATION_SMOKE_BYTES",
    "DIRECTOR_QUERY_P95_MS",
    "ENFORCED_GATES",
    "FRAME_BUDGET_P95_MS",
    "GATE_POLICY",
    "MAX_DRAW_CALLS",
    "PERF_ALLOCATION_QUERIES",
    "PERF_DIRECTOR_QUERIES",
    "PERF_FIXTURE_NAME",
    "PERF_SCENE_QUERIES",
    "RECORDED_ONLY_GATES",
    "REDUCED_IMPUSE_SCALE_MAX",
    "REDUCED_MOTION_POSITION_MAX",
    "RENDERER_CPU_P95_MS",
    "SCENE_QUERY_P95_MS",
    "SCENE_STEADY_SPREAD_CAP",
    "SCENE_TWIST_CAP",
    "SETTLE_EXACTNESS",
    "TRANSITION_TIME_TOLERANCE_SECONDS",
    "TRANSITION_TWIST_CAP",
    "TRANSITION_SAMPLE_COUNT",
    "VISUAL_BENCHMARK_SCHEMA",
    "VISUAL_CHECKPOINTS_SCHEMA",
    "checkpoint_mismatches",
    "collect_visual_checkpoints",
    "evaluate_visual_case",
    "identity_report",
    "load_visual_checkpoints",
    "load_visual_fixtures",
    "motion_report",
    "run_visual_benchmark",
    "scene_composition_base",
    "scene_tiling_report",
    "transition_report",
    "transition_sample_times",
    "write_markdown",
]
