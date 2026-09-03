/**
 * Browser end-to-end flow for the WebMCP Director demo
 * (v0.10 plan sections 18.5, 26).
 *
 * A modelContext shim is injected before the page loads, so the shim sees
 * exactly what a WebMCP-capable browser would register. The flow drives the
 * frozen static demo (scripts/build_webmcp_demo.py output served at
 * --base-url) through a full research-and-act round trip:
 *
 *     node tests/browser/webmcp-smoke.mjs [baseURL]
 *     (default baseURL: http://127.0.0.1:8770)
 *
 * Evidence: a single screenshot at build/webmcp-evidence/director-focus.png.
 * No cross-platform pixel hashing (plan section 18.6).
 */
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const BASE_URL = process.argv[2] || 'http://127.0.0.1:8770';
const REPO_ROOT = path.resolve(fileURLToPath(import.meta.url), '..', '..', '..');
const EVIDENCE_DIR = path.join(REPO_ROOT, 'build', 'webmcp-evidence');

const fail = (message) => {
  console.error(`webmcp-smoke FAILED: ${message}`);
  process.exit(1);
};

const browser = await chromium.launch({
  // Chromium 141 on Windows can internally pause a headless media element
  // when the process-wide --mute-audio flag is present. Mute the element
  // instead: playback still exercises the real media clock without sound.
  args: ['--autoplay-policy=no-user-gesture-required'],
});
const page = await browser.newPage();
const pageErrors = [];
page.on('pageerror', (error) => pageErrors.push(error));

try {
  // The shim must exist before any page script runs: register.js
  // feature-detects document.modelContext at module init.
  await page.addInitScript(() => {
    const tools = new Map();
    Object.defineProperty(document, 'modelContext', {
      value: {
        registerTool(definition, options = {}) {
          tools.set(definition.name, { definition, signal: options.signal || null });
          return Promise.resolve();
        },
      },
      configurable: true,
    });
    window.__capturedWebMcpTools = tools;
  });

  await page.goto(`${BASE_URL}/?demo=webmcp`, { waitUntil: 'load', timeout: 30000 });

  // 2. The topbar must reach the ready state with all eight tools.
  await page.waitForFunction(() => document.querySelector('#webmcpStatus')?.textContent === 'WEBMCP READY · 8 TOOLS', null, { timeout: 20000 });

  // The demo mp3 must be buffered enough for seeks to apply: Chromium
  // ignores currentTime assignment while only metadata has arrived
  // (HAVE_METADATA), so wait for HAVE_FUTURE_DATA before acting.
  await page.waitForFunction(() => {
    const audio = document.querySelector('#audio');
    return Boolean(audio && audio.currentSrc && audio.readyState >= 3);
  }, null, { timeout: 20000 });
  await page.evaluate(() => { document.querySelector('#audio').muted = true; });

  const registered = await page.evaluate(() => [...window.__capturedWebMcpTools.keys()].sort());
  const expected = [
    'compare_ranges', 'control_playback', 'find_visual_moments', 'focus_range',
    'get_events', 'get_project_context', 'get_state_at_time', 'set_loop_range',
  ];
  if (JSON.stringify(registered) !== JSON.stringify(expected)) {
    fail(`expected the 8 Director tools, got ${JSON.stringify(registered)}`);
  }

  const execute = (name, input) => page.evaluate(async ([toolName, toolInput]) => {
    const entry = window.__capturedWebMcpTools.get(toolName);
    return entry.definition.execute(toolInput, {});
  }, [name, input]);

  // 3. Context first: the demo track is loaded and describes itself.
  const context = await execute('get_project_context', {});
  if (!context.ok) fail(`get_project_context failed: ${JSON.stringify(context)}`);

  // 4. Find the structural transition candidates.
  const moments = await execute('find_visual_moments', { kind: 'structural_transition' });
  if (!moments.ok || !moments.candidates?.length) fail('find_visual_moments returned no candidates');
  const candidate = moments.candidates[0];

  // 5-7. Focus the candidate, loop it, and start playback two beats early.
  const focus = await execute('focus_range', {
    startBar: candidate.startBar, endBar: candidate.endBar, reason: 'Smoke test transition',
  });
  if (!focus.ok) fail(`focus_range failed: ${JSON.stringify(focus)}`);
  const loop = await execute('set_loop_range', { enabled: true, startBar: candidate.startBar, endBar: candidate.endBar });
  if (!loop.ok) fail(`set_loop_range failed: ${JSON.stringify(loop)}`);
  const playback = await execute('control_playback', {
    action: 'seek_and_play', bar: candidate.startBar, preRollBeats: 2,
  });
  if (!playback.ok) fail(`control_playback failed: ${JSON.stringify(playback)}`);
  if (playback.requiresUserGesture) fail('autoplay was rejected in a browser launched with autoplay allowed');

  // 8. The focus readout and the action ledger are visible in the page.
  const focusText = await page.textContent('#agentFocusText');
  if (!new RegExp(`AGENT FOCUS · BARS \\d+—\\d+`).test(focusText || '')) {
    fail(`focus readout missing: ${JSON.stringify(focusText)}`);
  }
  const ledgerVisible = await page.isVisible('#agentCollab');
  if (!ledgerVisible) fail('action ledger is not visible after tool calls');

  // 9. The audio element landed on the promised position.
  const audioTime = await page.evaluate(() => document.querySelector('#audio').currentTime);
  if (Math.abs(audioTime - playback.seekTime) > 0.15) {
    fail(`audio at ${audioTime.toFixed(3)}s, tool promised ${playback.seekTime}s`);
  }

  // 10. The loop is live in tool-visible state.
  const loopedContext = await execute('get_project_context', {});
  if (!loopedContext.playback.loop.enabled) fail('context does not report the enabled loop');

  // 11. Playback advances.
  await page.waitForTimeout(1000);
  const laterTime = await page.evaluate(() => document.querySelector('#audio').currentTime);
  if (laterTime <= audioTime + 0.3) fail(`audio did not advance (${audioTime.toFixed(3)} -> ${laterTime.toFixed(3)})`);

  // 12. Crossing the loop end wraps back to the loop start.
  await execute('control_playback', { action: 'seek', time: loop.loop.endTime + 0.2 });
  const loopStart = loop.loop.startTime;
  await page.waitForFunction((start) => Math.abs(document.querySelector('#audio').currentTime - start) < 0.3, loopStart, { timeout: 4000 });

  // 13. Pause, then the tool context must match the paused player.
  await execute('control_playback', { action: 'pause' });
  const pausedContext = await execute('get_project_context', {});
  if (pausedContext.playback.playing) fail('context still reports playing after pause');
  const pausedTime = await page.evaluate(() => document.querySelector('#audio').currentTime);
  if (Math.abs(pausedContext.playback.time - pausedTime) > 0.05) {
    fail(`context time ${pausedContext.playback.time} != audio time ${pausedTime}`);
  }

  // 14. One evidence screenshot; layout only, no pixel hashing. Full page so
  // the overview Agent Focus bracket, the readout and the ledger are in it.
  mkdirSync(EVIDENCE_DIR, { recursive: true });
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'director-focus.png'), fullPage: true });

  if (pageErrors.length) {
    fail(`page raised ${pageErrors.length} uncaught error(s): ${pageErrors[0]}`);
  }
  console.log('webmcp-smoke ok: 8 tools registered, focus/loop/playback round trip verified');
} catch (error) {
  fail(error.stack || String(error));
} finally {
  await browser.close();
}
