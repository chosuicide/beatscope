// Planar particle field — an authored geometry mapping for the Canvas
// reference consumer. Pure and seek-safe: every value is a function of
// particle identity, the current timing state, and the canvas size.
// No random state, no accumulated frame count, no wall clock.
//
// This module contains no beat mathematics: all timing facts arrive via
// getVisualState, and the direction below is authored here, in the example.
// It is example code, not a BeatScope SDK.

export const FIELD_COLUMNS = 56;
export const FIELD_ROWS = 30;

/** Deterministic per-identity hash in [0, 1); replaces Math.random. */
export function hash01(a, b) {
  let h = Math.imul(a, 0x27d4eb2d) ^ Math.imul(b, 0x165667b1);
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

/** The fixed particle identities; a pure function of the grid indices. */
export function createParticleField(columns = FIELD_COLUMNS, rows = FIELD_ROWS) {
  const particles = [];
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const index = row * columns + column;
      particles.push({
        index,
        u: (column + 0.5) / columns,
        v: row / (rows - 1),
        jitter: hash01(index, 7),
        drift: hash01(index, 31),
        sparkle: hash01(index, 101) < 0.06,
      });
    }
  }
  return particles;
}


/**
 * Authored direction. The package reports measured facts — bands, phases,
 * transients, structure — and this example turns them into the composition
 * channels its geometry expects. These numbers are the example's own choices:
 * the package ships no scene, no palette and no transition envelope, by design.
 */
const LEAD_SECONDS = 1.2; // how long before a boundary the plane starts to open
const SETTLE_SECONDS = 0.9; // how long an arrival takes to settle back
const HIT_SECONDS = 0.12; // how long a transient keeps its impulse

export function directionFor(state) {
  const structure = state.structure || null;
  const span = structure ? Math.max(1e-6, structure.endTime - structure.startTime) : 1;
  const sinceBoundary = structure ? structure.phase * span : 0;
  const toBoundary = structure && Number.isFinite(structure.secondsToBoundary)
    ? structure.secondsToBoundary
    : Infinity;
  const approach = Math.max(0, Math.min(1, 1 - toBoundary / LEAD_SECONDS));
  const settle = Math.max(0, 1 - sinceBoundary / SETTLE_SECONDS);
  const onset = state.onset && state.onset.value ? state.onset.value : 0;
  const accent = state.accent && state.accent.value ? state.accent.value : 0;
  const impulse = Math.max(0, 1 - sinceBoundary / HIT_SECONDS) * Math.max(onset, accent);
  return {
    composition: {
      spread: 0.16 + state.mid * 0.26, // mid band widens the plane
      twist: Math.sin(state.barPhase * Math.PI * 2) * 0.32, // one slow turn per bar
      flow: 0.3 + state.low * 0.5, // low band sets the wave speed
      orbit: structure ? structure.phase : 0, // progress through the segment
      void: approach * 0.35, // the gap opens as a boundary approaches
      contrast: 0.45 + state.high * 0.35, // high band lifts contrast
      paletteMix: Math.max(approach, settle), // bounded colour shift at boundaries
    },
    transition: {
      stage: approach > 0 ? "approach" : settle > 0 ? "settle" : "idle",
      approach,
      cross: 0,
      settle,
      impulse,
    },
    onset,
    accent,
  };
}

function frameInputs(state) {
  const direction = directionFor(state);
  return {
    timing: state,
    composition: direction.composition,
    transition: direction.transition,
    onset: direction.onset,
    accent: direction.accent,
  };
}

/**
 * Motion-free layout: the plane projection (spread widens it, twist
 * rotates it). Everything that moves with music is displacement on top
 * of this, so reduced motion can scale displacement without touching
 * layout.
 */
export function particleLayout(field, state, size) {
  const { composition } = frameInputs(state);
  const centerX = size.width / 2;
  const centerY = size.height * 0.42;
  const layout = new Array(field.length);
  for (let i = 0; i < field.length; i += 1) {
    const particle = field[i];
    const depthScale = 1 - particle.v * 0.45;
    const planeX = (particle.u - 0.5) * size.width * (0.72 + composition.spread * 0.45) * depthScale;
    const planeY = size.height * (0.3 + particle.v * 0.55);
    const twist = composition.twist * 0.35;
    const cosTwist = Math.cos(twist);
    const sinTwist = Math.sin(twist);
    layout[i] = {
      x: planeX * cosTwist - planeY * sinTwist + centerX,
      y: planeX * sinTwist + planeY * cosTwist + centerY,
      depth: particle.v,
    };
  }
  return layout;
}

