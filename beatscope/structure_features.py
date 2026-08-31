"""Bar-synchronous multi-view audio features for whole-song structure (v0.7).

The structure analyzer needs to know how one bar compares to every other bar
in four independent dimensions - harmony, timbre, rhythm, and energy. This
module turns decoded audio plus the beat grid into exactly that:

* real bar spans from consecutive downbeats (never a BPM-rebuilt grid);
* frame features (chroma / MFCC / contrast / RMS / onset envelope) at a fixed
  hop, aggregated per bar with robust summaries;
* the legacy 66-dim bar rhythm vector, kept as the rhythm view's backbone;
* absolute-level column scaling plus per-view L2, so one loud section cannot
  dominate cosine similarity while per-bar measurement noise stays
  proportional to each column's signal scale.

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

FEATURE_VERSION = "structure-features-v2"
STRUCTURE_HOP = 512
STRUCTURE_N_FFT = 2048
N_MFCC = 20
N_CHROMA = 12
N_CONTRAST = 7

# Absolute-level scaling floor: columns with median |x| at or below this
# carry no measurable signal and collapse to zero.
LEVEL_SCALE_FLOOR = 1e-9

# Fixed weight for the gain-invariant band-ratio dims of the energy view;
# kept small so they cannot drown the anchored log-level dim.
ENERGY_RATIO_WEIGHT = 0.12

# An onset marks only the energy bands whose level reaches this fraction of
# its strongest band, so a kick marks the low layer, a snare the mid/high
# layers, and sub-dominant leakage is dropped. Binary dominant-band
# occupancy is the pattern signal: raw step strengths make the cosine
# between bars measure loudness overlap instead of "which instrument hits
# which step", and uniform leakage above any absolute floor makes a
# kick-to-snare swap invisible.
RHYTHM_DOMINANT_BAND_RATIO = 0.5


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


def _median_over_span(block: np.ndarray, span: BarSpan) -> np.ndarray:
    """Per-feature median over one bar's frames.

    Medians only, deliberately: over ~86 frames the median averages
    measurement noise down, whereas spread summaries (MAD, percentiles,
    first-to-last delta) sit at the noise floor on sustained content - and
    any per-column rescaling then amplifies that noise until same-section
    bars decorrelate under cosine similarity.
    """
    start = min(span.start_frame, block.shape[1] - 1)
    end = max(start + 1, min(span.end_frame, block.shape[1]))
    frames = block[:, start:end]
    if frames.shape[1] == 0:  # unreachable with the clamps above, kept safe
        return np.zeros(block.shape[0], dtype=np.float64)
    return np.median(frames, axis=1)


def level_normalize(matrix: np.ndarray) -> np.ndarray:
    """Scale each column by its typical absolute level, then L2 each row.

    Deliberately NOT variance-based (no centring, no MAD z-scores): on a
    near-constant column the MAD *is* the per-bar measurement noise, so
    dividing by it amplifies wobble ~1e-3 of the signal to unit magnitude
    and identical-section bars decorrelate into random directions under
    cosine similarity. Centring is equally destructive - it subtracts the
    shared signal first, leaving only that noise for the row L2 to inflate.
    Dividing by an absolute level reference (median |x|) keeps every
    contribution proportional to its column's signal scale instead: real
    cross-bar changes survive, noise stays small. Columns whose absolute
    level is zero carry nothing and collapse to zero. Only for continuous
    per-bar summaries; sparse occupancy vectors (the rhythm view) use
    :func:`l2_normalize_rows` instead - most step columns are zero in the
    majority of bars, so their level is zero and they would be deleted
    exactly where they distinguish sections.
    """
    values = np.nan_to_num(
        np.asarray(matrix, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0
    )
    if values.size == 0:
        return np.zeros_like(values, dtype=np.float32)
    level = np.median(np.abs(values), axis=0)
    safe = level > LEVEL_SCALE_FLOOR
    normalized = np.zeros_like(values)
    normalized[:, safe] = values[:, safe] / level[safe]
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


def _energy_rows(rms_medians: np.ndarray, band_means: np.ndarray) -> np.ndarray:
    """Song-anchored log level plus fixed-weight spectral-balance ratios.

    Cosine similarity is scale-invariant, so a view built purely from
    amplitude-like columns cannot see a uniform gain change: every column
    scales together and the rows stay parallel. Anchoring the level at the
    song's own median rms breaks that invariance - a section at half gain
    sits ~0.7 away from the typical level while a typical bar sits at 0, so
    same-level bars keep cosine ~1 while level changes become visible. The
    low/mid/high-over-all band ratios are gain-invariant spectral-balance
    context and ride along at a fixed small weight so they cannot drown the
    anchor. The anchor is clipped so digitally silent bars stay outliers
    instead of unbounded ones.
    """
    reference = max(float(np.median(rms_medians)), 1e-6)
    anchor = np.log(np.maximum(rms_medians, 1e-6) / reference)
    anchor = np.clip(anchor, -4.0, 4.0)
    total = np.maximum(band_means[:, 0], 1e-9)
    has_signal = band_means[:, 0] > 1e-9
    rows = np.zeros((band_means.shape[0], 4), dtype=np.float64)
    rows[:, 0] = anchor
    for column in (1, 2, 3):
        rows[:, column] = ENERGY_RATIO_WEIGHT * np.where(
            has_signal, band_means[:, column] / total, 0.0
        )
    return rows


# ------------------------------------------------------------- rhythm view

def _rhythm_base_rows(
    onsets: list[dict[str, Any]],
    beats: list[dict[str, Any]],
    spans: list[BarSpan],
    subdivision: int,
    onset_env: np.ndarray,
    sr: int,
) -> np.ndarray:
    """Dominant-band step occupancy per bar, plus density and onset level.

    The rhythm view owns pattern identity. Each onset is reduced to the
    energy bands that dominate it (>= RHYTHM_DOMINANT_BAND_RATIO of its
    strongest band) and marks those layers' step: a kick fills only the low
    layer, a snare the mid/high layers, and leakage levels are dropped, so
    a kick-to-snare role swap is a large change in two layers instead of a
    4-of-64-step wobble. The same material at a different tempo reproduces
    the same bar-synced grid exactly. Layout: low/mid/high step layers
    (3 x subdivision), hit count, onset-envelope median.
    """
    band_names = ("low", "mid", "high")
    width = len(band_names) * subdivision
    bar_onsets: dict[int, list[dict[str, Any]]] = {span.bar: [] for span in spans}
    if beats:
        for onset in onsets:
            try:
                raw = float(onset.get("raw_time", onset.get("time")))
                placed = quantize_to_beat_grid(raw, beats, subdivision=subdivision)
            except (KeyError, TypeError, ValueError):
                continue
            bar_onsets.setdefault(placed["bar"], [])
            if placed["bar"] in bar_onsets:
                bar_onsets[placed["bar"]].append({**onset, **placed})

    rows = np.zeros((len(spans), width + 2), dtype=np.float64)
    for index, span in enumerate(spans):
        hits = bar_onsets.get(span.bar, [])
        rows[index, width] = float(min(1.0, len(hits) / 16.0))
        for onset in hits:
            step = int(onset.get("step_in_bar", 1)) - 1
            if not 0 <= step < subdivision:
                continue
            values = onset.get("bands") if isinstance(onset.get("bands"), dict) else {}
            band_levels = [
                float((values or {}).get(name, 0.0) or 0.0) for name in band_names
            ]
            peak = max(band_levels)
            if peak <= 1e-6:
                band_levels = [1.0, 1.0, 1.0]  # bandless hit: treat as broadband
            else:
                band_levels = [
                    1.0 if level >= RHYTHM_DOMINANT_BAND_RATIO * peak else 0.0
                    for level in band_levels
                ]
            for band, marked in enumerate(band_levels):
                if marked:
                    rows[index, band * subdivision + step] = 1.0
        start = min(span.start_frame, onset_env.shape[1] - 1)
        end = max(start + 1, min(span.end_frame, onset_env.shape[1]))
        frames = onset_env[0, start:end]
        if frames.size:
            rows[index, width + 1] = float(np.median(frames))
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
        "harmony": np.zeros((0, N_CHROMA), dtype=np.float32),
        "timbre": np.zeros((0, N_MFCC - 1 + N_CONTRAST), dtype=np.float32),
        "rhythm": np.zeros((0, 3 * 16 + 2), dtype=np.float32),
        "energy": np.zeros((0, 4), dtype=np.float32),
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
    # MFCC c0 is a log-energy offset (~-500 on typical audio) that dwarfs the
    # shape coefficients and is gain-blind after level scaling anyway; the
    # energy view owns level. Timbre keeps c1.. only.
    timbre = np.concatenate([frames["mfcc"][1:], frames["contrast"]], axis=0)

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

    # Harmony: chroma medians only, no column scaling - every column shares
    # the same 0-1 unit and chord bins dominate leakage bins on their own.
    harmony_raw = np.stack([_median_over_span(chroma, span) for span in spans])
    timbre_raw = np.stack([_median_over_span(timbre, span) for span in spans])
    rms_medians = np.stack([_median_over_span(rms, span) for span in spans])[:, 0]
    rhythm_raw = _clean(_rhythm_base_rows(onsets, beats, spans, subdivision, onset_env, sr))

    views = {
        "harmony": l2_normalize_rows(harmony_raw),
        "timbre": level_normalize(timbre_raw),
        "rhythm": l2_normalize_rows(rhythm_raw),
        "energy": l2_normalize_rows(_energy_rows(rms_medians, band_means)),
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
    "level_normalize",
]
