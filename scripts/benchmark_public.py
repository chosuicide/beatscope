"""Run BeatScope and optional baselines on a local Ballroom dataset."""
from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path

from beatscope.public_benchmark import (
    beat_this_estimator,
    beatscope_estimator,
    cached_estimator,
    canonical_report_bytes,
    discover_ballroom_tracks,
    librosa_estimator,
    report_markdown,
    run_public_benchmark,
    select_stratified,
)
from beatscope.schema import ANALYZER_VERSION


def _version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--annotation-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("build/public-benchmark/results"))
    parser.add_argument("--limit", type=int, help="stable genre-balanced subset; omit for all 698 tracks")
    parser.add_argument(
        "--systems",
        nargs="+",
        choices=("beatscope", "librosa", "beat-this"),
        default=("beatscope", "librosa"),
    )
    parser.add_argument("--beat-this-model", default="final0")
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="parallel track workers; use 1 for constrained machines",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("build/public-benchmark/predictions"),
        help="content-addressed prediction cache used to resume interrupted runs",
    )
    args = parser.parse_args()

    tracks = select_stratified(
        discover_ballroom_tracks(args.audio_root, args.annotation_root),
        args.limit,
    )
    estimators = {}
    for name in args.systems:
        if name == "beatscope":
            system_id = f"beatscope-lightweight-{ANALYZER_VERSION}"
            estimators[system_id] = cached_estimator(
                beatscope_estimator,
                args.cache_dir,
                system_id,
            )
        elif name == "librosa":
            system_id = f"librosa-default-{_version('librosa')}"
            estimators[system_id] = cached_estimator(
                librosa_estimator,
                args.cache_dir,
                system_id,
            )
        else:
            estimator = beat_this_estimator(args.beat_this_model, args.device)
            system_id = (
                f"beat-this-{_version('beat-this')}-{args.beat_this_model}-{args.device}"
            )
            estimators[system_id] = cached_estimator(
                estimator,
                args.cache_dir,
                system_id,
            )

    report = run_public_benchmark(tracks, estimators, workers=args.workers)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_bytes(canonical_report_bytes(report))
    (args.output_dir / "results.md").write_text(report_markdown(report), encoding="utf-8", newline="\n")
    print(json.dumps({
        "output": str(args.output_dir),
        "tracks": len(tracks),
        "systems": list(estimators),
        "failures": {name: len(data["failures"]) for name, data in report["systems"].items()},
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
