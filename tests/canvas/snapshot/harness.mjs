/**
 * Snapshot harness helpers for the Beathi Canvas design contract.
 *
 * Playwright is reused from tests/browser (pinned there at 1.61.0); the
 * pixel comparison runs inside the browser page so no extra decoding
 * dependencies are needed. Comparison is masked perceptual block-mean
 * distance (plan §2.11): composition must match, not anti-aliased pixels.
 */
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..', '..');

export function repoPath(...parts) {
  return path.join(repoRoot, ...parts);
}

export function loadPlaywright() {
  const require = createRequire(repoPath('tests', 'browser', 'package.json'));
  return require('playwright');
}

export const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1920x1080', width: 1920, height: 1080 },
];

/**
 * Capture `url` at every frozen viewport into `outDir`,
 * named `<stem>-<viewport>.png`. Returns written file paths.
 */
export async function captureAllViewports(url, outDir, options = {}) {
  const { playwright } = loadPlaywright();
  const browser = await playwright.chromium.launch();
  const written = [];
  try {
    for (const vp of VIEWPORTS) {
      const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
      await page.goto(url, { waitUntil: 'load' });
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(options.settleMs ?? 250);
      const file = path.join(outDir, `${options.stem ?? 'capture'}-${vp.name}.png`);
      await page.screenshot({ path: file, fullPage: false });
      await page.close();
      written.push(file);
    }
  } finally {
    await browser.close();
  }
  return written;
}

/** Metric code evaluated inside a browser page. Exported for tests. */
export const COMPARE_PAGE_FN = `
async ({ candidate, baseline, masks = [] }) => {
  const load = (src) => new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('decode failed: ' + src));
    img.src = src;
  });
  const [a, b] = await Promise.all([load(candidate), load(baseline)]);
  if (a.width !== b.width || a.height !== b.height) {
    return { ok: false, reason: 'size-mismatch', size: [a.width, a.height, b.width, b.height] };
  }
  const GRID = 64;
  const canvas = document.createElement('canvas');
  canvas.width = GRID; canvas.height = GRID;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const sample = (img) => {
    ctx.clearRect(0, 0, GRID, GRID);
    ctx.drawImage(img, 0, 0, GRID, GRID);
    const data = ctx.getImageData(0, 0, GRID, GRID).data;
    const gray = new Float64Array(GRID * GRID);
    for (let i = 0; i < GRID * GRID; i++) {
      gray[i] = 0.2126 * data[i * 4] + 0.7152 * data[i * 4 + 1] + 0.0722 * data[i * 4 + 2];
    }
    return gray;
  };
  const ga = sample(a), gb = sample(b);
  // masks are rects in source pixels; exclude every grid cell they touch
  const masked = new Uint8Array(GRID * GRID);
  for (const [mx, my, mw, mh] of masks || []) {
    const x0 = Math.max(0, Math.floor(mx / a.width * GRID));
    const x1 = Math.min(GRID - 1, Math.ceil((mx + mw) / a.width * GRID) - 1);
    const y0 = Math.max(0, Math.floor(my / a.height * GRID));
    const y1 = Math.min(GRID - 1, Math.ceil((my + mh) / a.height * GRID) - 1);
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) masked[y * GRID + x] = 1;
  }
  let total = 0, counted = 0, worst = 0, worstCell = -1;
  for (let i = 0; i < GRID * GRID; i++) {
    if (masked[i]) continue;
    const d = Math.abs(ga[i] - gb[i]);
    total += d; counted++;
    if (d > worst) { worst = d; worstCell = i; }
  }
  const mean = total / Math.max(1, counted);
  return { ok: mean <= 1.5, mean, worst, worstCell, grid: GRID, maskedCells: masked.reduce((s, v) => s + v, 0) };
}
`;
