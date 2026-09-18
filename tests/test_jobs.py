"""JobManager concurrency and lifecycle contracts.

The manager is written by its worker thread and read by request threads, so
these tests pin the two things that used to be decided by timing: what a cancel
racing the final write means, and how long finished jobs stay in memory.
"""
import threading
from pathlib import Path

import pytest

from beatscope import jobs as jobs_module
from beatscope.jobs import JobManager
from beatscope.messages import msg
from beatscope.pipeline import AnalysisCancelled
from beatscope.project import ProjectManager

CONFIG = {"subdivision": 16, "separation": "auto"}


@pytest.fixture()
def manager(tmp_path) -> JobManager:
    jobs = JobManager(ProjectManager(cache_root=tmp_path / "cache"))
    yield jobs
    jobs.executor.shutdown(wait=True)


@pytest.fixture()
def upload(tmp_path) -> Path:
    """The upload file the worker deletes when it is done with it."""
    path = tmp_path / "clip.wav"
    path.write_bytes(b"RIFF")
    return path


def _stub_cache(monkeypatch, manager: JobManager) -> None:
    """Keep the pipeline fake out of the schema: it writes no project."""
    monkeypatch.setattr(jobs_module, "content_hash", lambda path: "a" * 64)

    def save_project(project_id, audio_path, rhythm, config, cache_key):
        target = manager.project_manager.cache_root / project_id
        target.mkdir(parents=True, exist_ok=True)
        return target

    manager.project_manager.save_project = save_project


def _drain(manager: JobManager) -> None:
    """Wait for the worker to finish, not merely for a terminal state.

    A cancel makes the job terminal while the worker is still inside the
    pipeline, so polling for a terminal state can read the job mid-flight.
    """
    manager.executor.shutdown(wait=True)


def _only_job(manager: JobManager):
    (job,) = manager.jobs.values()
    return job


def test_cancel_racing_the_final_write_still_reports_complete(manager, upload, monkeypatch):
    """Completion wins: the analysis finished, so the job is not relabelled.

    The cancel lands after the pipeline's last cancellation check, while the
    result is on its way to the cache - the window where a cancel request and a
    finished analysis used to overwrite each other.
    """
    _stub_cache(monkeypatch, manager)
    calls: list[str] = []

    def analyze_track(path, config, *, display_name, progress, cancelled):
        calls.append(f"enter cancelled={cancelled()}")
        accepted = manager.cancel_job(_only_job(manager).id)
        calls.append(f"cancel accepted={accepted}")
        progress("serialize", 0.5, "progress after the cancel")
        calls.append("returning")
        return {"project_id": "0" * 12, "source": {"sha256": "a" * 64}}

    monkeypatch.setattr(jobs_module, "analyze_track", analyze_track)

    job = manager.submit_analysis(upload, "clip.wav", CONFIG)
    _drain(manager)
    snapshot = job.to_dict()
    detail = (
        f"stage={snapshot['stage']} progress={snapshot['progress']} "
        f"message={snapshot['message']!r} error={snapshot['error']!r} calls={calls}"
    )
    assert snapshot["state"] == "complete", detail
    assert snapshot["error"] is None
    # The cancel was accepted while the job was live, so it is now final and a
    # second cancel is refused rather than rewriting the outcome.
    assert manager.cancel_job(job.id) is False
    assert job.to_dict()["state"] == "complete"


def test_cancel_the_pipeline_honours_stays_cancelled(manager, upload, monkeypatch):
    """The other half of the contract: a cancel the pipeline obeys is final."""
    _stub_cache(monkeypatch, manager)

    def analyze_track(path, config, *, display_name, progress, cancelled):
        assert manager.cancel_job(_only_job(manager).id) is True
        raise AnalysisCancelled("cancelled mid-analysis")

    monkeypatch.setattr(jobs_module, "analyze_track", analyze_track)

    job = manager.submit_analysis(upload, "clip.wav", CONFIG)
    _drain(manager)
    assert job.to_dict()["state"] == "cancelled"
    assert job.to_dict()["message"] == msg("job.cancelled")
    assert manager.cancel_job(job.id) is False


def test_a_finished_job_is_frozen_and_progress_never_goes_backwards(manager):
    job = manager.create_job()
    assert job.update(stage="decode", progress=0.9, message=msg("job.decoding")) is True
    # A report is not a request: a smaller number is ignored, not applied.
    assert job.update(progress=0.2) is True
    assert job.to_dict()["progress"] == 0.9

    job.mark_complete(message=msg("job.complete"))
    assert job.update(stage="serialize", progress=0.5, message=msg("job.serializing")) is False
    assert job.update(state="running") is False
    snapshot = job.to_dict()
    assert snapshot["state"] == "complete"
    assert snapshot["stage"] == "complete"
    assert snapshot["progress"] == 1.0
    assert snapshot["message"] == msg("job.complete")


def test_terminal_jobs_are_evicted_and_live_ones_are_kept(manager):
    for _ in range(250):
        manager.create_job().mark_complete(message=msg("job.complete"))

    live = manager.create_job()

    assert len(manager.jobs) <= 201, "200 terminal jobs plus the live one"
    assert live.id in manager.jobs
    assert live.state == "queued"


def test_job_ids_are_unique_and_a_waiting_job_reports_its_place(manager, upload, monkeypatch):
    """A single worker means the queue is real: say where a waiting job sits."""
    _stub_cache(monkeypatch, manager)
    started = threading.Event()
    release = threading.Event()

    def analyze_track(path, config, *, display_name, progress, cancelled):
        started.set()
        release.wait(timeout=30)
        raise AnalysisCancelled("done for the test")

    monkeypatch.setattr(jobs_module, "analyze_track", analyze_track)

    first = manager.submit_analysis(upload, "first.wav", CONFIG)
    assert started.wait(timeout=30), "the worker never started the first job"
    second = manager.submit_analysis(upload, "second.wav", CONFIG)
    third = manager.submit_analysis(upload, "third.wav", CONFIG)

    assert len({first.id, second.id, third.id}) == 3
    assert all(len(job.id) == 12 and job.id.isalnum() for job in (first, second, third))
    # The count includes the waiting job itself, so "第 1 位" runs next.
    assert second.to_dict()["message"] == msg("job.queued-position", position=1)
    assert third.to_dict()["message"] == msg("job.queued-position", position=2)

    release.set()
    _drain(manager)
    for job in (first, second, third):
        assert job.to_dict()["state"] == "cancelled"
