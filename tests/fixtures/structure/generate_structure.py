"""Deterministic whole-song structure fixtures (v0.7 plan section 18).

Each fixture renders bar-synchronous sections whose harmony, timbre, rhythm,
and energy move independently, so the whole-song structure analyzer can be
scored against known section boundaries and neutral repeat families.

Generation is pure math - fixed note tables, no noise generators, no RNG, and
no wall-clock input - so one generator version renders byte-identical WAVs on
every platform. The truth manifest is committed beside this module
(``structure-truth.json``); the benchmark refuses to score fixtures whose
regenerated manifest differs from the committed bytes. Regenerate with:

    python -m fixtures.structure.generate_structure <output-dir>
"""
from __future__ import annotations

import json
import math
import wave
from pathlib import Path
from typing import Any

import numpy as np

try:  # the repo checkout puts ``tests/`` itself on sys.path
    from tests.fixtures.generate_audio import float_to_pcm16
except ImportError:  # pragma: no cover - conftest-style imports
    from fixtures.generate_audio import float_to_pcm16

GENERATOR_VERSION = "structure-fixtures-v1"
TRUTH_SCHEMA = "beatscope-structure-truth-1"
SR = 22050
STEPS_PER_BAR = 16

# --------------------------------------------------------------- synthesis

KICK_SECONDS = 0.13
SNARE_SECONDS = 0.12
HAT_SECONDS = 0.06

# Chords as low, mid, upper partials (Hz). A minor, C major, F major triads.
CHORD_A_M = (220.0, 261.6256, 329.6276)
CHORD_C = (261.6256, 329.6276, 391.9954)
CHORD_F = (174.6141, 220.0, 261.6256)

# Drum grids over the 16 steps of one 4/4 bar (step 0 = downbeat).
PATTERNS: dict[str, dict[str, tuple[int, ...]]] = {
    "four-floor": {"kick": (0, 4, 8, 12), "hat": (2, 6, 10, 14)},
    "backbeat": {"kick": (0, 8), "snare": (4, 12), "hat": (2, 6, 10, 14)},
    "syncopated": {"kick": (0, 3, 8, 11), "snare": (4, 12), "hat": (2, 6, 10, 14)},
    # Break bars keep one soft click per beat: near-silent for the energy
    # and density descriptors, but still enough of a pulse for the beat
    # tracker to stay locked across the break.
    "break": {"hat": (0, 4, 8, 12)},
}

# Section presets. ``brightness`` trades low for high spectral content; the
# pad always plays the section chord. BREAK bars stay audible but near-silent
# so both the legacy and the v0.7 break descriptors can see them.
SECTIONS: dict[str, dict[str, Any]] = {
    "A": {"chord": CHORD_A_M, "pattern": "four-floor", "brightness": 0.0, "gain": 1.0, "pad_scale": 1.0},
    "B": {"chord": CHORD_C, "pattern": "backbeat", "brightness": 1.0, "gain": 1.0, "pad_scale": 1.0},
    "C": {"chord": CHORD_F, "pattern": "syncopated", "brightness": 0.0, "gain": 1.0, "pad_scale": 1.0},
    "BREAK": {"chord": CHORD_A_M, "pattern": "break", "brightness": 0.0, "gain": 0.3, "pad_scale": 0.3},
}


def _bar_seconds(bpm: float) -> float:
    return (60.0 / bpm) * 4.0


def _mix(buffer: np.ndarray, start: int, wave_form: np.ndarray) -> None:
    end = min(len(buffer), start + len(wave_form))
    if start < 0 or end <= start:
        return
    buffer[start:end] += wave_form[: end - start]


def _add_kick(buffer: np.ndarray, start: int, level: float) -> None:
    n = int(round(KICK_SECONDS * SR))
    t = np.arange(n) / SR
    freq = 160.0 * np.exp(-t * 22.0) + 44.0
    phase = 2.0 * np.pi * np.cumsum(freq) / SR
    _mix(buffer, start, np.sin(phase) * np.exp(-t * 14.0) * level)


