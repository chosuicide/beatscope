"""Human-chart parsing, alignment, and chart-consensus weak labels (v0.11 R2).

A dormant dataset-construction module: it turns operator-provided StepMania
(``.sm``/``.ssc``) and osu! (``.osu``) charts into onset-ID-only weak labels
that describe how consistently human authors retained each detected BeatScope
onset across difficulty densities.

Hard boundaries (v0.11 Round 2 plan sections 1-3):

- chart timestamps are a private annotation layer; the Round 1 evidence
  bundle keeps its no-timestamp rule, and label records never carry a chart
  or onset time;
- the chart grid is never the output clock: markers are aligned to existing
  BeatScope onsets, never snapped, merged, created, or deleted;
- unsupported timing or modes raise explicit errors with stable codes
  instead of approximate conversions;
- one malformed chart never crashes a corpus build; it is excluded with a
  reason and the song group is re-evaluated.

This module owns parsing, timing conversion, normalization, song grouping,
chart deduplication, exact monotone alignment, weak labels, preference pairs,
and deterministic song-level splitting. ``event_ranker.py`` owns features,
training, evaluation, and the portable model.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from pathlib import Path
from typing import Any

CHART_CONTRACT = "beatscope-human-chart-1"
WEAK_LABEL_SCHEMA = "beatscope-response-labels-1"
DATASET_SCHEMA = "beatscope-response-ranking-dataset-1"

ALIGNMENT_TOLERANCE_SECONDS = 0.050
SIMULTANEOUS_MARKER_TOLERANCE_SECONDS = 0.001
COINCIDENT_ONSET_TOLERANCE_SECONDS = 0.001
MIN_DIFFICULTIES_PER_SONG = 3
MIN_SONGS = 24
MIN_PAIR_SUPPORT_GAP = 0.34
MAX_PAIRS_PER_EVENT = 8
MAX_LOCALITY_SECONDS = 4.0
MIN_CHART_MATCH_RATE = 0.60
MAX_P95_RESIDUAL_SECONDS = 0.040
V2_MAX_P95_RESIDUAL_SECONDS = 0.025
MAX_DURATION_DRIFT_SECONDS = 0.250
MIN_UNIQUE_MARKERS_PER_CHART = 2
SPLIT_SALT = "beatscope-v011-split:"
VALIDATION_FRACTION = 0.15
TEST_FRACTION = 0.15
DEVELOPMENT_VALIDATION_FRACTION = 0.25
# Round 2-B corpus minimums (v0.11 Round 2-B plan section 3.2).
MIN_DEV_SONGS = 32
MIN_DEV_SOURCES = 2
MIN_DEV_CHARTS = 96
MIN_DEV_VALIDATION_SONGS = 8
CODE_CHART_HASH_ACROSS_SPLITS = "chart_hash_across_splits"
CODE_TIMELINE_HASH_ACROSS_SPLITS = "timeline_hash_across_splits"
CODE_CONSUMED_V2_ARTIFACT = "consumed_v2_artifact"
CODE_CONSUMED_V2_TEST_SONG = "consumed_v2_test_song"
# Consumed historical evaluation (v0.11 Round 2-B plan section 1.3).  These
# artifacts and the test partition behind them may never select, tune, or
# promote another candidate.
CONSUMED_V2_ARTIFACTS = (
    "78282ab15c3594ee4bd4aa4bc46e4494366615ee9b254db8c657192ecf2e006a",
    "e97e9faa994f14cdef93d3baaf03550ec24b60af694553ea28611f737c29b5d0",
    "b089fcc3035e02a4279f36580b256ea1e57c9a96259329b7d2936118e76889fb",
    "6a74d48a90481ada2792a2f9d4e1cad786bf7a1b08aa74a0ca55b25212570052",
)
MIN_CALIBRATION_CHARTS = 3
MAX_CALIBRATION_OFFSET_SECONDS = 0.035
MAX_CALIBRATION_MAD_SECONDS = 0.010

# Chart exclusion / error codes (plan section 19).
CODE_UNSUPPORTED_CHART_FORMAT = "unsupported_chart_format"
CODE_UNSUPPORTED_CHART_MODE = "unsupported_chart_mode"
CODE_UNSUPPORTED_TIMING_FEATURE = "unsupported_timing_feature"
CODE_MALFORMED_CHART = "malformed_chart"
CODE_MISSING_AUDIO = "missing_audio"
CODE_AUDIO_HASH_MISMATCH = "audio_hash_mismatch"
CODE_INSUFFICIENT_UNIQUE_DIFFICULTIES = "insufficient_unique_difficulties"
CODE_ALIGNMENT_MATCH_RATE_TOO_LOW = "alignment_match_rate_too_low"
CODE_ALIGNMENT_RESIDUAL_TOO_HIGH = "alignment_residual_too_high"
CODE_DURATION_DRIFT_TOO_HIGH = "duration_drift_too_high"
CODE_DUPLICATE_AUDIO_ACROSS_SPLITS = "duplicate_audio_across_splits"
CODE_UNKNOWN_LICENSE = "unknown_license"


class ChartLabelError(ValueError):
    """Raised for a chart, audio, or corpus problem with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# ---------------------------------------------------------------- shared utils


def canonical_json_text(payload: Any) -> str:
    """Deterministic JSON text: UTF-8, indent 2, no NaN, final newline."""
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def round6(value: float) -> float:
    parsed = round(float(value), 6)
    return 0.0 if parsed == 0.0 else parsed


def marker_sequence_hash(markers: list[float]) -> str:
    canonical = json.dumps([round6(marker) for marker in markers], separators=(",", ":"))
    return sha256_text(canonical)


def collapse_simultaneous(seconds: list[float], tolerance: float) -> list[float]:
    """Collapse markers chained within ``tolerance`` onto the earliest instant."""
    collapsed: list[float] = []
    for value in seconds:
        if collapsed and value - collapsed[-1] <= tolerance:
            continue
        collapsed.append(value)
    return collapsed


