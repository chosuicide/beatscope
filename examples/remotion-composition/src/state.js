// Pure state for the Remotion reference composition. The React tree only
// renders this object; all musical facts come from the handoff package's
// frame API. No wall clock, no audio element, no requestAnimationFrame —
// the clock is frame / fps (plan section 12).
import { getBeatScopeFrame, RHYTHM_MAP } from "../../shared/fixture.beatscope/visual-state.js";

export const DURATION_SECONDS = RHYTHM_MAP.duration;

/** The Remotion clock rule: a frame index becomes media time via fps. */
export function frameTime(frame, fps, startFrame = 0) {
  return Math.max(0, (frame - startFrame) / fps);
}

/** Total composition length in frames for a target fps. */
export function compositionDuration(fps) {
  return Math.ceil(DURATION_SECONDS * fps);
}

/**
 * One serializable state object per media time. Rendering frame N twice
 * yields deep-equal state: the same second maps to the same BeatScope
 * state at any fps because time is the only input.
 */
export function sceneState(time) {
  // clamp: true keeps the final scene at phase 1 beyond its end, so the
  // last rendered frames freeze instead of losing scene ownership.
  const frame = getBeatScopeFrame(Math.max(0, time), { clamp: true });
  const timing = frame.timing;
  const scene = frame.scene;
  return {
    time: Math.max(0, time),
    scene: {
      id: scene.scene.id,
      family: scene.scene.family,
      variant: scene.scene.variant,
      phase: scene.scene.phase,
    },
    transition: {
      stage: scene.transition.stage,
      approach: scene.transition.approach,
      cross: scene.transition.cross,
      settle: scene.transition.settle,
      impulse: scene.transition.impulse,
    },
    composition: { ...scene.composition },
    timing: {
      low: timing.low,
      mid: timing.mid,
      high: timing.high,
      beatPhase: timing.beatPhase,
      barPhase: timing.barPhase,
      accent: timing.accent && timing.accent.value ? timing.accent.value : 0,
    },
  };
}
