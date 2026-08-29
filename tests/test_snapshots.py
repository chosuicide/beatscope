"""Snapshot tests for the current analysis entry points.

These tests do not claim the current behavior is correct; they record what it
is before the Rhythm IR refactor changes it. After an intentional behavior
change, regenerate the committed snapshots with:

    python tests/record_snapshots.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapshot_utils import canonical_snapshot, diff_snapshots

try:
    import librosa  # noqa: F401
    _HAS_LIBROSA = True
except ImportError:
    _HAS_LIBROSA = False

requires_librosa = pytest.mark.skipif(not _HAS_LIBROSA, reason="librosa is not installed")

SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "legacy"


def load_snapshot(name: str) -> dict:
    path = SNAPSHOT_DIR / f"{name}.json"
    if not path.is_file():
        pytest.fail(f"Missing snapshot {path}; regenerate with: python tests/record_snapshots.py")
    return json.loads(path.read_text(encoding="utf-8"))


def assert_matches_snapshot(name: str, project: dict) -> None:
    expected = load_snapshot(name)
    diffs = diff_snapshots(expected, canonical_snapshot(project))
    assert not diffs, f"Snapshot '{name}' diverged (expected -> actual):\n" + "\n".join(diffs[:8])


@requires_librosa
def test_lightweight_web_path_snapshot(fixed_120_audio, run_web_analysis):
    assert_matches_snapshot("lightweight_web", run_web_analysis(fixed_120_audio))


@requires_librosa
def test_rhythm_path_snapshot(fixed_120_audio, beat_file):
    from beatscope.rhythm import analyze_rhythm

    result = analyze_rhythm(fixed_120_audio, fixed_120_audio, beat_file)
    assert_matches_snapshot("rhythm_path", result)


@requires_librosa
def test_silence_web_snapshot(silence_audio, run_web_analysis):
    assert_matches_snapshot("silence_web", run_web_analysis(silence_audio))
