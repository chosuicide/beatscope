"""Beatgrid analysis, Beat This parser, robust BPM estimation, and local beat interpolation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import numpy as np


@dataclass
class BeatGridResult:
    beats: list[dict[str, Any]]
    bpm: float
    origin: float
    bars: int
    step_duration: float
    variable_tempo: bool = False
    confidence: float = 0.9
    warnings: list[str] = field(default_factory=list)


def parse_beat_this(source: str | Path) -> list[dict[str, Any]]:
    """Parse Beat This .beats content into a structured list of beat dictionaries.
    
    Each item contains:
      - time: float (seconds)
      - beat: int (1..4)
      - bar: int (0 if before the first downbeat, then 1, 2, ...)
      - downbeat: bool
      - sequence_gap: bool
    """
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and Path(source).is_file()):
        lines = Path(source).read_text(encoding="utf-8").splitlines()
    else:
        lines = str(source).splitlines()

    parsed_raw: list[tuple[float, int]] = []
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.replace(",", " ").split()
        if len(fields) < 2:
            raise ValueError(f"Beat This line {line_number} needs time and beat")
        try:
            time, beat = float(fields[0]), int(float(fields[1]))
        except ValueError as exc:
            raise ValueError(f"Invalid Beat This line {line_number}: {raw}") from exc
        if time < 0 or beat not in (1, 2, 3, 4):
            raise ValueError(f"Invalid Beat This value on line {line_number}: {raw}")
        if parsed_raw and time <= parsed_raw[-1][0]:
            raise ValueError(f"Beat This times must be strictly increasing at line {line_number}")
        parsed_raw.append((time, beat))

    if len(parsed_raw) < 2:
        raise ValueError("Beat This file needs at least two beat points")

    result: list[dict[str, Any]] = []
    current_bar = 0
    first_downbeat_seen = False

    for idx, (time, beat) in enumerate(parsed_raw):
        if beat == 1:
            first_downbeat_seen = True
            current_bar += 1
        elif not first_downbeat_seen:
            current_bar = 0

        sequence_gap = False
        if idx > 0:
            prev_beat = parsed_raw[idx - 1][1]
            expected_next = (prev_beat % 4) + 1
            if beat != expected_next and beat != 1:
                sequence_gap = True

        result.append({
            "time": round(time, 4),
            "beat": beat,
            "bar": current_bar,
            "downbeat": bool(beat == 1),
            "sequence_gap": sequence_gap,
        })

    return result


def estimate_bpm(beat_times: list[float] | np.ndarray) -> tuple[float, float, bool]:
    """Estimate global BPM from beat timestamps using median and MAD outlier rejection.
    
    Returns (bpm, confidence, variable_tempo).
    """
    times = np.asarray(beat_times, dtype=float)
    if len(times) < 2:
        return 120.0, 0.0, False

    intervals = np.diff(times)
    median = float(np.median(intervals))
    if median <= 0:
        return 120.0, 0.0, False

    mad = float(np.median(np.abs(intervals - median)))
    threshold = max(3.0 * mad, 0.03)
    valid_mask = np.abs(intervals - median) <= threshold
    valid_intervals = intervals[valid_mask]

    if len(valid_intervals) == 0:
        valid_intervals = intervals

    bpm = 60.0 / float(np.median(valid_intervals))
    
    # Calculate variability
    std_interval = float(np.std(valid_intervals))
    variable_tempo = bool(std_interval > 0.015)
    confidence = max(0.2, min(0.99, 1.0 - (std_interval / median)))

    return round(bpm, 3), round(confidence, 2), variable_tempo


def quantize_to_beat_grid(
    t: float,
    beats: list[dict[str, Any]],
    subdivision: int = 16,
    default_bpm: float = 120.0,
    default_origin: float = 0.0,
) -> dict[str, Any]:
    """Quantize a timestamp using real adjacent beat interpolation where possible.
    
    Returns dict with quantized_time, offset_ms, bar, beat, step_in_bar, nearest_step, pre_grid.
    """
    if not beats:
        step_duration = (60.0 / default_bpm) / (subdivision / 4)
        nearest = int(round((t - default_origin) / step_duration))
        quantized = default_origin + nearest * step_duration
        in_grid = nearest >= 0
        return {
            "quantized_time": round(float(quantized), 4),
            "offset_ms": round((t - quantized) * 1000.0, 3),
            "nearest_step": nearest,
            "bar": (nearest // subdivision + 1) if in_grid else 0,
            "beat": (nearest % subdivision // (subdivision // 4) + 1) if in_grid else 0,
            "step_in_bar": (nearest % subdivision + 1) if in_grid else 0,
            "pre_grid": not in_grid,
        }

    beat_times = np.array([b["time"] for b in beats], dtype=float)
    parts_per_beat = subdivision // 4

    # Case 1: t is before the first beat
    if t < beat_times[0]:
        first_beat = beats[0]
        # estimate local step from first two beats
        avg_beat_len = beat_times[1] - beat_times[0] if len(beat_times) > 1 else (60.0 / default_bpm)
        step_len = avg_beat_len / parts_per_beat
        steps_before = int(round((beat_times[0] - t) / step_len))
        quantized = beat_times[0] - steps_before * step_len
        return {
            "quantized_time": round(float(quantized), 4),
            "offset_ms": round((t - quantized) * 1000.0, 3),
            "nearest_step": -steps_before,
            "bar": 0,
            "beat": 0,
            "step_in_bar": 0,
            "pre_grid": True,
        }

    # Case 2: t is after the last beat
    if t >= beat_times[-1]:
        last_beat = beats[-1]
        avg_beat_len = beat_times[-1] - beat_times[-2] if len(beat_times) > 1 else (60.0 / default_bpm)
        step_len = avg_beat_len / parts_per_beat
        steps_after = int(round((t - beat_times[-1]) / step_len))
        quantized = beat_times[-1] + steps_after * step_len
        # calculate bar / beat continuation
        total_steps_from_last = steps_after
        cur_beat_idx = last_beat["beat"] - 1 + (total_steps_from_last // parts_per_beat)
        cur_bar = last_beat["bar"] + (cur_beat_idx // 4)
        cur_beat = (cur_beat_idx % 4) + 1
        cur_step_in_bar = (cur_beat - 1) * parts_per_beat + (total_steps_from_last % parts_per_beat) + 1
        return {
            "quantized_time": round(float(quantized), 4),
            "offset_ms": round((t - quantized) * 1000.0, 3),
            "nearest_step": 0,  # relative
            "bar": cur_bar,
            "beat": cur_beat,
            "step_in_bar": cur_step_in_bar,
            "pre_grid": False,
        }

    # Case 3: t is strictly within [beat_times[0], beat_times[-1]]
    idx = int(np.searchsorted(beat_times, t)) - 1
    left_beat = beats[idx]
    right_beat = beats[idx + 1]
    left_t = left_beat["time"]
    right_t = right_beat["time"]
    beat_span = right_t - left_t

    candidate_times = [left_t + beat_span * part / parts_per_beat for part in range(parts_per_beat + 1)]
    best_part = min(range(len(candidate_times)), key=lambda p: abs(candidate_times[p] - t))
    quantized = candidate_times[best_part]

    if best_part == parts_per_beat:
        # Snap to right beat
        target_beat = right_beat
        step_in_beat = 0
    else:
        target_beat = left_beat
        step_in_beat = best_part

    bar = target_beat["bar"]
    beat_num = target_beat["beat"]
    step_in_bar = (beat_num - 1) * parts_per_beat + step_in_beat + 1

    return {
        "quantized_time": round(float(quantized), 4),
        "offset_ms": round((t - quantized) * 1000.0, 3),
        "nearest_step": 0,
        "bar": bar,
        "beat": beat_num,
        "step_in_bar": step_in_bar,
        "pre_grid": bool(bar == 0),
    }


class BeatGridAnalyzer:
    """Encapsulates Beat This parsing and beatgrid generation."""

    def analyze_beats(
        self,
        beat_this_source: str | Path,
        duration: float = 0.0,
        subdivision: int = 16,
    ) -> BeatGridResult:
        beats = parse_beat_this(beat_this_source)
        beat_times = [b["time"] for b in beats]
        bpm, confidence, variable_tempo = estimate_bpm(beat_times)
        
        downbeat_time = next((b["time"] for b in beats if b["beat"] == 1), beat_times[0])
        max_time = max(duration, beat_times[-1])
        step_duration = (60.0 / bpm) / (subdivision / 4)
        
        # Calculate bars
        bars = max(1, int(np.ceil(max(0.0, max_time - downbeat_time) / (60.0 / bpm * 4.0))))
        
        warnings = []
        gap_count = sum(1 for b in beats if b["sequence_gap"])
        if gap_count > 0:
            warnings.append(f"Detected {gap_count} beat sequence gaps in Beat This tracking")

        return BeatGridResult(
            beats=beats,
            bpm=bpm,
            origin=round(downbeat_time, 4),
            bars=bars,
            step_duration=round(step_duration, 6),
            variable_tempo=variable_tempo,
            confidence=confidence,
            warnings=warnings,
        )
