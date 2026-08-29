"""Audio decoding, format verification, peak checking, and resampling."""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any
import numpy as np

try:
    import soundfile as sf
except ImportError:
    sf = None

try:
    import librosa
except ImportError:
    librosa = None


MAX_AUDIO_BYTES = 500 * 1024 * 1024


def to_mono_float32(data: np.ndarray) -> np.ndarray:
    """Convert multi-channel or integer numpy audio buffer to 1D float32 mono."""
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    elif arr.ndim > 2:
        arr = arr.reshape(-1, arr.shape[-1]).mean(axis=1)
    return np.nan_to_num(arr)


def probe_audio_channels(path: str | Path) -> int:
    """Best-effort source channel count without decoding the complete file."""
    p = Path(path)
    if sf is not None:
        try:
            return max(1, int(sf.info(str(p)).channels))
        except Exception:
            pass
    try:
        with wave.open(str(p), "rb") as handle:
            return max(1, int(handle.getnchannels()))
    except Exception:
        pass
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            probe = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=channels",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(p),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if probe.returncode == 0 and probe.stdout.strip().isdigit():
                return max(1, int(probe.stdout.strip()))
        except (OSError, subprocess.SubprocessError):
            pass
    return 1


def load_analysis_audio(
    path: str | Path,
    target_sr: int = 44100,
    max_bytes: int = MAX_AUDIO_BYTES,
) -> tuple[np.ndarray, int, float, int, list[str]]:
    """Decode audio to mono float32 while preserving the source channel count.

    Returns ``(y, sr, duration, channels, warnings)``.  ``y`` is always mono,
    while ``channels`` describes the uploaded source before downmixing.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    file_size = p.stat().st_size
    if file_size > max_bytes:
        raise ValueError(f"Audio file exceeds size limit ({file_size} > {max_bytes} bytes)")
    if file_size == 0:
        return np.zeros(0, dtype=np.float32), target_sr, 0.0, 1, ["Audio file is empty"]

    warnings: list[str] = []
    data: np.ndarray | None = None
    rate: int = target_sr
    source_channels = probe_audio_channels(p)

    # Method 1: soundfile
    if sf is not None:
        try:
            raw_data, rate = sf.read(str(p), always_2d=False, dtype="float32")
            source_channels = int(raw_data.shape[1]) if raw_data.ndim == 2 else 1
            data = to_mono_float32(raw_data)
        except Exception:
            data = None

    # Method 2: wave PCM
    if data is None:
        try:
            with wave.open(str(p), "rb") as handle:
                rate = handle.getframerate()
                channels = handle.getnchannels()
                source_channels = channels
                width = handle.getsampwidth()
                raw_bytes = handle.readframes(handle.getnframes())
            if width == 2:
                raw_arr = np.frombuffer(raw_bytes, dtype="<i2").astype(np.float32) / 32768.0
            elif width == 1:
                raw_arr = (np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            elif width == 4:
                raw_arr = np.frombuffer(raw_bytes, dtype="<i4").astype(np.float32) / 2147483648.0
            else:
                raw_arr = None
            if raw_arr is not None:
                if channels > 1:
                    raw_arr = raw_arr.reshape(-1, channels).mean(axis=1)
                data = raw_arr
        except Exception:
            data = None

    # Method 3: ffmpeg subprocess fallback
    if data is None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("Cannot decode audio. For MP3/M4A/OGG without soundfile, please install FFmpeg and add it to PATH.")
        try:
            converted = subprocess.run(
                [
                    ffmpeg,
                    "-v", "error",
                    "-i", str(p),
                    "-f", "f32le",
                    "-ac", "1",
                    "-ar", str(target_sr),
                    "pipe:1",
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
            data = np.frombuffer(converted.stdout, dtype="<f4").astype(np.float32)
            rate = target_sr
        except subprocess.SubprocessError as exc:
            detail = exc.stderr.decode(errors="replace").strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
            raise ValueError(f"FFmpeg decoding failed: {detail}") from exc

    if data is None:
        raise ValueError(f"Unsupported audio format: {p.name}")

    # Check for clipping / peak > 1.0
    peak = float(np.max(np.abs(data))) if len(data) > 0 else 0.0
    if peak > 1.0:
        data = data / peak
        warnings.append(f"Audio peaked at {round(peak, 2)}; normalized to prevent distortion")

    # Resample if needed and librosa is available
    if rate != target_sr and len(data) > 0:
        if librosa is not None:
            data = librosa.resample(data, orig_sr=rate, target_sr=target_sr)
            rate = target_sr
        else:
            warnings.append(f"Audio sample rate is {rate} Hz (target {target_sr} Hz, librosa not installed for resampling)")

    duration = round(float(len(data) / rate), 4) if rate > 0 else 0.0
    return data.astype(np.float32), rate, duration, source_channels, warnings
