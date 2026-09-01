// BeatScope → Three.js mapping (plan section 11). Framework-specific and
// deliberately thin: it converts one BeatScope frame into plain scene
// properties and contains no beat mathematics and no Three.js objects,
// so it stays importable in Node for checkpoint parity tests.

export function mapFrame(frame, time) {
  const timing = frame.timing;
  const scene = frame.scene || null;
  return {
    scale: 1 + timing.low * 0.25,
    twist: scene?.composition?.twist ?? 0,
    transition: scene?.transition?.cross ?? 0,
    cameraPhase: time * 0.08,
  };
}

/**
 * Scene palette from the neutral family identity. The scene frame does
 * not expose the incoming family, so boundary paletteMix eases the
 * emission intensity instead of pretending to know the next palette.
 */
const FAMILY_COLORS = Object.freeze({
  A: 0x5d7d8f,
  B: 0xa8613c,
  C: 0x6f5f8f,
});
const NEUTRAL_COLOR = 0x5d7d8f;

export function familyColor(frame) {
  const family = frame.scene?.family;
  return FAMILY_COLORS[family] ?? NEUTRAL_COLOR;
}

/**
 * Boundary ease for the point material: paletteMix softens opacity at
 * scene boundaries instead of claiming to know the incoming palette.
 */
export function pointOpacity(frame, reducedMotion = false) {
  const composition = frame.scene?.composition;
  const mix = composition ? composition.paletteMix ?? 0 : 0;
  const base = composition ? 0.6 + composition.contrast * 0.35 : 0.7;
  return base * (1 - (reducedMotion ? mix * 0.5 : mix));
}
