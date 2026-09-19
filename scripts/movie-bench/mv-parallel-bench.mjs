/**
 * Parallel-capture throughput: how much does wall time drop when N browser
 * pages render and capture frames round-robin? Each frame is rendered at an
 * exact media time by the same template code, so the output stays identical.
 *
 * Usage: BEATSCOPE_PLAYWRIGHT_MODULE=<path> node scripts/movie-bench/mv-parallel-bench.mjs <job-dir> [frames] [pages...]
 */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import os from 'node:os';
import { pathToFileURL } from 'node:url';

const root = path.resolve(process.argv[2]);
const FRAMES = Number(process.argv[3] || 90);
const PAGE_COUNTS = (process.argv.slice(4).length ? process.argv.slice(4) : ['1', '2', '3']).map(Number);
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
const url = `http://127.0.0.1:${server.address().port}/`;
const fps = plan.fps || 30;

const browser = await chromium.launch({
  headless: true,
  channel: process.env.BEATSCOPE_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : 'chromium'),
  args: ['--enable-webgl', '--ignore-gpu-blocklist'],
});

async function makeWorker() {
  const page = await browser.newPage({ viewport: { width: 1080, height: 1080 }, deviceScaleFactor: 1 });
  await page.goto(url);
  await page.waitForFunction(() => window.ready, {}, { timeout: 45000 });
  const cdp = await page.context().newCDPSession(page);
  const grab = async (t) => {
    await page.evaluate((x) => window.renderAt(x), t);
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png', optimizeForSpeed: true, captureBeyondViewport: false });
    return Buffer.from(shot.data, 'base64');
  };
  return { page, grab };
}

console.log(`machine: ${os.cpus().length} logical cores`);
for (const count of PAGE_COUNTS) {
  const workers = [];
  for (let i = 0; i < count; i++) workers.push(await makeWorker());
  // warm-up
  await Promise.all(workers.map((w) => w.grab(0)));
  const start = Date.now();
  const results = new Array(FRAMES);
  const queues = workers.map(() => []);
  for (let i = 0; i < FRAMES; i++) queues[i % count].push(i);
  await Promise.all(workers.map(async (worker, index) => {
    for (const i of queues[index]) results[i] = await worker.grab(i / fps);
  }));
  const elapsed = Date.now() - start;
  const bytes = results.reduce((sum, buffer) => sum + buffer.length, 0);
  console.log(`pages=${count}: ${(elapsed / FRAMES).toFixed(1)} ms/frame, ${(FRAMES / (elapsed / 1000)).toFixed(1)} fps, ${(bytes / FRAMES / 1e6).toFixed(2)} MB/frame png`);
  for (const worker of workers) await worker.page.close();
}
await browser.close();
server.close();
