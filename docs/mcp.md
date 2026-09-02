# BeatScope MCP server: complete contract

`beatscope_mcp` exposes BeatScope's rhythm facts to coding agents over the
Model Context Protocol. An agent can analyze a local song, inspect beats,
onsets, energy, and cues in precise time windows, and export a portable
handoff package - without reading BeatScope source code and without
re-deriving timing semantics.

This document is the full contract. The README only covers getting started.

## Semantics statement

BeatScope reports **timing facts**: beats, transients (onsets), frequency-band
energy, sections, and pattern groups. It does **not** identify instruments.
Onset data must never be labeled kick, snare, hi hat, or 808 - the analysis
cannot know that, and the server's instructions say so explicitly.

## Install and launch

~~~powershell
pip install -e ".[mcp]"
beatscope-mcp
~~~

The server speaks **stdio**: requests on stdin, responses on stdout, one
JSON-RPC message per line. stdout never carries anything but protocol
output; diagnostics go to stderr with a `beatscope-mcp:` prefix.

Requires Python 3.10+ (`mcp>=2,<3`) and Node.js 20+ for the runtime-backed
tools (`beatscope_get_visual_state`, `beatscope_get_events`). If Node is
missing, read-only project tools still work and runtime queries fail with an
actionable error.

## Configuration

All settings come from environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BEATSCOPE_ALLOWED_ROOTS` | current working directory | `os.pathsep`-separated directories the server may read or write. Everything else is rejected before any I/O. |
| `BEATSCOPE_CACHE_ROOT` | `.beatscope-cache` | Where analyzed projects are stored. |
| `BEATSCOPE_MCP_NODE` | `node` | Node binary used by the runtime worker. Point it at an absolute path if `node` is not on `PATH`. |
| `BEATSCOPE_MCP_MAX_RESPONSE_CHARS` | `25000` | Response budget; larger payloads are truncated with a resource pointer (see below). |
| `BEATSCOPE_MCP_LOG_LEVEL` | `WARNING` | stderr log level. |

### Security model

- Input paths are resolved strictly (`Path.resolve(strict=True)`), must be
  regular files, and must sit inside an allowed root (containment check on
  resolved paths, so symlink escapes are rejected).
- Audio inputs accept `.wav .flac .mp3 .ogg .m4a`; beat files `.beats`;
  export destinations must end in `.zip`.
- Nothing is sent over the network: the stdio server never uploads audio,
  and analysis is local DSP.
- The server exposes no generic file-read or command-execution tool.

## Cache and project identity

A project id is the first 12 hex chars of the audio file's SHA-256. The
cache key adds the schema version, analyzer version, and the full analysis
config, so **the same audio can hold several configurations at once**
(subdivision 16 and 32 coexist under one project id as variants). A cache
hit promotes the requested variant to the project root; `force=true` on
`beatscope_analyze_audio` bypasses the cache entirely.

## Tools

Six tools, all prefixed `beatscope_`. All except `beatscope_analyze_audio`
and `beatscope_export_package` are read-only. All are idempotent and
non-destructive.

### beatscope_list_projects

`query?: str, backend?: "lightweight"|"beat-this"|"demucs", limit?: 1-100 = 20, offset?: int = 0`

Lists cached projects newest-first with identity, BPM, bars, duration,
backend, and provenance. Broken or unreadable cache entries are skipped with
a stderr warning, never surfaced as tool errors.

### beatscope_get_project

`project_id: 12-hex, detail?: "summary"|"timing"|"full" = "summary"`

- `summary`: identity and counts. When structural segments exist,
  `structure.segment_energy` adds one compact row per segment with
  frame-weighted mean `low`, `mid`, and `high` values. It never returns the
  underlying energy arrays.
- `timing`: adds beats, tempo segments, patterns, cues - never energy arrays.
- `full`: the complete schema v4 JSON. If it exceeds the response budget the
  reply carries `truncated: true` and the resource URI
  `beatscope://projects/{id}/rhythm` instead of a broken JSON string.

### beatscope_analyze_audio

`audio_path, backend? = "lightweight", subdivision?: 16|32 = 16, beat_file?, drums_path?, force? = false`

Analyzes a local audio file into a cached project. Rules:

- The file must live under an allowed root.
- `backend="beat-this"` **requires** `beat_file` (a `.beats` file from the
  Beat This workflow); `beat_file` is invalid with any other backend.
- `drums_path` means the user supplied a stem and, like `beat_file`, is valid
  only with `backend="beat-this"`; the server never pretends a separation
  happened that did not.
- Cache identity includes the audio, complete analysis configuration, and the
  content hashes of any `.beats` or drums-stem inputs.
- Heavy DSP runs on a worker thread; progress is reported through the MCP
  progress protocol (`value/total 1.0/message`). Cancellation (client
  cancels the request) sets an event the pipeline checks; **a cancelled
  analysis writes nothing**.
- Returns `{ok, project_id, cache_hit, source, tempo, grid, counts,
  analysis, warnings}` per schema v4 - never the raw energy arrays.

