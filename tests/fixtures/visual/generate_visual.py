"""Deterministic visual fixture baselines (v0.8 plan section 17).

The checked-in ``visual-*.rhythm.json`` files are frozen Rhythm IR projects
derived once from the deterministic structure fixtures
(``tests/fixtures/structure``) and stripped of wall-clock fields. Each file
is a valid v4 project whose ``patterns.segments``/``patterns.boundaries``
facts feed the v0.8 visual compiler; ``visual-legacy`` intentionally drops
the structure payload to cover legacy mode.

This module verifies the frozen set instead of regenerating audio: it
re-serializes every fixture, validates it against the v4 schema, compiles
the visual artifacts twice (once the v0.8 compiler exists), asserts byte
equality, and records SHA-256 hashes in ``visual-fixtures.json``.

The committed manifest is the acceptance baseline. Regeneration refuses to
overwrite it without ``--accept-baseline``, so a fixture or compiler change
can never silently move the visual gates:

    python -m tests.fixtures.visual.generate_visual [--accept-baseline]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from beatscope.schema import validate_rhythm_v4

GENERATOR_VERSION = "visual-fixtures-v1"
MANIFEST_SCHEMA = "beatscope-visual-fixtures-1"

FIXTURE_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = FIXTURE_DIR / "visual-fixtures.json"

# The 13 required projects (v0.8 plan section 17). A missing or renamed
# fixture is a baseline change and must go through --accept-baseline.
FIXTURE_NAMES = (
    "visual-aba",
    "visual-aba-prime",
    "visual-rondo",
    "visual-break",
    "visual-driver-harmony",
    "visual-driver-rhythm",
    "visual-driver-energy",
    "visual-driver-timbre",
    "visual-neutral-boundary",
    "visual-dense",
    "visual-variable-tempo",
    "visual-legacy",
    "visual-short",
)


def fixture_path(name: str) -> Path:
    return FIXTURE_DIR / f"{name}.rhythm.json"


def rhythm_bytes(name: str) -> bytes:
    return fixture_path(name).read_bytes()


def load_rhythm(name: str) -> dict[str, Any]:
    return json.loads(rhythm_bytes(name).decode("utf-8"))


def load_rhythm_fixtures() -> dict[str, dict[str, Any]]:
    """Every frozen fixture, keyed by name, validated against the v4 schema."""
    fixtures: dict[str, dict[str, Any]] = {}
    for name in FIXTURE_NAMES:
        rhythm = load_rhythm(name)
        errors = validate_rhythm_v4(rhythm)
        if errors:
            raise SystemExit(
                f"fixture {name} is not a valid v4 project:\n"
                + "\n".join(f"- {error}" for error in errors)
            )
        fixtures[name] = rhythm
    return fixtures


def compile_case(rhythm: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Compile one fixture into ``(recipe, timeline)`` with a double-run check.

    Wired to ``beatscope.visual_recipe`` from the compiler commit onward.
    Before that commit the artifact hashes stay ``null`` and only the frozen
    Rhythm IR baselines are verified.
    """
    try:
        from beatscope.visual_recipe import (  # noqa: F401 - lands with the compiler commit
            canonical_visual_bytes,
            compile_visual_recipe,
            compile_visual_timeline,
        )
    except ImportError:
        return None, None
    recipe = compile_visual_recipe(rhythm)
    timeline = compile_visual_timeline(rhythm, recipe)
    recipe_again = compile_visual_recipe(rhythm)
    timeline_again = compile_visual_timeline(rhythm, recipe_again)
    if (
        canonical_visual_bytes(recipe_again) != canonical_visual_bytes(recipe)
        or canonical_visual_bytes(timeline_again) != canonical_visual_bytes(timeline)
    ):
        raise SystemExit(f"visual compilation is not byte-deterministic for project {rhythm.get('project_id')}")
    return recipe, timeline


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_manifest() -> dict[str, Any]:
    """Recompute the manifest from the frozen fixtures on disk."""
    entries: dict[str, dict[str, Any]] = {}
    for name, rhythm in load_rhythm_fixtures().items():
        recipe, timeline = compile_case(rhythm)
        entries[name] = {
            "project_id": rhythm["project_id"],
            "rhythm_sha256": _sha256(rhythm_bytes(name)),
            "recipe_sha256": _sha256(canonical_bytes(recipe)) if recipe is not None else None,
            "timeline_sha256": _sha256(canonical_bytes(timeline)) if timeline is not None else None,
        }
    return {
        "schema": MANIFEST_SCHEMA,
        "generator_version": GENERATOR_VERSION,
        "fixtures": entries,
    }


def canonical_bytes(value: dict[str, Any]) -> bytes:
    """UTF-8 LF JSON with stable formatting - the manifest hashing form."""
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def baseline_differences(rebuilt: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Human-readable differences between a rebuilt manifest and the baseline."""
    differences: list[str] = []
    if rebuilt.get("schema") != baseline.get("schema"):
        differences.append(f"schema: {baseline.get('schema')!r} -> {rebuilt.get('schema')!r}")
    if rebuilt.get("generator_version") != baseline.get("generator_version"):
        differences.append(
            f"generator_version: {baseline.get('generator_version')!r} -> {rebuilt.get('generator_version')!r}"
        )
    baseline_fixtures = baseline.get("fixtures") if isinstance(baseline.get("fixtures"), dict) else {}
    rebuilt_fixtures = rebuilt.get("fixtures") if isinstance(rebuilt.get("fixtures"), dict) else {}
    for name in sorted(set(baseline_fixtures) - set(rebuilt_fixtures)):
        differences.append(f"fixture removed: {name}")
    for name in sorted(set(rebuilt_fixtures) - set(baseline_fixtures)):
        differences.append(f"fixture added: {name}")
    for name in sorted(set(rebuilt_fixtures) & set(baseline_fixtures)):
        before, after = baseline_fixtures[name], rebuilt_fixtures[name]
        for field in ("project_id", "rhythm_sha256", "recipe_sha256", "timeline_sha256"):
            if before.get(field) != after.get(field):
                differences.append(f"{name}.{field}: {before.get(field)!r} -> {after.get(field)!r}")
    return differences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--accept-baseline",
        action="store_true",
        help="overwrite the committed manifest after an intentional fixture or compiler change",
    )
    args = parser.parse_args(argv)

    rebuilt = build_manifest()
    if not MANIFEST_PATH.exists():
        if not args.accept_baseline:
            print(f"No visual fixture baseline recorded at {MANIFEST_PATH.name}; pass --accept-baseline to record it.")
            return 2
        MANIFEST_PATH.write_bytes(canonical_bytes(rebuilt))
        print(f"Recorded visual fixture baseline for {len(rebuilt['fixtures'])} fixtures.")
        return 0

    baseline = json.loads(MANIFEST_PATH.read_bytes().decode("utf-8"))
    differences = baseline_differences(rebuilt, baseline)
    if not differences:
        print(f"Visual fixture baseline unchanged ({len(rebuilt['fixtures'])} fixtures).")
        return 0
    if not args.accept_baseline:
        print("Visual fixture baseline differs; refusing to overwrite without --accept-baseline:")
        for difference in differences:
            print(f"- {difference}")
        return 2
    MANIFEST_PATH.write_bytes(canonical_bytes(rebuilt))
    print(f"Accepted new visual fixture baseline ({len(differences)} intentional changes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
