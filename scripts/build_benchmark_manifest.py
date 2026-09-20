"""Write the dataset manifest the accuracy work needs.

A run is only reproducible if the tracks are pinned, and a comparison is only
honest if the tracks used to tune something are not the tracks used to report
it. The manifest records both: every track's audio and annotation hash, and a
deterministic song-level split.

Ballroom is a development corpus here, not the final word: the refinement work
has to report its headline number on material the base model did not train on.
The split below separates development from an internal check; it does not make
Ballroom a held-out set.

Usage:
    python scripts/build_benchmark_manifest.py \
        --audio-root build/public-benchmark/audio/BallroomData \
        --annotation-root build/public-benchmark/annotations/BallroomAnnotations-<rev> \
        --output evaluations/public-beat/ballroom-manifest-v1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from beatscope.public_benchmark import (  # noqa: E402
    BALLROOM_ANNOTATION_REVISION,
    BALLROOM_AUDIO_MD5,
    BALLROOM_AUDIO_URL,
    BALLROOM_LICENSE,
    canonical_report_bytes,
    discover_ballroom_tracks,
)

MANIFEST_SCHEMA = "beatscope-benchmark-manifest-1"
# One track in five, taken from a genre-balanced order, is the internal check.
TEST_EVERY = 5


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def genre_balanced_order(tracks) -> list:
    """Order tracks by genre round-robin, then by a hash of the track id.

    The same idea the benchmark's subset selection uses: every genre appears
    early, so a prefix of this order is representative rather than alphabetical.
    """
    by_genre: dict[str, list] = {}
    for track in sorted(
        tracks,
        key=lambda item: (hashlib.sha256(f"ballroom-v1\0{item.track_id}".encode()).hexdigest(), item.track_id),
    ):
        by_genre.setdefault(track.genre, []).append(track)
    ordered: list = []
    genres = sorted(by_genre)
    while any(by_genre[genre] for genre in genres):
        for genre in genres:
            if by_genre[genre]:
                ordered.append(by_genre[genre].pop(0))
    return ordered


def build_manifest(audio_root: Path, annotation_root: Path) -> dict:
    tracks = discover_ballroom_tracks(audio_root, annotation_root)
    ordered = genre_balanced_order(tracks)
    rows = []
    for position, track in enumerate(ordered):
        rows.append(
            {
                "track_id": track.track_id,
                "genre": track.genre,
                "split": "test" if position % TEST_EVERY == 0 else "dev",
                "audio_sha256": _sha256(track.audio_path),
                "annotation_sha256": _sha256(track.annotation_path),
            }
        )
    rows.sort(key=lambda row: row["track_id"])
    counts = {split: sum(1 for row in rows if row["split"] == split) for split in ("dev", "test")}
    return {
        "schema": MANIFEST_SCHEMA,
        "dataset": {
            "name": "Ballroom",
            "license": BALLROOM_LICENSE,
            "audio_url": BALLROOM_AUDIO_URL,
            "audio_md5": BALLROOM_AUDIO_MD5,
            "annotation_revision": BALLROOM_ANNOTATION_REVISION,
            "note": (
                "Development corpus, not a held-out set: the final claim needs material "
                "the base model did not train on. The split separates development from an "
                "internal check at song level."
            ),
        },
        "splits": {**counts, "test_every": TEST_EVERY, "total": len(rows)},
        "tracks": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--annotation-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evaluations/public-beat/ballroom-manifest-v1.json"))
    args = parser.parse_args()

    manifest = build_manifest(args.audio_root, args.annotation_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_report_bytes(manifest))
    print(json.dumps({"output": str(args.output), "splits": manifest["splits"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
