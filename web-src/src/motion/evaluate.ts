/**
 * Public motion facade (plan §4.6). The compiled evaluator lives in
 * compile.ts; this module re-exports the registries and keeps the small
 * scene lookup helper every consumer already uses.
 */
import type { DirectionDocument, DirectionScene } from '../direction/types';

export {
  compileDirection,
  getDirectionState,
  outputFor,
  envelopeValue,
  videoSourceTime,
  DEFAULT_TRANSITION_SECONDS,
} from './compile.js';
export type {
  CompiledDirection,
  CompiledScene,
  CompiledResponse,
  CompileOptions,
  QueryOptions,
  ResponseDiagnostics,
} from './compile.js';
export { driverFor, registeredDriverKinds } from './drivers.js';
export type { DriverDefinition, CompiledDriver, DriverEvent, DriverAvailability } from './drivers.js';
export { operatorFor, registeredOperatorKinds } from './operators.js';
export type { MotionOperatorDefinition, CombineMode, MotionChannel, OperatorContext } from './operators.js';
export { applyReducedMotion, prefersReducedMotion, observeReducedMotion, REDUCED_MOTION_PROFILE } from './reduced-motion.js';
export type { ReducedMotionProfile } from './reduced-motion.js';
export { seededNoise, seededUnit, hashSeed, quantize } from './noise.js';
export { lowerBound, upperBound } from './search.js';
export {
  BASE_OUTPUT,
  CHANNEL_BOUNDS,
  freshAccumulator,
  finalizeOutput,
} from './types.js';
export type {
  LayerOutput,
  ChannelAccumulator,
  DirectionState,
  TransitionState,
} from './types.js';

/** Half-open scene lookup; the last scene owns the tail of the timeline. */
export function sceneAtTime(doc: DirectionDocument, time: number): DirectionScene {
  const scenes = doc.scenes;
  for (const scene of scenes) {
    if (time >= scene.start_time && time < scene.end_time) return scene;
  }
  return scenes[scenes.length - 1];
}
