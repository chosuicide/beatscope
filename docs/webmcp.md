# BeatScope WebMCP Director: complete contract

The Studio page exposes the loaded track as eight WebMCP tools through
`document.modelContext.registerTool`. An agent inside a WebMCP-capable
browser can inspect any moment, read bounded events, rank and compare visual
ranges, then focus, audition, and loop a range in the same player the user is
watching.

This document is the full contract. The README only covers getting started.

## Two entry points, one model

| | WebMCP Director | stdio MCP server |
| --- | --- | --- |
| Where it runs | inside the Studio page | local subprocess |
| Consumer | the browser Agent host | desktop MCP clients |
| Transport | `document.modelContext` | stdio JSON-RPC |
| Lifecycle | page session, disposed on `pagehide` | server process |
| Tools | the eight below, page-scoped | six `beatscope_*` tools (see [mcp.md](mcp.md)) |

Both read the same Rhythm IR v4 through the same dependency-free runtime, so
a query answered in the browser and a query answered over stdio describe the
same song with the same semantics. Only transport and lifecycle differ.

## Semantics statement

BeatScope reports **timing facts**: beats, transients (onsets),
frequency-band energy, and neutral structural repetition. It does **not**
identify instruments and never labels a range verse, chorus, drop, kick,
snare, or 808. Structure appears only as repeat families (`A`, `B`, `A′`):
`A′` is related to `A`, nothing more. A candidate range is a measured
suggestion for the user to audition - not musical truth.

## Running the demo

~~~powershell
python scripts/build_webmcp_demo.py
python tests/browser/webmcp_demo_server.py --port 8770 --directory build/webmcp-demo
~~~

Open `http://127.0.0.1:8770/?demo=webmcp`. The header status pill moves
through `WEBMCP · LOAD A TRACK`, `WEBMCP READY · 8 TOOLS`, `WEBMCP ERROR`,
and `WEBMCP UNAVAILABLE` (no `document.modelContext`). The demo track is
pre-analyzed, authorized material: `scripts/make_webmcp_demo_audio.py`
synthesizes it deterministically and the committed fixture lock verifies the
bytes. The bundled demo server sends HTTP Range headers, which Chromium
requires before it will seek an audio element.

The regular Studio at `/?` works exactly as before: upload is local, analysis
is local. WebMCP adds a collaboration surface on top - it never replaces the
user's own controls.

## Lifecycle

- On page load the Studio calls `installWebMCP()`: all eight tools are
  registered in one session, and the status callback reports `registering`,
  then `ready` or `error`.
- Registration is aborted on `pagehide`, so the tools disappear with the
  page.
- Installing again disposes the previous session first; the abort signal
  unregisters the tools on the host. In-flight calls reject with
  `CANCELED`.

## Response envelope

Every tool returns `{ok: true, ...}` or
`{ok: false, error: {code, message}}`. All seconds are rounded to four
decimals, and nothing in a tool path consults a wall clock or randomness:
the same query over the same project returns byte-identical JSON. Responses
are bounded - no filesystem paths, no audio bytes, no uncapped arrays.

Every successful page-changing action is announced in the on-page Agent
ledger with a bounded label such as `Focused bars 11—18` or `Looped bars
11—18`. Read tools leave playback, focus, loop state, and the ledger
byte-identical, matching their `readOnlyHint: true` annotation.

## Read tools

Five tools carry `readOnlyHint: true`. They never change playback, the loop,
the window, or the Agent Focus.

### get_project_context

`{}` - no inputs. The first call to make. Returns:

- `track`: `displayName`, `duration`, `globalBpm`, `bars`, `timeSignature`
  as `[beatsPerBar, beatUnit]`, and `variableTempo` (true only when stored
  tempo segments really disagree with the global BPM).
- `playback`: `time`, `playing`, `bar`, `beat`, and
  `loop {enabled, startTime, endTime}` (`null` times when no loop selection
  exists).
- `structure`: `available`, `current {family, label, variant, startBar,
  endBar, phase}`, up to 32 `segments`, and `total`/`truncated` when more
  exist.
- `capabilities`: the other seven tool names.

### get_state_at_time

