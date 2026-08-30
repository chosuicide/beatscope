"""Deterministic synthetic audio fixtures with exact ground truth.

Every test WAV is generated from code (no committed binaries) so snapshot
tests and the benchmark can compare analyzer output against known beat and
onset times. Generator version 2 adds the variable-tempo family
(gradual drift, micro drift, octave trap) and pins the PCM conversion,
sample rate, seed, and frame count in the truth so future jitter cases
cannot become platform-dependent. Run directly to regenerate the audio:

    python tests/fixtures/generate_audio.py <output-dir>
"""
from __future__ import annotations

import json
import math
import wave
from pathlib import Path
from typing import Any, Callable

import numpy as np

FIXTURE_GENERATOR_VERSION = "2"
RNG_SEED = 20260830
SR = 44100
PCM_DTYPE = "<i2"
CLICK_SECONDS = 0.018
LOW_HZ = 80.0
MID_HZ = 800.0
HIGH_HZ = 8000.0
CURVE_ANCHOR_SECONDS = 0.5


def float_to_pcm16(signal: np.ndarray) -> np.ndarray:
    """Defined float->int16 conversion: clip, then round half to even.

    ``astype`` alone would truncate toward zero; the rounding rule must be
    pinned so regenerated WAVs stay byte-identical across platforms.
    """
    clipped = np.clip(signal.astype(np.float64), -1.0, 1.0)
    scaled = np.rint(clipped * 32767.0)
    return scaled.astype(PCM_DTYPE)


def add_click(signal: np.ndarray, sr: int, time: float, frequency: float, gain: float = 0.8) -> None:
    """Add a short windowed sine transient at ``time`` seconds."""
    start = int(round(time * sr))
    length = int(round(CLICK_SECONDS * sr))
    if start < 0 or start + length > len(signal):
        return
    window = np.hanning(length)
    phase = np.arange(length) / sr
    signal[start:start + length] += np.sin(2 * np.pi * frequency * phase) * window * gain


def grid_times(bpm: float, start: float, end: float, per_beat: int = 1) -> list[float]:
    """Regular grid timestamps in [start, end) at ``per_beat`` events per beat."""
    step = 60.0 / bpm / per_beat
    times: list[float] = []
    count = int(math.ceil((end - start) / step - 1e-9))
    for i in range(count):
        t = start + i * step
        if t < end - 1e-6:
            times.append(round(t, 6))
    return times


def variable_grid_times(curve: Callable[[float], float], duration: float) -> list[float]:
    """Deterministic beat recurrence under a tempo curve: t += 60 / bpm(t)."""
    beats: list[float] = []
    time = 0.0
    while time < duration - 1e-9:
        rounded = round(time, 6)
        if rounded < duration:
            beats.append(rounded)
        bpm = float(curve(time))
        if bpm <= 0:
            break
        time += 60.0 / bpm
    return beats


def curve_anchors(
    curve: Callable[[float], float],
    duration: float,
    *,
    skip_times: set[float] | None = None,
) -> list[dict[str, float]]:
    """Sample a tempo curve every CURVE_ANCHOR_SECONDS for truth comparison.

    Segment boundaries are excluded via ``skip_times`` so a tempo-step anchor
    never sits ambiguously between two predicted segments.
    """
    anchors: list[dict[str, float]] = []
    steps = int(round(duration / CURVE_ANCHOR_SECONDS))
    for i in range(steps):
        t = round(i * CURVE_ANCHOR_SECONDS, 4)
        if skip_times and t in skip_times:
            continue
        anchors.append({"time": t, "bpm": round(float(curve(t)), 3)})
    return anchors


def constant_curve(bpm: float) -> Callable[[float], float]:
    return lambda _t: bpm


def beats_file_content(beats: list[float]) -> str:
    """Render beat times as a Beat This style "time beat" file (beat cycles 1..4)."""
    return "".join(f"{t:.4f} {i % 4 + 1}\n" for i, t in enumerate(beats))


def _segment(bpm: float | None, start: float, end: float) -> dict[str, Any]:
    return {"start": round(start, 4), "end": round(end, 4), "bpm": bpm}


