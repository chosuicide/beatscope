# BeatScope timing invariants: consumer-fixture

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
- `low`, `mid`, `high`, `all`: measured band energy, 0-1. Frequency evidence,
  never instrument identity - the data does not identify a kick, snare or 808,
  and a consumer must not claim it does.
- `onset`, `accent`: transients with a `value` and an `age` in seconds.
- `state.structure`: the current segment (`id`, `family`, `variant`, `label`,
  `index`), its `phase`, `nextBoundaryTime` and `secondsToBoundary`. Family
  letters mark recurrence, not musical role: `A'` is related to `A`, never
  "Chorus". Never rename them unless the user asks.
- `response_relevance`: an ordering value learned from human-authored rhythm
  charts, used to spend a limited response budget. It is not a probability, a
  confidence score or an instruction to animate everything it ranks.

## Times: measured versus quantised

- Every onset carries the instant it was measured at (`raw_time`, exposed as
  `time` by the API). That is the only value a cut, marker or edit may use.
- `rhythm.mid` is quantised to the exported subdivision and `rhythm.csv` also
  carries `quantized_time` with `offset_ms`: both are annotations. Snapping a
  cut to a grid the user did not ask for is a defect, not a simplification.

## Invariants

- Never re-analyse the audio, and never scan arrays every frame for facts the
  frame already carries.
- The audio element owns transport; the visual only samples the current time.
- Honour `prefers-reduced-motion`: the facts never change, but your motion must
  drop continuous agitation.
