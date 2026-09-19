/**
 * Ground truth for the encoding A/B: render specific frames in the real worker
 * page and read the 1080x1080 canvas back losslessly. The page canvas is a 2D
 * context that the template composites onto, so toDataURL() is exactly what the
 * compositor should show for that media time - independent of both the CDP
 * screenshot path and the in-page WebCodecs path.
 *
 * Usage: BEATSCOPE_PLAYWRIGHT_MODULE=<pw/index.mjs> node scripts/movie-bench/ab-probe.mjs <job-dir> <out-dir> <frame...>
 */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { pathToFileURL } from 'node:url';

const root = path.resolve(process.argv[2]);
const outDir = path.resolve(process.argv[3]);
const frames = process.argv.slice(4).map(Number);
if (!frames.length) throw new Error('no frames requested');
fs.mkdirSync(outDir, { recursive: true });

const modulePath = process.env.BEATSCOPE_PLAYWRIGHT_MODULE
  || path.resolve('web-src/node_modules/playwright/index.mjs');
const { chromium } = await import(pathToFileURL(modulePath).href);
const input = JSON.parse(fs.readFileSync(path.join(root, 'input.json')));
const plan = JSON.parse(fs.readFileSync(path.join(root, 'plan.json')));
const allowed = new Set(['mv-render.html', 'mv-frame.mjs', 'mv-visual.js', 'mv-encode.mjs', 'beatscope-runtime.js', 'input.json', 'plan.json']);
const publicInput = JSON.stringify({ rhythm: input.rhythm, ranking: input.ranking });
const server = http.createServer((req, res) => {
  const name = new URL(req.url, 'http://local').pathname.slice(1) || 'mv-render.html';
  if (!allowed.has(name)) { res.writeHead(404).end(); return; }
  res.setHeader('Content-Type', name.endsWith('.html') ? 'text/html' : name.endsWith('.json') ? 'application/json' : 'text/javascript');
  res.end(name === 'input.json' ? publicInput : fs.readFileSync(path.join(root, name)));
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));

const browser = await chromium.launch({
  headless: true,
  channel: process.env.BEATSCOPE_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : 'chromium'),
  args: ['--enable-webgl', '--ignore-gpu-blocklist'],
});
const page = await browser.newPage({ viewport: { width: 1080, height: 1080 }, deviceScaleFactor: 1 });
await page.goto(`http://127.0.0.1:${server.address().port}/`);
await page.waitForFunction(() => window.ready, {}, { timeout: 45000 });

for (const index of frames) {
  const dataUrl = await page.evaluate((t) => {
    window.renderAt(t);
    return document.querySelector('canvas').toDataURL('image/png');
  }, index / plan.fps);
  const bytes = Buffer.from(dataUrl.split(',')[1], 'base64');
  if (bytes.length < 20_000) throw new Error(`frame ${index} looks blank (${bytes.length} bytes)`);
  fs.writeFileSync(path.join(outDir, `truth-${index}.png`), bytes);
  console.log(`truth-${index}.png  ${(bytes.length / 1000).toFixed(0)} kB`);
}
await browser.close();
server.close();