def _percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        return 0.0
    position = quantile * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def audio_fingerprint(duration: float, onset_times: list[float]) -> str:
    """Coarse re-encode-surviving duplicate-encode probe (plan section 9.1).

    Counts onsets in 5-second buckets from the analyzed project. Different
    encodes of one master land on near-identical bucket counts; the audit
    treats an exact bucket match plus a duration within 0.25 s as a possible
    duplicate. This is a conservative grouping hint, never an identity claim.
    """
    buckets: dict[int, int] = {}
    for time_value in onset_times:
        bucket = int(time_value // 5.0)
        buckets[bucket] = buckets.get(bucket, 0) + 1
    payload = json.dumps({
        "duration_half_seconds": int(round(duration * 2.0)),
        "buckets": [buckets.get(index, 0) for index in range(max(buckets, default=0) + 1)],
    }, separators=(",", ":"))
    return sha256_text(payload)


# ------------------------------------------------------------- StepMania parsing

_TAP_HEADS = frozenset({"1", "2", "4"})


def _tokenize_simfile(text: str) -> list[tuple[str, str]]:
    """Split ``#TAG:value;`` pairs; a valueless tag (``#NOTEDATA;``) yields ''."""
    tags: list[tuple[str, str]] = []
    index = 0
    length = len(text)
    while index < length:
        if text[index] != "#":
            index += 1
            continue
        name_end = index + 1
        while name_end < length and (text[name_end].isalnum() or text[name_end] == "_"):
            name_end += 1
        tag = text[index + 1:name_end].strip().upper()
        if not tag:
            index = name_end
            continue
        cursor = name_end
        while cursor < length and text[cursor] in " \t\r\n":
            cursor += 1
        if cursor < length and text[cursor] == ":":
            terminator = text.find(";", cursor)
            if terminator < 0:
                terminator = length
            tags.append((tag, text[cursor + 1:terminator]))
            index = terminator + 1
        elif cursor < length and text[cursor] == ";":
            tags.append((tag, ""))
            index = cursor + 1
        else:
            index = name_end
    return tags


def _parse_timing_list(value: str, where: str, allow_empty: bool = False) -> list[tuple[float, float]]:
    if not value.strip():
        if allow_empty:
            return []
        raise ChartLabelError(CODE_MALFORMED_CHART, f"{where}: empty timing list")
    entries: list[tuple[float, float]] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ChartLabelError(CODE_MALFORMED_CHART, f"{where}: timing entry {chunk!r} lacks '='")
        left, _, right = chunk.partition("=")
        try:
            beat = float(left.strip())
            number = float(right.strip())
        except ValueError as error:
            raise ChartLabelError(CODE_MALFORMED_CHART, f"{where}: timing entry {chunk!r} is not numeric") from error
        if not (math.isfinite(beat) and math.isfinite(number)):
            raise ChartLabelError(CODE_UNSUPPORTED_TIMING_FEATURE, f"{where}: non-finite BPM/stop/delay value")
        entries.append((beat, number))
    if not entries:
        raise ChartLabelError(CODE_MALFORMED_CHART, f"{where}: empty timing list")
    return entries


def _beat_to_seconds(beat: float, bpm_segments: list[tuple[float, float]],
                     stops: list[tuple[float, float]], delays: list[tuple[float, float]],
                     offset: float) -> float:
    """Mirror StepMania timing: delays precede a row; stops follow it."""
    seconds = -offset
    for index, (segment_beat, bpm) in enumerate(bpm_segments):
        if beat <= segment_beat:
            break
        segment_end = bpm_segments[index + 1][0] if index + 1 < len(bpm_segments) else math.inf
        span = min(beat, segment_end) - segment_beat
        seconds += span * 60.0 / bpm
    for stop_beat, stop_seconds in stops:
        if beat > stop_beat:
            seconds += stop_seconds
    for delay_beat, delay_seconds in delays:
        if beat >= delay_beat:
            seconds += delay_seconds
    return seconds


def _parse_measure_rows(note_data: str, chart_label: str) -> list[tuple[float, str]]:
    rows: list[tuple[float, str]] = []
    measures = note_data.split(",")
    for measure_index, measure in enumerate(measures):
        cleaned: list[str] = []
        for line in measure.splitlines():
            comment = line.find("//")
            if comment >= 0:
                line = line[:comment]
            if line.strip():
                cleaned.append(line.strip())
        if not cleaned:
            continue
        row_count = len(cleaned)
        for row_index, row in enumerate(cleaned):
            beat = 4.0 * (measure_index + row_index / row_count)
            rows.append((beat, row))
    if rows:
        lane_count = len(rows[0][1])
        if lane_count < 1 or any(len(row) != lane_count for _, row in rows):
            raise ChartLabelError(CODE_MALFORMED_CHART, f"{chart_label}: inconsistent lane count")
    return rows


def _stepmania_markers(rows: list[tuple[float, str]], timing: dict[str, Any], *,
                       allow_lifts: bool, chart_label: str,
                       diagnostics: dict[str, int]) -> list[float]:
    markers: list[float] = []
    bpm_segments = timing["bpm_segments"]
    stops = timing["stops"]
    delays = timing["delays"]
    offset = timing["offset"]
    for beat, row in rows:
        included = False
        for symbol in row:
            if symbol in _TAP_HEADS:
                included = True
            elif symbol == "3":
                diagnostics["ignored_tail_count"] += 1
            elif symbol in {"M", "F", "K"}:
                diagnostics["ignored_hazard_count"] += 1
            elif symbol == "L":
                if allow_lifts:
                    included = True
                else:
                    raise ChartLabelError(
                        CODE_UNSUPPORTED_TIMING_FEATURE,
                        f"{chart_label}: lift notes (L) are only supported in .ssc charts",
                    )
            elif symbol != "0":
                raise ChartLabelError(CODE_MALFORMED_CHART, f"{chart_label}: unsupported note symbol {symbol!r}")
        if included:
            seconds = _beat_to_seconds(beat, bpm_segments, stops, delays, offset)
            if not math.isfinite(seconds) or seconds < 0.0:
                raise ChartLabelError(
                    CODE_UNSUPPORTED_TIMING_FEATURE,
                    f"{chart_label}: timing maps a note before audio start",
                )
            markers.append(round6(seconds))
    if any(later < earlier for earlier, later in zip(markers, markers[1:])):
        raise ChartLabelError(CODE_UNSUPPORTED_TIMING_FEATURE, f"{chart_label}: non-monotone audio-time mapping")
    return markers


def _timing_from_tags(tags: dict[str, str], where: str) -> dict[str, Any]:
    if "BPMS" not in tags:
        raise ChartLabelError(CODE_MALFORMED_CHART, f"{where}: missing #BPMS")
    bpm_segments = _parse_timing_list(tags["BPMS"], where)
    if any(beat < 0.0 for beat, _ in bpm_segments):
        raise ChartLabelError(CODE_UNSUPPORTED_TIMING_FEATURE, f"{where}: negative BPM beat")
    if bpm_segments[0][0] != 0.0:
        raise ChartLabelError(CODE_MALFORMED_CHART, f"{where}: BPM timeline must start at beat 0")
    if any(later <= earlier for earlier, later in zip(bpm_segments, bpm_segments[1:])):
        raise ChartLabelError(CODE_MALFORMED_CHART, f"{where}: BPM change beats must strictly increase")
    if any(bpm <= 0.0 for _, bpm in bpm_segments):
        raise ChartLabelError(CODE_UNSUPPORTED_TIMING_FEATURE, f"{where}: non-positive BPM")
    stops = _parse_timing_list(tags["STOPS"], where, allow_empty=True) if "STOPS" in tags else []
    delays = _parse_timing_list(tags["DELAYS"], where, allow_empty=True) if "DELAYS" in tags else []
    if any(beat < 0.0 or length < 0.0 for beat, length in stops):
        raise ChartLabelError(CODE_UNSUPPORTED_TIMING_FEATURE, f"{where}: negative stop")
    if any(beat < 0.0 or length < 0.0 for beat, length in delays):
        raise ChartLabelError(CODE_UNSUPPORTED_TIMING_FEATURE, f"{where}: negative delay")
    stops.sort(key=lambda entry: entry[0])
    delays.sort(key=lambda entry: entry[0])
    if "WARPS" in tags and tags["WARPS"].strip():
        raise ChartLabelError(CODE_UNSUPPORTED_TIMING_FEATURE, f"{where}: #WARPS is not supported")
    if "TIMESIGNATURES" in tags and tags["TIMESIGNATURES"].strip():
        for chunk in tags["TIMESIGNATURES"].split(","):
            parts = chunk.strip().split("=")
            if len(parts) != 3:
                raise ChartLabelError(CODE_MALFORMED_CHART, f"{where}: bad time signature")
            if len(parts) == 3:
                try:
                    numerator = float(parts[1])
                    denominator = float(parts[2])
                except ValueError as error:
                    raise ChartLabelError(CODE_MALFORMED_CHART, f"{where}: bad time signature") from error
                if numerator != 4.0 or denominator != 4.0:
                    raise ChartLabelError(
                        CODE_UNSUPPORTED_TIMING_FEATURE,
                        f"{where}: non-4/4 time signature change is not supported",
                    )
    offset = 0.0
    if "OFFSET" in tags:
        try:
            offset = float(tags["OFFSET"].strip())
        except ValueError as error:
            raise ChartLabelError(CODE_MALFORMED_CHART, f"{where}: non-numeric #OFFSET") from error
        if not math.isfinite(offset):
            raise ChartLabelError(CODE_UNSUPPORTED_TIMING_FEATURE, f"{where}: non-finite #OFFSET")
    return {"bpm_segments": bpm_segments, "stops": stops, "delays": delays, "offset": offset}


def _empty_diagnostics() -> dict[str, int]:
    return {"raw_object_count": 0, "normalized_marker_count": 0,
            "ignored_tail_count": 0, "ignored_hazard_count": 0}


def _finish_chart(markers: list[float], *, format_name: str, mode: str, chart_sha256: str,
                  audio_reference: str, difficulty_name: str, declared_meter: int,
                  diagnostics: dict[str, int]) -> dict[str, Any]:
    collapsed = collapse_simultaneous(markers, SIMULTANEOUS_MARKER_TOLERANCE_SECONDS)
    diagnostics["normalized_marker_count"] = len(collapsed)
    return {
        "schema": CHART_CONTRACT,
        "format": format_name,
        "mode": mode,
        "chart_sha256": chart_sha256,
        "audio_reference": audio_reference,
        "difficulty_name": difficulty_name,
        "declared_meter": declared_meter,
        "markers_seconds": collapsed,
        "diagnostics": diagnostics,
    }


def _chart_instance_sha256(source_sha256: str, ordinal: int, total: int) -> str:
    """Give each difficulty in a multi-chart simfile a stable identity.

    A one-chart file keeps its historical file hash.  Multi-chart StepMania
    files need distinct IDs because downstream alignment maps are keyed by
    ``chart_sha256``; using the container hash for every difficulty silently
    made the final difficulty overwrite all earlier ones.
    """
    if total == 1:
        return source_sha256
    return hashlib.sha256(f"{source_sha256}:{ordinal}".encode("ascii")).hexdigest()


def parse_stepmania_sm(text: str, chart_sha256: str, audio_reference: str) -> list[dict[str, Any]]:
    """Parse a legacy ``.sm`` file; every ``#NOTES`` block becomes one chart."""
    tags = _tokenize_simfile(text)
    timing = _timing_from_tags({tag: value for tag, value in tags}, "song")
    charts: list[dict[str, Any]] = []
    notes_values = [value for tag, value in tags if tag == "NOTES"]
    if not notes_values:
        raise ChartLabelError(CODE_MALFORMED_CHART, "no #NOTES chart in file")
    for ordinal, notes_value in enumerate(notes_values):
        # The real .sm contract is
        # stepstype:description:difficulty:meter:radar-values:note-data.
        # Early Round-2 fixtures intentionally omitted radar-values, so retain
        # that five-field shorthand while accepting the standard six fields.
        fields = notes_value.split(":", 5)
        if len(fields) == 6:
            note_data = fields[5]
        elif len(fields) == 5:
            note_data = fields[4]
        else:
            raise ChartLabelError(CODE_MALFORMED_CHART, "#NOTES needs five or six ':' fields")
        mode = fields[0].strip() or "dance-single"
        difficulty_name = fields[2].strip() or "Unnamed"
        try:
            meter = int(float(fields[3].strip()))
        except ValueError as error:
            raise ChartLabelError(CODE_MALFORMED_CHART, "non-numeric #METER") from error
        diagnostics = _empty_diagnostics()
        instance_sha256 = _chart_instance_sha256(chart_sha256, ordinal, len(notes_values))
        rows = _parse_measure_rows(note_data, instance_sha256[:12])
        diagnostics["raw_object_count"] = sum(1 for _, row in rows for symbol in row if symbol != "0")
        markers = _stepmania_markers(rows, timing, allow_lifts=False,
                                     chart_label=instance_sha256[:12], diagnostics=diagnostics)
        charts.append(_finish_chart(
            markers, format_name="stepmania", mode=mode, chart_sha256=instance_sha256,
            audio_reference=audio_reference, difficulty_name=difficulty_name,
            declared_meter=meter, diagnostics=diagnostics))
    return charts


def parse_stepmania_ssc(text: str, chart_sha256: str, audio_reference: str) -> list[dict[str, Any]]:
    """Parse a ``.ssc`` file with song-level and chart-scoped timing fields.

    Chart-scoped ``OFFSET``/``BPMS``/``STOPS``/``DELAYS`` override the song
    values for that chart only and never leak into neighbouring blocks.
    """
    tags = _tokenize_simfile(text)
    song_tags: dict[str, str] = {}
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    saw_notedata = False
    for tag, value in tags:
        if tag == "NOTEDATA":
            saw_notedata = True
            if current is not None:
                blocks.append(current)
            current = {}
            continue
        if current is None:
            song_tags[tag] = value
        elif tag == "NOTES":
            current["__NOTES__"] = value
            blocks.append(current)
            current = None
        else:
            current[tag] = value
    if current is not None:
        blocks.append(current)
    if not saw_notedata:
        raise ChartLabelError(CODE_MALFORMED_CHART, ".ssc file has no #NOTEDATA block")
    song_timing = _timing_from_tags(song_tags, "song")

    charts: list[dict[str, Any]] = []
    chart_blocks = [block for block in blocks if "__NOTES__" in block]
    for ordinal, block in enumerate(chart_blocks):
        note_data = block.pop("__NOTES__", None)
        if note_data is None:
            continue  # a #NOTEDATA block without note rows declares nothing
        merged = dict(song_tags)
        merged.update(block)
        timing = _timing_from_tags(merged, f"chart {block.get('DIFFICULTY', '?').strip()}")
        difficulty_name = block.get("DIFFICULTY", "Unnamed").strip() or "Unnamed"
        try:
            meter = int(float(block.get("METER", "4").strip() or "4"))
        except ValueError as error:
            raise ChartLabelError(CODE_MALFORMED_CHART, "non-numeric #METER") from error
        mode = block.get("STEPSTYPE", "dance-single").strip() or "dance-single"
        diagnostics = _empty_diagnostics()
        instance_sha256 = _chart_instance_sha256(chart_sha256, ordinal, len(chart_blocks))
        rows = _parse_measure_rows(note_data, instance_sha256[:12])
        diagnostics["raw_object_count"] = sum(1 for _, row in rows for symbol in row if symbol != "0")
        markers = _stepmania_markers(rows, timing, allow_lifts=True,
                                     chart_label=instance_sha256[:12], diagnostics=diagnostics)
        charts.append(_finish_chart(
            markers, format_name="stepmania", mode=mode, chart_sha256=instance_sha256,
            audio_reference=audio_reference, difficulty_name=difficulty_name,
            declared_meter=meter, diagnostics=diagnostics))
    if not charts:
        raise ChartLabelError(CODE_MALFORMED_CHART, "no #NOTEDATA chart in file")
    return charts


# ------------------------------------------------------------------ osu! parsing

_OSU_MODES = {0: "osu-standard", 1: "osu-taiko", 3: "osu-mania"}


def _osu_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"__header__": []}
    current = "__header__"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
            sections.setdefault(current, [])
            continue
        sections[current].append(stripped)
    return sections


