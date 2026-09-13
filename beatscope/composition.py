"""Single-artwork document contract, independent of the legacy direction schema."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .direction import _canonical_json

SCHEMA = json.loads((Path(__file__).parent / "data" / "composition-schema.json").read_text(encoding="utf-8"))
MAX_COMPOSITION_BYTES = 1024 * 1024


def validate_composition(document: Any, asset_ids: set[str] | None = None) -> list[str]:
    """Reject unknown fields instead of silently destroying them on a round trip."""
    errors: list[str] = []

    def walk(value: Any, rule: dict, path: str) -> None:
        if "enum" in rule:
            if not isinstance(value, str) or value not in rule["enum"]:
                errors.append(path + ":enum")
            return
        kind = rule["type"]
        valid = {
            "object": isinstance(value, dict), "array": isinstance(value, list),
            "string": isinstance(value, str), "boolean": isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        }[kind]
        if not valid:
            errors.append(path + ":type")
            return
        if kind == "object":
            for key in rule["required"]:
                if key not in value:
                    errors.append(path + "." + key + ":required")
            for key, child in value.items():
                if key not in rule["properties"]:
                    errors.append(path + "." + str(key) + ":unknown")
                else:
                    walk(child, rule["properties"][key], path + "." + key)
        elif kind == "array":
            if len(value) > rule["maxItems"]:
                errors.append(path + ":length")
                return
            for i, child in enumerate(value):
                walk(child, rule["items"], f"{path}[{i}]")
        elif kind == "number":
            if not rule["minimum"] <= value <= rule["maximum"] or not math.isfinite(value):
                errors.append(path + ":range")
        elif kind == "string":
            # JavaScript length is UTF-16 code units.
            if len(value.encode("utf-16-le", errors="surrogatepass")) // 2 > rule["maxLength"]:
                errors.append(path + ":length")
            if "pattern" in rule and re.fullmatch(rule["pattern"], value) is None:
                errors.append(path + ":pattern")
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
                errors.append(path + ":unicode")

    walk(document, SCHEMA, "$")
    if errors:
        return errors
    ids: set[str] = set()
    for layer in document["objects"]:
        if layer["id"] in ids:
            errors.append("objects:duplicate-id")
        ids.add(layer["id"])
        crop = layer["crop"]
        if crop["left"] + crop["right"] >= 1 or crop["top"] + crop["bottom"] >= 1:
            errors.append("objects:crop-empty")
        if layer["kind"] != "text" and (not layer["asset_id"] or
                (asset_ids is not None and layer["asset_id"] not in asset_ids)):
            errors.append("objects:asset-missing")
    response_ids: set[str] = set()
    for response in document["responses"]:
        if response["id"] in response_ids:
            errors.append("responses:duplicate-id")
        response_ids.add(response["id"])
        if response["target_id"] not in ids:
            errors.append("responses:target-missing")
    if (document["background"]["mode"] == "solid") != (document["background"]["preset_id"] == ""):
        errors.append("background:mode-mismatch")
    return errors


def composition_bytes(document: dict) -> bytes:
    errors = validate_composition(document)
    if errors:
        raise ValueError("; ".join(errors))
    chunks: list[str] = []
    _canonical_json(document, chunks)
    payload = "".join(chunks).encode("utf-8")
    if len(payload) > MAX_COMPOSITION_BYTES:
        raise ValueError("composition/too-large")
    # Canonical rounding must not turn a valid narrow crop into an empty crop.
    errors = validate_composition(json.loads(payload))
    if errors:
        raise ValueError("; ".join(errors))
    return payload


def new_composition(project_id: str, rhythm_sha256: str, title: str) -> dict:
    title = title.encode("utf-16-le")[:400].decode("utf-16-le", errors="ignore")
    return {
        "schema": "beatscope-composition-1", "project_id": project_id,
        "source_rhythm_sha256": rhythm_sha256, "title": title,
        "artwork": {"width": 1920, "height": 1080, "color": "#17191c"},
        "background": {"preset_id": "", "mode": "solid", "opacity": 1},
        "objects": [], "responses": [], "author_notes": "",
    }
