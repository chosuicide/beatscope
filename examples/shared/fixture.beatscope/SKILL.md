---
name: beatscope-visualizer
description: Consume a BeatScope timing package — deterministic rhythm facts for one audio file — when building or customising an audio-reactive visual.
---

# Consuming a BeatScope timing package

Use this skill when a package (a folder or zip holding `beatscope-package.json`) is provided for a piece of music. **Read `AGENT.md` first**: it owns the collaboration flow, the questions to ask the user, and how to read this package without loading megabytes into context. **`BEATSCOPE.md` owns the timing invariants** — the clock contract, what the fields mean, and the difference between measured and quantised times. This file is only about the API.

## The two functions

- `getVisualState(time)` → one instant's facts: `time`, `bar`, `beat`, `beatIndex`, `beatPhase`, `barPhase`, `low`/`mid`/`high`/`all`, `onset` and `accent` as `{item, age, value}`, `section`, and `structure` (`id`, `family`, `variant`, `label`, `index`, `startTime`, `endTime`, `phase`, `nextBoundaryTime`, `secondsToBoundary`).
- `getResponseEvents(start, end, budget)` → the candidates in one window, chosen by the ordering value and restored to time order: `{available, semantics, strategy, total, selected, events}`. Each event is `{id, time, strength, bands, response_relevance}` at the instant it was measured. When ranking is unavailable the call reports `strategy: "chronological-fallback"`; keep that fact in your diagnostics instead of presenting the fallback as ranked output.

## The primitive to copy: candidates, real times, a bounded number of responses

This is the shape, not a style — the treatment is yours, and it should come from what you and the user agreed to make.

```js
import { getVisualState, getResponseEvents } from './visual-state.js';

// One window, a budget you derived from the pacing you agreed on, and the
// candidates at their measured times. Nothing here is quantised.
const window = { start: 24, end: 40 };
const budget = 10;
const candidates = getResponseEvents(window.start, window.end, budget).events;
const marks = candidates.map((event) => ({ time: event.time, strength: event.strength }));

function frame(mediaTime) {
  const facts = getVisualState(mediaTime);
  const live = marks.filter((mark) => mediaTime >= mark.time && mediaTime - mark.time < 0.12);
  // ...your own treatment for `live`, driven by `facts`...
  return facts;
}
```

Why this shape and not a growing circle:

- the marks are the events the ranking says are worth spending, at their **measured** times — no grid, no re-quantising, no smoothing them into a pulse;
- the budget is a decision, not a setting: derive it from the intent and the material, and change it yourself if you change your mind. Never hand the number to the user;
- continuous facts (`low`, `mid`, `high`, `beatPhase`, `barPhase`, `structure.phase`) and discrete ones (`onset`, `accent`, the marks above) stay separate: volume-following is the trap this example exists to avoid;
- it stays seek-safe: `frame(t)` depends on `t` alone.

## What is not in the package

No audio, no assets, no palette, no style, no scene, no task. Ask the user (see `AGENT.md`) instead of assuming any of it exists. Exact field semantics: `references/schema.md`.
