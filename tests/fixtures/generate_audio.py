"""Deterministic synthetic audio fixtures with exact ground truth.

Every test WAV is generated from code (no committed binaries) so snapshot
tests and the benchmark can compare analyzer output against known beat and
onset times. Run directly to regenerate the audio into a directory:

    python tests/fixtures/generate_audio.py <output-dir>
"""
from __future__ import annotations

import json
import math
import wave
from pathlib import Path
from typing import Any

import numpy as np

SR = 44100
CLICK_SECONDS = 0.018
LOW_HZ = 80.0
MID_HZ = 800.0
HIGH_HZ = 8000.0


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


def beats_file_content(beats: list[float]) -> str:
    """Render beat times as a Beat This style "time beat" file (beat cycles 1..4)."""
    return "".join(f"{t:.4f} {i % 4 + 1}\n" for i, t in enumerate(beats))


def _segment(bpm: float, start: float, end: float) -> dict[str, Any]:
    return {"start": round(start, 4), "end": round(end, 4), "bpm": bpm}


def _fixture_fixed_120(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(120.0, 0.0, duration)
    for t in beats:
        add_click(signal, SR, t, MID_HZ)
    truth = {"duration": duration, "bpm": 120.0, "beats": beats, "onsets": list(beats),
             "tempo_segments": [_segment(120.0, 0.0, duration)]}
    return signal, truth


def _fixture_fixed_90(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(90.0, 0.0, duration)
    for t in beats:
        add_click(signal, SR, t, MID_HZ)
    truth = {"duration": duration, "bpm": 90.0, "beats": beats, "onsets": list(beats),
             "tempo_segments": [_segment(90.0, 0.0, duration)]}
    return signal, truth


def _fixture_dense_128(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    onsets = grid_times(128.0, 0.0, duration, per_beat=2)
    for t in onsets:
        add_click(signal, SR, t, MID_HZ, gain=0.7)
    truth = {"duration": duration, "bpm": 128.0, "beats": grid_times(128.0, 0.0, duration),
             "onsets": onsets, "tempo_segments": [_segment(128.0, 0.0, duration)]}
    return signal, truth


def _fixture_sparse_100(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    onsets = grid_times(100.0, 0.0, duration, per_beat=4)
    for t in onsets:
        add_click(signal, SR, t, LOW_HZ, gain=0.9)
        add_click(signal, SR, t, MID_HZ, gain=0.5)
    truth = {"duration": duration, "bpm": 100.0, "beats": grid_times(100.0, 0.0, duration),
             "onsets": onsets, "tempo_segments": [_segment(100.0, 0.0, duration)]}
    return signal, truth


def _fixture_tempo_change() -> tuple[np.ndarray, dict[str, Any]]:
    duration = 16.0
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(120.0, 0.0, 8.0) + grid_times(140.0, 8.0, duration)
    for t in beats:
        add_click(signal, SR, t, MID_HZ)
    truth = {"duration": duration, "bpm": None, "beats": beats, "onsets": list(beats),
             "tempo_segments": [_segment(120.0, 0.0, 8.0), _segment(140.0, 8.0, duration)]}
    return signal, truth


def _fixture_offgrid(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(120.0, 0.0, duration)
    offsets = (0.031, -0.026, 0.044, -0.019)
    onsets = [round(t + offsets[i % len(offsets)], 6) for i, t in enumerate(beats)]
    for t in onsets:
        add_click(signal, SR, t, MID_HZ)
    truth = {"duration": duration, "bpm": 120.0, "beats": beats, "onsets": onsets,
             "tempo_segments": [_segment(120.0, 0.0, duration)]}
    return signal, truth


def _fixture_bass_heavy(duration: float = 8.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    beats = grid_times(120.0, 0.0, duration)
    phase = np.arange(len(signal)) / SR
    signal += np.sin(2 * np.pi * 55.0 * phase) * 0.35
    for t in beats:
        add_click(signal, SR, t, LOW_HZ, gain=0.5)
    truth = {"duration": duration, "bpm": 120.0, "beats": beats, "onsets": list(beats),
             "tempo_segments": [_segment(120.0, 0.0, duration)]}
    return signal, truth


def _fixture_silence(duration: float = 4.0) -> tuple[np.ndarray, dict[str, Any]]:
    signal = np.zeros(int(duration * SR), dtype=np.float64)
    truth = {"duration": duration, "bpm": None, "beats": [], "onsets": [],
             "tempo_segments": [_segment(None, 0.0, duration)]}
    return signal, truth


BUILDERS = {
    "fixed-120": _fixture_fixed_120,
    "fixed-90": _fixture_fixed_90,
    "dense-128": _fixture_dense_128,
    "sparse-100": _fixture_sparse_100,
    "tempo-change": _fixture_tempo_change,
    "offgrid": _fixture_offgrid,
    "bass-heavy": _fixture_bass_heavy,
    "silence": _fixture_silence,
}


def write_wav(path: Path, signal: np.ndarray, sr: int = SR) -> None:
    pcm = (np.clip(signal, -1.0, 1.0) * 32767.0).astype("<i2")
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
    purposes = {
        "fixed-120": "fixed 120 BPM, one mid-band click per beat",
        "fixed-90": "non-120 BPM baseline",
        "dense-128": "eighth-note transients at 128 BPM",
        "sparse-100": "one hit per bar at 100 BPM",
        "tempo-change": "120 to 140 BPM at 8 s",
        "offgrid": "onsets deviate from the 1/16 grid",
        "bass-heavy": "low-frequency dominated, must not be labeled 808",
        "silence": "empty input boundary",
    }
    for name, builder in BUILDERS.items():
        signal, truth = builder()
        audio_path = out / f"{name}.wav"
        write_wav(audio_path, signal)
        truth = {"name": name, "purpose": purposes[name], **truth}
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
