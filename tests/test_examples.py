"""Example-consumer contract tests (v0.9 plan sections 7, 9, and 18.1).

The reference consumers are the standing proof that one handoff package
drives different visual stacks through the same deterministic frame
contract. These tests hold each example to its own declaration: the
package it points to, the clock it claims, the dependencies it may
have, and the static hygiene layers of the validator. Nothing here
requires an installed browser; the browser layer stays honestly
`unavailable` until tooling is wired in a later release.
"""
from __future__ import annotations

import json
import shutil
from functools import lru_cache
from pathlib import Path

import pytest

from beatscope.consumer_contract import (
    CHECKPOINT_SCHEMA,
    FIXTURE_LOCK_SCHEMA,
    validate_checkpoints,
    validate_fixture_lock,
)
from beatscope.consumer_validation import STATUS_PASSED, validate_consumer

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
SHARED_DIR = EXAMPLES_DIR / "shared"
FIXTURE_DIR = SHARED_DIR / "fixture.beatscope"
CHECKPOINTS_PATH = SHARED_DIR / "checkpoints.json"
LOCK_PATH = SHARED_DIR / "fixture-lock.json"

EXAMPLE_NAMES = ("canvas-particles", "threejs-geometry", "remotion-composition")

# Dependencies stay example-local and pinned exact. Nothing example-side
# may depend on the beatscope core package, and no unpinned range is
# allowed into a reference consumer.
ALLOWED_DEPENDENCIES = {
    "canvas-particles": {},
    "threejs-geometry": {"three": "0.169.0"},
    "remotion-composition": {
        "@remotion/cli": "4.0.520",
        "react": "19.2.8",
        "react-dom": "19.2.8",
        "remotion": "4.0.520",
    },
}

# Where each example's clock actually lives, per declaration.
CLOCK_SOURCES = {
    "canvas-particles": ("app.js",),
    "threejs-geometry": ("src/main.js",),
    "remotion-composition": ("src/BeatScopeScope.tsx",),
}

# Runtime fingerprints: files with these names must exist only inside
# the handoff package, never as copies inside an example.
RUNTIME_FINGERPRINTS = (
    "beatscope-runtime.js",
    "visual-state.js",
    "scene-director.js",
    "worker-example.js",
    "consumer-probe.js",
    "visual-recipe-data.js",
    "visual-timeline-data.js",
)


def _node_missing() -> bool:
    return shutil.which("node") is None


