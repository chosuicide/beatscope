---
name: beatscope-visualizer
description: Build deterministic audio-reactive web, video, or motion visuals from a BeatScope export package.
---

# BeatScope visualizer handoff

Use this skill when a BeatScope export package is provided for an audio-reactive visual. Read `BEATSCOPE.md`, then inspect `rhythm-map.json` and `visual-state.js` before writing visual code.

## Timing contract

- Do not re-analyse the audio. The exported timing and energy data are the inspected facts.
- Make `audio.currentTime` the only clock. When the package carries `visual-recipe.json`, call `getBeatScopeFrame(audio.currentTime)` on each render — it returns `{ timing, scene }` from one call. Otherwise sample `getVisualState(audio.currentTime)`.
- Keep visuals seek-safe and pause-safe: the same time must produce the same frame, with no wall-clock drift, hidden timers, or non-reproducible random state.
- Timing state and scene state are separate surfaces: `getVisualState(time)` reports rhythm facts (bar, beat, energy, impulses); `getSceneState(time)` reports the structural visual scene. Never merge them into one ad-hoc state object.
- Use the export's `duration`, `bpm`, `origin`, `beats`, `onsets`, `energy`, and `sections` as available; when the map carries `patterns.segments`, those are the whole-song structure facts. Gracefully handle missing optional arrays.

## Scene contract (v0.8)

When `visual-recipe.json` and `visual-timeline.json` are present, `getSceneState(time)` returns the compiled scene. Rules:

- Family identity must persist across repetitions: every occurrence of family `A` wears the same motif and palette slot. `variant` means controlled visual variation of that identity (bounded `variant_delta`), never a different musical role.
- Respect the recipe tokens before inventing new ones: the palette, transition timing (`lead_beats`, `settle_beats`), and motion limits (`max_scene_spread`, `max_scene_twist`, `max_palette_mix`) are the design budget.
- `scene.transition` reports `stage` (`approach`, `cross`, `settle`, `idle`) with envelopes already scaled by the transition's `lead_seconds`/`settle_seconds`. The transition `driver` selects the treatment (`phase-turn`, `radial-part`, `aperture`, `flow-shear`, or the neutral cross-settle); it describes why the boundary exists, not an emotion. Do not label boundaries with feelings.
- Do not animate every property at every boundary. Pick at most two channels (for example spread + contrast) and let the envelopes drive them.
- Keep all extra motion seek-safe: derive everything from `getSceneState(audio.currentTime)` the same way every frame.
- Preserve reduced-motion behavior: honor `prefers-reduced-motion` and pass `{ reducedMotion: true }` to `getSceneState` so envelopes collapse to their calm form.
- Never rename the neutral `A`/`B`/`A′` families without explicit user instruction.

## Motion mapping

Use `low` for scale or weight, `mid` for surface motion, and `high` for light or fine detail. Use `onset` and `accent` for short impact impulses, `beatPhase` and `barPhase` for repeatable breathing, and `section` for larger composition changes. Treat these as rhythm-strength signals, not instrument identity: do not claim a signal is a kick, snare, or 808.

When `patterns.segments` exists, treat it as the whole-song form:

- Drive scene-level changes (palette, layout, framing) from segment boundaries; keep moment-level motion on beats and onsets.
- `family` (`A`, `B`, ...) marks recurrence, not musical role: equal families repeat the same material. `variant` marks a passage related to its family but audibly changed — keep a variant's scene related to its family's scene instead of inventing a new one.
- Never rename `A`/`B` to Verse/Chorus or any other section name without the user's instruction; the letters are deliberately neutral.
- `state.structure` from `getVisualState(time)` reports the current segment (`id`, `family`, `variant`, `label`, `index`), its `phase`, and `secondsToBoundary`; the shared runtime also exposes `track.structureLead` and `track.boundaryImpulse` for approach and arrival emphasis. Derive transitions from these rather than re-parsing the JSON per frame.

## Minimal example (no build system)

```html
<script type="module">
  import { getBeatScopeFrame } from './visual-state.js';
  const circle = document.querySelector('#pulse');
  function render() {
    const frame = getBeatScopeFrame(audio.currentTime);
    circle.setAttribute('r', 20 + frame.timing.low * 30);
    requestAnimationFrame(render);
  }
  render();
</script>
```

## Advanced example (scene-driven composition)

```html
<script type="module">
  import { getBeatScopeFrame } from './visual-state.js';
  function render() {
    const { timing, scene } = getBeatScopeFrame(audio.currentTime, {
      reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
    });
    // Scene composition channels are pre-interpolated across boundaries;
    // onsets stay moment-level. Two channels at a boundary, no more.
    const spread = scene ? scene.composition.spread : 0.14;
    const approach = scene ? scene.transition.approach : 0;
    stage.style.setProperty('--spread', String(spread + timing.onset * 0.05));
    stage.style.setProperty('--settle', String(approach));
    requestAnimationFrame(render);
  }
  render();
</script>
```

Keep controls accessible and make pause, replay, and arbitrary seek work without special cases. Read [`references/schema.md`](references/schema.md) when exact field semantics are needed.
