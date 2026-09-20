"""Score the onset extractors against real annotations.

CPJKU/onset_db carries 58 onset annotations derived from Ballroom, one per
ten-second snippet, named `al_<track>(<start>-<end>).onsets`. The times inside
are relative to the snippet - checked rather than assumed: every file's first
onset falls inside [0, 10), none falls inside the absolute window, and the median
span is 9.81 s against a 10 s crop.

That is enough to score an extractor on real music without labelling anything by
hand, which is the blocker the accuracy plan names. What it is not is a final
evaluation: 58 snippets cover Ballroom only, and the plan's own rule applies -
Ballroom is where the base model trained, so this measures the extractor, not
generalization.

Matching is greedy one-to-one at a tolerance, which is the standard onset
convention; the tolerance is reported rather than hidden, and so is recall, so a
detector cannot look precise by finding almost nothing.

Usage:
    python scripts/evaluate_onsets.py --onset-db build/onset_db --limit 58
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
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

NAME = re.compile(r"^al_(?P<track>.+)\((?P<start>[\d.]+)-(?P<end>[\d.]+)\)\.onsets$")
TOLERANCE_SECONDS = 0.050


def read_annotations(path: Path) -> list[float]:
    times = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        times.append(float(stripped.split()[0]))
    return sorted(times)


def match_counts(reference: list[float], estimated: list[float], tolerance: float) -> tuple[int, int, int]:
    """Greedy one-to-one matching; returns (matched, len(reference), len(estimated))."""
    used = [False] * len(estimated)
    matched = 0
    for wanted in reference:
        best, best_distance = -1, tolerance
        for index, found in enumerate(estimated):
            if used[index]:
                continue
            distance = abs(found - wanted)
            if distance <= best_distance:
                best, best_distance = index, distance
        if best >= 0:
            used[best] = True
            matched += 1
    return matched, len(reference), len(estimated)


def score(reference: list[float], estimated: list[float]) -> dict[str, float]:
    if not reference or not estimated:
        return {"precision": 0.0, "recall": 0.0, "f_measure": 0.0}
    matched, total_reference, total_estimated = match_counts(reference, estimated, TOLERANCE_SECONDS)
    precision = matched / total_estimated
    recall = matched / total_reference
    f_measure = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f_measure": round(f_measure, 4)}


def snippets_for_split(onset_db: Path, audio_root: Path, manifest_path: Path, split: str):
    """Snippet paths for one side of the manifest's song-level split.

    Tuning on the same snippets a number is reported from is how a parameter gets
    fitted to noise. The split comes from the committed manifest, so it is the
    same one every run.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    split_of = {row["track_id"]: row["split"] for row in manifest["tracks"]}
    audio_index = {path.stem: path for path in audio_root.rglob("*.wav")}
    found = []
    for path in sorted(onset_db.glob("al_*.onsets")):
        match = NAME.match(path.name)
        if match is None or match.group("track") not in audio_index:
            continue
        if split in ("all", split_of.get(match.group("track"))):
            found.append((match.group("track"), float(match.group("start")), float(match.group("end")), path))
    return found, audio_index


def sweep_prominence(snippets, audio_index, ratios) -> dict[float, dict[str, float]]:
    """Score the full v2 extractor at several prominence ratios, novelty once."""
    collected: dict[float, list[dict[str, float]]] = {ratio: [] for ratio in ratios}
    for track, start, end, annotation_path in snippets:
        signal, sample_rate = load_analysis_audio(audio_index[track])[:2]
        snippet = signal[int(round(start * sample_rate)):int(round(end * sample_rate))]
        reference = read_annotations(annotation_path)
        times, novelty = compute_multiband_novelty(snippet, sample_rate, 256, version=2)
        raw = compute_raw_band_novelty(snippet, sample_rate, 256, version=2)[1]
        for ratio in ratios:
            found = extract_onsets(
                times, novelty, sample_rate, 256, version=2, raw_novelty=raw, prominence_ratio=ratio
            )
            collected[ratio].append(score(reference, [onset["raw_time"] for onset in found]))
    return {
        ratio: {key: round(statistics.fmean(row[key] for row in rows), 4)
                for key in ("precision", "recall", "f_measure")}
        for ratio, rows in collected.items()
    }


def sweep_valley_ratio(snippets, audio_index, ratios) -> dict[float, dict[str, float]]:
    """Score the full v2 extractor at several valley ratios on the same novelty.

    The novelty does not depend on the ratio, so it is computed once per snippet
    and the ratios are applied to it - otherwise a sweep costs one full extraction
    pass per value.
    """
    collected: dict[float, list[dict[str, float]]] = {ratio: [] for ratio in ratios}
    for track, start, end, annotation_path in snippets:
        signal, sample_rate = load_analysis_audio(audio_index[track])[:2]
        snippet = signal[int(round(start * sample_rate)):int(round(end * sample_rate))]
        reference = read_annotations(annotation_path)
        times, novelty = compute_multiband_novelty(snippet, sample_rate, 256, version=2)
        raw = compute_raw_band_novelty(snippet, sample_rate, 256, version=2)[1]
        for ratio in ratios:
            found = extract_onsets(
                times, novelty, sample_rate, 256, version=2, raw_novelty=raw, valley_ratio=ratio
            )
            collected[ratio].append(score(reference, [onset["raw_time"] for onset in found]))
    return {
        ratio: {key: round(statistics.fmean(row[key] for row in rows), 4)
                for key in ("precision", "recall", "f_measure")}
        for ratio, rows in collected.items()
    }


