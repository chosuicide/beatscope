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
from .consumer_contract import (
    ENTRY_MEMBER,
    MANIFEST_MEMBER,
    MANIFEST_SCHEMA,
    PROBE_MEMBER,
    canonical_manifest_bytes,
    sha256_hex,
    validate_manifest,
)
from .midi import TPQ, _meta_track, _meta_track_tempo_map, _tempo_map_tick, _track
from .event_evidence import InvalidEventEvidenceSource
from .response_relevance import (
    ResponseRelevanceError,
    build_response_relevance,
    canonical_response_relevance_bytes,
)
from .visual_recipe import canonical_visual_bytes

# The handoff package format version (plan section 4.3). This tracks the
# package contract only: the audio analyser stays at schema.ANALYZER_VERSION
# (0.7.0) and the visual recipe contract at 0.8.0.
PACKAGE_VERSION = "0.12.0"


def _agent_skill_file(relative_path: str) -> str:
    """Read a bundled Codex skill resource from the installed package."""
    path = Path(__file__).with_name("agent_skill") / relative_path
    return path.read_text(encoding="utf-8")


def _probe_source() -> str:
    """Return the consumer self-verification probe shipped with every export."""
    probe_path = Path(__file__).with_name("runtime") / "consumer-probe.js"
    return probe_path.read_text(encoding="utf-8")




def _package_manifest(
    rhythm_map: dict[str, Any],
    response_relevance: dict[str, Any] | None,
    member_bytes: dict[str, bytes],
    display_name: str,
) -> bytes:
    """Build the self-describing routing document (plan section 4.2).

    Capabilities describe what the package actually carries, never
    aspirations. The manifest is assembled last so its integrity section
    covers every other member, and it is validated with the exact rules
    consumers apply before anything ships.
    """
    duration = float(rhythm_map["duration"])
    has_scenes = False
    has_structure = bool((rhythm_map.get("patterns") or {}).get("segments"))
    functions: dict[str, str] = {"timing": "getVisualState"}
    files: dict[str, str] = {"rhythm": "rhythm-map.json"}
    if has_scenes:
        functions["frame"] = "getBeatScopeFrame"
        functions["scene"] = "getSceneState"
        files["recipe"] = "visual-recipe.json"
        files["timeline"] = "visual-timeline.json"
    if response_relevance is not None:
        functions["response_events"] = "getResponseEvents"
        files["response_relevance"] = "response-relevance.json"
    project_id = rhythm_map.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        # Hand-built minimal maps carry no project id; derive a stable
        # content address so the manifest never ships an empty field.
        project_id = sha256_hex(member_bytes["rhythm-map.json"])[:12]
    tempo = rhythm_map.get("tempo") or {}
    bpm = tempo.get("global_bpm") or tempo.get("bpm")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "package_version": PACKAGE_VERSION,
        "project_id": project_id,
        "display_name": display_name,
        "summary": {
            "bpm": round(float(bpm), 3) if isinstance(bpm, (int, float)) else None,
            "bars": int(rhythm_map.get("bars_count") or len(rhythm_map.get("bars") or []) or 0),
            "beats": len(rhythm_map.get("beats") or []),
            "onsets": len(rhythm_map.get("onsets") or []),
            "segments": len(((rhythm_map.get("patterns") or {}).get("segments")) or []),
        },
        "duration": duration,
        "entry": ENTRY_MEMBER,
        "probe": PROBE_MEMBER,
        "clock": {
            "unit": "seconds",
            "minimum": 0.0,
            "maximum": duration,
            "semantics": "media-time",
        },
        "capabilities": {
            "timing": True,
            "bands": True,
            "structure": has_structure,
            "scenes": has_scenes,
            "module_worker": True,
            "response_relevance": response_relevance is not None,
        },
        "functions": functions,
        "files": files,
        "integrity": {
            "algorithm": "sha256",
            "members": {
                name: sha256_hex(data)
                for name, data in sorted(member_bytes.items())
                if name != MANIFEST_MEMBER
            },
        },
    }
    errors = validate_manifest(manifest, member_bytes)
    if errors:
        raise ValueError(f"generated package manifest is invalid: {errors}")
    return canonical_manifest_bytes(manifest)


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
    response_relevance: dict[str, Any] | None = None,
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
    response_import = (
        "import { RESPONSE_RELEVANCE } from './response-relevance-data.js';\n"
        if response_relevance is not None else ""
    )
    response_option = ", { responseRelevance: RESPONSE_RELEVANCE }" if response_relevance is not None else ""
    response_export = '''

export function getResponseEvents(start, end, budget) {
  return track.responseBetween(start, end, budget);
}
''' if response_relevance is not None else ""
    if visual_artifacts is None:
        head = "// BeatScope visual state contract — deterministic and seek-safe.\n"
        head += "import { createTrack } from './beatscope-runtime.js';\n"
        head += response_import + "\n"
        head += "export const RHYTHM_MAP = "
        tail = ''';

const track = createTrack(RHYTHM_MAP%s);

export function getVisualState(time) {
  return track.at(time);
}
%s''' % (response_option, response_export)
        return head + data + tail
    head = (
        "// BeatScope visual state contract — deterministic and seek-safe.\n"
        "// Timing state and scene state are separate surfaces: getVisualState\n"
        "// reports rhythm facts, getSceneState reports the structural scene,\n"
        "// and getBeatScopeFrame returns both from one call.\n"
        "import { createTrack } from './beatscope-runtime.js';\n"
        "import { createSceneDirector } from './scene-director.js';\n"
        "import { VISUAL_RECIPE } from './visual-recipe-data.js';\n"
        "import { VISUAL_TIMELINE } from './visual-timeline-data.js';\n"
        + response_import + "\n"
        "export const RHYTHM_MAP = "
    )
    tail = ''';

const track = createTrack(RHYTHM_MAP%s);
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
%s''' % (response_option, response_export)
    return head + data + tail


