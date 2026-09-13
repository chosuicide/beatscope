"""Local-only movie jobs. Analysis/export contracts are intentionally unchanged."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading

from .project import _atomic_write_bytes
from .response_relevance import build_response_relevance

WEB = Path(__file__).parent / "web"
RUNTIME = Path(__file__).parent / "runtime"


def renderer_tools() -> dict:
    portable_root = Path(sys.executable).resolve().parent / "tools" if getattr(sys, "frozen", False) else None
    module = os.environ.get("BEATSCOPE_PLAYWRIGHT_MODULE", "")
    if not module:
        candidate = Path(__file__).parent.parent / "web-src/node_modules/playwright/index.mjs"
        if candidate.is_file():
            module = str(candidate)
        elif portable_root:
            candidate = portable_root / "node_modules" / "playwright" / "index.mjs"
            if candidate.is_file():
                module = str(candidate)
    node = shutil.which("node")
    if not node and portable_root and (portable_root / "node.exe").is_file():
        node = str(portable_root / "node.exe")
    ffmpeg = shutil.which(os.environ.get("BEATSCOPE_FFMPEG", "ffmpeg"))
    if not ffmpeg and portable_root and (portable_root / "ffmpeg.exe").is_file():
        ffmpeg = str(portable_root / "ffmpeg.exe")
    available = bool(node and ffmpeg and module and Path(module).is_file())
    return {"available": available, "node": node, "ffmpeg": ffmpeg, "module": module,
            "message": "" if available else "本地渲染器未配置：需要 Node、FFmpeg 和 Playwright。请按 docs/local-movie.md 配置。"}


class MovieJobs:
    def __init__(self, projects):
        self.projects = projects
        self.root = projects.cache_root / "movies"
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.active = None
        self.jobs = {}

    def _save(self, job):
        _atomic_write_bytes(self.root / job["id"] / "status.json", json.dumps(job, ensure_ascii=False).encode())

    def get(self, job_id):
        if not re.fullmatch(r"[0-9a-f]{24}", job_id):
            return None
        with self.lock:
            if job_id in self.jobs:
                return dict(self.jobs[job_id])
            target = self.root / job_id / "status.json"
            if not target.is_file():
                return None
            try:
                job = json.loads(target.read_bytes())
            except (ValueError, OSError):
                return None
            if (not isinstance(job, dict) or job.get("id") != job_id
                    or job.get("state") not in {"queued", "running", "failed", "cancelled", "complete"}):
                return None
            if job["state"] in ("queued", "running"):
                job.update(state="failed", message="服务已重启，请重新生成。")
                self._save(job)
            return job

    def submit(self, project_id, seed=None):
        if seed is not None and (type(seed) is not int or not 0 <= seed < 2**24):
            raise ValueError("seed must be an integer from 0 to 16777215")
        if not re.fullmatch(r"[0-9a-f]{12}", project_id):
            raise ValueError("无效的项目编号")
        tools = renderer_tools()
        if not tools["available"]:
            raise ValueError(tools["message"])
        rhythm = self.projects.get_project_rhythm(project_id)
        if rhythm is None:
            raise ValueError("歌曲分析不存在")
        duration = rhythm.get("source", {}).get("duration", 0)
        if not isinstance(duration, (int, float)) or not 0 < duration <= 600:
            raise ValueError("首版支持最长 10 分钟的歌曲。")
        audio = self.projects.get_project_audio_path(project_id)
        if not audio or not audio.is_file():
            raise ValueError("找不到原始音频，请重新上传。")
        with self.lock:
            if self.active:
                active = self.jobs[self.active]
                if active["project_id"] == project_id and (seed is None or active["seed"] == seed):
                    return dict(active)
                raise RuntimeError("另一个视频正在生成，请等待或先取消。")
            job_id = secrets.token_hex(12)
            directory = self.root / job_id
            directory.mkdir()
            job = {"id": job_id, "project_id": project_id, "seed": secrets.randbits(24) if seed is None else seed,
                   "state": "queued", "progress": 0, "message": "准备音乐数据", "duration": duration}
            self.jobs[job_id] = job
            self.active = job_id
            self._save(job)
            threading.Thread(target=self._run, args=(job_id, rhythm, audio, tools), daemon=True).start()
            return dict(job)

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["state"] not in ("queued", "running"):
                return False
            (self.root / job_id / "cancel").touch()
            job["message"] = "正在停止生成"
            self._save(job)
            return True

    def _run(self, job_id, rhythm, audio, tools):
        directory = self.root / job_id
        job = self.jobs[job_id]
        process = None
        try:
            for name in ("mv-render.html", "mv-frame.mjs", "mv-visual.js", "mv-plan.mjs", "mv-encode.mjs"):
                shutil.copyfile(WEB / name, directory / name)
            shutil.copyfile(RUNTIME / "runtime.js", directory / "beatscope-runtime.js")
            (directory / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            ranking = build_response_relevance(rhythm)
            (directory / "input.json").write_text(json.dumps({"rhythm": rhythm, "ranking": ranking,
                "audio": str(audio.resolve()), "seed": job["seed"]}), encoding="utf-8")
            if (directory / "cancel").exists():
                raise ValueError("cancelled")
            env = dict(os.environ, BEATSCOPE_PLAYWRIGHT_MODULE=tools["module"], BEATSCOPE_FFMPEG=tools["ffmpeg"],
                       BEATSCOPE_RENDER_PARENT_PID=str(os.getpid()))
            with self.lock:
                job.update(state="running", message="逐帧渲染视频")
                self._save(job)
            with (directory / "render.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen([tools["node"], str(WEB / "mv-worker.mjs"), str(directory)],
                    stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8", env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for line in process.stdout:
                    try:
                        update = json.loads(line)
                    except ValueError:
                        continue
                    with self.lock:
                        job["progress"] = max(0, min(1, float(update.get("progress", 0))))
                        self._save(job)
                code = process.wait()
            if (directory / "cancel").exists():
                raise ValueError("cancelled")
            if code != 0 or not (directory / "movie.mp4").is_file():
                raise ValueError("渲染未完成。请检查本地浏览器／FFmpeg；详情见缓存任务目录 render.log。")
            with self.lock:
                job.update(state="complete", progress=1, message="视频已生成", video_url=f"/api/movies/{job_id}/video")
        except Exception as exc:
            with self.lock:
                cancelled = (directory / "cancel").exists()
                job.update(state="cancelled" if cancelled else "failed", message="生成已取消" if cancelled else str(exc))
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            with self.lock:
                self.active = None
                self._save(job)

    def video(self, job_id):
        job = self.get(job_id)
        if not job or job["state"] != "complete":
            return None
        target = self.root / job_id / "movie.mp4"
        return target if target.is_file() else None
