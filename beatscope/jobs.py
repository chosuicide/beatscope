"""In-memory asynchronous job manager: queue, state, progress, cancel, cache.

All DSP lives in beatscope.backends; every job runs through
``pipeline.analyze_track()`` so web uploads and the CLI share one pipeline.

A job is written by the worker thread and read by request threads, so its
fields are only touched through the locked methods on ``Job`` below.
"""
from __future__ import annotations

import datetime
import json
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .messages import msg
from .models import AnalysisConfig
from .pipeline import AnalysisCancelled, analyze_track
from .project import ProjectManager, compute_cache_key, content_hash

JobState = Literal["queued", "running", "complete", "failed", "cancelled"]
TERMINAL_STATES: frozenset[str] = frozenset({"complete", "failed", "cancelled"})

# Finished jobs stay queryable for a while, then the oldest are dropped: the
# dictionary used to grow for the lifetime of the process.
_MAX_TERMINAL_JOBS = 200


@dataclass
class Job:
    id: str
    state: JobState = "queued"
    stage: str = "init"
    progress: float = 0.0
    message: str = msg("job.queued")
    error: str | None = None
    project_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    cancel_event: threading.Event = field(default_factory=threading.Event)
    # The worker thread writes these fields while request threads read them.
    _fields_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def update(
        self,
        *,
        state: JobState | None = None,
        stage: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        error: str | None = None,
        project_id: str | None = None,
    ) -> bool:
        """Single write path for the state fields; returns False if refused.

        A job that reached a terminal state is frozen: a late progress callback
        cannot rewrite what happened, and a late stage callback cannot drag it
        back to running. Terminal may replace terminal - that is how a failure
        lands on a cancelled job - and ``mark_complete`` is the one deliberate
        way past the guard, for the cancel that arrives during the final write.
        """
        with self._fields_lock:
            if state is None:
                if self.state in TERMINAL_STATES:
                    return False
            else:
                if self.state in TERMINAL_STATES and state not in TERMINAL_STATES:
                    return False
                self.state = state
            if stage is not None:
                self.stage = stage
            if progress is not None:
                # Progress is a report, not a request: it never goes backwards.
                self.progress = max(self.progress, progress)
            if message is not None:
                self.message = message
            if error is not None:
                self.error = error
            if project_id is not None:
                self.project_id = project_id
            return True

    def mark_complete(self, *, message: str) -> None:
        """Record a finished analysis, even if a cancel arrived mid-write.

        The work is done and the cache is written, so relabelling the job
        "cancelled" would be the misleading answer: completion wins.
        """
        with self._fields_lock:
            self.state = "complete"
            self.stage = "complete"
            self.progress = 1.0
            self.message = message
            self.error = None

    def request_cancel(self) -> bool:
        """Accept a cancel, unless the job already reached a terminal state."""
        with self._fields_lock:
            if self.state in TERMINAL_STATES:
                return False
            self.cancel_event.set()
            self.state = "cancelled"
            self.message = msg("job.cancelled")
            return True

    def to_dict(self) -> dict[str, Any]:
        """Locked read: a poll never sees a half-updated job."""
        with self._fields_lock:
            return {
                "id": self.id,
                "state": self.state,
                "stage": self.stage,
                "progress": round(self.progress, 3),
                "message": self.message,
                "error": self.error,
                "project_id": self.project_id,
                "created_at": self.created_at,
            }


