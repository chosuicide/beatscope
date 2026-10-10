"""Local-only movie jobs. Analysis/export contracts are intentionally unchanged."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .assets import AssetStore
from .composition_store import composition_lock
from .custom_media import extract_video_frames, load_media, media_bytes
from .edit_plan import edit_plan_bytes, load_edit_plan
from .material_templates import MaterialTemplates, material_version, paint_version, validate_template
from .messages import msg
from .movie_output import movie_output
from .project import _atomic_write_bytes
from .response_relevance import build_response_relevance

WEB = Path(__file__).parent / "web"
RUNTIME = Path(__file__).parent / "runtime"


def _link_or_copy(source, target):
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)
    return target


def renderer_tools() -> dict:
    portable_root = Path(sys.executable).resolve().parent / "tools" if getattr(sys, "frozen", False) else None
    repo_root = Path(__file__).parent.parent
    module = os.environ.get("BEATSCOPE_PLAYWRIGHT_MODULE", "")
    if not module:
        # A frozen build carries its own tools; a checkout declares Playwright
        # in tests/browser/package.json, next to the browser tests that drive
        # the studio, and may also have it under web-src. Look where it is
        # actually declared before giving up.
        candidates = []
        if portable_root:
            candidates.append(portable_root / "node_modules" / "playwright" / "index.mjs")
        candidates += [
            repo_root / "tests/browser/node_modules/playwright/index.mjs",
            repo_root / "web-src/node_modules/playwright/index.mjs",
        ]
        module = next((str(candidate) for candidate in candidates if candidate.is_file()), "")
    node = shutil.which("node")
    if not node and portable_root and (portable_root / "node.exe").is_file():
        node = str(portable_root / "node.exe")
    ffmpeg = shutil.which(os.environ.get("BEATSCOPE_FFMPEG", "ffmpeg"))
    if not ffmpeg and portable_root and (portable_root / "ffmpeg.exe").is_file():
        ffmpeg = str(portable_root / "ffmpeg.exe")
    available = bool(node and ffmpeg and module and Path(module).is_file())
    return {"available": available, "node": node, "ffmpeg": ffmpeg, "module": module,
            "message": "" if available else msg("movie.renderer-unavailable")}


class MovieJobs:
    def __init__(self, projects):
        self.projects = projects
        self.root = projects.cache_root / "movies"
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.active = None
        self.jobs = {}
        self.materials = MaterialTemplates(projects)

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
                job.update(state="failed", message=msg("movie.restarted"))
                self._save(job)
            return job

    def submit(self, project_id, seed=None, template='voxel', output=None):
        output = movie_output(output)
        validate_template(template)
        template_digest = paint_version() if template == 'paint' else material_version() if template != 'voxel' else 'voxel-phrase-2'
        if seed is not None and (type(seed) is not int or not 0 <= seed < 2**24):
            raise ValueError("seed must be an integer from 0 to 16777215")
        if not re.fullmatch(r"[0-9a-f]{12}", project_id):
            raise ValueError(msg("movie.invalid-project"))
        tools = renderer_tools()
        if not tools["available"]:
            raise ValueError(tools["message"])
        rhythm = self.projects.get_project_rhythm(project_id)
        if rhythm is None:
            raise ValueError(msg("movie.missing-analysis"))
        duration = rhythm.get("source", {}).get("duration", 0)
        if not isinstance(duration, (int, float)) or not 0 < duration <= 600:
            raise ValueError(msg("movie.too-long"))
        audio = self.projects.get_project_audio_path(project_id)
        if not audio or not audio.is_file():
            raise ValueError(msg("movie.missing-audio"))
        with composition_lock():
            edit_plan = load_edit_plan(self.projects, project_id, rhythm)
            media = load_media(self.projects, project_id)
            if template == 'voxel':
                media = dict(media, assets=[], slots=[])
        edit_digest = hashlib.sha256(edit_plan_bytes(edit_plan)).hexdigest()
        media_digest = hashlib.sha256(media_bytes(media)).hexdigest()
        with self.lock:
            if self.active:
                active = self.jobs[self.active]
                if active["project_id"] == project_id and (seed is None or active["seed"] == seed) and active.get("edit_plan_digest") == edit_digest and active.get('template', 'voxel') == template and active.get('template_digest', 'voxel-phrase-2') == template_digest and active.get('output') == output and active.get('media_digest') == media_digest:
                    return dict(active)
                raise RuntimeError(msg("movie.busy"))
            job_id = secrets.token_hex(12)
            directory = self.root / job_id
            directory.mkdir()
            job = {"id": job_id, "project_id": project_id, "seed": secrets.randbits(24) if seed is None else seed,
                   "edit_plan_digest": edit_digest,
                   "template": template, "template_digest": template_digest,
                   "output": output,
                   "media_digest": media_digest,
                   "template_version": 'pastel-bloom-2' if template == 'paint' else 'prismatic-echo-5' if template == 'material-mix' else 'prismatic-echo-ii-1' if template == 'material-mix-2' else 'voxel-phrase-2',
                   "state": "queued", "progress": 0, "message": msg("movie.preparing"), "duration": duration}
            self._save(job)
            (directory / 'custom-media.json').write_bytes(media_bytes(media))
            store = AssetStore(self.projects.get_project_dir(project_id), project_id)
            media_files = {}
            if media['assets']:
                (directory / 'custom').mkdir()
            for asset in media['assets']:
                source = store.path_for(asset['id'])
                if source is None:
                    raise ValueError('media/asset-missing')
                media_files[asset['id']] = source.suffix[1:]
                _link_or_copy(source, directory / 'custom' / source.name)
            (directory / 'media-files.json').write_text(json.dumps(media_files), encoding='utf-8')
            self.jobs[job_id] = job
            self.active = job_id
            threading.Thread(target=self._run, args=(job_id, rhythm, audio, tools, edit_plan), daemon=True).start()
            return dict(job)

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["state"] not in ("queued", "running"):
                return False
            (self.root / job_id / "cancel").touch()
            job["message"] = msg("movie.stopping")
            self._save(job)
            return True

    def _run(self, job_id, rhythm, audio, tools, edit_plan=None):
        directory = self.root / job_id
        job = self.jobs[job_id]
        process = None
        try:
            for name in ("mv-render.html", "mv-frame.mjs", "mv-visual.js", "mv-plan.mjs", "mv-encode.mjs", 'movie-factory.mjs', 'movie-templates.mjs', 'material-frame.mjs', 'material-gpu.mjs', 'custom-media.mjs', 'media-color.mjs', 'paint-frame.mjs', 'paint-sources.mjs'):
                shutil.copyfile(WEB / name, directory / name)
            shutil.copyfile(RUNTIME / "runtime.js", directory / "beatscope-runtime.js")
            shutil.copyfile(RUNTIME / "edit-plan.js", directory / "edit-plan.js")
            (directory / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            ranking = build_response_relevance(rhythm)
            # Video slots render from pre-extracted frames, never the codec:
            # the headless browser only ever sees deterministic JPEGs.
            media = json.loads((directory / 'custom-media.json').read_bytes())
            media_files = json.loads((directory / 'media-files.json').read_bytes())
            by_id = {a['id']: a for a in media['assets']}
            media_frames = {}
            video_slots = [(i, s) for i, s in enumerate(media['slots']) if by_id.get(s['asset'], {}).get('kind') == 'video']
            if video_slots:
                with self.lock:
                    job["message"] = msg("movie.preparing-video")
                    self._save(job)
                for index, slot in video_slots:
                    if (directory / "cancel").exists():
                        raise ValueError("cancelled")
                    source = directory / 'custom' / f"{slot['asset']}.{media_files[slot['asset']]}"
                    media_frames[str(index)] = extract_video_frames(
                        tools["ffmpeg"], source, slot.get('offset', 0),
                        slot['end'] - slot['start'], directory / 'custom' / 'v' / str(index),
                        resolution=min(job['output']['width'], job['output']['height']),
                        cancelled=lambda: (directory / 'cancel').exists())
            (directory / "input.json").write_text(json.dumps({"rhythm": rhythm, "ranking": ranking,
                "audio": str(audio.resolve()), "seed": job["seed"], "editPlan": edit_plan, 'template': job.get('template', 'voxel'), 'output': job['output'], 'media':media, 'mediaFiles':media_files, 'mediaFrames':media_frames}), encoding="utf-8")
            if job.get('template') == 'paint':
                shutil.copytree(WEB / 'paint-assets', directory / 'paint-assets', copy_function=_link_or_copy)
            if job.get('template', 'voxel').startswith('material-'):
                while True:
                    if (directory / 'cancel').exists():
                        raise ValueError('cancelled')
                    state = self.materials.prepare(job['project_id'], job['seed'], job['template'], tools, rhythm, edit_plan)
                    if state['state'] == 'failed':
                        raise ValueError(state['message'])
                    if state['state'] == 'ready':
                        break
                    time.sleep(.5)
                prepared = self.materials.root / state['key']
                for name in ('score.json', 'plan.json', 'material-timeline.json', 'material-library.json'):
                    shutil.copyfile(prepared / name, directory / name)
                shutil.copytree(prepared / 'media', directory / 'media', copy_function=_link_or_copy)
            if (directory / "cancel").exists():
                raise ValueError("cancelled")
            env = dict(os.environ, BEATSCOPE_PLAYWRIGHT_MODULE=tools["module"], BEATSCOPE_FFMPEG=tools["ffmpeg"],
                       BEATSCOPE_RENDER_PARENT_PID=str(os.getpid()))
            with self.lock:
                job.update(state="running", message=msg("movie.rendering"))
                self._save(job)
            with (directory / "render.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen([tools["node"], str(WEB / "mv-worker.mjs"), str(directory)],
                    stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8", env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                assert process.stdout is not None  # stdout=PIPE above
                for line in process.stdout:
                    try:
                        update = json.loads(line)
                    except ValueError:
                        continue
                    with self.lock:
                        job["progress"] = max(0, min(1, float(update.get("progress", 0))))
                        if isinstance(update.get("acceleration"), dict):
                            job["acceleration"] = update["acceleration"]
                        self._save(job)
                code = process.wait()
            if (directory / "cancel").exists():
                raise ValueError("cancelled")
            if code != 0 or not (directory / "movie.mp4").is_file():
                raise ValueError(msg("movie.render-incomplete"))
            with self.lock:
                job.update(state="complete", progress=1, message=msg("movie.complete"), video_url=f"/api/movies/{job_id}/video")
        except Exception as exc:
            with self.lock:
                cancelled = (directory / "cancel").exists()
                job.update(state="cancelled" if cancelled else "failed", message=msg("movie.cancelled") if cancelled else str(exc))
        finally:
            shutil.rmtree(directory / 'custom' / 'v', ignore_errors=True)
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