def _meter_fields(beats: list[float], numerator: int = 4) -> tuple[list[float], list[int]]:
    downbeats = [t for i, t in enumerate(beats) if i % numerator == 0]
    beat_in_bar = [i % numerator + 1 for i in range(len(beats))]
    return downbeats, beat_in_bar


def _truth(
    name: str,
    purpose: str,
    duration: float,
    bpm: float | None,
    beats: list[float],
    onsets: list[float],
    tempo_segments: list[dict[str, Any]],
    tempo_curve: list[dict[str, float]],
) -> dict[str, Any]:
    downbeats, beat_in_bar = _meter_fields(beats)
    return {
        "name": name,
        "purpose": purpose,
        "generator_version": FIXTURE_GENERATOR_VERSION,
        "seed": RNG_SEED,
        "sample_rate": SR,
        "frame_count": int(round(duration * SR)),
        "duration": duration,
        "bpm": bpm,
        "beats": beats,
        "downbeats": downbeats,
        "beat_in_bar": beat_in_bar,
        "onsets": onsets,
        "tempo_segments": tempo_segments,
        "tempo_curve": tempo_curve,
    }


def _click_beats(signal: np.ndarray, times: list[float], frequency: float = MID_HZ, gain: float = 0.8) -> None:
    for t in times:
        add_click(signal, SR, t, frequency, gain=gain)


