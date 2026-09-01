# BeatScope Agent handoff: consumer-fixture

You are reading a BeatScope handoff package: the analyzed timing facts for one audio track (30.000 s), prepared for an autonomous Agent that builds a new visual consumer.

## Your task

Build a new audio-reactive visual consumer around this package. Do not modify, rebuild, or copy the BeatScope player, and do not import anything from a BeatScope installation: this package is self-contained.

## Start here

1. Read `beatscope-package.json` first. It is the routing document: it names the entry module, the exported functions, the honest capability set, and the sha256 of every member.
2. Import the function named by `functions.frame` from the file named by `entry` (`visual-state.js`).
3. Sample time, not audio. The package never contains the audio itself; pair it with the original local media file.

## The clock contract

- Time is seconds of media time, from `clock.minimum` to `clock.maximum`.
- Interactive playback: sample `audio.currentTime` once per animation frame and pass it to the frame function.
- Offline rendering: derive seconds from the requested frame number and the composition FPS (`seconds = frame / fps`), then call the same function. Never accumulate time across frames.
- Every query is pure: pause, seek, replay, re-render one frame, or query in any order. The answer for a given time never changes. Keep your own animation state seek-safe the same way.

## Minimal start

```js

import { getBeatScopeFrame } from './visual-state.js';

function render(timeSeconds) {
  const frame = getBeatScopeFrame(timeSeconds);
  // frame.timing is audio evidence; frame.scene is BeatScope's
  // deterministic visual orchestration. Map facts to authored visuals.
  draw(frame);
}

```

`frame.timing` is audio evidence: beat phase, onsets, band energies, and structural facts measured from the track. `frame.scene` is BeatScope's own deterministic visual orchestration. You may ignore `frame.scene` and author your own mapping, which is encouraged, but you must not alter, re-derive, or second-guess the factual timing contract.

## Scene surface

This package carries a compiled scene timeline (`capabilities.scenes` is true). `getSceneState(time)` reports the current scene (`family`, `variant`, `motif`, `phase`) and `getBeatScopeFrame` adds the boundary envelope (`stage`, `approach`, `cross`, `settle`) during structural transitions.

## Ground rules

- Never re-analyse audio, and never scan arrays every frame to re-derive facts the frame already carries.
- Use beat and onset facts for local motion; use structure and scene boundaries for scene-scale changes.
- Do not infer instruments, emotion, or semantic section names. Structural families are neutral letters (`A`, `B`, ...), not musical roles.
- Keep animation deterministic: no wall-clock timers, no unseeded random motion, nothing that breaks single-frame rendering.
- Preserve playback controls: the audio element owns transport; the visual only samples the current time.
- Respect reduced-motion preferences: when the user asks for reduced motion, drop continuous agitation while keeping the composition honest.

## Self-check before you finish

Run the supplied probe from the package root:

    node consumer-probe.js . --checkpoints <checkpoints.json>

The probe imports `visual-state.js`, verifies every declared function, and replays recorded checkpoints when a checkpoint file is supplied. Frame parity must be exact. When you work inside the BeatScope repository itself, also run the repository's consumer validation command (see the repository README).

## Package honesty

`beatscope-package.json` describes what exists, not aspirations. Trust it over any other description: if it does not declare a function or a file, do not use it. Detailed guidance for building the visual lives in `SKILL.md`; exact field semantics live in `references/schema.md`; the implementation handoff notes remain in `BEATSCOPE.md`.
