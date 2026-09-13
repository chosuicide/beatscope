/**
 * Studio Director v2 browser round trip (v0.12 WebMCP plan §11.5, §12).
 *
 *   node tests/browser/studio-webmcp-smoke.mjs http://127.0.0.1:<port>
 *
 * The harness injects a test-only `document.modelContext` before any page
 * script runs; it records the registrations and invokes the real callbacks.
 * Nothing here is bundled into the product (no shipping polyfill), and the
 * heavyweight render launch is deliberately not exercised — its validation
 * path is.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const base = process.argv[2];
if (!base) {
  console.error('usage: node studio-webmcp-smoke.mjs http://127.0.0.1:<port>');
  process.exit(2);
}
const { chromium } = await import(process.env.BEATSCOPE_PLAYWRIGHT_MODULE || 'playwright');

const PROJECT_ID = '0a1b2c3d4e5f';
const SESSION_KEY = 'beathi.movie.session.1';
const rhythm = JSON.parse(readFileSync(new URL('../fixtures/structure/aba.rhythm.json', import.meta.url), 'utf8'));
const { createTrack } = await import('../../beatscope/runtime/runtime.js');
/* Page integration, not a ranking oracle: the fixture's own measured facts are
   the expectation, and whether this song carries a v0.11 sidecar is read from
   the tool's own capability report. Shot-for-shot agreement with makePlan is
   pinned by the unit tests for four fixtures. */
const track = createTrack(rhythm);
const downbeats = (rhythm.beats ?? []).filter((beat) => beat.beat_in_bar === 1).map((beat) => beat.time).sort((a, b) => a - b);

const initScript = () => {
  const record = { registered: [], aborted: [] };
  window.__STUDIO_WEBMCP__ = record;
  document.modelContext = {
    registerTool: async (tool, options = {}) => {
      record.registered.push({ name: tool.name, tool });
      options.signal?.addEventListener('abort', () => {
        record.aborted.push(tool.name);
        try { window.__reportAbort?.(tool.name); } catch { /* no reporter */ }
      }, { once: true });
    },
    getTools: async () => record.registered.map((entry) => ({ name: entry.name })),
  };
};

const sessionScript = (value) => {
  try { window.localStorage.setItem('beathi.movie.session.1', value); } catch { /* about:blank */ }
};

const p95 = (values) => [...values].sort((a, b) => a - b)[Math.max(0, Math.ceil(values.length * 0.95) - 1)];

const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
const context = await browser.newContext();
const abortedTools = [];
await context.exposeFunction('__reportAbort', (name) => { abortedTools.push(name); });
await context.addInitScript(initScript);
await context.addInitScript(`(${sessionScript.toString()})(${JSON.stringify(JSON.stringify({ name: 'aba-fixture.wav', projectId: PROJECT_ID, seed: 7 }))})`);
const page = await context.newPage();
const failures = [];
page.on('pageerror', (error) => failures.push(String(error)));

const callTool = (name, input = {}) => page.evaluate(
  async ([tool, payload]) => {
    const entry = window.__STUDIO_WEBMCP__.registered.find((candidate) => candidate.name === tool);
    if (!entry) throw new Error(`tool not registered: ${tool}`);
    const controller = new AbortController();
    const started = performance.now();
    const result = await entry.tool.execute(payload, { signal: controller.signal });
    return { result, ms: performance.now() - started };
  },
  [name, input],
);

