"""Baseline governance tests for the event-evidence fixtures (v0.11 Round 1).

These tests freeze the CURRENT analysis behavior on the deterministic
dense-mixture fixtures: raw onset counts, ``cues.accent`` membership counts,
generator-role match rates at +-50 ms, extraction-time errors, and per-case
onset hashes. They assert characterization, not perceptual truth: synthetic
roles describe generator intent, and nothing here claims the current accent
heuristic is correct.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

from beatscope.schema import validate_rhythm_v4
from tests.fixtures.event_evidence import generate_event_evidence as gen

COMMITTED_TRUTH = gen.TRUTH_PATH.read_text(encoding="utf-8")
COMMITTED_BASELINE = json.loads(gen.BASELINE_PATH.read_text(encoding="utf-8"))


def _rendered_hash(name: str, audio_dir: Path) -> str:
    """SHA-256 of the rendered WAV bytes, matching what ``collect`` hashes."""
    import hashlib

    wav_path = gen.render_case_wav(name, audio_dir)
    return hashlib.sha256(wav_path.read_bytes()).hexdigest()


@pytest.fixture(scope="session")
def audio_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("event-evidence-audio")


_original_analyze_case = gen.analyze_case


@lru_cache(maxsize=None)
def _analyzed(name: str, audio_dir: str) -> dict:
    wav_path = gen.render_case_wav(name, Path(audio_dir))
    return _original_analyze_case(wav_path)


def _current_characterization(audio_dir: Path) -> dict:
    entries: dict[str, dict] = {}
    for name in gen.AUDIO_CASES:
        entries[name] = gen.characterize_case(name, _analyzed(name, str(audio_dir)))
    entries["no-grid"] = gen.characterize_no_grid(gen.build_no_grid_project())
    return entries


def test_truth_manifest_regenerates_byte_identical(audio_dir: Path) -> None:
    audio_hashes = {name: _rendered_hash(name, audio_dir) for name in gen.AUDIO_CASES}
    regenerated = gen._canonical_json_text(gen.build_truth(audio_hashes))
    assert regenerated == COMMITTED_TRUTH


def test_committed_truth_and_baseline_schemas() -> None:
    truth = json.loads(COMMITTED_TRUTH)
    assert truth["schema"] == gen.TRUTH_SCHEMA
    assert truth["generator_version"] == gen.GENERATOR_VERSION
    assert set(truth["cases"]) == set(gen.AUDIO_CASES) | {"no-grid"}
    assert COMMITTED_BASELINE["schema"] == gen.BASELINE_SCHEMA
    assert "not perceptual" in COMMITTED_BASELINE["note"]


def test_baseline_matches_current_pipeline(audio_dir: Path) -> None:
    current = _current_characterization(audio_dir)
    diffs = gen._diff_dicts(
        {"cases": current},
        {"cases": COMMITTED_BASELINE["cases"]},
    )
    assert not diffs, "current pipeline behavior drifted from the committed baseline:\n" + "\n".join(diffs)


def test_offgrid_offsets_survive_extraction(audio_dir: Path) -> None:
    project = _analyzed("offgrid", str(audio_dir))
    truth = json.loads(COMMITTED_TRUTH)["cases"]["offgrid"]["events"]
    detected = [float(onset["time"]) for onset in project["onsets"]]
    matches = gen._greedy_match([event["time"] for event in truth], detected, gen.MATCH_TOLERANCE_SECONDS)
    assert len(matches) == len(truth), "every labelled off-grid transient must be matched at +-50 ms"
    for (_truth_index, detection_index), event in zip(matches, truth, strict=True):
        offset = event["grid_offset"]
        beat = event["nearest_beat"]
        detected_offset = detected[detection_index] - beat
        assert abs(detected_offset - offset) <= gen.OFFGRID_PRESERVATION_TOLERANCE_SECONDS, (
            f"detection {detected[detection_index]} collapsed onto the beat grid; "
            f"expected to stay {offset:+.3f} s from beat at {beat}"
        )


def test_no_grid_project_is_valid() -> None:
    project = gen.build_no_grid_project()
    assert project["beats"] == []
    assert validate_rhythm_v4(project) == []


def test_silence_produces_no_onsets(audio_dir: Path) -> None:
    project = _analyzed("silence", str(audio_dir))
    assert project["onsets"] == []


def test_baseline_drift_requires_accept_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    truth_copy = tmp_path / "event-evidence-truth.json"
    baseline_copy = tmp_path / "event-evidence-baseline.json"
    truth_copy.write_text(COMMITTED_TRUTH, encoding="utf-8", newline="\n")
    tampered = json.loads(gen.BASELINE_PATH.read_text(encoding="utf-8"))
    tampered["cases"]["offgrid"]["raw_onset_count"] += 1
    baseline_copy.write_text(gen._canonical_json_text(tampered), encoding="utf-8", newline="\n")

    monkeypatch.setattr(gen, "TRUTH_PATH", truth_copy)
    monkeypatch.setattr(gen, "BASELINE_PATH", baseline_copy)
    monkeypatch.setattr(gen, "analyze_case", lambda wav_path: _analyzed(wav_path.stem, str(tmp_path)))

    audio_dir = tmp_path / "audio"
    assert gen.main(["--audio-dir", str(audio_dir)]) == 1
    output = capsys.readouterr().out
    assert "event-evidence-baseline.json drifted" in output
    assert "offgrid" in output

    assert gen.main(["--audio-dir", str(audio_dir), "--accept-baseline"]) == 0
    accepted = json.loads(baseline_copy.read_text(encoding="utf-8"))
    assert accepted["cases"]["offgrid"] == COMMITTED_BASELINE["cases"]["offgrid"]

    capsys.readouterr()
    assert gen.main(["--audio-dir", str(audio_dir)]) == 0


def test_no_wav_files_are_committed() -> None:
    wav_files = list(gen.FIXTURE_DIR.glob("*.wav"))
    assert wav_files == [], "generated audio must never be committed beside the generator"
