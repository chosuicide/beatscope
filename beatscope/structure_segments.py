"""Deterministic whole-song segmentation: boundaries, segments, families.

Consumes the per-bar view matrices from :mod:`beatscope.structure_features`
and produces neutral structure facts - where the song changes (boundaries),
which larger passages exist (segments), and which passages repeat (families
A/B/A', C - never Verse/Chorus labels).

Pipeline:
1. per-view cosine self-similarity matrices combined with fixed view weights
   and a diagonal-band median enhancement;
2. Foote checkerboard novelty at 4- and 8-bar kernels;
3. candidate cuts (strict local maxima above median + 1.25*MAD with driver
   evidence) and a length-constrained dynamic program with an explicit
   segment cost;
4. duration-normalized family agglomeration against family medoids.

Everything is float64 numpy with fixed iteration order - the same input
always yields byte-identical output. No RNG, no wall-clock reads.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .structure_features import StructureFeatures

STRUCTURE_METHOD = "bar-multiview-ssm-v2"

VIEW_WEIGHTS = {"harmony": 0.34, "timbre": 0.28, "rhythm": 0.23, "energy": 0.15}
BOUNDARY_KERNELS = (4, 8)
NOVELTY_MAD_FACTOR = 1.25
# Absolute per-view kernel-4 novelty a candidate must reach in at least one
# view (driver corroboration). Calibrated on the structure fixtures: true
# boundary drivers score >= 0.30, flat-song noise peaks <= 0.16.
NOVELTY_DRIVER_FLOOR = 0.2
NOVELTY_LOCAL_RADIUS = 2
MIN_BOUNDARY_GAP_BARS = 4
EDGE_EXCLUSION_BARS = 2
FLAT_NOVELTY_FLOOR = 0.25  # fallback when the novelty bed has zero MAD

MIN_SEGMENT_BARS = 4
MAX_SEGMENT_BARS = 32
PREFERRED_LENGTHS = (4, 8, 12, 16)
COST_WITHIN_VARIANCE = 0.55
COST_LENGTH_PENALTY = 0.25
COST_WEAK_BOUNDARY = 0.20
BOUNDARY_REWARD = 0.30
COST_TIE_EPSILON = 1e-9

FAMILY_JOIN_THRESHOLD = 0.82
FAMILY_VARIANT_THRESHOLD = 0.88
# A single view below this blocks a family join outright. The weighted
# geometric mean still dilutes a lone dissenter (energy at 0.48 with weight
# 0.15 leaves the score at ~0.88), but "these passages are under 55% alike
# in some independent dimension" is disqualifying on its own.
FAMILY_VIEW_VETO = 0.55
# Two views below this also block a join. One view dipping can be a
# measurement artifact - timbre legitimately shifts ~0.69 when the same
# material is played at a different tempo (the fixed pad attack covers a
# different fraction of the bar) - so a lone dip must not veto. When two
# independent dimensions agree the content changed, it changed.
FAMILY_DUAL_DISSENT_THRESHOLD = 0.85
FAMILY_DUAL_DISSENT_COUNT = 2
FAMILY_RESAMPLE_POSITIONS = 8
LENGTH_RATIO_FLOOR = 0.75

# Column blocks of the rhythm view's three 16-step dominant-band layers
# (low/mid/high). Its agreement score is the MINIMUM per-band cosine: bands
# are independent rhythmic layers, and a flat cosine over the concatenation
# lets the layers two patterns share dilute a complete role swap in one
# layer - four-floor kick turning into backbeat snare - into a near match.
RHYTHM_BAND_BLOCKS = ((0, 16), (16, 32), (32, 48))

LOW_ENERGY_PERCENTILE = 20.0
BREAK_DENSITY_FACTOR = 0.5
TRANSITION_MAX_BARS = 6

SUPERFRAME_BARS = 2048  # beyond this, boundary detection runs on bar pairs


# ------------------------------------------------------------ similarity

def cosine_matrix(features: np.ndarray) -> np.ndarray:
    """B x B cosine similarity: clipped to [0, 1], symmetrized, unit diagonal."""
    values = np.asarray(features, dtype=np.float64)
    norms = np.linalg.norm(values, axis=1)
    safe = np.where(norms > 1e-9, norms, 1.0)
    unit = values / safe[:, None]
    sim = np.clip(unit @ unit.T, 0.0, 1.0)
    sim = (sim + sim.T) / 2.0
    np.fill_diagonal(sim, 1.0)
    return sim


def _diagonal_band_median(sim: np.ndarray) -> np.ndarray:
    """Median over the -1/0/+1 diagonal offsets, reinforcing local repetition."""
    stacked = np.full((3, *sim.shape), np.nan)
    stacked[0, 1:, 1:] = sim[:-1, :-1]
    stacked[1] = sim
    stacked[2, :-1, :-1] = sim[1:, 1:]
    with np.errstate(all="ignore"):
        smoothed = np.nanmedian(stacked, axis=0)
    return np.where(np.isfinite(smoothed), smoothed, sim)


def combine_views(views: dict[str, np.ndarray]) -> np.ndarray:
    """Weighted per-view cosine matrices, weights renormalized over views present."""
    matrices: dict[str, np.ndarray] = {}
    weights: dict[str, float] = {}
    for name, features in views.items():
        if features.shape[0] == 0:
            continue
        matrices[name] = cosine_matrix(features)
        weights[name] = VIEW_WEIGHTS.get(name, 0.0)
    if not matrices:
        raise ValueError("no view matrices to combine")
    total = sum(weights.values())
    if total <= 0.0:
        weights = {name: 1.0 for name in matrices}
        total = float(len(matrices))
    combined = np.zeros_like(next(iter(matrices.values())))
    for name, matrix in matrices.items():
        combined += (weights[name] / total) * matrix
    return _diagonal_band_median(combined)


# -------------------------------------------------------------- novelty

def checkerboard_novelty(sim: np.ndarray, kernel: int) -> np.ndarray:
    """Foote checkerboard novelty; entry ``d`` scores the cut before bar ``d``."""
    size = sim.shape[0]
    half = kernel // 2
    novelty = np.zeros(size)
    for cut in range(half, size - half + 1):
        before = sim[cut - half:cut, cut - half:cut]
        after = sim[cut:cut + half, cut:cut + half]
        cross = sim[cut - half:cut, cut:cut + half]
        novelty[cut] = (before.mean() + after.mean()) / 2.0 - cross.mean()
    return novelty


def _minmax(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    scaled = np.zeros_like(values)
    if not valid.any():
        return scaled
    low = float(values[valid].min())
    high = float(values[valid].max())
    if high - low < 1e-12:
        return scaled
    scaled[valid] = (values[valid] - low) / (high - low)
    return scaled


# ------------------------------------------------------------ candidates

def select_boundary_candidates(
    sim: np.ndarray,
    view_novelty: dict[str, np.ndarray],
) -> tuple[list[int], dict[int, float], dict[int, dict[str, float]]]:
    """Candidate cut positions with normalized novelty and per-view drivers.

    A cut qualifies when it is a strict local maximum (+/-2 bars) of the
    combined kernel novelty above a noise floor estimated from the bed of
    non-boundary positions (median + 1.25*MAD of the lower half of the
    eligible values), and at least one view's own RAW kernel-4 novelty at
    the cut clears NOVELTY_DRIVER_FLOOR (driver corroboration).

    The driver floor is absolute on purpose. Min-max normalization rescales
    whatever variation remains to [0, 1], so on a uniform song the largest
    noise wiggle always looks like a boundary and no relative rule can
    reject it; a real boundary, by contrast, always makes at least one view
    spike far above the noise (fixture-measured: true drivers >= 0.30,
    flat-song noise <= 0.16).
    """
    size = sim.shape[0]
    half_max = max(BOUNDARY_KERNELS) // 2
    valid = np.zeros(size, dtype=bool)
    if size >= 2 * half_max:
        valid[half_max: size - half_max + 1] = True

    kernel_curves = [
        _minmax(checkerboard_novelty(sim, kernel), valid) for kernel in BOUNDARY_KERNELS
    ]
    combined = np.mean(kernel_curves, axis=0) if kernel_curves else np.zeros(size)
    drivers = {name: _minmax(curve, valid) for name, curve in view_novelty.items()}

    interior = np.zeros(size, dtype=bool)
    if size > 2 * EDGE_EXCLUSION_BARS:
        interior[EDGE_EXCLUSION_BARS: size - EDGE_EXCLUSION_BARS + 1] = True
    eligible = valid & interior
    if not eligible.any():
        return [], {}, {}

    values = combined[eligible]
    # The noise floor must come from the "bed" of non-boundary positions.
    # With dense boundaries the kernel side lobes occupy most positions and
    # would drag a global median (and MAD) up to the lobe level, putting the
    # floor above the true peaks; the lower half of the values tracks the
    # actual bed instead.
    median = float(np.median(values))
    bed = values[values <= median]
    reference = bed if bed.size >= 4 else values
    centre = float(np.median(reference))
    mad = float(np.median(np.abs(reference - centre)))
    if mad > 1e-12:
        floor = centre + NOVELTY_MAD_FACTOR * mad
    else:
        floor = centre + FLAT_NOVELTY_FLOOR

    candidates: list[int] = []
    novelty_map: dict[int, float] = {}
    driver_map: dict[int, dict[str, float]] = {}
    for cut in range(size):
        if not eligible[cut] or combined[cut] < floor:
            continue
        lo = max(0, cut - NOVELTY_LOCAL_RADIUS)
        hi = min(size - 1, cut + NOVELTY_LOCAL_RADIUS)
        if any(combined[other] >= combined[cut] for other in range(lo, hi + 1) if other != cut):
            continue
        if candidates and cut - candidates[-1] < MIN_BOUNDARY_GAP_BARS:
            continue  # keep the earlier of two near neighbours
        strong_driver = any(
            float(curve[cut]) >= NOVELTY_DRIVER_FLOOR
            for curve in view_novelty.values()
        )
        if view_novelty and not strong_driver:
            continue
        candidates.append(cut)
        novelty_map[cut] = round(float(combined[cut]), 4)
        driver_map[cut] = {
            name: round(float(scaled[cut]), 4) for name, scaled in drivers.items()
        }
    return candidates, novelty_map, driver_map


# --------------------------------------------------------------- segments

def _within_variance(sim: np.ndarray, prefix: np.ndarray, start: int, end: int) -> float:
    """Mean (1 - similarity) over off-diagonal bar pairs of [start, end)."""
    length = end - start
    if length < 2:
        return 0.0
    total = prefix[end, end] - prefix[start, end] - prefix[end, start] + prefix[start, start]
    mean_pair = (total - length) / (length * (length - 1))
    return float(np.clip(1.0 - mean_pair, 0.0, 1.0))


def _length_penalty(length: int) -> float:
    return min(abs(length - preferred) / preferred for preferred in PREFERRED_LENGTHS)


def segment_with_dp(
    sim: np.ndarray,
    candidates: list[int],
    novelty: dict[int, float],
) -> list[int]:
    """Choose cut positions with a length-constrained dynamic program.

    Segment cost = 0.55 * within-variance + 0.25 * length penalty
                 + 0.20 * weak-boundary penalty - boundary reward.
    Ties prefer fewer segments, then the earliest final boundary.
    """
    size = sim.shape[0]
    prefix = np.zeros((size + 1, size + 1))
    prefix[1:, 1:] = np.cumsum(np.cumsum(sim, axis=0), axis=1)

    positions = sorted({0, *candidates, size})
    best: dict[int, tuple[float, int, int | None]] = {size: (0.0, 0, None)}
    for index in range(len(positions) - 2, -1, -1):
        start = positions[index]
        best_option: tuple[float, int, int | None] | None = None
        for end in positions[index + 1:]:
            length = end - start
            if length < MIN_SEGMENT_BARS or length > MAX_SEGMENT_BARS:
                continue
            if end < size:
                weak = 1.0 - novelty.get(end, 0.0)
                reward = BOUNDARY_REWARD * novelty.get(end, 0.0)
            else:
                weak, reward = 0.0, 0.0
            cost = (
                COST_WITHIN_VARIANCE * _within_variance(sim, prefix, start, end)
                + COST_LENGTH_PENALTY * _length_penalty(length)
                + COST_WEAK_BOUNDARY * weak
                - reward
                + best[end][0]
            )
            count = 1 + best[end][1]
            if best_option is None or cost < best_option[0] - COST_TIE_EPSILON or (
                abs(cost - best_option[0]) <= COST_TIE_EPSILON and count < best_option[1]
            ):
                best_option = (cost, count, end)
        if best_option is None:
            # No legal segment fits from here; an enormous cost keeps earlier
            # positions from routing through this one.
            best[start] = (1e18, 10**6, None)
        else:
            best[start] = best_option

    if best[0][1] >= 10**6 or best[0][0] >= 1e17:
        return [size]
    cuts: list[int] = []
    cursor = 0
    while cursor < size:
        next_cut = best[cursor][2]
        if next_cut is None:
            return [size]
        cuts.append(cursor)
        cursor = next_cut
    cuts.append(size)
    return cuts


# --------------------------------------------------------------- families

def _resample_rows(rows: np.ndarray, positions: int = FAMILY_RESAMPLE_POSITIONS) -> np.ndarray:
    """Linear resample of a segment's per-bar rows onto fixed positions."""
    count = rows.shape[0]
    if count == 0:
        return np.zeros((positions, rows.shape[1]))
    if count == 1:
        return np.repeat(rows, positions, axis=0)
    source = np.linspace(0.0, count - 1.0, num=positions)
    left = np.clip(np.floor(source).astype(int), 0, count - 1)
    right = np.clip(left + 1, 0, count - 1)
    frac = (source - left)[:, None]
    return rows[left] * (1.0 - frac) + rows[right] * frac


