/**
 * Shared texture assets + canvas-generated helpers for the Pixi renderer.
 * Demo media are repository-owned deterministic PNGs served from
 * demo-media/ (no third-party assets).
 */
import { Assets, Texture, ColorMatrixFilter } from 'pixi.js';

export interface DemoTextures {
  fogRidge: Texture | null;
  fogBright: Texture | null;
  paperFiber: Texture | null;
  halftone: Texture | null;
}

export const MEDIA_URLS = {
  fogRidge: 'demo-media/fog-ridge.png',
  fogBright: 'demo-media/fog-bright.png',
  paperFiber: 'demo-media/paper-fiber.png',
  halftone: 'demo-media/halftone.png',
};

export async function loadDemoTextures(): Promise<DemoTextures> {
  const loaded = await Promise.all(
    Object.values(MEDIA_URLS).map((url) => Assets.load<Texture>(url).catch(() => null)),
  );
  const [fogRidge, fogBright, paperFiber, halftone] = loaded;
  return { fogRidge, fogBright, paperFiber, halftone };
}

/* ---------------- CSS-equivalent filter composition ---------------- */

type Mat = number[]; // 20-entry color matrix

function identity(): Mat {
  return [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0] as Mat;
}

function multiply(a: Mat, b: Mat): Mat {
  // a then b, rows of combined color transform
  const out = new Array<number>(20).fill(0);
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 5; col++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) {
        sum += a[row * 5 + k] * b[k * 5 + col];
      }
      if (col === 4) sum += a[row * 5 + 4];
      out[row * 5 + col] = sum;
    }
  }
  return out;
}

function saturateMat(s: number): Mat {
  const lr = 0.213;
  const lg = 0.715;
  const lb = 0.072;
  return ([
    lr + (1 - lr) * s, lg - lg * s, lb - lb * s, 0, 0,
    lr - lr * s, lg + (1 - lg) * s, lb - lb * s, 0, 0,
    lr - lr * s, lg - lg * s, lb + (1 - lb) * s, 0, 0,
    0, 0, 0, 1, 0,
  ]) as Mat;
}

function brightnessMat(b: number): Mat {
  return [b, 0, 0, 0, 0, 0, b, 0, 0, 0, 0, 0, b, 0, 0, 0, 0, 0, 1, 0] as Mat;
}

function contrastMat(c: number): Mat {
  const f = c;
  const o = 0.5 * (1 - f);
  return [f, 0, 0, 0, o, 0, f, 0, 0, o, 0, 0, f, 0, o, 0, 0, 0, 1, 0] as Mat;
}

export interface FilterSpec {
  saturate?: number;
  contrast?: number;
  brightness?: number;
}

/** Compose saturate → contrast → brightness, mirroring the CSS filter chain. */
export function makeColorFilter(spec: FilterSpec): ColorMatrixFilter | null {
  if (!spec.saturate && !spec.contrast && !spec.brightness) return null;
  let m = identity();
  if (spec.saturate !== undefined) m = multiply(saturateMat(spec.saturate), m);
  if (spec.contrast !== undefined) m = multiply(contrastMat(spec.contrast), m);
  if (spec.brightness !== undefined) m = multiply(brightnessMat(spec.brightness), m);
  const filter = new ColorMatrixFilter();
  filter.matrix = m as unknown as ColorMatrixFilter['matrix'];
  return filter;
}
