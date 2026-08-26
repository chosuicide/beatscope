# BeatScope export fields

`rhythm-map.json` has `schema_version: "beatscope-rhythm-map-1.0"`. Top-level fields include `duration`, `bpm`, `origin`, `subdivision`, `bars_count`, `beats`, `onsets`, `energy`, and `sections`.

- `beats`: ordered objects with `time`, `bar`, `beat`, and optional `downbeat`.
- `onsets`: ordered raw events with `raw_time`, `strength`, `bands.all/low/mid/high`, and `accent`.
- `energy`: sampled arrays under `bands.all/low/mid/high`, with `fps` and `start`; older maps may instead expose `frames`.
- `sections`: optional per-bar summaries such as `bar`, `label`, `group`, `mean_strength`, and `similarity_previous`.

`visual-state.js` exports `getVisualState(time)` and `RHYTHM_MAP`. The returned state includes `time`, `bar`, `beat`, `beatPhase`, `barPhase`, `low`, `mid`, `high`, `all`, `accent`, `onset`, and `section`.