class JobManager:
    """Manages analysis jobs with a single worker to avoid GPU/CPU memory contention."""

    def __init__(self, project_manager: ProjectManager | None = None, max_workers: int = 1):
        self.project_manager = project_manager or ProjectManager()
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="BeatScopeJob")

    def create_job(self) -> Job:
        # uuid4 replaced a hash of timestamp + id(self) + len(jobs): that scheme
        # could collide for two jobs created in the same instant, and it mixed
        # the process's object ids into a value clients see.
        job = Job(id=uuid.uuid4().hex[:12])
        with self.lock:
            self.jobs[job.id] = job
        self._evict_old_jobs()
        return job

    def _evict_old_jobs(self) -> None:
        """Keep the newest terminal jobs; created_at is a UTC ISO string, so it sorts.

        Called from create_job rather than a background thread: one worker means
        one new job at a time, which is all the frequency this needs.
        """
        with self.lock:
            terminal = sorted(
                (job for job in self.jobs.values() if job.state in TERMINAL_STATES),
                key=lambda job: job.created_at,
            )
            for job in terminal[: len(terminal) - _MAX_TERMINAL_JOBS]:
                self.jobs.pop(job.id, None)

    def get_job(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if job is None:
            return False
        return job.request_cancel()

    def submit_analysis(
        self,
        temp_audio_path: Path,
        original_filename: str,
        config: dict[str, Any] | None = None,
    ) -> Job:
        job = self.create_job()
        cfg = config or {"subdivision": 16, "separation": "auto"}
        self.executor.submit(self._run_analysis, job, temp_audio_path, original_filename, cfg)
        # The single worker may already have picked this job up; only one that
        # is still waiting is told where it sits. The count includes this job,
        # so position 1 means it runs next.
        with self.lock:
            waiting = sum(1 for queued in self.jobs.values() if queued.state == "queued")
        if job.to_dict()["state"] == "queued":
            job.update(message=msg("job.queued-position", position=waiting))
        return job

    def _run_analysis(
        self,
        job: Job,
        temp_audio_path: Path,
        original_filename: str,
        config: dict[str, Any],
    ) -> None:
        try:
            if job.cancel_event.is_set():
                # Cancelled while queued: nothing has run, and the upload is
                # removed in the finally block below.
                job.update(state="cancelled", stage="cancelled", message=msg("job.cancelled"))
                return

            started = job.update(
                state="running", stage="decode", progress=0.05, message=msg("job.decoding")
            )
            if not started:
                # A cancel landed between the check above and this write, so the
                # job is already terminal and the pipeline never ran.
                return

            cfg = AnalysisConfig.from_dict(config)
            cfg.validate()
            sha256 = content_hash(temp_audio_path)
            cache_key = compute_cache_key(sha256, cfg.to_dict())
            job.update(project_id=sha256[:12])

            # Fast path: content-addressed disk cache
            cached_rhythm = self.project_manager.find_cached_rhythm(sha256, cache_key)
            if cached_rhythm is not None:
                job.mark_complete(message=msg("job.cache-hit"))
                return

            def update_progress(stage: str, value: float, message: str) -> None:
                job.update(stage=stage, progress=value, message=message)

            rhythm = analyze_track(
                temp_audio_path,
                cfg,
                display_name=original_filename,
                progress=update_progress,
                cancelled=job.cancel_event.is_set,
            )

            # Save project to disk cache and copy audio for playback
            job.update(stage="serialize", progress=0.98, message=msg("job.serializing"))
            p_dir = self.project_manager.save_project(
                rhythm["project_id"], temp_audio_path, rhythm, cfg.to_dict(), cache_key,
            )
            audio_dst = p_dir / "source.audio"
            if not audio_dst.is_file():
                shutil.copy2(temp_audio_path, audio_dst)

            p_json_file = p_dir / "project.json"
            if p_json_file.is_file():
                p_meta = json.loads(p_json_file.read_text(encoding="utf-8"))
                p_meta["audio_path"] = str(audio_dst.resolve())
                p_json_file.write_text(json.dumps(p_meta, indent=2, ensure_ascii=False), encoding="utf-8")

            job.mark_complete(message=msg("job.complete"))

        except AnalysisCancelled:
            job.update(state="cancelled", stage="cancelled", message=msg("job.cancelled"))
        except Exception as exc:
            job.update(state="failed", error=str(exc), message=msg("job.failed", error=exc))
        finally:
            # Delete upload temp file
            temp_audio_path.unlink(missing_ok=True)
