"""The built wheel must carry the visual instrument and handoff assets.

The app is zero-build in the browser, but the wheel packages ``beatscope/web``
and the export runtime as package data; a packaging regression that silently
drops a module would ship a player without its particle instrument or a
handoff without its self-verification probe (v0.9 plan section 4).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_MODULES = [
    "beatscope/web/visual-stage.js",
    "beatscope/web/particle-field.js",
    "beatscope/web/particle-geometry.js",
    "beatscope/web/particle-shaders.js",
    "beatscope/web/webmcp/schemas.js",
    "beatscope/web/webmcp/queries.js",
    "beatscope/web/webmcp/actions.js",
    "beatscope/web/webmcp/responses.js",
    "beatscope/web/webmcp/register.js",
    "beatscope/runtime/consumer-probe.js",
    "beatscope/runtime/consumer-browser.mjs",
    "beatscope/runtime/consumer-offline.mjs",
]

# Release policy (v0.10): the frozen demo audio/fixtures are static-host
# assets, not wheel payload (see pyproject package-data comment).
EXCLUDED_MODULES = [
    "beatscope/web/demo/audio.mp3",
]


def test_wheel_contains_particle_modules(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "wheel", ".",
            "--no-deps", "--no-build-isolation",
            "--wheel-dir", str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"wheel build failed:\n{result.stdout}\n{result.stderr}"

    wheels = list(tmp_path.glob("beatscope-*.whl"))
    assert wheels, f"no wheel produced in {tmp_path}"

    names = zipfile.ZipFile(wheels[0]).namelist()
    missing = [name for name in REQUIRED_MODULES if name not in names]
    assert not missing, f"modules missing from the built wheel: {missing}"
    leaked = [name for name in EXCLUDED_MODULES if name in names]
    assert not leaked, f"demo assets must stay out of the wheel: {leaked}"
