"""Compare complete product output between two backends, not just their beats.

The review that prompted this asked for the whole project to be compared, and for
good reason: the enhanced backend's first version agreed with the official
pipeline internally while publishing a project that contradicted itself - a
global tempo of 60 with segments at 120, three bars of beats inside a five-bar
grid, and the model's downbeats replaced by a 4-cycle. None of that shows up in a
beat F1 number, and all of it would reach a consumer.

So this checks the invariants a project must satisfy as well as the metric:

- the global tempo and the tempo segments agree;
- the declared bar count covers the beats that exist;
- the meter numerator matches the numbering the beats use;
- the downbeat flags agree with the meter's first beat;
- the source labels are present and consistent with what the backend did.

The metric is reported per backend and per track. Which corpus it runs on decides
what the number means: Ballroom is in final0's training data, so on Ballroom this
is a wiring check and nothing more. final0's own documentation says it was trained
on all data except GTZAN, which makes GTZAN the held-out set - and its audio is
licence-restricted, so it has to be obtained separately.

Usage:
    python scripts/compare_product_output.py --limit 8 [--device cuda] [--backends lightweight enhanced]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from beatscope.models import AnalysisConfig  # noqa: E402
from beatscope.pipeline import analyze_track  # noqa: E402
from beatscope.public_benchmark import evaluate_events, read_ballroom_annotation  # noqa: E402
from beatscope.schema import validate_rhythm_v4  # noqa: E402

MANIFEST = REPO_ROOT / "evaluations/public-beat/ballroom-manifest-v1.json"
AUDIO_ROOT = REPO_ROOT / "build/public-benchmark/audio/BallroomData"
ANNOTATION_ROOT = REPO_ROOT / "build/public-benchmark/annotations"


def consistency_problems(project: dict) -> list[str]:
    """Everything a consumer would trip over, as a list of plain statements."""
    problems: list[str] = []
    diagnostics = project.get("analysis", {}).get("diagnostics", {})
    beats = project.get("beats", [])
    meter = project.get("meter", {})
    numerator = int(meter.get("numerator", 0))
    grid = project.get("grid", {})
    tempo = project.get("tempo", {})

    if numerator < 1:
        problems.append("meter numerator is not positive")
    for index, beat in enumerate(beats):
        if not 1 <= int(beat.get("beat_in_bar", 0)) <= max(1, numerator):
            problems.append(f"beat {index} has beat_in_bar outside the meter")
            break
        if bool(beat.get("downbeat")) != (int(beat.get("beat_in_bar", 0)) == 1):
            problems.append(f"beat {index} disagrees with the rule that a downbeat is beat 1")
            break

    if beats:
        declared = int(grid.get("bars", 0))
        used = max(int(beat.get("bar", 0)) for beat in beats)
        if declared < used:
            problems.append(f"grid declares {declared} bars but beats reach bar {used}")

    global_bpm = float(tempo.get("global_bpm", 0.0))
    segments = tempo.get("segments", [])
    if not segments:
        problems.append("no tempo segment at all")
    # A single segment and the global tempo may be derived by different
    # estimators over the same beats, so a fraction of a percent apart is not a
    # contradiction - the lightweight path does exactly that. What must not
    # happen is the two saying different things about the music, which is what
    # the 1% band catches.
    # A segment the pipeline synthesized from the global tempo must match it to
    # serialization; one from the backend's own estimator may differ by a fraction
    # of a percent, which is two estimators agreeing rather than contradicting.
    synthesized = diagnostics.get("tempo_segments_source") == "synthesized-from-global"
    if not beats:
        problems.append("the project has no beats at all")
    if global_bpm <= 0 and beats:
        problems.append(f"global tempo is {global_bpm} with {len(beats)} beats")
    if diagnostics.get("tempo_source") == "measured" and len(beats) < 2:
        problems.append("tempo is labelled measured although no tempo could be measured")
    for index, segment in enumerate(segments):
        bpm = float(segment.get("bpm", 0.0))
        if len(segments) != 1:
            continue  # a variable-tempo piece is supposed to disagree
        allowed = 1e-6 if synthesized else 0.01 * global_bpm
        if abs(bpm - global_bpm) > allowed:
            problems.append(f"segment {index} says {bpm} BPM while the project says {global_bpm}")
    for key in ("meter_source", "tempo_source", "tempo_segments_source"):
        if key not in diagnostics:
            problems.append(f"{key} is not reported")
    # The schema is the strongest statement of self-consistency available.
    problems.extend(f"schema: {error}" for error in validate_rhythm_v4(project)[:3])
    if numerator > 16:
        problems.append(f"meter numerator {numerator} exceeds what the schema allows")
    if diagnostics.get("tempo_source") == "prior-fallback" and beats:
        problems.append("tempo is labelled a prior fallback although beats exist")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--backends", nargs="+", default=["lightweight", "enhanced"])
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=Path("build/product-output-comparison.json"))
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--audio-root", type=Path, default=REPO_ROOT / "build/public-benchmark/audio/BallroomData")
    parser.add_argument("--annotation-root", type=Path, default=REPO_ROOT / "build/public-benchmark/annotations")
    args = parser.parse_args()
    # The enhanced backend pins its device through the environment, so the flag has
    # to reach it there or the comparison silently runs on CPU.
    os.environ["BEATSCOPE_MODEL_DEVICE"] = args.device

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    selected = [row["track_id"] for row in manifest["tracks"] if args.split in ("all", row["split"])][: args.limit]
    audio = {path.stem: path for path in args.audio_root.rglob("*.wav")}
    annotations = {path.stem: path for path in args.annotation_root.rglob("*.beats")}
    missing_audio = [track for track in selected if track not in audio]
    missing_annotation = [track for track in selected if track in audio and track not in annotations]

    rows = []
    for track_id in selected:
        if track_id not in audio or track_id not in annotations:
            continue
        reference, reference_downbeats = read_ballroom_annotation(annotations[track_id])
        entry: dict = {"track_id": track_id, "backends": {}}
        for backend in args.backends:
            project = analyze_track(
                audio[track_id],
                AnalysisConfig.from_dict({"backend": backend}),
            )
            beats = [float(beat["time"]) for beat in project.get("beats", [])]
            published_downbeats = [float(beat["time"]) for beat in project.get("beats", []) if beat.get("downbeat")]
            entry["backends"][backend] = {
                "f_measure": evaluate_events(reference, beats)["f_measure"] if len(beats) > 1 else 0.0,
                # The downbeats are evaluated, not merely checked for legality: the
                # numbering was changed to carry the model's own, and that is what to measure.
                "downbeat_f_measure": (
                    evaluate_events(reference_downbeats, published_downbeats)["f_measure"]
                    if len(reference_downbeats) > 1 and len(published_downbeats) > 1
                    else None
                ),
                "beats": len(beats),
                "bars": project.get("grid", {}).get("bars"),
                "numerator": project.get("meter", {}).get("numerator"),
                "problems": consistency_problems(project),
            }
        rows.append(entry)

    if not rows:
        raise SystemExit("no tracks matched")

    print(f"  {len(rows)} of {len(selected)} selected tracks evaluated ({args.split} split), backends {args.backends}")
    print(f"  skipped: {len(missing_audio)} without audio, {len(missing_annotation)} without annotation")
    print(f"\n  {'track':<28} " + " ".join(f"{b:>22}" for b in args.backends))
    for entry in rows:
        cells = []
        for backend in args.backends:
            payload = entry["backends"][backend]
            mark = "ok" if not payload["problems"] else f"{len(payload['problems'])} problem(s)"
            cells.append(f"{payload['f_measure']:.4f} n={payload['beats']:<3} {mark:<8}")
        print(f"  {entry['track_id'][:27]:<28} " + " ".join(f"{cell:>22}" for cell in cells))

    print()
    for backend in args.backends:
        values = [entry["backends"][backend]["f_measure"] for entry in rows]
        problems = sum(len(entry["backends"][backend]["problems"]) for entry in rows)
        scored = [entry["backends"][backend]["downbeat_f_measure"] for entry in rows]
        scored = [value for value in scored if value is not None]
        downbeat = f"{statistics.fmean(scored):.4f} (n={len(scored)})" if scored else "not scorable"
        print(f"  {backend:<12} macro Beat F1 {statistics.fmean(values):.4f}   downbeat F1 {downbeat}   "
              f"consistency problems {problems}")
        for entry in rows:
            for problem in entry["backends"][backend]["problems"]:
                print(f"      {entry['track_id'][:26]}: {problem}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"split": args.split, "tracks": rows}, indent=2), encoding="utf-8")
    print(f"\n  written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
