"""The built wheel must carry the v0.8.0 visual instrument modules.

The app is zero-build in the browser, but the wheel packages ``beatscope/web``
as package data; a packaging regression that silently drops the new modules
would ship a player without its particle instrument.
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
