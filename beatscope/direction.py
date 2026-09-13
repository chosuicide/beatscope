"""`beatscope-direction-1` — the canonical scene/layer direction document.

Round 2 Commit 1 contract (v0.12 plan §4 / §10.1):

- ``validate_direction`` returns ``(errors, notices)`` with STABLE error
  codes. Unknown layer/driver/motion kinds are preserved and reported as
  notices — never deleted, never rejected.
- ``canonical_direction_bytes`` serializes a validated document to
  byte-identical UTF-8 JSON in Python and in a fresh Node process
  (``web-src/src/direction/contract.ts`` implements the mirror algorithm;
  ``tests/test_direction_contract.js`` pins the two together):

  * object keys sorted by code point, emitted without spaces,
  * numbers formatted at exactly six fractional decimals with trailing
    zeros stripped (integral values lose the dot), minus zero -> ``0``,
    non-finite values are rejected by the validator before serialization,
  * strings serialized like ``json.dumps(..., ensure_ascii=False)``.

  Direction values are authored at <= 6 fractional decimals (analysis
  rounds to 6, editor commands round before writing), so the six-decimal
  form is exact for the contract corpus.
- ``derive_scenes_from_structure`` builds the initial scenes from the
  Rhythm IR's ``patterns.segments`` (bar anchors) without touching the IR
  bytes; without segments it chunks the grid bars, and without a grid it
  falls back to half-open time anchors. Bar and time fallback semantics
  agree at exact boundaries: ``resolve_anchor_times`` maps bar ``n`` to
  ``origin + (n - 1) * bar_seconds`` and the half-open interval rule is
  shared by both anchor kinds.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

DIRECTION_SCHEMA = "beatscope-direction-1"
DIRECTION_DOC_VERSION = "0.12.0"
WORKSPACE_SCHEMA = "beathi-workspace-1"

_TRANSITIONS = {"cut", "dissolve", "directional-wipe", "split-reveal", "hold-through"}
_LAYER_KINDS = {"editorial-typography", "graphic-field", "media-slice"}
_DRIVER_KINDS = {"ranked_onsets", "beat_phase", "energy_envelope"}
_MOTION_KINDS = {"scale_pulse", "translate_recoil", "opacity_lift"}
_BLEND_MODES = {"normal", "multiply", "screen", "difference", "overlay"}
_RATIOS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}

_PROJECT_ID_CHARS = set("0123456789abcdef")

# Stability bound for float comparisons against authored boundaries.
_TIME_EPSILON = 1e-3


# ---------------------------------------------------------------------------
# validation


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_string(value: Any) -> bool:
    return isinstance(value, str)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _walk_nonfinite(value: Any, path: str, errors: list[str]) -> None:
    """One stable code for any NaN/Infinity anywhere in the document."""
    if isinstance(value, float):
        if not math.isfinite(value):
            errors.append(f"direction/non-finite: {path} must be a finite number")
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk_nonfinite(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_nonfinite(item, f"{path}[{index}]", errors)


def _slug_ok(value: Any) -> bool:
    """Non-empty lowercase ASCII slug: alnum start, then alnum/'-' only."""
    if not _is_string(value) or not value:
        return False
    if not all(("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch == "-" for ch in value):
        return False
    if not ("a" <= value[0] <= "z" or "A" <= value[0] <= "Z" or "0" <= value[0] <= "9"):
        return False
    return value == value.lower()


def _scene_id_ok(scene_id: Any) -> bool:
    return _is_string(scene_id) and scene_id.startswith("scene-") and len(scene_id) > 6 and _slug_ok(scene_id[len("scene-"):])


def _anchor_of(scene: dict[str, Any], label: str, errors: list[str]) -> dict[str, Any] | None:
    anchor = scene.get("anchor")
    if not isinstance(anchor, dict) or anchor.get("kind") not in ("bars", "time"):
        errors.append(f"direction/anchor: {label}.anchor.kind must be 'bars' or 'time'")
        return None
    if anchor["kind"] == "bars":
        start, end = anchor.get("start_bar"), anchor.get("end_bar")
        if not _is_int(start) or start < 1 or not _is_int(end) or end < 1 or end <= start:
            errors.append(
                f"direction/anchor: {label}.anchor bars must be integers with start_bar < end_bar (1-based, exclusive end)"
            )
            return None
    else:
        start, end = anchor.get("start_seconds"), anchor.get("end_seconds")
        if not _finite(start) or start < 0 or not _finite(end) or end <= start:
            errors.append(f"direction/anchor: {label}.anchor seconds must be finite with start_seconds < end_seconds")
            return None
    return anchor


def _scene_time_ok(scene: dict[str, Any], label: str, errors: list[str]) -> tuple[float, float] | None:
    start, end = scene.get("start_time"), scene.get("end_time")
    if not _finite(start) or start < 0 or not _finite(end) or end <= start:
        errors.append(f"direction/scene-times: {label} start_time/end_time must be finite with start_time < end_time")
        return None
    return float(start), float(end)


def _validate_layer(layer: dict[str, Any], label: str, errors: list[str], notices: list[str]) -> None:
    # Layer ids follow the slug charset rule without the scene- prefix.
    if not _slug_ok(layer.get("id")):
        errors.append(f"direction/layer-id: {label}.id must be a non-empty lowercase slug")
    if not _is_string(layer.get("label")) or not layer.get("label"):
        errors.append(f"direction/layer-label: {label}.label must be a non-empty string")
    if not isinstance(layer.get("visible"), bool) or not isinstance(layer.get("locked"), bool):
        errors.append(f"direction/layer-flags: {label}.visible/.locked must be booleans")
    opacity = layer.get("opacity")
    if not _finite(opacity) or not 0.0 <= float(opacity) <= 1.0:
        errors.append(f"direction/layer-opacity: {label}.opacity must be within 0..1")
    blend = layer.get("blend")
    if not _is_string(blend):
        errors.append(f"direction/layer-blend: {label}.blend must be a string")
    elif blend not in _BLEND_MODES:
        notices.append(f"direction/layer-blend-unknown: {label}.blend '{blend}' is not in the core set; preserved as authored")
    kind = layer.get("kind")
    if not _is_string(kind) or not kind:
        errors.append(f"direction/layer-kind: {label}.kind must be a non-empty string")
    elif kind not in _LAYER_KINDS:
        notices.append(f"direction/layer-kind-unknown: {label}.kind '{kind}' is not registered; preserved as authored")
    transform = layer.get("transform")
    if not isinstance(transform, dict):
        errors.append(f"direction/layer-transform: {label}.transform must be an object")
    else:
        x, y, w, h = transform.get("x"), transform.get("y"), transform.get("w"), transform.get("h")
        if not all(_finite(v) for v in (x, y, w, h)):
            errors.append(f"direction/layer-transform: {label}.transform.x/.y/.w/.h must be finite numbers")
        else:
            if not 0.0 <= float(x) <= 1.0 or not 0.0 <= float(y) <= 1.0:
                errors.append(f"direction/layer-transform: {label}.transform.x/.y must be normalized 0..1")
            if float(w) <= 0 or float(h) <= 0:
                errors.append(f"direction/layer-transform: {label}.transform.w/.h must be positive")
        if not _finite(transform.get("rotation")):
            errors.append(f"direction/layer-transform: {label}.transform.rotation must be finite")
    if "crop" in layer.get("transform", {}):
        crop = transform.get("crop")
        if (
            not isinstance(crop, dict)
            or not all(_finite(crop.get(k)) for k in ("left", "top", "right", "bottom"))
            or not all(0.0 <= float(crop[k]) <= 1.0 for k in ("left", "top", "right", "bottom"))
        ):
            errors.append(f"direction/layer-transform: {label}.transform.crop must carry left/top/right/bottom within 0..1")


def _validate_driver(driver: Any, label: str, errors: list[str], notices: list[str]) -> None:
    if not isinstance(driver, dict) or not _is_string(driver.get("kind")):
        errors.append(f"direction/driver: {label}.driver must be an object with a kind")
        return
    if driver["kind"] not in _DRIVER_KINDS:
        notices.append(f"direction/driver-unknown: {label}.driver.kind '{driver['kind']}' is not registered; preserved as authored")
        return
    if driver["kind"] == "ranked_onsets":
        if driver.get("band") not in ("low", "mid", "high") or driver.get("tier") not in ("primary", "secondary"):
            errors.append(f"direction/driver: {label}.driver band/tier are out of range")
        if not _is_int(driver.get("max_events_per_bar")) or driver["max_events_per_bar"] < 1:
            errors.append(f"direction/driver: {label}.driver.max_events_per_bar must be a positive integer")
        if not _finite(driver.get("refractory_beats")) or driver["refractory_beats"] < 0:
            errors.append(f"direction/driver: {label}.driver.refractory_beats must be a non-negative number")
    elif driver["kind"] == "beat_phase":
        if not _is_int(driver.get("subdivision")) or driver["subdivision"] not in (1, 2, 4):
            errors.append(f"direction/driver: {label}.driver.subdivision must be 1, 2 or 4")
    else:  # energy_envelope
        if driver.get("band") not in ("low", "mid", "high"):
            errors.append(f"direction/driver: {label}.driver.band must be low, mid or high")


def _validate_motion(motion: Any, label: str, errors: list[str], notices: list[str]) -> None:
    if not isinstance(motion, dict) or not _is_string(motion.get("kind")):
        errors.append(f"direction/motion: {label}.motion must be an object with a kind")
        return
    if motion["kind"] not in _MOTION_KINDS:
        notices.append(f"direction/motion-unknown: {label}.motion.kind '{motion['kind']}' is not registered; preserved as authored")
        return
    for field in ("attack_seconds", "release_seconds"):
        if not _finite(motion.get(field)) or motion[field] < 0:
            errors.append(f"direction/motion: {label}.motion.{field} must be a non-negative number")
    if not _finite(motion.get("amount")):
        errors.append(f"direction/motion: {label}.motion.amount must be a finite number")
    if motion["kind"] == "translate_recoil":
        axis = motion.get("axis")
        if (
            not isinstance(axis, list)
            or len(axis) != 2
            or not all(_finite(v) for v in axis)
        ):
            errors.append(f"direction/motion: {label}.motion.axis must be a pair of finite numbers")


def validate_direction(doc: Any) -> tuple[list[str], list[str]]:
    """Return ``(errors, notices)`` with stable ``direction/...`` codes.

    Errors mean the document is refused (save/export); notices mean an
    unregistered-but-well-formed kind was preserved as authored.
    """
    errors: list[str] = []
    notices: list[str] = []
    if not isinstance(doc, dict):
        return (["direction/schema: document must be an object"], [])
    _walk_nonfinite(doc, "doc", errors)

    if doc.get("schema") != DIRECTION_SCHEMA:
        errors.append(f"direction/schema-version: schema must be '{DIRECTION_SCHEMA}'")
    if not _is_string(doc.get("version")) or not doc.get("version"):
        errors.append("direction/version: version must be a non-empty string")
    project_id = doc.get("project_id")
    if not _is_string(project_id) or len(project_id) != 12 or any(ch not in _PROJECT_ID_CHARS for ch in project_id):
        errors.append("direction/project-id: project_id must be 12 lowercase hex characters")
    if not _is_string(doc.get("project_title")) or not doc.get("project_title"):
        errors.append("direction/title: project_title must be a non-empty string")
    sha = doc.get("source_rhythm_sha256")
    if not _is_string(sha) or len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
        errors.append("direction/source-sha: source_rhythm_sha256 must be 64 hex characters")

    composition = doc.get("composition")
    if not isinstance(composition, dict):
        errors.append("direction/composition: composition must be an object")
    else:
        ratio = composition.get("primary_ratio")
        if ratio not in _RATIOS:
            errors.append("direction/ratio: primary_ratio must be '16:9', '9:16' or '1:1'")
        else:
            width, height = _RATIOS[ratio]
            if composition.get("width") != width or composition.get("height") != height:
                errors.append(f"direction/composition: {ratio} requires {width}x{height}")
        background = composition.get("background")
        if not _is_string(background) or not background.startswith("#") or len(background) != 7:
            errors.append("direction/composition: background must be a #rrggbb string")

    for field, expected_type in (("theme", dict), ("assets", list), ("transitions", list), ("diagnostics", dict)):
        if not isinstance(doc.get(field), expected_type):
            errors.append(f"direction/{field}: {field} must be a {expected_type.__name__}")

    scenes = doc.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        errors.append("direction/scenes: scenes must be a non-empty list")
        return (errors, notices)

    scene_ids: set[str] = set()
    previous_end_time: float | None = None
    previous_end_bar: int | None = None
    anchors_are_bars = True
    for position, scene in enumerate(scenes):
        label = f"scenes[{position}]"
        if not isinstance(scene, dict):
            errors.append(f"direction/scenes: {label} must be an object")
            continue
        scene_id = scene.get("id")
        if not _scene_id_ok(scene_id):
            errors.append(f"direction/scene-id: {label}.id must match scene-<lowercase-slug>")
        elif scene_id in scene_ids:
            errors.append(f"direction/scene-duplicate: {label}.id '{scene_id}' is duplicated")
        else:
            scene_ids.add(scene_id)
        if not _is_string(scene.get("title")) or not scene.get("title"):
            errors.append(f"direction/scene-title: {label}.title must be a non-empty string")
        if not _is_string(scene.get("family")):
            errors.append(f"direction/scene-family: {label}.family must be a string")
        if scene.get("transition_out") not in _TRANSITIONS:
            errors.append(f"direction/scene-transition: {label}.transition_out must be one of {sorted(_TRANSITIONS)}")

        span = _scene_time_ok(scene, label, errors)
        anchor = _anchor_of(scene, label, errors)
        if anchor is not None:
            anchors_are_bars = anchors_are_bars and anchor["kind"] == "bars"
            if anchor["kind"] == "bars" and previous_end_bar is not None and _is_int(anchor.get("start_bar")):
                if anchor["start_bar"] != previous_end_bar:
                    errors.append(
                        f"direction/scene-overlap: {label} starts at bar {anchor['start_bar']} "
                        f"while the previous scene ends at bar {previous_end_bar}"
                    )
                previous_end_bar = anchor.get("end_bar")
            elif anchor["kind"] == "bars":
                previous_end_bar = anchor.get("end_bar")

        if span is not None and previous_end_time is not None:
            if abs(span[0] - previous_end_time) > _TIME_EPSILON:
                errors.append(
                    f"direction/scene-continuity: {label} starts at {_canonical_number(span[0])} "
                    f"while the previous scene ends at {_canonical_number(previous_end_time)}"
                )
        if span is not None:
            previous_end_time = span[1]

        layers = scene.get("layers")
        if not isinstance(layers, list):
            errors.append(f"direction/scenes: {label}.layers must be a list")
            layers = []
        layer_ids: set[str] = set()
        for lpos, layer in enumerate(layers):
            llabel = f"{label}.layers[{lpos}]"
            if not isinstance(layer, dict):
                errors.append(f"direction/scenes: {llabel} must be an object")
                continue
            _validate_layer(layer, llabel, errors, notices)
            lid = layer.get("id")
            if _is_string(lid):
                if lid in layer_ids:
                    errors.append(f"direction/layer-duplicate: {llabel}.id '{lid}' is duplicated")
                layer_ids.add(lid)

        responses = scene.get("responses")
        if not isinstance(responses, list):
            errors.append(f"direction/scenes: {label}.responses must be a list")
            responses = []
        response_ids: set[str] = set()
        for rpos, response in enumerate(responses):
            rlabel = f"{label}.responses[{rpos}]"
            if not isinstance(response, dict):
                errors.append(f"direction/scenes: {rlabel} must be an object")
                continue
            rid = response.get("id")
            if not _is_string(rid) or not rid:
                errors.append(f"direction/response-id: {rlabel}.id must be a non-empty string")
            elif rid in response_ids:
                errors.append(f"direction/response-duplicate: {rlabel}.id '{rid}' is duplicated")
            else:
                response_ids.add(rid)
            if not _is_string(response.get("label")) or not response.get("label"):
                errors.append(f"direction/response-label: {rlabel}.label must be a non-empty string")
            if response.get("target_layer_id") not in layer_ids:
                errors.append(
                    f"direction/response-layer: {rlabel}.target_layer_id '{response.get('target_layer_id')}' does not exist in this scene"
                )
            reason = response.get("unavailable_reason")
            if reason is not None and not _is_string(reason):
                errors.append(f"direction/response-unavailable: {rlabel}.unavailable_reason must be a string when present")
            _validate_driver(response.get("driver"), rlabel, errors, notices)
            _validate_motion(response.get("motion"), rlabel, errors, notices)

    return (errors, notices)


# ---------------------------------------------------------------------------
# canonical bytes


def _canonical_number(value: float) -> str:
    """Six fractional decimals, trailing zeros stripped, -0 -> 0."""
    if not math.isfinite(value):
        raise ValueError("direction document contains a non-finite number")
    text = f"{value:.6f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text


def _canonical_json(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("direction document contains a non-finite number")
        out.append(_canonical_number(value))
    elif isinstance(value, str):
        out.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, list):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _canonical_json(item, out)
        out.append("]")
    elif isinstance(value, dict):
        out.append("{")
        for index, key in enumerate(sorted(value.keys())):
            if index:
                out.append(",")
            out.append(json.dumps(str(key), ensure_ascii=False))
            out.append(":")
            _canonical_json(value[key], out)
        out.append("}")
    else:
        raise TypeError(f"direction document contains unsupported value: {type(value)!r}")


def canonical_direction_bytes(doc: dict[str, Any]) -> bytes:
    """Deterministic UTF-8 JSON bytes; the mirror lives in contract.ts."""
    errors, _ = validate_direction(doc)
    if errors:
        raise ValueError("cannot canonicalize an invalid direction document: " + "; ".join(errors))
    out: list[str] = []
    _canonical_json(doc, out)
    return "".join(out).encode("utf-8")


def validate_workspace(doc: Any) -> list[str]:
    """Validate editor-only state kept outside the Agent-facing document."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["workspace/schema: document must be an object"]
    _walk_nonfinite(doc, "workspace", errors)
    if doc.get("schema") != WORKSPACE_SCHEMA:
        errors.append(f"workspace/schema-version: schema must be '{WORKSPACE_SCHEMA}'")
    if doc.get("version") != DIRECTION_DOC_VERSION:
        errors.append(f"workspace/version: version must be '{DIRECTION_DOC_VERSION}'")
    project_id = doc.get("project_id")
    if not _is_string(project_id) or len(project_id) != 12 or any(ch not in _PROJECT_ID_CHARS for ch in project_id):
        errors.append("workspace/project-id: project_id must be 12 lowercase hex characters")
    sha = doc.get("source_rhythm_sha256")
    if not _is_string(sha) or len(sha) != 64 or any(ch not in _PROJECT_ID_CHARS for ch in sha):
        errors.append("workspace/source-sha: source_rhythm_sha256 must be 64 lowercase hex characters")
    layout = doc.get("layout")
    if not isinstance(layout, dict) or not isinstance(layout.get("boards"), dict):
        errors.append("workspace/layout: layout.boards must be an object")
    camera = doc.get("camera")
    if not isinstance(camera, dict) or not all(_finite(camera.get(k)) for k in ("x", "y", "zoom")) or float(camera.get("zoom", 0)) <= 0:
        errors.append("workspace/camera: camera x/y must be finite and zoom must be positive")
    if not isinstance(doc.get("selection"), dict):
        errors.append("workspace/selection: selection must be an object")
    if not isinstance(doc.get("panels"), dict):
        errors.append("workspace/panels: panels must be an object")
    return errors


