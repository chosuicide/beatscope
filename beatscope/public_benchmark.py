"""Reproducible evaluation against public beat annotations.

This stays separate from synthetic regression gates: it measures external
validity, never changes a baseline, and never downloads audio in normal tests.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from .pipeline import analyze_track

BALLROOM_ANNOTATION_REVISION = "1db08914a8ae15edb01f104046e30bad88effe67"
BALLROOM_AUDIO_MD5 = "2872a3e52070bc342a4510a95e2fa0b8"
BALLROOM_LICENSE = "CC BY-NC-SA 4.0"
BALLROOM_AUDIO_URL = "https://mtg.upf.edu/ismir2004/contest/tempoContest/data1.tar.gz"
BALLROOM_ANNOTATION_URL = (
    "https://github.com/CPJKU/BallroomAnnotations/archive/"
    f"{BALLROOM_ANNOTATION_REVISION}.zip"
)
REPORT_SCHEMA = "beatscope-public-beat-benchmark-1"


@dataclass(frozen=True)
class BenchmarkTrack:
    """One audio excerpt paired with its independent human annotation."""

    track_id: str
    genre: str
    audio_path: Path
    annotation_path: Path


Prediction = tuple[list[float], list[float]]
Estimator = Callable[[Path], Prediction]


def cached_estimator(estimator: Estimator, cache_dir: str | Path, system_id: str) -> Estimator:
    """Persist predictions so a long public-corpus run can resume safely."""
    cache_dir = Path(cache_dir)

    def estimate(audio_path: Path) -> Prediction:
        audio_sha256 = hashlib.sha256(audio_path.read_bytes()).hexdigest()
        cache_key = hashlib.sha256(
            f"{system_id}\0{audio_path.stem}\0{audio_sha256}".encode()
        ).hexdigest()
        cache_path = cache_dir / system_id / f"{cache_key}.json"
        if cache_path.is_file():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                payload.get("schema") == "beatscope-public-prediction-1"
                and payload.get("system_id") == system_id
                and payload.get("audio_sha256") == audio_sha256
            ):
                return (
                    [float(value) for value in payload["beats"]],
                    [float(value) for value in payload["downbeats"]],
                )
        beats, downbeats = estimator(audio_path)
        payload = {
            "schema": "beatscope-public-prediction-1",
            "system_id": system_id,
            "audio_sha256": audio_sha256,
            "beats": [round(float(value), 9) for value in beats],
            "downbeats": [round(float(value), 9) for value in downbeats],
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".tmp")
        temporary.write_bytes(canonical_report_bytes(payload))
        temporary.replace(cache_path)
        return payload["beats"], payload["downbeats"]

    return estimate


def read_ballroom_annotation(path: str | Path) -> tuple[list[float], list[float]]:
    """Read time/position rows and return beats plus downbeats."""
    beats: list[float] = []
    downbeats: list[float] = []
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 2:
            raise ValueError(f"{path}:{line_number}: expected time and beat position")
        try:
            time = float(fields[0])
            position = int(fields[1])
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid annotation row") from exc
        if not math.isfinite(time) or time < 0 or position < 1:
            raise ValueError(f"{path}:{line_number}: invalid annotation value")
        if beats and time <= beats[-1]:
            raise ValueError(f"{path}:{line_number}: beat times must increase")
        beats.append(time)
        if position == 1:
            downbeats.append(time)
    if len(beats) < 2:
        raise ValueError(f"{path}: annotation needs at least two beats")
    return beats, downbeats


def discover_ballroom_tracks(
    audio_root: str | Path,
    annotation_root: str | Path,
) -> list[BenchmarkTrack]:
    """Match the official recursive WAV tree to the flat annotation directory."""
    audio_root = Path(audio_root)
    annotation_root = Path(annotation_root)
    annotations = {path.stem: path for path in annotation_root.rglob("*.beats")}
    tracks: list[BenchmarkTrack] = []
    seen_ids: set[str] = set()
    for audio in sorted(audio_root.rglob("*.wav"), key=lambda path: path.as_posix()):
        annotation = annotations.get(audio.stem)
        if annotation is None:
            continue
        track_id = audio.stem
        if track_id in seen_ids:
            raise ValueError(f"duplicate Ballroom track id: {track_id}")
        seen_ids.add(track_id)
        raw_genre = audio.parent.name
        genre = "Rumba" if raw_genre.startswith("Rumba-") else raw_genre
        tracks.append(BenchmarkTrack(track_id, genre, audio, annotation))
    if not tracks:
        raise ValueError("no matching Ballroom WAV and .beats files found")
    return tracks


def select_stratified(tracks: Iterable[BenchmarkTrack], limit: int | None) -> list[BenchmarkTrack]:
    """Choose a stable, genre-balanced subset; None selects the full corpus."""
    ordered = sorted(
        tracks,
        key=lambda track: (
            hashlib.sha256(f"ballroom-v1\0{track.track_id}".encode()).hexdigest(),
            track.track_id,
        ),
    )
    if limit is None or limit >= len(ordered):
        return sorted(ordered, key=lambda track: track.track_id)
    if limit < 1:
        raise ValueError("limit must be positive")
    by_genre: dict[str, list[BenchmarkTrack]] = {}
    for track in ordered:
        by_genre.setdefault(track.genre, []).append(track)
    selected: list[BenchmarkTrack] = []
    genres = sorted(by_genre)
    while len(selected) < limit:
        progressed = False
        for genre in genres:
            bucket = by_genre[genre]
            if bucket and len(selected) < limit:
                selected.append(bucket.pop(0))
                progressed = True
        if not progressed:
            break
    return sorted(selected, key=lambda track: track.track_id)


def beatscope_estimator(audio_path: Path) -> Prediction:
    """Run the shipping lightweight analyzer and preserve exact beat times."""
    project = analyze_track(audio_path, {"backend": "lightweight"})
    beats = [float(beat["time"]) for beat in project.get("beats", [])]
    downbeats = [float(beat["time"]) for beat in project.get("beats", []) if beat.get("downbeat")]
    return beats, downbeats


def librosa_estimator(audio_path: Path) -> Prediction:
    """Small conventional baseline; librosa does not predict downbeats."""
    import librosa

    audio, sample_rate = librosa.load(audio_path, sr=None, mono=True)
    _, beats = librosa.beat.beat_track(y=audio, sr=sample_rate, units="time")
    return [float(value) for value in beats], []


def beat_this_estimator(model: str = "final0", device: str = "cpu") -> Estimator:
    """Create an official Beat This estimator when its optional package exists."""
    try:
        from beat_this.inference import File2Beats
    except ImportError as exc:
        raise RuntimeError("Beat This is unavailable; install the public-benchmark extra") from exc
    infer = File2Beats(checkpoint_path=model, device=device, dbn=False)

    def estimate(audio_path: Path) -> Prediction:
        beats, downbeats = infer(str(audio_path))
        return [float(value) for value in beats], [float(value) for value in downbeats]

    return estimate


_METRIC_NAMES = {
    "F-measure": "f_measure",
    "Cemgil": "cemgil",
    "Correct Metric Level Continuous": "cmlc",
    "Correct Metric Level Total": "cmlt",
    "Any Metric Level Continuous": "amlc",
    "Any Metric Level Total": "amlt",
}


def evaluate_events(reference: list[float], estimated: list[float]) -> dict[str, float]:
    """Evaluate with the standard mir_eval.beat implementation."""
    if len(reference) < 2 or len(estimated) < 2:
        return {name: 0.0 for name in _METRIC_NAMES.values()}
    try:
        import mir_eval
    except ImportError as exc:
        raise RuntimeError("mir_eval is unavailable; install the public-benchmark extra") from exc
    scores = mir_eval.beat.evaluate(
        np.asarray(reference, dtype=float),
        np.asarray(estimated, dtype=float),
        trim=True,
    )
    return {output: round(float(scores[source]), 6) for source, output in _METRIC_NAMES.items()}


def _aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, float] | None:
    values = [float(row[key]) for row in rows if key in row]
    if not values:
        return None
    return {"mean": round(statistics.fmean(values), 6), "median": round(statistics.median(values), 6)}


def run_public_benchmark(
    tracks: Iterable[BenchmarkTrack],
    estimators: dict[str, Estimator],
    *,
    workers: int = 1,
) -> dict[str, Any]:
    """Run every estimator on the same files and return a canonical report."""
    if workers < 1:
        raise ValueError("workers must be positive")
    selected = list(tracks)
    systems: dict[str, Any] = {}
    for name, estimator in estimators.items():
        rows: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []

        def evaluate_track(track: BenchmarkTrack) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
            try:
                reference, reference_downbeats = read_ballroom_annotation(track.annotation_path)
                estimated, estimated_downbeats = estimator(track.audio_path)
                row: dict[str, Any] = {
                    "track_id": track.track_id,
                    "genre": track.genre,
                    **evaluate_events(reference, estimated),
                    "reference_beats": len(reference),
                    "estimated_beats": len(estimated),
                }
                if estimated_downbeats:
                    row["downbeat_f_measure"] = evaluate_events(
                        reference_downbeats, estimated_downbeats
                    )["f_measure"]
                return row, None
            except Exception as exc:
                return None, {
                    "track_id": track.track_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        if workers == 1:
            outcomes = map(evaluate_track, selected)
        else:
            executor = ThreadPoolExecutor(max_workers=workers)
            outcomes = executor.map(evaluate_track, selected)
        try:
            for row, failure in outcomes:
                if row is not None:
                    rows.append(row)
                if failure is not None:
                    failures.append(failure)
        finally:
            if workers != 1:
                executor.shutdown(wait=True)
        aggregate = {
            key: value
            for key in (*_METRIC_NAMES.values(), "downbeat_f_measure")
            if (value := _aggregate(rows, key)) is not None
        }
        systems[name] = {"tracks": rows, "failures": failures, "aggregate": aggregate}
    return {
        "schema": REPORT_SCHEMA,
        "dataset": {
            "name": "Ballroom",
            "license": BALLROOM_LICENSE,
            "audio_url": BALLROOM_AUDIO_URL,
            "audio_md5": BALLROOM_AUDIO_MD5,
            "annotation_url": BALLROOM_ANNOTATION_URL,
            "annotation_revision": BALLROOM_ANNOTATION_REVISION,
            "selected_tracks": len(selected),
            "selection": "full" if len(selected) == 698 else "deterministic genre-balanced subset",
        },
        "evaluation": {
            "library": "mir_eval.beat",
            "trim_first_seconds": 5,
            "note": "External benchmark; not a CI gate and never updates synthetic baselines.",
        },
        "systems": systems,
    }


def report_markdown(report: dict[str, Any]) -> str:
    """Render a compact human-readable table from the machine report."""
    dataset = report["dataset"]
    lines = [
        "# Public beat benchmark",
        "",
        f"Dataset: **{dataset['name']}** ({dataset['license']}), "
        f"{dataset['selected_tracks']} tracks, {dataset['selection']}.",
        "",
        "| System | Tracks | Failed | F-measure | CMLt | AMLt | Downbeat F |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, system in report["systems"].items():
        aggregate = system["aggregate"]

        def value(key: str) -> str:
            return f"{aggregate[key]['mean']:.3f}" if key in aggregate else "—"

        lines.append(
            f"| {name} | {len(system['tracks'])} | {len(system['failures'])} | "
            f"{value('f_measure')} | {value('cmlt')} | {value('amlt')} | "
            f"{value('downbeat_f_measure')} |"
        )
    lines.extend([
        "",
        "Values are macro means across successfully evaluated tracks. "
        "They are measurements on this corpus, not claims about every genre.",
        "",
    ])
    return "\n".join(lines)


def canonical_report_bytes(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
