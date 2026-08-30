/**
 * Characterization for the web playbackState adapter (v0.6.1 plan commit 1):
 * pin the exact field contract and sqrt energy compression that the layered
 * stage and the Canvas fallback will consume, so the renderer refactor
 * cannot silently change the visual input.
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { playbackState } from '../beatscope/web/renderer.js';
import { createTrack } from '../beatscope/runtime/runtime.js';
import { assertFiniteFrame } from './helpers/visual-frame.js';

const project = JSON.parse(
  await readFile(new URL('./fixtures/runtime/characterization-project.json', import.meta.url), 'utf-8'),
);
const variableProject = JSON.parse(
  await readFile(new URL('./fixtures/runtime/variable-tempo-project.json', import.meta.url), 'utf-8'),
);

const FIELDS = [
  'time', 'bar', 'beat', 'beatPhase', 'barPhase',
  'low', 'mid', 'high', 'all', 'onset', 'accent', 'onsetAge', 'beatPulse', 'section',
];

// Field contract: exactly the documented keys, same order-independent set.
{
  const state = playbackState(project, 1.25);
  assert.deepEqual(Object.keys(state).sort(), FIELDS.slice().sort());
}

// Energy is sqrt-compressed against the raw runtime facts; phase fields pass
// through; beatPulse is the documented exp decay of beatPhase.
{
  const track = createTrack(project);
  for (const time of [0, 0.125, 0.6, 1.375, 2.5, 3.5, 5.5]) {
    const state = playbackState(project, time);
    const raw = track.at(time);
    assert.equal(state.time, time);
    assert.equal(state.bar, raw.bar);
    assert.equal(state.beat, raw.beat);
    assert.ok(Math.abs(state.beatPhase - raw.beatPhase) < 1e-15);
    assert.ok(Math.abs(state.barPhase - raw.barPhase) < 1e-15);
    for (const band of ['low', 'mid', 'high', 'all']) {
      assert.ok(Math.abs(state[band] - Math.sqrt(raw[band])) < 1e-15, `${band} at t=${time}`);
    }
    assert.ok(Math.abs(state.beatPulse - Math.exp(-raw.beatPhase * 7)) < 1e-15);
    assert.equal(state.onset, raw.onset.value);
    assert.equal(state.onsetAge, raw.onset.age);
    assert.equal(state.accent, raw.accent ? raw.accent.value : 0);
    // Every sampled state is finite (onsetAge may be the Infinity sentinel).
    assertFiniteFrame(state, ['onsetAge'], `playbackState(t=${time})`);
  }
}

// Variable tempo: phase facts stay inside [0, 1) across the tempo seam and
// the energy compression rule is unchanged.
{
  const track = createTrack(variableProject);
  const boundary = variableProject.tempo.segments[1].start;
  for (const time of [1.0, boundary - 0.001, boundary, boundary + 0.001, 12.0]) {
    const state = playbackState(variableProject, time);
    const raw = track.at(time);
    assert.ok(state.beatPhase >= 0 && state.beatPhase < 1, `beatPhase at t=${time}`);
    assert.ok(state.barPhase >= 0 && state.barPhase < 1, `barPhase at t=${time}`);
    assert.ok(Math.abs(state.low - Math.sqrt(raw.low)) < 1e-15);
  }
  // Bars never move backwards around the seam.
  const before = playbackState(variableProject, boundary - 0.002).bar;
  const after = playbackState(variableProject, boundary + 0.002).bar;
  assert.ok(after >= before);
}

// Determinism: identical queries return identical plain objects.
assert.deepEqual(playbackState(project, 1.375), playbackState(project, 1.375));
assert.deepEqual(playbackState(variableProject, 8.0), playbackState(variableProject, 8.0));

// Out-of-range times stay finite and clamped, never NaN.
assertFiniteFrame(playbackState(project, -5), ['onsetAge'], 't=-5');
assertFiniteFrame(playbackState(project, 1e6), ['onsetAge'], 't=1e6');

console.log('Playback state OK: field contract, sqrt compression, variable tempo, determinism.');
