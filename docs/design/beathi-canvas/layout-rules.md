# Beathi Canvas layout rules (frozen)

Responsive and layout contract for the React shell. Values here mirror
`design-tokens.json` and the frozen reference frames; deviations fail the
snapshot harness.

## Frame structure

- Full-screen editor shell; the page never scrolls at or above 1280×720.
- Fixed chrome: top bar 48 px; floating transport 68 px total (52 px inner
  column + 8 px glass padding, bottom margin 20 px, horizontally centered).
- Panels: left dock 280 px, right inspector 320 px, prompt/package inspector
  400 px. Collapsed panels become 52 px icon rails with a vertical label.
- The infinite canvas always keeps the majority of the width.
- Reference stage widths at 1440×900: A `1440−280−52 = 1108`,
  B `1440−52−52 = 1336`, C `1440−280−320 = 840`, D `1440−280−400 = 760`.

## Viewports

- Design and snapshot viewports: **1440×900** (primary) and **1920×1080**.
- Below 1280 px width both panels auto-collapse to rails (canvas ≥ 70% width).
- Chrome never reflows between the two snapshot viewports; only the canvas
  viewport grows. Frozen references are authored at 1440×900 and centered
  when captured at 1920×1080.

## Stacking scale (z)

`canvas 0 → boards 10 → panels 30 → transport 40 → popover 50 → toast 60 →
dialog 70`. Nothing may use an ad-hoc z-index outside this scale.

## Canvas behavior (§2.9)

- Camera `{x, y, zoom}` clamped to zoom 0.12–3.0. Wheel pans; Ctrl/Cmd+wheel
  zooms around the pointer with focal-point drift ≤ 1e-6.
- Snap threshold 7 px screen-space (divided by zoom in world units) against
  canvas edges/centers and sibling bounds.
- Connectors: SVG path, 1 px base / 1.5 px active stroke; arrowheads render
  only above 45% zoom. Chronology links cannot be rewired.
- Handles stay 8 screen px via inverse scale. Board shadows appear above 35%
  zoom. Hover = −1 px translate + shadow, never scale. Selection = 2 px
  accent outline with 6 px moat, no glow.
- LOD: < 28% silhouette; 28–55% poster + title; > 55% full controls.

## Motion contract (§2.8, see motion-spec.md)

- Buttons 80/140 ms in/out; panels collapse 220 ms settle with camera
  compensation; inspector content 160 ms out / 220 ms in; selection ring
  120 ms; board focus camera 340 ms settle (shortest-path, interruptible);
  snap 90/130 ms; chain attach 240 ms + 1.015 ack; scene activation 260 ms;
  popover 160/120 ms; toast 400 ms; ≤ 3 toasts visible.
- During pointer interaction only transforms/opacity animate; never
  top/left/width/height.
- Reduced motion: fades ≤ 120 ms; reduced transparency is an app setting.

## Surfaces

- Light editor theme only in v0.12. Lilac `#7567E8` reserved for focus,
  selection and active links. No purple/blue gradients in chrome; gradients
  are permitted only inside authored scene artwork.
- Glass blur restricted to floating transport, transient menus/popovers and
  active controls. Never blur boards, canvas content or inspector rows.
- Radii: inner controls 6–8 px, floating panels 12–16 px.
- Paper grain: single fixed SVG turbulence overlay ≤ 2% alpha on the canvas.
