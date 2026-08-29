"""Shared fixtures: deterministic synthetic audio, Beat This files, web job runner."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from fixtures.generate_audio import beats_file_content, generate_all
from beatscope.jobs import JobManager
from beatscope.project import ProjectManager


@pytest.fixture(scope="session")
def synth_audio(tmp_path_factory):
    """All synthetic fixtures with ground truth, generated once per session."""
    return generate_all(tmp_path_factory.mktemp("beatscope-audio"))


@pytest.fixture(scope="session")
def fixed_120_audio(synth_audio):
    return synth_audio["fixed-120"]["audio"]


@pytest.fixture(scope="session")
def silence_audio(synth_audio):
    return synth_audio["silence"]["audio"]


@pytest.fixture(scope="session")
def beat_file(tmp_path_factory, synth_audio):
    """Beat This file for fixed-120 built from exact ground truth beats."""
    truth = synth_audio["fixed-120"]["truth"]
    path = tmp_path_factory.mktemp("beats") / "fixed-120.beats"
    path.write_text(beats_file_content(truth["beats"]), encoding="utf-8")
    return path


@pytest.fixture()
def run_web_analysis(tmp_path):
    """Run the current web upload path (JobManager) synchronously and return the rhythm JSON."""

    def _run(audio_path: str | Path, config: dict | None = None) -> dict:
        # The server uploads to a temp file that JobManager deletes afterwards,
        # so hand it a disposable copy and keep the fixture intact.
        upload = tmp_path / "upload" / Path(audio_path).name
        upload.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio_path, upload)
        manager = ProjectManager(cache_root=tmp_path / "cache")
        jobs = JobManager(manager)
        job = jobs.submit_analysis(
            upload,
            Path(audio_path).name,
            config or {"subdivision": 16, "separation": "auto"},
        )
        deadline = time.time() + 180
        while job.state in ("queued", "running") and time.time() < deadline:
            time.sleep(0.05)
        assert job.state == "complete", f"web analysis failed: {job.error}"
        rhythm = manager.get_project_rhythm(job.project_id)
        assert rhythm is not None, "completed job produced no rhythm.json"
        return rhythm

    return _run
