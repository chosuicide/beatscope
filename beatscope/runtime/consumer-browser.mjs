import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

const [playwrightModule, rootArg, entryArg, audioPath] = process.argv.slice(2);
const root = resolve(rootArg);
const errors = [];
const checks = {};

function same(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function contentType(path) {
  return ({ ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json" })[extname(path)] || "application/octet-stream";
}

const server = createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, "http://127.0.0.1").pathname);
    const file = resolve(root, `.${pathname}`);
    if (file !== root && !file.startsWith(`${root}${sep}`)) throw new Error("path escapes validation root");
    const body = await readFile(file);
    response.writeHead(200, { "content-type": contentType(file), "cache-control": "no-store" });
    response.end(body);
  } catch {
    if (!response.headersSent) response.writeHead(404);
    response.end("not found");
  }
});

let browser;
try {
  const { chromium } = await import(pathToFileURL(resolve(playwrightModule)).href);
  await new Promise((resolveListen) => server.listen(0, "127.0.0.1", resolveListen));
  const { port } = server.address();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on("pageerror", (error) => errors.push(`page:${error.message}`));
  page.on("console", (message) => { if (message.type() === "error") errors.push(`console:${message.text()}`); });
  const url = `http://127.0.0.1:${port}/${entryArg.split(sep).join("/")}`;
  await page.goto(url, { waitUntil: "networkidle" });
  await page.waitForFunction(() => Object.isFrozen(window.__BEATSCOPE_CONSUMER__));
  checks.frozenHook = true;

  await page.locator("#audio-file").setInputFiles(audioPath);
  await page.waitForFunction(() => Number.isFinite(document.querySelector("#audio")?.duration));
  const initial = await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.frameAt(0));
  const atEight = await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.frameAt(8));
  await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.frameAt(3));
  const atEightAgain = await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.frameAt(8));
  checks.seekDeterministic = same(atEight, atEightAgain);

  await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.seek(5));
  await page.waitForFunction(() => Math.abs(window.__BEATSCOPE_CONSUMER__.diagnostics().audioTime - 5) < 0.1);
  checks.seek = true;
  await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.resume());
  await page.waitForTimeout(350);
  await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.pause());
  const paused = await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.diagnostics());
  checks.playback = paused.paused === true && paused.audioTime > 5.05;

  const beforeReduced = await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.frameAt(8).timing);
  await page.locator("#reduced-motion").check();
  const afterReduced = await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.frameAt(8).timing);
  checks.reducedMotionTiming = same(beforeReduced, afterReduced);

  await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.seek(0));
  const replay = await page.evaluate(() => window.__BEATSCOPE_CONSUMER__.frameAt(0));
  checks.replay = same(initial, replay);
  for (const [name, passed] of Object.entries(checks)) if (!passed) errors.push(`browser:${name}:failed`);
} catch (error) {
  errors.push(`browser:${error?.message || String(error)}`);
} finally {
  if (browser) await browser.close();
  await new Promise((resolveClose) => server.close(resolveClose));
}

process.stdout.write(JSON.stringify({ ok: errors.length === 0, checks, errors }));
process.exitCode = errors.length ? 1 : 0;
