"""Local timing refinement over the model's beats (accuracy plan, phase 4).

The model supplies general rhythmic judgement; this layer tries to improve where
a beat sits in time, using evidence the model does not look at directly: where
the audio actually has an attack, and what the model's own support curve says
nearby. It is the only place BeatScope can contribute accuracy on top of the
model, so it is also the only place that can lose it.

Round 1 does one thing: move a beat, or leave it exactly where it was. Every beat
keeps the "do not move" option, so a beat with no clear acoustic event stays put
rather than being pulled somewhere by a rule. Adding or removing beats, and
choosing a metrical level, are round 2 - they are not attempted here, and the
plan says they wait until this round shows a gain.

Two things this deliberately avoids:

- No global grid, no fixed tempo, no assumption of 4/4. The window and the period
  are local, so a tempo change or a pause is not something to correct.
- No multiplying acoustic scores together. The onset kernel and the support curve
  measure related things, so they are combined as a weighted sum with a separate
  penalty for moving a beat at all; treating them as independent probabilities
  would overstate the confidence.

The parameters are development-set values, not measured optima. Whether the layer
helps at all is answered by the evaluation, not by this file.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

# Development-set starting values. The plan requires these to be chosen on the
# development split and to leave the held-out split for the decision.
WINDOW_RATIO = 0.25
ONSET_WEIGHT = 1.0
SUPPORT_WEIGHT = 0.6
MOVE_PENALTY = 0.8
MARGIN = 0.15
ONSET_TOLERANCE_SECONDS = 0.05
MIN_GAP_RATIO = 0.25


@dataclass
class RefinementRecord:
    """What happened to one beat, so a move can be explained or audited."""

    original: float
    chosen: float
    moved: bool
    reason: str
    score: float
    margin: float
    candidates: list[tuple[float, float]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "original": round(self.original, 6),
            "chosen": round(self.chosen, 6),
            "moved": self.moved,
            "reason": self.reason,
            "score": round(self.score, 6),
            "margin": round(self.margin, 6),
        }


def support_at(support: np.ndarray, frame_rate: float, time: float) -> float:
    """The support curve sampled at a time, or 0.0 outside it."""
    if frame_rate <= 0 or len(support) == 0:
        return 0.0
    index = int(round(time * frame_rate))
    if index < 0 or index >= len(support):
        return 0.0
    return float(support[index])


def onset_evidence(onsets: Sequence[float], time: float, tolerance: float) -> float:
    """How close the nearest onset is, as a linear kernel in [0, 1]."""
    best = 0.0
    for onset in onsets:
        distance = abs(float(onset) - time)
        if distance <= tolerance:
            best = max(best, 1.0 - distance / tolerance)
    return best


def local_period(times: Sequence[float], index: int) -> float:
    """The interval around a beat, from its neighbours only."""
    if len(times) < 2:
        return 0.0
    if index == 0:
        return max(0.0, float(times[1]) - float(times[0]))
    if index == len(times) - 1:
        return max(0.0, float(times[-1]) - float(times[-2]))
    left = float(times[index]) - float(times[index - 1])
    right = float(times[index + 1]) - float(times[index])
    return max(0.0, (left + right) / 2.0)


def refine_beats(
    beats: Sequence[float],
    *,
    support: np.ndarray | None = None,
    support_frame_rate: float = 50.0,
    onsets: Sequence[float] = (),
    window_ratio: float = WINDOW_RATIO,
    onset_weight: float = ONSET_WEIGHT,
    support_weight: float = SUPPORT_WEIGHT,
    move_penalty: float = MOVE_PENALTY,
    margin: float = MARGIN,
    onset_tolerance: float = ONSET_TOLERANCE_SECONDS,
    min_gap_ratio: float = MIN_GAP_RATIO,
) -> tuple[list[float], list[RefinementRecord]]:
    """Move beats that have evidence, leave the rest exactly where they are.

    Returns the refined times and one record per beat. The order of the input is
    preserved: a candidate is rejected if it would collide with the neighbour
    already accepted on the left.
    """
    times = [float(value) for value in beats]
    if len(times) < 2:
        return times, [RefinementRecord(t, t, False, "too-few-beats", 0.0, 0.0) for t in times]

    onsets = sorted(float(value) for value in onsets)
    refined: list[float] = []
    records: list[RefinementRecord] = []
    for index, original in enumerate(times):
        period = local_period(times, index)
        if period <= 0:
            refined.append(original)
            records.append(RefinementRecord(original, original, False, "no-local-period", 0.0, 0.0))
            continue
        window = window_ratio * period
        min_gap = min_gap_ratio * period

        def score(target: float, original: float = original, period: float = period) -> float:
            # Bound as defaults so the closure owns this iteration's values: it is
            # called within the same iteration today, and a deferred caller would
            # otherwise score every beat against the last one's period.
            evidence = onset_weight * onset_evidence(onsets, target, onset_tolerance)
            if support is not None:
                evidence += support_weight * support_at(support, support_frame_rate, target)
            return evidence - move_penalty * (abs(target - original) / period)

        stay = score(original)
        candidates: list[tuple[float, float]] = [(original, stay)]
        for onset in onsets:
            if abs(onset - original) <= window:
                candidates.append((onset, score(onset)))
        if support is not None and support_frame_rate > 0:
            # The model's own support peak nearby, as its own candidate rather
            # than as a tie-break inside the sum.
            low = max(0, int(round((original - window) * support_frame_rate)))
            high = min(len(support), int(round((original + window) * support_frame_rate)) + 1)
            if high > low:
                peak = low + int(np.argmax(np.asarray(support)[low:high]))
                peak_time = peak / support_frame_rate
                candidates.append((peak_time, score(peak_time)))

        best_time, best_score = max(candidates, key=lambda item: item[1])
        reason = "stay"
        chosen = original
        gained = best_score - stay
        lower = (refined[-1] + min_gap) if refined else -math.inf
        upper = (times[index + 1] - min_gap) if index + 1 < len(times) else math.inf
        if gained >= margin and lower <= best_time <= upper and best_time != original:
            chosen = best_time
            reason = "moved"
        records.append(
            RefinementRecord(
                original=original,
                chosen=chosen,
                moved=chosen != original,
                reason=reason,
                score=best_score,
                margin=gained,
                candidates=sorted(candidates),
            )
        )
        refined.append(chosen)

    if any(later <= earlier for earlier, later in zip(refined, refined[1:], strict=False)):
        # A refinement that inverts two beats is worse than no refinement; the
        # guard above should prevent it, and this keeps the promise if it does not.
        return times, [RefinementRecord(t, t, False, "order-guard", 0.0, 0.0) for t in times]
    return refined, records


__all__ = [
    "RefinementRecord",
    "local_period",
    "onset_evidence",
    "refine_beats",
    "support_at",
]