`time?: seconds >= 0 (default: the current playback position)`,
`includeScene?: boolean = true`.

One deterministic instant: `position {bar, beat, beatPhase, barPhase}`,
`energy {all, low, mid, high}`, `onset {impulse, age, strength, accent}`
(`age`, `strength`, and `accent` are `null` between onsets), `structure
{family, label, variant, phase, secondsToBoundary}` or `null`, and `scene
{available, family, motif, phase, transitionStage}` when visual artifacts
are loaded. `time` is clamped to the track; when omitted, the response adds
`playing`.

### get_events

`startTime` + `endTime` (seconds) or `startBar` + `endBar` (1-based,
inclusive) - never both. `include`: 1-5 unique kinds from `beats`, `onsets`,
`segments`, `boundaries`, `cues` (default `[beats, onsets, boundaries]`);
`limit`: 1-200, default 100.

Windows are capped at 64 bars or 180 seconds. Beats, onsets, boundaries, and
cues use the half-open `(start, end]` slice; segments appear on any overlap.
Events sort by `(time, kind)` (`startTime` is the segment timestamp). At
equal times, segments come before boundaries, boundaries before beats,
beats before onsets, onsets before cues. The response carries `range
{startTime, endTime, startBar, endBar}`, the capped `events`, `total`, and
`truncated`.

### find_visual_moments

`kind`: `structural_transition`, `strong_transient`, `energy_lift`,
`energy_drop`, or `quiet_contrast`; `windowBars`: 4, 8, or 16 (default 8);
`band`: `all`, `low`, `mid`, or `high` (default `all`); `limit`: 1-8
(default 3).

Returns ranked, bar-aligned candidates with stable ids
(`kind:startBar-endBar`), `anchorTime`, one fixed `reason` line per kind,
and measured `facts {boundaryNovelty, energyBefore, energyAfter,
onsetDensity, peakStrength, dominantBand}`. A candidate overlapping an
already-kept one by more than half is dropped. Scoring uses measured facts
only: boundary novelty for transitions, peak onset strength for transients,
mean band-energy change for lifts and drops, quietest mean for contrast. If
nothing matches, the tool raises `NO_CANDIDATES` instead of inventing one.

### compare_ranges

`ranges`: 2-4 objects `{startBar, endBar, label? (<= 48 characters)}`.

Each range is summarized - `onsets`, `onsetDensity`, `peakStrength`,
per-band `energy {mean, peak}`, `dominantBand`, and the `families` it
intersects - and the reply adds `differences`: numeric sentences such as
`B has 18% higher high-band mean than A` (energy threshold 0.05) or
`B has 2.3 more onsets per second than A` (density threshold 0.5/s). When
nothing crosses a threshold it says exactly that; differences are never
invented.

## Action tools

Three tools carry `readOnlyHint: false`. Each validates every input first,
takes an undo snapshot, then commits its changes in one pass - a rejected
call leaves the page byte-identical, down to the undo stack.

### focus_range

`startBar`, `endBar`, `reason` (1-120 characters, required, echoed back).

Selects and shows a bar range: the eight-bar window moves to the range,
follow-playback turns off so the window stays put, and an Agent Focus marker
with the stated reason appears. It does **not** seek, play, pause, or loop -
combine it with `control_playback` and `set_loop_range`. The user can clear
the focus at any time.

### control_playback

`action`: `play`, `pause`, `seek`, or `seek_and_play`. `seek` and
`seek_and_play` take `time` (seconds) or `bar` with an optional `beat`
(1-based, must exist in the meter) - never both. `preRollBeats`: 0-16,
default 0, walks back real stored beats, so variable-tempo songs stay
accurate; only beat-less projects fall back to the global-BPM grid, and the
response names the source via `timingSource` (`stored-beats` or
`synthetic-grid`). The song start clamps to 0.

`play` and `pause` take no position fields. Responses carry `targetTime`,
`seekTime`, `currentTime`, `playing`, and `requiresUserGesture` - `true`
means the browser blocked programmatic audio start, and the user's own play
button is the fallback. The tool never changes the Agent Focus or the loop.

### set_loop_range

