"""The dataset manifest: pinned tracks and a split that means something.

The manifest is what makes a benchmark run reproducible after the audio is gone
(it is ignored build storage) and what keeps development from tuning on the
tracks it reports on. These tests check the committed manifest's integrity and
the split rule, not the local corpus: a fresh clone has no audio.
"""
import hashlib
import json
from pathlib import Path

from scripts.build_benchmark_manifest import TEST_EVERY, build_manifest, genre_balanced_order

MANIFEST = Path("evaluations/public-beat/ballroom-manifest-v1.json")


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_pins_every_track_with_both_hashes():
    manifest = _manifest()
    tracks = manifest["tracks"]
    assert manifest["schema"] == "beatscope-benchmark-manifest-1"
    assert manifest["dataset"]["annotation_revision"], "the annotation revision must be pinned"
    assert len(tracks) == manifest["splits"]["total"] == 698
    for row in tracks:
        assert set(row) == {"track_id", "genre", "split", "audio_sha256", "annotation_sha256"}
        assert row["split"] in ("dev", "test")
        for key in ("audio_sha256", "annotation_sha256"):
            assert len(row[key]) == 64 and all(c in "0123456789abcdef" for c in row[key])
    assert [row["track_id"] for row in tracks] == sorted(row["track_id"] for row in tracks)
    assert len({row["track_id"] for row in tracks}) == len(tracks)


def test_the_split_is_at_song_level_and_balanced_across_genres():
    """Every fifth track of a genre-balanced order, so no genre lands only in dev."""
    manifest = _manifest()
    assert manifest["splits"]["test_every"] == TEST_EVERY
    counts = manifest["splits"]
    assert counts["dev"] + counts["test"] == counts["total"]
    assert counts["test"] == 140, "one in five of 698, off by the rounding"

    by_genre: dict[str, set[str]] = {}
    for row in manifest["tracks"]:
        by_genre.setdefault(row["genre"], set()).add(row["split"])
    assert all(splits == {"dev", "test"} for splits in by_genre.values()), (
        "a genre with no test track would make its dev score unverifiable"
    )


def test_manifest_bytes_are_canonical_and_stable():
    """A regenerated manifest must be byte-identical, or it is not a pin."""
    from beatscope.public_benchmark import canonical_report_bytes

    payload = _manifest()
    assert MANIFEST.read_bytes() == canonical_report_bytes(payload)
    # Rebuilding from the parsed content reproduces the same bytes.
    assert canonical_report_bytes(json.loads(json.dumps(payload))) == MANIFEST.read_bytes()


def test_the_split_rule_is_a_pure_function_of_the_track_list():
    class Track:
        def __init__(self, track_id: str, genre: str):
            self.track_id = track_id
            self.genre = genre

    tracks = [Track(f"song-{index:02d}", ("Jive", "Waltz", "Tango")[index % 3]) for index in range(15)]
    first = [track.track_id for track in genre_balanced_order(tracks)]
    second = [track.track_id for track in genre_balanced_order(list(reversed(tracks)))]
    assert first == second, "the order must not depend on the input order"
    # Round-robin: the first three entries cover three different genres.
    assert len({track.genre for track in genre_balanced_order(tracks)[:3]}) == 3


def test_a_manifest_matches_the_local_corpus_when_it_is_present():
    """When the audio is unpacked, the pins must still describe it."""
    import pytest

    from scripts.build_benchmark_manifest import REPO_ROOT

    audio_root = REPO_ROOT / "build/public-benchmark/audio/BallroomData"
    annotation_root = next(
        iter(sorted((REPO_ROOT / "build/public-benchmark/annotations").glob("BallroomAnnotations-*"))),
        None,
    )
    if not audio_root.is_dir() or annotation_root is None:
        pytest.skip("local Ballroom corpus is not unpacked")

    rebuilt = build_manifest(audio_root, annotation_root)
    committed = _manifest()
    assert rebuilt == committed, "the manifest no longer describes the local corpus"
    assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == hashlib.sha256(
        MANIFEST.read_bytes()
    ).hexdigest()
