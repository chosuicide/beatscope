"""Export utilities for Rhythm Reference MIDI, CSV, and visual snapshots."""
from __future__ import annotations

import csv
import io
import json
import math
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
from .edit_plan import default_edit_plan, edit_plan_bytes, validate_edit_plan
from .event_evidence import InvalidEventEvidenceSource
from .midi import TPQ, _meta_track, _meta_track_tempo_map, _tempo_map_tick, _track
from .response_relevance import (
    ResponseRelevanceError,
    build_response_relevance,
    canonical_response_relevance_bytes,
)
from .timing_quality import timing_quality

# The handoff package format version (plan section 4.3). This tracks the
# package contract only: the audio analyser stays at schema.ANALYZER_VERSION
# (0.7.0) and the visual recipe contract at 0.8.0.
PACKAGE_VERSION = "0.19.2"


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
    has_structure = bool((rhythm_map.get("patterns") or {}).get("segments"))
    functions: dict[str, str] = {"timing": "getVisualState"}
    files: dict[str, str] = {"rhythm": "rhythm-map.json", "edit_plan": "edit-plan.json"}
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
    plan = json.loads(member_bytes["edit-plan.json"])
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
            "stage_count": len(plan["boundaries"]) + 1,
            "cue_edits": {
                "added": sum(c["id"].startswith("u:") for c in plan["cues"]),
                "moved": sum(c["id"].startswith("o:") and not c.get("deleted") for c in plan["cues"]),
                "deleted": sum(c.get("deleted") is True for c in plan["cues"]),
            },
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
            # The product ships measured timing facts and no visual layer, so
            # this is a constant, not a per-package property.
            "scenes": False,
            "module_worker": True,
            "response_relevance": response_relevance is not None,
            "choreography": True,
            "edit_score": True,
            "edit_plan": True,
            **({"segment_levels": True} if any(
                isinstance(segment.get("mean_rms"), (int, float))
                and not isinstance(segment.get("mean_rms"), bool)
                and math.isfinite(segment["mean_rms"]) and segment["mean_rms"] >= 0
                for segment in ((rhythm_map.get("patterns") or {}).get("segments") or [])
            ) else {}),
        },
        "functions": functions,
        "files": files,
        "authoring": {
            "module": "choreography.js",
            "factory": "createChoreography",
            "brief": "music-brief.mjs",
            "editor": "edit-score.js",
            "editor_factory": "createEditScore",
            "plan_module": "edit-plan.js",
        },
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
            {"time": o.get("time", o.get("raw_time")), "onset": o.get("id")}
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
    diagnostics = (rhythm_data.get("analysis") or {}).get("diagnostics") or {}
    safe_diagnostics: dict[str, Any] = {}
    if isinstance(diagnostics, dict):
        for key in ("energy_semantics", "meter_source", "tempo_source", "tempo_segments_source"):
            value = diagnostics.get(key)
            if isinstance(value, str) and len(value) <= 80:
                safe_diagnostics[key] = value
        value = diagnostics.get("structure_unavailable")
        if isinstance(value, bool) or (isinstance(value, str) and len(value) <= 80):
            safe_diagnostics["structure_unavailable"] = value
    safe_diagnostics["timing_quality"] = timing_quality(rhythm_data)
    revision = diagnostics.get("timing_revision") if isinstance(diagnostics, dict) else None
    if isinstance(revision, dict) and revision.get("status") == "unverified":
        safe_diagnostics["timing_revision"] = {
            "status": "unverified",
            "method": "constant-grid-hypothesis",
        }
        parent_digest = revision.get("parent_beats_sha256")
        if isinstance(parent_digest, str) and len(parent_digest) == 64 and all(c in "0123456789abcdef" for c in parent_digest):
            safe_diagnostics["timing_revision"]["parent_beats_sha256"] = parent_digest
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
            **({"diagnostics": safe_diagnostics} if safe_diagnostics else {}),
        },
    }


