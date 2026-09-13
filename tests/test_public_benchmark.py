import hashlib
import json
from pathlib import Path

import pytest

from beatscope.public_benchmark import (
    BenchmarkTrack,
    cached_estimator,
    canonical_report_bytes,
    discover_ballroom_tracks,
    read_ballroom_annotation,
    report_markdown,
    run_public_benchmark,
    select_stratified,
)


def test_prediction_cache_is_content_addressed_and_reused(tmp_path: Path) -> None:
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"first")
    calls = []

    def estimator(path: Path):
        calls.append(path.read_bytes())
        return [0.1234567894, 1.0], [0.1234567894]

    cached = cached_estimator(estimator, tmp_path / "cache", "example-v1")
    assert cached(audio) == ([0.123456789, 1.0], [0.123456789])
    assert cached(audio) == ([0.123456789, 1.0], [0.123456789])
    audio.write_bytes(b"second")
    assert cached(audio) == ([0.123456789, 1.0], [0.123456789])
    assert calls == [b"first", b"second"]


def _track(root: Path, genre: str, name: str, rows: str) -> BenchmarkTrack:
    audio = root / "audio" / genre / f"{name}.wav"
    annotation = root / "annotations" / f"{name}.beats"
    audio.parent.mkdir(parents=True, exist_ok=True)
    annotation.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"RIFF")
    annotation.write_text(rows, encoding="utf-8")
    return BenchmarkTrack(name, genre, audio, annotation)


def test_reads_beats_and_downbeats_without_quantizing(tmp_path):
    path = tmp_path / "song.beats"
    path.write_text("0.1234 4\n0.7012 1\n1.2999 2\n", encoding="utf-8")
    assert read_ballroom_annotation(path) == ([0.1234, 0.7012, 1.2999], [0.7012])


@pytest.mark.parametrize("rows", ["0 1\n", "0 1\n0 2\n", "nan 1\n1 2\n", "0 nope\n1 2\n"])
def test_rejects_invalid_annotations(tmp_path, rows):
    path = tmp_path / "bad.beats"
    path.write_text(rows, encoding="utf-8")
    with pytest.raises(ValueError):
        read_ballroom_annotation(path)


def test_discovers_and_selects_a_stable_balanced_subset(tmp_path):
    rows = "0 1\n0.5 2\n"
    for genre in ("Jive", "Waltz"):
        for index in range(3):
            _track(tmp_path, genre, f"{genre}-{index}", rows)
    found = discover_ballroom_tracks(tmp_path / "audio", tmp_path / "annotations")
    first = select_stratified(found, 4)
    second = select_stratified(reversed(found), 4)
    assert [item.track_id for item in first] == [item.track_id for item in second]
    assert {item.genre for item in first} == {"Jive", "Waltz"}


def test_discovery_normalizes_the_three_rumba_folders(tmp_path):
    rows = "0 1\n0.5 2\n"
    _track(tmp_path, "Rumba-American", "american", rows)
    _track(tmp_path, "Rumba-International", "international", rows)
    _track(tmp_path, "Rumba-Misc", "misc", rows)
    found = discover_ballroom_tracks(tmp_path / "audio", tmp_path / "annotations")
    assert {item.genre for item in found} == {"Rumba"}


def test_report_is_deterministic_and_keeps_failures_explicit(tmp_path, monkeypatch):
    good = _track(tmp_path, "Jive", "good", "0 1\n0.5 2\n1 3\n")
    bad = _track(tmp_path, "Waltz", "bad", "0 1\n0.5 2\n1 3\n")
    monkeypatch.setattr(
        "beatscope.public_benchmark.evaluate_events",
        lambda reference, estimated: {
            "f_measure": 0.5,
            "cemgil": 0.4,
            "cmlc": 0.3,
            "cmlt": 0.2,
            "amlc": 0.6,
            "amlt": 0.7,
        },
    )

    def estimator(path):
        if path.stem == "bad":
            raise RuntimeError("deliberate")
        return [0.01, 0.51, 1.01], []

    report = run_public_benchmark([good, bad], {"test": estimator})
    assert len(report["systems"]["test"]["tracks"]) == 1
    assert report["systems"]["test"]["failures"] == [
        {"track_id": "bad", "error": "RuntimeError: deliberate"}
    ]
    assert canonical_report_bytes(report) == canonical_report_bytes(report)
    assert "| test | 1 | 1 | 0.500 | 0.200 | 0.700 | — |" in report_markdown(report)


def test_parallel_report_preserves_input_order(tmp_path, monkeypatch):
    tracks = [
        _track(tmp_path, "Jive", f"song-{index}", "0 1\n0.5 2\n1 3\n")
        for index in range(6)
    ]
    monkeypatch.setattr(
        "beatscope.public_benchmark.evaluate_events",
        lambda reference, estimated: {key: 1.0 for key in (
            "f_measure", "cemgil", "cmlc", "cmlt", "amlc", "amlt"
        )},
    )
    report = run_public_benchmark(
        tracks,
        {"test": lambda path: ([0.0, 0.5, 1.0], [])},
        workers=3,
    )
    assert [row["track_id"] for row in report["systems"]["test"]["tracks"]] == [
        track.track_id for track in tracks
    ]


def test_parallel_worker_count_must_be_positive():
    with pytest.raises(ValueError, match="workers must be positive"):
        run_public_benchmark([], {}, workers=0)


def test_recorded_public_measurement_is_canonical_and_hash_locked():
    path = Path("evaluations/public-beat/ballroom-32-v1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.read_bytes() == canonical_report_bytes(payload)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "796a15bd4b170f2b56dd8a20deeb56f5fad72231cb9199e6bd4bbd07c733a6e2"
    )
    assert payload["dataset"]["selected_tracks"] == 32
    assert all(not system["failures"] for system in payload["systems"].values())


def test_recorded_balanced_half_is_canonical_and_hash_locked():
    """The published measurement is a deterministic genre-balanced half."""
    path = Path("evaluations/public-beat/ballroom-349-v1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.read_bytes() == canonical_report_bytes(payload)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "e048db449892a23e3b4640727757ce5139ff5401f7aa5cc86d7918f6292a6ad9"
    )
    assert payload["dataset"]["selected_tracks"] == 349
    assert all(not system["failures"] for system in payload["systems"].values())
