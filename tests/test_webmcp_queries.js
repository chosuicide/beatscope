/**
 * Director read-tool contract tests (v0.10 plan sections 8-12, 18.1).
 *
 * Every query is a pure function of (project, runtime track, input): the
 * same call returns byte-identical JSON, leaks no paths or raw arrays, and
 * rejects malformed input before anything is built. The snapshot files in
 * tests/snapshots/webmcp/ freeze the exact bytes; re-record only with the
 * explicit --accept recorder, never by hand.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';

import {
  barRange,
  previousBeatTime,
  projectContext,
  stateAtTime,
  eventsWindow,
  findVisualMoments,
  compareRanges,
} from '../beatscope/web/webmcp/queries.js';
import { WebMcpError } from '../beatscope/web/webmcp/responses.js';
import { trackForProject } from '../beatscope/runtime/runtime.js';
import {
  makeStructuredProject,
  makeQuietProject,
  makeLegacyProject,
  loadProject,
  state,
} from './webmcp_fixtures.mjs';

const MOMENT_KINDS = [
  'structural_transition',
  'strong_transient',
  'energy_lift',
  'energy_drop',
  'quiet_contrast',
];
const INCLUDES = ['beats', 'onsets', 'segments', 'boundaries', 'cues'];

const snapshot = (name) => JSON.parse(
  readFileSync(new URL(`./snapshots/webmcp/${name}.json`, import.meta.url), 'utf-8'),
);

function pageFor(project, overrides = {}) {
  loadProject(project);
  return {
    project: state.project,
    track: trackForProject(state.project),
    playbackTime: 0,
    isPlaying: false,
    loop: false,
    loopSelection: null,
    subdivision: 16,
    adjustments: state.adjustments,
    ...overrides,
  };
}

async function assertCode(callable, code) {
  try {
    await callable();
  } catch (error) {
    assert.ok(error instanceof WebMcpError, `expected WebMcpError, got ${error}`);
    assert.equal(error.code, code);
    return;
  }
  assert.fail(`expected WebMcpError ${code}`);
}

/** Every number in a tool response is finite (plan 18.1 #12). */
function assertFiniteDeep(value, path = '$') {
  if (typeof value === 'number') {
    assert.ok(Number.isFinite(value), `${path} is not finite: ${value}`);
  } else if (Array.isArray(value)) {
    value.forEach((item, index) => assertFiniteDeep(item, `${path}[${index}]`));
  } else if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) assertFiniteDeep(item, `${path}.${key}`);
  }
}

/** context carries no source paths, ids, hashes, or raw energy arrays. */
const BANNED_CONTEXT_KEYS = new Set(['file', 'path', 'id', 'energy', 'sha256', 'project_id']);
function assertNoLeaks(value, path = '$') {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoLeaks(item, `${path}[${index}]`));
    return;
  }
  if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      assert.ok(!BANNED_CONTEXT_KEYS.has(key.toLowerCase()), `leaky key ${path}.${key}`);
      assert.ok(
        typeof item !== 'string' || !(item.includes('/') || item.includes('\\')),
        `path-like value ${path}.${key}=${item}`,
      );
      assertNoLeaks(item, `${path}.${key}`);
    }
  }
}

// --- 1. project context leaks no paths, ids, or energy arrays --------------
{
  const page = pageFor(makeStructuredProject());
  const context = projectContext(page);
  assert.equal(context.ok, true);
  assert.equal(context.track.displayName, 'Director Fixture');
  assertNoLeaks(context);
}

// --- 2. playback position agrees with track.at() ---------------------------
{
  const page = pageFor(makeStructuredProject(), { playbackTime: 13.3 });
  const context = projectContext(page);
  const raw = page.track.at(13.3);
  assert.equal(context.playback.time, 13.3);
  assert.equal(context.playback.bar, raw.bar);
  assert.equal(context.playback.beat, raw.beat);
  assert.equal(context.playback.playing, false);
  assert.equal(context.playback.loop.enabled, false);
}

