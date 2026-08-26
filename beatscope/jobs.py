"""In-memory asynchronous job manager for audio analysis and stage progress."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import threading
from typing import Any, Literal
from concurrent.futures import ThreadPoolExecutor

from .audio_io import load_analysis_audio
from .beatgrid import BeatGridAnalyzer
from .features import compute_multiband_novelty, extract_onsets
from .structure import analyze_song_structure
from .schema import SCHEMA_VERSION, ANALYZER_VERSION, validate_rhythm_v3
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
            
            # Stage 1: Decode & SHA256 (0 - 10%)
            job.stage = "decode"
            job.progress = 0.05
            job.message = "正在读取音频并计算哈希..."
            
            if job.cancel_event.is_set():
                job.state = "cancelled"
                return

            sha256 = content_hash(temp_audio_path)
            cache_key = compute_cache_key(sha256, config)
            job.project_id = cache_key[:12]

            # Fast path: Check disk cache
            cached_rhythm = self.project_manager.find_cached_rhythm(cache_key)
            if cached_rhythm is not None:
                job.progress = 1.0
                job.stage = "complete"
                job.state = "complete"
                job.message = "命中文档缓存，直接加载"
                return

            y, sr, duration, audio_warnings = load_analysis_audio(temp_audio_path, target_sr=44100)
            job.progress = 0.10

            if job.cancel_event.is_set():
                job.state = "cancelled"
                return

            # Stage 2: Separate / Stem preparation (10 - 55%)
            # If no demucs or separation=off, fast forward to 55%
            job.stage = "separate"
            job.progress = 0.30
            job.message = "检查鼓组音轨..."
            # Currently fallback/auto without external stem passes audio directly as drums
            analysis_audio = y
            separation_used = False
            job.progress = 0.55

            if job.cancel_event.is_set():
                job.state = "cancelled"
                return

            # Stage 3: Beatgrid analysis (55 - 70%)
            job.stage = "beatgrid"
            job.progress = 0.60
            job.message = "计算拍点与网格..."
            subdivision = int(config.get("subdivision", 16))

            # Beat estimation fallback when no external beat_this file provided
            # Using onset envelopes for robust tempo & beat grid
            hop = 256
            times, novelty = compute_multiband_novelty(analysis_audio, sr=sr, hop=hop)
            
            # Estimate BPM from novelty if beat_this is not provided
            from .analysis import _estimate_bpm
            bpm = _estimate_bpm(novelty["all"], sr, hop)
            if bpm <= 0:
                bpm = 120.0
            
            beat_step = 60.0 / bpm
            downbeat_time = 0.0
            
            # Find first significant peak for origin
            from .features import detect_transient_peaks
            peaks = detect_transient_peaks(novelty["all"], min_distance_samples=int(0.12 * sr / hop), threshold=0.15)
            if len(peaks) > 0:
                downbeat_time = float(times[peaks[0]])

            beats: list[dict[str, Any]] = []
            cur_time = downbeat_time
            cur_beat = 1
            cur_bar = 1
            while cur_time <= duration + beat_step:
                beats.append({
                    "time": round(cur_time, 4),
                    "beat": cur_beat,
                    "bar": cur_bar,
                    "downbeat": bool(cur_beat == 1),
                    "sequence_gap": False,
                })
                cur_time += beat_step
                cur_beat = (cur_beat % 4) + 1
                if cur_beat == 1:
                    cur_bar += 1

            bars = max(1, cur_bar - 1)
            job.progress = 0.70

            if job.cancel_event.is_set():
                job.state = "cancelled"
                return

            # Stage 4: Features & Transients (70 - 88%)
            job.stage = "features"
            job.progress = 0.75
            job.message = "提取多频段瞬态能量..."
            onsets = extract_onsets(times, novelty, sr=sr, hop=hop, bpm=bpm)
            job.progress = 0.88

            if job.cancel_event.is_set():
                job.state = "cancelled"
                return

            # Stage 5: Song Structure (88 - 96%)
            job.stage = "structure"
            job.progress = 0.90
            job.message = "比对小节相似度与结构..."
            overview = analyze_song_structure(onsets, beats, bars, subdivision=subdivision)
            job.progress = 0.96

            if job.cancel_event.is_set():
                job.state = "cancelled"
                return

            # Stage 6: Serialization & Save Project (96 - 100%)
            job.stage = "serialize"
            job.progress = 0.98
            job.message = "生成并缓存项目数据..."

            dt = hop / sr
            fps = int(round(1.0 / dt)) if dt > 0 else 100
            energy_data = {
                "fps": fps,
                "start": 0.0,
                "bands": {
                    "all": [round(float(v), 4) for v in novelty["all"]],
                    "low": [round(float(v), 4) for v in novelty["low"]],
                    "mid": [round(float(v), 4) for v in novelty["mid"]],
                    "high": [round(float(v), 4) for v in novelty["high"]],
                },
            }

            rhythm_result = {
                "schema_version": SCHEMA_VERSION,
                "project_id": job.project_id,
                "source": {
                    "display_name": original_filename,
                    "duration": round(duration, 4),
                    "sample_rate": sr,
                    "channels": 2,
                    "sha256": sha256,
                },
                "analysis": {
                    "pipeline": "multiband-novelty+spectral-flux",
                    "analyzer_version": ANALYZER_VERSION,
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "warnings": list(audio_warnings),
                    "separation_used": separation_used,
                },
                "tempo": {
                    "global_bpm": round(bpm, 3),
                    "confidence": 0.85,
                    "variable_tempo": False,
                },
                "grid": {
                    "time_signature": [4, 4],
                    "origin": round(downbeat_time, 4),
                    "default_subdivision": subdivision,
                    "bars": bars,
                },
                "beats": beats,
                "onsets": onsets,
                "energy": energy_data,
                "overview": overview,
                "exports": {},
            }

            # Save project to disk cache and copy audio for playback
            p_dir = self.project_manager.save_project(job.project_id, temp_audio_path, rhythm_result, config, cache_key)
            audio_dst = p_dir / "source.audio"
            if not audio_dst.is_file():
                import shutil
                shutil.copy2(temp_audio_path, audio_dst)

            # Update project.json audio_path
            import json
            p_json_file = p_dir / "project.json"
            if p_json_file.is_file():
                p_meta = json.loads(p_json_file.read_text(encoding="utf-8"))
                p_meta["audio_path"] = str(audio_dst.resolve())
                p_json_file.write_text(json.dumps(p_meta, indent=2, ensure_ascii=False), encoding="utf-8")

            job.progress = 1.0
            job.stage = "complete"
            job.state = "complete"
            job.message = "分析完成"

        except Exception as exc:
            job.state = "failed"
            job.error = str(exc)
            job.message = f"分析失败: {exc}"
        finally:
            # Delete upload temp file
            temp_audio_path.unlink(missing_ok=True)