def _runtime_source() -> str:
    """Return the shared rhythm runtime module shipped with every export."""
    runtime_path = Path(__file__).with_name("runtime") / "runtime.js"
    return runtime_path.read_text(encoding="utf-8")


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical UTF-8/LF JSON bytes with 6-decimal float precision.

    Every generated member goes through this serializer, so a package's bytes
    depend only on its facts - not on the platform's float repr or dict order.
    """
    def round6(node: Any) -> Any:
        if isinstance(node, float):
            return round(node, 6) + 0.0  # never -0.0
        if isinstance(node, dict):
            return {key: round6(item) for key, item in node.items()}
        if isinstance(node, list):
            return [round6(item) for item in node]
        return node

    # Sort object keys as well as normalising numbers. The paired JSON member
    # is loaded again by validate-handoff before executable templates are
    # reconstructed; a module generated from insertion order would therefore
    # have different (but semantically equivalent) bytes and fail the trust
    # boundary for real user exports.
    canonical = json.dumps(
        round6(value), indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False
    )
    return (canonical + "\n").encode("utf-8")


def _visual_data_module(constant: str, document: dict[str, Any]) -> str:
    """Generated data module so examples avoid network/file loading (plan 14.2).

    The JSON documents stay directly readable in the package; these modules
    exist only so `import` works without a build system or fetch layer.
    """
    body = canonical_json_bytes(document).decode("utf-8")
    return (
        "// Generated by BeatScope: deterministic data module (do not hand-edit).\n"
        f"export const {constant} = {body}"
    )


def _visual_state_source(
    rhythm_map: dict[str, Any],
    response_relevance: dict[str, Any] | None = None,
    *,
    embedded: bool = False,
) -> str:
    """Build the visual-state.js module: measured facts plus the runtime.

    getVisualState is exactly ``track.at(time)`` - the same time-query the
    web player samples and the MCP bridge serves - so every carrier shares one
    implementation and one output shape (plan section 43). The module names the
    state a visualizer samples; it carries no scene, transition, or recipe
    data, because the handoff states no visual language.
    """
    response_import = (
        ("import { RESPONSE_RELEVANCE } from './response-relevance-data.js';\n" if embedded
         else "import RESPONSE_RELEVANCE from './response-relevance.json' with { type: 'json' };\n")
        if response_relevance is not None else ""
    )
    response_option = ", { responseRelevance: RESPONSE_RELEVANCE }" if response_relevance is not None else ""
    response_export = '''

export function getResponseEvents(start, end, budget) {
  return track.responseBetween(start, end, budget);
}
''' if response_relevance is not None else ""
    head = "// BeatScope visual state contract — deterministic and seek-safe.\n"
    head += "import { createTrack } from './beatscope-runtime.js';\n"
    head += response_import + "\n"
    if embedded:
        data = json.dumps(rhythm_map, ensure_ascii=False, separators=(",", ":"))
        head += "export const RHYTHM_MAP = " + data + ";"
    else:
        head += "import RHYTHM_MAP from './rhythm-map.json' with { type: 'json' };\n"
        head += "export { RHYTHM_MAP };"
    tail = '''

const track = createTrack(RHYTHM_MAP%s);

export function getVisualState(time) {
  return track.at(time);
}
%s''' % (response_option, response_export)
    return head + tail


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
    """BEATSCOPE.md: the timing invariants. This file owns them."""
    return f"""# BeatScope timing invariants: {display_name}

The rules a consumer must not break, and what the reported fields actually
mean. The collaboration flow lives in `AGENT.md`; API details live in
`SKILL.md` and `references/schema.md`.

## Clock contract

- Time is seconds of media time, from 0 to the duration in
  `beatscope-package.json`.
- Interactive playback samples `audio.currentTime` once per frame; offline
  rendering derives seconds from the frame number and the composition FPS.
  Never accumulate time across frames.
- Every query is pure: pause, seek, replay and single-frame rendering resolve
  the same instant to the same facts. Keep your own animation state seek-safe
  the same way - no wall-clock timers, no unseeded random motion.

## What the fields mean

- `beat`, `bar`, `beatPhase`, `barPhase`: position in the measured grid. The
  phases interpolate between the two real beats around the query, so variable
  tempo stays honest instead of drifting off a global BPM.
- `low`, `mid`, `high`, `all`: normalized multiband spectral novelty (activity),
  not calibrated loudness or power. The analysis diagnostics name the source
  semantics when available. These bands never identify a kick, snare or 808.
- `onset`, `accent`: transients with a `value` and an `age` in seconds.
- `state.structure`: the current segment (`id`, `family`, `variant`, `label`,
  `index`), its `phase`, `nextBoundaryTime` and `secondsToBoundary`. Family
  letters mark recurrence, not musical role: `A'` is related to `A`, never
  "Chorus". Never rename them unless the user asks.
