/**
 * Implementation-conformance check (Round 1 Commit 2 visual gate).
 *
 * The frozen-reference check (run-reference-check.mjs) proves the approved
 * design frames have not drifted. This script proves the OPPOSITE edge: the
 * React/PixiJS implementation, captured live from the built `web/app`
 * bundle, still matches the composition of those frozen references.
 *
 * For each frozen view the script:
 *   1. serves `beatscope/web/app` on an ephemeral local port,
 *   2. captures the seeded `?shot=1` state headlessly at 1440x900
 *      (SwiftShader WebGL, deterministic 24-frame settle),
 *   3. writes the capture to `impl-<stem>.png` (the committed evidence),
 *   4. compares it against the frozen reference with the same masked
 *      64x64 block-mean grayscale metric the reference check uses,
 *   5. validates live composition geometry (visible board set, wall
 *      occupancy, focus size, panel/minimap state and overlap safety).
 *
 * Pixel thresholds are per-view and deliberately looser than the reference
 * integrity gate: the implementation renders the real demo document
 * (its own board art, demo copy and live panels), so the metric can never
 * reach the 1.5/255 identity band of the HTML frames. These are regression
 * gates, not mock-identity gates — the reference frames are hand-drawn
 * mock worlds whose absolute scale differs from the shared impl world (the
 * frame-A viewport pins row 1 to the stage-left half of the wall, so frame
 * B's row spacing can only approximate the mock). Each threshold is the
 * implementation's different authored art. They are a broad visual smoke
 * guard only; the geometry assertions below are the composition gate. This
 * avoids the previous false-green where a wide but mostly empty bounding box
 * satisfied one global image average.
 *
 * Usage:
 *   node tests/canvas/snapshot/run-impl-conformance.mjs            # capture + verify
 *   node tests/canvas/snapshot/run-impl-conformance.mjs --verify   # pixel smoke only; CI never uses this shortcut
 */
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { COMPARE_PAGE_FN, loadPlaywright, repoPath } from './harness.mjs';

const APP_ROOT = repoPath('beatscope', 'web', 'app');
const OUT_DIR = repoPath('tests', 'canvas', 'snapshot');
const DESIGN = repoPath('docs', 'design', 'beathi-canvas');
const VERIFY_ONLY = process.argv.includes('--verify');

const VIEWS = [
  { stem: 'impl-a-first-run', reference: 'reference-a-first-run.png', seed: '?shot=1', threshold: 8 },
  { stem: 'impl-b-fit-all', reference: 'reference-b-canvas-overview.png', seed: '?shot=1&fit=1&dock=0&sel=scene-04&seek=204&play=1&loop=1', threshold: 38 },
  { stem: 'impl-c-layer-inspector', reference: 'reference-c-selected-editing.png', seed: '?shot=1&sel=scene-02&lay=lay-06&seek=38.6&focus=1&docktab=layers&resp=1', threshold: 27 },
  { stem: 'impl-d-package-review', reference: 'reference-d-prompt-package.png', seed: '?shot=1&sel=scene-02&seek=38.6&package=1&focus=1', threshold: 26 },
];

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.mp3': 'audio/mpeg',
};

function serveApp() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, 'http://localhost');
      const rel = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
      const file = path.join(APP_ROOT, rel);
      if (!file.startsWith(APP_ROOT) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
        res.writeHead(404);
        res.end('not found');
        return;
      }
      res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] ?? 'application/octet-stream' });
      res.end(fs.readFileSync(file));
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

function toDataUrl(file) {
  return `data:image/png;base64,${fs.readFileSync(file).toString('base64')}`;
}

function overlapArea(a, b) {
  const w = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x));
  const h = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  return w * h;
}