def canonical_workspace_bytes(doc: dict[str, Any]) -> bytes:
    errors = validate_workspace(doc)
    if errors:
        raise ValueError("cannot canonicalize an invalid workspace document: " + "; ".join(errors))
    out: list[str] = []
    _canonical_json(doc, out)
    return "".join(out).encode("utf-8")


def migrate_round2_draft(doc: dict[str, Any]) -> dict[str, Any]:
    """Upgrade pre-freeze Round 2 draft keys without changing timestamps."""
    migrated = json.loads(json.dumps(doc))
    migrated.setdefault("theme", {})
    migrated.setdefault("assets", [])
    migrated.setdefault("transitions", [])
    migrated.setdefault("diagnostics", {})
    for scene in migrated.get("scenes", []):
        anchor = scene.get("anchor", {})
        if anchor.get("kind") == "time":
            if "start" in anchor:
                anchor["start_seconds"] = anchor.pop("start")
            if "end" in anchor:
                anchor["end_seconds"] = anchor.pop("end")
        for response in scene.get("responses", []):
            if "layer_id" in response:
                response["target_layer_id"] = response.pop("layer_id")
            driver = response.get("driver", {})
            if driver.get("kind") == "ranked_onsets" and "refractory_seconds" in driver:
                driver["refractory_beats"] = round(float(driver.pop("refractory_seconds")) * 2.0, 6)
    return migrated