def _worker_example_source() -> str:
    """A module-worker adapter for the pure exported timing API."""
    return '''// BeatScope module Worker example — transport stays on the main thread.
import { getVisualState } from './visual-state.js';

self.onmessage = ({ data = {} }) => {
  const time = Number(data.time);
  if (!Number.isFinite(time) || time < 0) {
    self.postMessage({ id: data.id ?? null, error: 'time must be a finite number >= 0' });
    return;
  }
  self.postMessage({ id: data.id ?? null, time, timing: getVisualState(time) });
};
'''


def _license_bytes() -> bytes | None:
    """The repository license, shipped so consumers know the terms.

    Absent in an installed wheel that does not carry the repository file; the
    package then omits it and README.md still names the license.
    """
    candidate = Path(__file__).resolve().parents[1] / "LICENSE"
    return candidate.read_bytes() if candidate.is_file() else None


def _handoff_document(display_name: str) -> str:
    """BEATSCOPE.md: the timing invariants a consumer must not break."""
    return f"""# BeatScope timing handoff: {display_name}

This package records what BeatScope measured in one audio file, plus an optional
ordering value for spending a limited response budget. It carries no visual
language and no task: what the visual is, is your decision.

## Clock contract

- Time is seconds of media time, from 0 to the duration in `beatscope-package.json`.
- Interactive playback samples `audio.currentTime` once per frame; offline
  rendering derives seconds from the frame number and the composition FPS. Never
  accumulate time across frames.
- Every query is pure: pause, seek, replay, and rendering a single frame resolve
  the same instant to the same facts. Keep your own animation state seek-safe the
  same way — no wall-clock timers, no unseeded random motion.

## What the facts mean

- `beatPhase` and `barPhase` interpolate between the two measured beats around
  the query, so variable tempo stays honest instead of drifting off a global BPM.
- `low`, `mid`, and `high` are measured band energy: frequency evidence, not
  instrument labels. The data never identifies a kick or a snare.
- `onset` and `accent` are transients with a strength and an age.
- Structure segments carry a neutral family letter (`A`, `B`, ...) that marks
  recurrence, not a musical role. Never rename them to Verse or Chorus unless the
  user says so.
- `getResponseEvents(start, end, budget)` returns existing onsets at their stored
  times, chosen by a bounded ordering value learned from human-authored rhythm
  charts. It is not a probability, a confidence score, or an instruction to
  animate every selected event. When ranking is unavailable it reports
  `chronological-fallback`, and that fact belongs in your diagnostics.

## Invariants

- Never re-analyse the audio, and never scan arrays every frame for facts the
  frame already carries.
- The audio element owns transport; the visual only samples the current time.
- Honour reduced-motion preferences.
"""