// --- 3. a legacy project reports structure honestly -------------------------
{
  const page = pageFor(makeLegacyProject());
  const context = projectContext(page);
  assert.equal(context.structure.available, false);
  assert.equal(context.structure.current, null);
  assert.equal(context.structure.total, 0);
  assert.equal(context.structure.segments.length, 0);
  const at = stateAtTime(page, { time: 1 });
  assert.equal(at.structure, null);
}

// --- 4. structural transitions order stably by score ------------------------
{
  const page = pageFor(makeStructuredProject());
  const first = findVisualMoments(page, { kind: 'structural_transition' });
  // novelty 0.9 (bar 17) > 0.72 (bar 25) > 0.55 (bar 9)
  assert.deepEqual(
    first.candidates.map((candidate) => [candidate.startBar, candidate.endBar]),
    [[17, 24], [25, 32], [9, 16]],
  );
  const second = findVisualMoments(page, { kind: 'structural_transition' });
  assert.deepEqual(first, second);
}

// --- 5. strong transients claim each bar once -------------------------------
{
  const page = pageFor(makeStructuredProject());
  const result = findVisualMoments(page, { kind: 'strong_transient', limit: 8 });
  assert.ok(result.candidates.length >= 1, 'fixture has transients');
  const covered = new Set();
  for (const candidate of result.candidates) {
    for (let bar = candidate.startBar; bar <= candidate.endBar; bar += 1) {
      assert.ok(!covered.has(bar), `bar ${bar} claimed by two candidates`);
      covered.add(bar);
    }
    assert.ok(
      candidate.anchorTime >= candidate.startTime && candidate.anchorTime < candidate.endTime,
      `anchor ${candidate.anchorTime} outside ${candidate.id}`,
    );
  }
}

// --- 6. energy lifts anchor at real bar times -------------------------------
{
  const page = pageFor(makeStructuredProject());
  const result = findVisualMoments(page, { kind: 'energy_lift' });
  assert.ok(result.candidates.length >= 1);
  for (const candidate of result.candidates) {
    const expected = barRange(page, candidate.startBar, candidate.startBar).startTime;
    assert.equal(candidate.startTime, expected, candidate.id);
  }
  assert.equal(result.candidates[0].startTime, 32); // bar 17 downbeat: 16 bars × 2 s
}

// --- 7. variable-tempo pre-roll walks the stored beat array -----------------
{
  const project = JSON.parse(
    await readFile(new URL('./fixtures/runtime/variable-tempo-project.json', import.meta.url), 'utf-8'),
  );
  const beatTimes = project.beats.map((beat) => beat.time ?? beat.raw_time);
  const anchorIndex = 30;
  const anchor = beatTimes[anchorIndex] + 0.001;
  const preRoll = previousBeatTime(project, anchor, 2);
  assert.equal(preRoll.source, 'stored-beats');
  assert.equal(preRoll.time, beatTimes[anchorIndex - 2]);
  // The global-BPM shortcut would land somewhere else in this fixture.
  const globalBpm = project.tempo.global_bpm ?? project.tempo.bpm;
  const globalGuess = Number((anchor - 2 * (60 / globalBpm)).toFixed(4));
  assert.notEqual(preRoll.time, globalGuess);
  const page = pageFor(project);
  const context = projectContext(page);
  assert.equal(context.track.variableTempo, true);
  assert.equal(context.track.globalBpm, 129.92);
}

// --- 8. candidate ids are stable and derived from the window ----------------
{
  const page = pageFor(makeStructuredProject());
  for (const kind of MOMENT_KINDS) {
    const result = findVisualMoments(page, { kind });
    for (const candidate of result.candidates) {
      assert.equal(candidate.id, `${kind}:${candidate.startBar}-${candidate.endBar}`);
      assert.equal(candidate.rank, result.candidates.indexOf(candidate) + 1);
      assert.ok(candidate.reason.length >= 8, `${kind} reason is a real sentence`);
    }
  }
}

