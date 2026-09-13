# Capability migration ledger — Studio v0.11 → Beathi Canvas

Commit 1 record required by the v0.12 plan: every user capability that exists
in the shipped v0.11 Studio (`beatscope/web` static UI + Python backend) must
either survive the Round 1 Commit 2 shell replacement or have an explicit,
recorded transition. Nothing may disappear silently.

| # | Capability in v0.11 Studio | Disposition in v0.12 Beathi Canvas |
|---|---|---|
| 1 | Local audio intake: drop/choose file, processed locally | Kept. "New audio" in the top bar opens the intake flow in a side sheet (§2.3). Local Studio capability adapter only; hidden in static demo. |
| 2 | Supported audio formats: WAV / FLAC / MP3 / OGG / M4A | Kept unchanged; the same backend analysis path runs. |
| 3 | Analysis progress display with cancel | Kept. Progress renders as progressive placeholder boards on the canvas; cancel aborts the same backend job. Semantic structure boards appear only after validated structure data exists (§2.3). |
| 4 | Track facts panel: BPM, bar count, duration, analysis backend | Kept. Facts surface in the inspector/top-bar area, sourced from Rhythm IR only; never user-editable. |
| 5 | Playback: play/pause, seek, ±5 s nudge, volume | Kept via the floating transport (§2.1), driven by the existing playback service adapter. |
| 6 | Loop range: loop 8 bars, set/clear loop | Kept on the transport; loop range remains time-exact against measured beats. |
| 7 | Timecode / bar-beat readout | Kept in transport readouts using tabular figures and the bundled mono face. |
| 8 | Signal player (particle stage) | Retired after migration. The single Pixi compositor replaces it; the particle renderer is never resurrected as a WebGL-loss fallback (§3.2 — cached posters + "Live preview unavailable" instead). |
| 9 | Rhythm overview canvas | Kept as evidence, not as a separate screen: measured onsets/energy feed drivers and the chronology strip; the old canvas is not an active route. |
| 10 | 8-bar cue map: 1/16–1/32 cell switch, click-to-preview, drag select, cell details (raw/grid/shift/strength/bands) | Kept. Accessible from the evidence view feeding drivers (§4.4 low/mid/high evidence views); cell semantics and preview behavior unchanged. |
| 11 | Structure navigation Shift+←/→ | Kept and extended (§5.1): Shift+←/→ moves by structural scene; plain ←/→ keep existing time navigation semantics. |
| 12 | WebMCP tool `get_project_context` | Kept frozen. Registered through the agent bridge; semantics unchanged (§7.1). |
| 13 | WebMCP tool `get_state_at_time` | Kept frozen; the direction runtime now backs `getDirectionState`, while the original timing-state semantics remain available (§7.3 compatibility window). |
| 14 | WebMCP tool `get_events` | Kept frozen. |
| 15 | WebMCP tool `find_visual_moments` | Kept frozen. |
| 16 | WebMCP tool `compare_ranges` | Kept frozen. |
| 17 | WebMCP tool `focus_range` | Kept frozen. |
| 18 | WebMCP tool `control_playback` | Kept frozen; drives the same transport service. |
| 19 | WebMCP tool `set_loop_range` | Kept frozen; drives the same transport service. |
| 20 | Agent focus display | Kept. The selected-scene/agent-focus state feeds the three new direction tools (`beatscope_get_direction_context`, `beatscope_get_direction_state`, `beatscope_propose_direction_patch`). |
| 21 | Agent actions ledger + undo | Kept and generalized: one chronological command history (cap 100) whose entries declare targets; Agent Apply is one composite undoable command (§3.6, §7.1). |
| 22 | Codex package export: rhythm-map.json, visual-state.js, beatscope-runtime.js, BEATSCOPE.md, SKILL.md | Kept byte-compat for v0.12 consumers; extended with direction files per §7.2 (`beatscope-direction.json`, `direction-data.js`, `direction-runtime.js`, `direction-probe.js`, `DIRECTION.md`, `AGENT.md`, optional assets/reference.png, v0.12-compat visual-recipe.json/visual-timeline.json). |
| 23 | Advanced exports: MIDI, CSV, PNG, project JSON | Kept. PNG additionally gains the deterministic per-scene storyboard contact sheet (§8.1). |
| 24 | Bundled demo project (beatscope/web/demo with audio.mp3) | Replaced by the licensed first-run demo: a repository-owned synthetic "Beyond the Fog" project (direction document + generated editorial-collage media), no third-party audio. Static-demo capability adapter per §3.7. |
| 25 | Keyboard: Space play, double-click focus, F fit selection, 0 fit all | Kept/extended as the canvas interaction spec (§5.1). |
| 26 | No `alert()` — inline, actionable errors | Kept and extended to the new status stack and boot-state error surfaces (`ready`/`read-only-demo`/`conflict`/`fatal` §3.5). |

## Retirement notes (explicit, not silent)

- **Particle signal player (row 8):** its visual role is superseded by the
  `graphic-field` layer system on the new canvas. The v0.11 renderer code
  remains in the repository until the separately approved v0.13 cleanup, but
  is no longer an active route and is never a fallback renderer.
- **Bundled demo audio (row 24):** `demo/audio.mp3` (third-party audio) is
  replaced by the deterministic, repository-owned synthetic demo. No
  copyrighted audio enters Git (standing constraint from the v0.11 plan).
- **Old shell (rows 1–26 as a surface):** the orange-accent Studio UI stops
  being an active route at Commit 2; all capabilities above are reachable
  through the Beathi Canvas shell before the route removal is committed.

## Verification hook

Round 1's stop gate (user acceptance of implemented views against the frozen
references) must include a pass over this ledger: for every "Kept" row, name
the surface where it now lives. Rows marked "Retired/Replaced" must show the
replacement and the absence of the old route.
