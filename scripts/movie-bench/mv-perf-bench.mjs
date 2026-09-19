/**
 * Render-pipeline benchmark: split the capture loop into
 *   (a) page renderAt   (b) screenshot PNG   (c) screenshot JPEG q100
 *   (d) x264 encode of the same frames
 * so we can see where the wall time actually goes.
 *
 * Usage: BEATSCOPE_PLAYWRIGHT_MODULE=<path> node scripts/movie-bench/mv-perf-bench.mjs <job-dir> [frames]
 */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { pathToFileURL } from 'node:url';

const root = path.resolve(process.argv[2]);
const FRAMES = Number(process.argv[3] || 120);
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

const fps = plan.fps || 30;
const t = (i) => i / fps;
const ms = (label, value, frames) => console.log(`${label}: ${value.toFixed(0)} ms total, ${(value / frames).toFixed(1)} ms/frame`);

async function phase(label, fn) {
  const start = Date.now();
  for (let i = 0; i < FRAMES; i++) await fn(i);
  const elapsed = Date.now() - start;
  ms(label, elapsed, FRAMES);
  return elapsed;
}

// warm-up
for (let i = 0; i < 10; i++) { await page.evaluate((x) => window.renderAt(x), t(i)); await page.screenshot(); }

const renderOnly = await phase('renderAt only        ', async (i) => { await page.evaluate((x) => window.renderAt(x), t(i)); });
const pngTotal = await phase('renderAt + PNG       ', async (i) => { await page.evaluate((x) => window.renderAt(x), t(i)); await page.screenshot(); });
const jpegTotal = await phase('renderAt + JPEG q100 ', async (i) => { await page.evaluate((x) => window.renderAt(x), t(i)); await page.screenshot({ type: 'jpeg', quality: 100 }); });

// collect the PNG frames once for the encoder benchmark
const frames = [];
for (let i = 0; i < FRAMES; i++) { await page.evaluate((x) => window.renderAt(x), t(i)); frames.push(await page.screenshot()); }
await browser.close();
server.close();

async function encode(extraArgs, label, stdinFormat = 'png') {
  const temp = path.join(root, `bench-${label.replace(/[^a-z0-9]+/gi, '-')}.mp4`);
  const args = ['-y', '-v', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-vcodec', stdinFormat, '-i', 'pipe:0',
    '-i', input.audio, '-map', '0:v:0', '-map', '1:a:0', '-af', `atrim=duration=${plan.duration},asetpts=PTS-STARTPTS`,
    ...extraArgs, '-t', String(plan.duration), '-movflags', '+faststart', temp];
  const child = spawn(process.env.BEATSCOPE_FFMPEG || 'ffmpeg', args, { windowsHide: true, stdio: ['pipe', 'ignore', 'pipe'] });
  let stderr = '';
  child.stderr.on('data', (b) => { stderr = (stderr + b).slice(-2000); });
  const start = Date.now();
  for (const frame of frames) {
    if (!child.stdin.write(frame)) await once(child.stdin, 'drain');
  }
  child.stdin.end();
  const [code] = await once(child, 'close');
  const elapsed = Date.now() - start;
  if (code !== 0) { console.log(`${label}: FAILED ${stderr}`); return null; }
  const size = fs.statSync(temp).size / 1e6;
  console.log(`${label}: ${elapsed.toFixed(0)} ms total, ${(elapsed / FRAMES).toFixed(1)} ms/frame, ${size.toFixed(1)} MB for ${FRAMES} frames`);
  return { elapsed, size };
}

console.log(`\n--- encode (${FRAMES} frames, ${(FRAMES / fps).toFixed(1)} s of video) ---`);
await encode(['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k'], 'x264 fast   crf18');
await encode(['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k'], 'x264 veryfast crf18');
await encode(['-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k'], 'x264 medium crf18');
await encode(['-c:v', 'libx264', '-preset', 'medium', '-crf', '21', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k'], 'x264 medium crf21');
await encode(['-c:v', 'libx264', '-preset', 'medium', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k'], 'x264 medium crf23');

console.log('\n--- summary ---');
console.log(`capture split: render ${renderOnly.toFixed(0)} ms, PNG overhead ${(pngTotal - renderOnly).toFixed(0)} ms, JPEG overhead ${(jpegTotal - renderOnly).toFixed(0)} ms`);