// --- 9. the candidate limit clamps to at most 8 -----------------------------
{
  const page = pageFor(makeStructuredProject());
  const many = findVisualMoments(page, { kind: 'strong_transient', limit: 50 });
  assert.ok(many.candidates.length <= 8);
  const one = findVisualMoments(page, { kind: 'strong_transient', limit: 0 });
  assert.equal(one.candidates.length, 1);
}

// --- 10. overlapping candidates are deduped ---------------------------------
{
  const page = pageFor(makeStructuredProject());
  const result = findVisualMoments(page, { kind: 'energy_lift', windowBars: 4, limit: 8 });
  for (let i = 0; i < result.candidates.length; i += 1) {
    for (let j = i + 1; j < result.candidates.length; j += 1) {
      const a = result.candidates[i];
      const b = result.candidates[j];
      const shared = Math.min(a.endBar, b.endBar) - Math.max(a.startBar, b.startBar) + 1;
      const shorter = Math.min(a.endBar - a.startBar, b.endBar - b.startBar) + 1;
      assert.ok(shared / shorter <= 0.5, `candidates ${a.id} and ${b.id} overlap`);
    }
  }
}

// --- 11. range comparison is deterministic ----------------------------------
{
  const page = pageFor(makeStructuredProject());
  const input = {
    ranges: [
      { label: 'First A', startBar: 1, endBar: 8 },
      { label: 'A-prime', startBar: 9, endBar: 16 },
    ],
  };
  const one = compareRanges(page, input);
  const two = compareRanges(page, input);
  assert.deepEqual(one, two);
  assert.equal(one.ok, true);
  assert.equal(one.ranges[0].label, 'First A');
  assert.equal(one.ranges[1].label, 'A-prime');
  assert.ok(one.differences.length >= 1);
  assert.ok(one.differences.every((line) => typeof line === 'string' && line.length > 0));
}

// --- 12. zero energy never produces Infinity/NaN ----------------------------
{
  const page = pageFor(makeQuietProject());
  const results = [
    projectContext(page),
    stateAtTime(page, { time: 1 }),
    eventsWindow(page, { startBar: 1, endBar: 4, include: INCLUDES }),
    // The 4-bar quiet fixture cannot host the default 8-bar window, so the
    // quiet-window query runs at its smallest legal size.
    findVisualMoments(page, { kind: 'quiet_contrast', windowBars: 4 }),
    compareRanges(page, { ranges: [{ startBar: 1, endBar: 2 }, { startBar: 3, endBar: 4 }] }),
  ];
  for (const result of results) assertFiniteDeep(result);
  const text = JSON.stringify(results);
  assert.ok(!text.includes('Infinity'));
  assert.ok(!text.includes('NaN'));
}

// --- 13. invalid bars, inverted ranges, and out-of-bounds are rejected ------
{
  const page = pageFor(makeStructuredProject());
  await assertCode(() => barRange(page, 0, 8), 'INVALID_RANGE');
  await assertCode(() => barRange(page, 5, 3), 'INVALID_RANGE');
  await assertCode(() => barRange(page, 1.5, 8), 'INVALID_RANGE');
  await assertCode(() => barRange(page, 1, 33), 'OUT_OF_RANGE');
  await assertCode(() => stateAtTime(page, { time: 'abc' }), 'INVALID_RANGE');
  // Out-of-range times clamp instead of throwing (plan section 9.3).
  assert.equal(stateAtTime(page, { time: -4 }).time, 0);
  assert.equal(stateAtTime(page, { time: 999 }).time, 64);
  await assertCode(() => eventsWindow(page, { startBar: 8, endBar: 2 }), 'INVALID_RANGE');
  await assertCode(() => eventsWindow(page, { startTime: 4, endTime: 1 }), 'INVALID_RANGE');
  await assertCode(() => eventsWindow(page, { startTime: 0, endTime: 4, startBar: 1, endBar: 8 }), 'INVALID_RANGE');
  await assertCode(() => eventsWindow(page, { startBar: 1, endBar: 65 }), 'INVALID_RANGE');
  await assertCode(() => findVisualMoments(page, { kind: 'nope' }), 'INVALID_RANGE');
  await assertCode(() => findVisualMoments(page, { kind: 'energy_lift', windowBars: 5 }), 'INVALID_RANGE');
  await assertCode(() => compareRanges(page, { ranges: [{ startBar: 1, endBar: 4 }] }), 'INVALID_RANGE');
  await assertCode(
    () => compareRanges(page, { ranges: [{ startBar: 1, endBar: 4 }, { startBar: 1, endBar: 99 }] }),
    'OUT_OF_RANGE',
  );
}