def _osu_field(section: list[str], key: str) -> str | None:
    for line in section:
        if ":" in line:
            name, _, value = line.partition(":")
            if name.strip() == key:
                return value.strip()
    return None


def parse_osu(text: str, chart_sha256: str) -> dict[str, Any]:
    """Parse one ``.osu`` beatmap into a normalized chart record."""
    sections = _osu_sections(text)
    header = " ".join(sections["__header__"])
    if "osu file format" not in header:
        raise ChartLabelError(CODE_UNSUPPORTED_CHART_FORMAT, "missing osu file format header")
    general = sections.get("General", [])
    mode_value = _osu_field(general, "Mode")
    try:
        mode = int(mode_value) if mode_value is not None else 0
    except ValueError as error:
        raise ChartLabelError(CODE_MALFORMED_CHART, "non-integer Mode") from error
    if mode not in _OSU_MODES:
        raise ChartLabelError(CODE_UNSUPPORTED_CHART_MODE, f"mode {mode} is not supported in v1")
    audio_reference = _osu_field(general, "AudioFilename") or ""
    difficulty_name = _osu_field(sections.get("Metadata", []), "Version") or "Unnamed"
    meter_value = _osu_field(sections.get("Difficulty", []), "KeyCount") \
        or _osu_field(sections.get("Difficulty", []), "CircleSize")
    try:
        declared_meter = int(float(meter_value)) if meter_value is not None else 4
    except ValueError as error:
        raise ChartLabelError(CODE_MALFORMED_CHART, "non-numeric difficulty meter") from error

    diagnostics = _empty_diagnostics()
    seconds: list[float] = []
    previous_time: float | None = None
    for line in sections.get("HitObjects", []):
        fields = line.split(",")
        if len(fields) < 5:
            raise ChartLabelError(CODE_MALFORMED_CHART, "hit object needs at least five fields")
        try:
            time_ms = float(fields[2])
            type_bits = int(fields[3])
        except ValueError as error:
            raise ChartLabelError(CODE_MALFORMED_CHART, "non-numeric hit object time or type") from error
        if not math.isfinite(time_ms):
            raise ChartLabelError(CODE_UNSUPPORTED_TIMING_FEATURE, "non-finite hit object time")
        if time_ms < 0.0:
            raise ChartLabelError(CODE_UNSUPPORTED_TIMING_FEATURE, "negative hit object time")
        seconds_value = round6(time_ms / 1000.0)
        if previous_time is not None and seconds_value < previous_time:
            raise ChartLabelError(CODE_MALFORMED_CHART, "hit objects must be chronological")
        previous_time = seconds_value
        diagnostics["raw_object_count"] += 1
        if type_bits & 8:  # spinner
            diagnostics["ignored_hazard_count"] += 1
            continue
        is_circle = bool(type_bits & 1)
        is_slider = bool(type_bits & 2)
        is_hold = bool(type_bits & 128)
        include = (
            (is_circle and mode in (0, 1, 3))
            or (is_slider and mode == 0)
            or (is_hold and mode == 3)
        )
        if include:
            seconds.append(seconds_value)
        else:
            diagnostics["ignored_tail_count"] += 1
    collapsed = collapse_simultaneous(seconds, SIMULTANEOUS_MARKER_TOLERANCE_SECONDS)
    diagnostics["normalized_marker_count"] = len(collapsed)
    return {
        "schema": CHART_CONTRACT,
        "format": "osu",
        "mode": _OSU_MODES[mode],
        "chart_sha256": chart_sha256,
        "audio_reference": audio_reference,
        "difficulty_name": difficulty_name,
        "declared_meter": declared_meter,
        "markers_seconds": collapsed,
        "diagnostics": diagnostics,
    }


