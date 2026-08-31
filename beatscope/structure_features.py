"""Bar-synchronous multi-view audio features for whole-song structure (v0.7).

The structure analyzer needs to know how one bar compares to every other bar
in four independent dimensions - harmony, timbre, rhythm, and energy. This
module turns decoded audio plus the beat grid into exactly that:

* real bar spans from consecutive downbeats (never a BPM-rebuilt grid);
* frame features (chroma / MFCC / contrast / RMS / onset envelope) at a fixed
  hop, aggregated per bar with robust summaries;
* the legacy 66-dim bar rhythm vector, kept as the rhythm view's backbone;
* robust cross-bar normalization (median centre, 1.4826*MAD scale, clipped
  to +/-4) and per-view L2, so one loud section cannot dominate cosine
  similarity.

Determinism contract: no RNG, no wall-clock input; float32 only after all
aggregation; non-finite values are replaced by 0 and counted in diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

try:
    import librosa
except ImportError as exc:  # pragma: no cover - librosa is a hard dependency
    raise RuntimeError("beatscope.structure_features requires librosa") from exc

from .beatgrid import quantize_to_beat_grid
from .structure import build_bar_vector

FEATURE_VERSION = "structure-features-v1"
STRUCTURE_HOP = 512
STRUCTURE_N_FFT = 2048
N_MFCC = 20
N_CHROMA = 12
N_CONTRAST = 7

# Robust normalization: deviations beyond this many robust sigmas are clipped.
ROBUST_CLIP = 4.0
MAD_TO_SIGMA = 1.4826

# Summary statistic layout per base feature: median, MAD, p25, p75, delta.
SUMMARY_WIDTH = 5


@dataclass(frozen=True)
class BarSpan:
    """One bar's real extent in seconds and feature frames (end exclusive)."""

    bar: int
    start_time: float
    end_time: float
    start_frame: int
    end_frame: int


@dataclass
class StructureFeatures:
    """Per-bar view matrices plus extraction diagnostics."""

    bar_spans: list[BarSpan]
    views: dict[str, np.ndarray]  # view name -> B x D float32, normalized
    diagnostics: dict[str, Any]


def _quantize_time(value: float) -> float:
    return round(float(value), 6)


# ------------------------------------------------------------- bar spans

def build_bar_spans(
    beats: list[dict[str, Any]],
    duration: float,
    n_frames: int,
    sr: int,
    hop: int = STRUCTURE_HOP,
) -> tuple[list[BarSpan], list[str]]:
    """Real bar spans from consecutive downbeats.

    The final bar has no following downbeat, so it ends after four beats at
    the local median beat interval, clamped to the duration. A terminal
    fragment shorter than one beat is dropped from clustering entirely.
    """
    warnings: list[str] = []
    downbeats = sorted(
        (int(b.get("bar") or 0), _quantize_time(b["time"]))
        for b in beats
        if b.get("downbeat")
    )
    if len(downbeats) < 2:
        return [], ["Fewer than two downbeats; no bar spans for structure analysis"]

    # Keep marker bar numbers when they run contiguously from 1; otherwise
    # renumber by sequence so segment ranges always align with the bars list.
    numbers = [bar for bar, _ in downbeats]
    if numbers != list(range(1, len(numbers) + 1)):
        warnings.append("Downbeat bar numbers were not contiguous; renumbered by sequence")
        numbers = list(range(1, len(numbers) + 1))

    beat_times = sorted(_quantize_time(b["time"]) for b in beats)
    intervals = np.diff(np.asarray(beat_times, dtype=np.float64))
    intervals = intervals[(intervals > 1e-4)]
    local_beat = float(np.median(intervals[-8:])) if len(intervals) else 0.5

    spans: list[BarSpan] = []
    for index in range(len(downbeats)):
        bar = numbers[index]
        start = downbeats[index][1]
        if index + 1 < len(downbeats):
            end = downbeats[index + 1][1]
        else:
            end = start + 4.0 * local_beat
        start = max(0.0, min(start, _quantize_time(duration)))
        end = max(start, min(end, _quantize_time(duration)))
        if end - start < local_beat * 0.5:
            continue  # zero-length clamp artifact at the very end
        if end - start < local_beat and index == len(downbeats) - 1:
            warnings.append("Dropped terminal bar fragment shorter than one beat")
            continue
        start_frame = int(np.floor(start * sr / hop))
        end_frame = int(np.ceil(end * sr / hop))
        start_frame = max(0, min(start_frame, n_frames - 1)) if n_frames else 0
        end_frame = max(start_frame + 1, min(end_frame, n_frames)) if n_frames else start_frame + 1
        spans.append(BarSpan(bar, start, end, start_frame, end_frame))

    if not spans:
        warnings.append("No usable bar spans for structure analysis")
    return spans, warnings


