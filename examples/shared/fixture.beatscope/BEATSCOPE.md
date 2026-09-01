# BeatScope handoff: consumer-fixture

This package is the inspected timing data for one audio file. It is intended to be handed to an agent making an audio-reactive web, video, or motion visual.

## Rules

- Do not re-analyse the audio. Use `rhythm-map.json` as the source of analysed timing facts.
- Use `audio.currentTime` as the only clock. When the package carries visual artifacts, call `getBeatScopeFrame(audio.currentTime)` from `visual-state.js` — one call returning `{ timing, scene }` — and treat timing state and scene state as separate surfaces. Otherwise call `getVisualState(time)`.
- Every animation must remain correct after pause, seek, replay, and rendering a single frame. Do not use wall-clock timers or non-reproducible random motion.
- Keep playback controls and the visual clock separate: audio controls own transport; the visual samples the current time.
- Heavy state queries may run in a module Worker via `worker-example.js`; the main thread still owns the audio element and sends its current time.
- When `visual-recipe.json` is present, respect its tokens (palette, transition timing, motion limits) before inventing new ones, keep family identity stable across repetitions, and keep any extra motion seek-safe.

## Suggested mapping

`low`, `mid`, and `high` can drive separate scale, density, or line-weight layers. `onset` and `accent` are short impulses; `beatPhase` and `barPhase` provide repeatable breathing; `section` can change composition density or palette. These are starting points, not instrument labels. The data does not identify kick, snare, or 808. When `rhythm-map.json` carries `patterns.segments`, treat segment boundaries as scene-level changes, treat `family` and `variant` as recurrence rather than musical role, and never rename the neutral `A`/`B` families without instruction. When `visual-timeline.json` is present, `getSceneState(time).scene` reports the compiled scene (`family`, `variant`, `motif`, `phase`) and `.transition` reports the boundary envelope (`stage`, `approach`, `cross`, `settle`) — do not animate every property at every boundary.

The original file name, duration, BPM, origin, beats, raw onsets, energy arrays, section annotations, and (when present) whole-song structure segments are recorded in `rhythm-map.json`.
