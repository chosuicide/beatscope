"""Does the refinement layer improve on the model's beats? (accuracy plan, phase 4)

The plan's gate is a gain in Beat F1 over the vanilla model on the development
split, with the continuity metrics watched for regressions, and the decision made
on the held-out split. This runs both arms on the same tracks and reports them
per track, because a macro mean hides which tracks got worse.

The onsets fed to the layer are the shipping extractor's, not the experimental
v2: v2 lost to v1 on the onset evaluation, and building the refinement on a
component that lost would be building on sand.

Usage:
    python scripts/evaluate_refinement.py --split dev --limit 24 [--device cuda]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from beatscope.backends.beat_this_model import model_beats_and_downbeats  # noqa: E402
from beatscope.backends.lightweight import LightweightBackend  # noqa: E402
from beatscope.models import AnalysisConfig  # noqa: E402
from beatscope.public_benchmark import evaluate_events, read_ballroom_annotation  # noqa: E402
from beatscope.timing_refinement import refine_beats  # noqa: E402

MANIFEST = REPO_ROOT / "evaluations/public-beat/ballroom-manifest-v1.json"
AUDIO_ROOT = REPO_ROOT / "build/public-benchmark/audio/BallroomData"
ANNOTATION_ROOT = REPO_ROOT / "build/public-benchmark/annotations"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--model", default="final0")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=Path("build/refinement-evaluation.json"))
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected = [row["track_id"] for row in manifest["tracks"] if args.split in ("all", row["split"])][: args.limit]
    audio = {path.stem: path for path in AUDIO_ROOT.rglob("*.wav")}
    annotations = {path.stem: path for path in ANNOTATION_ROOT.rglob("*.beats")}

    inner = LightweightBackend()
    rows = []
    for track_id in selected:
        if track_id not in audio or track_id not in annotations:
            continue
        reference, _ = read_ballroom_annotation(annotations[track_id])
        beats, _downbeats, support = model_beats_and_downbeats(audio[track_id], args.model, args.device)
        evidence = inner.analyze(audio[track_id], AnalysisConfig.from_dict({"backend": "lightweight"}), lambda *a: None, lambda: False)
        onsets = [float(row["raw_time"]) for row in evidence.onsets]
        refined, records = refine_beats(list(map(float, beats)), support=support, onsets=onsets)

        vanilla = evaluate_events(reference, list(map(float, beats)))
        changed = evaluate_events(reference, refined)
        rows.append(
            {
                "track_id": track_id,
                "beats": len(beats),
                "moved": sum(1 for record in records if record.moved),
                "vanilla_f1": vanilla["f_measure"],
                "refined_f1": changed["f_measure"],
                "vanilla_cmlt": vanilla["cmlt"],
                "refined_cmlt": changed["cmlt"],
            }
        )

    if not rows:
        raise SystemExit("no tracks matched")

    print(f"  {len(rows)} tracks ({args.split} split, {args.model} on {args.device})")
    print(f"\n  {'track':<30} {'beats':>6} {'moved':>6} {'vanilla':>8} {'refined':>8} {'delta':>7}")
    for row in rows:
        delta = row["refined_f1"] - row["vanilla_f1"]
        print(
            f"  {row['track_id'][:29]:<30} {row['beats']:>6} {row['moved']:>6} "
            f"{row['vanilla_f1']:>8.4f} {row['refined_f1']:>8.4f} {delta:>+7.4f}"
        )

    def mean(key: str) -> float:
        return statistics.fmean(row[key] for row in rows)

    print(f"\n  macro Beat F1   vanilla {mean('vanilla_f1'):.4f}   refined {mean('refined_f1'):.4f}"
          f"   delta {mean('refined_f1') - mean('vanilla_f1'):+.4f}")
    print(f"  macro CMLt      vanilla {mean('vanilla_cmlt'):.4f}   refined {mean('refined_cmlt'):.4f}"
          f"   delta {mean('refined_cmlt') - mean('vanilla_cmlt'):+.4f}")
    worse = [row for row in rows if row["refined_f1"] < row["vanilla_f1"] - 1e-9]
    better = [row for row in rows if row["refined_f1"] > row["vanilla_f1"] + 1e-9]
    print(f"  per track: {len(better)} better, {len(worse)} worse, {len(rows) - len(better) - len(worse)} unchanged")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"split": args.split, "tracks": rows}, indent=2), encoding="utf-8")
    print(f"  written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