def parse_stepmania_file(text: str, chart_sha256: str) -> list[dict[str, Any]]:
    """Parse ``.sm``/``.ssc`` text, resolving the song-level audio reference."""
    tags = dict(_tokenize_simfile(text))
    audio_reference = tags.get("MUSIC", tags.get("AUDIOFILENAME", "")).strip().strip('"')
    if any(tag == "NOTEDATA" for tag, _ in _tokenize_simfile(text)):
        return parse_stepmania_ssc(text, chart_sha256, audio_reference)
    return parse_stepmania_sm(text, chart_sha256, audio_reference)


def parse_chart_file(path: str | Path) -> list[dict[str, Any]]:
    """Parse one chart file into normalized records (one per difficulty)."""
    chart_path = Path(path)
    data = chart_path.read_bytes()
    chart_sha256 = hashlib.sha256(data).hexdigest()
    suffix = chart_path.suffix.lower()
    if suffix == ".osu":
        return [parse_osu(data.decode("utf-8-sig"), chart_sha256)]
    if suffix in (".sm", ".ssc"):
        return parse_stepmania_file(data.decode("utf-8-sig"), chart_sha256)
    raise ChartLabelError(CODE_UNSUPPORTED_CHART_FORMAT, f"unsupported chart suffix {suffix!r}")


