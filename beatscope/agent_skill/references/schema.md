# BeatScope export fields

`rhythm-map.json` uses `schema_version: "beatscope-rhythm-map-1.0"`. Top-level fields include `duration`, `bpm`, `origin`, `subdivision`, `bars_count`, `beats`, `onsets`, `energy`, and `sections`.

- `beats`: ordered objects with `time`, `bar`, `beat`, and optional `downbeat`.
- `onsets`: ordered raw events with `raw_time`, `strength`, `bands.all/low/mid/high`, and `accent`.
- `energy`: sampled arrays under `bands.all/low/mid/high`, with `fps` and `start`; older maps may instead expose `frames`.
- `sections`: optional per-bar summaries such as `bar`, `label`, `group`, `mean_strength`, and `similarity_previous`.
- `patterns.segments` (optional, v0.7): ordered whole-song segments with `id`, `index`, `start_bar`/`end_bar` (inclusive), `start_time`/`end_time` (half-open; the final segment ends at `duration`), `family`, `variant`, `display_label`, and `bar_count`.
- `patterns.boundaries` (optional): one per adjacent segment pair, with `bar`, `time`, `novelty` in 0-1, and `drivers` naming the dimensions that changed.
- `patterns.repetitions` (optional): which segments repeat, grouped by `family`. Family letters mark recurrence, not musical role.

`visual-state.js` exports `getVisualState(time)` and `RHYTHM_MAP`; it builds on the shared runtime shipped as `beatscope-runtime.js` (`createTrack`). `getVisualState(time)` returns the runtime track state at that audio time: `time`, `bar`, `beat`, `beatIndex`, `beatPhase`, `barPhase`, raw band energy in `low`/`mid`/`high`/`all`, `onset` and `accent` as decaying impulses `{item, age, value}` over the previous onset (`accent` is `null` unless the onset is cued as an accent), and `section`. When the map carries segments, a `structure` block adds the current segment's `id`, `family`, `variant`, `label`, `index`, `startTime`, `endTime`, `phase`, `nextBoundaryTime`, and `secondsToBoundary`; it is `null` on older maps. A `null` onset age or accent means no previous onset exists at that time.

## Visual artifacts (v0.8)

When the package carries visual artifacts, `visual-state.js` additionally exports `getSceneState(time, options)` and `getBeatScopeFrame(time, options)`; `getVisualState`'s own output is unchanged.

- `visual-recipe.json` (schema `beatscope-visual-recipe-1`): `mode` (`structure` or `legacy`), `tokens` with the `palette` (four hex colors: `paper`, `ink`, `accent`, `warm`), `transition` timing (`lead_beats`, `settle_beats`, `max_lead_seconds`, `max_settle_seconds`), and `motion` limits (`max_scene_spread`, `max_scene_twist`, `max_palette_mix`); `families` maps each neutral family letter to its `motif`, `palette_slot` (0-3), and `composition` channels (`spread`, `twist`, `flow`, `orbit`, `void`, `contrast`).
- `visual-timeline.json` (schema `beatscope-visual-timeline-1`): `scenes` are half-open time spans (`start_time`/`end_time`; the final scene ends at `duration`) carrying `id`, `segment_id`, `family`, `variant`, `label`, `motif`, and bounded `variant_delta`; `transitions` sit on scene boundaries with `time`, `treatment` (`phase-turn`, `radial-part`, `aperture`, `flow-shear`, or a neutral cross), `driver`, `strength` in 0-1, and `lead_seconds`/`settle_seconds`.
- `getSceneState(time, options)` returns one frozen frame: `scene` (`id`, `family`, `variant`, `motif`, `label`, `phase`), `transition` (`stage`: `approach`/`cross`/`settle`/`idle`, `approach`/`cross`/`settle` envelopes in 0-1, `impulse` at the boundary instant, and per-treatment `channels`), and `composition` (interpolated `spread`, `twist`, `flow`, `orbit`, `void`, `contrast`, plus `paletteMix` while a transition crossfades). `options.reducedMotion` collapses motion channels to their calm form; palette/contrast crossfades stay.
- `getBeatScopeFrame(time, options)` returns `{ timing, scene }` — the runtime state and the scene state sampled at the same instant. Use it as the only animation input.
