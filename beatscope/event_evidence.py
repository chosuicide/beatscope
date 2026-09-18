"""Deterministic multi-view event evidence (v0.11 Round 1).

A dormant, pure builder: it consumes an already validated Rhythm IR v4
project and derives independent, measured evidence views for every onset -
local band contrast, spectral distribution, temporal context, optional
metric context, optional structural context, and lossless short-run group
shape. It never re-reads audio, never runs a second analysis pass, and never
changes how any event is timed: the bundle references onsets by ``onset_id``
only, and consumers resolve time from the original Rhythm IR onset.

Round 1 boundaries (plan sections 2 and 5):

- no ``primary``/``secondary``/``texture`` output and no composite
  importance score - those belong to a later, task-aware layer;
- no public analysis, runtime, MCP, or export path calls this module yet;
- the bundle is an internal contract frozen by snapshots and validation.

Determinism: the same validated project yields byte-identical canonical
JSON on every call and process on one platform. No wall clock, no RNG, no
unordered iteration in output, no mutable global state.
"""
from __future__ import annotations

import bisect
import json
import math
from typing import Any

import numpy as np

from .schema import validate_rhythm_v4

EVENT_EVIDENCE_SCHEMA = "beatscope-event-evidence-1"
EVENT_EVIDENCE_METHOD = "multiview-local-evidence-v1"
LOCAL_RADIUS_SECONDS = 2.0
LOCAL_SCALE_FLOOR = 0.08
GROUP_MAX_GAP_SECONDS = 0.18
GROUP_MAX_DURATION_SECONDS = 1.50
GROUP_MIN_EVENTS = 3

BANDS = ("all", "low", "mid", "high")
SPECTRAL_BANDS = ("low", "mid", "high")
DOMINANT_BANDS = ("low", "mid", "high", "mixed")

# Keys that may never appear anywhere in a bundle: timestamps (one canonical
# clock lives in the Rhythm IR onset) and premature decision vocabulary
# (plan sections 4.1 and 4.3).
FORBIDDEN_KEYS = frozenset({
    "time",
    "raw_time",
    "quantized_time",
    "snapped_time",
    "score",
    "confidence",
    "importance",
    "salience",
    "primary",
    "secondary",
    "texture",
    "kick",
    "snare",
    "hihat",
    "808",
    "created_at",
})

PARAMETERS: dict[str, float | int] = {
    "local_radius_seconds": LOCAL_RADIUS_SECONDS,
    "local_scale_floor": LOCAL_SCALE_FLOOR,
    "group_max_gap_seconds": GROUP_MAX_GAP_SECONDS,
    "group_max_duration_seconds": GROUP_MAX_DURATION_SECONDS,
    "group_min_events": GROUP_MIN_EVENTS,
}


