"""Run TorchCREPE on a separated bass stem and emit discrete note candidates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
import torch
import torchcrepe
from scipy.ndimage import median_filter


def midi_name(midi: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[midi % 12]}{midi // 12 - 1}"


def segment_notes(pitch: np.ndarray, periodicity: np.ndarray, hop_seconds: float) -> list[dict]:
    valid = np.isfinite(pitch) & (pitch > 0)
    midi_float = np.full(len(pitch), np.nan, dtype=float)
    midi_float[valid] = librosa.hz_to_midi(pitch[valid])
    if valid.any():
        indices = np.arange(len(pitch))
        filled = np.interp(indices, indices[valid], midi_float[valid])
        midi_float = median_filter(filled, size=11, mode="nearest")
    midi = np.where(valid, np.rint(midi_float), -1).astype(int)
    notes: list[dict] = []
    start = 0
    current = int(midi[0]) if len(midi) else -1
    for index in range(1, len(midi) + 1):
        value = int(midi[index]) if index < len(midi) else -2
        if value == current:
            continue
        if current >= 0:
            duration = (index - start) * hop_seconds
            confidence = float(np.mean(periodicity[start:index]))
            if duration >= 0.08 and confidence >= 0.35:
                notes.append({
                    "start": round(start * hop_seconds, 4),
                    "end": round(index * hop_seconds, 4),
                    "duration": round(duration, 4),
                    "midi": current,
                    "note": midi_name(current),
                    "confidence": round(confidence, 3),
                })
        start, current = index, value

    merged: list[dict] = []
    for note in notes:
        if merged and note["midi"] == merged[-1]["midi"] and note["start"] - merged[-1]["end"] <= 0.12:
            merged[-1]["end"] = note["end"]
            merged[-1]["duration"] = round(merged[-1]["end"] - merged[-1]["start"], 4)
            merged[-1]["confidence"] = round((merged[-1]["confidence"] + note["confidence"]) / 2, 3)
        else:
            merged.append(note)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    audio, sample_rate = sf.read(args.audio, dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    target_rate, hop = 16000, 160
    if sample_rate != target_rate:
        audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=target_rate)
    audio_tensor = torch.from_numpy(np.asarray(audio, dtype=np.float32)).unsqueeze(0).cuda()
    with torch.inference_mode():
        pitch, periodicity = torchcrepe.predict(
            audio_tensor,
            target_rate,
            hop_length=hop,
            fmin=45,
            fmax=220,
            model="full",
            return_periodicity=True,
            batch_size=2048,
            device="cuda",
        )
        periodicity = torchcrepe.filter.median(periodicity, 7)
        periodicity = torchcrepe.threshold.Silence(-55)(periodicity, audio_tensor, target_rate, hop)
        pitch = torchcrepe.filter.median(pitch, 7)
        pitch = torchcrepe.threshold.At(0.45)(pitch, periodicity)

    pitch_np = pitch.squeeze(0).cpu().numpy()
    periodicity_np = periodicity.squeeze(0).cpu().numpy()
    notes = segment_notes(pitch_np, periodicity_np, hop / target_rate)
    voiced = pitch_np[pitch_np > 0]
    midi_frames = np.rint(librosa.hz_to_midi(voiced)).astype(int) if len(voiced) else np.zeros(0, dtype=int)
    unique, counts = np.unique(midi_frames, return_counts=True)
    top_pitches = [
        {"midi": int(note), "note": midi_name(int(note)), "frames": int(count)}
        for note, count in sorted(zip(unique, counts), key=lambda item: item[1], reverse=True)[:10]
    ]
    result = {
        "backend": "torchcrepe-0.0.24/full",
        "device": torch.cuda.get_device_name(0),
        "source": str(args.audio.resolve()),
        "frame_hop_seconds": hop / target_rate,
        "voiced_frame_ratio": round(float(np.mean(pitch_np > 0)), 4),
        "median_frequency_hz": round(float(np.median(voiced)), 3) if len(voiced) else None,
        "notes": notes,
        "note_count": len(notes),
        "midi_min": min((note["midi"] for note in notes), default=None),
        "midi_max": max((note["midi"] for note in notes), default=None),
        "top_frame_pitches": top_pitches,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "notes"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