# ------------------------------------------------- song grouping and deduplication


def _chart_density(chart: dict[str, Any]) -> float:
    markers = chart["markers_seconds"]
    if len(markers) < 2:
        return math.inf
    playable = markers[-1] - markers[0]
    if playable <= 0.0:
        return math.inf
    return len(markers) / playable


def group_charts_into_songs(chart_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group parsed charts by audio SHA, deduplicate timelines, order density.

    Each entry: ``{"chart": <parsed>, "audio_sha256": str, "audio_duration": float}``.
    Identical canonical marker sequences vote once; a chart with fewer than
    two unique markers is excluded; a song below three unique timelines is
    excluded as a group (plan section 9).
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in chart_entries:
        groups.setdefault(entry["audio_sha256"], []).append(entry)
    songs: list[dict[str, Any]] = []
    for audio_sha256 in sorted(groups):
        entries = groups[audio_sha256]
        exclusions: list[dict[str, str]] = []
        unique_by_hash: dict[str, dict[str, Any]] = {}
        for entry in sorted(entries, key=lambda item: item["chart"]["chart_sha256"]):
            chart = entry["chart"]
            markers = chart["markers_seconds"]
            if len(set(markers)) < MIN_UNIQUE_MARKERS_PER_CHART:
                exclusions.append({
                    "chart_sha256": chart["chart_sha256"],
                    "reason": "fewer_than_two_unique_markers",
                })
                continue
            timeline_hash = marker_sequence_hash(markers)
            if timeline_hash in unique_by_hash:
                exclusions.append({
                    "chart_sha256": chart["chart_sha256"],
                    "reason": "duplicate_timeline",
                })
                continue
            unique_by_hash[timeline_hash] = entry
        retained = sorted(unique_by_hash.values(), key=lambda item: _chart_density(item["chart"]))
        if len(retained) < MIN_DIFFICULTIES_PER_SONG:
            exclusions.append({
                "chart_sha256": "",
                "reason": CODE_INSUFFICIENT_UNIQUE_DIFFICULTIES,
            })
            retained = []
        songs.append({
            "audio_sha256": audio_sha256,
            "charts": retained,
            "exclusions": exclusions,
        })
    songs.sort(key=lambda song: song["audio_sha256"])
    return songs


# ------------------------------------------------------------- onset clustering


def coincident_onset_clusters(onset_times: list[float], onset_ids: list[int]) -> list[dict[str, Any]]:
    """Temporary label-only clusters of onsets within 1 ms (plan section 10.1)."""
    clusters: list[dict[str, Any]] = []
    previous_time: float | None = None
    for time_value, onset_id in zip(onset_times, onset_ids):
        if clusters and previous_time is not None \
                and time_value - previous_time <= COINCIDENT_ONSET_TOLERANCE_SECONDS:
            clusters[-1]["onset_ids"].append(onset_id)
        else:
            clusters.append({"time": time_value, "onset_ids": [onset_id]})
        previous_time = time_value
    return clusters


# ---------------------------------------------------------------- alignment


def align_chart_to_clusters(markers: list[float], clusters: list[dict[str, Any]]) -> dict[str, Any]:
    """Exact monotone one-to-one alignment under the frozen lexicographic objective.

    Per connected component, optimize: maximize matched pairs, then minimize
    total absolute residual, then minimize the ordered onset-cluster index
    sequence, then the ordered marker index sequence (plan section 10.3).
    Candidate edges satisfy ``abs(marker - cluster) <= 0.050`` seconds.
    """
    cluster_times = [cluster["time"] for cluster in clusters]
    cluster_adjacency: list[list[int]] = [[] for _ in clusters]
    marker_adjacency: dict[int, list[int]] = {}
    for marker_index, marker_time in enumerate(markers):
        low = bisect.bisect_left(cluster_times, marker_time - ALIGNMENT_TOLERANCE_SECONDS - 1e-9)
        high = bisect.bisect_right(cluster_times, marker_time + ALIGNMENT_TOLERANCE_SECONDS + 1e-9)
        for cluster_index in range(low, high):
            if abs(cluster_times[cluster_index] - marker_time) <= ALIGNMENT_TOLERANCE_SECONDS + 1e-12:
                cluster_adjacency[cluster_index].append(marker_index)
                marker_adjacency.setdefault(marker_index, []).append(cluster_index)

    components: list[tuple[list[int], list[int]]] = []
    claimed: set[int] = set()
    for start in range(len(clusters)):
        if not cluster_adjacency[start] or start in claimed:
            continue
        seen_clusters: set[int] = set()
        seen_markers: set[int] = set()
        stack = [start]
        while stack:
            cluster_index = stack.pop()
            if cluster_index in seen_clusters:
                continue
            seen_clusters.add(cluster_index)
            for marker_index in cluster_adjacency[cluster_index]:
                seen_markers.add(marker_index)
                for other in marker_adjacency.get(marker_index, ()):
                    if other not in seen_clusters:
                        stack.append(other)
        claimed |= seen_clusters
        components.append((sorted(seen_clusters), sorted(seen_markers)))

    matches: list[tuple[int, int, float]] = []
    ambiguous_components = 0
    for cluster_indices, marker_indices in components:
        times_c = [cluster_times[index] for index in cluster_indices]
        times_m = [markers[index] for index in marker_indices]
        count_c = len(cluster_indices)
        count_m = len(marker_indices)
        # dp[i][j] = (-matched, total_error, onset_seq, marker_seq), minimized.
        dp: list[list[tuple[int, float, tuple[int, ...], tuple[int, ...]]]] = [
            [(0, 0.0, (), ())] * (count_m + 1) for _ in range(count_c + 1)
        ]
        ambiguous = False
        for i in range(count_c - 1, -1, -1):
            for j in range(count_m - 1, -1, -1):
                candidates = [dp[i + 1][j], dp[i][j + 1]]
                error = round6(abs(times_c[i] - times_m[j]))
                if error <= ALIGNMENT_TOLERANCE_SECONDS:
                    tail = dp[i + 1][j + 1]
                    candidates.append((
                        tail[0] - 1,
                        tail[1] + round6(error),
                        (cluster_indices[i],) + tail[2],
                        (marker_indices[j],) + tail[3],
                    ))
                best = min(candidates)
                ties = sum(1 for candidate in candidates
                           if (candidate[0], candidate[1]) == (best[0], best[1]))
                if ties > 1:
                    ambiguous = True
                dp[i][j] = best
        if ambiguous:
            ambiguous_components += 1
        negative_count, _total_error, onset_sequence, marker_sequence = dp[0][0]
        # The sequences store global cluster/marker indices already.
        for cluster_index, marker_index in zip(onset_sequence, marker_sequence):
            residual = round6(abs(cluster_times[cluster_index] - markers[marker_index]))
            matches.append((marker_index, cluster_index, residual))
    matches.sort()
    matched_marker_count = len(matches)
    matched_cluster_ids = {cluster for _, cluster, _ in matches}
    residuals = [residual for _, _, residual in matches]
    sorted_residuals = sorted(residuals)
    return {
        "matches": matches,
        "matched_marker_count": matched_marker_count,
        "unmatched_marker_count": len(markers) - matched_marker_count,
        "matched_cluster_count": len(matched_cluster_ids),
        "covered_onset_ids": sorted(
            onset_id
            for match in matches
            for onset_id in clusters[match[1]]["onset_ids"]
        ),
        "median_residual": round6(_percentile(sorted_residuals, 0.50)) if residuals else None,
        "p95_residual": round6(_percentile(sorted_residuals, 0.95)) if residuals else None,
        "max_residual": round6(max(residuals)) if residuals else None,
        "ambiguous_component_count": ambiguous_components,
    }


def estimate_song_alignment_offset(charts: list[dict[str, Any]],
                                   clusters: list[dict[str, Any]]) -> dict[str, Any]:
    """Estimate one bounded chart-to-detector offset shared by a song.

    The calibration is a private label-alignment aid.  It never changes an
    onset time or a published event.  A shift is applied only when at least
    three chart difficulties independently agree and their median absolute
    deviation is small; otherwise the honest zero-offset path is retained.
    """
    cluster_times = [float(cluster["time"]) for cluster in clusters]
    chart_offsets: list[float] = []
    for chart in charts:
        markers = chart["markers_seconds"]
        if not markers:
            continue
        alignment = align_chart_to_clusters(markers, clusters)
        if alignment["matched_marker_count"] < 2 \
                or alignment["matched_marker_count"] / len(markers) < MIN_CHART_MATCH_RATE:
            continue
        signed = sorted(
            float(markers[marker_index]) - cluster_times[cluster_index]
            for marker_index, cluster_index, _residual in alignment["matches"]
        )
        chart_offsets.append(_percentile(signed, 0.50))
    if len(chart_offsets) < MIN_CALIBRATION_CHARTS:
        return {"applied": False, "offset_seconds": 0.0,
                "eligible_chart_count": len(chart_offsets), "mad_seconds": None}
    center = _percentile(sorted(chart_offsets), 0.50)
    mad = _percentile(sorted(abs(value - center) for value in chart_offsets), 0.50)
    applied = abs(center) <= MAX_CALIBRATION_OFFSET_SECONDS \
        and mad <= MAX_CALIBRATION_MAD_SECONDS
    return {
        "applied": applied,
        "offset_seconds": round6(center) if applied else 0.0,
        "eligible_chart_count": len(chart_offsets),
        "mad_seconds": round6(mad),
    }


def calibrated_chart(chart: dict[str, Any], offset_seconds: float) -> dict[str, Any]:
    """Return an alignment-only chart view; the source chart is untouched."""
    return {
        **chart,
        "markers_seconds": [round6(value - offset_seconds)
                            for value in chart["markers_seconds"]],
    }


def chart_alignment_verdict(parsed_chart: dict[str, Any], alignment: dict[str, Any],
                            audio_duration: float | None, *,
                            max_p95_residual_seconds: float = MAX_P95_RESIDUAL_SECONDS) -> str | None:
    """Return an exclusion reason code, or None when the chart is retained."""
    marker_count = len(parsed_chart["markers_seconds"])
    if marker_count == 0 or alignment["matched_marker_count"] / marker_count < MIN_CHART_MATCH_RATE:
        return CODE_ALIGNMENT_MATCH_RATE_TOO_LOW
    p95 = alignment["p95_residual"]
    if p95 is not None and p95 > max_p95_residual_seconds:
        return CODE_ALIGNMENT_RESIDUAL_TOO_HIGH
    if audio_duration is not None and parsed_chart["markers_seconds"]:
        last_marker = parsed_chart["markers_seconds"][-1]
        if last_marker > audio_duration + MAX_DURATION_DRIFT_SECONDS:
            return CODE_DURATION_DRIFT_TOO_HIGH
    return None


# ------------------------------------------------------------- weak labels


def build_weak_labels(song: dict[str, Any], alignments: dict[str, dict[str, Any]],
                      clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cross-difficulty survival labels keyed by onset ID only (plan section 11)."""
    retained = song["charts"]
    eligible = len(retained)
    sparse_count = eligible // 2  # an odd middle chart joins the dense half
    labels: dict[int, dict[str, Any]] = {
        onset_id: {
            "onset_id": onset_id,
            "chart_support_count": 0,
            "eligible_chart_count": eligible,
            "support_rate": 0.0,
            "sparse_half_support": 0,
            "dense_half_support": 0,
        }
        for cluster in clusters
        for onset_id in cluster["onset_ids"]
    }
    for position, entry in enumerate(retained):
        alignment = alignments[entry["chart"]["chart_sha256"]]
        for _, cluster_index, _ in alignment["matches"]:
            for onset_id in clusters[cluster_index]["onset_ids"]:
                record = labels[onset_id]
                record["chart_support_count"] += 1
                if position < sparse_count:
                    record["sparse_half_support"] += 1
                else:
                    record["dense_half_support"] += 1
    for record in labels.values():
        record["support_rate"] = (
            round6(record["chart_support_count"] / record["eligible_chart_count"])
            if record["eligible_chart_count"] else 0.0
        )
    return [labels[onset_id] for onset_id in sorted(labels)]


def build_preference_pairs(labels: list[dict[str, Any]], onset_times: dict[int, float],
                           segment_of_onset: dict[int, int | None]) -> list[dict[str, Any]]:
    """Within-song, locality-aware, deterministically capped pairs (plan 11.2-11.3)."""
    by_id = {record["onset_id"]: record for record in labels}
    ids = sorted(by_id)
    candidates: list[tuple[int, int]] = []
    for first in range(len(ids)):
        for second in range(first + 1, len(ids)):
            left, right = ids[first], ids[second]
            gap = abs(by_id[left]["support_rate"] - by_id[right]["support_rate"])
            if gap < MIN_PAIR_SUPPORT_GAP:
                continue
            separation = abs(onset_times[left] - onset_times[right])
            same_segment = (
                segment_of_onset.get(left) is not None
                and segment_of_onset.get(left) == segment_of_onset.get(right)
            )
            if separation > MAX_LOCALITY_SECONDS and not same_segment:
                continue
            preferred, other = (left, right) if by_id[left]["support_rate"] > by_id[right]["support_rate"] \
                else (right, left)
            candidates.append((preferred, other))
    ordered = sorted(
        candidates,
        key=lambda pair: (
            -abs(by_id[pair[0]]["support_rate"] - by_id[pair[1]]["support_rate"]),
            abs(onset_times[pair[0]] - onset_times[pair[1]]),
            pair[0],
            pair[1],
        ),
    )
    kept: dict[tuple[int, int], tuple[int, int]] = {}
    per_event: dict[int, int] = {}
    for preferred, other in ordered:
        if per_event.get(preferred, 0) >= MAX_PAIRS_PER_EVENT \
                or per_event.get(other, 0) >= MAX_PAIRS_PER_EVENT:
            continue
        key = (min(preferred, other), max(preferred, other))
        if key in kept:
            continue
        kept[key] = (preferred, other)
        per_event[preferred] = per_event.get(preferred, 0) + 1
        per_event[other] = per_event.get(other, 0) + 1
    return [
        {
            "preferred_onset_id": preferred,
            "other_onset_id": other,
            "support_gap": round6(abs(by_id[preferred]["support_rate"] - by_id[other]["support_rate"])),
        }
        for preferred, other in sorted(kept.values(), key=lambda pair: (min(pair), max(pair)))
    ]


# --------------------------------------------------------------------- split


def _split_hash(audio_sha256: str) -> str:
    return hashlib.sha256((SPLIT_SALT + audio_sha256).encode("utf-8")).hexdigest()


def assign_splits(song_groups: list[dict[str, Any]],
                  frozen_assignments: dict[str, str] | None = None) -> dict[str, str]:
    """Deterministic song-level 70/15/15 split keyed by hashed audio identity.

    Strata are (format family, density tertile); ordering inside a stratum is
    the salted SHA-256 of the audio identity. Assignments supplied by an
    earlier manifest are immutable; only unseen songs are allocated.
    """
    family_by_song: dict[str, str] = {}
    density_by_song: dict[str, float] = {}
    for song in song_groups:
        formats = sorted({chart["chart"]["format"] for chart in song["charts"]})
        family_by_song[song["audio_sha256"]] = formats[0] if len(formats) == 1 else "mixed"
        densities = [_chart_density(chart["chart"]) for chart in song["charts"]]
        density_by_song[song["audio_sha256"]] = sum(densities) / len(densities) if densities else math.inf

    tertile_by_song: dict[str, int] = {}
    by_family: dict[str, list[float]] = {}
    for audio_sha256, density in density_by_song.items():
        by_family.setdefault(family_by_song[audio_sha256], []).append(density)
    for family, values in by_family.items():
        ordered_songs = sorted(
            (density, audio_sha256) for audio_sha256, density in density_by_song.items()
            if family_by_song[audio_sha256] == family
        )
        for rank, (density, audio_sha256) in enumerate(ordered_songs):
            if len(ordered_songs) < 6:
                # Too few songs in this family for meaningful density strata.
                tertile_by_song[audio_sha256] = 0
                continue
            tertile_by_song[audio_sha256] = min(2, int(rank * 3 / len(ordered_songs)))

    strata: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for song in song_groups:
        key = (family_by_song[song["audio_sha256"]], tertile_by_song[song["audio_sha256"]])
        strata.setdefault(key, []).append(song)

    frozen_assignments = frozen_assignments or {}
    invalid = sorted(set(frozen_assignments.values()) - {"train", "validation", "test"})
    if invalid:
        raise ValueError(f"invalid frozen split values: {invalid}")
    assignments: dict[str, str] = {
        song["audio_sha256"]: frozen_assignments[song["audio_sha256"]]
        for song in song_groups if song["audio_sha256"] in frozen_assignments
    }
    for (_family, _tertile), songs in strata.items():
        ordered = sorted(songs, key=lambda song: _split_hash(song["audio_sha256"]))
        ordered = [song for song in ordered if song["audio_sha256"] not in assignments]
        total = len(ordered)
        if total == 0:
            continue
        validation_count = max(1, int(round(total * VALIDATION_FRACTION)))
        test_count = max(1, int(round(total * TEST_FRACTION)))
        if total >= 8:
            validation_count = max(2, validation_count)
            test_count = max(2, test_count)
        validation_count = min(validation_count, total - 1)
        test_count = min(test_count, max(1, total - validation_count))
        for position, song in enumerate(ordered):
            if position < test_count:
                assignments[song["audio_sha256"]] = "test"
            elif position < test_count + validation_count:
                assignments[song["audio_sha256"]] = "validation"
            else:
                assignments[song["audio_sha256"]] = "train"
    return assignments


def assign_splits_with_holdout(song_groups: list[dict[str, Any]],
                               holdout_audio_sha256s: set[str]) -> dict[str, str]:
    """Keep an explicit untouched source partition entirely in ``test``.

    Development songs use the existing deterministic stratification; its
    would-be test slice is folded into training because the independent
    holdout owns the only test role for this method version.
    """
    known = {song["audio_sha256"] for song in song_groups}
    unknown = sorted(holdout_audio_sha256s - known)
    if unknown:
        raise ValueError(f"holdout assignments reference unknown songs: {unknown}")
    development = [song for song in song_groups
                   if song["audio_sha256"] not in holdout_audio_sha256s]
    assignments = assign_splits(development)
    for audio_sha256, split in list(assignments.items()):
        if split == "test":
            assignments[audio_sha256] = "train"
    assignments.update({audio_sha256: "test" for audio_sha256 in holdout_audio_sha256s})
    return assignments


def audit_split_leakage(song_groups: list[dict[str, Any]], assignments: dict[str, str],
                        fingerprint_by_song: dict[str, str]) -> list[str]:
    """Zero audio-SHA or fingerprint-cluster leakage across splits."""
    errors: list[str] = []
    seen_fingerprint: dict[str, str] = {}
    for song in song_groups:
        sha = song["audio_sha256"]
        if assignments.get(sha) is None:
            errors.append(f"song {sha} has no split assignment")
            continue
        fingerprint = fingerprint_by_song.get(sha)
        if fingerprint is not None:
            if fingerprint in seen_fingerprint and seen_fingerprint[fingerprint] != assignments[sha]:
                errors.append(
                    f"{CODE_DUPLICATE_AUDIO_ACROSS_SPLITS}: fingerprint {fingerprint[:12]} "
                    f"spans {seen_fingerprint[fingerprint]} and {assignments[sha]}"
                )
            else:
                seen_fingerprint[fingerprint] = assignments[sha]
    return errors


def consumed_artifact_conflicts(dataset_sha256: str | None, manifest_sha256: str | None,
                                selected_sha256: str | None = None,
                                report_sha256: str | None = None) -> list[str]:
    """Name every produced artifact whose hash matches the consumed v2 set."""
    candidates = {
        "dataset.jsonl": dataset_sha256,
        "training-manifest.json": manifest_sha256,
        "selected.json": selected_sha256,
        "evaluation-report.json": report_sha256,
    }
    return sorted(
        name for name, digest in candidates.items()
        if digest and str(digest).lower() in CONSUMED_V2_ARTIFACTS
    )


def assign_development_splits(song_groups: list[dict[str, Any]],
                              source_by_song: dict[str, str],
                              frozen_assignments: dict[str, str] | None = None) -> dict[str, str]:
    """Source-aware 75/25 train/validation split; B1 has no test role.

    Strata are ``(source_id, format, density_tertile)``; ordering inside a
    stratum is the salted content hash, so adding songs never moves a frozen
    assignment. Any would-be test allocation is folded into training (plan
    section 4.1).
    """
    family_by_song: dict[str, tuple[str, str]] = {}
    density_by_song: dict[str, float] = {}
    for song in song_groups:
        sha = song["audio_sha256"]
        source_id = source_by_song.get(sha, "unknown")
        formats = sorted({chart["chart"]["format"] for chart in song["charts"]})
        family_by_song[sha] = (source_id, formats[0] if len(formats) == 1 else "mixed")
        densities = [_chart_density(chart["chart"]) for chart in song["charts"]]
        density_by_song[sha] = sum(densities) / len(densities) if densities else math.inf

    tertile_by_song: dict[str, int] = {}
    by_family: dict[tuple[str, str], list[float]] = {}
    for sha, density in density_by_song.items():
        by_family.setdefault(family_by_song[sha], []).append(density)
    for family in by_family:
        ordered_songs = sorted(
            (density, sha) for sha, density in density_by_song.items()
            if family_by_song[sha] == family
        )
        for rank, (_density, sha) in enumerate(ordered_songs):
            tertile_by_song[sha] = (
                0 if len(ordered_songs) < 6
                else min(2, int(rank * 3 / len(ordered_songs)))
            )

    strata: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for song in song_groups:
        sha = song["audio_sha256"]
        source_id, fmt = family_by_song[sha]
        strata.setdefault((source_id, fmt, tertile_by_song[sha]), []).append(song)

    frozen_assignments = frozen_assignments or {}
    invalid = sorted(set(frozen_assignments.values()) - {"train", "validation"})
    if invalid:
        raise ValueError(f"invalid frozen development split values: {invalid}")
    assignments: dict[str, str] = {
        song["audio_sha256"]: frozen_assignments[song["audio_sha256"]]
        for song in song_groups if song["audio_sha256"] in frozen_assignments
    }
    for (_source, _fmt, _tertile), songs in strata.items():
        ordered = [song for song in sorted(songs, key=lambda song: _split_hash(song["audio_sha256"]))
                   if song["audio_sha256"] not in assignments]
        total = len(ordered)
        if total == 0:
            continue
        validation_count = max(1, int(round(total * DEVELOPMENT_VALIDATION_FRACTION)))
        if total >= 8:
            validation_count = max(2, validation_count)
        validation_count = min(validation_count, total - 1)
        for position, song in enumerate(ordered):
            assignments[song["audio_sha256"]] = (
                "validation" if position < validation_count else "train")
    return assignments


def audit_partition_leakage(song_groups: list[dict[str, Any]], assignments: dict[str, str],
                            fingerprint_by_song: dict[str, str],
                            chart_hashes_by_song: dict[str, set[str]],
                            timeline_hash_by_chart: dict[str, str]) -> list[str]:
    """Audio SHA, fingerprint, chart hash, and timeline hash never cross splits."""
    errors: list[str] = []
    seen: dict[str, dict[str, str]] = {"audio": {}, "fingerprint": {}, "chart": {}, "timeline": {}}
    codes = {
        "audio": CODE_DUPLICATE_AUDIO_ACROSS_SPLITS,
        "fingerprint": CODE_DUPLICATE_AUDIO_ACROSS_SPLITS,
        "chart": CODE_CHART_HASH_ACROSS_SPLITS,
        "timeline": CODE_TIMELINE_HASH_ACROSS_SPLITS,
    }

    def claim(kind: str, key: str, split: str) -> None:
        if not key:
            return
        previous = seen[kind].get(key)
        if previous is not None and previous != split:
            errors.append(
                f"{codes[kind]}: {kind} {key[:12]} spans {previous} and {split}")
        else:
            seen[kind][key] = split

    for song in song_groups:
        sha = song["audio_sha256"]
        split = assignments.get(sha)
        if split is None:
            errors.append(f"song {sha} has no split assignment")
            continue
        claim("audio", sha, split)
        claim("fingerprint", fingerprint_by_song.get(sha, ""), split)
        for chart_hash in sorted(chart_hashes_by_song.get(sha, set())):
            claim("chart", chart_hash, split)
            claim("timeline", timeline_hash_by_chart.get(chart_hash, ""), split)
    return errors
