"""Phase 3 acceptance: the adapter's beats equal the official pipeline's.

The plan's gate for the model adapter is that it agrees with the official minimal
post-processing on shared input, including across the chunk boundaries the
official code uses for long audio. Agreement has to be measured, not assumed,
even though the adapter calls the same functions - a different loader, a
different sample rate or a different post-processor would all change the answer.

Reports per track: the longest local track is included on purpose, because a
track short enough to fit in one chunk cannot show a boundary difference.

Usage:
    python scripts/check_model_parity.py --audio <file> [<file> ...] [--device cuda]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, nargs="+", required=True)
    parser.add_argument("--model", default="final0")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    try:
        from beat_this.inference import Audio2Beats
        from beat_this.preprocessing import load_audio
    except ImportError as exc:
        raise SystemExit(f"Beat This is not installed here: {exc}") from None

    from beatscope.backends.beat_this_model import model_beats_and_downbeats

    official = Audio2Beats(checkpoint_path=args.model, device=args.device)
    rows = []
    all_equal = True
    for path in args.audio:
        signal, sample_rate = load_audio(str(path))
        duration = round(len(signal) / sample_rate, 3)
        expected_beats, expected_downbeats = official(signal, sample_rate)
        beats, downbeats, support = model_beats_and_downbeats(path, args.model, args.device)

        beats_equal = list(map(float, expected_beats)) == list(map(float, beats))
        downbeats_equal = list(map(float, expected_downbeats)) == list(map(float, downbeats))
        all_equal = all_equal and beats_equal and downbeats_equal
        rows.append(
            {
                "track": path.name,
                "seconds": duration,
                "beats": len(beats),
                "downbeats": len(downbeats),
                "frames": int(len(support)),
                "beats_equal": beats_equal,
                "downbeats_equal": downbeats_equal,
                "max_beat_delta": (
                    round(max(abs(a - b) for a, b in zip(map(float, expected_beats), map(float, beats), strict=True)), 9)
                    if len(expected_beats) == len(beats) and len(beats)
                    else None
                ),
            }
        )

    for row in rows:
        print(
            f"  {row['track'][:34]:<36} {row['seconds']:>7.1f}s  beats {row['beats']:>4} "
            f"downbeats {row['downbeats']:>3}  equal {row['beats_equal']}/{row['downbeats_equal']}  "
            f"max delta {row['max_beat_delta']}"
        )
    print(json.dumps({"all_equal": all_equal, "tracks": len(rows)}))
    return 0 if all_equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