# ------------------------------------------------------- frame features

def _frame_features(audio: np.ndarray, sr: int) -> tuple[dict[str, np.ndarray], list[str]]:
    warnings: list[str] = []
    hop, n_fft = STRUCTURE_HOP, STRUCTURE_N_FFT
    features: dict[str, np.ndarray] = {}
    # Harmony must come from pitched content: harmonic/percussive separation
    # keeps kick and snare transients out of the chroma medians.
    harmonic = librosa.effects.harmonic(y=audio, margin=2.0)
    try:
        features["chroma"] = librosa.feature.chroma_cqt(y=harmonic, sr=sr, hop_length=hop)
    except Exception:
        # CQT needs a minimum signal length/bandwidth; STFT chroma is the
        # documented fallback and the downgrade is recorded, never silent.
        warnings.append("chroma_cqt failed; fell back to chroma_stft")
        features["chroma"] = librosa.feature.chroma_stft(y=harmonic, sr=sr, hop_length=hop, n_fft=n_fft)
    features["mfcc"] = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=N_MFCC, hop_length=hop, n_fft=n_fft)
    features["contrast"] = librosa.feature.spectral_contrast(y=audio, sr=sr, hop_length=hop, n_fft=n_fft)
    features["rms"] = librosa.feature.rms(y=audio, hop_length=hop, frame_length=n_fft)
    features["onset_env"] = librosa.onset.onset_strength(y=audio, sr=sr, hop_length=hop, n_fft=n_fft)

    frame_count = int(features["rms"].shape[1])
    aligned: dict[str, np.ndarray] = {}
    for name, matrix in features.items():
        values = np.atleast_2d(np.asarray(matrix, dtype=np.float64))
        if values.shape[1] < frame_count:
            pad = np.full((values.shape[0], frame_count - values.shape[1]), values[:, -1:].mean())
            values = np.concatenate([values, pad], axis=1)
        aligned[name] = values[:, :frame_count]
    return aligned, warnings


def _summarize_block(block: np.ndarray, span: BarSpan) -> np.ndarray:
    """Robust summaries of one base feature block over one bar's frames."""
    start = min(span.start_frame, block.shape[1] - 1)
    end = max(start + 1, min(span.end_frame, block.shape[1]))
    frames = block[:, start:end]
    if frames.shape[1] == 0:  # unreachable with the clamps above, kept safe
        return np.zeros(block.shape[0] * SUMMARY_WIDTH, dtype=np.float64)
    median = np.median(frames, axis=1)
    mad = np.median(np.abs(frames - median[:, None]), axis=1)
    p25 = np.percentile(frames, 25, axis=1)
    p75 = np.percentile(frames, 75, axis=1)
    delta = frames[:, -1] - frames[:, 0]
    return np.concatenate([median, mad, p25, p75, delta]).astype(np.float64)


