/**
 * Studio Director v2 action tests (v0.12 WebMCP plan §11.3).
 *
 * Every kernel is exercised against the recording fake port: invalid input must
 * reach the page zero times, valid input exactly once, and a blocked or busy
 * outcome must never be reported as success.
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { loadStudioWebmcpModule } from './helpers/studio-webmcp.mjs';
import { FIXTURES, downbeatsOf, loadRhythmFixture, makeSnapshot } from './helpers/studio-webmcp-fixtures.mjs';
import { createFakePort } from './helpers/studio-webmcp-harness.mjs';

const { controlPlayback, renderMovie, exportTimingPackage, timeAtPosition } = await loadStudioWebmcpModule('actions');

const structured = loadRhythmFixture(FIXTURES.structured);
const callsOf = (port, name) => port.calls.filter((call) => call.name === name);
const activityOf = (port) => port.calls.filter((call) => call.name === 'recordAgentAction').map((call) => call.payload);

function readyPort(overrides = {}) {
  const snapshot = makeSnapshot(structured, overrides);
  // Both views carry the same facts: the fake's recording methods read
  // `snapshot`, the kernels read `snapshotNow`.
  return createFakePort({ snapshot, snapshotNow: () => makeSnapshot(structured, overrides), ...overrides });
}

// --- validation never reaches the page --------------------------------------

test('invalid playback input produces zero page calls and zero activity', async () => {
  const cases = [
    { action: 'play', time: 3 },
    { action: 'pause', bar: 2 },
    { action: 'seek' },
    { action: 'seek', time: 3, bar: 2 },
    { action: 'seek', beat: 2 },
    { action: 'seek', time: 3, start_time: 1, end_time: 2 },
    { action: 'audition' },
    { action: 'audition', time: 3 },
    { action: 'audition', start_time: 2, end_time: 2 },
    { action: 'audition', start_time: 0, end_time: 200 },
    { action: 'audition', start_time: 1, end_time: 2, start_bar: 1 },
    { action: 'nope' },
  ];
  for (const input of cases) {
    const port = readyPort();
    const result = await controlPlayback(port, input);
    assert.equal(result.ok, false, `${JSON.stringify(input)} must fail`);
    assert.ok(['invalid_input', 'invalid_range'].includes(result.error.code), `${JSON.stringify(input)} -> ${result.error.code}`);
    assert.deepEqual(port.calls, [], `${JSON.stringify(input)} must not reach the page`);
  }
});

test('invalid render and seed input never reaches the page', async () => {
  for (const input of [{ action: 'start', seed: -1 }, { action: 'start', seed: 16777216 }, { action: 'start', seed: 1.5 },
    { action: 'cancel', seed: 4 }, { action: 'cancel' }, { action: 'nope' }]) {
    const port = readyPort();
    const result = await renderMovie(port, input);
    assert.equal(result.ok, false);
    assert.ok(['invalid_input', 'render_not_active'].includes(result.error.code), `${JSON.stringify(input)} -> ${result.error.code}`);
    assert.deepEqual(port.calls, []);
  }
});

test('invalid render input wins over renderer availability', async () => {
  const port = readyPort({ rendererAvailable: false });
  const result = await renderMovie(port, { action: 'start', seed: 16777216 });
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'invalid_input');
  assert.equal(port.calls.length, 0);
});

// --- playback ---------------------------------------------------------------

test('play, pause and seek use the port exactly once', async () => {
  const port = readyPort();
  const played = await controlPlayback(port, { action: 'play' });
  assert.equal(played.ok, true);
  assert.equal(played.data.playing, true);
  assert.equal(callsOf(port, 'play').length, 1);

  const paused = await controlPlayback(port, { action: 'pause' });
  assert.equal(paused.data.playing, false);
  assert.equal(callsOf(port, 'pause').length, 1);

  const sought = await controlPlayback(port, { action: 'seek', time: 12.5 });
  assert.equal(sought.data.time, 12.5);
  assert.deepEqual(callsOf(port, 'seek')[0].payload, { time: 12.5 });
});

test('a blocked autoplay is reported, not hidden', async () => {
  const port = readyPort({ play: async () => ({ playing: false, requiresUserGesture: true }) });
  const result = await controlPlayback(port, { action: 'play' });
  assert.equal(result.ok, true);
  assert.equal(result.data.playing, false);
  assert.equal(result.data.requires_user_gesture, true);
  assert.match(result.summary, /gesture/i);
});

test('bar and beat seek convert through measured beats only', () => {
  assert.equal(timeAtPosition(structured, 1), downbeatsOf(structured)[0]);
  const second = timeAtPosition(structured, 2);
  assert.ok(second > 0 && second < structured.source.duration);
  const beatTwo = timeAtPosition(structured, 1, 2);
  assert.ok(beatTwo > 0);
  assert.throws(() => timeAtPosition(structured, 0), /Bar must be/);
  assert.throws(() => timeAtPosition(structured, 999), /Bar must be/);
  assert.throws(() => timeAtPosition(structured, 1, 99), /measured beats/);
  assert.throws(() => timeAtPosition({ ...structured, beats: [] }, 1), /no measured beat grid/);
});

test('audition validates, calls once, and reports the range', async () => {
  const port = readyPort();
  const result = await controlPlayback(port, { action: 'audition', start_time: 10, end_time: 16.5 });
  assert.equal(result.ok, true);
  assert.deepEqual(callsOf(port, 'audition')[0].payload, { start: 10, end: 16.5, autoplay: true });
  const [entry] = activityOf(port);
  assert.equal(entry.kind, 'playback');
  assert.equal(entry.action, 'audition');
  assert.equal(entry.restorable, true);
  assert.match(entry.label, /Auditioning 00:10\.0—00:16\.5/);
});

test('audition can be requested without autoplay, and restore reports the prior state', async () => {
  const port = readyPort();
  const auditioned = await controlPlayback(port, { action: 'audition', start_bar: 1, end_bar: 2, autoplay: false });
  assert.equal(auditioned.data.autoplay, false);
  assert.deepEqual(callsOf(port, 'audition')[0].payload, { start: downbeatsOf(structured)[0], end: timeAtPosition(structured, 3), autoplay: false });

  const restored = await controlPlayback(port, { action: 'restore' });
  assert.equal(restored.ok, true);
  assert.equal(restored.data.time, 0);
  assert.equal(callsOf(port, 'restoreAudition').length, 1);
});

test('restore without a snapshot fails honestly', async () => {
  const port = readyPort({ restoreAudition: async () => ({ restored: false, time: 0, playing: false }) });
  const result = await controlPlayback(port, { action: 'restore' });
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'playback_unavailable');
});

// --- render -----------------------------------------------------------------

test('render start reuses the current seed when omitted, and accepts the boundary seeds', async () => {
  const omitted = readyPort();
  const started = await renderMovie(omitted, { action: 'start' });
  assert.equal(started.ok, true);
  assert.equal(callsOf(omitted, 'render')[0].payload[1], undefined, 'the port decides the visible seed');
  assert.equal(started.data.seed, 7, 'and it is reported from the port');

  for (const seed of [0, 16777215]) {
    const port = readyPort({ render: async (action, value) => ({ action, job: null, seed: value }) });
    const result = await renderMovie(port, { action: 'start', seed });
    assert.equal(result.ok, true);
    assert.equal(result.data.seed, seed);
  }
});

test('an active render is never replaced', async () => {
  const port = readyPort({ movieJob: { id: 'job-9', state: 'running', progress: 0.42, video_ready: false } });
  const result = await renderMovie(port, { action: 'start' });
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'render_busy');
  assert.match(result.error.message, /42%/);
  assert.deepEqual(port.calls, []);
});

test('cancel reports render_not_active without a render, and cancels exactly once with one', async () => {
  const idle = readyPort();
  const nothing = await renderMovie(idle, { action: 'cancel' });
  assert.equal(nothing.error.code, 'render_not_active');
  assert.deepEqual(idle.calls, []);

  const busy = readyPort({ movieJob: { id: 'job-9', state: 'running', progress: 0.42, video_ready: false } });
  const cancelled = await renderMovie(busy, { action: 'cancel' });
  assert.equal(cancelled.ok, true);
  assert.equal(callsOf(busy, 'render').length, 1);
  assert.equal(activityOf(busy)[0].action, 'cancel');
  assert.equal(activityOf(busy)[0].restorable, false);
});

test('render is unavailable without a song or without a renderer', async () => {
  const empty = createFakePort({ snapshotNow: () => makeSnapshot(null, { stage: 'idle', duration: 0 }) });
  assert.equal((await renderMovie(empty, { action: 'start' })).error.code, 'render_unavailable');
  const noRenderer = readyPort({ rendererAvailable: false });
  assert.equal((await renderMovie(noRenderer, { action: 'start' })).error.code, 'render_unavailable');
  assert.deepEqual(empty.calls, []);
});

test('aborting a call stops waiting, and never claims an accepted render was cancelled', async () => {
  const controller = new AbortController();
  const port = readyPort({
    render: async (action, seed, signal) => {
      controller.abort();
      void signal;
      return { action, job: { id: 'job-1', state: 'running', progress: 0, video_ready: false }, seed: seed ?? 7 };
    },
  });
  const result = await renderMovie(port, { action: 'start' }, controller.signal);
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'canceled');
  assert.match(result.error.message, /continues/);
  assert.equal(callsOf(port, 'cancel').length, 0);
  assert.equal(callsOf(port, 'render')[0].payload[0], 'start');
});

test('an already-aborted signal fails before any page call', async () => {
  const controller = new AbortController();
  controller.abort();
  const port = readyPort();
  const result = await controlPlayback(port, { action: 'play' }, controller.signal);
  assert.equal(result.error.code, 'canceled');
  assert.deepEqual(port.calls, []);
});

// --- export -----------------------------------------------------------------

test('export starts the same-origin download and returns no archive bytes', async () => {
  const port = readyPort();
  const result = await exportTimingPackage(port);
  assert.equal(result.ok, true);
  assert.equal(result.data.filename, 'fixture.beatscope.zip');
  assert.deepEqual(callsOf(port, 'exportTimingPackage').length, 1);
  const serialized = JSON.stringify(result);
  for (const token of ['base64', 'PK', 'sha256']) assert.ok(!serialized.includes(token), `${token} must not travel`);
  assert.ok(result.data.includes.includes('timing facts'));
  assert.ok(result.data.excludes.includes('source audio'));
});

test('a blocked download is reported with the button next action', async () => {
  const port = readyPort({ exportTimingPackage: async () => ({ filename: 'x.zip', started: false, requires_user_action: true }) });
  const result = await exportTimingPackage(port);
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'download_requires_user_action');
  assert.match(result.error.next_action, /Data export button/);
});

test('export without a project fails as track_required', async () => {
  const port = createFakePort({ snapshotNow: () => makeSnapshot(null, { stage: 'idle', duration: 0 }) });
  const result = await exportTimingPackage(port);
  assert.equal(result.error.code, 'track_required');
  assert.deepEqual(port.calls, []);
});

// --- activity rules ---------------------------------------------------------

test('only page-changing calls append activity, and never more than one entry', async () => {
  const port = readyPort();
  await controlPlayback(port, { action: 'play' });
  await controlPlayback(port, { action: 'pause' });
  await controlPlayback(port, { action: 'audition', start_time: 1, end_time: 2 });
  assert.equal(activityOf(port).length, 3);
  assert.deepEqual(activityOf(port).map((entry) => entry.kind), ['playback', 'playback', 'playback']);

  const failing = readyPort();
  await controlPlayback(failing, { action: 'seek' });
  assert.deepEqual(activityOf(failing), [], 'a rejected call records nothing');
});
