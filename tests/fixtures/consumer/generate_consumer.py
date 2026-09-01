"""Deterministic consumer-interoperability fixture (v0.9 plan section 9).

Renders one 30-second synthetic arrangement, runs it through the real
analysis pipeline, exports the portable BeatScope handoff package, and
freezes it beside its factual checkpoints and a content-addressed lock
manifest. Nothing here may touch the user's music: the audio is pure
math, and the committed evidence is the frozen package plus hashes.

Arrangement (bar-synchronous, 4/4):

    bars 1-4   A    @128 BPM  four-floor + hats, dark  (LOW-weight, ordinary)
    bars 5-8   B    @128 BPM  dense grid, bright       (dense onsets, HIGH)
    bars 9-15  A-2  @112 BPM  varied return of the A material (tempo change)

That yields exactly 30.000 s, one deliberate tempo change, two structural
boundaries at bars 5 and 9, low/mid/high activity changes, and sparse
versus dense onset regions. The section design is an A/B/A-prime layout;
the analyzer records whichever neutral letters it honestly hears (with
four-bar sections around a tempo change it currently labels A/B/C) and
the frozen package keeps that reading as the truth.

Generation is deterministic: fixed note tables, no RNG, no wall clock.
The WAV itself is never committed. Regenerate and compare with:

    python tests/fixtures/consumer/generate_consumer.py --out <dir>

Baselines under ``examples/shared/`` change only through:

    python tests/fixtures/consumer/generate_consumer.py --accept-baseline

which requires a manual diff review afterwards.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import subprocess
import sys
import tempfile
import wave
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from beatscope.consumer_contract import package_member_digest  # noqa: E402
from beatscope.exports import generate_codex_export  # noqa: E402
from beatscope.pipeline import analyze_track  # noqa: E402
from beatscope.visual_recipe import compile_visual_artifacts  # noqa: E402

GENERATOR_VERSION = "consumer-fixture-1"
LOCK_SCHEMA = "beatscope-consumer-fixture-lock-1"
CHECKPOINT_SCHEMA = "beatscope-consumer-checkpoints-1"

SR = 22050
STEPS_PER_BAR = 16
KICK_SECONDS = 0.13
SNARE_SECONDS = 0.12
HAT_SECONDS = 0.06

CHORD_A_MINOR = (220.0, 261.6256, 329.6276)
CHORD_C_MAJOR = (261.6256, 329.6276, 391.9954)

# Drum grids over the 16 steps of one 4/4 bar (step 0 = downbeat).
PATTERNS: dict[str, dict[str, tuple[int, ...]]] = {
    "four-floor": {"kick": (0, 4, 8, 12), "hat": (2, 6, 10, 14)},
    "dense": {
        "kick": (0, 4, 8, 12),
        "snare": (4, 12),
        "hat": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
    },
    "sparse": {"kick": (0, 8), "hat": (4, 12)},
}

SECTIONS: dict[str, dict[str, Any]] = {
    "A": {"chord": CHORD_A_MINOR, "pattern": "four-floor", "brightness": 0.0, "gain": 1.0, "pad_scale": 1.0},
    "B": {"chord": CHORD_C_MAJOR, "pattern": "dense", "brightness": 1.0, "gain": 1.0, "pad_scale": 1.0},
    # The A-prime span keeps A's material (chord, pattern, level) intact and
    # changes only timbre plus tempo, so the structure analyzer can hear the
    # recurrence instead of a third unrelated section.
    "A-VARIANT": {
        "chord": CHORD_A_MINOR,
        "pattern": "four-floor",
        "brightness": 0.12,
        "gain": 1.0,
        "pad_scale": 1.0,
    },
}

SPANS: list[dict[str, Any]] = [
    {"section": "A", "bars": 4, "bpm": 128.0},
    {"section": "B", "bars": 4, "bpm": 128.0},
    {"section": "A-VARIANT", "bars": 7, "bpm": 112.0},
]


# --------------------------------------------------------------- synthesis


def float_to_pcm16(signal: np.ndarray) -> np.ndarray:
    """Pinned conversion: clip, then round half to even."""
    clipped = np.clip(signal.astype(np.float64), -1.0, 1.0)
    return np.rint(clipped * 32767.0).astype("<i2")


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
    _mix(
        buffer,
        start,
        (np.sin(2 * np.pi * 1900.0 * t) + 0.7 * np.sin(2 * np.pi * 2600.0 * t)) * envelope,
    )


def _add_hat(buffer: np.ndarray, start: int, level: float) -> None:
    n = int(round(HAT_SECONDS * SR))
    t = np.arange(n) / SR
    _mix(buffer, start, np.sin(2 * np.pi * 7800.0 * t) * np.exp(-t * 70.0) * level)


def _render_bar(bpm: float, spec: dict[str, Any]) -> np.ndarray:
    """Render exactly one 4/4 bar of one section on the step grid."""
    bar_len = int(round(_bar_seconds(bpm) * SR))
    buffer = np.zeros(bar_len, dtype=np.float64)
    duration = bar_len / SR

    t = np.arange(bar_len) / SR
    fade = 0.35
    envelope = np.minimum(1.0, np.minimum(t / fade, (duration - t) / fade))
    envelope = np.clip(envelope, 0.0, 1.0)
    brightness = float(spec["brightness"])
    pad = np.zeros(bar_len, dtype=np.float64)
    chord = tuple(float(f) for f in spec["chord"])
    for freq in chord:
        pad += np.sin(2.0 * np.pi * freq * t)
        pad += brightness * 0.5 * np.sin(2.0 * np.pi * freq * 3.0 * t)
    gain = float(spec["gain"])
    pad *= 0.11 * gain * float(spec.get("pad_scale", 1.0)) * envelope / len(chord)
    buffer += pad

    grid = PATTERNS[str(spec["pattern"])]
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


def render_audio() -> np.ndarray:
    """Render the full arrangement as float64 mono at SR."""
    chunks: list[np.ndarray] = []
    for span in SPANS:
        spec = dict(SECTIONS[str(span["section"])])
        for _ in range(int(span["bars"])):
            chunks.append(_render_bar(float(span["bpm"]), spec))
    return np.concatenate(chunks)


def write_wav(path: Path, signal: np.ndarray) -> None:
    pcm = float_to_pcm16(signal)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- analysis


def _expected_boundaries() -> list[float]:
    """Boundary times implied by the span table (bar-accurate)."""
    times: list[float] = []
    elapsed = 0.0
    for span in SPANS[:-1]:
        elapsed += _bar_seconds(float(span["bpm"])) * int(span["bars"])
        times.append(elapsed)
    return times


def analyze_project(wav_path: Path) -> dict[str, Any]:
    project = analyze_track(wav_path, display_name="consumer-fixture")
    # The live pipeline stamps wall-clock provenance; the frozen fixture must
    # stay content-addressed, so the timestamp never reaches the package.
    project["analysis"].pop("created_at", None)
    duration = float(project["source"]["duration"])
    assert abs(duration - 30.0) < 1e-3, f"fixture duration drifted: {duration}"

    tempo_segments = project["tempo"]["segments"]
    assert len(tempo_segments) >= 2, f"expected a tempo change, got {len(tempo_segments)} segments"
    first_bpm = float(tempo_segments[0]["bpm"])
    last_bpm = float(tempo_segments[-1]["bpm"])
    assert 122.0 <= first_bpm <= 134.0, f"first tempo segment {first_bpm} BPM is not the 128 section"
    assert 104.0 <= last_bpm <= 120.0, f"last tempo segment {last_bpm} BPM is not the 112 section"

    segments = project["patterns"]["segments"]
    assert len(segments) >= 3, f"expected the A/B/A-prime layout, got {len(segments)} segments"
    boundaries = [float(seg["end_time"]) for seg in segments[:-1]]
    expected = _expected_boundaries()
    assert len(boundaries) >= 2, f"need two structural boundaries, found {boundaries}"
    for found, want in zip(boundaries, expected):
        assert abs(found - want) < 0.75, f"boundary {found} is not near the arranged {want}"

    recipe, timeline = compile_visual_artifacts(project)
    assert len(timeline["scenes"]) >= 3, "visual artifacts must carry real scenes, not legacy mode"
    return project


# -------------------------------------------------------------- checkpoints


def _sorted_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sorted_keys(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted_keys(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"checkpoint frame carries non-finite value: {value}")
        if value == 0.0:
            return 0.0
    return value


def canonical_frame_json(frame: Any) -> str:
    return json.dumps(_sorted_keys(frame), ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _checkpoint_times(project: dict[str, Any], timeline: dict[str, Any]) -> tuple[list[float], list[float]]:
    """Ordered checkpoint times plus an out-of-order seek sequence."""
    beats = [float(b["time"]) for b in project["beats"]]
    duration = float(project["source"]["duration"])
    boundaries = [float(t["time"]) for t in timeline["transitions"]]
    settle_midpoints = [float(t["time"]) + float(t["settle_seconds"]) / 2.0 for t in timeline["transitions"]]

    times: set[float] = {0.0, duration}
    beat = beats[5] if len(beats) > 5 else beats[0]
    times.add(round(beat, 9))
    # A beat midpoint and a beat +/- 1 ms sit inside the steady-state window.
    times.add(round((beats[4] + beats[5]) / 2.0, 9))
    times.add(round(beat - 0.001, 9))
    times.add(round(beat + 0.001, 9))
    for boundary in boundaries:
        times.add(round(boundary - 0.001, 9))
        times.add(round(boundary, 9))
        times.add(round(boundary + 0.001, 9))
    times.add(round(settle_midpoints[0], 9))
    times.add(round(duration - 0.001, 9))
    ordered = sorted(times)

    seek_sequence = [
        round(duration, 9),
        0.0,
        round(settle_midpoints[-1], 9),
        round(boundaries[0] - 0.001, 9),
        round((beats[4] + beats[5]) / 2.0, 9),
    ]
    return ordered, seek_sequence


_NODE_RUNNER = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const times = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const { getBeatScopeFrame } = await import(pathToFileURL(process.argv[2]).href);
const frames = times.map((time) => getBeatScopeFrame(time));
process.stdout.write(JSON.stringify({ frames }));
"""


