# BeatScope timing package fields

The field reference. The collaboration flow lives in `AGENT.md`, the timing invariants in `BEATSCOPE.md`, and how to consume the API in `SKILL.md`; this file is what to look up when you need an exact field.

The package carries measured timing facts for one audio file, and ships no visual layer: no recipe, no scene timeline, no palette. `getVisualState(time)` and `getResponseEvents(start, end, budget)` are the only accessors, and `rhythm-map.json` is the authoritative data — query it, do not read it in full.

## rhythm-map.json

Uses `schema_version: "beatscope-rhythm-map-1.0"`. Top-level fields include `duration`, `bpm`, `origin`, `subdivision`, `bars_count`, `beats`, `onsets`, `energy`, and `sections`.

- `beats`: ordered objects with `time`, `bar`, `beat`, and optional `downbeat`.
- `onsets`: ordered raw events with `raw_time`, `strength`, `bands.all/low/mid/high`, and `accent`.
- `energy`: sampled arrays under `bands.all/low/mid/high`, with `fps` and `start`; older maps may instead expose `frames`.
- `sections`: optional per-bar summaries such as `bar`, `label`, `group`, `mean_strength`, and `similarity_previous`.
- `patterns.segments` (optional, v0.7): ordered whole-song segments with `id`, `index`, `start_bar`/`end_bar` (inclusive), `start_time`/`end_time` (half-open; the final segment ends at `duration`), `family`, `variant`, `display_label`, and `bar_count`.
- `patterns.boundaries` (optional): one per adjacent segment pair, with `bar`, `time`, `novelty` in 0-1, and `drivers` naming the dimensions that changed.
- `patterns.repetitions` (optional): which segments repeat, grouped by `family`. Family letters mark recurrence, not musical role.

## visual-state.js

Exports `getVisualState(time)` and `RHYTHM_MAP`; it builds on the shared runtime shipped as `beatscope-runtime.js` (`createTrack`). `getVisualState(time)` returns the runtime track state at that audio time: `time`, `bar`, `beat`, `beatIndex`, `beatPhase`, `barPhase`, raw band energy in `low`/`mid`/`high`/`all`, `onset` and `accent` as decaying impulses `{item, age, value}` over the previous onset (`accent` is `null` unless the onset is cued as an accent), and `section`. When the map carries segments, a `structure` block adds the current segment's `id`, `family`, `variant`, `label`, `index`, `startTime`, `endTime`, `phase`, `nextBoundaryTime`, and `secondsToBoundary`; it is `null` on older maps. Direct JavaScript uses `Infinity` for onset age before the first onset; canonical JSON/probe and MCP transports encode that compatibility sentinel as `null`. A `null` accent means no previous accent exists at that time.

## beatscope-package.json

The routing manifest. Trust it over prose: if it does not declare a function or a file, the package does not carry it.

- `schema` (`beatscope-package-1`), `package_version`, `project_id`.
- `display_name`: the original audio file name; pair the package with that file.
- `summary`: `bpm`, `bars`, `beats`, `onsets`, `segments` — the shape of the track without parsing the data.
- `duration`, `clock` (`unit: seconds`, `semantics: media-time`, `minimum`, `maximum`).
- `capabilities`: booleans that describe what is actually present (`timing`, `bands`, `structure`, `module_worker`, `response_relevance`).
- `functions`: the exported names to call (`timing`, and `response_events` when the capability is on).
- `files`: where the canonical documents live.
- `integrity`: `sha256` of every other member, so a consumer can verify the package before running it.

## rhythm.mid

Standard MIDI file: one tempo-map track (per-segment when the song changes tempo) plus one note per onset on middle C, velocity from `strength`, **quantised to the exported subdivision**. It carries no beats layer and no markers. Because it is quantised it is a musical reference, never an exact cut list: every cut, marker or edit uses the measured time from `rhythm.csv` (`raw_time`) or the JSON.

## rhythm.csv

One row per onset: `raw_time`, `quantized_time`, `offset_ms`, `bar`, `beat`, `step`, `strength`, `low`, `mid`, `high`, `accent`. `raw_time` is the measured instant and the one to cut on; `quantized_time` and `offset_ms` describe how far the onset sits from the grid, which is information, not a correction.

## Response relevance (v0.11)

When `beatscope-package.json` declares `capabilities.response_relevance: true`, the package also carries `response-relevance.json` (`schema: beatscope-response-relevance-1`) and `visual-state.js` exports `getResponseEvents(start, end, budget)`. The sidecar maps every existing `onset_id` to `response_relevance` in 0-1; it contains no timestamps. The helper selects at most `budget` events by that ordering and then restores chronological order. Its result includes `available`, `semantics`, `strategy`, `total`, `selected`, and `events`. `response_relevance` is not probability or confidence. With no valid sidecar the helper reports `available: false`, `strategy: chronological-fallback`, and returns the first events in time order.
