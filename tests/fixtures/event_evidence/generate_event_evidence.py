"""Deterministic dense-mixture event-evidence fixtures (v0.11 Round 1).

Each fixture renders a short, dense arrangement whose transients carry
generator-intent roles (``foreground``/``background``) and a band label. The
roles describe why the generator placed an event; they are NOT perceptual
ground truth and must never train the Round 2 ranker directly.

Generation is pure math - fixed event tables, no RNG, no wall-clock input -
so one generator version renders byte-identical WAVs on every platform. The
committed material is this module plus ``event-evidence-truth.json`` and
``event-evidence-baseline.json``; generated audio goes to a caller-provided
build/temp directory and is never committed.

Baseline governance follows the repository pattern:

    python -m tests.fixtures.event_evidence.generate_event_evidence
    python -m tests.fixtures.event_evidence.generate_event_evidence --accept-baseline

Without ``--accept-baseline`` the command re-renders every case, re-runs the
current analysis, and fails with a field-level diff when the committed truth
or the recorded characterization drifts. ``--accept-baseline`` rewrites the
committed JSON after a reviewed change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import wave
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

try:  # the repo checkout puts ``tests/`` itself on sys.path
    from tests.fixtures.generate_audio import float_to_pcm16
except ImportError:  # pragma: no cover - conftest-style imports
    from fixtures.generate_audio import float_to_pcm16

GENERATOR_VERSION = "event-evidence-fixtures-v1"
TRUTH_SCHEMA = "beatscope-event-evidence-truth-1"
BASELINE_SCHEMA = "beatscope-event-evidence-baseline-1"
SR = 22050
# Frozen for reproducibility bookkeeping even though no RNG is used today.
RANDOM_SEED = 20260906
TRANSIENT_SECONDS = 0.030
LOW_HZ = 80.0
MID_HZ = 800.0
HIGH_HZ = 8000.0
MATCH_TOLERANCE_SECONDS = 0.05
OFFGRID_PRESERVATION_TOLERANCE_SECONDS = 0.01

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = Path(__file__).resolve().parent
TRUTH_PATH = FIXTURE_DIR / "event-evidence-truth.json"
BASELINE_PATH = FIXTURE_DIR / "event-evidence-baseline.json"
DEFAULT_AUDIO_DIR = REPO_ROOT / "build" / "event-evidence-fixtures"


# --------------------------------------------------------------- synthesis

def add_transient(
    signal: np.ndarray,
    time: float,
    frequency: float,
    gain: float,
    seconds: float = TRANSIENT_SECONDS,
) -> None:
    """Mix one windowed sine transient at ``time`` seconds."""
    start = int(round(time * SR))
    length = int(round(seconds * SR))
    if start < 0 or start + length > len(signal):
        return
    window = np.hanning(length)
    phase = np.arange(length) / SR
    signal[start:start + length] += np.sin(2.0 * np.pi * frequency * phase) * window * gain


def _event(time: float, role: str, band: str, **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"time": round(float(time), 6), "role": role, "band": band}
    entry.update(extra)
    return entry


def _grid(signal: np.ndarray, events: list[dict[str, Any]], start: float, end: float, step: float,
          band: str, frequency: float, gain: float, seconds: float = TRANSIENT_SECONDS) -> None:
    time = start
    while time < end - 1e-9:
        add_transient(signal, time, frequency, gain, seconds)
        events.append(_event(time, "background", band))
        time += step


# --------------------------------------------------------------- case table
# Background layers create a continuously busy texture; foreground events are
# rare, band-focused, and deliberately off the beat grid so the characterization
# records how the current global-strength pipeline treats them.

BARS = 8
BPM = 120.0
CASE_DURATION = BARS * 4.0 * 60.0 / BPM  # 16.0 s

LOW_FOREGROUND_TIMES = (2.087, 4.213, 6.541, 9.318, 11.129, 13.006, 14.771, 15.594)
HIGH_FOREGROUND_TIMES = (1.093, 2.617, 4.066, 5.522, 7.129, 9.651, 11.443, 13.188)
BROADBAND_TIMES = (1.213, 3.094, 5.606, 8.187, 10.512, 13.905)
OFFGRID_OFFSETS = (0.019, -0.031, 0.047, -0.055, 0.063, -0.023, 0.041, -0.061, 0.059, -0.047)
ACCELERATING_GAPS = (0.16, 0.13, 0.10, 0.07)
DECELERATING_GAPS = (0.07, 0.10, 0.13, 0.16)
NO_GRID_TIMES = tuple(
    round(0.37 * index + 0.013 * (index % 5), 6) for index in range(12)
)


def _render_low_foreground() -> tuple[np.ndarray, list[dict[str, Any]]]:
    signal = np.zeros(int(round(CASE_DURATION * SR)))
    events: list[dict[str, Any]] = []
    _grid(signal, events, 0.0, CASE_DURATION, 0.25, "high", HIGH_HZ, 0.30)
    _grid(signal, events, 0.375, CASE_DURATION, 0.5, "mid", MID_HZ, 0.22)
    for time in LOW_FOREGROUND_TIMES:
        add_transient(signal, time, LOW_HZ, 0.85, seconds=0.09)
        events.append(_event(time, "foreground", "low"))
    return signal, events


def _render_high_foreground() -> tuple[np.ndarray, list[dict[str, Any]]]:
    signal = np.zeros(int(round(CASE_DURATION * SR)))
    events: list[dict[str, Any]] = []
    _grid(signal, events, 0.0, CASE_DURATION, 0.5, "low", LOW_HZ, 0.50, seconds=0.09)
    _grid(signal, events, 0.25, CASE_DURATION, 0.5, "mid", MID_HZ, 0.22)
    for time in HIGH_FOREGROUND_TIMES:
        add_transient(signal, time, HIGH_HZ, 0.70)
        events.append(_event(time, "foreground", "high"))
    return signal, events


def _render_broadband_foreground() -> tuple[np.ndarray, list[dict[str, Any]]]:
    signal = np.zeros(int(round(CASE_DURATION * SR)))
    events: list[dict[str, Any]] = []
    _grid(signal, events, 0.0, CASE_DURATION, 1.0, "low", LOW_HZ, 0.50, seconds=0.09)
    _grid(signal, events, 0.5, CASE_DURATION, 1.0, "high", HIGH_HZ, 0.30)
    for time in BROADBAND_TIMES:
        for band, frequency, gain, seconds in (
            ("low", LOW_HZ, 0.85, 0.09),
            ("mid", MID_HZ, 0.55, TRANSIENT_SECONDS),
            ("high", HIGH_HZ, 0.55, TRANSIENT_SECONDS),
        ):
            add_transient(signal, time, frequency, gain, seconds)
            events.append(_event(time, "foreground", band))
    return signal, events


def _render_run(gaps: tuple[float, ...]) -> tuple[np.ndarray, list[dict[str, Any]]]:
    duration = 4.0  # two bars at 120 BPM
    signal = np.zeros(int(round(duration * SR)))
    events: list[dict[str, Any]] = []
    time = 1.0
    for gap in (0.0,) + gaps:
        time += gap
        add_transient(signal, time, MID_HZ, 0.65)
        events.append(_event(time, "foreground", "mid"))
    # Two isolated markers far outside any 0.18 s run window.
    add_transient(signal, 3.0, LOW_HZ, 0.5, seconds=0.09)
    events.append(_event(3.0, "background", "low"))
    add_transient(signal, 3.5, HIGH_HZ, 0.35)
    events.append(_event(3.5, "background", "high"))
    return signal, events


def _render_offgrid() -> tuple[np.ndarray, list[dict[str, Any]]]:
    duration = 8.0  # four bars at 120 BPM
    signal = np.zeros(int(round(duration * SR)))
    events: list[dict[str, Any]] = []
    for index, offset in enumerate(OFFGRID_OFFSETS):
        beat_time = index * 0.5
        time = beat_time + offset
        add_transient(signal, time, MID_HZ, 0.65)
        events.append(_event(time, "foreground", "mid", grid_offset=round(offset, 6),
                             nearest_beat=round(beat_time, 6)))
    return signal, events


def _render_silence() -> tuple[np.ndarray, list[dict[str, Any]]]:
    duration = 8.0
    return np.zeros(int(round(duration * SR))), []


AUDIO_CASES: dict[str, dict[str, Any]] = {
    "dense-low-foreground": {
        "purpose": "busy high/mid texture with rare off-grid low-band hits",
        "render": _render_low_foreground,
        "bars": BARS,
        "bpm": BPM,
        "duration": CASE_DURATION,
    },
    "dense-high-foreground": {
        "purpose": "busy low/mid texture with rare off-grid high-band hits",
        "render": _render_high_foreground,
        "bars": BARS,
        "bpm": BPM,
        "duration": CASE_DURATION,
    },
    "broadband-foreground": {
        "purpose": "alternating narrow-band texture with rare simultaneous three-band hits",
        "render": _render_broadband_foreground,
        "bars": BARS,
        "bpm": BPM,
        "duration": CASE_DURATION,
    },
    "accelerating-run": {
        "purpose": "one short run with progressively shorter intervals",
        "render": lambda: _render_run(ACCELERATING_GAPS),
        "bars": 2,
        "bpm": BPM,
        "duration": 4.0,
    },
    "decelerating-run": {
        "purpose": "one short run with progressively longer intervals",
        "render": lambda: _render_run(DECELERATING_GAPS),
        "bars": 2,
        "bpm": BPM,
        "duration": 4.0,
    },
    "offgrid": {
        "purpose": "labelled transients 19-63 ms off the beat grid",
        "render": _render_offgrid,
        "bars": 4,
        "bpm": BPM,
        "duration": 8.0,
    },
    "silence": {
        "purpose": "digital silence; the analyzer must return no onsets",
        "render": _render_silence,
        "bars": 4,
        "bpm": BPM,
        "duration": 8.0,
    },
}


# ------------------------------------------------------------ no-grid project

def build_no_grid_project() -> dict[str, Any]:
    """A valid Rhythm IR v4 project with onsets and no measured beats."""
    onsets = []
    bands = ("low", "mid", "high")
    for index, time in enumerate(NO_GRID_TIMES):
        band = bands[index % 3]
        strength = 0.45 + 0.05 * (index % 4)
        onsets.append({
            "id": index + 1,
            "time": time,
            "strength": round(strength, 4),
            "bands": {
                "all": round(strength, 4),
                "low": round(strength if band == "low" else strength * 0.3, 4),
                "mid": round(strength if band == "mid" else strength * 0.3, 4),
                "high": round(strength if band == "high" else strength * 0.3, 4),
            },
        })
    return {
        "schema_version": "4.0",
        "project_id": "a1b2c3d4e5f0",
        "source": {
            "display_name": "Event Evidence No-Grid",
            "duration": 8.0,
            "sample_rate": SR,
            "channels": 1,
            "sha256": "f" * 64,
        },
        "analysis": {
            "backend": "fixture",
            "pipeline_version": GENERATOR_VERSION,
            "provenance": {"beats": {"method": "none"}, "onsets": {"method": "synthetic"}},
        },
        "tempo": {
            "global_bpm": 120.0,
            "segments": [{"start": 0.0, "end": 8.0, "bpm": 120.0, "method": "fixture", "score": None}],
        },
        "meter": {"numerator": 4, "denominator": 4},
        "grid": {"origin": 0.0, "default_subdivision": 16, "bars": 16},
        "beats": [],
        "onsets": onsets,
        "energy": {
            "fps": 20,
            "start": 0.0,
            "bands": {name: [0.0] * 160 for name in ("all", "low", "mid", "high")},
        },
        # Structure keys stay absent: an empty segments list is not valid v4,
        # and a no-grid fixture has no structure to describe.
        "patterns": {"method": "fixture", "bars": []},
        "cues": {"accent": []},
        "exports": {},
    }


# -------------------------------------------------------------- truth bundle

def build_truth(audio_hashes: dict[str, str]) -> dict[str, Any]:
    """Truth manifest for every case; ``audio_hashes`` maps case -> WAV sha256."""
    cases: dict[str, Any] = {}
    for name, spec in AUDIO_CASES.items():
        _, events = spec["render"]()
        cases[name] = {
            "purpose": spec["purpose"],
            "kind": "audio",
            "bars": spec["bars"],
            "bpm": spec["bpm"],
            "duration": round(float(spec["duration"]), 6),
            "events": events,
            "audio_sha256": audio_hashes[name],
        }
    no_grid = build_no_grid_project()
    cases["no-grid"] = {
        "purpose": "valid v4 project with onsets and no measured beats",
        "kind": "project",
        "duration": no_grid["source"]["duration"],
        "events": [
            {
                "time": onset["time"],
                "role": "foreground",
                "band": max(
                    ("low", "mid", "high"),
                    key=lambda band: onset["bands"][band],
                ),
            }
            for onset in no_grid["onsets"]
        ],
    }
    return {
        "schema": TRUTH_SCHEMA,
        "generator_version": GENERATOR_VERSION,
        "random_seed": RANDOM_SEED,
        "sample_rate": SR,
        "transient_seconds": TRANSIENT_SECONDS,
        "frequencies_hz": {"low": LOW_HZ, "mid": MID_HZ, "high": HIGH_HZ},
        "roles_note": (
            "foreground/background and band labels describe generator intent only; "
            "they are not perceptual ground truth."
        ),
        "cases": cases,
    }


# ----------------------------------------------------------- characterization

def hash_onsets(onsets: list[dict[str, Any]]) -> str:
    canonical = json.dumps(onsets, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _greedy_match(truth_times: list[float], detected_times: list[float],
                  tolerance: float) -> list[tuple[int, int]]:
    """Greedy nearest matching in time order; returns (truth_index, detection_index)."""
    matches: list[tuple[int, int]] = []
    used_detections: set[int] = set()
    for truth_index, truth_time in enumerate(truth_times):
        best: tuple[float, int] | None = None
        for detection_index, detected_time in enumerate(detected_times):
            if detection_index in used_detections:
                continue
            error = abs(detected_time - truth_time)
            if error <= tolerance and (best is None or error < best[0]):
                best = (error, detection_index)
        if best is not None:
            used_detections.add(best[1])
            matches.append((truth_index, best[1]))
    return matches


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def characterize_case(name: str, project: dict[str, Any]) -> dict[str, Any]:
    """Freeze the current pipeline behavior on one case (baseline, not truth)."""
    onsets = project.get("onsets", [])
    accents = project.get("cues", {}).get("accent", [])
    entry: dict[str, Any] = {
        "kind": "audio",
        "raw_onset_count": len(onsets),
        "accent_count": len(accents),
        "truth_event_count": 0,
        "matched_truth_count": 0,
        "precision_at_50ms": None,
        "recall_at_50ms": None,
        "median_error_seconds": None,
        "max_error_seconds": None,
    }
    truth_events = AUDIO_CASES[name]["render"]()[1]
    truth_times = [event["time"] for event in truth_events]
    detected_times = [float(onset["time"]) for onset in onsets]
    entry["truth_event_count"] = len(truth_times)
    matches = _greedy_match(truth_times, detected_times, MATCH_TOLERANCE_SECONDS)
    entry["matched_truth_count"] = len(matches)
    if detected_times:
        entry["precision_at_50ms"] = round(len(matches) / len(detected_times), 6)
    if truth_times:
        entry["recall_at_50ms"] = round(len(matches) / len(truth_times), 6)
    if matches:
        errors = [abs(detected_times[detection] - truth_times[truth]) for truth, detection in matches]
        entry["median_error_seconds"] = round(_median(errors), 6)
        entry["max_error_seconds"] = round(max(errors), 6)
    return entry


def characterize_no_grid(project: dict[str, Any]) -> dict[str, Any]:
    onsets = project.get("onsets", [])
    return {
        "kind": "project",
        "onset_count": len(onsets),
        "onsets_sha256": hash_onsets(onsets),
    }


def build_baseline(characterization: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": BASELINE_SCHEMA,
        "generator_version": GENERATOR_VERSION,
        "match_tolerance_seconds": MATCH_TOLERANCE_SECONDS,
        "note": (
            "Characterization of current analysis behavior. Synthetic roles are not "
            "perceptual labels and accent membership is not asserted to be truth."
        ),
        "cases": characterization,
    }


def _diff_dicts(actual: dict[str, Any], expected: dict[str, Any], path: str = "") -> list[str]:
    """Readable field-level diff used for both truth and baseline drift."""
    diffs: list[str] = []
    for key in sorted(set(actual) | set(expected)):
        label = f"{path}.{key}" if path else key
        if key not in actual:
            diffs.append(f"{label}: missing in regenerated output (committed {expected[key]!r})")
        elif key not in expected:
            diffs.append(f"{label}: unexpected in regenerated output ({actual[key]!r})")
        elif actual[key] != expected[key]:
            if isinstance(actual[key], dict) and isinstance(expected[key], dict):
                diffs.extend(_diff_dicts(actual[key], expected[key], label))
            else:
                diffs.append(f"{label}: regenerated {actual[key]!r} != committed {expected[key]!r}")
    return diffs


# ------------------------------------------------------------------ analysis

def analyze_case(wav_path: Path) -> dict[str, Any]:
    """Run the current analysis pipeline on one rendered WAV."""
    from beatscope.pipeline import analyze_track

    return analyze_track(wav_path)


@lru_cache(maxsize=None)
def analyze_case_cached(name: str, audio_dir: Path) -> dict[str, Any]:
    """Cached analysis so test modules share one run per case and directory."""
    return analyze_case(render_case_wav(name, Path(audio_dir)))


SNAPSHOT_CASES = ("dense-low-foreground", "dense-high-foreground", "accelerating-run", "no-grid")
SNAPSHOT_DIR = REPO_ROOT / "tests" / "snapshots" / "event-evidence"


def write_snapshots(audio_dir: Path) -> list[str]:
    """Re-record the four frozen event-evidence snapshots."""
    from beatscope.event_evidence import build_event_evidence, canonical_event_evidence_bytes

    written: list[str] = []
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for name in SNAPSHOT_CASES:
        if name == "no-grid":
            project = build_no_grid_project()
        else:
            project = analyze_case(render_case_wav(name, audio_dir))
        payload = canonical_event_evidence_bytes(build_event_evidence(project))
        (SNAPSHOT_DIR / f"{name}.json").write_bytes(payload)
        written.append(name)
    return written


def render_case_wav(name: str, audio_dir: Path) -> Path:
    """Render one case to ``audio_dir/<case>.wav`` with the pinned PCM rule."""
    signal, _ = AUDIO_CASES[name]["render"]()
    pcm = float_to_pcm16(signal)
    audio_dir.mkdir(parents=True, exist_ok=True)
    wav_path = audio_dir / f"{name}.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(pcm.tobytes())
    return wav_path


def _canonical_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect(audio_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Render, analyze, and return (truth, baseline) for the current run."""
    audio_hashes: dict[str, str] = {}
    characterization: dict[str, dict[str, Any]] = {}
    for name in AUDIO_CASES:
        wav_path = render_case_wav(name, audio_dir)
        audio_hashes[name] = hashlib.sha256(wav_path.read_bytes()).hexdigest()
        project = analyze_case(wav_path)
        characterization[name] = characterize_case(name, project)
    characterization["no-grid"] = characterize_no_grid(build_no_grid_project())
    return build_truth(audio_hashes), build_baseline(characterization)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=DEFAULT_AUDIO_DIR,
        help="directory for generated WAV files (never committed)",
    )
    parser.add_argument(
        "--accept-baseline",
        action="store_true",
        help="rewrite the committed truth and baseline JSON after a reviewed change",
    )
    parser.add_argument(
        "--accept-snapshots",
        action="store_true",
        help="re-record the four frozen event-evidence bundle snapshots",
    )
    args = parser.parse_args(argv)

    if args.accept_snapshots:
        written = write_snapshots(args.audio_dir)
        print(json.dumps({"snapshots": written}, indent=2))
        return 0

    truth, baseline = collect(args.audio_dir)

    committed_truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8")) if TRUTH_PATH.exists() else None
    committed_baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8")) if BASELINE_PATH.exists() else None

    truth_diffs = _diff_dicts(truth, committed_truth) if committed_truth is not None else ["truth file missing"]
    baseline_diffs = (
        _diff_dicts(baseline, committed_baseline) if committed_baseline is not None else ["baseline file missing"]
    )

    if args.accept_baseline:
        TRUTH_PATH.write_text(_canonical_json_text(truth), encoding="utf-8", newline="\n")
        BASELINE_PATH.write_text(_canonical_json_text(baseline), encoding="utf-8", newline="\n")
        print(json.dumps({
            "accepted": True,
            "generator_version": GENERATOR_VERSION,
            "cases": sorted(baseline["cases"]),
            "truth_sha256": _sha256_of_text(_canonical_json_text(truth)),
            "baseline_sha256": _sha256_of_text(_canonical_json_text(baseline)),
        }, indent=2))
        return 0

    failures = []
    if truth_diffs:
        failures.append("event-evidence-truth.json drifted:\n  " + "\n  ".join(truth_diffs))
    if baseline_diffs:
        failures.append("event-evidence-baseline.json drifted:\n  " + "\n  ".join(baseline_diffs))
    if failures:
        for failure in failures:
            print(failure, flush=True)
        print("re-run with --accept-baseline only after reviewing the diff above")
        return 1
    print(json.dumps({
        "verified": True,
        "generator_version": GENERATOR_VERSION,
        "cases": {name: entry["kind"] for name, entry in sorted(baseline["cases"].items())},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
