"""Full-pipeline stress test on ARTBeaT: decode, analyze, export, validate, score.

ARTBeaT is the material the held-out GTZAN evaluation cannot be: CC BY 4.0 audio
with beat ground truth, built to stress tempo changes (75 to 150 BPM and back),
syncopation and polyrhythm - the cases a beat tracker is most likely to fail, and
the ones the Ballroom corpus barely contains. Its annotations are a single column
of beat times, so beats are scored and downbeats are not.

This runs the whole product path per track, not just the model: decode, analyze
with the enhanced backend, export MIDI and the handoff package, validate the
package, and check the project's own consistency invariants. Failures are counted
rather than skipped, and the timing is reported per track so a slow path shows up
as a slow path.

Usage:
    python scripts/stress_pipeline_artbeat.py --root build/evaluation-data/artbeat/ARTBeaT_Dataset
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from beatscope.exports import generate_codex_export, generate_rhythm_csv  # noqa: E402
from beatscope.models import AnalysisConfig  # noqa: E402
from beatscope.pipeline import analyze_track  # noqa: E402
from beatscope.public_benchmark import evaluate_events  # noqa: E402
from beatscope.schema import validate_rhythm_v4  # noqa: E402
from scripts.compare_product_output import consistency_problems  # noqa: E402


def read_beat_times(path: Path) -> list[float]:
    """ARTBeaT's ground truth is one beat time per line."""
    times = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith(("time", "#")):
            continue
        times.append(float(stripped.split(",")[0]))
    return sorted(times)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--backend", default="enhanced")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, default=Path("build/artbeat-stress.json"))
    args = parser.parse_args()

    audio_dir = args.root / "Audio"
    annotation_dir = args.root / "Annotations" / "gt_csv"
    if not audio_dir.is_dir() or not annotation_dir.is_dir():
        raise SystemExit(f"expected Audio/ and Annotations/gt_csv/ under {args.root}")

    annotations = {path.stem.replace("_gt", ""): path for path in annotation_dir.glob("*.csv")}
    os.environ["BEATSCOPE_MODEL_DEVICE"] = args.device

    rows = []
    for audio in sorted(audio_dir.glob("*.wav")):
        reference = read_beat_times(annotations[audio.stem]) if audio.stem in annotations else []
        entry: dict = {"track": audio.stem, "annotated_beats": len(reference)}
        started = time.perf_counter()
        try:
            project = analyze_track(audio, AnalysisConfig.from_dict({"backend": args.backend}))
            entry["analyze_seconds"] = round(time.perf_counter() - started, 2)
            beats = [float(beat["time"]) for beat in project.get("beats", [])]
            entry["beats"] = len(beats)
            entry["f_measure"] = (
                evaluate_events(reference, beats)["f_measure"] if len(reference) > 1 and len(beats) > 1 else 0.0
            )
            entry["cmlt"] = (
                evaluate_events(reference, beats)["cmlt"] if len(reference) > 1 and len(beats) > 1 else 0.0
            )
            entry["problems"] = consistency_problems(project) + [f"schema: {e}" for e in validate_rhythm_v4(project)[:2]]
            generate_rhythm_csv(project, subdivision=16)
            archive = generate_codex_export(project)
            entry["package_bytes"] = len(archive)
            entry["ok"] = True
        except Exception as exc:
            entry["analyze_seconds"] = round(time.perf_counter() - started, 2)
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["ok"] = False
        rows.append(entry)

    ok = [row for row in rows if row["ok"]]
    failed = [row for row in rows if not row["ok"]]
    print(f"  {len(rows)} tracks, backend {args.backend} on {args.device}")
    print(f"\n  {'track':<34} {'beats':>6} {'F1':>7} {'CMLt':>7} {'秒':>6} {'问题':>5}")
    for row in rows:
        if not row["ok"]:
            print(f"  {row['track'][:33]:<34} {'-':>6} {'-':>7} {'-':>7} {row['analyze_seconds']:>6} {'FAIL':>5}  {row.get('error','')[:60]}")
            continue
        print(
            f"  {row['track'][:33]:<34} {row['beats']:>6} {row['f_measure']:>7.4f} {row['cmlt']:>7.4f} "
            f"{row['analyze_seconds']:>6} {len(row['problems']):>5}"
        )

    if ok:
        print(f"\n  macro Beat F1 {statistics.fmean(row['f_measure'] for row in ok):.4f}   "
              f"macro CMLt {statistics.fmean(row['cmlt'] for row in ok):.4f}   "
              f"median seconds/track {statistics.median(row['analyze_seconds'] for row in ok):.2f}")
        print(f"  tracks with consistency problems: {sum(1 for row in ok if row['problems'])}")
        for row in ok:
            for problem in row["problems"][:2]:
                print(f"      {row['track'][:30]}: {problem}")
    print(f"  failures: {len(failed)}/{len(rows)}")
    print("  downbeats are not scored: ARTBeaT's annotations carry beat times only")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"backend": args.backend, "tracks": rows}, indent=2), encoding="utf-8")
    print(f"  written to {args.output}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
