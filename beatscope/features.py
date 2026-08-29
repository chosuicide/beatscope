"""Multiband spectral energy, novelty curves, and transient detection."""
from __future__ import annotations

from typing import Any
import numpy as np

try:
    import librosa
except ImportError as exc:  # pragma: no cover
    librosa = None
    _LIBROSA_ERROR = exc


def _require_librosa():
    if librosa is None:
        raise RuntimeError("features module requires optional dependency librosa") from _LIBROSA_ERROR
    return librosa


def estimate_tempo_from_novelty(values: np.ndarray, rate: int, hop: int) -> float:
    """Estimate BPM from a novelty curve via onset intervals and autocorrelation.

    Pure NumPy so both the legacy and unified pipelines can use it without librosa.
    """
    if len(values) < 4 or not np.any(values > 0):
        return 0.0
    onset_threshold = max(0.6, float(np.percentile(values, 78)))
    onset_peaks = detect_transient_peaks(values, min_distance_samples=max(1, int(0.12 * rate / hop)), threshold=onset_threshold)
    if len(onset_peaks) < 3:
        return 0.0
    intervals = np.diff(onset_peaks).astype(float)
    median_interval = float(np.median(intervals))
    if median_interval <= 0 or float(np.median(np.abs(intervals - median_interval))) / median_interval > 0.3:
        return 0.0
    centered = values - np.mean(values)
    corr = np.correlate(centered, centered, mode="full")[len(centered) - 1:]
    lo = max(1, int(60 * rate / (180 * hop)))
    hi = min(len(corr) - 1, int(60 * rate / (60 * hop)))
    if hi <= lo:
        return 0.0
    bpm = 60 * rate / ((lo + int(np.argmax(corr[lo:hi + 1]))) * hop)
    while bpm < 80:
        bpm *= 2
    while bpm > 160:
        bpm /= 2
    return round(float(bpm), 2)


def normalize_band_signal(values: np.ndarray) -> np.ndarray:
    """Robust percentile-based normalization with smooth compression.
    
    Ensures that values >= 0.99 represent true extremes (< 2% of frames).
    """
    if len(values) == 0:
        return np.zeros(0, dtype=np.float32)
    lo = float(np.percentile(values, 10))
    hi = float(np.percentile(values, 99.5))
    scale = max(hi - lo, 1e-8)
    clipped = np.clip((values - lo) / scale, 0.0, 1.0)
    # Smooth compression
    compressed = np.sqrt(clipped)
    return compressed.astype(np.float32)


def compute_multiband_novelty(
    y: np.ndarray,
    sr: int,
    hop: int = 256,
    n_fft: int = 2048,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Compute normalized positive flux novelty across LOW, MID, HIGH, and ALL bands."""
    lib = _require_librosa()
    if len(y) == 0:
        empty = np.zeros(0, dtype=np.float32)
        return empty, {"all": empty, "low": empty, "mid": empty, "high": empty}

    spectrum = np.abs(lib.stft(y, n_fft=n_fft, hop_length=hop, center=True))
    freqs = lib.fft_frequencies(sr=sr, n_fft=n_fft)

    masks = {
        "low": (20, 180),
        "mid": (180, 4000),
        "high": (4000, min(16000, sr / 2)),
    }

    raw_novelty: dict[str, np.ndarray] = {}
    for name, (low, high) in masks.items():
        mask = (freqs >= low) & (freqs < high)
        if mask.any():
            energy = np.mean(spectrum[mask], axis=0)
        else:
            energy = np.zeros(spectrum.shape[1], dtype=np.float32)
        raw_novelty[name] = np.maximum(0.0, np.diff(np.log1p(energy), prepend=energy[:1]))

    raw_novelty["all"] = raw_novelty["low"] + raw_novelty["mid"] + raw_novelty["high"]

    normalized: dict[str, np.ndarray] = {}
    for key, arr in raw_novelty.items():
        normalized[key] = normalize_band_signal(arr)

    times = np.arange(len(normalized["all"]), dtype=np.float32) * hop / sr
    return times, normalized


def detect_transient_peaks(
    values: np.ndarray,
    min_distance_samples: int = 8,
    threshold: float = 0.10,
) -> np.ndarray:
    """Find peak indices above an adaptive threshold with minimum distance spacing."""
    if len(values) < 3:
        return np.zeros(0, dtype=int)

    candidates = np.where(
        (values[1:-1] >= values[:-2])
        & (values[1:-1] > values[2:])
        & (values[1:-1] >= threshold)
    )[0] + 1

    if len(candidates) == 0:
        return np.zeros(0, dtype=int)

    # Sort candidates by strength descending to resolve conflicts
    sorted_candidates = candidates[np.argsort(values[candidates])[::-1]]
    chosen: list[int] = []
    for cand in sorted_candidates:
        c = int(cand)
        if all(abs(c - other) >= min_distance_samples for other in chosen):
            chosen.append(c)

    return np.array(sorted(chosen), dtype=int)


def extract_onsets(
    times: np.ndarray,
    novelty: dict[str, np.ndarray],
    sr: int,
    hop: int = 256,
    bpm: float = 120.0,
) -> list[dict[str, Any]]:
    """Extract factual onsets with local window adaptive accent labeling."""
    all_band = novelty.get("all", np.zeros(0, dtype=np.float32))
    if len(all_band) == 0 or len(times) == 0:
        return []

    threshold = max(0.10, float(np.percentile(all_band, 75)))
    min_dist_sec = 0.045
    min_dist_samples = max(1, int(round(min_dist_sec * sr / hop)))

    peaks = detect_transient_peaks(all_band, min_dist_samples, threshold)
    if len(peaks) == 0:
        return []

    bar_sec = (60.0 / bpm) * 4.0 if bpm > 0 else 2.0
    window_sec = 4.0 * bar_sec

    # Prepare raw onsets
    raw_onsets = []
    for idx, frame in enumerate(peaks, 1):
        t = float(times[frame])
        str_val = float(all_band[frame])
        bands = {
            "all": round(str_val, 4),
            "low": round(float(novelty["low"][frame]), 4),
            "mid": round(float(novelty["mid"][frame]), 4),
            "high": round(float(novelty["high"][frame]), 4),
        }
        raw_onsets.append({
            "id": idx,
            "frame": frame,
            "raw_time": round(t, 4),
            "strength": round(str_val, 4),
            "bands": bands,
            "confidence": round(float(min(1.0, max(0.05, str_val))), 3),
        })

    # Accent detection via local window percentile (85th percentile within +/- 4 bars)
    onsets = []
    for cur in raw_onsets:
        t = cur["raw_time"]
        local_strengths = [
            o["strength"] for o in raw_onsets if abs(o["raw_time"] - t) <= window_sec
        ]
        accent_thresh = float(np.percentile(local_strengths, 85)) if len(local_strengths) >= 4 else 0.72
        is_accent = bool(cur["strength"] >= max(0.60, accent_thresh))
        
        onsets.append({
            "id": cur["id"],
            "raw_time": cur["raw_time"],
            "strength": cur["strength"],
            "bands": cur["bands"],
            "accent": is_accent,
            "confidence": cur["confidence"],
        })

    return onsets
