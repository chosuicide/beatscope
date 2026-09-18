"""Generate tests/fixtures/direction/contract-corpus.json (plan §4.7).

The corpus pins the `beatscope-direction-1` contract across the two
implementations (beatscope/direction.py and web-src/src/direction/contract.ts):

- ``number_cases`` — hand-written expected canonical forms for the shared
  six-decimal number formatter (not computed by the module under test);
- ``doc_cases`` — documents with hand-listed expected error/notice CODES;
  valid cases additionally carry the full canonical string and its SHA-256,
  recorded here mechanically so both languages must agree byte for byte.

Both test suites read the checked-in JSON; neither is allowed to "pass" by
regenerating expectations at test time.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from beatscope.direction import canonical_direction_bytes, validate_direction  # noqa: E402

SCHEMA = "beatscope-direction-1"

# Hand-written expectations for _canonical_number / canonicalNumber.
NUMBER_CASES = [
    [0.0, "0"],
    [-0.0, "0"],
    [1.0, "1"],
    [0.5, "0.5"],
    [-2.5, "-2.5"],
    [0.1, "0.1"],
    [1 / 3, "0.333333"],
    [15.9869, "15.9869"],
    [0.123456789, "0.123457"],
    [1e-7, "0"],
    [-1e-7, "0"],
    [2.0000006, "2.000001"],
    [123.4567894, "123.456789"],
    [1920, "1920"],
    [1e15, "1000000000000000"],
]

# Hand-written expected canonical form of the formatting doc's props object
# (key order = code point, numbers via the shared formatter, unicode raw).
EXPECTED_PROPS_CANONICAL = (
    '{"M_case":0.5,"a_first":0.1,"big":1920,'
    '"esc":"line\\nbreak \\"quoted\\" back\\\\slash",'
    '"neg":-2.5,"neg_tiny":0,"neg_zero":0,"one":1,"prec":0.123457,'
    '"round_down":123.456789,"round_up":2.000001,"third":0.333333,'
    '"time":15.9869,"tiny":0,"unicode":"雾中之雾","z_last":1,"zero":0}'
)


def scene(index: int, start_bar: int, end_bar: int, start_time: float, end_time: float, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": f"scene-{index:02d}",
        "title": f"Scene {index:02d}",
        "family": "section",
        "anchor": {"kind": "bars", "start_bar": start_bar, "end_bar": end_bar},
        "start_time": start_time,
        "end_time": end_time,
        "transition_out": "cut",
        "layers": [],
        "responses": [],
    }
    body.update(over)
    return body


def base_doc(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "version": "0.12.0",
        "project_id": "62bce8192088",
        "project_title": "Beyond the Fog",
        "source_rhythm_sha256": "ab" * 32,
        "composition": {"primary_ratio": "16:9", "width": 1920, "height": 1080, "background": "#F5F1E8"},
        "theme": {},
        "assets": [],
        "scenes": [scene(1, 1, 13, 0.0, 24.0)],
        "transitions": [],
        "diagnostics": {},
    }
    doc.update(over)
    return doc


def full_layer() -> dict[str, Any]:
    return {
        "id": "lay-title-01",
        "kind": "editorial-typography",
        "label": "Title",
        "visible": True,
        "locked": False,
        "opacity": 1.0,
        "blend": "normal",
        "transform": {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.3, "rotation": -0.123457, "crop": {"left": 0.0, "top": 0.1, "right": 1.0, "bottom": 0.9}},
        "props": {},
    }


def ranked_response(layer_id: str = "lay-title-01") -> dict[str, Any]:
    return {
        "id": "resp-01",
        "target_layer_id": layer_id,
        "label": "Mid onsets lift",
        "driver": {"kind": "ranked_onsets", "band": "mid", "tier": "primary", "max_events_per_bar": 2, "refractory_beats": 0.4},
        "motion": {"kind": "opacity_lift", "amount": 0.08, "attack_seconds": 0.02, "release_seconds": 0.3},
    }


def doc_case(
    name: str,
    doc: Any,
    error_codes: list[str],
    notice_codes: list[str],
    asset_ids: list[str] | None = None,
) -> dict[str, Any]:
    case: dict[str, Any] = {"name": name, "doc": doc, "expected_error_codes": error_codes, "expected_notice_codes": notice_codes}
    if asset_ids is not None:
        case["asset_ids"] = asset_ids
    return case


def build_doc_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    # 1. minimal valid document
    cases.append(doc_case("minimal-valid", base_doc(), [], []))

    # 2. full document: every registered kind, crop, all three drivers/motions
    doc = base_doc()
    s = doc["scenes"][0]
    s["layers"].append(full_layer())
    s["responses"].append(ranked_response())
    s["responses"].append({
        "id": "resp-02",
        "target_layer_id": "lay-title-01",
        "label": "Beat phase sway",
        "driver": {"kind": "beat_phase", "subdivision": 2},
        "motion": {"kind": "translate_recoil", "axis": [1.0, 0.0], "amount": 6.0, "attack_seconds": 0.03, "release_seconds": 0.25},
    })
    s["responses"].append({
        "id": "resp-03",
        "target_layer_id": "lay-title-01",
        "label": "Low energy drift",
        "driver": {"kind": "energy_envelope", "band": "low"},
        "motion": {"kind": "scale_pulse", "amount": 1.04, "attack_seconds": 0.4, "release_seconds": 1.2},
        "unavailable_reason": "energy stream not compiled for this project",
    })
    cases.append(doc_case("full-valid", doc, [], []))

    # 3. formatting doc: number cases + unicode + escapes + key order in props
    doc = base_doc(project_title="雾中之雾")
    layer = full_layer()
    layer["props"] = {
        "z_last": 1,
        "M_case": 0.5,
        "a_first": 0.1,
        "zero": 0.0,
        "neg_zero": -0.0,
        "one": 1.0,
        "neg": -2.5,
        "third": 1 / 3,
        "time": 15.9869,
        "prec": 0.123456789,
        "tiny": 1e-7,
        "neg_tiny": -1e-7,
        "round_up": 2.0000006,
        "round_down": 123.4567894,
        "big": 1920,
        "unicode": "雾中之雾",
        "esc": "line\nbreak \"quoted\" back\\slash",
    }
    doc["scenes"][0]["layers"].append(layer)
    cases.append(doc_case("formatting", doc, [], []))

    # 4. unknown kinds preserved as notices (never errors, never stripped)
    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    layer["kind"] = "hologram"
    layer["blend"] = "phosphor"
    s["layers"].append(layer)
    s["responses"].append(ranked_response())
    s["responses"][0]["driver"] = {"kind": "spectral_flux", "band": "mid"}
    s["responses"][0]["motion"] = {"kind": "wiggle", "amount": 1.0}
    cases.append(doc_case(
        "unknown-kinds", doc, [],
        ["direction/layer-blend-unknown", "direction/layer-kind-unknown", "direction/driver-unknown", "direction/motion-unknown"],
    ))

    # 5. top-level unknown keys survive canonicalization
    doc = base_doc(editor_notes={"keep": "一切都会保留", "z": 1, "A": 2})
    cases.append(doc_case("unknown-top-level-key", doc, [], []))

    # 6. time-anchored scenes (no-grid fallback shape) are valid
    doc = base_doc()
    doc["scenes"] = [
        {"id": "scene-01", "title": "A", "family": "section", "anchor": {"kind": "time", "start_seconds": 0.0, "end_seconds": 30.0},
         "start_time": 0.0, "end_time": 30.0, "transition_out": "cut", "layers": [], "responses": []},
        {"id": "scene-02", "title": "B", "family": "section", "anchor": {"kind": "time", "start_seconds": 30.0, "end_seconds": 48.0},
         "start_time": 30.0, "end_time": 48.0, "transition_out": "hold-through", "layers": [], "responses": []},
    ]
    cases.append(doc_case("time-anchors", doc, [], []))

    # refusal cases — one stable code each, in traversal order
    doc = base_doc()
    doc["scenes"].append(scene(2, 13, 25, 24.0, 48.0))
    doc["scenes"][1]["id"] = "scene-01"  # duplicate id, otherwise continuous
    cases.append(doc_case("duplicate-scene-id", doc, ["direction/scene-duplicate"], []))

    doc = base_doc()
    doc["scenes"][0]["id"] = "Scene-1"
    cases.append(doc_case("bad-scene-id", doc, ["direction/scene-id"], []))

    doc = base_doc()
    doc["scenes"][0]["transition_out"] = "crossfade"
    cases.append(doc_case("bad-transition", doc, ["direction/scene-transition"], []))

    doc = base_doc()
    doc["scenes"][0]["start_time"] = 30.0
    doc["scenes"][0]["end_time"] = 24.0
    cases.append(doc_case("inverted-times", doc, ["direction/scene-times"], []))

    doc = base_doc()
    doc["scenes"].append(scene(2, 1, 25, 0.0, 48.0))  # bar AND time restart
    cases.append(doc_case("overlap-bars-and-time", doc, ["direction/scene-overlap", "direction/scene-continuity"], []))

    doc = base_doc()
    doc["scenes"].append(scene(2, 13, 25, 0.0, 48.0))  # times restart, bars fine
    cases.append(doc_case("overlap-time-only", doc, ["direction/scene-continuity"], []))

    doc = base_doc()
    doc["composition"]["primary_ratio"] = "4:3"
    cases.append(doc_case("bad-ratio", doc, ["direction/ratio"], []))

    doc = base_doc()
    doc["composition"]["primary_ratio"] = "1:1"
    doc["composition"]["width"] = 1080
    doc["composition"]["height"] = 1080
    cases.append(doc_case("square-ratio-valid", doc, [], []))

    doc = base_doc()
    doc["composition"]["width"] = 1080
    cases.append(doc_case("composition-size-mismatch", doc, ["direction/composition"], []))

    doc = base_doc()
    doc["composition"]["background"] = "cream"
    cases.append(doc_case("bad-background", doc, ["direction/composition"], []))

    doc = base_doc()
    doc["project_id"] = "beyondthefog"
    cases.append(doc_case("bad-project-id", doc, ["direction/project-id"], []))

    doc = base_doc()
    doc["source_rhythm_sha256"] = "zz" * 32
    cases.append(doc_case("bad-source-sha", doc, ["direction/source-sha"], []))

    doc = base_doc()
    doc["schema"] = "beatscope-direction-2"
    cases.append(doc_case("bad-schema", doc, ["direction/schema-version"], []))

    doc = base_doc()
    doc["scenes"] = []
    cases.append(doc_case("empty-scenes", doc, ["direction/scenes"], []))

    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    layer["transform"]["x"] = 1.5
    s["layers"].append(layer)
    s["responses"].append(ranked_response())
    cases.append(doc_case("transform-out-of-range", doc, ["direction/layer-transform"], []))

    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    layer["transform"]["crop"] = {"left": 0.0, "top": 0.0, "right": 2.0, "bottom": 1.0}
    s["layers"].append(layer)
    s["responses"].append(ranked_response())
    cases.append(doc_case("crop-out-of-range", doc, ["direction/layer-transform"], []))

    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    layer["opacity"] = 1.5
    s["layers"].append(layer)
    s["responses"].append(ranked_response())
    cases.append(doc_case("opacity-out-of-range", doc, ["direction/layer-opacity"], []))

    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    s["layers"].append(layer)
    s["responses"].append(ranked_response())
    s["responses"][0]["target_layer_id"] = "lay-missing"
    cases.append(doc_case("response-layer-missing", doc, ["direction/response-layer"], []))

    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    s["layers"].append(layer)
    s["responses"].append(ranked_response())
    s["responses"][0]["driver"] = {"kind": "beat_phase", "subdivision": 3}
    cases.append(doc_case("bad-subdivision", doc, ["direction/driver"], []))

    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    s["layers"].append(layer)
    s["responses"].append(ranked_response())
    s["responses"][0]["driver"]["refractory_beats"] = -0.1
    cases.append(doc_case("negative-refractory", doc, ["direction/driver"], []))

    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    s["layers"].append(layer)
    s["responses"].append(ranked_response())
    s["responses"][0]["motion"]["attack_seconds"] = -1.0
    cases.append(doc_case("negative-attack", doc, ["direction/motion"], []))

    doc = [1, 2, 3]
    cases.append(doc_case("not-an-object", doc, ["direction/schema"], []))

    # 24. every Round 3 driver and motion operator is a registered kind
    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    s["layers"].append(layer)
    drivers = [
        {"kind": "downbeat_impulse"},
        {"kind": "structure_boundary"},
        {"kind": "scene_phase"},
        {"kind": "transition_phase"},
        {"kind": "energy_envelope", "band": "high"},
    ]
    motions = [
        {"kind": "radial_expand", "amount": 0.04, "attack_seconds": 0.02, "release_seconds": 0.2},
        {"kind": "translate_drift", "axis": [0.0, 1.0], "amount": 0.02, "attack_seconds": 0.05, "release_seconds": 0.3},
        {"kind": "rotate_recoil", "amount": 1.5, "attack_seconds": 0.02, "release_seconds": 0.25},
        {"kind": "crop_reveal", "amount": 0.05, "attack_seconds": 0.03, "release_seconds": 0.3},
        {"kind": "invert_palette", "amount": 1.0, "attack_seconds": 0.01, "release_seconds": 0.12},
    ]
    for index, (driver, motion) in enumerate(zip(drivers, motions, strict=True)):
        s["responses"].append(
            {
                "id": f"resp-ext-{index + 1:02d}",
                "target_layer_id": layer["id"],
                "label": f"Extended {index + 1}",
                "driver": driver,
                "motion": motion,
            }
        )
    s["responses"].append(
        {
            "id": "resp-ext-06",
            "target_layer_id": layer["id"],
            "label": "Strip offset",
            "driver": {"kind": "scene_phase"},
            "motion": {"kind": "strip_offset", "amount": 0.03, "attack_seconds": 0.02, "release_seconds": 0.2},
        }
    )
    s["responses"].append(
        {
            "id": "resp-ext-07",
            "target_layer_id": layer["id"],
            "label": "Blur focus",
            "driver": {"kind": "transition_phase"},
            "motion": {"kind": "blur_focus", "amount": 2.5, "attack_seconds": 0.05, "release_seconds": 0.35},
        }
    )
    s["responses"].append(
        {
            "id": "resp-ext-08",
            "target_layer_id": layer["id"],
            "label": "Opacity fade",
            "driver": {"kind": "downbeat_impulse"},
            "motion": {"kind": "opacity_fade", "amount": 0.2, "attack_seconds": 0.04, "release_seconds": 0.4},
        }
    )
    cases.append(doc_case("extended-registry-valid", doc, [], []))

    # asset references are checked only when the caller supplies a manifest
    asset_id = "ab" * 32

    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    layer["kind"] = "media-slice"
    layer["props"] = {"src": f"asset:{asset_id}", "full": True}
    s["layers"].append(layer)
    cases.append(doc_case("asset-reference-valid", doc, [], [], asset_ids=[asset_id]))

    doc = base_doc()
    s = doc["scenes"][0]
    layer = full_layer()
    layer["kind"] = "media-slice"
    layer["props"] = {"src": f"asset:{asset_id}", "full": True}
    s["layers"].append(layer)
    cases.append(doc_case("asset-reference-missing", doc, ["direction/asset-missing"], [], asset_ids=[]))

    return cases


def main() -> None:
    cases = build_doc_cases()
    for case in cases:
        doc = case["doc"]
        asset_ids = set(case["asset_ids"]) if "asset_ids" in case else None
        errors, notices = validate_direction(doc, asset_ids)
        if not errors:
            body = canonical_direction_bytes(doc)
            case["canonical"] = body.decode("utf-8")
            case["canonical_sha256"] = hashlib.sha256(body).hexdigest()

    corpus = {
        "schema": SCHEMA,
        "number_cases": NUMBER_CASES,
        "expected_props_canonical": EXPECTED_PROPS_CANONICAL,
        "doc_cases": cases,
    }
    out = ROOT / "tests" / "fixtures" / "direction" / "contract-corpus.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(corpus, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} with {len(cases)} doc cases")


if __name__ == "__main__":
    main()