function assertComposition(view, data) {
  const fail = (message) => { throw new Error(`${view.stem}: ${message}`); };
  const visible = data.composition.boards.filter((b) => b.visible);
  const ids = visible.map((b) => b.id);
  if (view.stem === 'impl-a-first-run') {
    if (ids.join(',') !== 'scene-01,scene-02,scene-03,scene-04,scene-05') {
      fail(`first run must progressively show scenes 01–05, got ${ids.join(',')}`);
    }
    if (!data.composition.firstRunMode) fail('first-run disclosure is inactive');
    for (const board of visible) {
      const pageRect = { x: board.x + data.stage.x, y: board.y + data.stage.y, w: board.w, h: board.h };
      if (data.coach && overlapArea(pageRect, data.coach) > 1) fail(`${board.id} overlaps coach mark`);
      if (data.transport && overlapArea(pageRect, data.transport) > 1) fail(`${board.id} overlaps transport`);
    }
    return;
  }
  if (view.stem === 'impl-b-fit-all') {
    if (ids.length !== 10) fail(`overview must show all 10 boards, got ${ids.length}`);
    const minX = Math.min(...visible.map((b) => b.x));
    const minY = Math.min(...visible.map((b) => b.y));
    const maxX = Math.max(...visible.map((b) => b.x + b.w));
    const maxY = Math.max(...visible.map((b) => b.y + b.h));
    const widths = visible.map((b) => b.w).sort((a, b) => a - b);
    if ((maxX - minX) / data.stage.w < 0.68) fail('overview wall uses less than 68% of stage width');
    if ((maxY - minY) / data.stage.h < 0.58) fail('overview wall uses less than 58% of stage height');
    if (widths[Math.floor(widths.length / 2)] < 140) fail('overview boards are thumbnail-sized');
    if (!data.minimap) fail('overview minimap is hidden');
    return;
  }
  if (ids.join(',') !== 'scene-02') fail(`focused view must isolate scene-02, got ${ids.join(',')}`);
  const selected = visible.find((b) => b.id === 'scene-02');
  if (!selected) fail('selected scene-02 is not visible');
  if (data.minimap) fail('focused view must hide minimap');
  if (view.stem === 'impl-c-layer-inspector') {
    if (selected.w < 680 || selected.w > 780) fail(`focused width ${selected.w.toFixed(1)} is outside 680–780`);
    if (selected.h / data.stage.h < 0.55 || selected.h / data.stage.h > 0.65) fail('focused height is outside 55–65%');
  } else if (view.stem === 'impl-d-package-review') {
    if (selected.w < 620 || selected.w > 700) fail(`review width ${selected.w.toFixed(1)} is outside 620–700`);
    if (selected.h < 410 || selected.h > 490) fail(`review height ${selected.h.toFixed(1)} is outside 410–490`);
  }
}

async function captureViews(port) {
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader'] });
  const written = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    for (const view of VIEWS) {
      const file = path.join(OUT_DIR, `${view.stem}.png`);
      await page.goto(`http://127.0.0.1:${port}/${view.seed}`, { waitUntil: 'load' });
      await page.waitForFunction('window.__beathiReady === true', null, { timeout: 45000 });
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(400);
      const composition = await page.evaluate(() => {
        const rect = (selector) => {
          const el = document.querySelector(selector);
          if (!el || getComputedStyle(el).display === 'none') return null;
          const r = el.getBoundingClientRect();
          return { x: r.x, y: r.y, w: r.width, h: r.height };
        };
        const stage = rect('#beathi-canvas');
        return {
          composition: window.__beathiComposition,
          stage,
          coach: rect('.coach'),
          transport: rect('.transport'),
          minimap: rect('.minimap'),
        };
      });
      if (!composition.composition || !composition.stage) throw new Error(`${view.stem}: missing live composition snapshot`);
      assertComposition(view, composition);
      await page.screenshot({ path: file, fullPage: false });
      written.push(file);
      console.log(`captured ${path.basename(file)}`);
    }
  } finally {
    await browser.close();
  }
  return written;
}

async function compare(page, view, compareFn) {
  const candidate = path.join(OUT_DIR, `${view.stem}.png`);
  const reference = path.join(DESIGN, view.reference);
  const result = await page.evaluate(compareFn, {
    candidate: toDataUrl(candidate),
    baseline: toDataUrl(reference),
  });
  return { ...result, threshold: view.threshold, stem: view.stem };
}

const server = VERIFY_ONLY ? null : await serveApp();
const port = server?.address().port;
try {
  if (!VERIFY_ONLY) await captureViews(port);
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const compareFn = new Function(`return (${COMPARE_PAGE_FN})`)();
  let failed = 0;
  try {
    for (const view of VIEWS) {
      const r = await compare(page, view, compareFn);
      const ok = typeof r.mean === 'number' && r.mean <= r.threshold;
      if (!ok) failed++;
      console.log(
        `${ok ? 'ok' : 'FAIL'} ${view.stem} vs ${view.reference}: mean ${r.mean?.toFixed(3)} (threshold ${r.threshold})`,
      );
    }
  } finally {
    await browser.close();
  }
  if (failed) {
    console.error(`implementation conformance: ${failed} view(s) outside composition tolerance`);
    process.exitCode = 1;
  } else {
    console.log('implementation matches the frozen reference compositions');
  }
} finally {
  server?.close();
}