- Optional `state.structure.meanRms` is the segment's waveform RMS amplitude,
  not instantaneous level or perceived loudness. Legacy `mean_energy` is novelty.
- `response_relevance`: an ordering value learned from human-authored rhythm
  charts, used to spend a limited response budget. It is not a probability, a
  confidence score or an instruction to animate everything it ranks.

## Times: measured versus quantised

- Current Rhythm IR v4 onsets carry the measured instant as `time`; older maps
  may call it `raw_time`. That instant is what a cut, marker or edit may use.
- Separate `rhythm.mid` export is quantised to the subdivision; `rhythm.csv` also
  carries `quantized_time` with `offset_ms`: both are annotations. Snapping a
  cut to a grid the user did not ask for is a defect, not a simplification.

## Invariants

- Never re-analyse the audio, and never scan arrays every frame for facts the
  frame already carries.
- The audio element owns transport; the visual only samples the current time.
- Honour `prefers-reduced-motion`: the facts never change, but your motion must
  drop continuous agitation.
"""


def _readme_document(display_name: str, has_relevance: bool) -> str:
    """Inventory without duplicated workflow or factual carriers."""
    relevance = "- `response-relevance.json`: optional onset-ordering values.\n" if has_relevance else ""
    return f"""# BeatScope timing package: {display_name}

Read `AGENT.md` first. Query data; do not load the map in full into context.

## Files

- `beatscope-package.json`: capabilities, functions, inventory and member hashes;
  summary `stage_count` is the resolved stage total, not a count of user edits.
- `rhythm-map.json`: authoritative measured facts, stored once without rounding.
{relevance}- `visual-state.js`: synchronous timing accessors using the JSON documents.
- `beatscope-runtime.js`: shared query implementation.
- `choreography.js`: renderer-neutral, seek-safe authored tracks and shared moments.
- `edit-score.js`: grouped cuts, reusable shots and deterministic revisit clocks.
- `edit-plan.json`, `edit-plan.js`: stage boundaries and compact cue overrides;
  resolve with `resolveEditPlan(rhythm, plan)` before authoring the score.
- `picture-tools.js`: optional target framing and native picture bindings; no style.
- `music-brief.mjs`: one bounded music summary query, no dependencies.
- `consumer-probe.js`, `worker-example.js`: contract check and module-worker adapter.
- `SKILL.md`: API examples; `BEATSCOPE.md`: timing invariants.
- `references/schema.md`: fields; `references/directing.md`: video workflow.
- `references/picture-tools.md`: optional framing/binding API; read only if needed.
- `LICENSE`: shipped code terms.

## Not in this package

No audio, assets, style, visual scene plan, rendered video or machine paths. Pair this
with `{display_name}` and the user's task. References and assets are optional;
follow AGENT.md for direction and source authorization. CSV and MIDI remain separate
BeatScope exports. Job-specific sources, decisions and evidence stay in the job.

## Authority

`rhythm-map.json` is the measured factual source; `edit-plan.json` is authored
passage/response timing. The entry imports facts with JSON
import attributes; use Node 22+ or a current Chromium browser/module worker.
In a browser, serve the package over HTTP with JSON MIME `application/json` and
JavaScript MIME `text/javascript`; opening a file URL is insufficient. No build
step or extra runtime dependency is required. Accessors remain synchronous after
module loading. Use the manifest instead of guessing capabilities.
"""


def _agent_document(display_name: str, duration: float, rhythm_map: dict[str, Any]) -> str:
    """Short entry; API, timing and directing each have one owner."""
    quality = rhythm_map.get("analysis", {}).get("diagnostics", {}).get("timing_quality", {})
    timing_label = "Unverified timing candidate" if quality.get("timing_revision_status") == "unverified" else "Measured music timing"
    return f"""# BeatScope handoff: {display_name}

{timing_label}, {duration:.3f} seconds. This package supplies music facts and
generic choreography, not a visual concept or fixed style. A line chart is not
the default picture.

