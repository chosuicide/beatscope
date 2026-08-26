"""Lightweight audio analysis with no model download requirement."""
from __future__ import annotations
import json
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

def _load_audio(path: str | Path) -> tuple[np.ndarray, int]:
    filename = Path(path)
    if sf is not None:
        try:
            data, rate = sf.read(str(filename), always_2d=False, dtype="float32")
            data = np.asarray(data, dtype=np.float32)
            if data.ndim == 2: data = data.mean(axis=1)
            return np.nan_to_num(data), int(rate)
        except Exception:
            pass
    try:
        with wave.open(str(filename), "rb") as handle:
            rate, channels, width = handle.getframerate(), handle.getnchannels(), handle.getsampwidth()
            raw = handle.readframes(handle.getnframes())
    except (wave.Error, EOFError, OSError) as wave_error:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("无法读取此音频；MP3/非 WAV 格式需要安装 FFmpeg 并确保 ffmpeg 在 PATH 中") from wave_error
        try:
            converted = subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(filename), "-f", "f32le", "-ac", "1", "-ar", "44100", "pipe:1"],
                check=True, capture_output=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            detail = exc.stderr.decode(errors="replace").strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
            raise ValueError(f"FFmpeg 无法解码音频: {detail}") from exc
        return np.frombuffer(converted.stdout, dtype="<f4").astype(np.float32), 44100
    if width == 2: data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 1: data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    elif width == 4: data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else: raise ValueError(f"Unsupported PCM width: {width} bytes")
    if channels > 1: data = data.reshape(-1, channels).mean(axis=1)
    return data, int(rate)

