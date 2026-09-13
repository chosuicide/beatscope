# Beathi Canvas — motion and interaction specification (v0.12 reference companion)

Status: **awaiting user approval** — companion to the four reference frames in
`build/beathi-references/` (outside Git). On approval this document is frozen
verbatim into Round 1 Commit 1 (`test(canvas): freeze Beathi Canvas design and
interaction contracts`). Source of truth: implementation plan §2.8, §2.9, §2.3.

## 1. Pan and zoom (infinite canvas)

- Camera state is `{x, y, zoom}` stored in workspace state (never in the
  direction document); one camera matrix transforms the DOM board layer. Zoom
  is clamped to `0.12..3.0`.
- Wheel without modifier pans 1:1, no easing, no inertia.
- Ctrl/Cmd+wheel zooms around the pointer; trackpad pinch routes through the
  same zoom-around-anchor function.
- Zoom invariant: `nextWorldUnderPointer == previousWorldUnderPointer` within
  `1e-6`; content never slips under the cursor.
- Zoom LOD (applies per board): below 28% color/title silhouette; 28–55%
  cached poster + title; above 55% full board controls. Board shadows render
  only above 35% zoom; below that a single outline replaces them.
- Connectors are SVG in the same world transform: 1 px base stroke, 1.5 px for
  the active (currently played) link; arrowheads appear only above 45% zoom.
- Camera moves animate a single transform (340 ms `--ease-settle`, see §6);
  pan/zoom from direct input never animates.

## 2. Selection

- Pointer Events with pointer capture; capture releases on cancel, blur,
  Escape and unmount.
- Click vs drag separation: drag intent begins after 4 px pointer travel; a
  click never starts a drag.
- Selection ring: 2 px accent outline plus a 6 px transparent interaction
  moat (no glow). Selection indicated by outline weight + 8 px corner handles
  (8 screen pixels via inverse scale), never by color alone.
- Ring appears within 120 ms `--ease-out` (shadow + outline-color only).
- Hovered unselected board: translateY(-1 px) max and shadow opacity change;
  **never** scale.
- Dock rows: 34 px, 8 px inset, 7 px radius; dragged rows become a 0.92
  opacity floating ghost with 1 px inner highlight, following the pointer
  without spring lag.

## 3. Magnetic response chains

- Attach gesture draws the connector toward the nearest valid port.
- Attach completes in 240 ms `--ease-settle`; target acknowledges with a
  single 1.015 scale pulse (spring overshoot cap: 2% of travel).
- Snap acquire/release: guides fade and grow from 80% length in 90/130 ms
  `--ease-out`; the board position itself stays under the pointer the whole
  time.
- Snap threshold: 7 screen px, converted to world units as `threshold / zoom`
  so snapping feels constant at every zoom level.
- Invalid targets never partially attach: validation happens before the
  connector animates.

## 4. Board activation in playback

- Live badge crosses between boards in 260 ms `--ease-out`
  (opacity + outline-color only); the badge never pulses while playing.
- Camera follows only when Follow is enabled; otherwise playback changes no
  camera state.
- Play button is a 32 px circle with a 1 px optically shifted glyph; no idle
  animation.
- Scrubbing makes the transport the authoritative time source; audio seeks
  once on pointer-up. Pointer-move never repeatedly calls play.
- Bar/beat readout and current scene sit on opposite sides of the time
  readout; all transport numerals use tabular figures.

## 5. Inspector and panel transitions

- Inspector content change: 160 ms out + 220 ms in; old content moves 4 px up,
  new enters from 6 px below. Editable values never crossfade.
- Panel collapse/expand: 220 ms `--ease-settle`, panel slides 12 px while
  content fades; the camera compensates so the focused board stays visually
  fixed.
- Panel resizing writes a CSS grid variable with no transition during the
  drag; only the final settle may animate.
- Nothing animates `top`/`left`/`width`/`height` during pointer interaction;
  shell motion uses transforms and opacity only.

## 6. Playback focus (camera)

- Board focus: 340 ms `--ease-settle` along the shortest zoom/pan path, one
  camera transform, no chained animations; interruptible at any moment by
  wheel or pointer.
- With `prefers-reduced-motion: reduce`: camera focus becomes a fade of
  ≤120 ms, scale/overshoot are removed, and only state-preserving opacity
  changes remain.
- Reduced transparency is an app setting (browsers do not expose it
  consistently): Level 2 glass surfaces fall back to opaque `--paper-1` at
  98%.

## 7. General timing contract

| Interaction | Duration | Curve | Notes |
|---|---|---|---|
| button press | 80 ms down / 140 ms up | `--ease-out` | translateY 1 px, scale 0.985 |
| panel collapse | 220 ms | `--ease-settle` | 12 px slide + fade, camera compensation |
| inspector content change | 160 out + 220 in | out/in | 4 px up / 6 px below, no value crossfade |
| board selection ring | 120 ms | `--ease-out` | shadow + outline-color |
| board focus camera | 340 ms | `--ease-settle` | shortest path, interruptible |
| snap acquire/release | 90 / 130 ms | `--ease-out` | guide opacity + length from 80% |
| response-chain attach | 240 ms | `--ease-settle` | 1.015 target acknowledgement |
| scene activation | 260 ms | `--ease-out` | live badge opacity + outline-color |
| popover / menu | 160 / 120 ms | out/in | 4 px translate + 0.985 scale, origin-aware, no bounce |
| toast stack | 400 ms | `--ease-settle` | height + Y interpolate, max 3 visible |

Standing rules: no idle floating/glowing/breathing in editor chrome;
pointer-down feedback within one frame (refs, not React round-trips); document
state commits on pointer-up; music artwork may be expressive, editor chrome
must feel weighted and precise.

## 8. Frame-specific notes (what each reference implies)

- **A · first run**: five boards in a loose left-to-right arc, board 01 live
  and largest, later boards recede through canvas placement scale (never CSS
  opacity); chronological links readable and crossing-free; 3-step non-modal
  coach in empty canvas space; transport is the strongest surface, project
  bar quiet; inspector collapsed.
- **B · overview**: 8–12 boards; repeated families share a tiny family mark
  (no color washes); selected (2 px outline + handles), playing (LIVE tag +
  filled play glyph), and hovered (-1 px lift + float shadow) are
  distinguishable without color; connection strokes vary only for
  current/selected; minimap lower-right above transport clearance; at 38%
  zoom boards show poster+title LOD without footers.
- **C · selected editing**: board at ~56% of usable height; dark authored
  composition is the darkest, highest-contrast area while chrome stays quiet;
  alignment guides carry world-space distance labels; crop bounds bracket the
  media slice; one response chain expanded with driver chips, operator,
  duration, combine rule and budget note.
- **D · prompt/package**: inspector at 400 px with structured summary
  (intent / scope / basis), diff groups "+2 added, ±1 changed, −0 removed"
  with scene/layer names, ghosted candidate overlay with before/after toggle,
  Apply as the only filled action, Reject as text, raw JSON as secondary
  disclosure, and the export checklist separating References / Included
  assets / Audio excluded.
