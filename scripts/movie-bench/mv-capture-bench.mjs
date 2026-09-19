/**
 * Capture-format comparison: lossless PNG (default vs CDP optimizeForSpeed),
 * JPEG q100, and an objective PSNR measurement of JPEG against PNG.
 * Also reports which hardware H.264 encoders this machine offers.
 */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { pathToFileURL } from 'node:url';

const root = path.resolve(process.argv[2]);
const FRAMES = Number(process.argv[3] || 60);
const OUT = path.join(root, 'bench-out');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(path.join(OUT, 'png'), { recursive: true });
fs.mkdirSync(path.join(OUT, 'jpeg'), { recursive: true });

const { chromium } = await import(pathToFileURL(process.env.BEATSCOPE_PLAYWRIGHT_MODULE).href);
const input = JSON.parse(fs.readFileSync(path.join(root, 'input.json')));
const plan = JSON.parse(fs.readFileSync(path.join(root, 'plan.json')));
const allowed = new Set(['mv-render.html', 'mv-frame.mjs', 'mv-visual.js', 'beatscope-runtime.js', 'input.json', 'plan.json']);
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
const session = await page.context().newCDPSession(page);

const fps = plan.fps || 30;
const at = (i) => i / fps;
for (let i = 0; i < 8; i++) { await page.evaluate((x) => window.renderAt(x), at(i)); await page.screenshot(); }

async function phase(label, fn) {
  const start = Date.now();
  for (let i = 0; i < FRAMES; i++) await fn(i);
  const elapsed = Date.now() - start;
  console.log(`${label}: ${(elapsed / FRAMES).toFixed(1)} ms/frame`);
  return elapsed;
}

await phase('playwright PNG            ', async (i) => { await page.evaluate((x) => window.renderAt(x), at(i)); await page.screenshot(); });
await phase('playwright JPEG q100      ', async (i) => { await page.evaluate((x) => window.renderAt(x), at(i)); await page.screenshot({ type: 'jpeg', quality: 100 }); });
await phase('CDP PNG optimizeForSpeed   ', async (i) => {
  await page.evaluate((x) => window.renderAt(x), at(i));
  await session.send('Page.captureScreenshot', { format: 'png', optimizeForSpeed: true, captureBeyondViewport: false });
});
await phase('CDP JPEG q100             ', async (i) => {
  await page.evaluate((x) => window.renderAt(x), at(i));
  await session.send('Page.captureScreenshot', { format: 'jpeg', quality: 100, captureBeyondViewport: false });
});

// collect both formats of the same frames for an objective comparison
for (let i = 0; i < FRAMES; i++) {
  await page.evaluate((x) => window.renderAt(x), at(i));
  fs.writeFileSync(path.join(OUT, 'png', `${String(i).padStart(3, '0')}.png`), await page.screenshot());
  fs.writeFileSync(path.join(OUT, 'jpeg', `${String(i).padStart(3, '0')}.jpg`), await page.screenshot({ type: 'jpeg', quality: 100 }));
}
await browser.close();
server.close();

const ffmpeg = process.env.BEATSCOPE_FFMPEG || 'ffmpeg';
const psnr = spawn(ffmpeg, ['-v', 'info', '-framerate', '30', '-i', path.join(OUT, 'png', '%03d.png'),
  '-framerate', '30', '-i', path.join(OUT, 'jpeg', '%03d.jpg'), '-lavfi', 'psnr', '-f', 'null', '-'],
  { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
let text = '';
psnr.stderr.on('data', (b) => { text += b; });
await once(psnr, 'close');
const line = text.split('\n').filter((l) => l.includes('average')).pop();
console.log(`\nPNG vs JPEG q100 (${FRAMES} frames): ${line ? line.trim() : 'no PSNR line'}`);

const encoders = spawn(ffmpeg, ['-hide_banner', '-encoders'], { windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
let list = '';
encoders.stdout.on('data', (b) => { list += b; });
await once(encoders, 'close');
const hardware = list.split('\n').filter((l) => /nvenc|qsv|amf|vaapi/.test(l)).map((l) => l.trim().split(/\s+/)[1]).filter(Boolean);
console.log(`hardware encoders: ${hardware.length ? hardware.join(', ') : 'none'}`);
