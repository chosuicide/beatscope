"""Visual orchestration benchmark: frozen acceptance gates (v0.8 plan section 18).

The v0.8 promise is that the same project and the same audio time produce
the same scene state across pause, seek, replay, offline analysis, MCP, and
export. The gates here freeze that promise as named, blocking checks:

* determinism - identical bytes across builds, order-independent scene
  state, cross-surface parity, seek determinism;
* identity - family motif/palette stability, bounded variant deltas,
  reserved BREAK treatment;
* timeline - exact tiling, adjacency, driver/treatment mapping, finite
  values, no forbidden semantic fields;
* motion - composition continuity around boundaries, reduced-motion scale,
  settle exactness;
* performance - pure-query budgets enforced with generous thresholds;
  browser frame rates are recorded as characterization, never gated.

This module starts as the commit-1 skeleton: the frozen gate tables plus
pure checks over compiled artifacts. The compiler wiring, motion sampling,
and performance probes land later in the v0.8 sequence; until then the CLI
reports ``compiler-unavailable``. Run with ``beatscope benchmark-visual``.
"""
from __future__ import annotations

import json
import math
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

# Motion combination caps shared with the runtime (plan section 10).
SCENE_STEADY_SPREAD_CAP = 0.32
HEAVY_BEAT_ADDITIVE_CAP = 0.28
COMBINED_SPREAD_CAP = 0.46
SCENE_TWIST_CAP = 0.28
TRANSITION_TWIST_CAP = 0.12

_FORBIDDEN_FIELDS = FORBIDDEN_VISUAL_KEYS