### beatscope_get_visual_state

`project_id, time: seconds >= 0`

One instant of visual state, computed by the shared JavaScript runtime (the
same `track.at(time)` the web player and the export package use):
`bar, beat, beatIndex, beatPhase, barPhase, low, mid, high, all, onset
{item, age, value}, accent, section`, and on v0.7 projects a `structure`
block with the current segment's `id, family, variant, label, index,
startTime, endTime, phase, nextBoundaryTime, secondsToBoundary`. The direct
JavaScript runtime uses `Infinity` before the first onset; MCP's JSON transport
encodes that sentinel as a `null` onset age. A `null` accent means no previous accent exists; a `null`
structure means the project carries no segments.

### beatscope_get_events

`project_id, start, end, include?: list, cue_types?: list, limit?: 1-500 = 100, offset? = 0`

Events in the half-open window **(start, end]**: `onsets` come from the
runtime's `between` op; `beats`, `cues` (accent/impact/scale/flow/flash/bloom),
and `pattern` bars are binary-sliced facts. `include` selects among `beats`,
`onsets`, `cues`, `patterns`, and - on v0.7 projects - `segments`
(`{kind, time, end, family, label, index}`, any overlap with the window) and
`boundaries` (`{kind, time, bar, novelty, drivers}`). Windows are capped at
600 s.
Results are sorted by `(time, kind)` and paginated with `{total, count,
offset, has_more, next_offset}`.

### beatscope_export_package

`project_id, destination (must end in .zip), overwrite? = false`

Writes the portable agent handoff ZIP: `rhythm-map.json`,
`beatscope-runtime.js`, `visual-state.js`, `worker-example.js`, `BEATSCOPE.md`, `SKILL.md`,
`references/schema.md`, `README.md`. The destination parent must exist and
live under an allowed root. The ZIP is written to a sibling temp file and
moved into place with an atomic replace, so a crash never leaves a truncated
file. An existing destination is kept unless `overwrite=true`. The response
returns path, size, SHA-256, and the ZIP manifest - not the binary.

## Module Worker use

The exported runtime has no DOM, Audio, Canvas, or wall-clock dependency, so
`visual-state.js` can run inside a browser module Worker. The ZIP includes a
ready-to-use `worker-example.js` adapter:

~~~js
const worker = new Worker("./worker-example.js", { type: "module" });
worker.onmessage = ({ data }) => render(data);

// The main thread owns HTMLAudioElement; the Worker only receives its clock.
worker.postMessage({ id: 1, time: audio.currentTime });
~~~

Serve the extracted package over HTTP with JavaScript module MIME types; module
Workers cannot normally import siblings from a ZIP or `file://` URL. The Worker
returns the same deterministic timing/scene frame as a direct main-thread call.

## Resources

| URI | Content |
| --- | --- |
| `beatscope://schema/v4` | Machine-readable schema v4 field reference. |
| `beatscope://projects/{project_id}/manifest` | Project summary without energy arrays or private paths. |
| `beatscope://projects/{project_id}/rhythm` | Complete schema v4 rhythm project JSON. |

Resource template parameters use the same 12-hex validation as the tools.

## Error semantics

Expected failures are raised as tool errors with actionable text, never as
`ok: true` payloads or opaque crashes:

- Unknown/invalid project → names the id, points at `beatscope_list_projects`
  or `beatscope_analyze_audio`.
- Path outside allowed roots → explains `BEATSCOPE_ALLOWED_ROOTS`.
- `beat-this` without `beat_file` → says exactly what is missing.
- Export destination exists → says to pass `overwrite=true`.
- Analysis pipeline failure → `AnalysisFailed` with the pipeline message.
- Runtime bridge unavailable/timeout → explains Node setup.

## Runtime parity

Position, phases, energy interpolation, onset impulse, quantization, and
window semantics are computed by one JavaScript runtime
(`beatscope/runtime/runtime.js`) shared by the web player, the export
package, and the MCP server through a Node worker subprocess. The Python
side never recomputes these values. `tests/mcp/test_runtime_parity.py`
asserts byte-identical state between direct runtime calls and MCP tool
responses, including after seeks and past the last stored beat.

## Evaluations

`evaluations/beatscope_mcp.xml` pins ten read-only question/answer pairs
against a committed synthetic fixture cache
(`evaluations/fixtures/mcp-eval-cache`, manifest in
`evaluations/fixtures-manifest.json`). They verify the "agent that knows
nothing about the internals" goal; `tests/mcp/test_evaluation_fixture.py`
keeps the answers reproducible.

## Development

~~~powershell
python -m pytest tests/mcp -q          # MCP contract tests
python tests/record_mcp_snapshots.py   # re-pin the tool/resource surface
python evaluations/build_fixture.py    # regenerate the evaluation fixture
~~~

The tool/resource surface is pinned by snapshots under `tests/mcp/snapshots/`;
a failing snapshot comparison means the contract changed and must be a
conscious decision.