def _add_snare(buffer: np.ndarray, start: int, level: float) -> None:
    n = int(round(SNARE_SECONDS * SR))
    t = np.arange(n) / SR
    envelope = np.exp(-t * 30.0) * level
    _mix(buffer, start, (np.sin(2 * np.pi * 1900.0 * t) + 0.7 * np.sin(2 * np.pi * 2600.0 * t)) * envelope)


def _add_hat(buffer: np.ndarray, start: int, level: float) -> None:
    n = int(round(HAT_SECONDS * SR))
    t = np.arange(n) / SR
    _mix(buffer, start, np.sin(2 * np.pi * 7800.0 * t) * np.exp(-t * 70.0) * level)


def _render_bar(
    bpm: float,
    chord: tuple[float, ...],
    pattern: str,
    brightness: float,
    gain: float,
    pad_scale: float,
) -> np.ndarray:
    """Render exactly one 4/4 bar of one section on the step grid."""
    bar_len = int(round(_bar_seconds(bpm) * SR))
    buffer = np.zeros(bar_len, dtype=np.float64)
    duration = bar_len / SR

    # Sustained chord pad with a short fade at each bar edge. The pad sits
    # above the drum bed so the harmony view sees pitch content, not just
    # broadband transients (real mixes carry chords at comparable level).
    t = np.arange(bar_len) / SR
    fade = 0.35
    envelope = np.minimum(1.0, np.minimum(t / fade, (duration - t) / fade))
    envelope = np.clip(envelope, 0.0, 1.0)
    pad = np.zeros(bar_len, dtype=np.float64)
    for freq in chord:
        pad += np.sin(2.0 * np.pi * freq * t)
        pad += brightness * 0.5 * np.sin(2.0 * np.pi * freq * 3.0 * t)
    pad *= 0.11 * gain * pad_scale * envelope / len(chord)
    buffer += pad

    grid = PATTERNS[pattern]
    step_seconds = _bar_seconds(bpm) / STEPS_PER_BAR
    levels = {
        "kick": gain * (0.65 - 0.20 * brightness),
        "snare": gain * (0.42 + 0.10 * brightness),
        "hat": gain * (0.10 + 0.30 * brightness),
    }
    adders = {"kick": _add_kick, "snare": _add_snare, "hat": _add_hat}
    for instrument, steps in grid.items():
        for step in steps:
            start = int(round(step * step_seconds * SR))
            adders[instrument](buffer, start, levels[instrument])
    return buffer


# ------------------------------------------------------------ case table

def _span(bars: int, section: str, *, bpm: float = 120.0, family: str | None = None, **overrides: Any) -> dict[str, Any]:
    """One span of a case: ``section`` picks the content, ``family`` the truth
    label (defaults to the section name, overridden for single-knob cases)."""
    spec = dict(SECTIONS[section])
    spec.update(overrides)
    return {"bars": bars, "family": family or section, "bpm": bpm, **spec}


