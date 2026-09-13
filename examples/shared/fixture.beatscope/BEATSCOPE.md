# BeatScope timing handoff: consumer-fixture

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
