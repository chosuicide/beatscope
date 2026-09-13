// Pure state for the Remotion reference composition. The React tree only
// renders this object; all musical facts come from the handoff package's
// timing API. No wall clock, no audio element, no requestAnimationFrame —
// the clock is frame / fps (plan section 12).
//
// The package ships facts, not a scene: the direction below (boundary
// envelopes, composition channels) is authored here, in the example.
import { getVisualState, RHYTHM_MAP } from "../../shared/fixture.beatscope/visual-state.js";

export const DURATION_SECONDS = RHYTHM_MAP.duration;

const LEAD_SECONDS = 1.2; // how early a structural boundary starts to show
const SETTLE_SECONDS = 0.9; // how long an arrival takes to settle
const HIT_SECONDS = 0.12; // how long a transient keeps its impulse

/** The Remotion clock rule: a frame index becomes media time via fps. */
export function frameTime(frame, fps, startFrame = 0) {
  return Math.max(0, (frame - startFrame) / fps);
}

/** Total composition length in frames for a target fps. */
export function compositionDuration(fps) {
  return Math.ceil(DURATION_SECONDS * fps);
}

/** Authored direction derived from the measured facts. */
function direction(facts) {
  const structure = facts.structure || null;
  const span = structure ? Math.max(1e-6, structure.endTime - structure.startTime) : 1;
  const sinceBoundary = structure ? structure.phase * span : 0;
  const toBoundary = structure && Number.isFinite(structure.secondsToBoundary)
    ? structure.secondsToBoundary
    : Infinity;
  const approach = Math.max(0, Math.min(1, 1 - toBoundary / LEAD_SECONDS));
  const settle = Math.max(0, 1 - sinceBoundary / SETTLE_SECONDS);
  const accent = facts.accent && facts.accent.value ? facts.accent.value : 0;
  return {
    composition: {
      spread: 0.16 + facts.mid * 0.26,
      twist: Math.sin(facts.barPhase * Math.PI * 2) * 0.32,
      flow: 0.3 + facts.low * 0.5,
      orbit: structure ? structure.phase : 0,
      void: approach * 0.35,
      contrast: 0.45 + facts.high * 0.35,
      paletteMix: Math.max(approach, settle),
    },
    transition: {
      stage: approach > 0 ? "approach" : settle > 0 ? "settle" : "idle",
      approach,
      cross: approach * (1 - approach) * 2,
      settle,
      impulse: Math.max(0, 1 - sinceBoundary / HIT_SECONDS) * accent,
    },
  };
}

/**
 * One serializable state object per media time. Rendering frame N twice
 * yields deep-equal state: the same second maps to the same state at any
 * fps because time is the only input.
 *
 * Scene ownership freezes on the final segment (the scene facts are sampled at
 * the duration), while the timing facts keep extrapolating past the grid — the
 * documented D6 behaviour.
 */
export function sceneState(time) {
  const seconds = Math.max(0, time);
  const facts = getVisualState(seconds);
  const frozen = seconds > DURATION_SECONDS ? getVisualState(DURATION_SECONDS) : facts;
  const structure = frozen.structure || null;
  const authored = direction(frozen);
  return {
    time: seconds,
    scene: {
      id: structure ? structure.id : "all",
      family: structure ? structure.family : "A",
      variant: structure ? structure.variant : 0,
      phase: structure ? structure.phase : 0,
    },
    transition: { ...authored.transition },
    composition: { ...authored.composition },
    timing: {
      low: facts.low,
      mid: facts.mid,
      high: facts.high,
      beatPhase: facts.beatPhase,
      barPhase: facts.barPhase,
      accent: facts.accent && facts.accent.value ? facts.accent.value : 0,
    },
  };
}
