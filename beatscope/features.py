"""Multiband spectral energy, novelty curves, and transient detection."""
from __future__ import annotations

from typing import Any

import numpy as np

try:
    import librosa
except ImportError as exc:  # pragma: no cover
    # The import failing is the signal; _require_librosa() turns it into an error
    # at the call site, so a None module here is the intended shape.
    librosa = None  # type: ignore[assignment]
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


NOVELTY_VERSIONS = (1, 2)

# An absolute gate on the un-normalized per-bin flux. Normalizing first cannot
# work: it maps whatever the signal's own scale is onto 0..1, so white noise at
# an RMS of 1e-9 arrives looking like a full-scale event. Measured on Ballroom,
# the per-bin mean flux has a median around 3e-2 to 6e-2, and 7e-4 to 1.5e-3
# after attenuating the audio by 40 dB, against roughly 1e-9 for that noise - so
# 1e-6 refuses the noise with three orders of margin and keeps quiet music with
# two. It is a starting value for the development set to tune, not a measured
# optimum.
NOISE_FLOOR_PER_BIN = 1e-6


def band_flux(magnitudes: np.ndarray, *, version: int = 1) -> np.ndarray:
    """Positive novelty of one band from its magnitude spectrogram (bins x frames).

    version=1 averages the bins before differencing, which is the shipping
    statistic and the reason a change can cancel: one group of frequencies
    falling while another rises leaves the average where it was.
    version=2 differences each bin first and sums the positive part, so that
    change survives. Extracted as its own function because this is the whole
    difference between the two, and it is testable on a spectrum directly.
    """
    if version not in NOVELTY_VERSIONS:
        raise ValueError(f"unknown novelty version: {version}")
    if version == 1:
        energy = np.mean(magnitudes, axis=0)
        return np.maximum(0.0, np.diff(np.log1p(energy), prepend=energy[:1]))
    log_band = np.log1p(magnitudes)
    rise = np.maximum(0.0, np.diff(log_band, axis=1, prepend=log_band[:, :1]))
    # The mean per bin, not the sum: the value then means the same thing for a
    # narrow and a wide band, and it is on a scale a noise gate can use.
    return rise.mean(axis=0)


