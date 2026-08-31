"""Unit tests for bar-synchronous multi-view structure features (v0.7)."""
from __future__ import annotations

import numpy as np
import pytest

import librosa
from beatscope.structure_features import (
    BarSpan,
    build_bar_spans,
    extract_structure_features,
    robust_normalize,
)

SR = 22050


def _beat_entries(beat_times: list[float], beats_per_bar: int = 4) -> list[dict]:
    beats = []
    for index, time in enumerate(beat_times):
        beats.append({
            "time": round(time, 4),
            "bar": index // beats_per_bar + 1,
            "beat": index % beats_per_bar + 1,
            "downbeat": index % beats_per_bar == 0,
        })
    return beats


def _synth_song(bars: int = 4, bpm: float = 120.0, *, with_nan: bool = False) -> tuple[np.ndarray, list[dict]]:
    """Bars of chord pad + one click per beat; optional NaN for cleanup tests."""
    beat_seconds = 60.0 / bpm
    duration = bars * 4 * beat_seconds
    signal = np.zeros(int(round(duration * SR)), dtype=np.float32)
    t = np.arange(signal.size) / SR
    signal += (0.08 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)
    beat_times = []
    index = 0
    while index * beat_seconds < duration - 1e-6:
        moment = index * beat_seconds
        beat_times.append(round(moment, 4))
        start = int(round(moment * SR))
        length = int(0.05 * SR)
        env = np.exp(-np.arange(length) / SR * 60.0)
        signal[start:start + length] += (0.5 * env * np.sin(2 * np.pi * 900.0 * np.arange(length) / SR)).astype(np.float32)
        index += 1
    if with_nan:
        signal[1000:1010] = np.nan
    return signal, _beat_entries(beat_times)


# ---------------------------------------------------------------- spans

def test_bar_spans_from_consecutive_downbeats():
    beats = _beat_entries([i * 0.5 for i in range(16)])  # 4 bars at 120 BPM
    spans, warnings = build_bar_spans(beats, 8.0, n_frames=346, sr=SR)
    assert not warnings
    assert [s.bar for s in spans] == [1, 2, 3, 4]
    assert spans[0].start_time == 0.0 and spans[0].end_time == 2.0
    assert spans[2].start_time == 4.0 and spans[2].end_time == 6.0
    # Final bar ends after four beats at the local median interval, clamped.
    assert spans[3].end_time == 8.0
    # Frame ranges are strictly increasing and track the audio clock.
    assert spans[0].start_frame == 0
    for first, second in zip(spans, spans[1:]):
        assert first.end_frame <= second.start_frame + 1
        assert first.start_frame < first.end_frame


def test_bar_spans_clamp_and_drop_terminal_fragment():
    beats = _beat_entries([i * 0.5 for i in range(13)])  # 4 downbeats, last at 6.0 s
    spans, warnings = build_bar_spans(beats, 6.4, n_frames=280, sr=SR)
    # The final downbeat at 6.0 s leaves only 0.4 s (< 1 beat): dropped.
    assert [s.bar for s in spans] == [1, 2, 3]
    assert any("terminal" in w for w in warnings)


def test_bar_spans_need_two_downbeats():
    spans, warnings = build_bar_spans(_beat_entries([0.0]), 4.0, n_frames=100, sr=SR)
    assert spans == []
    assert warnings


def test_bar_spans_renumber_noncontiguous_bars():
    beats = _beat_entries([i * 0.5 for i in range(8)])
    for beat in beats:  # simulate markers that skip bar numbers
        beat["bar"] = beat["bar"] * 2 - 1
    spans, warnings = build_bar_spans(beats, 4.0, n_frames=180, sr=SR)
    assert [s.bar for s in spans] == [1, 2]
    assert any("renumbered" in w for w in warnings)


# ------------------------------------------------------- robust normalize

