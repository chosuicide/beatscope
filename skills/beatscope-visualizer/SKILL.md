---
name: beatscope-visualizer
description: Build deterministic audio-reactive web, video, or motion visuals from a BeatScope export package.
---

# BeatScope visualizer handoff

Use this skill when a BeatScope export package is provided for an audio-reactive visual. Read `BEATSCOPE.md`, then inspect `rhythm-map.json` and `visual-state.js` before writing visual code.

## Timing contract

- Do not re-analyse the audio. The exported timing and energy data are the inspected facts.
- Make `audio.currentTime` the only clock. Sample `getVisualState(audio.currentTime)` on each render or update.
- Keep visuals seek-safe and pause-safe: the same time must produce the same frame, with no wall-clock drift, hidden timers, or non-reproducible random state.
- Use the export's `duration`, `bpm`, `origin`, `beats`, `onsets`, `energy`, and `sections` as available; gracefully handle missing optional arrays.

## Motion mapping

Use `low` for scale or weight, `mid` for surface motion, and `high` for light or fine detail. Use `onset` and `accent` for short impact impulses, `beatPhase` and `barPhase` for repeatable breathing, and `section` for larger composition changes. Treat these as rhythm-strength signals, not instrument identity: do not claim a signal is a kick, snare, or 808.

Keep controls accessible and make pause, replay, and arbitrary seek work without special cases. Read [`references/schema.md`](references/schema.md) when exact field semantics are needed.
