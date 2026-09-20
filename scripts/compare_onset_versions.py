"""Attribute the difference between the two onset extractors, one step at a time.

The full v2 combination changes the event set in three ways at once (flux
statistic, threshold, candidate resolution), so a single before/after count
cannot say which step did what. This runs the steps separately on the same audio:

    v1                     the shipping extractor
    v2-flux                v2's per-bin flux, shipping threshold and spacing
    v2-flux+local          plus the local background threshold
    v2                     plus the valley-aware dense candidates (the full v2)

It also reports how many events the noise gate removes on audible material, so
that the gate's contribution is not confused with the mechanisms under study.
No accuracy is claimed: onset ground truth is a separate problem, and until it
exists this can only say what changed, not what improved.

Usage:
    python scripts/compare_onset_versions.py --audio-root <BallroomData> --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from beatscope.audio_io import load_analysis_audio  # noqa: E402
from beatscope.features import (  # noqa: E402
    compute_multiband_novelty,
    compute_raw_band_novelty,
    extract_onsets,
)

STAGES = ("v1", "v2-flux", "v2-flux+local", "v2")


def extract(signal, sample_rate: int, hop: int, stage: str) -> list[dict]:
    if stage == "v1":
        times, novelty = compute_multiband_novelty(signal, sample_rate, hop, version=1)
        return extract_onsets(times, novelty, sample_rate, hop, version=1)
    times, novelty = compute_multiband_novelty(signal, sample_rate, hop, version=2)
    raw = compute_raw_band_novelty(signal, sample_rate, hop, version=2)[1]
    return extract_onsets(
        times,
        novelty,
        sample_rate,
        hop,
        version=2,
        raw_novelty=raw,
        local_threshold=stage in ("v2-flux+local", "v2"),
        dense_candidates=stage == "v2",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10, help="tracks to compare, in name order")
    parser.add_argument("--output", type=Path, default=Path("build/onset-ablation.json"))
    args = parser.parse_args()

    audio_files = sorted(args.audio_root.rglob("*.wav"))[: args.limit]
    if not audio_files:
        raise SystemExit(f"no audio under {args.audio_root}")

    rows: list[dict] = []
    for path in audio_files:
        signal, sample_rate = load_analysis_audio(path)[:2]
        counts = {stage: len(extract(signal, sample_rate, 256, stage)) for stage in STAGES}
        # The gate only removes inaudible frames; on audible material it should
        # change nothing, and that is worth showing rather than assuming.
        times, novelty = compute_multiband_novelty(signal, sample_rate, 256, version=2)
        raw = compute_raw_band_novelty(signal, sample_rate, 256, version=2)[1]
        without_gate = extract_onsets(
            times, novelty, sample_rate, 256, version=2, raw_novelty=raw, noise_gate=False
        )
        rows.append({"track_id": path.stem, **counts, "v2-gate-off": len(without_gate)})

    print(f"  {'track':<28} " + " ".join(f"{stage:>14}" for stage in STAGES))
    for row in rows:
        print(f"  {row['track_id'][:27]:<28} " + " ".join(f"{row[stage]:>14}" for stage in STAGES))

    totals = {stage: sum(row[stage] for row in rows) for stage in STAGES}
    print(f"\n  {'total':<28} " + " ".join(f"{totals[stage]:>14}" for stage in STAGES))
    print(f"  {'vs v1':<28} " + " ".join(
        f"{totals[stage] / max(1, totals['v1']):>13.2f}x" for stage in STAGES
    ))
    gate_removed = sum(row["v2"] - row["v2-gate-off"] for row in rows)
    print(f"\n  noise gate removed {gate_removed} of {totals['v2'] + gate_removed} v2 events on this material")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"tracks": rows, "totals": totals}, indent=2), encoding="utf-8")
    print(f"  written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