// --- 14. every result JSON-serializes and round-trips -----------------------
{
  const page = pageFor(makeStructuredProject(), { playbackTime: 8 });
  const results = {
    context: projectContext(page),
    state: stateAtTime(page, { time: 8.5 }),
    stateNow: stateAtTime(page, {}),
    events: eventsWindow(page, { startBar: 1, endBar: 8, include: INCLUDES, limit: 200 }),
    moments: findVisualMoments(page, { kind: 'structural_transition' }),
    compare: compareRanges(page, {
      ranges: [{ startBar: 1, endBar: 8 }, { startBar: 17, endBar: 24 }],
    }),
  };
  for (const [name, result] of Object.entries(results)) {
    const text = JSON.stringify(result);
    assert.deepEqual(JSON.parse(text), result, `${name} must round-trip through JSON`);
  }
}

// --- 15. identical inputs return deep-equal results -------------------------
{
  const page = pageFor(makeStructuredProject(), { playbackTime: 20 });
  const calls = [
    () => projectContext(page),
    () => stateAtTime(page, { time: 20.5 }),
    () => eventsWindow(page, { startBar: 17, endBar: 24, include: INCLUDES, limit: 200 }),
    () => findVisualMoments(page, { kind: 'energy_drop', windowBars: 4 }),
    () => compareRanges(page, {
      ranges: [
        { startBar: 1, endBar: 8 },
        { startBar: 9, endBar: 16 },
        { startBar: 17, endBar: 24 },
        { startBar: 25, endBar: 32 },
      ],
    }),
  ];
  for (const call of calls) assert.deepEqual(call(), call());
}

// --- frozen snapshots (plan 18.6) -------------------------------------------
{
  const page = pageFor(makeStructuredProject());
  assert.deepEqual(projectContext(page), snapshot('project-context'));
}
{
  const page = pageFor(makeStructuredProject());
  const expected = snapshot('state-at-boundary');
  assert.deepEqual(stateAtTime(page, { time: 31.9 }), expected.before);
  assert.deepEqual(stateAtTime(page, { time: 32 }), expected.at);
  assert.deepEqual(stateAtTime(page, { time: 32.1 }), expected.after);
}
{
  const page = pageFor(makeStructuredProject());
  assert.deepEqual(
    eventsWindow(page, { startBar: 17, endBar: 24, include: INCLUDES, limit: 200 }),
    snapshot('events-window'),
  );
}
{
  const page = pageFor(makeStructuredProject());
  const expected = snapshot('visual-moments');
  for (const kind of MOMENT_KINDS) {
    assert.deepEqual(findVisualMoments(page, { kind }), expected[kind], kind);
  }
}
{
  const page = pageFor(makeStructuredProject());
  assert.deepEqual(
    compareRanges(page, {
      ranges: [
        { label: 'First A', startBar: 1, endBar: 8 },
        { label: 'A-prime', startBar: 9, endBar: 16 },
      ],
    }),
    snapshot('range-comparison'),
  );
}
