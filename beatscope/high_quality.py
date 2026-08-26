"""Optional, real stem-based analysis for song replication.

Demucs does separation; this module only analyzes its drums and bass stems.
librosa is optional for the normal lightweight path but required by this pipeline.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import numpy as np

from .analysis import _event_grid, _midi_name

try:
    import librosa
except ImportError as exc:  # pragma: no cover
    librosa = None
    _LIBROSA_ERROR = exc

def _require_librosa() -> Any:
    if librosa is None: raise RuntimeError("高质量 stem pipeline 需要 librosa；请安装可选依赖") from _LIBROSA_ERROR
    return librosa

def _bass_notes(y: np.ndarray, sr: int) -> list[dict[str, Any]]:
    """Track monophonic F0 with librosa.pyin and merge stable frames."""
    lib = _require_librosa(); frame = 4096; hop = 512
    f0, voiced, probability = lib.pyin(y, fmin=lib.note_to_hz("C1"), fmax=lib.note_to_hz("C4"), sr=sr, frame_length=frame, hop_length=hop, fill_na=None)
    rms = lib.feature.rms(y=y, frame_length=frame, hop_length=hop, center=True)[0]
    active = (np.asarray(voiced, dtype=bool)) & (np.asarray(probability) >= 0.35) & (rms >= max(0.008, float(rms.max()) * 0.06))
    midi = np.where(active, np.rint(lib.hz_to_midi(np.nan_to_num(f0, nan=0.0))).astype(int), -1)
    notes: list[dict[str, Any]] = []; start = None; current = None; conf: list[float] = []
    for i, pitch in enumerate(np.r_[midi, -1]):
        if pitch != current:
            if current is not None and start is not None:
                end = min(len(y) / sr, float(lib.frames_to_time(i, sr=sr, hop_length=hop)))
                values = conf or [0.0]; notes.append({"start": round(start, 4), "end": round(end, 4), "duration": round(max(0.0, end - start), 4), "midi": int(current), "note": _midi_name(int(current)), "velocity": int(min(127, max(1, round(127 * min(1.0, float(np.mean(values))))))), "confidence": round(float(np.mean(values)), 3)})
            start = float(lib.frames_to_time(i, sr=sr, hop_length=hop)) if pitch >= 0 else None; current = int(pitch) if pitch >= 0 else None; conf = []
        if pitch >= 0: conf.append(float(probability[i]))
    filtered = [n for n in notes if n["duration"] >= 0.08 and n["confidence"] >= 0.35]
    merged: list[dict[str, Any]] = []
    for note in filtered:
        if merged and note["midi"] == merged[-1]["midi"] and note["start"] - merged[-1]["end"] <= 0.16:
            merged[-1]["end"] = note["end"]
            merged[-1]["duration"] = round(merged[-1]["end"] - merged[-1]["start"], 4)
            merged[-1]["confidence"] = round((merged[-1]["confidence"] + note["confidence"]) / 2, 3)
            merged[-1]["velocity"] = max(merged[-1]["velocity"], note["velocity"])
        else:
            merged.append(note)
    return merged

def _drum_events(y: np.ndarray, sr: int, bpm: float, origin: float) -> dict[str, list[dict[str, Any]]]:
    lib = _require_librosa(); hop = 256; n_fft = 2048
    onset_env = lib.onset.onset_strength(y=y, sr=sr, hop_length=hop, aggregate=np.median)
    onset_frames = lib.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=hop, units="frames", backtrack=False, pre_max=12, post_max=12, pre_avg=24, post_avg=24, delta=0.15, wait=8)
    stft = np.abs(lib.stft(y, n_fft=n_fft, hop_length=hop, center=True)); freqs = lib.fft_frequencies(sr=sr, n_fft=n_fft)
    masks = ((20, 160), (160, 4000), (4000, min(16000, sr / 2)))
    bands = []
    for low, high in masks:
        mask = (freqs >= low) & (freqs < high); bands.append(np.mean(stft[mask], axis=0) if mask.any() else np.zeros(stft.shape[1]))
    bands = np.asarray(bands); peak_norm = onset_env / max(float(np.percentile(onset_env, 95)), 1e-8)
    events = {"bass_808": [], "kick": [], "snare": [], "hihat": []}
    for frame in onset_frames:
        if frame >= bands.shape[1]: continue
        scores = np.maximum(0, bands[:, frame]); total = float(scores.sum()) + 1e-8; ratios = scores / total; strength = min(1.0, max(0.05, float(peak_norm[min(frame, len(peak_norm) - 1)])))
        # Assign one class per transient. This prevents a single drum hit from
        # being copied to kick, snare, and hat simultaneously.
        if ratios[0] >= 0.42 and ratios[0] == max(ratios): label = "kick"
        elif ratios[2] >= 0.28 and ratios[2] == max(ratios): label = "hihat"
        elif ratios[1] >= 0.28: label = "snare"
        else: label = ("kick", "snare", "hihat")[int(np.argmax(ratios))]
        time = float(lib.frames_to_time(frame, sr=sr, hop_length=hop)); confidence = min(1.0, strength * float(max(ratios)))
        events[label].append(_event_grid({"time": round(time, 4), "confidence": round(confidence, 3)}, bpm, origin, 16))
    return events

def analyze_separated(original: str | Path, drums: str | Path, bass: str | Path, model: str = "htdemucs") -> dict[str, Any]:
    """Analyze real Demucs stems and return the normal BeatScope beatmap schema."""
    lib = _require_librosa(); drums_y, sr = lib.load(str(drums), sr=None, mono=True); bass_y, bass_sr = lib.load(str(bass), sr=None, mono=True)
    if bass_sr != sr: bass_y = lib.resample(bass_y, orig_sr=bass_sr, target_sr=sr)
    onset_hop = 256
    onset_env = lib.onset.onset_strength(y=drums_y, sr=sr, hop_length=onset_hop, aggregate=np.median)
    # librosa's default beat-resolution tempo avoids the 86 BPM half-time
    # candidate produced by a very fine (256-sample) onset hop on this stem.
    tempo_values = np.asarray(lib.feature.tempo(y=drums_y, sr=sr, aggregate=np.median)).reshape(-1)
    bpm = round(float(tempo_values[0]), 3) if tempo_values.size and tempo_values[0] > 0 else 0.0
    onset_frames = lib.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=onset_hop, backtrack=False, delta=0.15, wait=8)
    origin = float(lib.frames_to_time(int(onset_frames[0]), sr=sr, hop_length=onset_hop)) if len(onset_frames) else 0.0
    duration = round(float(len(drums_y) / sr), 4); beat_step = 60 / bpm if bpm else 0.5
    events = _drum_events(drums_y, sr, bpm, origin)
    beats = [round(origin + i * beat_step, 4) for i in range(max(0, int((duration - origin) / beat_step) + 1)) if origin + i * beat_step <= duration]
    grid = {"time_signature": "4/4", "subdivision": 16, "bars": max(1, int(np.ceil(max(0, duration - origin) / (beat_step * 4)))) if bpm else 0, "origin": round(origin, 4), "step_duration": round(beat_step / 4, 6) if bpm else 0.0, "source": "demucs-drums"}
    separation = {"drums": str(Path(drums).resolve()), "bass": str(Path(bass).resolve())}
    for name in ("other", "vocals"):
        sibling = Path(drums).with_name(f"{name}.wav")
        if sibling.is_file(): separation[name] = str(sibling.resolve())
    return {"version": "1.0", "source": {"file": Path(original).name, "path": str(Path(original).resolve()), "sample_rate": sr, "channels": 1, "duration": duration}, "tempo": {"bpm": bpm, "beats": beats}, "grid": grid, "energy": {"bands": [], "frames": []}, "events": events, "bass_notes": _bass_notes(bass_y, sr), "analysis": {"method": "demucs-htdemucs+librosa-beat-onset-pyin", "model": model, "editable": True, "separation": separation}}

def save_analysis(result: dict[str, Any], destination: str | Path) -> None:
    Path(destination).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