def _declaration(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name / "beatscope-consumer.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _report(name: str, browser: bool, offline: bool) -> dict:
    return validate_consumer(
        EXAMPLES_DIR / name,
        browser=browser,
        offline=offline,
        checkpoints=CHECKPOINTS_PATH,
    )


def _checks(name: str, browser: bool, offline: bool) -> dict[str, dict]:
    return {check["name"]: check for check in _report(name, browser, offline)["checks"]}


def _flagged_flags(name: str) -> tuple[bool, bool]:
    capabilities = _declaration(name)["capabilities"]
    return capabilities["playback"] is True, capabilities["offline_frame"] is True


# --------------------------------------------------------- declarations


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_declaration_validates_and_paths_resolve_inside_roots(name: str):
    checks = _checks(name, False, False)
    assert checks["declaration"]["status"] == STATUS_PASSED, checks["declaration"]["errors"]
    declaration = _declaration(name)
    package_path = (EXAMPLES_DIR / name / declaration["package_path"]).resolve()
    entry_page = (EXAMPLES_DIR / name / declaration["entry_page"]).resolve()
    assert package_path.is_dir() and FIXTURE_DIR.resolve() == package_path
    assert entry_page.is_file() and entry_page.is_relative_to((EXAMPLES_DIR / name).resolve())


def test_interactive_consumers_declare_the_debug_hook():
    for name in ("canvas-particles", "threejs-geometry"):
        declaration = _declaration(name)
        assert declaration["capabilities"]["playback"] is True
        assert declaration["debug_hook"] == "__BEATSCOPE_CONSUMER__"


def test_offline_consumer_promises_no_debug_hook():
    declaration = _declaration("remotion-composition")
    assert declaration["capabilities"]["playback"] is False
    assert declaration["capabilities"]["offline_frame"] is True
    assert declaration.get("debug_hook") in (None, "")


# ---------------------------------------------------------------- clocks


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_each_example_uses_its_declared_clock(name: str):
    declaration = _declaration(name)
    for relative in CLOCK_SOURCES[name]:
        assert (EXAMPLES_DIR / name / relative).is_file(), relative
    joined = "\n".join(
        (EXAMPLES_DIR / name / relative).read_text(encoding="utf-8") for relative in CLOCK_SOURCES[name]
    )
    if declaration["clock"] == "audio.currentTime":
        assert "audio.currentTime" in joined, f"{name} must read audio.currentTime"
    else:
        assert declaration["clock"] == "frame/fps"
        assert "useCurrentFrame" in joined, f"{name} must derive time from useCurrentFrame"
        for path in (EXAMPLES_DIR / name).rglob("*.js"):
            assert "audio.currentTime" not in path.read_text(encoding="utf-8"), path


# ------------------------------------------------- static hygiene layers


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_static_layer_passes(name: str):
    checks = _checks(name, False, False)
    assert checks["static"]["status"] == STATUS_PASSED, checks["static"]["errors"]


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_no_runtime_fingerprints_are_copied_into_examples(name: str):
    example_dir = EXAMPLES_DIR / name
    for fingerprint in RUNTIME_FINGERPRINTS:
        assert not (example_dir / fingerprint).exists(), f"copied runtime file: {fingerprint}"
        nested = list(example_dir.rglob(fingerprint))
        assert not nested, f"copied runtime file: {nested}"


# ----------------------------------------------------------- dependencies


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_dependencies_remain_example_local_and_pinned(name: str):
    manifest_path = EXAMPLES_DIR / name / "package.json"
    allowed = ALLOWED_DEPENDENCIES[name]
    if not allowed:
        assert not manifest_path.exists(), f"{name} is zero-build and must not ship dependencies"
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest.get("private") is True
    dependencies = manifest.get("dependencies", {})
    assert dependencies == allowed, f"{name} dependencies drifted from the pinned allowlist"
    assert (EXAMPLES_DIR / name / "package-lock.json").is_file(), "lockfile must be committed"
    for pinned in dependencies.values():
        assert pinned == pinned.strip(" ^~"), f"dependency must be pinned exact: {pinned}"


def test_no_example_depends_on_the_beatscope_core_package():
    for name in EXAMPLE_NAMES:
        manifest_path = EXAMPLES_DIR / name / "package.json"
        if not manifest_path.exists():
            continue
        dependencies = json.loads(manifest_path.read_text(encoding="utf-8")).get("dependencies", {})
        assert "beatscope" not in dependencies, name


# ------------------------------------------------- required-layer status


@pytest.mark.skipif(_node_missing(), reason="node is required for the packaged probe")
@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_required_automatable_layers_pass_with_honest_gaps(name: str):
    browser, offline = _flagged_flags(name)
    checks = _checks(name, browser, offline)
    for layer in ("declaration", "handoff", "static"):
        assert checks[layer]["status"] == STATUS_PASSED, (layer, checks[layer]["errors"])
    assert checks["node-probe"]["status"] == STATUS_PASSED, checks["node-probe"]["errors"]
    for layer in ("browser", "offline"):
        # Requested but not wired in this release: honestly unavailable.
        # Not declared: skipped. Both are allowed; failure never is.
        assert checks[layer]["status"] in ("passed", "unavailable", "skipped"), (layer, checks[layer]["errors"])


# ------------------------------------------------- fixture lock agreement


def test_fixture_lock_and_checkpoint_hashes_agree():
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["schema"] == FIXTURE_LOCK_SCHEMA
    assert validate_fixture_lock(lock) == []
    checkpoints = json.loads(CHECKPOINTS_PATH.read_text(encoding="utf-8"))
    assert checkpoints["schema"] == CHECKPOINT_SCHEMA
    members = {
        path.relative_to(FIXTURE_DIR).as_posix(): path.read_bytes()
        for path in sorted(FIXTURE_DIR.rglob("*"))
        if path.is_file()
    }
    assert validate_checkpoints(checkpoints, members) == []