def direction_etag(payload: bytes) -> str:
    """Quoted strong ETag over canonical bytes (web_api GET convention)."""
    return f'"{hashlib.sha256(payload).hexdigest()}"'


# ---------------------------------------------------------------------------
# structure -> scenes derivation (Rhythm IR stays byte-identical)


def _bar_seconds(rhythm: dict[str, Any]) -> float | None:
    tempo = rhythm.get("tempo") or {}
    meter = rhythm.get("meter") or {}
    bpm = tempo.get("global_bpm")
    numerator = meter.get("numerator")
    if not _finite(bpm) or bpm <= 0 or not _is_int(numerator) or numerator < 1:
        return None
    return 60.0 / float(bpm) * numerator


def resolve_anchor_times(
    anchor: dict[str, Any],
    grid: dict[str, Any] | None,
    bar_seconds: float | None,
) -> tuple[float, float]:
    """Half-open anchor -> (start, end) media seconds.

    Bar ``n`` begins at ``origin + (n - 1) * bar_seconds`` (bars are
    1-based, anchor end is exclusive). Time anchors pass through exactly,
    so both fallback semantics agree at exact boundaries.
    """
    if anchor["kind"] == "time":
        return float(anchor["start_seconds"]), float(anchor["end_seconds"])
    if grid is None or bar_seconds is None:
        raise ValueError("bars anchors require the project grid")
    origin = float(grid.get("origin", 0.0))
    start = origin + (int(anchor["start_bar"]) - 1) * bar_seconds
    end = origin + (int(anchor["end_bar"]) - 1) * bar_seconds
    return (round(start, 6), round(end, 6))


