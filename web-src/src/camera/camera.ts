/**
 * Camera model for the spatial canvas (layout-rules.md §Canvas behavior).
 * World units are reference pixels divided by the first-run zoom (0.62), so
 * the frozen frame-A geometry is exact at the default camera.
 */
import type { CameraState } from '../direction/types';

export const ZOOM_MIN = 0.12;
export const ZOOM_MAX = 3.0;

export function clampZoom(zoom: number): number {
  return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoom));
}

/**
 * Zoom around a pointer: keeps the world point under the cursor invariant
 * (focal-point drift ≤ 1e-6 by construction).
 */
export function zoomAtPointer(
  camera: CameraState,
  nextZoomRaw: number,
  pointerX: number,
  pointerY: number,
): CameraState {
  const nextZoom = clampZoom(nextZoomRaw);
  if (nextZoom === camera.zoom) return camera;
  // world point under pointer stays fixed:
  //   wx = (px - cam.x) / zoom
  const wx = (pointerX - camera.x) / camera.zoom;
  const wy = (pointerY - camera.y) / camera.zoom;
  return {
    zoom: nextZoom,
    x: pointerX - wx * nextZoom,
    y: pointerY - wy * nextZoom,
  };
}

/** Snap a world value to candidates within a screen-space threshold. */
export function snapValue(
  value: number,
  candidates: number[],
  thresholdScreenPx: number,
  zoom: number,
): { value: number; snapped: boolean } {
  const threshold = thresholdScreenPx / zoom;
  let best: number | null = null;
  let bestDist = Infinity;
  for (const cand of candidates) {
    const d = Math.abs(value - cand);
    if (d <= threshold && d < bestDist) {
      best = cand;
      bestDist = d;
    }
  }
  return best === null ? { value, snapped: false } : { value: best, snapped: true };
}

/** Smooth settle interpolation for camera moves (340 ms board focus). */
export function settle(current: number, target: number, dt: number, stiffness = 14): number {
  const t = 1 - Math.exp(-stiffness * dt);
  return current + (target - current) * t;
}
