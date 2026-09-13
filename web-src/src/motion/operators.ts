/**
 * Motion operator registry (plan §4.4/§4.8). Every operator declares one
 * combine mode and one channel; overlapping responses accumulate with
 * bounded, deterministic rules — additive sums then clamps, multiplicative
 * multiplies deltas around 1, max keeps the strongest influence, boolean
 * uses the highest influence crossing 0.5. Order is response-array order,
 * never UI rendering order.
 */
import type { MotionSpec } from '../direction/types';
import type { ChannelAccumulator } from './types.js';
import { seededNoise } from './noise.js';

export type CombineMode = 'additive' | 'multiplicative' | 'max' | 'boolean';
export type MotionChannel = 'translate' | 'scale' | 'rotation' | 'opacity' | 'crop' | 'strip' | 'blur' | 'invert';

export interface OperatorContext {
  /** stable identity: project_id + scene_id + layer_id */
  seedKey: string;
  /** explicitly quantized presentation sample index */
  sample: number;
}

export interface MotionOperatorDefinition {
  kind: string;
  label: string;
  channel: MotionChannel;
  combine: CombineMode;
  /** documented channel bound for diagnostics and tests */
  bound: number;
  applyTo(acc: ChannelAccumulator, value: number, motion: MotionSpec, context: OperatorContext): void;
}

const registry = new Map<string, MotionOperatorDefinition>();

export function registerOperator(definition: MotionOperatorDefinition): void {
  registry.set(definition.kind, definition);
}

export function operatorFor(kind: string): MotionOperatorDefinition | null {
  return registry.get(kind) ?? null;
}

export function registeredOperatorKinds(): string[] {
  return [...registry.keys()].sort();
}

function axisOf(motion: MotionSpec): [number, number] {
  return 'axis' in motion ? motion.axis : [1, 0];
}

function amountOf(motion: MotionSpec): number {
  return motion.amount;
}

/** Reference pixels per unit of authored amount (keeps the frozen motion scale). */
const TRANSLATE_UNITS = 100;

registerOperator({
  kind: 'scale_pulse',
  label: 'Scale pulse',
  channel: 'scale',
  combine: 'multiplicative',
  bound: 4,
  applyTo(acc, value, motion) {
    acc.scale *= 1 + amountOf(motion) * value;
  },
});

registerOperator({
  kind: 'radial_expand',
  label: 'Radial expand',
  channel: 'scale',
  combine: 'multiplicative',
  bound: 4,
  applyTo(acc, value, motion, context) {
    acc.scale *= 1 + amountOf(motion) * value;
    // deterministic seeded angular variance: same identity + sample always
    // yields the same angle, so seeking reproduces the frame exactly
    const jitter = (seededNoise(context.seedKey, context.sample) - 0.5) * amountOf(motion) * 40;
    acc.rotation += jitter * value;
  },
});

registerOperator({
  kind: 'translate_recoil',
  label: 'Translate recoil',
  channel: 'translate',
  combine: 'additive',
  bound: 40,
  applyTo(acc, value, motion) {
    const [ax, ay] = axisOf(motion);
    acc.tx += ax * amountOf(motion) * TRANSLATE_UNITS * value;
    acc.ty += ay * amountOf(motion) * TRANSLATE_UNITS * value;
  },
});

registerOperator({
  kind: 'translate_drift',
  label: 'Translate drift',
  channel: 'translate',
  combine: 'additive',
  bound: 40,
  applyTo(acc, value, motion) {
    const [ax, ay] = axisOf(motion);
    acc.tx += ax * amountOf(motion) * TRANSLATE_UNITS * value;
    acc.ty += ay * amountOf(motion) * TRANSLATE_UNITS * value;
  },
});

registerOperator({
  kind: 'rotate_recoil',
  label: 'Rotate recoil',
  channel: 'rotation',
  combine: 'additive',
  bound: 12,
  applyTo(acc, value, motion) {
    acc.rotation += amountOf(motion) * value;
  },
});

registerOperator({
  kind: 'crop_reveal',
  label: 'Crop reveal',
  channel: 'crop',
  combine: 'max',
  bound: 1,
  applyTo(acc, value, motion) {
    acc.crop = Math.max(acc.crop, amountOf(motion) * value);
  },
});

registerOperator({
  kind: 'strip_offset',
  label: 'Strip offset',
  channel: 'strip',
  combine: 'additive',
  bound: 1,
  applyTo(acc, value, motion) {
    acc.strip += amountOf(motion) * value;
  },
});

registerOperator({
  kind: 'opacity_lift',
  label: 'Opacity lift',
  channel: 'opacity',
  combine: 'max',
  bound: 1,
  applyTo(acc, value, motion) {
    // lift brightens the headroom above the authored resting opacity
    acc.opacityLift = Math.max(acc.opacityLift, amountOf(motion) * value * 2);
  },
});

registerOperator({
  kind: 'opacity_fade',
  label: 'Opacity fade',
  channel: 'opacity',
  combine: 'max',
  bound: 1,
  applyTo(acc, value, motion) {
    acc.opacityFade = Math.max(acc.opacityFade, amountOf(motion) * value * 2);
  },
});

registerOperator({
  kind: 'blur_focus',
  label: 'Blur focus',
  channel: 'blur',
  combine: 'max',
  bound: 12,
  applyTo(acc, value, motion) {
    acc.blur = Math.max(acc.blur, amountOf(motion) * value);
  },
});

registerOperator({
  kind: 'invert_palette',
  label: 'Invert palette',
  channel: 'invert',
  combine: 'boolean',
  bound: 1,
  applyTo(acc, value, motion) {
    acc.invert = Math.max(acc.invert, amountOf(motion) * value);
  },
});
