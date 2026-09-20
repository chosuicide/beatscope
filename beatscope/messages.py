"""All user-visible progress and status strings, in one place.

The studio ships English first with Chinese behind its language switch; the
server-side strings are English by default for the same reason, and the Chinese
column is kept beside them so a language switch has something to switch to.

Nothing here is a log line: these strings reach the UI as job progress, job
status, or the reason a request failed, which is why they live in a table
instead of at the call sites.
"""
from __future__ import annotations

_TEXT: dict[str, dict[str, str]] = {
    # --- analysis job lifecycle (jobs.py) ----------------------------------
    "job.queued": {"en": "Job queued", "zh": "任务已排队"},
    "job.queued-position": {"en": "Queued (position {position})", "zh": "已排队（第 {position} 位）"},
    "job.decoding": {"en": "Reading audio and hashing…", "zh": "正在读取音频并计算哈希..."},
    "job.cache-hit": {"en": "Loaded from cache", "zh": "命中文档缓存，直接加载"},
    "job.serializing": {"en": "Building and caching project data…", "zh": "生成并缓存项目数据..."},
    "job.complete": {"en": "Analysis complete", "zh": "分析完成"},
    "job.cancelled": {"en": "Analysis cancelled", "zh": "分析已取消"},
    "job.failed": {"en": "Analysis failed: {error}", "zh": "分析失败: {error}"},
    # --- pipeline and backend progress stages ------------------------------
    "stage.decode": {"en": "Reading audio…", "zh": "读取音频..."},
    "stage.beatgrid": {"en": "Tracking local tempo and beats…", "zh": "追踪局部速度与拍点..."},
    "stage.features": {"en": "Extracting multi-band transient energy…", "zh": "提取多频段瞬态能量..."},
    "stage.separate": {"en": "Running Demucs separation…", "zh": "运行 Demucs 分离..."},
    "stage.model": {"en": "Running the beat model frame by frame…", "zh": "逐帧运行拍点模型..."},
    "stage.drum-decode": {"en": "Reading the drum stem…", "zh": "读取鼓组音轨..."},
    "stage.drum-beatgrid": {"en": "Parsing Beat This beats…", "zh": "解析 Beat This 拍点..."},
    "stage.structure-aggregate": {"en": "Aggregating bar features…", "zh": "聚合小节特征..."},
    "stage.structure-boundaries": {"en": "Finding section boundaries and repeats…", "zh": "计算段落边界与重复关系..."},
    "stage.validate": {"en": "Validating the rhythm IR…", "zh": "校验 Rhythm IR..."},
    "stage.serialize": {"en": "Building project data…", "zh": "生成项目数据..."},
    # --- movie jobs (mv_jobs.py) ------------------------------------------
    "movie.renderer-unavailable": {
        "en": "The local renderer is not configured: it needs Node, FFmpeg and Playwright. See docs/local-movie.md.",
        "zh": "本地渲染器未配置：需要 Node、FFmpeg 和 Playwright。请按 docs/local-movie.md 配置。",
    },
    "movie.restarted": {"en": "The service restarted; generate the video again.", "zh": "服务已重启，请重新生成。"},
    "movie.invalid-project": {"en": "Invalid project id.", "zh": "无效的项目编号"},
    "movie.missing-analysis": {"en": "No song analysis for this project.", "zh": "歌曲分析不存在"},
    "movie.too-long": {"en": "This version supports songs up to 10 minutes.", "zh": "首版支持最长 10 分钟的歌曲。"},
    "movie.missing-audio": {"en": "The original audio is gone; upload the song again.", "zh": "找不到原始音频，请重新上传。"},
    "movie.busy": {"en": "Another video is being generated; wait or cancel it first.", "zh": "另一个视频正在生成，请等待或先取消。"},
    "movie.preparing": {"en": "Preparing the music data", "zh": "准备音乐数据"},
    "movie.stopping": {"en": "Stopping the render", "zh": "正在停止生成"},
    "movie.rendering": {"en": "Rendering frames", "zh": "逐帧渲染视频"},
    "movie.complete": {"en": "Video ready", "zh": "视频已生成"},
    "movie.cancelled": {"en": "Generation cancelled", "zh": "生成已取消"},
    "movie.render-incomplete": {
        "en": "The render did not finish. Check the local browser and FFmpeg; render.log in the job directory has the details.",
        "zh": "渲染未完成。请检查本地浏览器／FFmpeg；详情见缓存任务目录 render.log。",
    },
    # --- failures a user can hit ------------------------------------------
    "error.unreadable-audio": {
        "en": "This audio could not be read; MP3 and other non-WAV formats need FFmpeg on PATH.",
        "zh": "无法读取此音频；MP3/非 WAV 格式需要安装 FFmpeg 并确保 ffmpeg 在 PATH 中",
    },
    "error.ffmpeg-decode": {"en": "FFmpeg could not decode the audio: {detail}", "zh": "FFmpeg 无法解码音频: {detail}"},
    "error.librosa-missing": {
        "en": "The high-quality stem pipeline needs librosa; install the optional dependency.",
        "zh": "高质量 stem pipeline 需要 librosa；请安装可选依赖",
    },
    "error.cuda-unavailable": {
        "en": "CUDA is not available; the GPU pipeline does not silently fall back to CPU.",
        "zh": "CUDA 不可用；GPU pipeline 不会偷偷回退 CPU",
    },
    "error.cuda-torch-missing": {
        "en": "Running GPU Demucs needs a CUDA build of Torch.",
        "zh": "需要安装 CUDA Torch 才能运行 GPU Demucs",
    },
    "error.demucs-failed": {
        "en": "Demucs separation failed ({code}); see {log}: {detail}",
        "zh": "Demucs 分离失败（{code}），详见 {log}: {detail}",
    },
}

LANGUAGES = ("en", "zh")

# English first, matching the studio's default. Wiring this to a request header
# or an environment variable is a separate change: it needs a decision about
# where the preference lives, not just a lookup.
_LANG = "en"


def msg(key: str, **fields: object) -> str:
    """The string for ``key`` in the current language, with any fields filled in."""
    template = _TEXT[key][_LANG]
    return template.format(**fields) if fields else template