# Gates this skeleton already enforces; every other blocking gate is
# reported as ``pending`` until the later v0.8 commits land its probe.
ENFORCED_GATES: tuple[str, ...] = (
    "recipe-bytes-identical",
    "timeline-bytes-identical",
    "family-motif-equality",
    "variant-property-count",
    "variant-distance-bounds",
    "variant-motif-stability",
    "break-reserved-motif",
    "duration-coverage",
    "scene-tiling",
    "transition-count",
    "transition-time-tolerance",
    "driver-treatment-mapping",
    "finite-values",
    "forbidden-fields",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "visual"


# ------------------------------------------------------------ fixtures


def load_visual_fixtures(fixtures_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load the frozen visual fixture projects, keyed by fixture name."""
    directory = Path(fixtures_dir) if fixtures_dir else COMMITTED_FIXTURE_DIR
    fixtures: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.rhythm.json")):
        fixtures[path.name[: -len(".rhythm.json")]] = json.loads(path.read_bytes().decode("utf-8"))
    return fixtures


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
    """Identity facts for one compiled pair (motifs, variants, BREAK)."""
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
    return {
        "family_motif_sets": {family: sorted(motifs) for family, motifs in motif_by_family.items()},
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
) -> dict[str, Any]:
    """Score one compiled fixture against the identity/timeline/determinism gates."""
    failed: list[str] = []
    metrics: dict[str, Any] = {}

    if recipe is None or timeline is None:
        return {"name": name, "gates_failed": ["compiler-unavailable"], "metrics": {}}

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

    recipe_errors = validate_visual_recipe(recipe)
    timeline_errors = validate_visual_timeline(timeline, rhythm, recipe)
    metrics["validator_errors"] = len(recipe_errors) + len(timeline_errors)

    return {"name": name, "gates_failed": sorted(set(failed)), "metrics": metrics}


def _default_compiler() -> tuple[
    Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]] | None,
    Callable[[dict[str, Any]], bytes] | None,
]:
    """``(compile_artifacts, canonical_bytes)`` from the v0.8 compiler.

    Returns ``(None, None)`` before the compiler commit, which the runner
    reports as ``compiler-unavailable`` instead of failing a case.
    """
    try:
        from .visual_recipe import canonical_visual_bytes, compile_visual_recipe, compile_visual_timeline
    except ImportError:
        return None, None

    def compile_artifacts(rhythm: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        recipe = compile_visual_recipe(rhythm)
        return recipe, compile_visual_timeline(rhythm, recipe)

    return compile_artifacts, canonical_visual_bytes


def run_visual_benchmark(
    output_dir: str | Path | None = None,
    fixtures_dir: str | Path | None = None,
    *,
    cases: list[dict[str, Any]] | None = None,
    compile_artifacts: Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]] | None = None,
    canonical_bytes: Callable[[dict[str, Any]], bytes] | None = None,
) -> dict[str, Any]:
    """Analyze every fixture and score it; writes JSON + markdown reports.

    ``cases`` injects precompiled fixtures for tests. Otherwise each frozen
    fixture is compiled twice for the determinism gates, via
    ``compile_artifacts`` or the v0.8 compiler when importable.
    """
    if cases is None:
        cases = []
        default_compiler, default_canonical = _default_compiler()
        compiler = compile_artifacts if compile_artifacts is not None else default_compiler
        canonical_bytes = canonical_bytes if canonical_bytes is not None else default_canonical
        for name, rhythm in sorted(load_visual_fixtures(fixtures_dir).items()):
            recipe = timeline = None
            recipe_bytes_again = timeline_bytes_again = None
            if compiler is not None:
                recipe, timeline = compiler(rhythm)
                recipe_again, timeline_again = compiler(rhythm)
                if canonical_bytes is not None:
                    recipe_bytes_again = canonical_bytes(recipe_again)
                    timeline_bytes_again = canonical_bytes(timeline_again)
            cases.append(
                evaluate_visual_case(
                    name,
                    rhythm,
                    recipe,
                    timeline,
                    recipe_bytes_again=recipe_bytes_again,
                    timeline_bytes_again=timeline_bytes_again,
                    canonical_bytes=canonical_bytes,
                )
            )

    failed = sorted({gate for case in cases for gate in case.get("gates_failed", [])})
    results: dict[str, Any] = {
        "schema": VISUAL_BENCHMARK_SCHEMA,
        "pipeline_version": ANALYZER_VERSION,
        "recipe_version": RECIPE_VERSION,
        "motif_bank_version": MOTIF_BANK_VERSION,
        "gates": {
            "failed": failed,
            "pending": sorted(gate for gate in BLOCKING_GATES if gate not in ENFORCED_GATES),
            "recorded_only": list(RECORDED_ONLY_GATES),
            "policy": {"blocking": list(BLOCKING_GATES)},
        },
        "cases": cases,
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
    lines: list[str] = [
        "# BeatScope Visual Benchmark",
        "",
        f"- analyzer: pipeline {results['pipeline_version']}",
        f"- recipe version: {results['recipe_version']}",
        f"- gates failed: {len(results['gates']['failed'])}",
        f"- gates pending (later v0.8 commits): {len(results['gates']['pending'])}",
        "",
        "| fixture | scenes | transitions | gates failed |",
        "|---|---|---|---|",
    ]
    for case in results["cases"]:
        metrics = case.get("metrics") or {}
        tiling = metrics.get("tiling") or {}
        transitions = metrics.get("transitions") or {}
        lines.append(
            f"| {case['name']} | {tiling.get('scene_count', '-')} "
            f"| {transitions.get('transition_count', '-')} "
            f"| {', '.join(case.get('gates_failed', [])) or 'none'} |"
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "BLOCKING_GATES",
    "COMBINED_SPREAD_CAP",
    "COMPOSITION_CONTINUITY_EPS",
    "DIRECTOR_QUERY_P95_MS",
    "ENFORCED_GATES",
    "FRAME_BUDGET_P95_MS",
    "GATE_POLICY",
    "MAX_DRAW_CALLS",
    "RECORDED_ONLY_GATES",
    "REDUCED_MOTION_POSITION_MAX",
    "RENDERER_CPU_P95_MS",
    "SCENE_QUERY_P95_MS",
    "SCENE_STEADY_SPREAD_CAP",
    "SCENE_TWIST_CAP",
    "SETTLE_EXACTNESS",
    "TRANSITION_TIME_TOLERANCE_SECONDS",
    "TRANSITION_TWIST_CAP",
    "VISUAL_BENCHMARK_SCHEMA",
    "evaluate_visual_case",
    "identity_report",
    "load_visual_fixtures",
    "run_visual_benchmark",
    "scene_tiling_report",
    "transition_report",
    "write_markdown",
]