def _frame_features(audio: np.ndarray, rate: int, hop: int, frame: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if len(audio) == 0: return np.zeros(0), np.zeros(0), np.zeros((0, 4))
    count = max(1, 1 + max(0, len(audio) - 1) // hop)
    padded = np.pad(audio, (0, max(0, (count - 1) * hop + frame - len(audio))))
    window = np.hanning(frame).astype(np.float32)
    mag = np.asarray([np.abs(np.fft.rfft(padded[i * hop:i * hop + frame] * window)) for i in range(count)], dtype=np.float32)
    flux = np.maximum(0, np.diff(mag, axis=0, prepend=mag[:1])).sum(axis=1)
    flux = (flux - np.median(flux)) / (np.std(flux) + 1e-8)
    freqs = np.fft.rfftfreq(frame, 1 / rate)
    energies = np.zeros((count, 4), dtype=np.float32)
    for idx, (low, high) in enumerate(((20, 120), (120, 250), (250, 5000), (5000, 12000))):
        mask = (freqs >= low) & (freqs < min(high, rate / 2))
        if mask.any(): energies[:, idx] = np.sqrt(np.mean(mag[:, mask] ** 2, axis=1))
    # Keep band magnitudes comparable: per-band normalization would make tiny
    # spectral leakage in a pure bass tone look like a full snare hit.
    energies /= max(float(energies.max()), 1e-8)
    return np.arange(count, dtype=np.float32) * hop / rate, flux, energies

def _peak_indices(values: np.ndarray, threshold: float = 0.0, distance: int = 1) -> np.ndarray:
    if values.size < 3: return np.array([], dtype=int)
    candidates = np.where((values[1:-1] > values[:-2]) & (values[1:-1] >= values[2:]) & (values[1:-1] >= threshold))[0] + 1
    if len(candidates) <= 1 or distance <= 1: return candidates
    chosen: list[int] = []
    for index in candidates[np.argsort(values[candidates])[::-1]]:
        if all(abs(index - other) >= distance for other in chosen): chosen.append(int(index))
    return np.array(sorted(chosen), dtype=int)

def _estimate_bpm(flux: np.ndarray, rate: int, hop: int) -> float:
    if len(flux) < 4 or not np.any(flux > 0): return 0.0
    onset_threshold = max(0.6, float(np.percentile(flux, 78)))
    onset_peaks = _peak_indices(flux, onset_threshold, max(1, int(0.12 * rate / hop)))
    if len(onset_peaks) < 3: return 0.0
    intervals = np.diff(onset_peaks).astype(float)
    median_interval = float(np.median(intervals))
    if median_interval <= 0 or float(np.median(np.abs(intervals - median_interval))) / median_interval > 0.3: return 0.0
    centered = flux - np.mean(flux); corr = np.correlate(centered, centered, mode="full")[len(centered) - 1:]
    lo = max(1, int(60 * rate / (180 * hop))); hi = min(len(corr) - 1, int(60 * rate / (60 * hop)))
    if hi <= lo: return 0.0
    bpm = 60 * rate / ((lo + int(np.argmax(corr[lo:hi + 1]))) * hop)
    while bpm < 80: bpm *= 2
    while bpm > 160: bpm /= 2
    return round(float(bpm), 2)

def _estimate_bass_notes(audio: np.ndarray, rate: int) -> list[dict[str, Any]]:
    """Estimate contiguous bass pitches with a small FFT; stable tones stay one note."""
    if len(audio) < 8 or not np.any(np.abs(audio) > 1e-5): return []
    target_frame = 2 ** int(np.ceil(np.log2(max(8, rate * 0.08))))
    frame = min(4096, max(1024, target_frame))
    hop = max(128, frame // 4); count = max(1, 1 + max(0, len(audio) - 1) // hop)
    padded = np.pad(audio, (0, max(0, (count - 1) * hop + frame - len(audio))))
    window = np.hanning(frame)
    freqs = np.fft.rfftfreq(frame, 1 / rate); mask = (freqs >= 35) & (freqs <= min(240, rate / 2))
    if not mask.any(): return []
    rms = np.asarray([np.sqrt(np.mean(padded[i * hop:i * hop + frame] ** 2)) for i in range(count)])
    active = rms >= max(0.01, float(rms.max()) * 0.2)
    pitches: list[int | None] = []
    confidences: list[float] = []
    for i in range(count):
        if not active[i]: pitches.append(None); confidences.append(0.0); continue
        spectrum = np.abs(np.fft.rfft(padded[i * hop:i * hop + frame] * window)); band = spectrum[mask]
        peak = int(np.argmax(band)); frequency = float(freqs[mask][peak]); midi = int(round(69 + 12 * np.log2(frequency / 440.0)))
        pitches.append(midi); confidences.append(float(band[peak] / (band.sum() + 1e-8)))
    notes: list[dict[str, Any]] = []; start = None; current = None; values: list[float] = []
    for i, midi in enumerate(pitches + [None]):
        if midi != current:
            if current is not None and start is not None:
                end = min(len(audio) / rate, i * hop / rate)
                notes.append({"start": round(start, 4), "end": round(end, 4), "duration": round(max(0.0, end - start), 4), "midi": current, "note": _midi_name(current), "velocity": int(min(127, max(1, round(127 * min(1.0, float(np.mean(values)) * 3))))), "confidence": round(float(np.mean(values)), 3)})
            start = i * hop / rate if midi is not None else None; current = midi; values = []
        if midi is not None: values.append(confidences[i])
    return notes

def _midi_name(midi: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[midi % 12]}{midi // 12 - 1}"

def _event_grid(event: dict[str, Any], bpm: float, origin: float, subdivision: int) -> dict[str, Any]:
    step_duration = 60.0 / bpm / (subdivision / 4) if bpm else 0.0
    if not step_duration: return {**event, "nearest_step": None, "bar": None, "beat": None, "step_in_bar": None, "timing_offset_ms": None, "velocity": int(round(127 * event.get("confidence", 0.0)))}
    absolute = (float(event["time"]) - origin) / step_duration; nearest = max(0, int(round(absolute))); steps_per_bar = subdivision
    return {**event, "nearest_step": nearest, "bar": nearest // steps_per_bar + 1, "beat": (nearest % steps_per_bar) // (subdivision // 4) + 1, "step_in_bar": nearest % steps_per_bar + 1, "timing_offset_ms": round((absolute - nearest) * step_duration * 1000, 3), "velocity": int(min(127, max(1, round(127 * event.get("confidence", 0.0)))))}

def analyze_audio(path: str | Path) -> dict[str, Any]:
    audio, rate = _load_audio(path); duration = round(float(len(audio) / rate), 4) if rate else 0.0
    hop, frame = max(128, rate // 50), max(512, int(rate * 0.0464)); times, flux, energy = _frame_features(audio, rate, hop, frame)
    band_novelty = np.maximum(np.diff(energy, axis=0, prepend=energy[:1]), 0).sum(axis=1) if len(energy) else np.zeros(0)
    bpm = _estimate_bpm(band_novelty, rate, hop); beat_step = 60.0 / bpm if bpm else 0.5; beats: list[float] = []
    grid_origin = 0.0
    if duration:
        onsets = _peak_indices(band_novelty, max(0.6, float(np.percentile(band_novelty, 78))) if len(band_novelty) else 0, max(1, int(0.18 * rate / hop)))
        anchor = float(times[onsets[0]]) if len(onsets) else 0.0; grid_origin = anchor
        beats = [round(anchor + i * beat_step, 4) for i in range(max(0, int((duration - anchor) / beat_step) + 1)) if anchor + i * beat_step <= duration]
    labels = ("bass_808", "kick", "snare", "hihat"); event_bands = (0, 0, 2, 3); events: dict[str, list[dict[str, Any]]] = {label: [] for label in labels}
    for label, band in zip(labels, event_bands):
        signal = np.maximum(np.diff(energy[:, band], prepend=energy[:1, band]), 0) if len(energy) else np.zeros(0)
        threshold = max(0.08, float(np.percentile(signal, 72))) if len(signal) else 0
        peaks = _peak_indices(signal, threshold, max(1, int((0.08 if label == "hihat" else 0.12) * rate / hop)))
        for index in peaks:
            confidence = min(1.0, max(0.05, float(signal[index] / (threshold + 1e-8))))
            events[label].append(_event_grid({"time": round(float(times[index]), 4), "confidence": round(confidence, 3)}, bpm, grid_origin, 16))
    names = ("low", "low_mid", "mid", "high")
    frames = [{"time": round(float(t), 4), **{n: round(float(v), 4) for n, v in zip(names, row)}} for t, row in zip(times, energy)]
    bass_notes = _estimate_bass_notes(audio, rate)
    return {"version": "1.0", "source": {"file": Path(path).name, "sample_rate": rate, "channels": 1, "duration": duration}, "tempo": {"bpm": bpm, "beats": beats}, "grid": {"time_signature": "4/4", "subdivision": 16, "bars": max(1, int(np.ceil(max(0.0, duration - grid_origin) / (beat_step * 4)))) if duration and bpm else 0, "origin": round(grid_origin, 4), "step_duration": round(beat_step / 4, 6) if bpm else 0.0}, "energy": {"bands": list(names), "frames": frames}, "events": events, "bass_notes": bass_notes, "analysis": {"method": "spectral-flux-band-candidates+fft-bass", "editable": True, "separation": None}}

def save_beatmap(beatmap: dict[str, Any], destination: str | Path) -> None:
    Path(destination).write_text(json.dumps(beatmap, ensure_ascii=False, indent=2), encoding="utf-8")