def test_robust_normalize_constant_column_and_row_norms():
    matrix = np.array([
        [5.0, 1.0, 2.0],
        [5.0, 2.0, -1.0],
        [5.0, 3.0, 2.0],
        [5.0, 4.0, -1.0],
    ])
    normalized = robust_normalize(matrix)
    assert normalized.dtype == np.float32
    assert np.all(normalized[:, 0] == 0.0)  # constant column carries nothing
    norms = np.linalg.norm(normalized, axis=1)
    assert np.allclose(norms[norms > 0], 1.0, atol=1e-5)


def test_robust_normalize_clips_outliers():
    values = np.array([[0.0], [1.0], [2.0], [3.0], [1000.0]])
    normalized = robust_normalize(values)
    assert normalized.max() <= 4.0 + 1e-6


def test_robust_normalize_preserves_row_deviations():
    # Rows keep their deviation from the typical bar (no row is special-cased).
    normalized = robust_normalize(np.array([[0.0, 0.0], [1.0, 2.0], [3.0, 4.0]]))
    assert normalized.shape == (3, 2)
    assert np.all(np.isfinite(normalized))


# ---------------------------------------------------------------- extract

def test_extract_structure_features_shapes_and_determinism():
    audio, beats = _synth_song()
    energy = {
        "fps": 100.0,
        "start": 0.0,
        "bands": {
            "all": [0.5] * 800,
            "low": [0.4] * 800,
            "mid": [0.3] * 800,
            "high": [0.2] * 800,
        },
    }
    onsets = [{"id": i + 1, "raw_time": i * 0.5, "strength": 0.8, "bands": {"all": 0.8, "low": 0.5, "mid": 0.3, "high": 0.1}} for i in range(16)]

    first = extract_structure_features(audio, SR, beats, onsets, energy, 8.0, subdivision=16)
    second = extract_structure_features(audio, SR, beats, onsets, energy, 8.0, subdivision=16)

    assert len(first.bar_spans) == 4
    assert set(first.views) == {"harmony", "timbre", "rhythm", "energy"}
    for name, matrix in first.views.items():
        assert matrix.dtype == np.float32
        assert matrix.shape[0] == 4
        assert np.all(np.isfinite(matrix))
        norms = np.linalg.norm(matrix, axis=1)
        assert np.all((np.abs(norms - 1.0) < 1e-5) | (norms == 0.0)), name
    assert first.diagnostics["bars_analyzed"] == 4
    assert first.diagnostics["feature_version"] == "structure-features-v1"
    assert first.diagnostics["nonfinite_replaced"] == 0
    # Bit-identical across runs: the analysis must be deterministic.
    for name in first.views:
        assert np.array_equal(first.views[name], second.views[name]), name
    # The energy view must actually see the band curves.
    assert np.any(first.views["energy"] != 0.0)


def test_extract_structure_features_replaces_nonfinite():
    audio, beats = _synth_song(with_nan=True)
    features = extract_structure_features(audio, SR, beats, [], {}, 8.0)
    assert features.diagnostics["nonfinite_audio_samples"] == 10
    assert any("non-finite audio samples" in w for w in features.diagnostics["warnings"])
    for matrix in features.views.values():
        assert np.all(np.isfinite(matrix))


def test_extract_structure_features_chroma_fallback(monkeypatch):
    def _broken(*_args, **_kwargs):
        raise RuntimeError("CQT unavailable in this build")

    monkeypatch.setattr(librosa.feature, "chroma_cqt", _broken)
    audio, beats = _synth_song(bars=2)
    features = extract_structure_features(audio, SR, beats, [], {}, 4.0)
    assert any("chroma_stft" in w for w in features.diagnostics["warnings"])
    assert features.views["harmony"].shape[0] == 2


def test_extract_structure_features_without_downbeats():
    audio, _ = _synth_song()
    features = extract_structure_features(audio, SR, [], [], {}, 4.0)
    assert features.bar_spans == []
    assert all(matrix.shape[0] == 0 for matrix in features.views.values())
    assert features.diagnostics["bars_analyzed"] == 0


def test_bar_span_dataclass_layout():
    span = BarSpan(3, 4.0, 6.0, 176, 346)
    assert (span.bar, span.start_time, span.end_time, span.start_frame, span.end_frame) == (3, 4.0, 6.0, 176, 346)
