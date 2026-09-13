/**
 * Studio Director v2 contract tests (v0.12 WebMCP plan §11.1).
 *
 * Freezes the seven tool definitions, the shared envelopes, the error
 * vocabulary and the sanitizers. These tests also reject the vocabulary and
 * input shapes of the retired director, and prove that the snapshot bytes are
 * identical across two fresh Node processes.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { loadStudioWebmcp, loadStudioWebmcpResponses } from './helpers/studio-webmcp.mjs';
import { createFakePort, createModelContextHarness } from './helpers/studio-webmcp-harness.mjs';

const { TOOL_DEFINITIONS, TOOL_NAMES, LIMITS, ERROR_CODE_SET, RETIRED_TOKENS, FORBIDDEN_INPUT_KEYS, READ_ANNOTATIONS } =
  await loadStudioWebmcp();
const { success, failure, sanitizeLabel, sanitizeNumber, canonicalJson, resultCodeUnits, withinResultBudget } =
  await loadStudioWebmcpResponses();

const SNAPSHOT = new URL('./snapshots/studio-webmcp/tool-definitions.json', import.meta.url);
const RECORDER = fileURLToPath(new URL('./record_studio_webmcp_snapshots.mjs', import.meta.url));

const EXPECTED_TOOLS = [
  'beatscope_get_studio_state',
  'beatscope_inspect_timing',
  'beatscope_get_response_events',
  'beatscope_explain_movie',
  'beatscope_control_playback',
  'beatscope_render_movie',
  'beatscope_export_timing_package',
];

// --- the frozen catalog -----------------------------------------------------

test('exactly seven tools, in a stable order, with the beatscope_ prefix', () => {
  assert.deepEqual([...TOOL_NAMES], EXPECTED_TOOLS);
  assert.equal(TOOL_DEFINITIONS.length, 7);
  for (const tool of TOOL_DEFINITIONS) {
    assert.match(tool.name, /^beatscope_[a-z_]+$/, `tool name ${tool.name}`);
    assert.ok(tool.title.length > 0 && tool.description.length > 40, `${tool.name} needs a real title and description`);
  }
});

test('every schema is a closed object and never names a retired input', () => {
  const walk = (node, path) => {
    if (node === null || typeof node !== 'object') return;
    if (Array.isArray(node)) return node.forEach((item, index) => walk(item, `${path}[${index}]`));
    const record = node;
    if (record.type === 'object') {
      assert.equal(record.additionalProperties, false, `${path} must set additionalProperties: false`);
    }
    for (const [key, value] of Object.entries(record)) {
      if (key === 'properties' && value && typeof value === 'object') {
        for (const property of Object.keys(value)) {
          assert.ok(
            !FORBIDDEN_INPUT_KEYS.includes(property),
            `${path}.properties must not accept ${property}`,
          );
        }
      }
      walk(value, `${path}.${key}`);
    }
  };
  for (const tool of TOOL_DEFINITIONS) walk(tool.inputSchema, tool.name);
});

test('definitions carry no retired vocabulary and interpolate no project text', () => {
  const serialized = JSON.stringify(TOOL_DEFINITIONS).toLowerCase();
  for (const token of RETIRED_TOKENS) {
    assert.ok(!serialized.includes(token.toLowerCase()), `retired token returned: ${token}`);
  }
  // Frozen literals only: nothing project-shaped may appear in a definition.
  for (const pattern of [/\d+\s*bpm/, /\.mp3|\.wav|\.flac|\.m4a/, /[0-9a-f]{12}/]) {
    assert.ok(!pattern.test(serialized), `definition looks project-derived: ${pattern}`);
  }
});

test('annotations separate reads, page actions and consequential calls', () => {
  const byName = new Map(TOOL_DEFINITIONS.map((tool) => [tool.name, tool]));
  const readNames = [
    'beatscope_get_studio_state',
    'beatscope_inspect_timing',
    'beatscope_get_response_events',
    'beatscope_explain_movie',
  ];
  for (const name of readNames) {
    const tool = byName.get(name);
    assert.equal(tool.kind, 'read');
    assert.deepEqual({ ...tool.annotations }, { ...READ_ANNOTATIONS });
  }
  const playback = byName.get('beatscope_control_playback');
  assert.deepEqual({ ...playback.annotations }, { readOnlyHint: false, untrustedContentHint: true, consequentialHint: false });
  for (const name of ['beatscope_render_movie', 'beatscope_export_timing_package']) {
    assert.deepEqual(
      { ...byName.get(name).annotations },
      { readOnlyHint: false, untrustedContentHint: true, consequentialHint: true },
      `${name} must be marked consequential`,
    );
  }
});

test('the error vocabulary is the frozen list', () => {
  assert.deepEqual([...ERROR_CODE_SET], [
    'track_required', 'service_unavailable', 'invalid_input', 'invalid_range', 'out_of_range',
    'beat_grid_unavailable', 'ranking_unavailable', 'movie_plan_unavailable', 'playback_unavailable',
    'render_unavailable', 'render_busy', 'render_not_active', 'download_requires_user_action',
    'canceled', 'internal_error',
  ]);
});

test('limits match the plan budgets', () => {
  assert.equal(LIMITS.timing_seconds, 180);
  assert.equal(LIMITS.timing_bars, 64);
  assert.equal(LIMITS.timing_events, 200);
  assert.equal(LIMITS.response_events, 64);
  assert.equal(LIMITS.explanation_shots, 7);
  assert.equal(LIMITS.result_code_units, 16000);
  assert.equal(LIMITS.seed_max, 16777215);
});

// --- snapshot bytes ---------------------------------------------------------

test('the committed snapshot is the current catalog, byte for byte', () => {
  const expected = readFileSync(SNAPSHOT, 'utf8');
  const actual = canonicalJson({
    tools: TOOL_DEFINITIONS,
    error_codes: ERROR_CODE_SET,
    limits: LIMITS,
    retired_tokens: RETIRED_TOKENS,
    forbidden_input_keys: FORBIDDEN_INPUT_KEYS,
  });
  assert.equal(actual, expected, 'record with node tests/record_studio_webmcp_snapshots.mjs');
  assert.ok(actual.endsWith('\n'), 'canonical JSON ends with one LF');
});

test('snapshot bytes are identical across two fresh Node processes', () => {
  const record = () => execFileSync(process.execPath, [RECORDER], { encoding: 'utf8' });
  const first = record();
  const second = record();
  assert.equal(first, second, 'canonical bytes must not depend on the process');
  assert.ok(first.includes(readFileSync(SNAPSHOT, 'utf8').trim()), 'the catalog snapshot is one of the recorded bytes');
});

// --- envelopes and sanitizers ----------------------------------------------

test('success and failure envelopes are small, typed and instruction-free', () => {
  const ok = success('beatscope_get_studio_state', 'Shattered Heartbeat.mp3 is ready at 00:38.600.', { stage: 'preview' });
  assert.equal(ok.ok, true);
  assert.equal(ok.tool, 'beatscope_get_studio_state');
  assert.ok(withinResultBudget(ok));

  const bad = failure('beatscope_render_movie', 'render_busy', 'A movie render is already running at 42%.', 'Wait for it to finish or call this tool with action=cancel.');
  assert.equal(bad.ok, false);
  assert.equal(bad.error.code, 'render_busy');
  assert.ok(bad.error.next_action.length > 0, 'every failure carries one concrete next action');
  assert.ok(withinResultBudget(bad));
});

test('labels are flattened and truncated, never multi-line', () => {
  const messy = sanitizeLabel('Shattered\nHeartbeat\t.mp3\u0000  part two');
  assert.equal(messy, 'Shattered Heartbeat .mp3 part two');
  const long = sanitizeLabel('x'.repeat(400));
  assert.equal(long.length, LIMITS.label_characters);
  assert.equal(sanitizeLabel(undefined), '');
});

test('numbers stay finite, six-decimal and never negative zero', () => {
  assert.equal(sanitizeNumber(38.6000000001), 38.6);
  assert.equal(sanitizeNumber(-0), 0);
  assert.equal(sanitizeNumber(Number.NaN), null);
  assert.equal(sanitizeNumber(Number.POSITIVE_INFINITY), null);
  assert.equal(sanitizeNumber('12'), null);
});

test('canonical JSON sorts keys by code point, rounds and rejects non-finite values', () => {
  const canonical = canonicalJson({ b: 1, a: 2, 'ä': 3, A: 4 });
  assert.equal(canonical, '{"A":4,"a":2,"b":1,"ä":3}\n');
  assert.equal(canonicalJson({ value: -0 }), '{"value":0}\n');
  assert.equal(canonicalJson({ value: 0.0000004 }), '{"value":0}\n');
  assert.throws(() => canonicalJson({ value: Number.NaN }), TypeError);
  assert.throws(() => canonicalJson({ value: Number.POSITIVE_INFINITY }), TypeError);
});

test('the result budget is measured in UTF-16 code units of the serialized result', () => {
  const tiny = success('beatscope_get_studio_state', 'ok', {});
  assert.equal(resultCodeUnits(tiny), JSON.stringify(tiny).length);
  const big = success('beatscope_inspect_timing', 'ok', { events: Array.from({ length: 200 }, (_, id) => ({ id, time: id / 3 })) });
  assert.ok(withinResultBudget(big), '200 events still fit the budget');
  const tooBig = success('beatscope_inspect_timing', 'ok', { blob: 'x'.repeat(17000) });
  assert.equal(withinResultBudget(tooBig), false);
});

// --- test-only fixtures the later rounds build on ---------------------------

test('the model-context harness registers real definitions under one signal', async () => {
  const harness = createModelContextHarness();
  const controller = new AbortController();
  const probe = {
    name: 'beatscope_get_studio_state',
    title: 'probe',
    description: 'test probe definition',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false },
    execute: (input, { signal }) => Promise.resolve({ ok: true, echoed: input, live: !signal.aborted }),
  };
  await harness.modelContext.registerTool(probe, { signal: controller.signal });
  assert.deepEqual(harness.names(), ['beatscope_get_studio_state']);

  const result = await harness.execute('beatscope_get_studio_state', { sample: 1 });
  assert.deepEqual(result, { ok: true, echoed: { sample: 1 }, live: true });

  // The execution signal is the caller's: an aborted call is visible to the tool.
  const cancelled = new AbortController();
  cancelled.abort();
  assert.equal((await harness.execute('beatscope_get_studio_state', {}, { signal: cancelled.signal })).live, false);

  // Aborting the registration signal unregisters the tool, exactly once.
  controller.abort();
  assert.equal(harness.abortCount(), 1);
  assert.deepEqual(harness.names(), []);
  await assert.rejects(() => harness.execute('beatscope_get_studio_state'), /not registered/);
});

test('the fake port records calls and never reports success for a rejected action', async () => {
  const port = createFakePort();
  await port.play();
  port.pause();
  port.seek(12.5);
  assert.deepEqual(port.calls.map((call) => call.name), ['play', 'pause', 'seek']);
  assert.equal(port.snapshot().stage, 'preview');

  const blocked = createFakePort({
    play: async () => ({ playing: false, requiresUserGesture: true }),
  });
  assert.deepEqual(await blocked.play(), { playing: false, requiresUserGesture: true });
  assert.equal(blocked.calls.at(-1).name, 'play');
});