def _segment_cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine with the empty-row conventions the family stage needs."""
    norm_a, norm_b = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if norm_a < 1e-9 and norm_b < 1e-9:
        return 1.0  # silent on both sides is agreement
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0  # a layer only one side has is disagreement
    return float(np.clip(float(a @ b) / (norm_a * norm_b), 0.0, 1.0))


def _view_agreement(name: str, rows_a: np.ndarray, rows_b: np.ndarray) -> float:
    """Agreement score for one view over two resampled row sequences."""
    if name == "rhythm" and rows_a.shape[1] >= max(hi for _, hi in RHYTHM_BAND_BLOCKS):
        return min(
            _segment_cosine(rows_a[:, lo:hi].flatten(), rows_b[:, lo:hi].flatten())
            for lo, hi in RHYTHM_BAND_BLOCKS
        )
    return _segment_cosine(rows_a.flatten(), rows_b.flatten())


def segment_similarity(
    views: dict[str, np.ndarray],
    first: tuple[int, int],
    second: tuple[int, int],
) -> float:
    """Duration-normalized similarity of two bar ranges [start, end).

    Aggregation is a weighted *geometric* mean, not an arithmetic one:
    per-view agreement is a probability-like score, and a weighted average
    lets a single dissenting view (e.g. energy seeing a pure gain change
    while harmony, timbre, and rhythm all say "identical") be diluted into
    a join. The geometric mean is a soft AND. Dissent is checked twice:
    any view below FAMILY_VIEW_VETO vetoes outright, and so do
    FAMILY_DUAL_DISSENT_COUNT views below FAMILY_DUAL_DISSENT_THRESHOLD -
    a lone moderate dip can be a measurement artifact (timbre legitimately
    shifts when the same material is played at a different tempo), but two
    independent dimensions agreeing the content changed means it changed.
    Agreement scores clamp to [0, 1] so a zero vetoes instead of breaking
    the logarithm.
    """
    agreements: list[float] = []
    weights: list[float] = []
    for name, features in views.items():
        rows_a = _resample_rows(features[first[0]: first[1]])
        rows_b = _resample_rows(features[second[0]: second[1]])
        agreements.append(_view_agreement(name, rows_a, rows_b))
        weights.append(VIEW_WEIGHTS.get(name, 0.0))
    if any(score < FAMILY_VIEW_VETO for score in agreements):
        return 0.0
    if sum(score < FAMILY_DUAL_DISSENT_THRESHOLD for score in agreements) >= FAMILY_DUAL_DISSENT_COUNT:
        return 0.0
    log_sum = sum(w * np.log(max(s, 1e-6)) for s, w in zip(agreements, weights))
    total = sum(weights)
    if total <= 0.0:
        return 0.0
    combined = float(np.exp(log_sum / total))
    ratio = min(first[1] - first[0], second[1] - second[0]) / max(
        first[1] - first[0], second[1] - second[0]
    )
    return float(combined * max(ratio, LENGTH_RATIO_FLOOR))


def _family_letter(index: int) -> str:
    """A..Z then AA.. (bijective base 26)."""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def assign_families(
    views: dict[str, np.ndarray],
    segments: list[dict[str, Any]],
    bar_density: np.ndarray,
    bar_energy: np.ndarray,
) -> None:
    """Attach family/variant/display_label/descriptors to segments in place.

    ``bar_density``/``bar_energy`` are per-bar curves indexed like the
    segments' bar indices (0 = first analyzed bar).
    """
    energy_floor = (
        float(np.percentile(bar_energy, LOW_ENERGY_PERCENTILE)) if bar_energy.size else 0.0
    )
    density_floor = (
        float(np.percentile(bar_density, 25)) * BREAK_DENSITY_FACTOR
        if bar_density.size
        else 0.0
    )

    letters = 0
    families: list[dict[str, Any]] = []
    for position, segment in enumerate(segments):
        start, end = segment["_start"], segment["_end"]
        mean_energy = float(bar_energy[start:end].mean()) if end > start else 0.0
        mean_density = float(bar_density[start:end].mean()) if end > start else 0.0
        low_energy = bool(bar_energy.size and mean_energy < energy_floor)
        break_like = bool(
            low_energy and bar_density.size and mean_density < density_floor
        )

        descriptors: list[str] = []
        if position == 0:
            descriptors.append("opening")
        if position == len(segments) - 1:
            descriptors.append("ending")
        if low_energy:
            descriptors.append("low-energy")
        if break_like:
            descriptors.append("break-like")

        if break_like:
            family = next((f for f in families if f["name"] == "BREAK"), None)
            if family is None:
                family = {"name": "BREAK", "members": [], "medoid": position}
                families.append(family)
            family["members"].append(position)
            variant = 0
        else:
            best_family: dict[str, Any] | None = None
            best_score = -1.0
            for candidate_family in families:
                if candidate_family["name"] == "BREAK":
                    continue
                medoid = segments[candidate_family["medoid"]]
                score = segment_similarity(
                    views, (medoid["_start"], medoid["_end"]), (start, end)
                )
                if score > best_score:
                    best_score, best_family = score, candidate_family
            if best_family is not None and best_score >= FAMILY_JOIN_THRESHOLD:
                family = best_family
                variant = 0 if best_score >= FAMILY_VARIANT_THRESHOLD else 1
                family["members"].append(position)
            else:
                family = {
                    "name": _family_letter(letters),
                    "members": [position],
                    "medoid": position,
                }
                letters += 1
                families.append(family)
                variant = 0

        segment["family"] = family["name"]
        segment["variant"] = variant
        segment["descriptors"] = descriptors
        segment["mean_energy"] = round(mean_energy, 4)

    # Medoid refresh: the member most similar to the rest of its family.
    for family in families:
        members = family["members"]
        if family["name"] == "BREAK" or len(members) < 2:
            continue
        best_index, best_mean = members[0], -1.0
        for candidate in members:
            anchor = segments[candidate]
            scores = [
                segment_similarity(
                    views,
                    (anchor["_start"], anchor["_end"]),
                    (segments[other]["_start"], segments[other]["_end"]),
                )
                for other in members
                if other != candidate
            ]
            mean_score = float(np.mean(scores)) if scores else 0.0
            if mean_score > best_mean:
                best_index, best_mean = candidate, mean_score
        family["medoid"] = best_index

    # Transition-like: a short segment wedged between two strong boundaries.
    interior_novelty = [seg["_entry_novelty"] for seg in segments[1:]]
    known = [value for value in interior_novelty if value is not None]
    strong_floor = float(np.percentile(known, 75)) if known else float("inf")
    for position, segment in enumerate(segments):
        if segment["bar_count"] > TRANSITION_MAX_BARS:
            continue
        left = segment["_entry_novelty"] if position > 0 else None
        right = (
            segments[position + 1]["_entry_novelty"]
            if position + 1 < len(segments)
            else None
        )
        if (
            left is not None
            and right is not None
            and left >= strong_floor
            and right >= strong_floor
        ):
            segment["descriptors"].append("transition-like")


# ---------------------------------------------------------------- payload

def _fit_curve(values: np.ndarray, count: int) -> np.ndarray:
    """Trim or edge-pad a per-bar curve to exactly ``count`` entries."""
    curve = np.asarray(values, dtype=np.float64).ravel()
    if curve.size == count:
        return curve
    if curve.size == 0:
        return np.zeros(count)
    if curve.size > count:
        return curve[:count]
    return np.concatenate([curve, np.full(count - curve.size, curve[-1])])


def _pair_curve(curve: np.ndarray, pair_count: int, odd_tail: bool) -> np.ndarray:
    pairs = 0.5 * (curve[0:2 * pair_count:2] + curve[1:2 * pair_count:2])
    if odd_tail:
        pairs = np.concatenate([pairs, curve[-1:]])
    return pairs


def analyze_structure_segments(
    features: StructureFeatures,
    duration: float,
    total_bars: int,
    bar_energy: np.ndarray,
    bar_density: np.ndarray,
) -> dict[str, Any] | None:
    """Full segment payload from extracted features, or None when unusable.

    ``bar_energy``/``bar_density`` are per analyzed bar (same order as
    ``features.bar_spans``). ``total_bars`` is the grid's bar count; the final
    segment always extends to it (and to ``duration``) so segments tile the
    whole song even when a terminal bar fragment was dropped from clustering.
    """
    spans = features.bar_spans
    count = len(spans)
    diagnostics: dict[str, Any] = {
        "feature_version": features.diagnostics.get("feature_version"),
        "bars_analyzed": count,
        "views_used": sorted(features.views),
        "boundary_kernel_bars": list(BOUNDARY_KERNELS),
        "minimum_segment_bars": MIN_SEGMENT_BARS,
        "warnings": list(features.diagnostics.get("warnings") or []),
    }
    if count == 0:
        diagnostics["warnings"].append("no bar spans; structure analysis unavailable")
        return None

    views = {
        name: np.asarray(matrix, dtype=np.float64)
        for name, matrix in features.views.items()
    }
    for name, matrix in views.items():
        nonfinite = int(np.count_nonzero(~np.isfinite(matrix)))
        if nonfinite:
            diagnostics["warnings"].append(
                f"view '{name}' contained {nonfinite} non-finite values; analysis refused"
            )
            return None

    energy_curve = _fit_curve(bar_energy, count)
    density_curve = _fit_curve(bar_density, count)

    # Beyond SUPERFRAME_BARS, boundary detection runs on bar pairs; family
    # similarity always uses the full per-bar matrices.
    family_views = views
    fold = count > SUPERFRAME_BARS
    if fold:
        pair_count = count // 2
        odd_tail = bool(count % 2)
        work_views = {
            name: _pair_curve(matrix, pair_count, odd_tail)
            for name, matrix in views.items()
        }
        work_energy = _pair_curve(energy_curve, pair_count, odd_tail)
        work_density = _pair_curve(density_curve, pair_count, odd_tail)
        work_bars = pair_count + (1 if odd_tail else 0)
    else:
        work_views = views
        work_energy = energy_curve
        work_density = density_curve
        work_bars = count

    combined = combine_views(work_views)
    view_novelty = {
        name: checkerboard_novelty(cosine_matrix(matrix), BOUNDARY_KERNELS[0])
        for name, matrix in work_views.items()
    }
    candidates, novelty_map, driver_map = select_boundary_candidates(
        combined, view_novelty
    )
    cuts = segment_with_dp(combined, candidates, novelty_map)

    if fold:
        cut_novelty = {min(2 * cut, count): novelty_map.get(cut, 0.0) for cut in cuts}
        cut_drivers = {min(2 * cut, count): driver_map.get(cut, {}) for cut in cuts}
    else:
        cut_novelty = dict(novelty_map)
        cut_drivers = dict(driver_map)
    bar_cuts = sorted({0, count, *(cut for cut in cut_novelty if 0 < cut < count)})

    diagnostics["bars_folded"] = fold
    diagnostics["boundary_candidates"] = len(candidates)
    diagnostics["segments_inferred"] = len(bar_cuts) - 1

    segments: list[dict[str, Any]] = []
    for position in range(len(bar_cuts) - 1):
        start, end = bar_cuts[position], bar_cuts[position + 1]
        segments.append({
            "_start": start,
            "_end": end,
            "_entry_novelty": cut_novelty.get(start),
            "start_bar": spans[start].bar,
            "end_bar": spans[end - 1].bar,
            # A pickup or leading silence can put the first downbeat after
            # zero. Structural spans still partition the complete source, so
            # the first segment owns that prefix.
            "start_time": 0.0 if start == 0 else round(spans[start].start_time, 6),
            "end_time": round(spans[end - 1].end_time, 6),
            "bar_count": spans[end - 1].bar - spans[start].bar + 1,
        })
    # The final segment owns the grid tail (terminal fragments included), and
    # its end_time is the track duration - the IR contract makes end_time
    # exclusive except for the final segment, where it tiles the whole file.
    if segments:
        if total_bars > segments[-1]["end_bar"]:
            segments[-1]["end_bar"] = total_bars
            segments[-1]["bar_count"] = segments[-1]["end_bar"] - segments[-1]["start_bar"] + 1
        segments[-1]["end_time"] = round(float(duration), 6)

    boundaries: list[dict[str, Any]] = []
    for cut in bar_cuts[1:-1]:  # interior cuts only; spans[cut] needs cut < count
        boundaries.append({
            "bar": spans[cut].bar,
            "time": round(spans[cut].start_time, 6),
            "novelty": round(cut_novelty.get(cut, 0.0), 4),
            "drivers": cut_drivers.get(cut, {}),
        })

    assign_families(family_views, segments, density_curve, energy_curve)

    for index, segment in enumerate(segments):
        variant = segment["variant"]
        family = segment["family"]
        segment["id"] = f"segment-{index + 1:03d}"
        segment["index"] = index
        segment["display_label"] = (
            family if (variant == 0 or family == "BREAK") else f"{family}\u2032"
        )

    repetitions: list[dict[str, Any]] = []
    by_family: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        by_family.setdefault(segment["family"], []).append(segment)
    for family, members in by_family.items():
        if len(members) < 2:
            continue
        scores = [
            segment_similarity(
                family_views,
                (members[i]["_start"], members[i]["_end"]),
                (members[j]["_start"], members[j]["_end"]),
            )
            for i in range(len(members))
            for j in range(i + 1, len(members))
        ]
        repetitions.append({
            "family": family,
            "segment_ids": [member["id"] for member in members],
            "mean_similarity": round(float(np.mean(scores)), 4) if scores else None,
        })

    # Per-bar family labels for the legacy bars list (1-based bars).
    bar_families: list[str | None] = [None] * (total_bars + 1)
    for segment in segments:
        for bar in range(segment["start_bar"], segment["end_bar"] + 1):
            if 1 <= bar <= total_bars:
                bar_families[bar] = segment["family"]
    tail_family = segments[-1]["family"] if segments else None
    for bar in range(1, total_bars + 1):
        if bar_families[bar] is None:
            bar_families[bar] = tail_family

    for segment in segments:
        segment.pop("_start", None)
        segment.pop("_end", None)
        segment.pop("_entry_novelty", None)

    diagnostics["families_used"] = sorted(by_family)
    return {
        "method": STRUCTURE_METHOD,
        "segments": segments,
        "boundaries": boundaries,
        "repetitions": repetitions,
        "form": "-".join(segment["display_label"] for segment in segments),
        "bar_families": bar_families[1:],
        "diagnostics": diagnostics,
    }


__all__ = [
    "BOUNDARY_KERNELS",
    "FAMILY_JOIN_THRESHOLD",
    "MIN_SEGMENT_BARS",
    "STRUCTURE_METHOD",
    "VIEW_WEIGHTS",
    "analyze_structure_segments",
    "assign_families",
    "checkerboard_novelty",
    "combine_views",
    "cosine_matrix",
    "segment_similarity",
    "segment_with_dp",
    "select_boundary_candidates",
]
