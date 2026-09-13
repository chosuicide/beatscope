/**
 * Studio Director v2 query tests (v0.12 WebMCP plan §11.2).
 *
 * Covers boundary semantics, bar conversion on stored downbeats, pagination,
 * segment overlap, the ranked-event contract (including honest failure),
 * unknown structural families, and shot-for-shot agreement between the movie
 * explanation and a direct `makePlan` call.
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { createTrack } from '../beatscope/runtime/runtime.js';
import { makePlan } from '../beatscope/web/mv-plan.mjs';
import { loadStudioWebmcpModule } from './helpers/studio-webmcp.mjs';
import { FIXTURES, downbeatsOf, loadRhythmFixture, makeSnapshot, syntheticRelevance } from './helpers/studio-webmcp-fixtures.mjs';

const { inspectTiming, responseEvents, resolveRange, studioState } = await loadStudioWebmcpModule('timing');
const { explainMovie } = await loadStudioWebmcpModule('movie');
const { canonicalJson } = await loadStudioWebmcpModule('responses');

const structured = loadRhythmFixture(FIXTURES.structured);
const plain = loadRhythmFixture(FIXTURES.plain);
const variableTempo = loadRhythmFixture(FIXTURES.variableTempo);

const onsetsIn = (snapshot, start, end) => inspectTiming(snapshot, {
  start_time: start, end_time: end, include: ['onsets'], limit: 200,
});

// --- range semantics --------------------------------------------------------

test('a time window is (start, end], exactly like the runtime', () => {
  const snapshot = makeSnapshot(plain);
  const track = createTrack(plain, { responseRelevance: snapshot.responseRelevance });
  const result = onsetsIn(snapshot, 1.0, 3.0);
  assert.equal(result.ok, true);
  const returned = result.data.events.map((event) => ({ id: event.id, time: event.time }));
  const expected = track.between(1.0, 3.0).map((onset) => ({ id: onset.id, time: onset.time }));
  assert.deepEqual(returned, expected, 'onset identities and timestamps are the runtime\'s');
  for (const event of result.data.events) {
    assert.ok(event.time > 1.0 && event.time <= 3.0, `event at ${event.time} breaks (1, 3]`);
  }
});

test('onset payloads pass through byte-identical, bands included', () => {
  const snapshot = makeSnapshot(plain);
  const track = createTrack(plain, { responseRelevance: snapshot.responseRelevance });
  const result = onsetsIn(snapshot, 0, 8.0);
  const strip = ({ kind, ...rest }) => rest;
  assert.deepEqual(result.data.events.map(strip), track.between(0, 8.0));
  for (const event of result.data.events) {
    assert.deepEqual(Object.keys(event.bands).sort(), ['all', 'high', 'low', 'mid']);
  }
});

test('a bar window starts at the stored downbeat and excludes the next bar', () => {
  const snapshot = makeSnapshot(variableTempo);
  const downbeats = downbeatsOf(variableTempo);
  const range = resolveRange(snapshot, { start_bar: 3, end_bar: 3 }, { maxSeconds: 180, maxBars: 64 });
  assert.equal(range.startInclusive, true);
  assert.equal(range.start, downbeats[2]);
  assert.equal(range.end, downbeats[3]);

  const third = inspectTiming(snapshot, { start_bar: 3, end_bar: 3, include: ['beats', 'onsets'] });
  const fourth = inspectTiming(snapshot, { start_bar: 4, end_bar: 4, include: ['beats', 'onsets'] });
  const thirdTimes = third.data.events.map((event) => event.time);
  const fourthTimes = fourth.data.events.map((event) => event.time);
  assert.equal(thirdTimes[0], range.start, 'the first bar\'s downbeat is included');
  assert.ok(!thirdTimes.includes(range.end), 'the next bar\'s downbeat is not');
  assert.ok(fourthTimes.includes(range.end), 'it belongs to the next window');
  assert.equal(third.data.events.filter((event) => fourthTimes.includes(event.time) && event.kind === 'beat').length, 0);
});

test('the final measured bar ends at the source duration', () => {
  const snapshot = makeSnapshot(variableTempo);
  const downbeats = downbeatsOf(variableTempo);
  const range = resolveRange(snapshot, { start_bar: downbeats.length, end_bar: downbeats.length }, { maxSeconds: 180, maxBars: 64 });
  assert.equal(range.end, variableTempo.source.duration);
});

test('a song without a measured grid accepts time windows and refuses bars', () => {
  const gridless = { ...plain, beats: [] };
  const snapshot = makeSnapshot(gridless);
  const time = onsetsIn(snapshot, 0, 4.0);
  assert.equal(time.ok, true);
  assert.ok(time.data.total > 0);
  const bars = inspectTiming(snapshot, { start_bar: 1, end_bar: 2, include: ['onsets'] });
  assert.equal(bars.ok, false);
  assert.equal(bars.error.code, 'beat_grid_unavailable');
  assert.ok(bars.error.next_action.length > 0);
});

test('range validation rejects mixed, partial, reversed and oversized windows', () => {
  const snapshot = makeSnapshot(plain);
  const limits = { maxSeconds: 180, maxBars: 64 };
  const code = (input) => {
    try { resolveRange(snapshot, input, limits); return null; } catch (error) { return error.code; }
  };
  assert.equal(code({ start_time: 0, end_time: 4, start_bar: 1 }), 'invalid_input');
  assert.equal(code({ start_time: 0 }), 'invalid_input');
  assert.equal(code({}), 'invalid_input');
  assert.equal(code({ start_time: 4, end_time: 1 }), 'invalid_range');
  assert.equal(code({ start_time: 0, end_time: 181 }), 'invalid_range');
  assert.equal(code({ start_time: 99, end_time: 120 }), 'out_of_range');
  assert.equal(code({ start_bar: 0, end_bar: 1 }), 'out_of_range');
  assert.equal(code({ start_bar: 2, end_bar: 1 }), 'invalid_range');
  assert.equal(code({ start_bar: 1, end_bar: 999 }), 'invalid_range');
  assert.equal(code({ start_time: 0, end_time: 4 }), null);
  assert.equal(code({ start_bar: 1, end_bar: 2 }), null);
});

// --- pagination, segments, determinism --------------------------------------

test('pagination is stable and lossless', () => {
  const snapshot = makeSnapshot(structured);
  const all = inspectTiming(snapshot, { start_time: 0, end_time: 16, include: ['onsets'], limit: 200 });
  const first = inspectTiming(snapshot, { start_time: 0, end_time: 16, include: ['onsets'], limit: 25, offset: 0 });
  const second = inspectTiming(snapshot, { start_time: 0, end_time: 16, include: ['onsets'], limit: 25, offset: 25 });
  assert.equal(first.data.count, 25);
  assert.equal(first.data.has_more, true);
  assert.equal(first.data.next_offset, 25);
  assert.deepEqual(
    [...first.data.events, ...second.data.events].map((event) => event.id),
    all.data.events.slice(0, 50).map((event) => event.id),
  );
});

test('segments overlap the window like spans, not instants', () => {
  const snapshot = makeSnapshot(structured);
  const result = inspectTiming(snapshot, { start_time: 20.0, end_time: 21.0, include: ['segments'] });
  assert.equal(result.data.events.length, 1);
  const [segment] = result.data.events;
  assert.equal(segment.kind, 'segment');
  assert.equal(segment.family, 'B');
  assert.ok(segment.time < 20.0, 'the span starts before the window and still counts');
  assert.ok(segment.end > 21.0);
});

test('repeated identical queries return identical bytes', () => {
  const snapshot = makeSnapshot(structured);
  const call = () => canonicalJson(inspectTiming(snapshot, { start_bar: 5, end_bar: 9, include: ['beats', 'onsets', 'cues', 'segments', 'boundaries'] }));
  assert.equal(call(), call());
});

// --- ranked response events -------------------------------------------------

test('response events honour the budget, keep original identities and restore time order', () => {
  const snapshot = makeSnapshot(structured);
  const track = createTrack(structured, { responseRelevance: snapshot.responseRelevance });
  for (const budget of [1, 6, 64]) {
    const result = responseEvents(snapshot, { start_time: 0, end_time: 48, budget });
    assert.equal(result.ok, true);
    assert.ok(result.data.selected_count <= budget);
    assert.equal(result.data.available, true);
    assert.equal(result.data.semantics, 'bounded-ranking-value-not-probability-or-confidence');
    assert.ok(result.data.selected_count > 0);
    const returned = result.data.events;
    const times = returned.map((event) => event.time);
    assert.deepEqual(times, [...times].sort((left, right) => left - right), 'chronological for scheduling');
    const pool = track.between(0, 48).map((onset) => `${onset.id}@${onset.time}`);
    for (const event of returned) {
      assert.ok(pool.includes(`${event.id}@${event.time}`), 'the event is an original onset, unmoved');
    }
  }
});

test('the budget is a count, not a threshold: a higher budget never loses an event', () => {
  const snapshot = makeSnapshot(structured);
  const small = responseEvents(snapshot, { start_time: 0, end_time: 48, budget: 4 });
  const large = responseEvents(snapshot, { start_time: 0, end_time: 48, budget: 12 });
  const smallIds = new Set(small.data.events.map((event) => event.id));
  for (const id of smallIds) assert.ok(large.data.events.some((event) => event.id === id));
});

test('a band preference is one frozen order and stays deterministic', () => {
  const snapshot = makeSnapshot(structured);
  const call = () => canonicalJson(responseEvents(snapshot, { start_time: 0, end_time: 48, budget: 8, band: 'low' }));
  assert.equal(call(), call());
  const low = responseEvents(snapshot, { start_time: 0, end_time: 48, budget: 8, band: 'low' });
  assert.equal(low.data.strategy, 'band-evidence-then-response-relevance');
  assert.equal(low.data.band, 'low');
  const mixed = responseEvents(snapshot, { start_time: 0, end_time: 48, budget: 100 });
  assert.equal(mixed.ok, false);
  assert.equal(mixed.error.code, 'invalid_input');
});

test('missing ranking fails honestly instead of falling back to chronology', () => {
  const snapshot = makeSnapshot(structured, { responseRelevance: null });
  const result = responseEvents(snapshot, { start_time: 0, end_time: 48, budget: 6 });
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'ranking_unavailable');
  assert.match(result.error.next_action, /inspect_timing/);
  // Raw timing keeps working on the same song.
  assert.equal(onsetsIn(snapshot, 0, 4).ok, true);
});

// --- studio state and movie explanation -------------------------------------

test('studio state reports capabilities and never a cached project list', () => {
  const idle = studioState(makeSnapshot(null, { stage: 'idle', duration: 0 }));
  assert.equal(idle.ok, true);
  assert.equal(idle.data.track, null);
  assert.deepEqual(idle.data.capabilities, {
    timing_queries: false, ranked_events: false, movie_explanation: false,
    playback_actions: false, rendering: false, timing_export: false,
  });
  assert.equal(idle.data.playback.clock, 'none');

  const loaded = studioState(makeSnapshot(structured, { stage: 'complete', currentTime: 38.6 }));
  assert.equal(loaded.data.track.structural_segments, 3);
  assert.equal(loaded.data.track.response_relevance_available, true);
  assert.equal(loaded.data.track.beat_grid_available, true);
  assert.equal(loaded.data.playback.clock, 'film');
  assert.equal(loaded.data.movie.plan_version, 'voxel-phrase-2');
  assert.equal(loaded.data.movie.template, 'VOXEL INTERFERENCE');
  assert.equal(loaded.data.capabilities.movie_explanation, true);
  assert.ok(!('projects' in loaded.data));
});

test('the movie explanation matches the shipping plan shot for shot', () => {
  // Fixed structure, plain two-bar song, variable tempo, and a stripped beat
  // grid: the explanation must follow makePlan on every one of them.
  const gridless = { ...plain, beats: [] };
  for (const rhythm of [structured, plain, variableTempo, gridless]) {
    const snapshot = makeSnapshot(rhythm);
    const track = createTrack(rhythm, { responseRelevance: snapshot.responseRelevance });
    const plan = makePlan(rhythm, track.responseBetween(0, rhythm.source.duration), snapshot.seed);
    assert.ok(plan.shots.length > 0);
    for (let index = 0; index < plan.shots.length; index += 1) {
      const explained = explainMovie(snapshot, { shot_index: index, context: 0 });
      assert.equal(explained.ok, true, `shot ${index} must be explainable`);
      const shot = explained.data.shot;
      const expected = plan.shots[index];
      assert.equal(shot.start, expected.start);
      assert.equal(shot.end, expected.end);
      assert.equal(shot.family, expected.family);
      assert.equal(shot.world, expected.world);
      assert.equal(shot.entry.kind, expected.kind);
      if (expected.kind === 'onset') assert.equal(String(shot.entry.onset_id), String(expected.eventId));
      if (expected.kind === 'structure') assert.equal(String(shot.entry.segment_id), String(expected.eventId));
    }
    assert.equal(explainMovie(snapshot, { shot_index: 0 }).data.plan_version, plan.version);
  }
});

test('the explanation keeps the fixedsong contract on a two-bar song', () => {
  const snapshot = makeSnapshot(plain);
  const track = createTrack(plain, { responseRelevance: snapshot.responseRelevance });
  const plan = makePlan(plain, track.responseBetween(0, plain.source.duration), snapshot.seed);

  for (let index = 0; index < plan.shots.length; index += 1) {
    const explained = explainMovie(snapshot, { shot_index: index, context: 0 });
    assert.equal(explained.ok, true, `shot ${index} must be explainable`);
    const shot = explained.data.shot;
    const expected = plan.shots[index];
    assert.equal(shot.start, expected.start);
    assert.equal(shot.end, expected.end);
    assert.equal(shot.family, expected.family);
    assert.equal(shot.world, expected.world);
    assert.equal(shot.entry.kind, expected.kind);
    if (expected.kind === 'onset') assert.equal(String(shot.entry.onset_id), String(expected.eventId));
    if (expected.kind === 'structure') assert.equal(String(shot.entry.segment_id), String(expected.eventId));
  }
  assert.equal(explainMovie(snapshot, { shot_index: 0 }).data.plan_version, plan.version);
});

test('explaining by time finds the same shot, and context stays bounded', () => {
  const snapshot = makeSnapshot(structured);
  const target = 20.0;
  const byTime = explainMovie(snapshot, { time: target, context: 3 });
  assert.equal(byTime.ok, true);
  assert.ok(byTime.data.shot.start <= target && byTime.data.shot.end > target);
  assert.ok(byTime.data.neighbors.length <= 6);
  const byIndex = explainMovie(snapshot, { shot_index: byTime.data.shot.index, context: 3 });
  assert.deepEqual(byIndex.data.shot, byTime.data.shot);
});

test('an unknown structural family still yields deterministic worlds', () => {
  const mutated = {
    ...structured,
    patterns: {
      ...structured.patterns,
      segments: structured.patterns.segments.map((segment) => ({ ...segment, family: 'BREAK' })),
    },
  };
  const snapshot = makeSnapshot(mutated);
  const first = explainMovie(snapshot, { shot_index: 1 });
  const second = explainMovie(snapshot, { shot_index: 1 });
  assert.equal(first.ok, true);
  assert.equal(canonicalJson(first), canonicalJson(second));
  assert.ok(Number.isInteger(first.data.shot.world));
});

test('explanation failures are honest and specific', () => {
  const noRanking = makeSnapshot(structured, { responseRelevance: null });
  assert.equal(explainMovie(noRanking, { time: 1 }).error.code, 'ranking_unavailable');
  assert.equal(explainMovie(makeSnapshot(structured), {}).ok, true, 'defaults to the playhead');
  assert.equal(explainMovie(makeSnapshot(structured), { time: 1, shot_index: 0 }).error.code, 'invalid_input');
  assert.equal(explainMovie(makeSnapshot(structured), { shot_index: 9999 }).error.code, 'out_of_range');
  assert.equal(explainMovie(makeSnapshot(structured), { time: 9999 }).error.code, 'out_of_range');
  assert.equal(explainMovie(makeSnapshot(null), { time: 1 }).error.code, 'track_required');
});

test('a different seed produces a different but equally explainable plan', () => {
  const a = makeSnapshot(structured, { seed: 1 });
  const b = makeSnapshot(structured, { seed: 1042 });
  const first = explainMovie(a, { time: 20 });
  const second = explainMovie(b, { time: 20 });
  assert.equal(first.ok, true);
  assert.equal(second.ok, true);
  assert.equal(first.data.seed, 1);
  assert.equal(second.data.seed, 1042);
  assert.equal(first.data.shot.start, second.data.shot.start, 'cuts come from the measured facts, not the seed');
});

test('the sidecar is a cached read, not a second analysis', () => {
  const snapshot = makeSnapshot(structured);
  // Two calls in a row must agree byte for byte, including relevance values.
  assert.equal(canonicalJson(explainMovie(snapshot, { time: 20 })), canonicalJson(explainMovie(snapshot, { time: 20 })));
  const relevance = syntheticRelevance(structured);
  assert.equal(relevance.events.length, structured.onsets.length);
  for (const row of relevance.events) {
    assert.ok(row.response_relevance >= 0 && row.response_relevance <= 1);
  }
});

// --- committed snapshots ----------------------------------------------------

test('every committed query snapshot is the current output, byte for byte', async () => {
  const { readFileSync } = await import('node:fs');
  const cases = [
    ['idle-state', studioState(makeSnapshot(null, { stage: 'idle', name: '', duration: 0 }))],
    ['loaded-state', studioState(makeSnapshot(structured, { stage: 'complete', currentTime: 38.6 }))],
    ['timing-window', inspectTiming(makeSnapshot(plain), { start_time: 1, end_time: 3, include: ['beats', 'onsets', 'cues'], limit: 50 })],
    ['ranked-events', responseEvents(makeSnapshot(structured), { start_time: 0, end_time: 48, budget: 6 })],
    ['movie-explanation', explainMovie(makeSnapshot(structured), { time: 20, context: 1 })],
  ];
  for (const [name, payload] of cases) {
    const committed = readFileSync(new URL(`./snapshots/studio-webmcp/${name}.json`, import.meta.url), 'utf8');
    assert.equal(canonicalJson(payload), committed, `${name} diverged; re-record with node tests/record_studio_webmcp_snapshots.mjs`);
  }
});
