"""WebMCP static demo gates (v0.10 plan sections 17.4, 18.4).

The demo must be a self-contained static bundle: the frozen demo fixtures
locked by hash, a project that passes Rhythm IR v4 validation, no private
paths anywhere, every HTML/JS reference resolvable inside the bundle, and
byte-stable rebuilds (``SOURCE_DATE_EPOCH`` drives build-info.json).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_webmcp_demo.py"
DEMO_ROOT = REPO_ROOT / "beatscope" / "web" / "demo"

EXPECTED_FILES = (
    "index.html",
    "style.css",
    "app.js",
    "webmcp/schemas.js",
    "webmcp/queries.js",
    "webmcp/actions.js",
    "webmcp/responses.js",
    "webmcp/register.js",
    "runtime/runtime.js",
    "runtime/visual-profile.js",
    "runtime/scene-director.js",
    "demo/project.json",
    "demo/visual-recipe.json",
    "demo/visual-timeline.json",
    "demo/audio.mp3",
    "demo/fixture-lock.json",
    "build-info.json",
)


def _build(output: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output", str(output)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"demo build failed:\n{result.stdout}\n{result.stderr}"


def _build_with_epoch(output: Path, epoch: str) -> None:
    env = dict(os.environ, SOURCE_DATE_EPOCH=epoch)
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output", str(output)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"demo build failed:\n{result.stdout}\n{result.stderr}"


def test_demo_fixture_lock_matches_files() -> None:
    lock = json.loads((DEMO_ROOT / "fixture-lock.json").read_text(encoding="utf-8"))
    assert lock["schema"] == "beatscope-webmcp-demo-fixture-lock-1"
    locked_names = set()
    for entry in lock["files"].values():
        path = DEMO_ROOT / entry["file"]
        assert path.is_file(), f"locked file missing: {entry['file']}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == entry["sha256"], f"fixture drift for {entry['file']}"
        locked_names.add(entry["file"])
    assert locked_names == {"project.json", "visual-recipe.json", "visual-timeline.json", "audio.mp3"}


def test_demo_project_passes_rhythm_v4_validation() -> None:
    from beatscope.schema import validate_rhythm_v4

    project = json.loads((DEMO_ROOT / "project.json").read_text(encoding="utf-8"))
    errors = validate_rhythm_v4(project)
    assert not errors, f"demo project violates Rhythm IR v4: {errors}"
    segments = project["patterns"]["segments"]
    assert len(project["patterns"]["boundaries"]) >= 2, "demo needs two structural boundaries"
    families = [segment["family"] for segment in segments]
    assert len(set(families)) < len(families), "demo needs a repeated structure family"


def test_demo_audio_exists_and_size_is_controlled() -> None:
    audio = DEMO_ROOT / "audio.mp3"
    assert audio.is_file()
    size = audio.stat().st_size
    assert 0 < size <= 3_000_000, f"demo audio must stay small, got {size} bytes"


def test_demo_project_has_no_private_paths() -> None:
    project_text = (DEMO_ROOT / "project.json").read_text(encoding="utf-8")
    forbidden = (
        re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]"),
        re.compile(r"\.beatscope-cache"),
        re.compile(r"/Users/"),
        re.compile(r"source\.path"),
    )
    for pattern in forbidden:
        assert not pattern.search(project_text), f"private path pattern {pattern.pattern!r} leaked into project.json"


def test_build_output_is_complete() -> None:
    output = REPO_ROOT / "build" / "webmcp-demo-test"
    try:
        _build(output)
        missing = [name for name in EXPECTED_FILES if not (output / name).is_file()]
        assert not missing, f"static demo build is incomplete: {missing}"
        build_info = json.loads((output / "build-info.json").read_text(encoding="utf-8"))
        assert build_info["schema"] == "beatscope-webmcp-demo-build-info-1"
        assert build_info["commit"]
        assert build_info["version"]
    finally:
        import shutil

        shutil.rmtree(output, ignore_errors=True)


def test_build_html_and_js_references_resolve() -> None:
    output = REPO_ROOT / "build" / "webmcp-demo-test"
    try:
        _build(output)
        # index.html references must land inside the bundle.
        html = (output / "index.html").read_text(encoding="utf-8")
        for attr_value in re.findall(r'(?:src|href)="([^"]+)"', html):
            if attr_value.startswith(("http://", "https://", "data:")):
                continue
            relative = attr_value.lstrip("/").split("#", 1)[0].split("?", 1)[0]
            if not relative:
                continue
            assert (output / relative).is_file(), f"index.html references missing file {attr_value}"
        # Every static JS import must land inside the bundle (this is what
        # keeps the ../runtime/* URL mapping honest in a static host).
        # Resolution uses URL semantics under a non-root deployment prefix,
        # like GitHub Pages. No import may escape /beatscope/.
        import urllib.parse

        for js_file in list(output.glob("*.js")) + list((output / "webmcp").glob("*.js")) + list((output / "runtime").glob("*.js")):
            text = js_file.read_text(encoding="utf-8")
            base = "http://demo/beatscope/" + js_file.relative_to(output).as_posix()
            for specifier in re.findall(r"""from\s+['"]([^'"]+)['"]""", text) + re.findall(r"""import\s+['"]([^'"]+)['"]""", text):
                if not specifier.startswith("."):
                    continue
                resolved = urllib.parse.urljoin(base, specifier)
                assert resolved.startswith("http://demo/beatscope/"), f"{js_file.name} import escapes hosting prefix: {specifier}"
                target = resolved.removeprefix("http://demo/beatscope/")
                assert (output / target).is_file(), f"{js_file.name} imports missing {specifier}"
    finally:
        import shutil

        shutil.rmtree(output, ignore_errors=True)


def test_double_build_is_byte_stable() -> None:
    first = REPO_ROOT / "build" / "webmcp-demo-test-a"
    second = REPO_ROOT / "build" / "webmcp-demo-test-b"
    try:
        _build_with_epoch(first, "1788360000")
        _build_with_epoch(second, "1788360000")
        first_files = {path.relative_to(first): path.read_bytes() for path in first.rglob("*") if path.is_file()}
        second_files = {path.relative_to(second): path.read_bytes() for path in second.rglob("*") if path.is_file()}
        assert set(first_files) == set(second_files), "two builds produced different file trees"
        for name, payload in first_files.items():
            assert payload == second_files[name], f"{name} is not byte-stable across builds"
    finally:
        import shutil

        shutil.rmtree(first, ignore_errors=True)
        shutil.rmtree(second, ignore_errors=True)