def _readme_document(display_name: str, has_relevance: bool) -> str:
    """README.md: the inventory, what is missing, and what is authoritative."""
    relevance = (
        "- `response-relevance.json` (+ `response-relevance-data.js`) — ordering-only sidecar "
        "for spending a consumer-chosen onset budget; it carries event ids rather than event "
        "times, and the values are not probability or confidence.\n"
        if has_relevance
        else ""
    )
    return f"""# BeatScope timing package — {display_name}

The measured timing facts for one audio file, packaged for a coding agent or a
visual tool. Read `AGENT.md` next: it is the contract. `BEATSCOPE.md` holds the
timing invariants.

## Files

- `rhythm-map.json` — the authoritative timing data: duration, tempo and origin,
  bars and beats, raw onsets with strength and band energy, accents, sampled
  energy, and structure segments.
- `rhythm.mid` — the same facts for a DAW: a tempo map plus one note per onset,
  velocity from strength.
- `rhythm.csv` — the same facts as a table: raw and quantised time, offset in
  milliseconds, bar/beat/step, strength, band energy, and the accent flag.
{relevance}- `beatscope-package.json` — the routing manifest: entry module, probe, honest
  capabilities, exported function names, a short summary, and the sha256 of every
  member.
- `visual-state.js` — dependency-free accessor: `getVisualState(time)`, plus
  `getResponseEvents(start, end, budget)` when the manifest declares it.
- `beatscope-runtime.js` — the shared runtime `visual-state.js` builds on.
- `worker-example.js` — a module Worker adapter: the main thread sends audio time,
  the worker returns the frame facts.
- `consumer-probe.js` — self-check: `node consumer-probe.js .`.
- `BEATSCOPE.md` — timing invariants.
- `SKILL.md`, `references/schema.md` — how to consume the package, and the exact
  field semantics.
- `LICENSE` — terms for the shipped code.

## Not in this package

No audio: pair the package with the original local file named
`{display_name}`. No assets, no fonts, no palette, no style, no scene timeline,
no rendered video, and no statement about aspect ratio, frame rate or pacing.
Those are decisions for you and the user to make together. The package also never
contains machine paths or cache locations.

## Authority

`rhythm-map.json` is the authoritative data. `visual-state.js` embeds the same map
only so that `import` works without a build step or a fetch layer; when the two
ever disagree, the JSON wins.
"""


def _agent_document(display_name: str, duration: float, rhythm_map: dict[str, Any]) -> str:
    """Build the short Agent routing document (plan section 5).

    Deterministic and display-name-scoped only: no wall clock, no machine paths,
    no audio facts beyond what the manifest already carries. Kept under roughly
    900 words; detailed field semantics live in ``references/schema.md``.
    """
    beats = len(rhythm_map.get("beats") or [])
    onsets = len(rhythm_map.get("onsets") or [])
    segments = len(((rhythm_map.get("patterns") or {}).get("segments")) or [])
    bars = int(rhythm_map.get("bars_count") or len(rhythm_map.get("bars") or []) or 0)
    return f"""# BeatScope timing handoff: {display_name}

You are reading the measured timing facts for one audio file: {duration:.3f} s,
{bars} bars, {beats} beats, {onsets} transients, {segments} structural segments.
This package describes the music. It carries no visual style, no scene, no
assets, and no task, because the visual is a decision you make with the user.

## Start here

1. Read `beatscope-package.json` first. It is the routing document: entry module,
   exported functions, the honest capability set, a short summary of the track,
   and the sha256 of every member.
2. Verify before you build: run `node consumer-probe.js .` from the package root.
   It imports the entry module, checks every declared function, and reports
   whether the package agrees with itself on this machine.
3. Query facts, never audio: `getVisualState(time)` for the frame, and
   `getResponseEvents(start, end, budget)` when the manifest enables
   `response_relevance`.

## Clock contract

- Time is seconds of media time, from `clock.minimum` to `clock.maximum`.
- Interactive playback: sample `audio.currentTime` once per animation frame and
  pass it in. Offline rendering: derive seconds from the frame number and the
  composition FPS. Never accumulate time across frames.
- Every query is pure: pause, seek, replay, re-render one frame, or query in any
  order. The answer for a given time never changes. Keep your own animation state
  seek-safe the same way.

## What you can trust

- `beatPhase` and `barPhase` interpolate between the two measured beats around the
  query, so variable tempo stays honest.
- `low`, `mid`, `high` are measured band energy: frequency evidence, not
  instrument labels. The data never identifies a kick, snare, or 808.
- Structure families (`A`, `B`, ...) mark recurrence, never musical roles, and
  `variant` means a related passage rather than a new identity.
- `response_relevance` is an ordering value learned from human-authored rhythm
  charts. Spend it through `getResponseEvents(start, end, budget)`: the returned
  objects are existing onsets at their stored times, and the value is not a
  probability or a command to animate everything it ranks. When ranking is
  unavailable the call reports `chronological-fallback`; keep that fact in your
  diagnostics instead of presenting the fallback as ranked output.

## Ground rules

- Never re-analyse the audio, and never scan arrays every frame to re-derive facts
  the frame already carries.
- The audio element owns transport; the visual only samples the current time.
- Keep animation deterministic: no wall-clock timers, no unseeded random motion,
  nothing that breaks single-frame rendering.
- Respect reduced-motion preferences: drop continuous agitation, keep the
  composition honest.
- Do not infer instruments, emotion, or semantic section names.

## Settle these with the user before writing visual code

- What are we making: a new visual, a variation of something they have seen, a
  tool, or an edit of existing footage?
- Do they have material (footage, images, logo, palette, fonts), or should it be
  generated?
- Format: aspect ratio, frame rate, resolution, whole song or a segment?
- How dense should the responses be? Run `getResponseEvents` for two or three
  budgets and show the event counts, then let the user choose instead of guessing
  a threshold.
- Delivery: an interactive page, a rendered file, or both?

## Self-check before you finish

    node consumer-probe.js .

Timing parity must be exact: the same time must resolve to the same facts.

## Package honesty

`beatscope-package.json` describes what exists, not aspirations. Trust it over any
other description: if it does not declare a function or a file, do not use it.
`README.md` lists what is deliberately absent, `SKILL.md` and
`references/schema.md` cover consumption and exact field semantics, and
`BEATSCOPE.md` holds the timing invariants.
"""


