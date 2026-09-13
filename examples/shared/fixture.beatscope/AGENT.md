# BeatScope timing handoff: consumer-fixture

You are reading the measured timing facts for one audio file: 30.000 s,
15 bars, 60 beats, 370 transients, 3 structural segments.
This package describes the music. It carries no visual style, no scene, no
assets, and no task, because the visual is a decision you make with the user.

## Start here

1. Read `beatscope-package.json` first. It is the routing document: entry module,
   exported functions, the honest capability set, a short summary of the track,
   and the sha256 of every member.
2. Verify before you build: run `node consumer-probe.js .` from the package root.
   It imports the entry module, checks every declared function, and reports
   whether the package agrees with itself on this machine.
3. Query facts, never audio: `getVisualState(time)` for the frame, and
   `getResponseEvents(start, end, budget)` when the manifest enables
   `response_relevance`.

## Clock contract

- Time is seconds of media time, from `clock.minimum` to `clock.maximum`.
- Interactive playback: sample `audio.currentTime` once per animation frame and
  pass it in. Offline rendering: derive seconds from the frame number and the
  composition FPS. Never accumulate time across frames.
- Every query is pure: pause, seek, replay, re-render one frame, or query in any
  order. The answer for a given time never changes. Keep your own animation state
  seek-safe the same way.

## What you can trust

- `beatPhase` and `barPhase` interpolate between the two measured beats around the
  query, so variable tempo stays honest.
- `low`, `mid`, `high` are measured band energy: frequency evidence, not
  instrument labels. The data never identifies a kick, snare, or 808.
- Structure families (`A`, `B`, ...) mark recurrence, never musical roles, and
  `variant` means a related passage rather than a new identity.
- `response_relevance` is an ordering value learned from human-authored rhythm
  charts. Spend it through `getResponseEvents(start, end, budget)`: the returned
  objects are existing onsets at their stored times, and the value is not a
  probability or a command to animate everything it ranks. When ranking is
  unavailable the call reports `chronological-fallback`; keep that fact in your
  diagnostics instead of presenting the fallback as ranked output.

## Ground rules

- Never re-analyse the audio, and never scan arrays every frame to re-derive facts
  the frame already carries.
- The audio element owns transport; the visual only samples the current time.
- Keep animation deterministic: no wall-clock timers, no unseeded random motion,
  nothing that breaks single-frame rendering.
- Respect reduced-motion preferences: drop continuous agitation, keep the
  composition honest.
- Do not infer instruments, emotion, or semantic section names.

## Settle these with the user before writing visual code

- What are we making: a new visual, a variation of something they have seen, a
  tool, or an edit of existing footage?
- Do they have material (footage, images, logo, palette, fonts), or should it be
  generated?
- Format: aspect ratio, frame rate, resolution, whole song or a segment?
- How dense should the responses be? Run `getResponseEvents` for two or three
  budgets and show the event counts, then let the user choose instead of guessing
  a threshold.
- Delivery: an interactive page, a rendered file, or both?

## Self-check before you finish

    node consumer-probe.js .

Timing parity must be exact: the same time must resolve to the same facts.

## Package honesty

`beatscope-package.json` describes what exists, not aspirations. Trust it over any
other description: if it does not declare a function or a file, do not use it.
`README.md` lists what is deliberately absent, `SKILL.md` and
`references/schema.md` cover consumption and exact field semantics, and
`BEATSCOPE.md` holds the timing invariants.