class InvalidEventEvidenceSource(ValueError):
    """Raised when a project or bundle cannot serve event-evidence work."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _round6(value: Any) -> float:
    parsed = round(float(value), 6)
    if parsed == 0.0:
        return 0.0  # normalize -0.0 so canonical bytes stay stable
    return parsed


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


# --------------------------------------------------------------- formulas

def midrank(value: float, values: np.ndarray) -> float:
    """Midrank percentile of ``value`` inside ``values`` (plan section 7.2)."""
    less = int(np.count_nonzero(values < value))
    equal = int(np.count_nonzero(values == value))
    return (less + 0.5 * equal) / len(values)


def _sorted_quantile(ordered: np.ndarray, quantile: float) -> float:
    """Linear-interpolation quantile of an ascending array.

    Matches ``numpy.quantile`` with its default ``linear`` method; kept as an
    explicit helper so the interpolation behavior is pinned by unit tests.
    """
    count = len(ordered)
    if count == 1:
        return float(ordered[0])
    position = quantile * (count - 1)
    lower = int(math.floor(position))
    upper = min(lower + 1, count - 1)
    fraction = position - lower
    return float(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction)


def contrast(value: float, values: np.ndarray) -> float:
    """Robust local contrast against the 0.50/0.90 quantile pair (plan 7.3)."""
    ordered = np.sort(values)
    median = _sorted_quantile(ordered, 0.50)
    upper = _sorted_quantile(ordered, 0.90)
    scale = max(upper - median, LOCAL_SCALE_FLOOR)
    return min(4.0, max(0.0, (float(value) - median) / scale))


def _nearest_index(times: list[float], target: float) -> int:
    """Index of the nearest time; an exact tie chooses the earlier entry."""
    position = bisect.bisect_left(times, target)
    if position == 0:
        return 0
    if position == len(times):
        return len(times) - 1
    if times[position] == target:
        return position
    left_distance = target - times[position - 1]
    right_distance = times[position] - target
    if right_distance < left_distance:
        return position
    return position - 1


# ------------------------------------------------------------- validation

def _walk_forbidden_keys(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            label = f"{path}.{key}"
            if isinstance(key, str) and key in FORBIDDEN_KEYS:
                errors.append(f"{label}: forbidden key '{key}'")
            _walk_forbidden_keys(item, label, errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden_keys(item, f"{path}[{index}]", errors)


def _require_finite_number(container: dict[str, Any], key: str, label: str, errors: list[str]) -> None:
    if key not in container:
        errors.append(f"{label}.{key} is missing")
    elif not _finite(container[key]):
        errors.append(f"{label}.{key} must be a finite number")


def _require_band_map(container: dict[str, Any], key: str, label: str, upper: float,
                      errors: list[str]) -> None:
    value = container.get(key)
    if not isinstance(value, dict) or set(value) != set(BANDS):
        errors.append(f"{label}.{key} must map exactly the bands {', '.join(BANDS)}")
        return
    for band in BANDS:
        entry = value[band]
        if not _finite(entry) or not 0.0 <= float(entry) <= upper:
            errors.append(f"{label}.{key}.{band} must be a finite number in [0, {upper}]")


def _validate_event_record(event: Any, label: str, errors: list[str]) -> None:
    if not isinstance(event, dict):
        errors.append(f"{label} must be an object")
        return
    expected_keys = {"onset_id", "local", "spectral", "temporal", "metric", "structure", "group_id"}
    if set(event) != expected_keys:
        missing = sorted(expected_keys - set(event))
        unexpected = sorted(set(event) - expected_keys)
        errors.append(f"{label} key set mismatch (missing {missing}, unexpected {unexpected})")
        return
    onset_id = event["onset_id"]
    if not isinstance(onset_id, int) or isinstance(onset_id, bool) or onset_id < 1:
        errors.append(f"{label}.onset_id must be a positive integer")

    local = event["local"]
    if not isinstance(local, dict) or set(local) != {"sample_count", "rank", "contrast"}:
        errors.append(f"{label}.local must hold exactly sample_count, rank, contrast")
    else:
        if not isinstance(local["sample_count"], int) or isinstance(local["sample_count"], bool) \
                or local["sample_count"] < 1:
            errors.append(f"{label}.local.sample_count must be a positive integer")
        _require_band_map(local, "rank", label, 1.0, errors)
        _require_band_map(local, "contrast", label, 4.0, errors)

    spectral = event["spectral"]
    spectral_keys = {"share", "focus", "active_band_count", "dominant_band"}
    if not isinstance(spectral, dict) or set(spectral) != spectral_keys:
        errors.append(f"{label}.spectral must hold exactly share, focus, active_band_count, dominant_band")
    else:
        share = spectral["share"]
        if not isinstance(share, dict) or set(share) != set(SPECTRAL_BANDS):
            errors.append(f"{label}.spectral.share must map exactly the bands low, mid, high")
        else:
            values = [share[band] for band in SPECTRAL_BANDS]
            if not all(_finite(entry) and 0.0 <= float(entry) <= 1.0 for entry in values):
                errors.append(f"{label}.spectral.share values must be finite numbers in [0, 1]")
            elif all(float(entry) == 0.0 for entry in values):
                pass  # silent onset: every share is legitimately zero
            elif abs(sum(float(entry) for entry in values) - 1.0) > 1e-6:
                errors.append(f"{label}.spectral.share values must sum to 1 within 1e-6")
        if not _finite(spectral["focus"]) or not 0.0 <= float(spectral["focus"]) <= 1.0:
            errors.append(f"{label}.spectral.focus must be a finite number in [0, 1]")
        active = spectral["active_band_count"]
        if not isinstance(active, int) or isinstance(active, bool) or not 0 <= active <= 3:
            errors.append(f"{label}.spectral.active_band_count must be an integer in 0..3")
        if spectral["dominant_band"] not in DOMINANT_BANDS:
            errors.append(f"{label}.spectral.dominant_band must be one of {', '.join(DOMINANT_BANDS)}")

    temporal = event["temporal"]
    temporal_keys = {"events_per_second", "previous_gap_seconds", "next_gap_seconds", "isolatedness"}
    if not isinstance(temporal, dict) or set(temporal) != temporal_keys:
        errors.append(f"{label}.temporal must hold exactly the four temporal fields")
    else:
        _require_finite_number(temporal, "events_per_second", label, errors)
        if _finite(temporal.get("events_per_second")) and float(temporal["events_per_second"]) < 0:
            errors.append(f"{label}.temporal.events_per_second must be non-negative")
        for gap_key in ("previous_gap_seconds", "next_gap_seconds"):
            gap = temporal[gap_key]
            if gap is not None and (not _finite(gap) or float(gap) < 0):
                errors.append(f"{label}.temporal.{gap_key} must be null or a non-negative number")
        if not _finite(temporal["isolatedness"]) or not 0.0 <= float(temporal["isolatedness"]) <= 1.0:
            errors.append(f"{label}.temporal.isolatedness must be a finite number in [0, 1]")

    metric = event["metric"]
    if metric is not None:
        metric_keys = {"beat_index", "beat_in_bar", "downbeat", "offset_seconds", "offset_ratio"}
        if not isinstance(metric, dict) or set(metric) != metric_keys:
            errors.append(f"{label}.metric must be null or hold exactly the five metric fields")
        else:
            for int_key in ("beat_index", "beat_in_bar"):
                entry = metric[int_key]
                if not isinstance(entry, int) or isinstance(entry, bool) or entry < (0 if int_key == "beat_index" else 1):
                    errors.append(f"{label}.metric.{int_key} must be a valid integer")
            if not isinstance(metric["downbeat"], bool):
                errors.append(f"{label}.metric.downbeat must be a boolean")
            _require_finite_number(metric, "offset_seconds", label, errors)
            ratio = metric["offset_ratio"]
            if ratio is not None and not _finite(ratio):
                errors.append(f"{label}.metric.offset_ratio must be null or a finite number")

    structure = event["structure"]
    if structure is not None:
        structure_keys = {"boundary_index", "distance_seconds", "novelty"}
        if not isinstance(structure, dict) or set(structure) != structure_keys:
            errors.append(f"{label}.structure must be null or hold exactly the three structure fields")
        else:
            index = structure["boundary_index"]
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                errors.append(f"{label}.structure.boundary_index must be a non-negative integer")
            _require_finite_number(structure, "distance_seconds", label, errors)
            if _finite(structure.get("distance_seconds")) and float(structure["distance_seconds"]) < 0:
                errors.append(f"{label}.structure.distance_seconds must be non-negative")
            if not _finite(structure["novelty"]) or not 0.0 <= float(structure["novelty"]) <= 1.0:
                errors.append(f"{label}.structure.novelty must be a finite number in [0, 1]")

    group_id = event["group_id"]
    if group_id is not None and (not isinstance(group_id, int) or isinstance(group_id, bool) or group_id < 1):
        errors.append(f"{label}.group_id must be null or a positive integer")


def _validate_group_record(group: Any, label: str, errors: list[str]) -> None:
    if not isinstance(group, dict):
        errors.append(f"{label} must be an object")
        return
    expected_keys = {"id", "onset_ids", "span_seconds", "intervals_seconds", "interval_trend",
                     "density_hz", "dominant_band_path"}
    if set(group) != expected_keys:
        errors.append(f"{label} key set mismatch")
        return
    if not isinstance(group["id"], int) or isinstance(group["id"], bool) or group["id"] < 1:
        errors.append(f"{label}.id must be a positive integer")
    members = group["onset_ids"]
    if not isinstance(members, list) or not members \
            or not all(isinstance(member, int) and not isinstance(member, bool) and member >= 1 for member in members):
        errors.append(f"{label}.onset_ids must be a non-empty list of positive integers")
        return
    if len(set(members)) != len(members):
        errors.append(f"{label}.onset_ids must not repeat a member")
    intervals = group["intervals_seconds"]
    if not isinstance(intervals, list) or len(intervals) != len(members) - 1 \
            or not all(_finite(interval) and float(interval) >= 0 for interval in intervals):
        errors.append(f"{label}.intervals_seconds must list member_count - 1 non-negative numbers")
    _require_finite_number(group, "span_seconds", label, errors)
    if _finite(group.get("span_seconds")) and float(group["span_seconds"]) < 0:
        errors.append(f"{label}.span_seconds must be non-negative")
    _require_finite_number(group, "interval_trend", label, errors)
    _require_finite_number(group, "density_hz", label, errors)
    path = group["dominant_band_path"]
    if not isinstance(path, list) or len(path) != len(members) \
            or not all(band in DOMINANT_BANDS for band in path):
        errors.append(f"{label}.dominant_band_path must name one band per member")


def _bundle_shape_errors(bundle: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(bundle, dict):
        return ["bundle must be a JSON object"]
    expected_keys = {"schema", "method", "project_id", "parameters", "events", "groups", "diagnostics"}
    if set(bundle) != expected_keys:
        missing = sorted(expected_keys - set(bundle))
        unexpected = sorted(set(bundle) - expected_keys)
        errors.append(f"bundle key set mismatch (missing {missing}, unexpected {unexpected})")
    if bundle.get("schema") != EVENT_EVIDENCE_SCHEMA:
        errors.append(f"schema must be {EVENT_EVIDENCE_SCHEMA!r}")
    if bundle.get("method") != EVENT_EVIDENCE_METHOD:
        errors.append(f"method must be {EVENT_EVIDENCE_METHOD!r}")
    if not isinstance(bundle.get("project_id"), str):
        errors.append("project_id must be a string")
    if bundle.get("parameters") != PARAMETERS:
        errors.append("parameters must equal the frozen method parameters")
    events = bundle.get("events")
    if not isinstance(events, list):
        errors.append("events must be a list")
        return errors
    groups = bundle.get("groups")
    if not isinstance(groups, list):
        errors.append("groups must be a list")
        return errors
    for index, event in enumerate(events):
        _validate_event_record(event, f"events[{index}]", errors)
    for index, group in enumerate(groups):
        _validate_group_record(group, f"groups[{index}]", errors)
    diagnostics = bundle.get("diagnostics")
    diagnostic_keys = {"onset_count", "group_count", "beat_context_available", "structure_context_available"}
    if not isinstance(diagnostics, dict) or set(diagnostics) != diagnostic_keys:
        errors.append("diagnostics must hold exactly onset_count, group_count, and the two context flags")
    else:
        if diagnostics.get("onset_count") != len(events) or isinstance(diagnostics.get("onset_count"), bool):
            errors.append("diagnostics.onset_count must equal the event count")
        if diagnostics.get("group_count") != len(groups) or isinstance(diagnostics.get("group_count"), bool):
            errors.append("diagnostics.group_count must equal the group count")
        for flag in ("beat_context_available", "structure_context_available"):
            if not isinstance(diagnostics[flag], bool):
                errors.append(f"diagnostics.{flag} must be a boolean")
    _walk_forbidden_keys(bundle, "bundle", errors)
    return errors


def validate_event_evidence(bundle: Any, project: dict[str, Any]) -> list[str]:
    """Validate a bundle against its contract and the source project."""
    errors = _bundle_shape_errors(bundle)
    if errors:
        return errors
    events = bundle["events"]
    groups = bundle["groups"]

    if bundle.get("project_id") != project.get("project_id"):
        errors.append("project_id must match the source project")
    if bundle.get("parameters") != PARAMETERS:
        errors.append("parameters must equal the frozen method parameters")

    expected_ids = [onset.get("id") for onset in project.get("onsets", [])]
    actual_ids = [event["onset_id"] for event in events]
    if actual_ids != expected_ids:
        errors.append("event onset_ids must equal the project's onset ids in project order")

    diagnostics = bundle["diagnostics"]
    if diagnostics["beat_context_available"] != bool(project.get("beats")):
        errors.append("diagnostics.beat_context_available must reflect the project's beats")
    boundaries = project.get("patterns", {}).get("boundaries")
    if diagnostics["structure_context_available"] != bool(boundaries):
        errors.append("diagnostics.structure_context_available must reflect the project's boundaries")

    known_ids = set(expected_ids)
    onset_positions = {onset_id: position for position, onset_id in enumerate(expected_ids)}
    claimed: dict[int, int] = {}
    expected_group_ids = list(range(1, len(groups) + 1))
    actual_group_ids = [group["id"] for group in groups]
    if actual_group_ids != expected_group_ids:
        errors.append("group ids must be one-based and sequential in group order")

    previous_first_position = -1
    for position, group in enumerate(groups):
        members = group["onset_ids"]
        if len(members) < GROUP_MIN_EVENTS:
            errors.append(
                f"groups[{position}] must contain at least {GROUP_MIN_EVENTS} onset ids"
            )
        member_positions = [onset_positions[member] for member in members if member in onset_positions]
        if len(member_positions) == len(members):
            if member_positions != sorted(member_positions):
                errors.append(f"groups[{position}].onset_ids must follow project onset order")
            if member_positions and member_positions != list(
                    range(member_positions[0], member_positions[0] + len(member_positions))):
                errors.append(f"groups[{position}].onset_ids must be consecutive project onsets")
            if member_positions and member_positions[0] <= previous_first_position:
                errors.append("groups must be ordered by their first member")
            if member_positions:
                previous_first_position = member_positions[0]
        for member in members:
            if member not in known_ids:
                errors.append(f"groups[{position}] references unknown onset id {member}")
            elif member in claimed:
                errors.append(f"onset id {member} belongs to groups {claimed[member]} and {group['id']}")
            else:
                claimed[member] = group["id"]
    for event in events:
        onset_id = event["onset_id"]
        group_id = event["group_id"]
        expected_group_id = claimed.get(onset_id)
        if group_id != expected_group_id:
            errors.append(
                f"event {onset_id} group_id must match group membership "
                f"({expected_group_id!r}, got {group_id!r})"
            )
    return errors


# ----------------------------------------------------------------- builder

def _spectral_view(bands: dict[str, float]) -> dict[str, Any]:
    low, mid, high = (float(bands[band]) for band in SPECTRAL_BANDS)
    total = low + mid + high
    if total <= 1e-12:
        return {
            "share": {band: 0.0 for band in SPECTRAL_BANDS},
            "focus": 0.0,
            "active_band_count": 0,
            "dominant_band": "mixed",
        }
    shares = {band: float(bands[band]) / total for band in SPECTRAL_BANDS}
    entropy = -sum(share * math.log(share) for share in shares.values() if share > 0.0) / math.log(3.0)
    focus = min(1.0, max(0.0, 1.0 - entropy))
    active = sum(1 for share in shares.values() if share >= 0.20)
    ordered = sorted(shares.items(), key=lambda item: (-item[1], SPECTRAL_BANDS.index(item[0])))
    dominant = "mixed"
    if ordered[0][1] - ordered[1][1] >= 0.05:
        dominant = ordered[0][0]
    rounded = {band: _round6(shares[band]) for band in SPECTRAL_BANDS}
    # Three 6-decimal roundings can drift up to 1.5e-6 from 1.0; let the
    # dominant share absorb the residual so the published values still sum
    # to 1 within the contract tolerance.
    residual = 1.0 - sum(rounded.values())
    rounded[ordered[0][0]] = _round6(rounded[ordered[0][0]] + residual)
    return {
        "share": rounded,
        "focus": _round6(focus),
        "active_band_count": active,
        "dominant_band": dominant,
    }


def _metric_view(onset_time: float, beats: list[dict[str, Any]], beat_times: list[float]) -> dict[str, Any] | None:
    if not beat_times:
        return None
    position = bisect.bisect_left(beat_times, onset_time)
    if position < len(beat_times) and beat_times[position] == onset_time:
        index = position
    else:
        index = _nearest_index(beat_times, onset_time)
    offset_seconds = onset_time - beat_times[index]
    if index > 0:
        span = beat_times[index] - beat_times[index - 1]
    elif len(beat_times) > 1:
        span = beat_times[1] - beat_times[0]
    else:
        span = 0.0  # a single measured beat defines no interval
    beat = beats[index]
    return {
        "beat_index": index,
        "beat_in_bar": int(beat["beat_in_bar"]),
        "downbeat": bool(beat["downbeat"]),
        "offset_seconds": _round6(offset_seconds),
        "offset_ratio": _round6(offset_seconds / span) if span > 0.0 else None,
    }


def _structure_view(onset_time: float, boundaries: list[dict[str, Any]],
                    boundary_times: list[float]) -> dict[str, Any] | None:
    if not boundary_times:
        return None
    index = _nearest_index(boundary_times, onset_time)
    novelty = boundaries[index].get("novelty")
    if not _finite(novelty):
        return None  # say nothing rather than invent a 0
    return {
        "boundary_index": index,
        "distance_seconds": _round6(abs(onset_time - boundary_times[index])),
        "novelty": _round6(novelty),
    }


def _group_views(times: list[float], ids: list[int], dominant_bands: list[str]) -> tuple[list[dict[str, Any]], list[int | None]]:
    groups: list[dict[str, Any]] = []
    group_ids: list[int | None] = [None] * len(times)
    total = len(times)
    start = 0
    while start < total:
        end = start
        while end + 1 < total \
                and times[end + 1] - times[end] <= GROUP_MAX_GAP_SECONDS \
                and times[end + 1] - times[start] <= GROUP_MAX_DURATION_SECONDS:
            end += 1
        count = end - start + 1
        if count >= GROUP_MIN_EVENTS:
            intervals = [times[start + step + 1] - times[start + step] for step in range(count - 1)]
            span = times[end] - times[start]
            if len(intervals) < 2:
                trend: float = 0.0
            else:
                mean_x = (len(intervals) - 1) / 2.0
                mean_y = sum(intervals) / len(intervals)
                covariance = sum((index - mean_x) * (value - mean_y) for index, value in enumerate(intervals))
                variance = sum((index - mean_x) ** 2 for index in range(len(intervals)))
                trend = covariance / variance if variance > 0 else 0.0
            group_id = len(groups) + 1
            groups.append({
                "id": group_id,
                "onset_ids": [ids[index] for index in range(start, end + 1)],
                "span_seconds": _round6(span),
                "intervals_seconds": [_round6(interval) for interval in intervals],
                "interval_trend": _round6(trend),
                "density_hz": _round6((count - 1) / max(span, 1e-9)),
                "dominant_band_path": [dominant_bands[index] for index in range(start, end + 1)],
            })
            for index in range(start, end + 1):
                group_ids[index] = group_id
        start = end + 1
    return groups, group_ids


def build_event_evidence(project: dict[str, Any]) -> dict[str, Any]:
    """Derive the deterministic event-evidence bundle for a validated project."""
    if not isinstance(project, dict):
        raise InvalidEventEvidenceSource(["project must be a dictionary"])
    source_errors = validate_rhythm_v4(project)
    if source_errors:
        raise InvalidEventEvidenceSource(source_errors)

    onsets = project["onsets"]
    times = [float(onset["time"]) for onset in onsets]
    ids = [int(onset["id"]) for onset in onsets]
    band_arrays = {
        band: np.array([float(onset["bands"][band]) for onset in onsets], dtype=np.float64)
        for band in BANDS
    }
    duration = float(project["source"]["duration"])
    beats = project.get("beats") or []
    beat_times = [float(beat["time"]) for beat in beats]
    boundaries = project.get("patterns", {}).get("boundaries") or []
    boundary_times = [float(boundary["time"]) for boundary in boundaries]

    events: list[dict[str, Any]] = []
    dominant_bands: list[str] = []
    for index, onset_time in enumerate(times):
        low = bisect.bisect_left(times, onset_time - LOCAL_RADIUS_SECONDS)
        high = bisect.bisect_right(times, onset_time + LOCAL_RADIUS_SECONDS)
        sample_count = high - low
        window_seconds = max(min(duration, onset_time + LOCAL_RADIUS_SECONDS)
                             - max(0.0, onset_time - LOCAL_RADIUS_SECONDS), 1e-9)

        rank: dict[str, float] = {}
        contrast_view: dict[str, float] = {}
        for band in BANDS:
            window = band_arrays[band][low:high]
            value = float(band_arrays[band][index])
            rank[band] = _round6(midrank(value, window))
            contrast_view[band] = _round6(contrast(value, window))

        spectral = _spectral_view(onsets[index]["bands"])
        dominant_bands.append(spectral["dominant_band"])

        previous_gap = times[index] - times[index - 1] if index > 0 else None
        next_gap = times[index + 1] - times[index] if index + 1 < len(times) else None
        # ``0.0`` is a real gap when two band events share a timestamp; do
        # not treat it as a missing neighbor via truthiness.
        previous_space = 2.0 if previous_gap is None else previous_gap
        next_space = 2.0 if next_gap is None else next_gap
        isolatedness = min(previous_space, next_space) / 1.0

        events.append({
            "onset_id": ids[index],
            "local": {
                "sample_count": sample_count,
                "rank": rank,
                "contrast": contrast_view,
            },
            "spectral": spectral,
            "temporal": {
                "events_per_second": _round6(sample_count / window_seconds),
                "previous_gap_seconds": None if previous_gap is None else _round6(previous_gap),
                "next_gap_seconds": None if next_gap is None else _round6(next_gap),
                "isolatedness": _round6(min(1.0, max(0.0, isolatedness))),
            },
            "metric": _metric_view(onset_time, beats, beat_times),
            "structure": _structure_view(onset_time, boundaries, boundary_times),
            "group_id": None,
        })

    groups, group_ids = _group_views(times, ids, dominant_bands)
    for event, group_id in zip(events, group_ids, strict=True):
        event["group_id"] = group_id

    bundle = {
        "schema": EVENT_EVIDENCE_SCHEMA,
        "method": EVENT_EVIDENCE_METHOD,
        "project_id": project["project_id"],
        "parameters": dict(PARAMETERS),
        "events": events,
        "groups": groups,
        "diagnostics": {
            "onset_count": len(events),
            "group_count": len(groups),
            "beat_context_available": bool(beats),
            "structure_context_available": bool(boundaries),
        },
    }
    internal_errors = validate_event_evidence(bundle, project)
    if internal_errors:
        raise InvalidEventEvidenceSource(internal_errors)
    return bundle


def canonical_event_evidence_bytes(bundle: dict[str, Any]) -> bytes:
    """Serialize a valid bundle to deterministic UTF-8 JSON bytes."""
    errors = _bundle_shape_errors(bundle)
    if errors:
        raise ValueError("invalid event-evidence bundle: " + "; ".join(errors))
    return (json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


__all__ = [
    "EVENT_EVIDENCE_METHOD",
    "EVENT_EVIDENCE_SCHEMA",
    "InvalidEventEvidenceSource",
    "build_event_evidence",
    "canonical_event_evidence_bytes",
    "validate_event_evidence",
]
