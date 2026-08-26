import numpy as np
import pytest
from beatscope.features import (
    normalize_band_signal,
    compute_multiband_novelty,
    detect_transient_peaks,
    extract_onsets,
)


def test_normalization_extremes_under_two_percent():
    np.random.seed(42)
    raw = np.random.lognormal(mean=0.0, sigma=1.0, size=5000)
    norm = normalize_band_signal(raw)
    assert norm.min() >= 0.0
    assert norm.max() <= 1.0
    extremes_pct = (norm >= 0.99).mean() * 100
    assert extremes_pct < 2.0


def test_sustained_sine_novelty():
    sr = 44100
    t = np.arange(sr * 2) / sr
    y = 0.5 * np.sin(2 * np.pi * 100 * t).astype(np.float32)
    times, novelty = compute_multiband_novelty(y, sr=sr, hop=256)
    assert len(times) > 0
    steady = novelty["all"][20:]
    assert steady.mean() < 0.2


def test_extract_onsets_clicks():
    sr = 44100
    duration = 2.0
    y = np.zeros(int(sr * duration), dtype=np.float32)
    for onset_sec in (0.2, 0.6, 1.0, 1.4):
        idx = int(onset_sec * sr)
        y[idx : idx + 200] = np.hanning(200)

    times, novelty = compute_multiband_novelty(y, sr=sr, hop=256)
    onsets = extract_onsets(times, novelty, sr=sr, hop=256, bpm=150.0)
    assert len(onsets) >= 4
    extracted_times = [o["raw_time"] for o in onsets]
    for expected in (0.2, 0.6, 1.0, 1.4):
        assert any(abs(t - expected) < 0.05 for t in extracted_times)