def robust_normalize(matrix: np.ndarray) -> np.ndarray:
    """Mean-centre, MAD-scale, clip to +/-4, then L2-normalize each row.

    The centring reference is the mean even though the scale is the robust
    1.4826*MAD: with median centring, whichever section forms the majority
    sits exactly at zero and its bars lose their shared deviation, leaving
    per-bar measurement noise as the only direction - same-section bars then
    decorrelate under cosine similarity. Mean centring keeps every cluster's
    shared offset alive, the MAD scale still ignores outlier bars, and the
    +/-4 clip bounds any single wild bar.

    Columns that never vary across bars carry no structure information and
    collapse to zero. Only for continuous per-bar summaries; sparse occupancy
    vectors (the rhythm view) must use :func:`l2_normalize_rows` instead -
    most step columns are zero in the majority of bars, so their MAD is zero
    and centring would delete exactly the dimensions that distinguish
    sections.
    """
    values = np.asarray(matrix, dtype=np.float64)
    if values.size == 0:
        return np.zeros_like(values, dtype=np.float32)
    centre = values.mean(axis=0)
    mad = np.median(np.abs(values - np.median(values, axis=0)), axis=0)
    scale = MAD_TO_SIGMA * mad
    safe = scale > 1e-9
    normalized = np.zeros_like(values)
    normalized[:, safe] = (values[:, safe] - centre[safe]) / scale[safe]
    normalized = np.clip(normalized, -ROBUST_CLIP, ROBUST_CLIP)
    norms = np.linalg.norm(normalized, axis=1)
    nonzero = norms > 1e-9
    normalized[nonzero] /= norms[nonzero][:, None]
    return normalized.astype(np.float32)


def l2_normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """Scale-invariant row normalization without any centring.

    Used for the rhythm view: the legacy bar vector already encodes level in
    its magnitudes, and L2 keeps only the occupancy pattern's direction.
    """
    values = np.asarray(matrix, dtype=np.float64)
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    norms = np.linalg.norm(values, axis=1)
    nonzero = norms > 1e-9
    values[nonzero] /= norms[nonzero][:, None]
    return values.astype(np.float32)


# ------------------------------------------------------------ energy bands

def _band_means_per_bar(
    energy: dict[str, Any], spans: list[BarSpan]
) -> np.ndarray:
    """Per-bar mean of the four stored energy-band curves (all/low/mid/high)."""
    bands = (energy or {}).get("bands") if isinstance(energy, dict) else None
    fps = float((energy or {}).get("fps") or 0.0) if isinstance(energy, dict) else 0.0
    names = ("all", "low", "mid", "high")
    out = np.zeros((len(spans), len(names)), dtype=np.float64)
    if not isinstance(bands, dict) or fps <= 0:
        return out
    curves = []
    for name in names:
        values = bands.get(name)
        curves.append(
            np.asarray(values, dtype=np.float64) if isinstance(values, list) else None
        )
    for index, span in enumerate(spans):
        for column, curve in enumerate(curves):
            if curve is None or curve.size == 0:
                continue
            first = max(0, int(np.floor(span.start_time * fps)))
            last = min(curve.size, max(first + 1, int(np.ceil(span.end_time * fps))))
            out[index, column] = float(np.mean(curve[first:last]))
    return out


# ------------------------------------------------------------- rhythm view

def _rhythm_base_rows(
    onsets: list[dict[str, Any]],
    beats: list[dict[str, Any]],
    spans: list[BarSpan],
    subdivision: int,
    onset_env: np.ndarray,
    sr: int,
) -> np.ndarray:
    """Legacy 66-dim bar vector plus onset-envelope summaries per bar."""
    bar_onsets: dict[int, list[dict[str, Any]]] = {span.bar: [] for span in spans}
    if beats:
        for onset in onsets:
            try:
                placed = quantize_to_beat_grid(float(onset["raw_time"]), beats, subdivision=subdivision)
            except (KeyError, TypeError, ValueError):
                continue
            bar_onsets.setdefault(placed["bar"], [])
            if placed["bar"] in bar_onsets:
                bar_onsets[placed["bar"]].append({**onset, **placed})

    rows = np.zeros((len(spans), 66 + SUMMARY_WIDTH), dtype=np.float64)
    for index, span in enumerate(spans):
        vector = build_bar_vector(bar_onsets.get(span.bar, []), subdivision)
        rows[index, :66] = vector
        start = min(span.start_frame, onset_env.shape[1] - 1)
        end = max(start + 1, min(span.end_frame, onset_env.shape[1]))
        frames = onset_env[0, start:end]
        if frames.size:
            median = float(np.median(frames))
            rows[index, 66] = median
            rows[index, 67] = float(np.median(np.abs(frames - median)))
            rows[index, 68] = float(np.percentile(frames, 25))
            rows[index, 69] = float(np.percentile(frames, 75))
            rows[index, 70] = float(frames[-1] - frames[0])
    return rows


# ---------------------------------------------------------------- extract

