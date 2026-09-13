import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { compileReflectedResponse, createReflectedPreset, STUDY_PRESET } from '../beatscope/web/reflected-response-study.mjs';
const require = createRequire(import.meta.url);
const original = require('../web-src/node_modules/butterchurn-presets').getPresets()[STUDY_PRESET];
const rhythm = { project_id: 'song', source: { sha256: 'source' }, onsets: [
  { id: 'a', time: .738, strength: .4 }, { id: 'b', time: .79, strength: 1 }, { id: 'c', time: 1.4, strength: .7 },
] };
const rank = { events: [{ onset_id: 'a', response_relevance: .9 }, { onset_id: 'b', response_relevance: .2 }] };
test('ranked original times, no-grid, silence, seek order, off and zero amount', () => {
  const c = compileReflectedResponse(rhythm, rank);
  assert.deepEqual(c.times, [.738, 1.4]);
  assert.equal(c.at(.73).pulse, 0); assert.ok(c.at(.85).pulse > 0);
  const expected = c.at(.8); c.at(200); c.at(0); assert.deepEqual(c.at(.8), expected);
  assert.equal(c.at(.738, false).pulse, 0);
  assert.equal(compileReflectedResponse(rhythm, rank, { amount: 0 }).at(.738).pulse, 0);
  assert.equal(compileReflectedResponse({ ...rhythm, onsets: [] }, null).at(10).pulse, 0);
  assert.ok(compileReflectedResponse(rhythm, rank, { gap: .01 }).times.length > c.times.length);
});
test('preserves material shaders; audio cannot affect action uniforms or emissions', () => {
  const before = JSON.stringify(original), c = compileReflectedResponse(rhythm, rank);
  let enabled = true;
  const p = createReflectedPreset(original, () => c.at(.738, enabled));
  assert.ok(p.warp.includes('8.0 * q30')); assert.equal(p.comp, original.comp);
  assert.equal(JSON.stringify(original), before);
  assert.equal(p.baseVals.wave_a, 0);
  assert.equal(p.waves[0].point_eqs({ sample: .2, value1: 0 }).x, p.waves[0].point_eqs({ sample: .2, value1: 999 }).x);
  const low = p.frame_eqs({ bass: 0 }), high = p.frame_eqs({ bass: 1000 });
  for (const key of ['q1', 'q2', 'q27', 'q32']) assert.equal(low[key], high[key]);
  assert.ok(p.shapes[1].frame_eqs({}).a > 0);
  enabled = false;
  for (const shape of p.shapes.slice(1)) assert.equal(shape.frame_eqs({}).a, 0);
  assert.equal(p.frame_eqs({}).q30, 0);
  assert.equal(p.shapes[0].frame_eqs({}).a, 0, 'off means no new illumination');
});
test('continuous curves drive motion without events; velocity integrates rather than teleporting', () => {
  const energy = { fps: 10, start: 0, bands: Object.fromEntries(['all','low','mid','high'].map(b => [b, Array(100).fill(.6)])) };
  const c = compileReflectedResponse({ ...rhythm, onsets: [], energy }, null);
  assert.ok(c.at(2).phase > c.at(1).phase); assert.ok(c.at(1).speed > 0);
  assert.equal(c.at(2, false).speed, 0);
  const blank = compileReflectedResponse({ ...rhythm, onsets: [] }, null);
  assert.equal(blank.at(2).phase, 0); assert.equal(blank.at(2).speed, 0);
  const eventOnly = compileReflectedResponse(rhythm, rank);
  assert.ok(eventOnly.at(1.1).phase > eventOnly.at(.95).phase, 'motion continues between events');
  for (let t = .7; t < 2; t += .001) {
    assert.ok(Math.abs(eventOnly.at(t+.001).x-eventOnly.at(t).x) < .002, 'no position jumps at onsets');
  }
  const again = compileReflectedResponse({ ...rhythm, onsets: [], energy }, null);
  assert.deepEqual(c.at(2), again.at(2));
});