/**
 * Screen-space points for one media-time state. The same (field, state,
 * size, reducedMotion) always yields the same points, so pause, seek,
 * and replay render identical geometry. Every displacement term is
 * linear in one motion factor (1, or 0.25 under reduced motion), so
 * reduced motion scales the displacement vector exactly and leaves the
 * layout, depth, and timing state unchanged.
 */
export function particlePoints(field, state, size, reducedMotion = false) {
  const { timing, composition, transition, onset, accent } = frameInputs(state);
  const motion = reducedMotion ? 0.25 : 1;
  const envelope = transition ? transition.settle + transition.approach * 0.5 : 0;
  const pop = transition ? transition.impulse * 0.25 * motion : 0;
  const wavePhase = timing.time * (0.35 + composition.flow * 0.5) + composition.orbit * Math.PI;
  const centerX = size.width / 2;
  const centerY = size.height * 0.42;
  const layout = particleLayout(field, state, size);
  const points = new Array(field.length);
  for (let i = 0; i < field.length; i += 1) {
    const particle = field[i];
    const base = layout[i];
    const depthScale = 1 - particle.v * 0.45;

    // Mid band bends the plane along the flow direction; low band drives
    // a standing wave across each row. Both are pure functions of time.
    let dx = Math.sin(particle.v * Math.PI * 1.6 + wavePhase) * composition.flow * 18;
    let dy = Math.sin(particle.u * Math.PI * 4 + wavePhase * 0.8) * (4 + timing.low * 42);

    // Onset impulse: a short local ripple, jittered per particle so the
    // field scatters instead of translating. Accent: one coherent lift.
    const ripple = onset * (8 + particle.jitter * 30);
    dx += (particle.drift - 0.5) * 2 * ripple;
    dy -= ripple * 0.6;
    dy -= accent * 20;

    // void clears a breathing gap around the field centre, pushed along
    // the motion-free layout direction so displacement stays linear.
    const vx = base.x - centerX;
    const vy = base.y - centerY;
    const distance = Math.sqrt(vx * vx + vy * vy) || 1;
    const push = composition.void * 90 * (1 - Math.min(1, distance / (size.width * 0.4)));
    dx += (vx / distance) * push;
    dy += (vy / distance) * push;

    const x = base.x + dx * motion;
    const y = base.y + dy * motion;

    let radius = (1.1 + particle.jitter * 1.7) * depthScale * (1 + timing.low * 0.8 + accent * 1.1);
    radius *= 1 + pop;
    let alpha = (0.2 + (1 - particle.v) * 0.32) * (0.7 + composition.contrast * 0.6);
    alpha *= 1 - envelope * 0.3;
    if (particle.sparkle) alpha = Math.min(1, alpha + timing.high * 0.55);

    points[i] = { x, y, radius, alpha, depth: particle.v, sparkle: particle.sparkle };
  }
  return points;
}

/**
 * Family palettes for the reference field. Family identity comes from the
 * measured structure segment (neutral A/B/C labels); unknown families fall
 * back to the neutral slate. The authored envelope eases the tones toward the
 * family accent at segment boundaries.
 */
const FAMILY_PALETTES = Object.freeze({
  A: Object.freeze(["#232833", "#5d7d8f", "#cfdde2"]),
  B: Object.freeze(["#2e2018", "#a8613c", "#f0bd8c"]),
  C: Object.freeze(["#241f2e", "#6f5f8f", "#d8cfdd"]),
});
const NEUTRAL_PALETTE = FAMILY_PALETTES.A;

export function familyPalette(family) {
  return FAMILY_PALETTES[family] || NEUTRAL_PALETTE;
}

function blendHex(a, b, mix) {
  const parse = (hex) => [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
  const ca = parse(a);
  const cb = parse(b);
  const clamped = Math.max(0, Math.min(1, mix));
  return `rgb(${Math.round(ca[0] + (cb[0] - ca[0]) * clamped)}, ${Math.round(
    ca[1] + (cb[1] - ca[1]) * clamped,
  )}, ${Math.round(ca[2] + (cb[2] - ca[2]) * clamped)})`;
}

/**
 * Palette for one frame. The family comes from the measured structure segment
 * (`state.structure.family`), and the authored boundary envelope eases the
 * background and highlight tones toward the family accent — a bounded colour
 * shift that stays a pure function of the frame.
 */
export function framePalette(state) {
  const family = state && state.structure ? state.structure.family : null;
  if (!family) return NEUTRAL_PALETTE.slice();
  const current = familyPalette(family);
  const paletteMix = directionFor(state).composition.paletteMix;
  if (!paletteMix) return current.slice();
  return [
    blendHex(current[0], current[1], paletteMix * 0.5),
    current[1],
    blendHex(current[2], current[1], paletteMix * 0.5),
  ];
}
