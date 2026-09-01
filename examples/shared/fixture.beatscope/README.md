# BeatScope export

Files in this handoff:

- `rhythm-map.json` — versioned timing data: duration, BPM, origin, bars/beats, raw onsets, accents, low/mid/high energy, and sections.
- `beatscope-package.json` — machine-readable routing manifest: entry, probe, honest capabilities, exported function names, and sha256 integrity over every member.
- `AGENT.md` — the short Agent routing document; start there.
- `consumer-probe.js` — self-verification probe: `node consumer-probe.js .` checks every declared function and replays checkpoints when a checkpoint file is supplied.
- `visual-state.js` — pure `getVisualState(time)` plus, when visual artifacts are present, `getSceneState(time)` and `getBeatScopeFrame(time)`. No random state; safe to call after seek.
- `beatscope-runtime.js` — the shared runtime module `visual-state.js` builds on (`createTrack`).
- `worker-example.js` — ready-to-use module Worker adapter. The main thread sends audio time; the Worker returns deterministic timing and scene state.
- `scene-director.js` — the shared scene orchestrator behind `getSceneState` (seek-safe, deterministic).
- `visual-recipe.json` — compiled family identities: motif, palette slot, and composition channels per structural family.
- `visual-timeline.json` — those identities instantiated on the real song: scenes and boundary transitions in seconds.
- `visual-recipe-data.js` / `visual-timeline-data.js` — generated importable copies of the two JSON documents.
- `BEATSCOPE.md` — implementation handoff and timing invariants.
- `SKILL.md` — portable Codex skill for building a visual from this package.
- `references/schema.md` — exact field semantics for the skill.

The source audio is not copied into this package. Pair it with the original local file named `consumer-fixture`.
