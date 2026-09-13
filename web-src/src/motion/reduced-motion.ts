/**
 * Reduced-motion mapping. The preference is observed live
 * and only scales the preview output: edit meaning (opacity, crop reveal,
 * palette inversion) is preserved, aggressive movement is suppressed. The
 * saved direction document is never altered.
 */
import type { LayerOutput } from './types';

export interface ReducedMotionProfile {
  translate: number;
  rotation: number;
  scale: number;
  strip: number;
  blur: number;
}

/** Suppress aggressive movement; keep meaning-carrying channels intact. */
export const REDUCED_MOTION_PROFILE: ReducedMotionProfile = Object.freeze({
  translate: 0.25,
  rotation: 0.25,
  scale: 0.5,
  strip: 0.25,
  blur: 0.5,
});

export function applyReducedMotion(
  output: LayerOutput,
  profile: ReducedMotionProfile = REDUCED_MOTION_PROFILE,
): LayerOutput {
  return {
    scale: 1 + (output.scale - 1) * profile.scale,
    translate: {
      x: output.translate.x * profile.translate,
      y: output.translate.y * profile.translate,
    },
    rotation: output.rotation * profile.rotation,
    // opacity, crop and invert carry edit meaning: unchanged
    opacity: output.opacity,
    crop: output.crop,
    strip: output.strip * profile.strip,
    blur: output.blur * profile.blur,
    invert: output.invert,
  };
}

/** Live media query, guarded for non-browser (test) environments. */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Subscribe to preference changes; returns an unsubscribe function. */
export function observeReducedMotion(listener: (reduced: boolean) => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {};
  const query = window.matchMedia('(prefers-reduced-motion: reduce)');
  const handler = (event: MediaQueryListEvent) => listener(event.matches);
  query.addEventListener('change', handler);
  return () => query.removeEventListener('change', handler);
}