def _fixture_fixed_120(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(120.0, 0.0, duration)
    _click_beats(signal, beats)
    truth = _truth(
        "fixed-120", "fixed 120 BPM, one mid-band click per beat", duration, 120.0,
        beats, list(beats), [_segment(120.0, 0.0, duration)],
        [{"time": 0.0, "bpm": 120.0}],
    )
    return signal, truth


def _fixture_fixed_90(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(90.0, 0.0, duration)
    _click_beats(signal, beats)
    truth = _truth(
        "fixed-90", "non-120 BPM baseline", duration, 90.0,
        beats, list(beats), [_segment(90.0, 0.0, duration)],
        [{"time": 0.0, "bpm": 90.0}],
    )
    return signal, truth


def _fixture_dense_128(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    onsets = grid_times(128.0, 0.0, duration, per_beat=2)
    _click_beats(signal, onsets, gain=0.7)
    truth = _truth(
        "dense-128", "eighth-note transients at 128 BPM", duration, 128.0,
        grid_times(128.0, 0.0, duration), onsets, [_segment(128.0, 0.0, duration)],
        [{"time": 0.0, "bpm": 128.0}],
    )
    return signal, truth


def _fixture_sparse_100(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    onsets = grid_times(100.0, 0.0, duration, per_beat=4)
    for t in onsets:
        add_click(signal, SR, t, LOW_HZ, gain=0.9)
        add_click(signal, SR, t, MID_HZ, gain=0.5)
    truth = _truth(
        "sparse-100", "one hit per bar at 100 BPM", duration, 100.0,
        grid_times(100.0, 0.0, duration), onsets, [_segment(100.0, 0.0, duration)],
        [{"time": 0.0, "bpm": 100.0}],
    )
    return signal, truth


def _fixture_tempo_change() -> tuple[np.ndarray, dict[str, Any]]:
    duration = 16.0
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(120.0, 0.0, 8.0) + grid_times(140.0, 8.0, duration)
    _click_beats(signal, beats)

    def curve(t: float) -> float:
        return 120.0 if t < 8.0 else 140.0

    truth = _truth(
        "tempo-change", "120 to 140 BPM at 8 s", duration, None,
        beats, list(beats),
        [_segment(120.0, 0.0, 8.0), _segment(140.0, 8.0, duration)],
        curve_anchors(curve, duration, skip_times={8.0}),
    )
    return signal, truth


def _fixture_gradual_drift(duration: float = 24.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)

    def curve(t: float) -> float:
        return 100.0 + 40.0 * (t / duration)

    beats = variable_grid_times(curve, duration)
    _click_beats(signal, beats)
    truth = _truth(
        "gradual-drift", "linear 100 to 140 BPM ramp over 24 s", duration, None,
        beats, list(beats), [], curve_anchors(curve, duration),
    )
    return signal, truth


def _fixture_micro_drift(duration: float = 24.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)

    def curve(t: float) -> float:
        return 120.0 + 2.0 * math.sin(2 * math.pi * t / 12.0)

    beats = variable_grid_times(curve, duration)
    _click_beats(signal, beats)
    truth = _truth(
        "micro-drift", "120 BPM with +/-2 BPM sinusoidal humanized drift", duration, None,
        beats, list(beats), [], curve_anchors(curve, duration),
    )
    return signal, truth


def _fixture_octave_trap(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(120.0, 0.0, duration)
    onsets: list[float] = []
    for t in beats:
        add_click(signal, SR, t, MID_HZ, gain=1.0)
        onsets.append(t)
        half = round(t + 30.0 / 120.0, 6)
        if half < duration - 1e-6:
            add_click(signal, SR, half, MID_HZ, gain=0.55)
            onsets.append(half)
    onsets.sort()
    truth = _truth(
        "octave-trap", "half-beat transients at 0.55 gain must not double the tempo",
        duration, 120.0, beats, onsets, [_segment(120.0, 0.0, duration)],
        [{"time": 0.0, "bpm": 120.0}],
    )
    return signal, truth


def _fixture_offgrid(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(120.0, 0.0, duration)
    offsets = (0.031, -0.026, 0.044, -0.019)
    onsets = [round(t + offsets[i % len(offsets)], 6) for i, t in enumerate(beats)]
    _click_beats(signal, onsets)
    truth = _truth(
        "offgrid", "onsets deviate from the 1/16 grid", duration, 120.0,
        beats, onsets, [_segment(120.0, 0.0, duration)],
        [{"time": 0.0, "bpm": 120.0}],
    )
    return signal, truth


def _fixture_bass_heavy(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(120.0, 0.0, duration)
    phase = np.arange(len(signal)) / SR
    signal += np.sin(2 * np.pi * 55.0 * phase) * 0.35
    for t in beats:
        add_click(signal, SR, t, LOW_HZ, gain=0.5)
    truth = _truth(
        "bass-heavy", "low-frequency dominated, must not be labeled 808", duration, 120.0,
        beats, list(beats), [_segment(120.0, 0.0, duration)],
        [{"time": 0.0, "bpm": 120.0}],
    )
    return signal, truth


def _fixture_silence(duration: float = 4.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    truth = _truth(
        "silence", "empty input boundary", duration, None,
        [], [], [_segment(None, 0.0, duration)], [],
    )
    return signal, truth


BUILDERS: dict[str, Callable[[], tuple[np.ndarray, dict[str, Any]]]] = {
    "fixed-120": _fixture_fixed_120,
    "fixed-90": _fixture_fixed_90,
    "dense-128": _fixture_dense_128,
    "sparse-100": _fixture_sparse_100,
    "tempo-change": _fixture_tempo_change,
    "offgrid": _fixture_offgrid,
    "bass-heavy": _fixture_bass_heavy,
    "silence": _fixture_silence,
    "gradual-drift": _fixture_gradual_drift,
    "micro-drift": _fixture_micro_drift,
    "octave-trap": _fixture_octave_trap,
}


def write_wav(path: Path, signal: np.ndarray, sr: int = SR) -> None:
    pcm = float_to_pcm16(signal)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())


def generate_all(output_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Generate every fixture WAV plus its ground truth into ``output_dir``."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    for name, builder in BUILDERS.items():
        signal, truth = builder()
        audio_path = out / f"{name}.wav"
        write_wav(audio_path, signal)
        truth = {**truth, "name": name}
        results[name] = {"audio": str(audio_path), "truth": truth}
    (out / "ground-truth.json").write_text(
        json.dumps({name: item["truth"] for name, item in results.items()}, indent=2),
        encoding="utf-8",
    )
    return results


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        print("usage: python tests/fixtures/generate_audio.py <output-dir>")
        return 2
    results = generate_all(sys.argv[1])
    print(f"Generated {len(results)} fixtures in {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
