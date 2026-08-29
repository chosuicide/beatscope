# BeatScope export fields

`rhythm-map.json` uses `schema_version: "beatscope-rhythm-map-1.0"`. Top-level fields include `duration`, `bpm`, `origin`, `subdivision`, `bars_count`, `beats`, `onsets`, `energy`, and `sections`.

- `beats`: ordered objects with `time`, `bar`, `beat`, and optional `downbeat`.
- `onsets`: ordered raw events with `raw_time`, `strength`, `bands.all/low/mid/high`, and `accent`.
- `energy`: sampled arrays under `bands.all/low/mid/high`, with `fps` and `start`; older maps may instead expose `frames`.
- `sections`: optional per-bar summaries such as `bar`, `label`, `group`, `mean_strength`, and `similarity_previous`.

`visual-state.js` exports `getVisualState(time)` and `RHYTHM_MAP`; it builds on the shared runtime shipped as `beatscope-runtime.js` (`createTrack`). `getVisualState(time)` returns the runtime track state at that audio time: `time`, `bar`, `beat`, `beatIndex`, `beatPhase`, `barPhase`, raw band energy in `low`/`mid`/`high`/`all`, `onset` and `accent` as decaying impulses `{item, age, value}` over the previous onset (`accent` is `null` unless the onset is cued as an accent), and `section`.
