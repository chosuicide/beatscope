"""Export utilities for Rhythm Reference MIDI, CSV, and visual snapshots."""
from __future__ import annotations

import csv
import io
import json
import struct
import zipfile
from pathlib import Path
from typing import Any

from .beatgrid import quantize_to_beat_grid
from .midi import TPQ, _meta_track, _meta_track_tempo_map, _tempo_map_tick, _track
from .visual_recipe import canonical_visual_bytes, compile_visual_artifacts
from .visual_recipe_schema import InvalidVisualRecipe


def _agent_skill_file(relative_path: str) -> str:
    """Read a bundled Codex skill resource from the installed package."""
    path = Path(__file__).with_name("agent_skill") / relative_path
    return path.read_text(encoding="utf-8")


def generate_rhythm_midi(rhythm_data: dict[str, Any], subdivision: int = 16) -> bytes:
    """Generate SMF MIDI for rhythm reference (note 60, velocity from strength).

    Event ticks come from the piecewise tempo map when the project carries
    ``tempo.segments``, so variable-tempo projects stay aligned in a DAW
    (plan section 19). The grid origin stays pinned to tick 0, matching the
    v0.5 single-BPM convention for single-segment projects.
    """
    tempo = rhythm_data.get("tempo", {}) or {}
    bpm = float(tempo.get("global_bpm") or tempo.get("bpm") or 120.0)
    origin = float(rhythm_data.get("grid", {}).get("origin", 0.0))
    segments = tempo.get("segments") or []
    beats = rhythm_data.get("beats", [])

    events: list[tuple[int, int, bytes]] = []
    for onset in rhythm_data.get("onsets", []):
        raw_t = float(onset.get("time", onset.get("raw_time", 0.0)))
        q = quantize_to_beat_grid(raw_t, beats, subdivision=subdivision)
        quantized_t = float(q.get("quantized_time", raw_t))
        if segments:
            tick = _tempo_map_tick(quantized_t, segments, origin)
        else:
            tick = max(0, int(round((quantized_t - origin) * bpm / 60.0 * TPQ)))
        str_val = float(onset.get("strength", 0.8))
        velocity = min(127, max(1, int(round(str_val * 126.0)) + 1))
        events += [
            (tick, 1, bytes((0x90, 60, velocity))),
            (tick + 30, 0, bytes((0x80, 60, 0))),
        ]

    track = _track(events, "BeatScope Rhythm Reference")
    header = b"MThd" + struct.pack(">IHHH", 6, 1, 2, TPQ)
    meta = _meta_track_tempo_map(segments, origin) if segments else _meta_track(bpm)
    return header + meta + track


