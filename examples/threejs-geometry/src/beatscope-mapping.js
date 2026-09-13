// BeatScope → Three.js mapping (plan section 11). Framework-specific and
// deliberately thin: it converts one timing state into plain scene properties
// and contains no beat mathematics and no Three.js objects, so it stays
// importable in Node for checkpoint parity tests.
//
// The direction below is authored here, in the example. The package reports
// measured facts — bands, phases, structure — and ships no scene, so every
// envelope the visuals need is written down in this file.

export const LEAD_SECONDS = 1.2; // how early a structural boundary starts to show
export const SETTLE_SECONDS = 0.9; // how long an arrival takes to settle
export const HIT_SECONDS = 0.12; // how long a transient keeps its impulse

/** Authored direction derived from the measured facts. */
export function direction(state) {
  const structure = state.structure || null;
  const span = structure ? Math.max(1e-6, structure.endTime - structure.startTime) : 1;
  const sinceBoundary = structure ? structure.phase * span : 0;
  const toBoundary = structure && Number.isFinite(structure.secondsToBoundary)
    ? structure.secondsToBoundary
    : Infinity;
  const approach = Math.max(0, Math.min(1, 1 - toBoundary / LEAD_SECONDS));
  const settle = Math.max(0, 1 - sinceBoundary / SETTLE_SECONDS);
  const accent = state.accent && state.accent.value ? state.accent.value : 0;
  const impulse = Math.max(0, 1 - sinceBoundary / HIT_SECONDS) * accent;
  return {
    twist: Math.sin(state.barPhase * Math.PI * 2) * 0.32,
    flow: 0.3 + state.low * 0.5,
    contrast: 0.45 + state.high * 0.35,
    paletteMix: Math.max(approach, settle),
    transition: {
      stage: approach > 0 ? "approach" : settle > 0 ? "settle" : "idle",
      approach,
      cross: approach * (1 - approach) * 2,
      settle,
      impulse,
    },
  };
}

export function mapFrame(state, time) {
  const authored = direction(state);
  return {
    scale: 1 + state.low * 0.25,
    twist: authored.twist,
    transition: authored.transition.cross,
    cameraPhase: time * 0.08,
  };
}

/**
 * Scene palette from the measured structure family (neutral A/B/C letters).
 * Unknown families fall back to the neutral colour.
 */
const FAMILY_COLORS = Object.freeze({
  A: 0x76d4e8,
  B: 0x9aa7ff,
  C: 0xd6f4ff,
});
const NEUTRAL_COLOR = 0x76d4e8;

export function familyColor(state) {
  const family = state.structure ? state.structure.family : null;
  return FAMILY_COLORS[family] ?? NEUTRAL_COLOR;
}

/**
 * Boundary ease for the point material: the authored mix softens opacity at
 * segment boundaries, and reduced motion halves that easing.
 */
export function pointOpacity(state, reducedMotion = false) {
  const authored = direction(state);
  const base = 0.6 + authored.contrast * 0.35;
  const mix = authored.paletteMix;
  return base * (1 - (reducedMotion ? mix * 0.5 : mix));
}
