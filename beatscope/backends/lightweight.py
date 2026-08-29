"""Lightweight backend: multiband novelty, autocorrelation tempo, uniform beat grid."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from ..audio_io import load_analysis_audio
from ..backends.base import AnalysisEvidence, CancelCallback, ProgressCallback, check_cancelled
from ..features import (
    compute_multiband_novelty,
    detect_transient_peaks,
    estimate_tempo_from_novelty,
    extract_onsets,
)
from ..models import AnalysisConfig

ENERGY_BANDS = ("all", "low", "mid", "high")


def compress_energy(novelty: dict[str, np.ndarray], sr: int, hop: int) -> dict:
    """Serialize the novelty curves as the v3 energy section."""
    fps = int(round(1.0 / (hop / sr))) if sr > 0 and hop > 0 else 100
    return {
        "fps": fps,
        "start": 0.0,
        "bands": {
            name: [round(float(v), 4) for v in novelty[name]]
            for name in ENERGY_BANDS
        },
    }


class LightweightBackend:
    """Analyze the full mix (or a provided stem) without external beat markers.

    Beat placement stays a uniform grid derived from one global BPM estimate;
    provenance records this honestly instead of implying real beat tracking.
    """

    name = "lightweight"
    version = "1.0"

    def analyze(
        self,
        audio_path: Path,
        config: AnalysisConfig,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> AnalysisEvidence:
        check_cancelled(cancelled)
        progress("decode", 0.10, "读取音频...")
        y, sr, duration, warnings = load_analysis_audio(audio_path, target_sr=config.sample_rate)

        check_cancelled(cancelled)
        progress("beatgrid", 0.60, "计算拍点与网格...")
        hop = config.hop_length
        times, novelty = compute_multiband_novelty(y, sr=sr, hop=hop, n_fft=config.n_fft)

        bpm = estimate_tempo_from_novelty(novelty["all"], sr, hop)
        if bpm <= 0:
            bpm = 120.0
            warnings.append("Tempo estimation failed; fell back to 120 BPM")

        beat_step = 60.0 / bpm
        peaks = detect_transient_peaks(
            novelty["all"],
            min_distance_samples=max(1, int(0.12 * sr / hop)),
            threshold=0.15,
        )
        origin = float(times[peaks[0]]) if len(peaks) > 0 else 0.0

        beats: list[dict] = []
        cur_time, cur_beat, cur_bar = origin, 1, 1
        while cur_time < duration:
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

        check_cancelled(cancelled)
        progress("features", 0.75, "提取多频段瞬态能量...")
        onsets = extract_onsets(times, novelty, sr=sr, hop=hop, bpm=bpm)

        check_cancelled(cancelled)
        intervals = np.diff([b["time"] for b in beats]) if len(beats) > 1 else np.zeros(0)
        mean_interval = float(np.mean(intervals)) if len(intervals) else 0.0
        interval_cv = float(np.std(intervals) / mean_interval) if mean_interval > 0 else 0.0

        return AnalysisEvidence(
            duration=round(float(duration), 4),
            sample_rate=sr,
            channels=2,
            tempo_bpm=float(bpm),
            grid_origin=round(origin, 4),
            bars=bars,
            beats=beats,
            onsets=onsets,
            energy=compress_energy(novelty, sr, hop),
            tempo_score=None,
            warnings=warnings,
            diagnostics={
                "tempo_method": "spectral-flux-autocorrelation",
                "beat_interval_cv": round(interval_cv, 4),
                "onset_count": len(onsets),
                "variable_tempo": False,
                "separated": False,
            },
            provenance={
                "beats": {"method": "uniform-grid-from-global-bpm", "backend": self.name},
                "onsets": {"method": "multiband-positive-spectral-flux", "backend": self.name},
            },
        )