try {
  await page.goto(`${base}/app/`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.mv-agent', { timeout: 15000 });

  // 3. seven tools register, and the chip says so
  const registered = await page.evaluate(() => window.__STUDIO_WEBMCP__.registered.map((entry) => entry.name));
  assert.equal(registered.length, 7, `expected seven tools, got ${registered.length}`);
  assert.ok(registered.includes('beatscope_explain_movie') && registered.includes('beatscope_export_timing_package'));
  assert.match(await page.textContent('.mv-agent'), /7 TOOLS/);

  // 4/5. state reflects the loaded fixture, with no cached-project list
  /* The sidecar load is best-effort and lands just after the rhythm, so wait
     for it: a state read that races it would report ranking as unavailable. */
  let state;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    state = (await callTool('beatscope_get_studio_state')).result;
    if (state.data?.track?.response_relevance_available) break;
    await page.waitForTimeout(250);
  }
  assert.equal(state.ok, true, JSON.stringify(state));
  assert.equal(state.data.track.bars, downbeats.length);
  assert.equal(state.data.track.response_relevance_available, true);
  assert.ok(!('projects' in state.data));

  // 6. timing window matches the fixture exactly, bar windows included
  const timing = await callTool('beatscope_inspect_timing', { start_bar: 2, end_bar: 3, include: ['beats', 'onsets'] });
  assert.equal(timing.result.ok, true, JSON.stringify(timing.result));
  const inWindow = rhythm.onsets.filter((onset) => onset.time >= downbeats[1] && onset.time < downbeats[3]);
  const returned = timing.result.data.events.filter((event) => event.kind === 'onset');
  assert.deepEqual(returned.map((event) => event.id), inWindow.map((onset) => onset.id));
  assert.deepEqual(returned.map((event) => event.time), inWindow.map((onset) => onset.time));

  // 6/7. ranked events and the movie explanation follow the capability report:
  // a real ranked set (unmoved originals) when the song carries a sidecar, and
  // ranking_unavailable when it does not — never a silent chronological pass-off.
  const pool = new Set(track.between(0, rhythm.source.duration).map((onset) => `${onset.id}@${onset.time}`));
  const rankedAvailable = state.data.capabilities.ranked_events;
  const ranked = await callTool('beatscope_get_response_events', { start_time: 0, end_time: rhythm.source.duration, budget: 6 });
  if (rankedAvailable) {
    assert.equal(ranked.result.ok, true, JSON.stringify(ranked.result));
    assert.ok(ranked.result.data.selected_count <= 6);
    for (const event of ranked.result.data.events) assert.ok(pool.has(`${event.id}@${event.time}`), 'ranked events are original onsets');
  } else {
    assert.equal(ranked.result.ok, false);
    assert.equal(ranked.result.error.code, 'ranking_unavailable');
  }
  const explained = await callTool('beatscope_explain_movie', { time: 20, context: 1 });
  if (rankedAvailable) {
    assert.equal(explained.result.ok, true, JSON.stringify(explained.result));
    assert.equal(explained.result.data.plan_version, 'voxel-phrase-2');
    assert.ok(Number.isInteger(explained.result.data.shot.index));
  } else {
    assert.equal(explained.result.ok, false);
    assert.equal(explained.result.error.code, 'ranking_unavailable');
  }

  // 8. seek, then audition: the visible transport moves and stops at the end
  const seek = await callTool('beatscope_control_playback', { action: 'seek', time: 12.5 });
  assert.equal(seek.result.ok, true);
  assert.ok(Math.abs(await page.evaluate(() => document.querySelector('audio').currentTime) - 12.5) < 0.05);
  assert.match(await page.textContent('.mv-strip'), /Seeked/);

  const audition = await callTool('beatscope_control_playback', { action: 'audition', start_time: 20, end_time: 21 });
  assert.equal(audition.result.ok, true);
  assert.equal(audition.result.data.started, true, 'autoplay is allowed in this launch');
  await page.waitForTimeout(1500);
  const stopped = await page.evaluate(() => document.querySelector('audio').currentTime);
  assert.ok(stopped >= 20.9 && stopped <= 21.3, `audition should stop at the range end, saw ${stopped}`);
  assert.match(await page.textContent('.mv-strip'), /Auditioning/);

  // 9. restore returns the pre-audition position and pauses
  const restore = await callTool('beatscope_control_playback', { action: 'restore' });
  assert.equal(restore.result.ok, true);
  assert.ok(Math.abs(restore.result.data.time - 12.5) < 0.05);
  assert.ok(Math.abs(await page.evaluate(() => document.querySelector('audio').currentTime) - 12.5) < 0.05);

  // 10. render: validation only, no heavy launch in this smoke. Which honest
  // refusal comes first depends on whether this session has a local renderer.
  const rejected = await callTool('beatscope_render_movie', { action: 'start', seed: 16777216 });
  assert.equal(rejected.result.ok, false, JSON.stringify(rejected.result));
  assert.equal(
    rejected.result.error.code,
    state.data.capabilities.rendering ? 'invalid_input' : 'render_unavailable',
  );

  // 11. the timing export asks for the same-origin archive, never its bytes
  const download = page.waitForEvent('download', { timeout: 10000 });
  const exported = await callTool('beatscope_export_timing_package');
  assert.equal(exported.result.ok, true, JSON.stringify(exported.result));
  const file = await download;
  assert.equal(new URL(file.url()).pathname, `/api/projects/${PROJECT_ID}/export/codex.zip`);
  assert.ok(!JSON.stringify(exported.result).includes('PK'), 'no archive bytes in the result');

  // 12. budgets: latency and serialized size (plan §12)
  const samples = { state: [], timing: [], response: [], movie: [] };
  for (let round = 0; round < 5; round += 1) {
    samples.state.push((await callTool('beatscope_get_studio_state')).ms);
    samples.timing.push((await callTool('beatscope_inspect_timing', { start_time: 0, end_time: 48, include: ['onsets'], limit: 200 })).ms);
    samples.response.push((await callTool('beatscope_get_response_events', { start_time: 0, end_time: 48, budget: 12 })).ms);
    samples.movie.push((await callTool('beatscope_explain_movie', { time: 20 })).ms);
  }
  const biggest = Math.max(...await Promise.all([
    'beatscope_get_studio_state',
    'beatscope_inspect_timing',
    'beatscope_get_response_events',
    'beatscope_explain_movie',
  ].map(async (name) => JSON.stringify((await callTool(
    name,
    name === 'beatscope_inspect_timing' ? { start_time: 0, end_time: 48, include: ['beats', 'onsets', 'cues'], limit: 200 }
      : name === 'beatscope_get_response_events' ? { start_time: 0, end_time: 48, budget: 64 }
        : name === 'beatscope_explain_movie' ? { time: 20, context: 3 } : {},
  )).result).length)));

  const budgets = [
    ['state p95 < 5 ms', p95(samples.state) < 5, p95(samples.state)],
    ['timing p95 < 15 ms', p95(samples.timing) < 15, p95(samples.timing)],
    ['response p95 < 15 ms', p95(samples.response) < 15, p95(samples.response)],
    ['movie p95 < 10 ms', p95(samples.movie) < 10, p95(samples.movie)],
    ['result <= 16000 code units', biggest <= 16000, biggest],
  ];

  // 13. leaving the page releases every registration
  await page.goto('about:blank');
  await page.waitForTimeout(300);
  assert.equal(abortedTools.length, 7, `pagehide must abort all seven registrations, saw ${abortedTools.length}`);

  assert.deepEqual(failures, [], 'the page logged no errors');

  console.log('Studio Director v2 browser round trip OK.');
  console.log(`  registered: ${registered.length} tools`);
  console.log(`  response ranking: ${rankedAvailable ? 'ranked events verified' : 'absent, honest ranking_unavailable verified'}`);
  for (const [label, ok, value] of budgets) console.log(`  ${ok ? 'ok  ' : 'OVER'} ${label} (${Number(value).toFixed(2)})`);
  if (budgets.some(([, ok]) => !ok)) process.exitCode = 1;
} finally {
  await browser.close();
}