def generate_rhythm_csv(rhythm_data: dict[str, Any], subdivision: int = 16) -> str:
    """Generate CSV string of all onsets with calculated quantized positions."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "raw_time",
        "quantized_time",
        "offset_ms",
        "bar",
        "beat",
        "step",
        "strength",
        "low",
        "mid",
        "high",
        "accent",
    ])

    beats = rhythm_data.get("beats", [])
    # v4 keeps accents in cues.accent; v3 kept a boolean on the onset itself.
    accent_ids = {
        int(cue["onset"])
        for cue in (rhythm_data.get("cues") or {}).get("accent", [])
        if isinstance(cue, dict) and isinstance(cue.get("onset"), int)
    }
    for onset in rhythm_data.get("onsets", []):
        raw_t = float(onset.get("time", onset.get("raw_time", 0.0)))
        q = quantize_to_beat_grid(raw_t, beats, subdivision=subdivision)
        bands = onset.get("bands", {})
        writer.writerow([
            f"{raw_t:.4f}",
            f"{q['quantized_time']:.4f}",
            f"{q['offset_ms']:.3f}",
            q["bar"],
            q["beat"],
            q["step_in_bar"],
            f"{float(onset.get('strength', 0.0)):.4f}",
            f"{float(bands.get('low', 0.0)):.4f}",
            f"{float(bands.get('mid', 0.0)):.4f}",
            f"{float(bands.get('high', 0.0)):.4f}",
            1 if onset.get("accent") or onset.get("id") in accent_ids else 0,
        ])

    return output.getvalue()


def _codex_rhythm_map(rhythm_data: dict[str, Any]) -> dict[str, Any]:
    """Return the stable, portable data contract used by an agent export.

    Keep private filesystem paths out of this document.  The original analysis
    result is intentionally retained under ``analysis`` so an agent can cite
    provenance without needing to re-run the analyzer.
    """
    source = rhythm_data.get("source", {})
    tempo = rhythm_data.get("tempo", {})
    grid = rhythm_data.get("grid", {})
    overview = rhythm_data.get("overview") or (rhythm_data.get("patterns") or {}).get("bars") or []
    sections = rhythm_data.get("sections") or [
        {k: item[k] for k in ("bar", "label", "group", "mean_strength", "similarity_previous") if k in item}
        for item in overview if isinstance(item, dict)
    ]
    beats = rhythm_data.get("beats", [])
    onsets = rhythm_data.get("onsets", [])
    meter = rhythm_data.get("meter") or {}
    cues = rhythm_data.get("cues")
    if not cues:
        cues = {"accent": [
            {"time": o.get("raw_time"), "onset": o.get("id")}
            for o in onsets if isinstance(o, dict) and o.get("accent")
        ]}
    bars = rhythm_data.get("bars") or grid.get("bars_data") or []
    if not isinstance(bars, list):
        bars = []
    if not bars:
        bar_numbers = range(1, int(grid.get("bars") or 0) + 1)
        by_bar = {n: [b for b in beats if int(b.get("bar", 0)) == n] for n in bar_numbers}
        bars = [{"bar": n, "start": float(items[0].get("time", 0)) if items else None,
                 "end": float(items[-1].get("time", 0)) if items else None,
                 "beats": items} for n, items in by_bar.items()]
    # v0.7 whole-song structure rides along (plan section 17): segments,
    # boundaries, repetitions, and diagnostics only. Self-similarity matrices
    # are analysis intermediates and never enter the export.
    source_patterns = rhythm_data.get("patterns") or {}
    structure_patterns = {
        key: source_patterns[key]
        for key in ("method", "segments", "boundaries", "repetitions", "diagnostics")
        if key in source_patterns
    }
    return {
        "schema_version": "beatscope-rhythm-map-1.0",
        "source_schema_version": rhythm_data.get("schema_version", "3.0"),
        "project_id": rhythm_data.get("project_id"),
        "source": {
            "display_name": source.get("display_name") or source.get("file") or "audio",
            "duration": float(source.get("duration") or 0),
            "sample_rate": source.get("sample_rate"),
            "channels": source.get("channels"),
            "sha256": source.get("sha256", ""),
        },
        "duration": float(source.get("duration") or 0),
        "bpm": float(tempo.get("global_bpm") or tempo.get("bpm") or 120),
        # Variable-tempo facts ride along (plan section 18.4): the exported
        # runtime reads real beats; segments document the piecewise tempo.
        "tempo": {
            "global_bpm": float(tempo.get("global_bpm") or tempo.get("bpm") or 120),
            "segments": tempo.get("segments") or [],
        },
        "origin": float(grid.get("origin") or 0),
        "time_signature": grid.get("time_signature") or [meter.get("numerator", 4), meter.get("denominator", 4)],
        "subdivision": int(grid.get("default_subdivision") or grid.get("subdivision") or 16),
        "bars_count": int(grid.get("bars") or 0),
        "bars": bars,
        "beats": beats,
        "onsets": onsets,
        "cues": cues,
        "energy": rhythm_data.get("energy", {}),
        "sections": sections,
        **({"patterns": structure_patterns} if structure_patterns.get("segments") else {}),
        "analysis": {
            "pipeline": rhythm_data.get("analysis", {}).get("pipeline") or rhythm_data.get("analysis", {}).get("backend"),
            "analyzer_version": rhythm_data.get("analysis", {}).get("analyzer_version") or rhythm_data.get("analysis", {}).get("pipeline_version"),
            "created_at": rhythm_data.get("analysis", {}).get("created_at"),
        },
    }


def _runtime_source() -> str:
    """Return the shared rhythm runtime module shipped with every export."""
    runtime_path = Path(__file__).with_name("runtime") / "runtime.js"
    return runtime_path.read_text(encoding="utf-8")


def _scene_director_source() -> str:
    """Return the shared scene director module shipped with every v0.8 export.

    The browser, the Codex export, and the MCP runtime worker all import the
    same file, so scene state has one implementation and one output shape
    (plan section 15).
    """
    director_path = Path(__file__).with_name("runtime") / "scene-director.js"
    return director_path.read_text(encoding="utf-8")


def _visual_data_module(constant: str, document: dict[str, Any]) -> str:
    """Generated data module so examples avoid network/file loading (plan 14.2).

    The JSON documents stay directly readable in the package; these modules
    exist only so `import` works without a build system or fetch layer.
    """
    body = canonical_visual_bytes(document).decode("utf-8")
    return (
        "// Generated by BeatScope: deterministic data module (do not hand-edit).\n"
        f"export const {constant} = {body}"
    )


def _visual_state_source(
    rhythm_map: dict[str, Any],
    visual_artifacts: tuple[dict[str, Any], dict[str, Any]] | None = None,
) -> str:
    """Build the visual-state.js module: data plus the shared runtime contract.

    getVisualState is exactly ``track.at(time)`` - the same time-query the
    web player samples - so both consumers share one implementation and one
    output shape (plan section 43). With compiled visual artifacts the scene
    surface is additive (plan section 14.2): getSceneState and
    getBeatScopeFrame ride the same module through the shared
    scene-director.js, and getVisualState's own output stays byte-identical.
    Without artifacts the legacy single-function shim is emitted unchanged.
    """
    data = json.dumps(rhythm_map, ensure_ascii=False, separators=(",", ":"))
    if visual_artifacts is None:
        head = "// BeatScope visual state contract — deterministic and seek-safe.\n"
        head += "import { createTrack } from './beatscope-runtime.js';\n\n"
        head += "export const RHYTHM_MAP = "
        tail = ''';

const track = createTrack(RHYTHM_MAP);

export function getVisualState(time) {
  return track.at(time);
}
'''
        return head + data + tail
    head = (
        "// BeatScope visual state contract — deterministic and seek-safe.\n"
        "// Timing state and scene state are separate surfaces: getVisualState\n"
        "// reports rhythm facts, getSceneState reports the structural scene,\n"
        "// and getBeatScopeFrame returns both from one call.\n"
        "import { createTrack } from './beatscope-runtime.js';\n"
        "import { createSceneDirector } from './scene-director.js';\n"
        "import { VISUAL_RECIPE } from './visual-recipe-data.js';\n"
        "import { VISUAL_TIMELINE } from './visual-timeline-data.js';\n\n"
        "export const RHYTHM_MAP = "
    )
    tail = ''';

const track = createTrack(RHYTHM_MAP);
const sceneDirector = createSceneDirector(VISUAL_RECIPE, VISUAL_TIMELINE);

export function getVisualState(time) {
  return track.at(time);
}

export function getSceneState(time, options) {
  return sceneDirector.at(time, options);
}

export function getBeatScopeFrame(time, options) {
  return {
    timing: getVisualState(time),
    scene: getSceneState(time, options),
  };
}
'''
    return head + data + tail


_LEGACY_HANDOFF = '''# BeatScope handoff: {display_name}\n\nThis package is the inspected timing data for one audio file. It is intended to be handed to an agent making an audio-reactive web, video, or motion visual.\n\n## Rules\n\n- Do not re-analyse the audio. Use `rhythm-map.json` as the source of analysed timing facts.\n- Use `audio.currentTime` as the only clock. Call `getVisualState(time)` from `visual-state.js` for animation state.\n- Every animation must remain correct after pause, seek, replay, and rendering a single frame. Do not use wall-clock timers or non-reproducible random motion.\n- Keep playback controls and the visual clock separate: audio controls own transport; the visual samples the current time.\n\n## Suggested mapping\n\n`low`, `mid`, and `high` can drive separate scale, density, or line-weight layers. `onset` and `accent` are short impulses; `beatPhase` and `barPhase` provide repeatable breathing; `section` can change composition density or palette. These are starting points, not instrument labels. The data does not identify kick, snare, or 808. When `rhythm-map.json` carries `patterns.segments`, treat segment boundaries as scene-level changes, treat `family` and `variant` as recurrence rather than musical role, and never rename the neutral `A`/`B` families without instruction.\n\nThe original file name, duration, BPM, origin, beats, raw onsets, energy arrays, section annotations, and (when present) whole-song structure segments are recorded in `rhythm-map.json`.\n'''

_LEGACY_README = '''# BeatScope export\n\nFiles in this handoff:\n\n- `rhythm-map.json` — versioned timing data: duration, BPM, origin, bars/beats, raw onsets, accents, low/mid/high energy, and sections.\n- `visual-state.js` — pure `getVisualState(time)` function. It has no random state and is safe to call after seek.\n- `beatscope-runtime.js` — the shared runtime module `visual-state.js` builds on (`createTrack`).\n- `BEATSCOPE.md` — implementation handoff and timing invariants.\n- `SKILL.md` — portable Codex skill for building a visual from this package.\n- `references/schema.md` — exact field semantics for the skill.\n\nThe source audio is not copied into this package. Pair it with the original local file named `{display_name}`.\n'''


def generate_codex_export(
    rhythm_data: dict[str, Any],
    include_preview: bool = False,
    visual_artifacts: tuple[dict[str, Any], dict[str, Any]] | None = None,
) -> bytes:
    """Package a portable BeatScope handoff for Codex/other coding agents.

    The v0.8 visual artifacts (plan section 14.2) ride along: the recipe and
    timeline JSON stay directly readable, generated data modules exist for
    import-based examples, and ``scene-director.js`` is the same module the
    browser and the MCP worker run. When artifacts are not supplied they are
    compiled from the rhythm on the fly, which is deterministic, so the
    package stays byte-stable for identical input. Rhythms that cannot
    compile (for example minimal hand-built maps without a project id) fall
    back to the v0.7 legacy package, byte-identical to that release.
    """
    if visual_artifacts is None:
        try:
            visual_artifacts = compile_visual_artifacts(rhythm_data)
        except InvalidVisualRecipe:
            visual_artifacts = None
    rhythm_map = _codex_rhythm_map(rhythm_data)
    display_name = rhythm_map["source"]["display_name"]
    handoff = f'''# BeatScope handoff: {display_name}\n\nThis package is the inspected timing data for one audio file. It is intended to be handed to an agent making an audio-reactive web, video, or motion visual.\n\n## Rules\n\n- Do not re-analyse the audio. Use `rhythm-map.json` as the source of analysed timing facts.\n- Use `audio.currentTime` as the only clock. When the package carries visual artifacts, call `getBeatScopeFrame(audio.currentTime)` from `visual-state.js` — one call returning `{{ timing, scene }}` — and treat timing state and scene state as separate surfaces. Otherwise call `getVisualState(time)`.\n- Every animation must remain correct after pause, seek, replay, and rendering a single frame. Do not use wall-clock timers or non-reproducible random motion.\n- Keep playback controls and the visual clock separate: audio controls own transport; the visual samples the current time.\n- When `visual-recipe.json` is present, respect its tokens (palette, transition timing, motion limits) before inventing new ones, keep family identity stable across repetitions, and keep any extra motion seek-safe.\n\n## Suggested mapping\n\n`low`, `mid`, and `high` can drive separate scale, density, or line-weight layers. `onset` and `accent` are short impulses; `beatPhase` and `barPhase` provide repeatable breathing; `section` can change composition density or palette. These are starting points, not instrument labels. The data does not identify kick, snare, or 808. When `rhythm-map.json` carries `patterns.segments`, treat segment boundaries as scene-level changes, treat `family` and `variant` as recurrence rather than musical role, and never rename the neutral `A`/`B` families without instruction. When `visual-timeline.json` is present, `getSceneState(time).scene` reports the compiled scene (`family`, `variant`, `motif`, `phase`) and `.transition` reports the boundary envelope (`stage`, `approach`, `cross`, `settle`) — do not animate every property at every boundary.\n\nThe original file name, duration, BPM, origin, beats, raw onsets, energy arrays, section annotations, and (when present) whole-song structure segments are recorded in `rhythm-map.json`.\n'''
    readme = f'''# BeatScope export\n\nFiles in this handoff:\n\n- `rhythm-map.json` — versioned timing data: duration, BPM, origin, bars/beats, raw onsets, accents, low/mid/high energy, and sections.\n- `visual-state.js` — pure `getVisualState(time)` plus, when visual artifacts are present, `getSceneState(time)` and `getBeatScopeFrame(time)`. No random state; safe to call after seek.\n- `beatscope-runtime.js` — the shared runtime module `visual-state.js` builds on (`createTrack`).\n- `scene-director.js` — the shared scene orchestrator behind `getSceneState` (seek-safe, deterministic).\n- `visual-recipe.json` — compiled family identities: motif, palette slot, and composition channels per structural family.\n- `visual-timeline.json` — those identities instantiated on the real song: scenes and boundary transitions in seconds.\n- `visual-recipe-data.js` / `visual-timeline-data.js` — generated importable copies of the two JSON documents.\n- `BEATSCOPE.md` — implementation handoff and timing invariants.\n- `SKILL.md` — portable Codex skill for building a visual from this package.\n- `references/schema.md` — exact field semantics for the skill.\n\nThe source audio is not copied into this package. Pair it with the original local file named `{display_name}`.\n'''
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rhythm-map.json", json.dumps(rhythm_map, ensure_ascii=False, indent=2) + "\n")
        archive.writestr("beatscope-runtime.js", _runtime_source())
        if visual_artifacts is None:
            archive.writestr("visual-state.js", _visual_state_source(rhythm_map))
            archive.writestr("BEATSCOPE.md", _LEGACY_HANDOFF.format(display_name=display_name))
            archive.writestr("SKILL.md", _agent_skill_file("SKILL.md"))
            archive.writestr("references/schema.md", _agent_skill_file("references/schema.md"))
            archive.writestr("README.md", _LEGACY_README.format(display_name=display_name))
        else:
            recipe, timeline = visual_artifacts
            archive.writestr("scene-director.js", _scene_director_source())
            archive.writestr("visual-recipe.json", canonical_visual_bytes(recipe))
            archive.writestr("visual-timeline.json", canonical_visual_bytes(timeline))
            archive.writestr("visual-recipe-data.js", _visual_data_module("VISUAL_RECIPE", recipe))
            archive.writestr("visual-timeline-data.js", _visual_data_module("VISUAL_TIMELINE", timeline))
            archive.writestr("visual-state.js", _visual_state_source(rhythm_map, visual_artifacts))
            archive.writestr("BEATSCOPE.md", handoff)
            archive.writestr("SKILL.md", _agent_skill_file("SKILL.md"))
            archive.writestr("references/schema.md", _agent_skill_file("references/schema.md"))
            archive.writestr("README.md", readme)
    return output.getvalue()