def extract(signal, sample_rate: int, hop: int, stage: str) -> list[float]:
    if stage == "v1":
        times, novelty = compute_multiband_novelty(signal, sample_rate, hop, version=1)
        onsets = extract_onsets(times, novelty, sample_rate, hop, version=1)
    else:
        times, novelty = compute_multiband_novelty(signal, sample_rate, hop, version=2)
        raw = compute_raw_band_novelty(signal, sample_rate, hop, version=2)[1]
        onsets = extract_onsets(
            times,
            novelty,
            sample_rate,
            hop,
            version=2,
            raw_novelty=raw,
            local_threshold=stage in ("v2-flux+local", "v2"),
            dense_candidates=stage == "v2",
        )
    return [float(onset["raw_time"]) for onset in onsets]


STAGES = ("v1", "v2-flux", "v2-flux+local", "v2")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onset-db", type=Path, required=True, help="checkout of CPJKU/onset_db")
    parser.add_argument("--audio-root", type=Path, default=Path("build/public-benchmark/audio/BallroomData"))
    parser.add_argument("--limit", type=int, default=58)
    parser.add_argument("--output", type=Path, default=Path("build/onset-evaluation.json"))
    parser.add_argument("--split", choices=("all", "dev", "test"), default="all",
                        help="which side of the manifest's song-level split to score")
    parser.add_argument("--manifest", type=Path, default=Path("evaluations/public-beat/ballroom-manifest-v1.json"))
    parser.add_argument("--sweep-valley-ratio", type=float, nargs="+", default=None,
                        help="score the full v2 extractor at these valley ratios instead of the stages")
    parser.add_argument("--sweep-prominence", type=float, nargs="+", default=None,
                        help="score the full v2 extractor at these prominence ratios instead of the stages")
    args = parser.parse_args()

    if args.sweep_prominence:
        chosen, audio_index = snippets_for_split(args.onset_db, args.audio_root, args.manifest, args.split)
        if not chosen:
            raise SystemExit(f"no snippets for split {args.split}")
        print(f"  {len(chosen)} snippets ({args.split}), sweeping prominence_ratio")
        table = sweep_prominence(chosen, audio_index, args.sweep_prominence)
        print(f"\n  {'prominence':<16} {'precision':>10} {'recall':>8} {'F1':>8}")
        for ratio, means in table.items():
            print(f"  {ratio:<16} {means['precision']:>10.3f} {means['recall']:>8.3f} {means['f_measure']:>8.3f}")
        return 0

    if args.sweep_valley_ratio:
        chosen, audio_index = snippets_for_split(args.onset_db, args.audio_root, args.manifest, args.split)
        if not chosen:
            raise SystemExit(f"no snippets for split {args.split}")
        print(f"  {len(chosen)} snippets ({args.split}), sweeping valley_ratio")
        table = sweep_valley_ratio(chosen, audio_index, args.sweep_valley_ratio)
        print(f"\n  {'valley_ratio':<16} {'precision':>10} {'recall':>8} {'F1':>8}")
        for ratio, means in table.items():
            print(f"  {ratio:<16} {means['precision']:>10.3f} {means['recall']:>8.3f} {means['f_measure']:>8.3f}")
        return 0

    audio_index = {path.stem: path for path in args.audio_root.rglob("*.wav")}
    snippets = []
    for path in sorted(args.onset_db.glob("al_*.onsets"))[: args.limit]:
        match = NAME.match(path.name)
        if match is None or match.group("track") not in audio_index:
            continue
        snippets.append((match.group("track"), float(match.group("start")), float(match.group("end")), path))
    if not snippets:
        raise SystemExit("no snippets matched local audio")

    rows = []
    for track, start, end, annotation_path in snippets:
        signal, sample_rate = load_analysis_audio(audio_index[track])[:2]
        first, last = int(round(start * sample_rate)), int(round(end * sample_rate))
        snippet = signal[first:last]
        reference = read_annotations(annotation_path)
        row = {"track_id": track, "crop": [start, end], "annotated": len(reference)}
        for stage in STAGES:
            row[stage] = score(reference, extract(snippet, sample_rate, 256, stage))
        rows.append(row)

    print(f"  {len(rows)} snippets, {sum(row['annotated'] for row in rows)} annotated onsets, "
          f"tolerance +-{int(TOLERANCE_SECONDS * 1000)} ms")
    print(f"\n  {'stage':<16} {'precision':>10} {'recall':>8} {'F1':>8}   (macro mean)")
    for stage in STAGES:
        means = {key: round(statistics.fmean(row[stage][key] for row in rows), 4)
                 for key in ("precision", "recall", "f_measure")}
        print(f"  {stage:<16} {means['precision']:>10.3f} {means['recall']:>8.3f} {means['f_measure']:>8.3f}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"snippets": rows, "tolerance_seconds": TOLERANCE_SECONDS}, indent=2), encoding="utf-8")
    print(f"\n  written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