def compute_raw_band_novelty(
    y: np.ndarray,
    sr: int,
    hop: int = 256,
    n_fft: int = 2048,
    *,
    version: int = 1,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """The same bands as compute_multiband_novelty, before normalization.

    Kept separate because normalization destroys the scale a noise gate needs,
    and because a caller that wants the gate should have to hold the raw evidence
    rather than infer it from the normalized signal.
    """
    if len(y) == 0:
        empty = np.zeros(0, dtype=np.float32)
        return empty, {"all": empty, "low": empty, "mid": empty, "high": empty}
    lib = _require_librosa()
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
        raw_novelty[name] = (
            band_flux(spectrum[mask], version=version)
            if mask.any()
            else np.zeros(spectrum.shape[1], dtype=np.float32)
        )
    raw_novelty["all"] = raw_novelty["low"] + raw_novelty["mid"] + raw_novelty["high"]
    times = np.arange(len(raw_novelty["all"]), dtype=np.float32) * hop / sr
    return times, raw_novelty


def compute_multiband_novelty(
    y: np.ndarray,
    sr: int,
    hop: int = 256,
    n_fft: int = 2048,
    *,
    version: int = 1,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Compute normalized positive flux novelty across LOW, MID, HIGH, and ALL bands.

    version=1 averages each band's magnitudes before differencing; that is the
    shipping statistic. version=2 differences every frequency bin first and
    aggregates the positive part afterwards, so a change that cancels inside the
    band average - one group of frequencies falling while another rises - still
    shows up. The two return the same shape and both are normalized per band, so
    they are interchangeable for callers; v2 is not on the shipping path and is
    not claimed to score better on real music until the onset evaluation exists.
    """
    if version not in NOVELTY_VERSIONS:
        raise ValueError(f"unknown novelty version: {version}")
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
        raw_novelty[name] = (
            band_flux(spectrum[mask], version=version)
            if mask.any()
            else np.zeros(spectrum.shape[1], dtype=np.float32)
        )

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


def local_background_threshold(
    values: np.ndarray,
    *,
    window_frames: int = 64,
    spread_multiplier: float = 3.0,
    floor: float = 0.10,
) -> np.ndarray:
    """A per-frame threshold from the surrounding signal, not from the whole track.

    The shipping extractor thresholds against a whole-track percentile, so a loud
    passage raises the bar for a quiet one and a weak event there is never seen.
    This walks a sliding median and spread instead. The absolute floor stays:
    without it a quiet passage would be normalized into events that are not there.
    """
    if len(values) == 0:
        return np.zeros(0, dtype=np.float64)
    half = max(1, window_frames // 2)
    padded = np.pad(values.astype(np.float64), (half, half), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * half + 1)
    medians = np.median(windows, axis=1)
    spreads = np.median(np.abs(windows - medians[:, None]), axis=1)
    return np.maximum(floor, medians + spread_multiplier * spreads)


def peak_prominence(values: np.ndarray, frame: int, window: int) -> float:
    """Topographic prominence: how far the peak stands above its higher saddle.

    A median-plus-spread threshold fires on the tail of any distribution, noise
    included, because a ripple that is uniform still has a tail. Prominence asks a
    different question - does this peak rise above the ground on both sides of it
    - and a ripple's peaks do not.
    """
    low = max(0, frame - window)
    high = min(len(values), frame + window + 1)
    left = float(values[low:frame + 1].min()) if frame > low else float(values[frame])
    right = float(values[frame:high].min()) if high > frame + 1 else float(values[frame])
    return float(values[frame]) - max(left, right)


def prominent_candidates(values: np.ndarray, candidates: np.ndarray, *, window: int, ratio: float) -> np.ndarray:
    """Keep only the candidates that rise above their surroundings by ``ratio``.

    ``ratio`` is a fraction of the peak's own height, so it means the same thing
    for a loud event and a quiet one.
    """
    if ratio <= 0.0:
        return candidates
    kept = [
        int(index)
        for index in candidates
        if float(values[index]) > 0 and peak_prominence(values, int(index), window) >= ratio * float(values[index])
    ]
    return np.array(kept, dtype=int)


def resolve_close_candidates(
    values: np.ndarray,
    candidates: np.ndarray,
    *,
    min_distance_samples: int,
    valley_neighbourhood: int | None = None,
    valley_ratio: float = 0.55,
) -> np.ndarray:
    """Keep dense candidates only when something separates them.

    Two distances, because they answer different questions. Candidates closer
    than ``min_distance_samples`` are one event, always. Within
    ``valley_neighbourhood`` - the shipping spacing by default, so the valley
    rule applies wherever the shipping picker would have made a decision - the
    signal between them decides: a fall to ``valley_ratio`` of the weaker peak is
    a real gap and both stay, anything shallower is one attack with a ripple.

    Passing one distance for both, which is how this started, means the valley is
    only ever consulted for candidates inside the hard minimum - so a pair 35 ms
    apart sails through the distance check and is never examined.
    """
    neighbourhood = min_distance_samples if valley_neighbourhood is None else valley_neighbourhood
    chosen: list[int] = []
    for candidate in sorted((int(index) for index in candidates), key=lambda index: values[index], reverse=True):
        blocked = False
        for other in chosen:
            if abs(candidate - other) >= neighbourhood:
                continue
            low, high = sorted((candidate, other))
            valley = float(values[low:high + 1].min())
            weaker = min(float(values[candidate]), float(values[other]))
            if weaker > 0.0 and valley <= valley_ratio * weaker:
                continue
            blocked = True
            break
        if not blocked:
            chosen.append(candidate)
    return np.array(sorted(chosen), dtype=int)


def attack_start(values: np.ndarray, frame: int, *, floor: float, max_lookback: int = 64) -> int:
    """Walk back from a peak to where its rise began, bounded and floored.

    The peak marks where a band is loudest, not where the attack starts; this is
    the internal correspondence the plan keeps between the two times. It is not
    published as the onset time yet, because the localization has not been
    measured against real annotations.
    """
    start = int(frame)
    limit = max(0, start - max_lookback)
    while start > limit and floor < values[start - 1] <= values[start]:
        start -= 1
    return start


ONSET_VERSIONS = (1, 2)


def extract_onsets(
    times: np.ndarray,
    novelty: dict[str, np.ndarray],
    sr: int,
    hop: int = 256,
    bpm: float = 120.0,
    *,
    version: int = 1,
    raw_novelty: dict[str, np.ndarray] | None = None,
    local_threshold: bool = True,
    dense_candidates: bool = True,
    noise_gate: bool = True,
    valley_ratio: float = 0.55,
    prominence_ratio: float = 0.0,
) -> list[dict[str, Any]]:
    """Extract factual onsets with local window adaptive accent labeling.

    version=1 is the shipping extractor: one whole-track percentile threshold and
    a fixed 45 ms spacing, which drops the weaker of two hits that are closer than
    that. version=2 thresholds each frame against its local background and keeps
    dense candidates separated by a real gap, and records where each attack began
    next to the peak it was found from. v2 is experimental: it changes which
    events exist, and the onset evaluation has to measure that before it ships.
    """
    if version not in ONSET_VERSIONS:
        raise ValueError(f"unknown onset version: {version}")

    all_band = novelty.get("all", np.zeros(0, dtype=np.float32))
    if len(all_band) == 0 or len(times) == 0:
        return []

    min_dist_samples = max(1, int(round(0.045 * sr / hop)))
    if version == 1:
        threshold = max(0.10, float(np.percentile(all_band, 75)))
        peaks = detect_transient_peaks(all_band, min_dist_samples, threshold)
    else:
        raw = raw_novelty
        if raw is None:
            raise ValueError(
                "version 2 gates noise on the un-normalized flux; pass raw_novelty from "
                "compute_raw_band_novelty"
            )
        # The gate reads the raw flux, not the normalized one: normalization maps
        # any scale onto 0..1, so a noise floor applied after it would be a floor
        # on the shape rather than on the signal.
        audible = np.ones(len(all_band), dtype=bool)
        if noise_gate:
            audible = np.zeros(len(all_band), dtype=bool)
            for band in ("low", "mid", "high"):
                band_raw = np.asarray(raw.get(band, np.zeros(0)), dtype=np.float64)
                if len(band_raw) == len(audible):
                    audible |= band_raw >= NOISE_FLOOR_PER_BIN
        if local_threshold:
            thresholds = local_background_threshold(all_band)
        else:
            thresholds = np.full(len(all_band), max(0.10, float(np.percentile(all_band, 75))))
        if dense_candidates:
            inner = all_band[1:-1]
            candidates = np.where(
                audible[1:-1]
                & (inner >= thresholds[1:-1])
                & (inner >= all_band[:-2])
                & (inner > all_band[2:])
            )[0] + 1
            candidates = prominent_candidates(
                all_band, candidates, window=min_dist_samples, ratio=prominence_ratio
            )
            # The hard minimum is half the shipping spacing, but the valley rule
            # has to apply across the whole shipping spacing - that is the
            # neighbourhood the shipping picker decides in, and the pairs it
            # merges live there.
            peaks = resolve_close_candidates(
                all_band,
                candidates,
                min_distance_samples=max(1, min_dist_samples // 2),
                valley_neighbourhood=min_dist_samples,
                valley_ratio=valley_ratio,
            )
        else:
            # Exactly the shipping picker, so that switching the two flags off
            # reproduces v1 and the ablation isolates one mechanism at a time.
            peaks = detect_transient_peaks(all_band, min_dist_samples, float(thresholds[0]))
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
        entry = {
            "id": idx,
            "frame": frame,
            "raw_time": round(t, 4),
            "strength": round(str_val, 4),
            "bands": bands,
            "confidence": round(float(min(1.0, max(0.05, str_val))), 3),
        }
        if version == 2:
            # Internal only: the peak says where the band is loudest, not where
            # the attack starts. Published as raw_time until localization is
            # measured against real annotations.
            entry["refined_time"] = round(float(times[attack_start(all_band, frame, floor=0.10)]), 4)
        raw_onsets.append(entry)

    # Accent detection via local window percentile (85th percentile within +/- 4 bars)
    onsets = []
    for cur in raw_onsets:
        t = cur["raw_time"]
        local_strengths = [
            o["strength"] for o in raw_onsets if abs(o["raw_time"] - t) <= window_sec
        ]
        accent_thresh = float(np.percentile(local_strengths, 85)) if len(local_strengths) >= 4 else 0.72
        is_accent = bool(cur["strength"] >= max(0.60, accent_thresh))

        entry = {
            "id": cur["id"],
            "raw_time": cur["raw_time"],
            "strength": cur["strength"],
            "bands": cur["bands"],
            "accent": is_accent,
            "confidence": cur["confidence"],
        }
        if "refined_time" in cur:
            entry["refined_time"] = cur["refined_time"]
        onsets.append(entry)

    return onsets