def derive_scenes_from_structure(rhythm: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Initial scenes from the Rhythm IR. Returns ``(scenes, mode)`` where
    mode is ``'segments'``, ``'bars'`` or ``'time'``. Never mutates the IR.
    """
    duration = float((rhythm.get("source") or {}).get("duration") or 0.0)
    grid = rhythm.get("grid") if isinstance(rhythm.get("grid"), dict) else None
    total_bars = int(grid.get("bars")) if grid and _is_int(grid.get("bars")) else 0
    bar_seconds = _bar_seconds(rhythm)
    origin = float(grid.get("origin", 0.0)) if grid else 0.0

    segments = None
    patterns = rhythm.get("patterns")
    if isinstance(patterns, dict) and isinstance(patterns.get("segments"), list) and patterns["segments"]:
        segments = patterns["segments"]

    scenes: list[dict[str, Any]] = []
    if segments and all(
        _is_int(s.get("start_bar")) and _is_int(s.get("end_bar")) and _finite(s.get("start_time")) and _finite(s.get("end_time"))
        for s in segments
        if isinstance(s, dict)
    ) and all(isinstance(s, dict) for s in segments):
        for index, segment in enumerate(segments):
            start_time = round(float(segment["start_time"]), 6)
            end_time = round(float(segment["end_time"]), 6)
            scenes.append(
                {
                    "id": f"scene-{index + 1:02d}",
                    "title": str(segment.get("display_label") or segment.get("family") or f"Scene {index + 1:02d}"),
                    "family": str(segment.get("family") or "section"),
                    "anchor": {"kind": "bars", "start_bar": int(segment["start_bar"]), "end_bar": int(segment["end_bar"]) + 1},
                    "start_time": start_time,
                    "end_time": end_time,
                    "transition_out": "hold-through" if index == len(segments) - 1 else "cut",
                    "layers": [],
                    "responses": [],
                }
            )
        return (scenes, "segments")

    if grid and total_bars >= 1 and bar_seconds:
        # No structural segmentation: chunk the grid into 8-bar sections.
        chunk = 8
        count = math.ceil(total_bars / chunk)
        for index in range(count):
            start_bar = 1 + index * chunk
            end_bar = min(start_bar + chunk, total_bars + 1)
            start_time = round(origin + (start_bar - 1) * bar_seconds, 6)
            end_time = round(min(origin + (end_bar - 1) * bar_seconds, duration), 6) if index < count - 1 else round(duration, 6)
            if end_time <= start_time:
                end_time = round(min(start_time + bar_seconds, duration), 6)
            scenes.append(
                {
                    "id": f"scene-{index + 1:02d}",
                    "title": f"Scene {index + 1:02d}",
                    "family": "section",
                    "anchor": {"kind": "bars", "start_bar": start_bar, "end_bar": end_bar},
                    "start_time": start_time,
                    "end_time": end_time,
                    "transition_out": "hold-through" if index == count - 1 else "cut",
                    "layers": [],
                    "responses": [],
                }
            )
        return (scenes, "bars")

    # No-grid fallback: half-open time anchors only.
    if duration <= 0:
        raise ValueError("cannot derive scenes: the rhythm project has no duration and no grid")
    scene_seconds = 30.0
    count = max(1, math.ceil(duration / scene_seconds))
    for index in range(count):
        start_time = round(index * scene_seconds, 6)
        end_time = round(min((index + 1) * scene_seconds, duration), 6)
        scenes.append(
            {
                "id": f"scene-{index + 1:02d}",
                "title": f"Scene {index + 1:02d}",
                "family": "section",
                "anchor": {"kind": "time", "start_seconds": start_time, "end_seconds": end_time},
                "start_time": start_time,
                "end_time": end_time,
                "transition_out": "hold-through" if index == count - 1 else "cut",
                "layers": [],
                "responses": [],
            }
        )
    return (scenes, "time")


def build_direction_document(rhythm: dict[str, Any], scenes: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble the initial document around derived scenes."""
    source = rhythm.get("source") or {}
    return {
        "schema": DIRECTION_SCHEMA,
        "version": DIRECTION_DOC_VERSION,
        "project_id": rhythm["project_id"],
        "project_title": str(source.get("display_name") or rhythm["project_id"]),
        "source_rhythm_sha256": source.get("sha256"),
        "composition": {"primary_ratio": "16:9", "width": 1920, "height": 1080, "background": "#F5F1E8"},
        "theme": {},
        "assets": [],
        "scenes": scenes,
        "transitions": [],
        "diagnostics": {},
    }
