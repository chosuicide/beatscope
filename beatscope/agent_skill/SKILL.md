---
name: beatscope-visualizer
description: Consume a BeatScope timing package — deterministic rhythm facts for one audio file — when building or customising an audio-reactive visual.
---

# BeatScope timing package

Use this skill when a BeatScope package (a folder or zip holding `beatscope-package.json`) is provided for a piece of music. The package is **timing facts only**: it carries no style, no scene, no assets and no task. Read `AGENT.md` first — it is the contract — and `BEATSCOPE.md` for the invariants.

## What you have

- `rhythm-map.json` — the authoritative facts: beats, onsets with strength and band energy, accents, sampled energy, structure segments.
- `rhythm.mid` / `rhythm.csv` — the same facts for a DAW or a spreadsheet.
- `response-relevance.json` — an ordering value for spending a limited response budget, when the manifest enables it.
- `visual-state.js` — the dependency-free accessor: `getVisualState(time)`, plus `getResponseEvents(start, end, budget)`.
- `beatscope-package.json` — the routing manifest: entry, probe, capabilities, function names, a track summary, and the sha256 of every member.

## What is not in the package

No audio (pair it with the original local file; the package names it), no footage or images, no fonts, no palette, no style, no scene timeline, no rendered video, and no statement about aspect ratio, frame rate or pacing. Do not assume any of these exist: **ask the user**. The package deliberately stops at measurement, because the visual is a decision you make with them.

## Timing contract

- Do not re-analyse the audio. The exported timing and energy data are the inspected facts.
- Make `audio.currentTime` the only clock: sample `getVisualState(audio.currentTime)` once per animation frame. Offline, derive seconds from the frame number and the composition FPS. Never accumulate time across frames.
- Keep visuals seek-safe and pause-safe: the same time must produce the same frame, with no wall-clock drift, hidden timers, or non-reproducible random state.
- When the manifest enables `response_relevance`, use `getResponseEvents(start, end, budget)` for effects or edits that cannot afford every onset. Choose the budget per shot or section and, when the choice matters, show the user the event counts for two or three budgets instead of inventing a global threshold. The selected objects are existing onsets and keep their stored times.
- Honour `prefers-reduced-motion` in your own motion: the exported facts never change, but your animation should drop continuous agitation and keep layout or contrast changes calm.
- Read fields defensively: optional arrays such as `energy` or `patterns.segments` may be absent.

## What the fields mean

- `beat`, `bar`, `beatPhase`, `barPhase` — position in the measured grid. The phases interpolate between the two real beats around the query, so variable tempo stays honest.
- `low`, `mid`, `high`, `all` — measured band energy, 0-1. Frequency evidence, never instrument identity: do not claim a signal is a kick, snare, or 808.
- `onset`, `accent` — transient impulses with `value` and `age` (seconds since the event).
- `state.structure` — the current segment (`id`, `family`, `variant`, `label`, `index`), its `phase`, and `secondsToBoundary`; `track.structureLead` and `track.boundaryImpulse` describe approach and arrival.
- `family` (`A`, `B`, ...) marks recurrence, not musical role: `A′` is related to `A`, never "Chorus". Never rename the neutral letters unless the user asks.
- `response_relevance` is an ordering value learned from human-authored rhythm charts — not probability, confidence, or a command to animate. When ranking is unavailable, `getResponseEvents` reports `chronological-fallback`; keep that fact in your diagnostics instead of presenting the fallback as ranked output.

## Minimal example (no build system)

```html
<script type="module">
  import { getVisualState } from './visual-state.js';
  const circle = document.querySelector('#pulse');
  function render() {
    const frame = getVisualState(audio.currentTime);
    circle.setAttribute('r', 20 + frame.low * 30);
    requestAnimationFrame(render);
  }
  render();
</script>
```

Keep controls accessible and make pause, replay, and arbitrary seek work without special cases. Verify the package before building: `node consumer-probe.js .` — and read [`references/schema.md`](references/schema.md) when exact field semantics are needed.