## Continue or start
Identify the matching song/project by source hash, score duration and revision
binding. Material paths prove neither identity nor authorization. Reuse assets/code
separately from another song's timing.
Resume a matching project within scope; otherwise create without inventing history.
Read summaries/selected fields, not entire maps, embedded
rhythm/ranking caches or recursive asset listings.
Assets and references are optional. Reuse explicit direction/authorization;
without references design independently. Without assets choose procedural visuals or
online sources within authorization. If direction and source authorization are
both unclear, ask once together; otherwise ask only for blocking inputs.
Do not require references, technical parameters or engineering versions.
Run `node consumer-probe.js .` for changed packages; reuse results for identical
bytes. Cache `node music-brief.mjs` by rhythm/edit-plan hashes;
Query uncertain windows only; do not decode/reanalyse music unless explicitly requested.
Read `beatscope-package.json`, `SKILL.md` and `BEATSCOPE.md`.
Consult `references/schema.md` for uncertain fields; runtime success does not prove timing.

## Compose
For video read `references/directing.md`. Inspect supplied reference passages once;
cache observations. Reuse a matching job-local
`score.json`, or create one. For an MV use `intent:"music-video"`: passage rhythm,
related shots, then motion. Compile with `createEditScore`; apply setup and values.
Keep measured `time` (legacy `raw_time`). Resolve `edit-plan.json` with `edit-plan.js` first:
use its boundaries and deleted/moved/added cues; preserve source times.
Stages require entry or explicit carry; cues can coordinate layers/sequences.
Default boundaries are suggestions; overrides are authored timing.
The saved plan outranks stale preview timing and automatic sections.
Preserve authored edits outside the requested scope.

Reuse renderer, camera and asset bindings. Optional `picture-tools.js`:
read `references/picture-tools.md` for needed helpers only. Helpers require no
extra analysis, reports or preview passes.

## Check within scope
Run `node music-brief.mjs --score ../score.json --mv` after score changes.
For a new piece use one representative preview at 24–30fps covering beats,
an accent and a handoff; revisions check affected windows/seams only.
Compare paired moving passages with audio when references exist; otherwise check
the declared direction. Reuse unaffected evidence. Repeated failure needs an
approach change or honest limitation. Follow user rendering limits.

## Deliver
Provide media, source, rerender command, credits and remaining differences.
Separate package verified, self-reviewed and user accepted. Keep job score,
assets and evidence outside this ZIP. `README.md` lists files.
"""


def generate_codex_export(
    rhythm_data: dict[str, Any],
    include_response_relevance: bool = True,
    edit_plan: dict[str, Any] | None = None,
) -> bytes:
    """Package the measured timing facts for one audio file.

    The package carries beats, transients, spectral novelty, structure and an
    optional ordering sidecar once each. CSV/MIDI remain separate exports.
    Generic directing guidance prescribes no visual style, scene or palette.

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
    plan = validate_edit_plan(edit_plan if edit_plan is not None else default_edit_plan(rhythm_map), rhythm_map)
    display_name = rhythm_map["source"]["display_name"]
    output = io.BytesIO()
    # Members are assembled first so the manifest can hash every other member,
    # then written in the fixed layout order (plan section 4.1).
    members: dict[str, bytes] = {
        "rhythm-map.json": (json.dumps(rhythm_map, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"),
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
    members["choreography.js"] = (Path(__file__).with_name("runtime") / "choreography.js").read_text(encoding="utf-8").encode("utf-8")
    members["edit-score.js"] = (Path(__file__).with_name("runtime") / "edit-score.js").read_text(encoding="utf-8").encode("utf-8")
    members["edit-plan.json"] = edit_plan_bytes(plan)
    members["edit-plan.js"] = (Path(__file__).with_name("runtime") / "edit-plan.js").read_bytes()
    members["picture-tools.js"] = (Path(__file__).with_name("runtime") / "picture-tools.js").read_text(encoding="utf-8").encode("utf-8")
    members["music-brief.mjs"] = _agent_skill_file("music-brief.mjs").encode("utf-8")
    members["SKILL.md"] = _agent_skill_file("SKILL.md").encode("utf-8")
    members["references/schema.md"] = _agent_skill_file("references/schema.md").encode("utf-8")
    members["references/directing.md"] = _agent_skill_file("references/directing.md").encode("utf-8")
    members["references/picture-tools.md"] = _agent_skill_file("references/picture-tools.md").encode("utf-8")
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
        "response-relevance.json",
        "visual-state.js",
        "beatscope-runtime.js",
        "choreography.js",
        "edit-score.js",
        "edit-plan.json",
        "edit-plan.js",
        "picture-tools.js",
        "music-brief.mjs",
        "worker-example.js",
        "consumer-probe.js",
        "BEATSCOPE.md",
        "SKILL.md",
        "references/schema.md",
        "references/directing.md",
        "references/picture-tools.md",
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
