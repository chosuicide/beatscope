/**
 * Motion engine types.
 *
 * Outputs are presentation values derived from authored bases; the evaluator
 * never mutates the direction document and never serializes editor state.
 * Every value is a pure function of media time — no wall-clock, ticker delta
 * or accumulated state is allowed anywhere in this module graph.
 */
import type { DirectionScene, TransitionKind } from '../direction/types';

/** Evaluated layer output. All fields are deltas from the authored base. */
export interface LayerOutput {
  /** multiplicative scale around 1 */
  scale: number;
  /** reference-pixel translation */
  translate: { x: number; y: number };
  /** additive degrees */
  rotation: number;
  /** multiplier on the authored opacity */
  opacity: number;
  /** 0..1 inset progress (crop/reveal) */
  crop: number;
  /** -1..1 horizontal strip offset */
  strip: number;
  /** blur radius in reference pixels */
  blur: number;
  /** 0..1 palette inversion influence (boolean-crossing at 0.5) */
  invert: number;
}

export const BASE_OUTPUT: LayerOutput = Object.freeze({
  scale: 1,
  translate: Object.freeze({ x: 0, y: 0 }),
  rotation: 0,
  opacity: 1,
  crop: 0,
  strip: 0,
  blur: 0,
  invert: 0,
});

/** Mutable accumulator the operator registry writes into. */
export interface ChannelAccumulator {
  scale: number;
  tx: number;
  ty: number;
  rotation: number;
  opacityLift: number;
  opacityFade: number;
  crop: number;
  strip: number;
  blur: number;
  invert: number;
}

export function freshAccumulator(): ChannelAccumulator {
  return {
    scale: 1,
    tx: 0,
    ty: 0,
    rotation: 0,
    opacityLift: 0,
    opacityFade: 0,
    crop: 0,
    strip: 0,
    blur: 0,
    invert: 0,
  };
}

export const CHANNEL_BOUNDS = Object.freeze({
  translate: 40, // reference px
  rotation: 12, // degrees
  scaleMin: 0.25,
  scaleMax: 4,
  strip: 1,
  blur: 12, // reference px
});

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/**
 * Convert the accumulator into the frozen output contract.
 *
 * Opacity responses blend between the authored resting opacity and the
 * operator's target: a lift can only brighten headroom that exists, a fade
 * dims from the authored base. Both are therefore meaningful only relative
 * to the authored value, never as absolute overrides.
 */
export function finalizeOutput(acc: ChannelAccumulator, baseOpacity = 1): LayerOutput {
  const lift = clamp(acc.opacityLift, 0, 1);
  const fade = clamp(acc.opacityFade, 0, 1);
  const rest = clamp(baseOpacity, 0, 1);
  return {
    scale: clamp(acc.scale, CHANNEL_BOUNDS.scaleMin, CHANNEL_BOUNDS.scaleMax),
    translate: {
      x: clamp(acc.tx, -CHANNEL_BOUNDS.translate, CHANNEL_BOUNDS.translate),
      y: clamp(acc.ty, -CHANNEL_BOUNDS.translate, CHANNEL_BOUNDS.translate),
    },
    rotation: clamp(acc.rotation, -CHANNEL_BOUNDS.rotation, CHANNEL_BOUNDS.rotation),
    opacity: clamp(rest + (1 - rest) * lift - rest * fade, 0, 1),
    crop: clamp(acc.crop, 0, 1),
    strip: clamp(acc.strip, -CHANNEL_BOUNDS.strip, CHANNEL_BOUNDS.strip),
    blur: clamp(acc.blur, 0, CHANNEL_BOUNDS.blur),
    // boolean-like inversion: highest influence crossing 0.5, deterministic
    invert: acc.invert >= 0.5 ? 1 : clamp(acc.invert, 0, 1),
  };
}

export interface TransitionState {
  kind: TransitionKind;
  fromSceneId: string;
  toSceneId: string | null;
  progress: number;
  duration: number;
}

export interface DirectionState {
  scene: DirectionScene;
  sceneIndex: number;
  time: number;
  transition: TransitionState | null;
  layers: Map<string, LayerOutput>;
}
