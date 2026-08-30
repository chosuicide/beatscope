"""Variable-tempo tracking: local candidates, global path, beat reconstruction.

Implements the v0.6 tempo-tracking plan (sections 10-15) as one pipeline:

    build_local_tempo_candidates()   windowed normalized autocorrelation
    select_tempo_path()              log-BPM Viterbi + octave suppression
    interpolate_period_guide()       per-frame period guide
    dynamic_programming_beats()      beat phase under the guide
    align_beats_to_onsets()          bounded snap to novelty peaks
    repair_beat_continuity()         duplicate / missing beat repair
    build_tempo_segments_from_beats()  piecewise-constant tempo segments
    track_tempo_and_beats()          the orchestrating entry point

Internal contracts (plan section 7):
- frame indices are integers; frame -> seconds is ``frame * hop / sr``;
- internal math runs in float64 and only the Rhythm IR writer rounds;
- every tie-break is explicit; nothing relies on set/dict order.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

# Plan section 7 constants. Initial values are informed guesses; the
# benchmark (sections 20/21) is the arbiter, and no fixture-specific
# branching is allowed.
MIN_BPM = 50.0
MAX_BPM = 220.0
TEMPO_WINDOW_SECONDS = 6.0
TEMPO_HOP_SECONDS = 0.5
TEMPO_CANDIDATES_PER_WINDOW = 5
MIN_SEGMENT_BEATS = 4
SNAP_LIMIT_SECONDS = 0.070

EPSILON = 1e-9
# Weak global-prior pull on the first anchor. Tuned against the benchmark:
# subdivision-only fixtures (dense-128, sparse-100) present a harmonic comb
# of near-equal autocorrelation peaks, and the accumulated per-window
# emission noise outweighs a 0.35-weighted tilt, so 2.0 restores the
# metrical decision without constraining variable-tempo paths (the prior
# cost is paid once, not per anchor).
PRIOR_WEIGHT = 2.0
BASE_LAMBDA = 0.6
# Tempo deltas below this (in log2) are ordinary drift (Huber quadratic
# region); above it they linearly approach the change-point cost.
TEMPO_DRIFT_SCALE = 0.06
# Penalizes transitions whose ratio sits within this distance of an octave.
OCTAVE_SWITCH_BAND = 0.08
OCTAVE_SWITCH_PENALTY = 1.5
# Hard safety cap between adjacent 0.5 s anchors (~1.75x). This only
# excludes octave catastrophes; real tempo steps stay far below it.
MAX_ANCHOR_JUMP_LOG2 = math.log2(1.75)
# A change becomes "observed" past this log2 delta and is fully trusted at
# CHANGE_FULL_DELTA; support counts anchors that agree with the medians.
CHANGE_ONSET_DELTA = 0.025
CHANGE_FULL_DELTA = 0.12
CHANGE_AGREEMENT_BAND = 0.06
CHANGE_SUPPORT_ANCHORS = 2.0

# Beat DP (section 12): how strongly a beat interval is pulled toward the
# local period guide, and how far from the guide a lag is still acceptable.
TIGHTNESS = 55.0
DP_LAG_MIN_RATIO = 0.67
DP_LAG_MAX_RATIO = 1.50
# Fraction of frames with above-median novelty needed to claim rhythm at all.
MIN_NOVELTY_SUPPORT = 0.02
# Phase anchoring (section 12.4, benchmark-tuned): on subdivision-only
# material every sub-pulse phase is equally supported, so the beat phase is
# ambiguous modulo the pulse period. v0.5 resolved this by anchoring its
# uniform grid on the first detected onset; the DP keeps that convention by
# giving the chain a one-beat bonus for passing through the first strong
# onset. Rhythmically implausible anchors (pickups far off the grid) are
# rejected by the tightness cost, which dwarfs a one-beat bonus.
FIRST_ONSET_ANCHOR_RATIO = 0.4
FIRST_ONSET_ANCHOR_BONUS = 1.0

# Onset alignment (section 13) and continuity repair (section 14).
SNAP_RADIUS_PERIOD_RATIO = 0.15
DUPLICATE_RATIO = 0.55
MISSING_MIN_RATIO = 1.65
MISSING_MAX_RATIO = 2.35
MISSING_GUIDE_BAND = 0.06
MISSING_SNAP_PERIOD_RATIO = 0.10
SUPPORT_WINDOW_FRAMES = 2

# Piecewise segmentation (section 15).
SEGMENT_SCALE = 0.05
SEGMENT_BOUNDARY_PENALTY = 1.5
SEGMENT_BOUNDARY_RELAX = 0.8
SEGMENT_MERGE_LOG2 = 0.02
MAX_SEGMENT_INTERVALS = 256
GLOBAL_BPM_TRIM_LOG2 = math.log2(1.5)

# Compact, JSON-safe algorithm configuration recorded in diagnostics. Keep
# this in one place so provenance cannot drift away from the constants that
# actually governed an analysis run.
TRACKING_PARAMETERS = {
    "min_bpm": MIN_BPM,
    "max_bpm": MAX_BPM,
    "tempo_window_seconds": TEMPO_WINDOW_SECONDS,
    "tempo_hop_seconds": TEMPO_HOP_SECONDS,
    "candidates_per_window": TEMPO_CANDIDATES_PER_WINDOW,
    "min_segment_beats": MIN_SEGMENT_BEATS,
    "snap_limit_seconds": SNAP_LIMIT_SECONDS,
    "tempo_drift_scale_log2": TEMPO_DRIFT_SCALE,
    "octave_switch_penalty": OCTAVE_SWITCH_PENALTY,
    "beat_dp_tightness": TIGHTNESS,
    "beat_lag_ratio": [DP_LAG_MIN_RATIO, DP_LAG_MAX_RATIO],
}

_CANDIDATE_ORIGIN_RANK = {"peak": 0, "octave-2x": 1, "octave-0.5x": 1, "fallback": 2}


@dataclass(frozen=True)
class TempoCandidate:
    """One plausible local tempo at one anchor frame (plan section 7)."""

    anchor_frame: int
    bpm: float
    period_frames: float
    emission_score: float
    origin: str = "peak"  # "peak" | "octave-2x" | "octave-0.5x" | "fallback"


@dataclass(frozen=True)
class TempoPath:
    """The selected per-anchor tempo path (plan section 7)."""

    anchor_frames: np.ndarray
    bpms: np.ndarray
    emission_scores: np.ndarray
    change_scores: np.ndarray


def huber(x: float, delta: float = 1.0) -> float:
    """Huber loss: quadratic below ``delta``, linear beyond (plan section 11.2)."""
    ax = abs(x)
    if ax <= delta:
        return 0.5 * ax * ax
    return delta * (ax - 0.5 * delta)


def _huber_array(values: np.ndarray, delta: float = 1.0) -> np.ndarray:
    """Vectorized Huber loss for segmentation fits (same shape as ``huber``)."""
    ax = np.abs(np.asarray(values, dtype=np.float64))
    return np.where(ax <= delta, 0.5 * ax * ax, delta * (ax - 0.5 * delta))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _window_bounds(novelty_length: int, anchor_frame: int, window_frames: int) -> tuple[int, int]:
    """Center a window on the anchor and truncate at the signal boundaries."""
    start = max(0, anchor_frame - window_frames // 2)
    end = min(novelty_length, start + window_frames)
    return start, end


def _autocorrelation_scores(
    x: np.ndarray, min_lag: int, max_lag: int
) -> tuple[np.ndarray, np.ndarray]:
    """Normalized autocorrelation for every lag in [min_lag, max_lag].

    ``score(lag) = dot(x[:-lag], x[lag:]) / (|x[:-lag]| * |x[lag:]|)``, i.e. a
    cosine, so the value stays in [-1, 1] regardless of window length.
    """
    lags = np.arange(min_lag, max_lag + 1)
    correlation = np.correlate(x, x, mode="full")[len(x) - 1:]
    squared = np.concatenate(([0.0], np.cumsum(x * x)))
    total = squared[-1]
    left_energy = squared[len(x) - lags]      # sum of x^2 over x[:len-lag]
    right_energy = total - squared[lags]      # sum of x^2 over x[lag:]
    denom = np.sqrt(left_energy * right_energy) + EPSILON
    return lags, correlation[lags] / denom


def _prior_distance(bpm: float, prior_bpm: float) -> float:
    return abs(math.log2(bpm / prior_bpm))


def _dedupe_candidates(
    candidates: list[TempoCandidate], prior_bpm: float
) -> list[TempoCandidate]:
    """Collapse candidates that share a BPM: higher score wins, then origin
    rank (a measured peak beats an octave variant), then prior distance."""
    by_bpm: dict[int, TempoCandidate] = {}
    for cand in candidates:
        key = round(cand.bpm, 6)
        bucket = by_bpm.get(key)
        if bucket is None:
            by_bpm[key] = cand
            continue
        challenger = (
            cand.emission_score,
            -_CANDIDATE_ORIGIN_RANK.get(cand.origin, 3),
            -_prior_distance(cand.bpm, prior_bpm),
        )
        incumbent = (
            bucket.emission_score,
            -_CANDIDATE_ORIGIN_RANK.get(bucket.origin, 3),
            -_prior_distance(bucket.bpm, prior_bpm),
        )
        if challenger > incumbent:
            by_bpm[key] = cand
    return [by_bpm[key] for key in sorted(by_bpm)]


def build_local_tempo_candidates(
    novelty: np.ndarray,
    sample_rate: int,
    hop_length: int,
    *,
    global_prior_bpm: float | None,
) -> list[list[TempoCandidate]]:
    """Windowed local tempo candidates per anchor frame (plan section 10).

    The input must be ``novelty["all"]`` from the feature stage; this function
    never recomputes an STFT. Windows are centered on anchors spaced
    ``TEMPO_HOP_SECONDS`` apart and truncated (never padded) at the edges.
    """
    fps = sample_rate / hop_length
    prior_bpm = float(global_prior_bpm) if global_prior_bpm else 120.0
    novelty_length = len(novelty)
    window_frames = int(round(TEMPO_WINDOW_SECONDS * fps))
    hop_frames = max(1, int(round(TEMPO_HOP_SECONDS * fps)))
    min_lag = int(math.ceil(fps * 60.0 / MAX_BPM))
    max_lag = int(math.floor(fps * 60.0 / MIN_BPM))

    windows: list[list[TempoCandidate]] = []
    previous_non_empty: list[TempoCandidate] | None = None
    for anchor in range(0, max(novelty_length, 1), hop_frames):
        start, end = _window_bounds(novelty_length, anchor, window_frames)
        if end - start <= max_lag:
            # Window too short for the lag range: reuse the nearest usable
            # window, or fall back to the prior when there is none yet.
            if previous_non_empty is not None:
                windows.append([
                    TempoCandidate(anchor, c.bpm, c.period_frames, c.emission_score, c.origin)
                    for c in previous_non_empty
                ])
            else:
                windows.append([TempoCandidate(
                    anchor, prior_bpm, fps * 60.0 / prior_bpm, 0.0, "fallback",
                )])
            continue

        x = novelty[start:end].astype(np.float64)
        x = x - np.mean(x)
        if float(np.linalg.norm(x)) <= EPSILON or not np.any(x != 0.0):
            candidates = [TempoCandidate(
                anchor, prior_bpm, fps * 60.0 / prior_bpm, 0.0, "fallback",
            )]
        else:
            lags, scores = _autocorrelation_scores(x, min_lag, max_lag)
            peaks = [
                int(i)
                for i in range(len(lags))
                if scores[i] > 0.0
                and (i == 0 or scores[i] > scores[i - 1])
                and (i == len(lags) - 1 or scores[i] >= scores[i + 1])
            ]
            peaks.sort(key=lambda i: (
                -float(scores[i]),
                _prior_distance(fps * 60.0 / float(lags[i]), prior_bpm),
                float(lags[i]),
            ))
            candidates = []
            for i in peaks[:TEMPO_CANDIDATES_PER_WINDOW]:
                lag = int(lags[i])
                score = float(scores[i])
                bpm = fps * 60.0 / lag
                candidates.append(TempoCandidate(anchor, bpm, float(lag), score, "peak"))
                for factor, origin in ((2.0, "octave-2x"), (0.5, "octave-0.5x")):
                    variant_bpm = bpm * factor
                    if MIN_BPM <= variant_bpm <= MAX_BPM:
                        candidates.append(TempoCandidate(
                            anchor, variant_bpm, fps * 60.0 / variant_bpm, score, origin,
                        ))
            candidates = _dedupe_candidates(candidates, prior_bpm) or [
                TempoCandidate(anchor, prior_bpm, fps * 60.0 / prior_bpm, 0.0, "fallback")
            ]
        windows.append(candidates)
        previous_non_empty = windows[-1]
    return windows


def _persistent_change_scores(
    windows: Sequence[Sequence[TempoCandidate]], prior_bpm: float
) -> np.ndarray:
    """Per-anchor change evidence from the local bests (plan section 11.3).

    A change only relaxes the transition cost when the local bests on both
    sides agree with their own median (support) and the evidence persists on
    two consecutive anchors.
    """
    bests: list[float] = []
    for window in windows:
        best = max(window, key=lambda c: (
            c.emission_score,
            -_prior_distance(c.bpm, prior_bpm),
            -c.bpm,
        ))
        bests.append(best.bpm)
    n = len(bests)
    scores = np.zeros(n, dtype=np.float64)
    for i in range(n):
        left_slice = bests[max(0, i - 2):i]
        right_slice = bests[i:min(n, i + 3)]
        if not left_slice or not right_slice:
            continue
        left = float(np.median(left_slice))
        right = float(np.median(right_slice))
        if left <= 0.0 or right <= 0.0:
            continue
        observed_delta = abs(math.log2(right / left))
        strength = _clamp(
            (observed_delta - CHANGE_ONSET_DELTA) / CHANGE_FULL_DELTA, 0.0, 1.0
        )
        left_support = sum(
            1 for bpm in left_slice if abs(math.log2(bpm / left)) <= CHANGE_AGREEMENT_BAND
        )
        right_support = sum(
            1 for bpm in right_slice if abs(math.log2(bpm / right)) <= CHANGE_AGREEMENT_BAND
        )
        support = min(left_support, right_support) / CHANGE_SUPPORT_ANCHORS
        scores[i] = strength * _clamp(support, 0.0, 1.0)
    persistent = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        persistent[i] = min(scores[i], scores[i - 1])
    return persistent


def _transition_cost(
    current: TempoCandidate, previous: TempoCandidate, lam: float
) -> float | None:
    """Soft Huber tempo cost + octave penalty; ``None`` when hard-forbidden."""
    delta = abs(math.log2(current.bpm / previous.bpm))
    if delta > MAX_ANCHOR_JUMP_LOG2:
        return None  # octave catastrophe between adjacent anchors
    cost = lam * huber(delta / TEMPO_DRIFT_SCALE)
    if abs(delta - 1.0) < OCTAVE_SWITCH_BAND:
        # The 1.75x cap already forbids full octave jumps between adjacent
        # anchors; the penalty keeps protecting this band if the cap is ever
        # relaxed (e.g. after retuning against the benchmark).
        cost += OCTAVE_SWITCH_PENALTY
    return cost


def _select_path_with_cap(
    windows: Sequence[Sequence[TempoCandidate]],
    lambdas: np.ndarray,
    prior_bpm: float,
    *,
    enforce_cap: bool,
) -> tuple[list[float], list[int]]:
    """Viterbi over log-BPM candidates; returns (final costs, backlinks)."""
    n = len(windows)
    costs = [
        PRIOR_WEIGHT * _prior_distance(c.bpm, prior_bpm) - c.emission_score
        for c in windows[0]
    ]
    backlinks: list[list[int]] = [[-1] * len(windows[0])]
    for i in range(1, n):
        lam = float(lambdas[i])
        row_costs: list[float] = []
        row_back: list[int] = []
        for cand in windows[i]:
            best_total = math.inf
            best_key: tuple[float, ...] | None = None
            best_j = -1
            for j, prev in enumerate(windows[i - 1]):
                transition = _transition_cost(cand, prev, lam)
                if transition is None:
                    if enforce_cap:
                        continue
                    delta = abs(math.log2(cand.bpm / prev.bpm))
                    transition = lam * huber(delta / TEMPO_DRIFT_SCALE)
                    if abs(delta - 1.0) < OCTAVE_SWITCH_BAND:
                        transition += OCTAVE_SWITCH_PENALTY
                total = costs[j] + transition - cand.emission_score
                key = (
                    transition,
                    abs(math.log2(cand.bpm / prev.bpm)),
                    _prior_distance(cand.bpm, prior_bpm),
                    cand.bpm,
                )
                if (
                    best_j < 0
                    or total < best_total - 1e-12
                    or (total <= best_total + 1e-12 and key < best_key)
                ):
                    best_total = total
                    best_key = key
                    best_j = j
            row_costs.append(best_total)
            row_back.append(best_j)
        costs = row_costs
        backlinks.append(row_back)
    return costs, backlinks


def select_tempo_path(
    windows: list[list[TempoCandidate]],
    *,
    global_prior_bpm: float,
) -> TempoPath:
    """Pick one candidate per anchor by global log-BPM Viterbi (section 11).

    Local argmax would turn every noisy window into a tempo jump; the path
    cost combines emission support, Huber-smooth tempo transitions, an
    adaptive relaxation where persistent change evidence exists, and a hard
    cap against octave catastrophes.
    """
    if not windows:
        raise ValueError("select_tempo_path needs at least one window")
    prior_bpm = float(global_prior_bpm) if global_prior_bpm else 120.0
    # Defensive: never feed the DP an empty window. Real anchors are kept
    # untouched; the placeholder only exists so a path is always defined.
    windows = [
        list(w) if w else [TempoCandidate(0, prior_bpm, 0.0, 0.0, "fallback")]
        for w in windows
    ]

    change_scores = _persistent_change_scores(windows, prior_bpm)
    lambdas = BASE_LAMBDA * (1.0 - 0.75 * change_scores)

    costs, backlinks = _select_path_with_cap(windows, lambdas, prior_bpm, enforce_cap=True)
    if all(math.isinf(c) for c in costs):
        # Only reachable when every final transition was hard-forbidden; drop
        # the cap so a path always exists (deterministically still costly).
        costs, backlinks = _select_path_with_cap(windows, lambdas, prior_bpm, enforce_cap=False)

    n = len(windows)
    final = min(range(len(costs)), key=lambda k: (costs[k], windows[n - 1][k].bpm))
    indices = [final]
    for i in range(n - 1, 0, -1):
        indices.append(backlinks[i][indices[-1]])
    indices.reverse()

    anchor_frames = np.array([w[0].anchor_frame for w in windows], dtype=np.int64)
    chosen = [windows[i][indices[i]] for i in range(n)]
    return TempoPath(
        anchor_frames=anchor_frames,
        bpms=np.array([c.bpm for c in chosen], dtype=np.float64),
        emission_scores=np.array([c.emission_score for c in chosen], dtype=np.float64),
        change_scores=change_scores,
    )


def interpolate_period_guide(
    path: TempoPath, novelty_length: int, fps: float
) -> np.ndarray:
    """Log-BPM linear interpolation of the path to every frame (section 11.5).

    Log space keeps tempo ratios symmetric: halfway between 120 and 60 BPM
    is ~84.85 BPM, not 90.
    """
    if novelty_length <= 0:
        return np.zeros(0, dtype=np.float64)
    frames = np.arange(novelty_length, dtype=np.float64)
    if len(path.anchor_frames) == 1:
        bpm_curve = np.full(novelty_length, float(path.bpms[0]))
    else:
        log_curve = np.interp(
            frames,
            path.anchor_frames.astype(np.float64),
            np.log(path.bpms.astype(np.float64)),
        )
        bpm_curve = np.exp(log_curve)
    return fps * 60.0 / bpm_curve


@dataclass(frozen=True)
class BeatTrackResult:
    """End-to-end tracker output for one analysis (plan section 7).

    ``beat_times`` stays unrounded; only the Rhythm IR writer rounds.
    When tracking fails, ``beat_times`` is empty and ``global_bpm`` carries
    the prior/120 fallback so the schema keeps a numeric BPM (section 12.5).
    """

    beat_times: tuple[float, ...]
    global_bpm: float
    tempo_segments: tuple[dict, ...]
    path_score: float | None
    diagnostics: dict = field(default_factory=dict)


def _local_beat_scores(novelty: np.ndarray) -> np.ndarray:
    """Stable per-frame beat support in [0, 1] (plan section 12.3)."""
    local = np.asarray(novelty, dtype=np.float64)
    if local.size == 0:
        return local
    local = local - np.median(local)
    scale = float(np.percentile(np.abs(local), 90)) + EPSILON
    return np.clip(local / scale, 0.0, 1.0)


def _first_strong_onset(novelty: np.ndarray) -> int:
    """First frame that plausibly starts the music (phase anchor).

    The first local maximum reaching ``FIRST_ONSET_ANCHOR_RATIO`` of the
    global maximum, or -1 when the novelty is empty or silent.
    """
    if novelty.size == 0:
        return -1
    peak = float(np.max(novelty))
    if peak <= 0.0:
        return -1
    threshold = FIRST_ONSET_ANCHOR_RATIO * peak
    radius = 2
    for i in range(novelty.size):
        value = float(novelty[i])
        if value < threshold:
            continue
        neighborhood = novelty[max(0, i - radius):i + radius + 1]
        if value >= float(np.max(neighborhood)):
            return i
    return -1


def dynamic_programming_beats(
    novelty: np.ndarray, period_curve: np.ndarray
) -> tuple[np.ndarray, dict]:
    """Recover beat frames under the period guide by DP (plan section 12).

    The guide says how fast the beat probably runs here; the DP decides the
    actual phase from local novelty support while punishing half-speed,
    double-speed, and phase jumps through the log-lag tightness cost.
    """
    n = len(novelty)
    diagnostics: dict = {"tracked": False, "support_fraction": 0.0, "beat_chain_length": 0}
    local = _local_beat_scores(novelty)
    if n == 0:
        return np.zeros(0, dtype=np.int64), diagnostics
    support = float(np.mean(local > 0.0))
    diagnostics["support_fraction"] = round(support, 4)
    if support < MIN_NOVELTY_SUPPORT:
        diagnostics["untracked_reason"] = "insufficient-novelty-support"
        return np.zeros(0, dtype=np.int64), diagnostics

    cumulative = np.zeros(n, dtype=np.float64)
    backlink = np.full(n, -1, dtype=np.int64)
    # One-beat bonus for chains passing through the first strong onset; see
    # the constant block for why this convention exists.
    anchor = _first_strong_onset(novelty)
    anchor_bonus = np.zeros(n, dtype=np.float64)
    if anchor >= 0:
        anchor_bonus[anchor] = FIRST_ONSET_ANCHOR_BONUS
    for t in range(n):
        expected = float(period_curve[t])
        lo = max(1, int(math.floor(expected * DP_LAG_MIN_RATIO)))
        hi = min(t, int(math.ceil(expected * DP_LAG_MAX_RATIO)))
        if expected <= 0 or hi < lo:
            cumulative[t] = local[t] + anchor_bonus[t]
            continue
        lags = np.arange(lo, hi + 1)
        previous = t - lags
        transition = TIGHTNESS * np.square(np.log(lags / expected))
        scores = cumulative[previous] - transition
        best = float(scores.max())
        ties = np.where(scores >= best - 1e-12)[0]
        if len(ties) == 1:
            choice = int(ties[0])
        else:
            # Equal scores: prefer the lag closest to the guide, then the
            # smaller lag (plan section 12.4).
            deviations = np.abs(np.log(lags[ties] / expected))
            choice = int(ties[np.lexsort((lags[ties], deviations))[0]])
        cumulative[t] = local[t] + anchor_bonus[t] + max(0.0, best)
        if best > 0.0:
            backlink[t] = int(previous[choice])

    last_period = float(period_curve[-1])
    window = max(1, int(math.ceil(1.5 * last_period))) if last_period > 0 else n
    start = max(0, n - window)
    tail = cumulative[start:]
    best_score = float(tail.max())
    ties = np.where(tail >= best_score - 1e-12)[0]
    end = start + int(ties.max())  # equal scores: the later end wins

    frames: list[int] = []
    cursor = end
    while cursor >= 0:
        frames.append(int(cursor))
        cursor = int(backlink[cursor])
    frames.reverse()
    # Only weak head/tail beats are dropped; interior beats stay (section 12.4).
    while frames and local[frames[0]] <= 0.0:
        frames.pop(0)
    while frames and local[frames[-1]] <= 0.0:
        frames.pop()
    if len(frames) < 2:
        diagnostics["untracked_reason"] = "beat-chain-too-short"
        return np.zeros(0, dtype=np.int64), diagnostics
    unique = sorted(set(frames))  # defensive; backlinks are strictly decreasing
    diagnostics["tracked"] = True
    diagnostics["beat_chain_length"] = len(unique)
    return np.array(unique, dtype=np.int64), diagnostics


def align_beats_to_onsets(
    beat_frames: np.ndarray,
    novelty: np.ndarray,
    period_curve: np.ndarray,
    fps: float,
) -> tuple[np.ndarray, int]:
    """Bounded snap of each beat toward its novelty peak (plan section 13).

    The snap radius is the smaller of ``SNAP_LIMIT_SECONDS`` and 15% of the
    local period, and a snap is only accepted while strict beat order, sane
    neighbor intervals, and distinct frames all survive. Never trades phase
    continuity for a slightly higher peak.
    """
    if len(beat_frames) == 0:
        return np.zeros(0, dtype=np.int64), 0
    n = len(novelty)
    final: list[int] = []
    snapped = 0
    for i, raw in enumerate(beat_frames):
        frame = int(raw)
        expected = float(period_curve[frame]) if 0 <= frame < len(period_curve) else 0.0
        if expected <= 0:
            final.append(frame)
            continue
        radius_seconds = min(SNAP_LIMIT_SECONDS, SNAP_RADIUS_PERIOD_RATIO * expected / fps)
        radius = max(1, int(round(radius_seconds * fps)))
        lo = max(0, frame - radius)
        hi = min(n - 1, frame + radius)
        window = np.asarray(novelty[lo:hi + 1], dtype=np.float64)
        peak = float(window.max())
        ties = np.where(window >= peak - 1e-12)[0]
        if len(ties) == 1:
            choice = lo + int(ties[0])
        else:
            candidates = ties + lo
            distances = np.abs(candidates - frame)
            choice = int(candidates[np.lexsort((candidates, distances))[0]])
        if choice == frame:
            final.append(frame)
            continue
        prev_bound = final[-1] if final else -1
        next_bound = int(beat_frames[i + 1]) if i + 1 < len(beat_frames) else n
        ok = prev_bound < choice < next_bound
        if ok and final:
            ok = DP_LAG_MIN_RATIO <= (choice - final[-1]) / expected <= DP_LAG_MAX_RATIO
        if ok and i + 1 < len(beat_frames):
            ok = DP_LAG_MIN_RATIO <= (next_bound - choice) / expected <= DP_LAG_MAX_RATIO
        if ok:
            final.append(choice)
            snapped += 1
        else:
            final.append(frame)
    aligned = np.array(final, dtype=np.int64)
    if np.any(np.diff(aligned) <= 0):  # last-resort phase-continuity guard
        return np.asarray(beat_frames, dtype=np.int64), 0
    return aligned, snapped


def _frame_support(novelty: np.ndarray, frame: int) -> float:
    lo = max(0, frame - SUPPORT_WINDOW_FRAMES)
    hi = min(len(novelty), frame + SUPPORT_WINDOW_FRAMES + 1)
    return float(np.sum(novelty[lo:hi]))


def repair_beat_continuity(
    beat_frames: np.ndarray,
    period_curve: np.ndarray,
    novelty: np.ndarray,
    *,
    fps: float,
) -> tuple[np.ndarray, dict]:
    """Fix mechanical tracker anomalies without re-estimating tempo (section 14).

    Duplicates (interval < 55% of the guide) drop the weaker beat; single
    missing beats (interval inside 1.65x..2.35x with a consistent guide) are
    reinserted from the predicted phase. Nothing else is touched.
    """
    kept: list[int] = []
    duplicates_removed = 0
    for raw in beat_frames:
        frame = int(raw)
        if not kept:
            kept.append(frame)
            continue
        expected = float(period_curve[kept[-1]])
        gap = frame - kept[-1]
        if expected > 0 and gap < DUPLICATE_RATIO * expected:
            duplicates_removed += 1
            if _frame_support(novelty, frame) > _frame_support(novelty, kept[-1]):
                kept[-1] = frame
            elif _frame_support(novelty, frame) == _frame_support(novelty, kept[-1]):
                predicted = (
                    kept[-2] + float(period_curve[kept[-2]]) if len(kept) >= 2 else -math.inf
                )
                if abs(frame - predicted) < abs(kept[-1] - predicted):
                    kept[-1] = frame  # equal support: keep the better-phase beat
            # else: keep the earlier beat (default)
        else:
            kept.append(frame)

    result: list[int] = []
    beats_inserted = 0
    for frame in kept:
        if result:
            expected = float(period_curve[result[-1]])
            gap = frame - result[-1]
            guide_right = float(period_curve[frame])
            guide_consistent = (
                expected > 0
                and guide_right > 0
                and abs(math.log2(guide_right / expected)) <= MISSING_GUIDE_BAND
            )
            if (
                guide_consistent
                and MISSING_MIN_RATIO * expected < gap < MISSING_MAX_RATIO * expected
            ):
                predicted = result[-1] + expected
                radius_seconds = min(
                    SNAP_LIMIT_SECONDS, MISSING_SNAP_PERIOD_RATIO * expected / fps
                )
                radius = max(1, int(round(radius_seconds * fps)))
                lo = max(0, int(round(predicted - radius)))
                hi = min(len(novelty) - 1, int(round(predicted + radius)))
                target = int(round(predicted))
                window = np.asarray(novelty[lo:hi + 1], dtype=np.float64)
                if hi >= lo and float(window.max()) > 0.0:
                    ties = np.where(window >= float(window.max()) - 1e-12)[0] + lo
                    distances = np.abs(ties - predicted)
                    target = int(ties[np.lexsort((ties, distances))[0]])
                left_gap = target - result[-1]
                right_gap = frame - target
                if (
                    result[-1] < target < frame
                    and DP_LAG_MIN_RATIO <= left_gap / expected <= DP_LAG_MAX_RATIO
                    and DP_LAG_MIN_RATIO <= right_gap / expected <= DP_LAG_MAX_RATIO
                ):
                    result.append(target)
                    beats_inserted += 1
        result.append(frame)

    unrepairable_gaps = 0
    for left, right in zip(result, result[1:]):
        expected = float(period_curve[left])
        if expected > 0 and right - left > MISSING_MAX_RATIO * expected:
            unrepairable_gaps += 1
    diagnostics = {
        "duplicates_removed": duplicates_removed,
        "beats_inserted": beats_inserted,
        "unrepairable_gaps": unrepairable_gaps,
    }
    return np.array(result, dtype=np.int64), diagnostics


def number_beats(
    beat_times: Sequence[float], numerator: int = 4
) -> list[dict]:
    """Assign bar/beat numbers once, after every repair (plan section 14.4)."""
    return [
        {
            "time": time,
            "beat": index % numerator + 1,
            "bar": index // numerator + 1,
            "downbeat": index % numerator == 0,
            "sequence_gap": False,
        }
        for index, time in enumerate(beat_times)
    ]


def _dp_key_is_better(new: tuple[float, int, int], old: tuple[float, int, int]) -> bool:
    """DP tie order: cost, then fewer segments, then the earlier boundary."""
    if new[0] < old[0] - 1e-12:
        return True
    if new[0] > old[0] + 1e-12:
        return False
    return new[1:] < old[1:]


def segment_tempo_curve(
    interval_times: np.ndarray,
    interval_bpms: np.ndarray,
    change_scores: np.ndarray | None,
    duration: float,
) -> list[tuple[int, int, float]]:
    """Piecewise-constant tempo segmentation by 1-D DP (plan section 15.2).

    Returns ``[(first_interval, end_interval_exclusive, bpm), ...]`` covering
    every input interval. Boundaries are interval indices; mapping them onto
    beat times is the caller's job (section 15.3). Interior segments must
    cover at least ``MIN_SEGMENT_BEATS`` intervals; leading and trailing
    segments are exempt so edges cannot force a merge.
    """
    n = len(interval_bpms)
    if n == 0:
        return []
    if float(interval_times[-1]) > float(duration) + 1e-6:
        raise ValueError("interval times exceed the audio duration")
    log_bpms = np.log2(np.asarray(interval_bpms, dtype=np.float64))
    if change_scores is None:
        change = np.zeros(n, dtype=np.float64)
    else:
        change = np.clip(np.asarray(change_scores, dtype=np.float64), 0.0, 1.0)

    dp = [math.inf] * (n + 1)
    dp[0] = 0.0
    parent = [0] * (n + 1)
    count = [0] * (n + 1)
    for j in range(1, n + 1):
        best: tuple[float, int, int] | None = None
        for i in range(max(0, j - MAX_SEGMENT_INTERVALS), j):
            if dp[i] == math.inf:
                continue
            length = j - i
            if 0 < i and j < n and length < MIN_SEGMENT_BEATS:
                continue  # interior segments need real support
            fit = float(np.median(log_bpms[i:j]))
            cost = float(np.sum(_huber_array((log_bpms[i:j] - fit) / SEGMENT_SCALE)))
            total = dp[i] + cost
            if i > 0:
                relaxed = 1.0 - SEGMENT_BOUNDARY_RELAX * float(change[i])
                total += SEGMENT_BOUNDARY_PENALTY * max(0.0, relaxed)
            key = (total, count[i] + 1, i)
            if best is None or _dp_key_is_better(key, best):
                best = key
                dp[j] = total
                parent[j] = i
                count[j] = count[i] + 1
        if best is None:  # unreachable: dp[0] is finite and a valid predecessor always exists
            raise RuntimeError("segmentation DP failed to advance")

    pieces: list[tuple[int, int]] = []
    j = n
    while j > 0:
        i = parent[j]
        pieces.append((i, j))
        j = i
    pieces.reverse()
    return [(i, j, float(2.0 ** float(np.median(log_bpms[i:j])))) for i, j in pieces]


def _refit_segment_bpm(log_bpms: np.ndarray, start: int, end: int) -> float:
    """Median log2 fit over intervals [start, end), returned as BPM."""
    return float(2.0 ** float(np.median(log_bpms[start:end])))


def build_tempo_segments_from_beats(
    beat_times: Sequence[float],
    duration: float,
    *,
    method: str,
    interval_change_scores: Sequence[float] | None = None,
    interval_emissions: Sequence[float] | None = None,
) -> tuple[dict, ...]:
    """Derive tempo segments from final beat times (plan sections 15.1/15.5).

    Usable directly for Beat This marker timestamps (``method=
    "beat-marker-intervals"``) so marker tempo changes survive the pipeline.
    Interval BPMs are median-smoothed over 3 intervals for fitting only;
    beat timestamps themselves are never rewritten here.
    """
    beats = [float(t) for t in beat_times]
    if len(beats) < 2:
        return ()
    times_arr = np.asarray(beats, dtype=np.float64)
    intervals = np.diff(times_arr)
    if np.any(intervals <= 0):
        raise ValueError("beat times must be strictly increasing")
    interval_times = (times_arr[:-1] + times_arr[1:]) / 2.0
    interval_bpms = 60.0 / intervals
    smoothed = np.array([
        float(np.median(interval_bpms[max(0, k - 1):min(len(interval_bpms), k + 2)]))
        for k in range(len(interval_bpms))
    ])

    raw_pieces = segment_tempo_curve(
        interval_times, smoothed, None if interval_change_scores is None else np.asarray(interval_change_scores, dtype=np.float64), duration,
    )

    # Re-merge adjacent segments whose fitted tempos are nearly identical.
    # Refits always come from the union of the merged intervals so a merged
    # segment can still re-merge with its predecessor.
    log_smoothed = np.log2(smoothed)
    merged: list[list] = []  # [start_i, end_i_exclusive, bpm]
    for i, j, _bpm in raw_pieces:
        if merged and abs(
            math.log2(_refit_segment_bpm(log_smoothed, i, j) / merged[-1][2])
        ) < SEGMENT_MERGE_LOG2:
            merged[-1][1] = j
            merged[-1][2] = _refit_segment_bpm(log_smoothed, merged[-1][0], j)
        else:
            merged.append([i, j, _refit_segment_bpm(log_smoothed, i, j)])
        while len(merged) >= 2 and abs(
            math.log2(merged[-1][2] / merged[-2][2])
        ) < SEGMENT_MERGE_LOG2:
            prev = merged[-2]
            merged[-2:] = [[prev[0], merged[-1][1], _refit_segment_bpm(log_smoothed, prev[0], merged[-1][1])]]

    emissions = (
        np.clip(np.asarray(interval_emissions, dtype=np.float64), 0.0, 1.0)
        if interval_emissions is not None else None
    )
    segments: list[dict] = []
    for i, j, bpm in merged:
        start = 0.0 if i == 0 else beats[i]
        end = duration if j >= len(beats) - 1 else beats[j]
        score = None
        if emissions is not None:
            score = round(float(np.mean(emissions[i:j])), 4)
        segments.append({
            "start": start,
            "end": end,
            "bpm": float(bpm),
            "method": method,
            "score": score,
        })
    return tuple(segments)


def track_tempo_and_beats(
    novelty: np.ndarray,
    sample_rate: int,
    hop_length: int,
    *,
    global_prior_bpm: float | None,
    duration: float | None = None,
) -> BeatTrackResult:
    """Orchestrate the full variable-tempo tracker (plan sections 10-15)."""
    fps = sample_rate / hop_length
    prior_bpm = float(global_prior_bpm) if global_prior_bpm else 120.0
    novelty = np.asarray(novelty, dtype=np.float64)
    n = len(novelty)
    if duration is None:
        duration = n * hop_length / sample_rate

    windows = build_local_tempo_candidates(
        novelty, sample_rate, hop_length, global_prior_bpm=global_prior_bpm
    )
    path = select_tempo_path(windows, global_prior_bpm=prior_bpm)
    period_curve = interpolate_period_guide(path, n, fps)

    beat_frames, dp_diagnostics = dynamic_programming_beats(novelty, period_curve)
    path_log = np.log2(np.maximum(path.bpms, 1e-9))
    diagnostics: dict = {
        "tempo_path_anchors": int(len(path.anchor_frames)),
        "tempo_path_octave_switches": (
            int(np.sum(np.abs(np.diff(path_log)) > 0.75)) if len(path_log) > 1 else 0
        ),
        "path_emission_support": round(float(np.mean(np.clip(path.emission_scores, 0.0, 1.0))), 4),
        **dp_diagnostics,
    }
    if len(beat_frames) < 2:
        return BeatTrackResult(
            beat_times=(), global_bpm=prior_bpm, tempo_segments=(),
            path_score=None, diagnostics=diagnostics,
        )

    beat_frames, snapped = align_beats_to_onsets(beat_frames, novelty, period_curve, fps)
    beat_frames, repair_diagnostics = repair_beat_continuity(
        beat_frames, period_curve, novelty, fps=fps
    )
    diagnostics["snapped_beats"] = snapped
    diagnostics.update(repair_diagnostics)
    beat_times = [frame * hop_length / sample_rate for frame in beat_frames]
    if len(beat_times) < 2:
        return BeatTrackResult(
            beat_times=(), global_bpm=prior_bpm, tempo_segments=(),
            path_score=None, diagnostics=diagnostics,
        )

    anchor_times = path.anchor_frames.astype(np.float64) / fps
    times_arr = np.asarray(beat_times, dtype=np.float64)
    interval_times = (times_arr[:-1] + times_arr[1:]) / 2.0
    interval_change = np.interp(interval_times, anchor_times, path.change_scores)
    interval_emissions = np.interp(
        interval_times, anchor_times, np.clip(path.emission_scores, 0.0, 1.0)
    )
    segments = build_tempo_segments_from_beats(
        beat_times,
        duration,
        method="local-autocorrelation-viterbi+beat-dp",
        interval_change_scores=interval_change,
        interval_emissions=interval_emissions,
    )

    # Global BPM: mean beat rate over the span, after trimming intervals that
    # clearly do not belong to the median pace (plan section 15.4).
    intervals = np.diff(times_arr)
    median_interval = float(np.median(intervals))
    keep = np.abs(np.log2(intervals / median_interval)) <= GLOBAL_BPM_TRIM_LOG2
    if bool(np.any(keep)):
        global_bpm = 60.0 * int(np.sum(keep)) / float(np.sum(intervals[keep]))
    else:
        global_bpm = prior_bpm

    diagnostics["segment_count"] = len(segments)
    return BeatTrackResult(
        beat_times=tuple(float(t) for t in beat_times),
        global_bpm=float(global_bpm),
        tempo_segments=segments,
        path_score=round(float(np.mean(np.clip(path.emission_scores, 0.0, 1.0))), 4),
        diagnostics=diagnostics,
    )
