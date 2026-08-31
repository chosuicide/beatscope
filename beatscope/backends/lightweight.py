"""Lightweight backend: multiband novelty, variable-tempo tracking, beat DP."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..audio_io import load_analysis_audio
from ..backends.base import AnalysisEvidence, CancelCallback, ProgressCallback, check_cancelled
from ..features import (
    compute_multiband_novelty,
    estimate_tempo_from_novelty,
    extract_onsets,
)
from ..models import AnalysisConfig
from ..tempo_tracking import TRACKING_PARAMETERS, number_beats, track_tempo_and_beats

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

    Tempo is tracked as a piecewise-constant path over local autocorrelation
    candidates, and beats come from a novelty-guided dynamic program anchored
    on that path — a uniform grid is never regenerated from one global BPM.
    Provenance records which algorithm produced each fact (plan section 16.3).
    """

    name = "lightweight"
    version = "2.0"

    def analyze(
        self,
        audio_path: Path,
        config: AnalysisConfig,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> AnalysisEvidence:
        check_cancelled(cancelled)
        progress("decode", 0.10, "读取音频...")
        y, sr, duration, channels, warnings = load_analysis_audio(audio_path, target_sr=config.sample_rate)

        check_cancelled(cancelled)
        progress("beatgrid", 0.60, "追踪局部速度与拍点...")
        hop = config.hop_length
        times, novelty = compute_multiband_novelty(y, sr=sr, hop=hop, n_fft=config.n_fft)

        prior_bpm = estimate_tempo_from_novelty(novelty["all"], sr, hop)
        if prior_bpm <= 0:
            prior_bpm = 120.0
            warnings.append("Tempo estimation failed; fell back to 120 BPM")

        tracked_duration = round(float(duration), 4)
        result = track_tempo_and_beats(
            novelty["all"], sr, hop,
            global_prior_bpm=prior_bpm,
            duration=tracked_duration,
        )

        if result.beat_times:
            beats = number_beats(result.beat_times)
            grid_origin = round(float(result.beat_times[0]), 4)
            bars = max(1, (len(beats) - 1) // 4 + 1)
            tempo_segments: list[dict[str, Any]] = list(result.tempo_segments)
        else:
            # Plan section 12.5: keep a numeric global BPM, but emit no fake
            # uniform grid just because a fallback tempo exists.
            beats = []
            grid_origin = 0.0
            bars = 1
            tempo_segments = []
            warnings.append("Insufficient rhythmic evidence; no tracked beats emitted")

        check_cancelled(cancelled)
        progress("features", 0.75, "提取多频段瞬态能量...")
        onsets = extract_onsets(times, novelty, sr=sr, hop=hop, bpm=result.global_bpm)

        check_cancelled(cancelled)
        intervals = np.diff([b["time"] for b in beats]) if len(beats) > 1 else np.zeros(0)
        mean_interval = float(np.mean(intervals)) if len(intervals) else 0.0
        interval_cv = float(np.std(intervals) / mean_interval) if mean_interval > 0 else 0.0

        path_diagnostics = result.diagnostics
        diagnostics: dict[str, Any] = {
            "tempo_method": (
                "local-autocorrelation-viterbi"
                if beats else "no-track-global-tempo-fallback"
            ),
            "beat_method": (
                "novelty-guided-dynamic-programming"
                if beats else "no-track-global-tempo-fallback"
            ),
            "candidate_windows": int(path_diagnostics.get("tempo_path_anchors", 0)),
            "tempo_path_changes": max(0, len(tempo_segments) - 1),
            "tracked_beats": len(beats),
            "beats_snapped": int(path_diagnostics.get("snapped_beats", 0)),
            "duplicates_removed": int(path_diagnostics.get("duplicates_removed", 0)),
            "missing_beats_inserted": int(path_diagnostics.get("beats_inserted", 0)),
            "unrepaired_gaps": int(path_diagnostics.get("unrepairable_gaps", 0)),
            "beat_interval_cv": round(interval_cv, 4),
            "variable_tempo": len(tempo_segments) > 1,
            "score_semantics": "normalized path support; not probability",
            "tracking_parameters": dict(TRACKING_PARAMETERS),
            "onset_count": len(onsets),
            "separated": False,
        }

        if beats:
            provenance: dict[str, Any] = {
                "beats": {
                    "method": "novelty-guided-dynamic-programming",
                    "backend": self.name,
                    "tempo_source": "local-autocorrelation-viterbi",
                    "onset_alignment": "bounded-local-maximum",
                },
                "onsets": {"method": "multiband-positive-spectral-flux", "backend": self.name},
                "meter_phase": {
                    "method": "four-four-cycle-from-first-tracked-beat",
                    "backend": self.name,
                    "inferred": True,
                },
            }
        else:
            provenance = {
                "beats": {"method": "no-track-global-tempo-fallback", "backend": self.name},
                "onsets": {"method": "multiband-positive-spectral-flux", "backend": self.name},
            }

        return AnalysisEvidence(
            duration=tracked_duration,
            sample_rate=sr,
            channels=channels,
            tempo_bpm=float(result.global_bpm),
            grid_origin=grid_origin,
            bars=bars,
            beats=beats,
            onsets=onsets,
            energy=compress_energy(novelty, sr, hop),
            tempo_score=result.path_score,
            tempo_segments=tempo_segments,
            audio=y,
            warnings=warnings,
            diagnostics=diagnostics,
            provenance=provenance,
        )
