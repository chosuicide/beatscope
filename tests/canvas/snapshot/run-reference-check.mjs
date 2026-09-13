/**
 * Frozen-reference snapshot check (Round 1 Commit 1).
 *
 * Captures the four approved frame sources at the two frozen viewports and
 * compares each capture against the committed baseline (masked perceptual
 * block-mean distance, tolerance 1.5/255 mean). Baseline SHA-256 digests are
 * recorded in baselines/manifest.json; verification fails if a baseline has
 * been altered without regenerating the manifest.
 *
 * Usage:
 *   node tests/canvas/snapshot/run-reference-check.mjs            # verify
 *   node tests/canvas/snapshot/run-reference-check.mjs --write    # (re)generate baselines + manifest
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { COMPARE_PAGE_FN, VIEWPORTS, loadPlaywright, repoPath } from './harness.mjs';

const DESIGN = repoPath('docs', 'design', 'beathi-canvas');
const BASELINES = repoPath('tests', 'canvas', 'snapshot', 'baselines');
const FRAMES = [
  { stem: 'reference-a-first-run', file: 'frame-a.html' },
  { stem: 'reference-b-canvas-overview', file: 'frame-b.html' },
  { stem: 'reference-c-selected-editing', file: 'frame-c.html' },
  { stem: 'reference-d-prompt-package', file: 'frame-d.html' },
];
const WRITE = process.argv.includes('--write');

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function fileUrl(p) {
  return 'file:///' + path.resolve(p).replace(/\\/g, '/');
}

// data: URLs keep the comparison canvas untainted by file:// origin rules
function dataUrl(file) {
  return 'data:image/png;base64,' + fs.readFileSync(file).toString('base64');
}

async function main() {
  fs.mkdirSync(BASELINES, { recursive: true });
  for (const vp of VIEWPORTS) fs.mkdirSync(path.join(BASELINES, vp.name), { recursive: true });

  const manifestPath = path.join(BASELINES, 'manifest.json');
  const manifest = fs.existsSync(manifestPath)
    ? JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
    : { baselines: {} };

  const playwright = loadPlaywright();
  const browser = await playwright.chromium.launch();
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'beathi-snap-'));
  const failures = [];
  const compareFn = new Function(`return (${COMPARE_PAGE_FN})`)();
  const comparePage = await browser.newPage();

  try {
    for (const frame of FRAMES) {
      for (const vp of VIEWPORTS) {
        const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
        await page.goto(fileUrl(path.join(DESIGN, frame.file)), { waitUntil: 'load' });
        await page.evaluate(() => document.fonts.ready.then(() => true));
        await page.waitForTimeout(250);
        const candidate = path.join(tmp, `${frame.stem}-${vp.name}.png`);
        await page.screenshot({ path: candidate });
        await page.close();

        const baseline = path.join(BASELINES, vp.name, `${frame.stem}.png`);
        const key = `${vp.name}/${frame.stem}.png`;
        if (WRITE) {
          fs.copyFileSync(candidate, baseline);
          manifest.baselines[key] = {
            sha256: sha256(baseline),
            source: `docs/design/beathi-canvas/${frame.file}`,
            viewport: vp.name,
          };
          console.log(`wrote baseline ${key}`);
          continue;
        }
        if (!fs.existsSync(baseline)) {
          failures.push(`missing baseline: ${key}`);
          continue;
        }
        const recorded = manifest.baselines?.[key];
        if (recorded && recorded.sha256 !== sha256(baseline)) {
          failures.push(`baseline tampered (manifest sha mismatch): ${key}`);
          continue;
        }
        const result = await comparePage.evaluate(compareFn, {
          candidate: dataUrl(candidate),
          baseline: dataUrl(baseline),
          masks: [],
        });
        if (!result.ok) {
          failures.push(`${key}: ${result.reason ?? `mean diff ${result.mean.toFixed(3)} > 1.5`}`);
        } else {
          console.log(`ok ${key} (mean ${(result.mean ?? 0).toFixed(3)})`);
        }
      }
    }
  } finally {
    await browser.close();
    if (!WRITE) fs.rmSync(tmp, { recursive: true, force: true });
  }

  if (WRITE) {
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
    console.log('manifest written');
    return;
  }
  if (failures.length) {
    console.error('FAIL\n' + failures.map((f) => ' - ' + f).join('\n'));
    process.exit(1);
  }
  console.log('frozen references verified at ' + VIEWPORTS.map((v) => v.name).join(' + '));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
