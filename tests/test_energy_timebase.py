"""Energy-curve time-base regression tests.

The serialized ``energy.fps`` must describe frame times exactly: frame i covers
``i * hop / sr`` seconds. Rounding fps to an integer while keeping the original
samples silently drifts the curve against onsets (~0.46 s by the 5-minute mark
at the default 44100/256). These tests pin the Python serializers and the
JavaScript consumer to one time base.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pytest

from beatscope.backends.lightweight import compress_energy
from beatscope.models import AnalysisConfig
from beatscope.schema import validate_rhythm_v4

REPO_ROOT = Path(__file__).resolve().parent.parent


def _energy_payload(fps: float, frame_count: int) -> dict:
    return {
        "fps": fps,
        "start": 0.0,
        "bands": {name: [0.0] * frame_count for name in ("all", "low", "mid", "high")},
    }


def _v4_project(energy: dict) -> dict:
    return {
        "schema_version": "4.0",
        "project_id": "a1b2c3d4e5f6",
        "source": {
            "display_name": "s.wav",
            "duration": 120.0,
            "sample_rate": 44100,
            "channels": 1,
            "sha256": "ab" * 32,
        },
        "analysis": {
            "backend": "lightweight",
            "pipeline_version": "0.12.0",
            "created_at": "2026-09-17T00:00:00Z",
            "warnings": [],
            "separation_used": False,
            "provenance": {"beats": {"method": "test"}, "onsets": {"method": "test"}},
        },
        "tempo": {
            "global_bpm": 120.0,
            "segments": [{"start": 0.0, "end": 120.0, "bpm": 120.0, "method": "test", "score": None}],
        },
        "meter": {"numerator": 4, "denominator": 4},
        "grid": {"origin": 0.0, "default_subdivision": 16, "bars": 3},
        "beats": [],
        "onsets": [],
        "energy": energy,
        "patterns": {"method": "test", "bars": []},
        "cues": {"accent": [], "impact": [], "scale": [], "flow": [], "flash": [], "bloom": []},
        "exports": {},
    }


@pytest.mark.parametrize("minutes", [1.0, 5.0, 10.0])
def test_serialized_energy_time_does_not_drift(minutes):
    """A peak encoded by the Python writer is read back at the same time."""
    config = AnalysisConfig()
    sr, hop = config.sample_rate, config.hop_length
    frame = int(minutes * 60 * sr / hop)
    bands = {name: np.zeros(frame + 1) for name in ("all", "low", "mid", "high")}
    for values in bands.values():
        values[frame] = 1.0
    energy = compress_energy(bands, sr, hop)
    peak_frame = energy["bands"]["all"].index(1.0)
    drift = peak_frame / energy["fps"] - frame * hop / sr
    assert abs(drift) < 0.01


def test_compress_energy_keeps_exact_frame_rate():
    config = AnalysisConfig()
    novelty = {name: np.zeros(4) for name in ("all", "low", "mid", "high")}
    energy = compress_energy(novelty, config.sample_rate, config.hop_length)
    assert energy["fps"] == pytest.approx(config.sample_rate / config.hop_length)
    assert energy["start"] == 0.0
    assert set(energy["bands"]) == {"all", "low", "mid", "high"}


def test_validate_rejects_invalid_fps_values():
    """The validator must refuse non-finite or non-numeric fps labels.

    Time-base agreement between fps and the frame count is guaranteed by the
    writers (see the serializer tests above); the validator's job is to keep
    corrupt or hand-edited data out of interpolation.
    """
    for bad_fps in (0, -172, True, float("nan"), float("inf"), "172"):
        energy = _energy_payload(fps=bad_fps, frame_count=2)
        assert any("fps" in error for error in validate_rhythm_v4(_v4_project(energy)))


def test_validate_accepts_exact_fractional_fps():
    energy = _energy_payload(fps=44100 / 256, frame_count=int(120 * 44100 / 256) + 1)
    energy["bands"]["low"][10] = 0.5
    assert validate_rhythm_v4(_v4_project(energy)) == []


@pytest.mark.parametrize("bad_fps", [0, -172, True, float("nan"), float("inf"), "172"])
def test_validate_rejects_invalid_fps(bad_fps):
    energy = _energy_payload(fps=bad_fps, frame_count=2)
    assert any("fps" in error for error in validate_rhythm_v4(_v4_project(energy)))


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -0.5, 1.5, "0.5", True])
def test_validate_rejects_invalid_band_values(bad_value):
    energy = _energy_payload(fps=44100 / 256, frame_count=3)
    energy["bands"]["low"][1] = bad_value
    errors = validate_rhythm_v4(_v4_project(energy))
    assert any("bands" in error for error in errors)


def test_runtime_energy_time_parity_with_python(tmp_path):
    """Read actual Python JSON in JS, using an independent sample-clock oracle."""
    config = AnalysisConfig()
    sr, hop = config.sample_rate, config.hop_length
    frame = 86132  # ~500 s at 44100/256
    novelty = {name: np.zeros(frame + 1) for name in ("all", "low", "mid", "high")}
    for values in novelty.values():
        values[frame] = 1.0
    payload_path = tmp_path / "energy.json"
    payload_path.write_text(json.dumps({"energy": compress_energy(novelty, sr, hop)}), encoding="utf-8")
    expected_time = frame * hop / sr

    # Temporary paths may be outside the repository and contain spaces (Windows).
    runtime_url = (REPO_ROOT / "beatscope" / "runtime" / "runtime.js").as_uri()
    script_path = tmp_path / "energy-parity.mjs"
    script_path.write_text(
        f"import {{ energyAt }} from {json.dumps(runtime_url)};\n"
        "import { readFileSync } from 'node:fs';\n"
        "const map = JSON.parse(readFileSync(process.argv[2], 'utf8'));\n"
        f"const frameTime = {expected_time!r};\n"
        "const recovered = ['all', 'low', 'mid', 'high'].map(band => {\n"
        "  let lo = 0, hi = frameTime + 5;\n"
        "  for (let i = 0; i < 80; i++) {\n"
        "    const mid = (lo + hi) / 2;\n"
        "    if (energyAt(map, mid, band) > 0.5) hi = mid; else lo = mid;\n"
        "  }\n"
        "  return (lo + hi) / 2;\n"
        "});\n"
        "console.log(JSON.stringify(recovered));\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(script_path), str(payload_path)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"Node energy parity failed:\n{result.stdout}\n{result.stderr}"
    recovered_times = json.loads(result.stdout)
    assert len(recovered_times) == 4
    for recovered_time in recovered_times:
        assert math.isfinite(recovered_time)
        assert abs(recovered_time - expected_time) < 0.01