def _node_frames(fixture_dir: Path, times: list[float], workdir: Path) -> list[Any]:
    runner = workdir / "frame_runner.mjs"
    times_file = workdir / "times.json"
    runner.write_text(_NODE_RUNNER, encoding="utf-8", newline="\n")
    times_file.write_text(json.dumps(times), encoding="utf-8", newline="\n")
    entry = (fixture_dir / "visual-state.js").resolve()
    result = subprocess.run(
        ["node", str(runner), str(entry), str(times_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(workdir),
    )
    if result.returncode != 0:
        raise RuntimeError(f"checkpoint frame runner failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    return payload["frames"]


# ----------------------------------------------------------------- locking


def build_fixture(output_dir: Path) -> dict[str, Any]:
    """Generate audio, analyze, export, and freeze everything into output_dir."""
    with tempfile.TemporaryDirectory(prefix="beatscope-consumer-fixture-") as tmp:
        workdir = Path(tmp)
        wav_path = workdir / "consumer-fixture.wav"
        write_wav(wav_path, render_audio())

        project = analyze_project(wav_path)
        zip_bytes = generate_codex_export(project)
        fixture_dir = output_dir / "fixture.beatscope"
        members: dict[str, bytes] = {}
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                target = fixture_dir / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(info.filename)
                target.write_bytes(data)
                members[info.filename] = data

        rhythm_map = json.loads(members["rhythm-map.json"].decode("utf-8"))
        timeline = json.loads(members["visual-timeline.json"].decode("utf-8"))
        duration = float(project["source"]["duration"])
        times, seek_sequence = _checkpoint_times(project, timeline)
        frames = _node_frames(fixture_dir, times, workdir)
        assert len(frames) == len(times)

        frames_canonical = json.dumps(
            [_sorted_keys(frame) for frame in frames],
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        checkpoints = {
            "schema": CHECKPOINT_SCHEMA,
            "package_sha256": package_member_digest(members),
            "duration": duration,
            "times": times,
            "frames_sha256": hashlib.sha256(frames_canonical.encode("utf-8")).hexdigest(),
            "seek_sequence": seek_sequence,
        }
        checkpoints_bytes = (
            json.dumps(checkpoints, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
        (output_dir / "checkpoints.json").write_bytes(checkpoints_bytes)

        lock = {
            "schema": LOCK_SCHEMA,
            "generator_version": GENERATOR_VERSION,
            "duration": duration,
            "rhythm_sha256": hashlib.sha256(members["rhythm-map.json"]).hexdigest(),
            "package_sha256": checkpoints["package_sha256"],
            "checkpoint_sha256": hashlib.sha256(checkpoints_bytes).hexdigest(),
        }
        lock_bytes = (json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        (output_dir / "fixture-lock.json").write_bytes(lock_bytes)
        return lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write the fixture into this directory for comparison")
    parser.add_argument(
        "--accept-baseline",
        action="store_true",
        help="regenerate examples/shared in place; requires a manual diff review afterwards",
    )
    args = parser.parse_args()
    if args.accept_baseline:
        target = REPO_ROOT / "examples" / "shared"
        target.mkdir(parents=True, exist_ok=True)
        lock = build_fixture(target)
        print(json.dumps({"accepted": str(target), **lock}, indent=2))
        return 0
    if args.out is None:
        parser.error("choose --out <dir> for a comparison run or --accept-baseline")
    lock = build_fixture(args.out)
    print(json.dumps(lock, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
