import assert from 'node:assert/strict';
import { metrics, gridPosition, formatTime, timeAtBar } from '../beatscope/web/grid.js';

console.log('Testing grid.js pure functions...');

// 1. metrics
const sampleProj = {
  tempo: { global_bpm: 120 },
  grid: { origin: 1.0, default_subdivision: 16, bars: 10 },
  beats: [
    { time: 1.0, beat: 1, bar: 1 },
    { time: 1.5, beat: 2, bar: 1 },
    { time: 2.0, beat: 3, bar: 1 },
    { time: 2.5, beat: 4, bar: 1 },
    { time: 3.0, beat: 1, bar: 2 },
  ],
};

const m = metrics(sampleProj, 16);
assert.equal(m.bpm, 120);
assert.equal(m.origin, 1.0);
assert.equal(m.step, 0.125);
assert.equal(m.bar, 2.0);

// 2. formatTime
assert.equal(formatTime(0), '00:00.000');
assert.equal(formatTime(65.432), '01:05.432');

// 3. gridPosition reversible across 1/16 and 1/32
const rawTime = 1.125;
const pos16 = gridPosition(rawTime, sampleProj, 16);
const pos32 = gridPosition(rawTime, sampleProj, 32);

assert.equal(pos16.bar, 1);
assert.equal(pos16.beat, 1);
assert.equal(pos16.stepInBar, 2);
assert.equal(pos16.quantizedTime, 1.125);
assert.equal(pos16.offsetMs, 0);

assert.equal(pos32.bar, 1);
assert.equal(pos32.beat, 1);
assert.equal(pos32.stepInBar, 3);
assert.equal(pos32.quantizedTime, 1.125);
assert.equal(pos32.offsetMs, 0);

// 4. timeAtBar
assert.equal(timeAtBar(1, sampleProj), 1.0);
assert.equal(timeAtBar(2, sampleProj), 3.0);

console.log('All JS grid tests passed successfully!');
