"""Establish the Beat This model facts an adapter has to be built on.

The accuracy plan's phase 3 is a model adapter: take the per-frame beat and
downbeat support from the official model, and keep the product's own onset work.
Before writing it, pin what the official interface actually returns - frame rate,
array shapes, and whether the post-processing is reachable - because the plan's
rule is that the model's 50 fps and the features' 44100/256 fps must be aligned by
time and never by array index.

This is a probe, not the adapter. It reads one local track and prints what it
finds; nothing here is on any shipping path.

Usage:
    python scripts/probe_beat_this_model.py --audio <track.wav> [--device cuda]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--model", default="final0")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    try:
        import beat_this
        from beat_this.inference import Audio2Beats, Audio2Frames, File2Beats
        from beat_this.preprocessing import load_audio
    except ImportError as exc:
        raise SystemExit(f"Beat This is not installed here: {exc}") from None

    report: dict[str, object] = {
        "beat_this_version": getattr(beat_this, "__version__", "unknown"),
        "package_file": str(Path(beat_this.__file__).resolve()),
        "model": args.model,
        "device": args.device,
        "audio": args.audio.name,
    }

    # 1. Per-frame support, which is what an adapter consumes.
    # The official interface takes a waveform and its rate, not a path: the
    # adapter has to load and hand over audio itself, and the model resamples to
    # 22050 internally. Reusing the package's own loader keeps that faithful.
    signal, sample_rate = load_audio(str(args.audio))
    report["loaded_sample_rate"] = int(sample_rate)
    report["loaded_samples"] = int(len(signal))
    frames = Audio2Frames(checkpoint_path=args.model, device=args.device)
    started = time.perf_counter()
    beats_logits, downbeats_logits = frames(signal, sample_rate)
    report["frames_seconds"] = round(time.perf_counter() - started, 3)
    report["beats_logits_shape"] = list(getattr(beats_logits, "shape", ()))
    report["downbeats_logits_shape"] = list(getattr(downbeats_logits, "shape", ()))
    duration = None
    try:
        import soundfile

        duration = float(soundfile.info(str(args.audio)).duration)
        report["audio_duration_seconds"] = round(duration, 4)
        frames_returned = report["beats_logits_shape"][0] if report["beats_logits_shape"] else 0
        if duration and frames_returned:
            report["implied_frame_rate"] = round(frames_returned / duration, 4)
    except Exception as exc:  # pragma: no cover - probe only
        report["duration_error"] = f"{type(exc).__name__}: {exc}"

    # 2. The official post-processing, which is the baseline the adapter must match.
    # `dbn` defaults to False in the official API, so "the official pipeline" is
    # the minimal post-processor unless DBN is asked for by name. DBN imports
    # madmom in the post-processor's constructor, which is why asking for it
    # either works or fails loudly - there is no silent middle.
    for label, call in (
        ("audio2beats_default", lambda: Audio2Beats(checkpoint_path=args.model, device=args.device)(signal, sample_rate)),
        ("audio2beats_dbn", lambda: Audio2Beats(checkpoint_path=args.model, device=args.device, dbn=True)(signal, sample_rate)),
        ("file2beats_minimal", lambda: File2Beats(checkpoint_path=args.model, device=args.device, dbn=False)(str(args.audio))),
    ):
        try:
            beats, downbeats = call()
            report[label] = {
                "beats": len(beats),
                "downbeats": len(downbeats),
                "first_beats": [round(float(value), 4) for value in list(beats)[:4]],
                "first_downbeats": [round(float(value), 4) for value in list(downbeats)[:4]],
            }
        except Exception as exc:
            # Reachability matters more than the numbers here: DBN needs madmom,
            # and whether that dependency resolves decides which baseline is
            # available at all.
            report[label] = {"unavailable": f"{type(exc).__name__}: {exc}"}

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
