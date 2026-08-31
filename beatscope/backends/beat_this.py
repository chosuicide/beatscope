"""Beat This backend: real beat markers from a .beats file drive the grid."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..audio_io import load_analysis_audio, probe_audio_channels
from ..backends.base import AnalysisEvidence, CancelCallback, ProgressCallback, check_cancelled
from ..backends.lightweight import compress_energy
from ..beatgrid import estimate_bpm, parse_beat_this
from ..features import compute_multiband_novelty, extract_onsets
from ..models import AnalysisConfig
from ..tempo_tracking import build_tempo_segments_from_beats


class BeatThisBackend:
    """Analyze a drums stem (or the full mix) using externally provided beat markers.

    Beats come from the marker file; the global BPM is derived from marker
    intervals and never regenerates the grid. Marker timestamps are real
    beats, so tempo segments are built directly from their intervals and
    marker tempo changes survive the pipeline (plan section 15.5).
    """

    name = "beat-this"
    version = "1.0"

    def __init__(self, beat_file: str | Path, drums_path: str | Path | None = None):
        self.beat_file = Path(beat_file)
        self.drums_path = Path(drums_path) if drums_path is not None else None

    def analyze(
        self,
        audio_path: Path,
        config: AnalysisConfig,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> AnalysisEvidence:
        check_cancelled(cancelled)
        progress("decode", 0.10, "读取鼓组音轨...")
        y, sr, duration, _analysis_channels, warnings = load_analysis_audio(
            self.drums_path or audio_path, target_sr=config.sample_rate,
        )
        source_channels = probe_audio_channels(audio_path)

        check_cancelled(cancelled)
        progress("beatgrid", 0.60, "解析 Beat This 拍点...")
        beats = parse_beat_this(self.beat_file)
        marker_times = [b["time"] for b in beats]
        bpm, tempo_score, _estimator_variable = estimate_bpm(marker_times)
        tracked_duration = round(float(duration), 4)
        tempo_segments = list(
            build_tempo_segments_from_beats(
                marker_times, tracked_duration, method="beat-marker-intervals",
            )
        )

        gap_count = sum(1 for b in beats if b["sequence_gap"])
        if gap_count > 0:
            warnings.append(f"Detected {gap_count} beat sequence gaps in Beat This tracking")

        origin = next((b["time"] for b in beats if b["beat"] == 1), beats[0]["time"])
        max_time = max(duration, beats[-1]["time"])
        bar_seconds = (60.0 / bpm) * 4.0
        bars = max(1, int(np.ceil(max(0.0, max_time - origin) / bar_seconds)))

        check_cancelled(cancelled)
        progress("features", 0.75, "提取多频段瞬态能量...")
        hop = config.hop_length
        times, novelty = compute_multiband_novelty(y, sr=sr, hop=hop, n_fft=config.n_fft)
        onsets = extract_onsets(times, novelty, sr=sr, hop=hop, bpm=bpm)

        return AnalysisEvidence(
            duration=tracked_duration,
            sample_rate=sr,
            channels=source_channels,
            tempo_bpm=float(bpm),
            grid_origin=round(float(origin), 4),
            bars=bars,
            beats=beats,
            onsets=onsets,
            energy=compress_energy(novelty, sr, hop),
            tempo_score=float(tempo_score),
            tempo_segments=tempo_segments,
            audio=y,
            warnings=warnings,
            diagnostics={
                "tempo_method": "beat-marker-intervals",
                "sequence_gaps": gap_count,
                "onset_count": len(onsets),
                "variable_tempo": len(tempo_segments) > 1,
                "separated": self.drums_path is not None,
            },
            provenance={
                "beats": {
                    "method": "beat-this-markers",
                    "backend": self.name,
                    "tempo_source": "beat-marker-intervals",
                },
                "onsets": {"method": "multiband-positive-spectral-flux", "backend": self.name},
            },
        )