def generate_codex_export(
    rhythm_data: dict[str, Any],
    include_response_relevance: bool = True,
) -> bytes:
    """Package the measured timing facts for one audio file.

    The package is deliberately facts-only: beats, transients, band energy,
    structure, an ordering value for spending a limited response budget, and the
    sidecars that carry the same facts into a DAW or a spreadsheet. It ships no
    visual language — no recipe, no scene timeline, no palette — and it states
    no task, because the visual is the consumer's decision and a package that
    pre-decides it stops the consumer from asking the user what they want.

    Everything is canonical bytes assembled in a fixed order, so the same rhythm
    always produces the same package.
    """
    response_relevance = None
    if include_response_relevance:
        try:
            response_relevance = build_response_relevance(rhythm_data)
        except (InvalidEventEvidenceSource, ResponseRelevanceError, KeyError, TypeError, ValueError):
            response_relevance = None
    rhythm_map = _codex_rhythm_map(rhythm_data)
    display_name = rhythm_map["source"]["display_name"]
    output = io.BytesIO()
    # Members are assembled first so the manifest can hash every other member,
    # then written in the fixed layout order (plan section 4.1).
    members: dict[str, bytes] = {
        "rhythm-map.json": (json.dumps(rhythm_map, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "rhythm.mid": generate_rhythm_midi(rhythm_data),
        "rhythm.csv": generate_rhythm_csv(rhythm_data).encode("utf-8"),
        "visual-state.js": _visual_state_source(
            rhythm_map, response_relevance=response_relevance
        ).encode("utf-8"),
        "beatscope-runtime.js": _runtime_source().encode("utf-8"),
        "worker-example.js": _worker_example_source().encode("utf-8"),
        "BEATSCOPE.md": _handoff_document(display_name).encode("utf-8"),
        "README.md": _readme_document(display_name, response_relevance is not None).encode("utf-8"),
    }
    if response_relevance is not None:
        members["response-relevance.json"] = canonical_response_relevance_bytes(response_relevance)
        members["response-relevance-data.js"] = _visual_data_module(
            "RESPONSE_RELEVANCE", response_relevance
        ).encode("utf-8")
    members["SKILL.md"] = _agent_skill_file("SKILL.md").encode("utf-8")
    members["references/schema.md"] = _agent_skill_file("references/schema.md").encode("utf-8")
    members["consumer-probe.js"] = _probe_source().encode("utf-8")
    members["AGENT.md"] = _agent_document(
        display_name, float(rhythm_map["duration"]), rhythm_map
    ).encode("utf-8")
    license_bytes = _license_bytes()
    if license_bytes is not None:
        members["LICENSE"] = license_bytes
    members[MANIFEST_MEMBER] = _package_manifest(
        rhythm_map, response_relevance, members, display_name
    )

    order = [
        MANIFEST_MEMBER,
        "README.md",
        "AGENT.md",
        "rhythm-map.json",
        "rhythm.mid",
        "rhythm.csv",
        "response-relevance.json",
        "response-relevance-data.js",
        "visual-state.js",
        "beatscope-runtime.js",
        "worker-example.js",
        "consumer-probe.js",
        "BEATSCOPE.md",
        "SKILL.md",
        "references/schema.md",
        "LICENSE",
    ]
    missing_from_order = sorted(set(members) - set(order))
    if missing_from_order:
        raise ValueError(f"package members missing from the layout order: {missing_from_order}")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in order:
            if name in members:
                # Fixed entry metadata: zipfile would otherwise stamp the current
                # time into every entry, which would make the package bytes
                # depend on when it was built instead of only on the rhythm.
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, members[name])
    return output.getvalue()
