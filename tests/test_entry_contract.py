"""Cross-entry contract tests for the analysis pipeline.

Every CLI and web surface routes through ``analyze_track()`` and produces
identical canonical snapshots for the same input and config. The
instrument-labeled legacy outputs (kick/snare/hihat events, bass_notes)
are no longer reachable from any entry point; ``beatscope.analysis``
remains importable for unit tests and as a conversion helper source.
"""
from __future__ import annotations

import json

import pytest

from snapshot_utils import canonical_snapshot

try:
    import librosa  # noqa: F401
    _HAS_LIBROSA = True
except ImportError:
    _HAS_LIBROSA = False

requires_librosa = pytest.mark.skipif(not _HAS_LIBROSA, reason="librosa is not installed")


@requires_librosa
def test_web_upload_matches_analyze_track(fixed_120_audio, run_web_analysis):
    from beatscope.models import AnalysisConfig
    from beatscope.pipeline import analyze_track

    direct = analyze_track(fixed_120_audio, AnalysisConfig(subdivision=16, separation="auto"))
    web = run_web_analysis(fixed_120_audio)

    assert canonical_snapshot(web) == canonical_snapshot(direct)


@requires_librosa
def test_web_project_is_content_addressed_and_honest(fixed_120_audio, run_web_analysis):
    from beatscope.project import content_hash

    project = run_web_analysis(fixed_120_audio)

    assert project["project_id"] == content_hash(fixed_120_audio)[:12]
    assert project["schema_version"] == "4.0"
    assert project["analysis"]["backend"] == "lightweight"
    assert project["analysis"]["pipeline_version"] == "0.6.0"

    # No uncalibrated tempo confidence on the lightweight path.
    assert "confidence" not in project["tempo"]
    assert project["analysis"]["diagnostics"]["variable_tempo"] is False
    assert project["tempo"]["segments"][0]["method"] == "local-autocorrelation-viterbi+beat-dp"

    # v4 facts/cues separation: no instrument labels or confidence anywhere.
    serialized = json.dumps(project)
    for forbidden in ("kick", "snare", "hihat", "bass_808", "confidence"):
        assert f'"{forbidden}"' not in serialized

    # Honest provenance: beats come from the tracked DP chain, not a uniform grid.
    assert project["analysis"]["provenance"]["beats"]["method"] == "novelty-guided-dynamic-programming"
    assert project["cues"]["accent"] and all(
        isinstance(cue.get("onset"), int) for cue in project["cues"]["accent"]
    )
    assert "events" not in project and "bass_notes" not in project


@requires_librosa
def test_cli_analyze_matches_web_upload(fixed_120_audio, tmp_path, run_web_analysis):
    """The CLI and the web upload must produce the same RhythmProject."""
    import json

    from beatscope.cli import main

    output = tmp_path / "cli-out" / "fixed-120.rhythm.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    code = main([
        "analyze", str(fixed_120_audio),
        "--output", str(output),
        "--backend", "lightweight",
        "--subdivision", "16",
    ])
    assert code == 0
    cli_project = json.loads(output.read_text(encoding="utf-8"))

    web = run_web_analysis(fixed_120_audio)
    assert canonical_snapshot(cli_project) == canonical_snapshot(web)