`enabled`: boolean; when `true`, `startBar` and `endBar` (1-based,
inclusive) are required. `enabled=false` stops looping but keeps the range
so the user can re-enable it. It does not seek, play, pause, or touch the
Agent Focus. Loop boundaries retain the stored downbeat timestamps, so a
tempo change cannot silently expand or shorten the requested bars.

## Reversal belongs to the user

Every action snapshots the page state before mutating. The Studio UI can
undo the most recent Agent action - focus, window, loop, seek, and play
state all restore, and the ledger logs the undo like any other action.
Deliberately, there is no `undo` WebMCP tool: the Agent proposes, the user
owns reversal.

## Errors

Expected failures return `{ok: false, error: {code, message}}` with stable,
user-facing copy - never a crash, never `ok: true` with empty data:

| Code | Message |
| --- | --- |
| `NO_TRACK` | Load a BeatScope track before using this tool. |
| `INVALID_RANGE` | The requested range is not usable. Check the bars or times and try again. |
| `OUT_OF_RANGE` | The requested position is outside the loaded track. |
| `NO_STRUCTURE` | This track has no stored structural segments. |
| `NO_CANDIDATES` | No candidate matched this query on the loaded track. |
| `PLAYBACK_UNAVAILABLE` | Playback is not available in this page state. |
| `CANCELED` | The call was canceled before it finished. |
| `INTERNAL_ERROR` | The tool failed unexpectedly. The browser console has details. |

Handlers re-validate every input after the JSON Schema layer; unexpected
failures log to the browser console and surface as `INTERNAL_ERROR`.

## Security model

- Tool names, titles, and descriptions are frozen literals in
  `beatscope/web/webmcp/schemas.js` - never assembled from song names, file
  metadata, or user input, so a hostile project cannot poison the tool
  catalog.
- Every response is bounded: no filesystem paths, no audio bytes, arrays
  with hard caps, seconds at four decimals.
- Free-text `reason` and `label` inputs are sanitized (control characters
  stripped, whitespace collapsed, length clamped), and the page renders
  Agent-provided text as text content only.
- The tools perform no network I/O and read no files; they answer from the
  analysis already in page memory. Audio never reaches the Agent.
- Read tools are annotated `readOnlyHint: true`; actions are visible in the
  ledger and reversible by the user.

## Limits

- Every tool answers `NO_TRACK` until a track is loaded.
- Event windows are capped at 64 bars / 180 seconds and 200 events.
- `find_visual_moments` returns at most 8 candidates and can honestly answer
  `NO_CANDIDATES`.
- `compare_ranges` compares 2-4 ranges and reports differences only above
  measured thresholds.
- Structure labels are repeat families, not Verse/Chorus roles, and onsets
  are not instruments.
- The tools are registered per page session; without a WebMCP-capable
  browser the Studio shows `WEBMCP UNAVAILABLE` and works normally.

## Example prompts

Against the loaded Studio page in a WebMCP-capable browser chat:

> Read this track and give me its neutral structure.

`get_project_context` - segments, families, and where playback sits now.

> Find the three strongest eight-bar structural transitions.

`find_visual_moments` with `kind: "structural_transition"`, `limit: 3`.

> Compare the first and second candidate. Which one has the larger high-band lift?

`compare_ranges` over the two candidate windows, reading the high-band mean
difference.

> Focus the second one, start two beats early, and loop it.

`focus_range` with a stated reason, then `control_playback`
`seek_and_play` with `preRollBeats: 2`, then `set_loop_range` for the same
bars. The user watches, listens, and decides; every step appears in the
ledger and the last one can be undone.

## Tests and snapshots

- `tests/test_webmcp_queries.js`, `tests/test_webmcp_actions.js`, and
  `tests/test_webmcp_registration.js` pin the contracts;
  `tests/test_webmcp_benchmark.js` keeps every query batch under its
  recorded budget.
- `tests/record_webmcp_snapshots.mjs --accept` re-records the frozen
  response snapshots under `tests/snapshots/webmcp/`; a snapshot diff means
  the contract changed and must be a conscious decision.
- `tests/browser/webmcp-smoke.mjs` replays the full browser round trip
  against the built demo bundle: register, query, focus, loop, seek with
  pre-roll, loop wrap, and pause.
