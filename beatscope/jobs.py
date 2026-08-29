"""In-memory asynchronous job manager: queue, state, progress, cancel, cache.

All DSP lives in beatscope.backends; every job runs through
``pipeline.analyze_track()`` so web uploads and the CLI share one pipeline.
"""
from __future__ import annotations

import datetime
import json
import shutil
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import threading
from typing import Any, Literal
from concurrent.futures import ThreadPoolExecutor

from .models import AnalysisConfig
from .pipeline import AnalysisCancelled, analyze_track
from .project import ProjectManager, content_hash, compute_cache_key


JobState = Literal["queued", "running", "complete", "failed", "cancelled"]


@dataclass
class Job:
    id: str
    state: JobState = "queued"
    stage: str = "init"
    progress: float = 0.0
    message: str = "任务已排队"
    error: str | None = None
    project_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict[str, Any]:
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
        job_id = hashlib.sha256(f"{datetime.datetime.now().isoformat()}:{id(self)}:{len(self.jobs)}".encode()).hexdigest()[:12]
        job = Job(id=job_id)
        with self.lock:
            self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            if job.state in ("complete", "failed", "cancelled"):
                return False
            job.cancel_event.set()
            job.state = "cancelled"
            job.message = "分析已取消"
            return True

    def submit_analysis(
        self,
        temp_audio_path: Path,
        original_filename: str,
        config: dict[str, Any] | None = None,
    ) -> Job:
        job = self.create_job()
        cfg = config or {"subdivision": 16, "separation": "auto"}
        self.executor.submit(self._run_analysis, job, temp_audio_path, original_filename, cfg)
        return job

    def _run_analysis(
        self,
        job: Job,
        temp_audio_path: Path,
        original_filename: str,
        config: dict[str, Any],
    ) -> None:
        try:
            job.state = "running"
            job.stage = "decode"
            job.progress = 0.05
            job.message = "正在读取音频并计算哈希..."

            if job.cancel_event.is_set():
                job.state = "cancelled"
                job.message = "分析已取消"
                return

            cfg = AnalysisConfig.from_dict(config)
            cfg.validate()
            sha256 = content_hash(temp_audio_path)
            cache_key = compute_cache_key(sha256, cfg.to_dict())
            job.project_id = sha256[:12]

            # Fast path: content-addressed disk cache
            cached_rhythm = self.project_manager.find_cached_rhythm(sha256, cache_key)
            if cached_rhythm is not None:
                job.progress = 1.0
                job.stage = "complete"
                job.state = "complete"
                job.message = "命中文档缓存，直接加载"
                return

            def update_progress(stage: str, value: float, message: str) -> None:
                job.stage = stage
                job.progress = max(job.progress, value)
                job.message = message

            rhythm = analyze_track(
                temp_audio_path,
                cfg,
                display_name=original_filename,
                progress=update_progress,
                cancelled=job.cancel_event.is_set,
            )

            # Save project to disk cache and copy audio for playback
            job.stage = "serialize"
            job.progress = max(job.progress, 0.98)
            job.message = "生成并缓存项目数据..."
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

            job.progress = 1.0
            job.stage = "complete"
            job.state = "complete"
            job.message = "分析完成"

        except AnalysisCancelled:
            job.state = "cancelled"
            job.message = "分析已取消"
        except Exception as exc:
            job.state = "failed"
            job.error = str(exc)
            job.message = f"分析失败: {exc}"
        finally:
            # Delete upload temp file
            temp_audio_path.unlink(missing_ok=True)