def extract_structure_features(
    audio: np.ndarray,
    sr: int,
    beats: list[dict[str, Any]],
    onsets: list[dict[str, Any]],
    energy: dict[str, Any],
    duration: float,
    subdivision: int = 16,
) -> StructureFeatures:
    """Extract the four per-bar view matrices from decoded audio."""
    warnings: list[str] = []
    audio = np.asarray(audio, dtype=np.float32)
    # librosa refuses non-finite input outright, so sanitize once here and
    # record how many samples were replaced instead of crashing mid-analysis.
    bad_samples = int(np.count_nonzero(~np.isfinite(audio))) if audio.size else 0
    if bad_samples:
        audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
        warnings.append(f"Replaced {bad_samples} non-finite audio samples with 0")

    probe = librosa.feature.rms(y=audio, hop_length=STRUCTURE_HOP, frame_length=STRUCTURE_N_FFT)
    n_frames = int(probe.shape[1])
    spans, span_warnings = build_bar_spans(beats, duration, n_frames, sr, STRUCTURE_HOP)
    warnings.extend(span_warnings)

    empty_views = {
        "harmony": np.zeros((0, N_CHROMA * SUMMARY_WIDTH), dtype=np.float32),
        "timbre": np.zeros((0, (N_MFCC + N_CONTRAST) * SUMMARY_WIDTH), dtype=np.float32),
        "rhythm": np.zeros((0, 66 + SUMMARY_WIDTH), dtype=np.float32),
        "energy": np.zeros((0, SUMMARY_WIDTH + 4), dtype=np.float32),
    }
    if not spans:
        return StructureFeatures([], dict(empty_views), {
            "feature_version": FEATURE_VERSION,
            "frames": n_frames,
            "bars_analyzed": 0,
            "nonfinite_audio_samples": bad_samples,
            "nonfinite_replaced": 0,
            "warnings": warnings,
        })

    frames, frame_warnings = _frame_features(audio, sr)
    warnings.extend(frame_warnings)

    chroma = frames["chroma"]
    if chroma.shape[0] != N_CHROMA:
        warnings.append(f"chroma width {chroma.shape[0]} != {N_CHROMA}; harmonized")
    timbre = np.concatenate([frames["mfcc"], frames["contrast"]], axis=0)

    nonfinite = 0

    def _clean(matrix: np.ndarray) -> np.ndarray:
        nonlocal nonfinite
        values = np.asarray(matrix, dtype=np.float64)
        bad = int(np.count_nonzero(~np.isfinite(values)))
        nonfinite += bad
        if bad:
            values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
        return values

    chroma = _clean(chroma)
    timbre = _clean(timbre)
    rms = _clean(frames["rms"])
    onset_env = _clean(frames["onset_env"])
    band_means = _clean(_band_means_per_bar(energy, spans))

    harmony_raw = np.stack([_summarize_block(chroma, span) for span in spans])
    timbre_raw = np.stack([_summarize_block(timbre, span) for span in spans])
    energy_raw = np.concatenate(
        [np.stack([_summarize_block(rms, span) for span in spans]), band_means],
        axis=1,
    )
    rhythm_raw = _clean(_rhythm_base_rows(onsets, beats, spans, subdivision, onset_env, sr))

    views = {
        "harmony": robust_normalize(harmony_raw),
        "timbre": robust_normalize(timbre_raw),
        "rhythm": l2_normalize_rows(rhythm_raw),
        "energy": robust_normalize(energy_raw),
    }

    diagnostics = {
        "feature_version": FEATURE_VERSION,
        "frames": n_frames,
        "bars_analyzed": len(spans),
        "view_dims": {name: int(matrix.shape[1]) for name, matrix in views.items()},
        "nonfinite_audio_samples": bad_samples,
        "nonfinite_replaced": nonfinite,
        "warnings": warnings,
    }
    return StructureFeatures(spans, views, diagnostics)


__all__ = [
    "BarSpan",
    "FEATURE_VERSION",
    "STRUCTURE_HOP",
    "STRUCTURE_N_FFT",
    "StructureFeatures",
    "build_bar_spans",
    "extract_structure_features",
    "l2_normalize_rows",
    "robust_normalize",
]