CASES: dict[str, dict[str, Any]] = {
    "structure-aba": {
        "purpose": "A-B-A form; harmony, timbre, and rhythm change together",
        "spans": [_span(8, "A"), _span(8, "B"), _span(8, "A")],
    },
    "structure-abacb": {
        "purpose": "five-section rondo; every family repeats at least once",
        "spans": [_span(6, "A"), _span(6, "B"), _span(6, "A"), _span(6, "C"), _span(6, "B")],
    },
    "structure-energy-only": {
        "purpose": "identical arrangement; only the section gain changes",
        "spans": [
            _span(8, "A", family="X", gain=1.0),
            _span(8, "A", family="Y", gain=0.45),
            _span(8, "A", family="X", gain=1.0),
        ],
    },
    "structure-harmony-only": {
        "purpose": "constant rhythm and timbre; only the chord changes",
        "spans": [
            _span(8, "A"),
            _span(8, "B", pattern="four-floor", brightness=0.0),
            _span(8, "A"),
        ],
    },
    "structure-rhythm-only": {
        "purpose": "constant chord and timbre; only the drum pattern changes",
        "spans": [
            _span(8, "A"),
            _span(8, "B", chord=CHORD_A_M, brightness=0.0),
            _span(8, "A"),
        ],
    },
    "structure-break": {
        "purpose": "near-silent break bars between two identical sections",
        "spans": [_span(8, "A"), _span(4, "BREAK"), _span(8, "A")],
    },
    "structure-monotony": {
        "purpose": "one unchanging section; the analyzer must not invent boundaries",
        "spans": [_span(24, "A")],
    },
    "structure-short": {
        "purpose": "six bars only; too short to segment and must not crash",
        "spans": [_span(6, "A")],
    },
    "structure-tempo-change-repeat": {
        "purpose": "same material at 120/140/120 BPM; bar-synced features must stay one family",
        "spans": [_span(8, "A", bpm=120.0), _span(8, "A", bpm=140.0), _span(8, "A", bpm=120.0)],
    },
    "structure-drift": {
        "purpose": "continuous timbre ramp across 24 bars; drift, not a boundary",
        "spans": [_span(24, "A", brightness=0.0, brightness_end=1.0)],
    },
}


def case_truth(name: str) -> dict[str, Any]:
    """Truth manifest entry for one case, derived from its span table."""
    spec = CASES[name]
    boundaries: list[dict[str, int]] = []
    segments: list[dict[str, Any]] = []
    bar = 0
    for span in spec["spans"]:
        start_bar = bar + 1
        bar += int(span["bars"])
        if start_bar > 1:
            boundaries.append({"bar": start_bar})
        segments.append({"start_bar": start_bar, "end_bar": bar, "family": span["family"]})
    return {
        "purpose": spec["purpose"],
        "bars": bar,
        "boundaries": boundaries,
        "segments": segments,
    }


def build_manifest() -> dict[str, Any]:
    return {
        "schema": TRUTH_SCHEMA,
        "generator_version": GENERATOR_VERSION,
        "sample_rate": SR,
        "cases": {name: case_truth(name) for name in CASES},
    }


# -------------------------------------------------------------- rendering

def render_case(name: str) -> np.ndarray:
    """Render one case's full arrangement as float64 mono at SR."""
    spec = CASES[name]
    chunks: list[np.ndarray] = []
    for span in spec["spans"]:
        bars = int(span["bars"])
        start_brightness = float(span.get("brightness", 0.0))
        end_brightness = float(span.get("brightness_end", start_brightness))
        for index in range(bars):
            fraction = index / (bars - 1) if bars > 1 else 0.0
            brightness = start_brightness + (end_brightness - start_brightness) * fraction
            chunks.append(_render_bar(
                float(span["bpm"]),
                tuple(span["chord"]),
                str(span["pattern"]),
                brightness,
                float(span["gain"]),
                float(span.get("pad_scale", 1.0)),
            ))
    return np.concatenate(chunks)


def write_wav(path: Path, signal: np.ndarray) -> None:
    """Write mono 16-bit PCM with the pinned conversion rule."""
    pcm = float_to_pcm16(signal)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(pcm.tobytes())


def generate_all(output_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Generate every fixture WAV plus the truth manifest into ``output_dir``."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    for name in CASES:
        audio_path = out / f"{name}.wav"
        write_wav(audio_path, render_case(name))
        results[name] = {"audio": str(audio_path), "truth": case_truth(name)}
    manifest_text = json.dumps(build_manifest(), indent=2, ensure_ascii=False) + "\n"
    (out / "structure-truth.json").write_text(manifest_text, encoding="utf-8", newline="\n")
    return results


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m fixtures.structure.generate_structure <output-dir>")
        return 2
    generate_all(sys.argv[1])
    print(f"Generated {len(CASES)} structure fixtures in {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
