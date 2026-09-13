import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compileComposition } from '../beatscope/web/composition-runtime.mjs';
const rhythm = { project_id: '123456789abc', source: { sha256: 'a'.repeat(64) }, beats: [], onsets: [
  { id: 1, time: .738, strength: .2, bands: { low: 1 } },
  { id: 2, time: .79, strength: 1, bands: { low: 1 } },
  { id: 3, time: 1.21, strength: .5, bands: { high: 1 } },
] };
const doc = { project_id: rhythm.project_id, source_rhythm_sha256: rhythm.source.sha256,
  objects: [{ id: 'text', opacity: .8 }], responses: [{ id: 'pulse', target_id: 'text', driver: 'ranked_onsets', band: 'all', motion: 'scale_pulse', amount: .2, release: .2, min_gap: .1 }] };
test('ranking selects exact off-grid timestamps and evaluation is seek-safe', () => {
  const before = JSON.stringify(rhythm);
  const engine = compileComposition(doc, rhythm, { events: [{ onset_id: 1, response_relevance: 1 }, { onset_id: 2, response_relevance: .1 }] });
  assert.deepEqual(engine.eventTimes[0].times, [.738, 1.21]);
  assert.equal(engine.at(.738).text.scale, 1.2);
  assert.equal(engine.at(.737).text.scale, 1);
  const times = [0, .738, .75, 1.21, 3];
  const first = times.map(t => JSON.stringify(engine.at(t)));
  for (const i of [4, 2, 0, 3, 1]) assert.equal(JSON.stringify(engine.at(times[i])), first[i]);
  assert.equal(engine.at(.738, true).text.scale, 1);
  assert.equal(JSON.stringify(rhythm), before);
});
test('no grid never manufactures beats; onset fallback survives', () => {
  const beats = compileComposition({ ...doc, responses: [{ ...doc.responses[0], driver: 'beats' }] }, rhythm);
  assert.equal(beats.diagnostics[0].unavailable, true); assert.equal(beats.at(.738).text.scale, 1);
  const onset = compileComposition(doc, rhythm);
  assert.equal(onset.diagnostics[0].source, 'onset-strength-fallback');
  assert.deepEqual(onset.eventTimes[0].times, [.79, 1.21]);
  assert.throws(() => compileComposition(doc, { ...rhythm, project_id: 'different' }), /identity/);
});
test('dense selection enforces minimum spacing and finite bounded response', () => {
  const source = { ...rhythm, onsets: Array.from({ length: 1500 }, (_, i) => ({ id: i, time: i / 50, strength: (i % 19) / 18 })) };
  const engine = compileComposition(doc, source);
  const times = engine.eventTimes[0].times;
  for (let i = 1; i < times.length; i++) assert.ok(times[i] - times[i - 1] >= .1);
  for (let i = 0; i < 1800; i++) { const state = engine.at(i / 60); assert.ok(state.text.scale >= 1 && state.text.scale <= 1.2); }
});
