import assert from 'node:assert/strict';
import {createChoreography} from '../beatscope/runtime/choreography.js';

// Irregular grid deliberately rules out a global-BPM approximation.
const beats = [.2, .7, 1.4, 2.2, 3.2, 4.5, 5.5].map((time, index) => ({time, index}));
const timing = {RHYTHM_MAP: {duration: 6, beats, onsets: [{id: 917, time: 2.35}]},
  getVisualState: t => ({time: t, low: .3, mid: .2, high: .4, all: .5})};
const score = {
  moments: {arrival: {onset: 917}, preparation: {moment: 'arrival', offsetBeats: -1}},
  stages: [
    {id: 'approach', start: 0, end: {moment: 'arrival'}, focus: 'subject', change: 'approach reveals entrance'},
    {id: 'inside', start: {moment: 'arrival'}, end: 6, focus: 'interior', change: 'interior becomes environment'},
  ],
  tracks: [
    {id: 'camera.position', keys: [{at: 0, value: [0, 0, 10], ease: 'hold'},
      {at: {moment: 'preparation'}, value: [0, 0, 10], ease: 'in-cubic'},
      {at: {moment: 'arrival'}, value: [0, 0, 0], ease: 'hold'}]},
    {id: 'foreground.visible', keys: [{at: 0, value: true, ease: 'hold'},
      {at: {moment: 'arrival'}, value: false}]},
    {id: 'subject.scale', keys: [{at: 0, value: 1}, {at: {moment: 'arrival'}, value: 2}]},
    {id: 'advance', keys: [{at: 0, value: 0}], pace: {from: .2, to: 4.5, every: 1, step: 1}},
    {id: 'travel', keys: [{at: 0, value: [0, 0]}],
      pace: {from: .2, to: 4.5, every: 1, step: [0, 2], mode: 'travel'}},
    {id: 'crease', keys: [{at: 0, value: 1}], activity: {band: 'low', amount: 2}},
    {id: 'sourceTime', keys: [{at: 0, value: 0}, {at: 2.2, value: 2, ease: 'hold'},
      {at: {moment: 'arrival'}, value: 2}, {at: 4.5, value: 4}]},
  ],
};
const original = JSON.stringify(score);
const compiled = createChoreography(score, timing);
assert.equal(compiled.moments.arrival, 2.35); // measured event preserved
assert.ok(Math.abs(compiled.moments.preparation - 1.52) < 1e-12);
assert.equal(compiled.resolve({onset: 917, offsetBeats: 0}), 2.35);
assert.ok(Math.abs(compiled.resolve({onset: 917, offsetBeats: 1}) - 3.395) < 1e-12);
const destination = compiled.at(2.35);
assert.equal(destination.stage.id, 'inside');
assert.deepEqual(destination.values['camera.position'], [0, 0, 0]);
assert.equal(destination.values['foreground.visible'], false);
assert.equal(destination.values['subject.scale'], 2);
assert.equal(compiled.at(2.35 - 1e-7).stage.id, 'approach');
assert.equal(compiled.at(2.35 - 1e-7).values['foreground.visible'], true);
assert.ok(compiled.at(2.35 - .001).values['camera.position'][2] < .04);
assert.equal(compiled.at(2.3).values.sourceTime, 2); // freeze persists until release
assert.equal(compiled.at(3.2).values.advance, 4);
assert.equal(compiled.at(6).values.advance, 5); // result retained, no beat reset
assert.deepEqual(compiled.at(2.35).values.travel, [0, 6.3]);
assert.equal(destination.values.crease, 1.6);
const times = [0, 1.52, 2.2, 2.35, 3.2, 4.5, 6];
const baseline = new Map(times.map(t => [t, JSON.stringify(compiled.at(t))]));
for (const t of [6, 2.35, 0, 4.5, 1.52, 3.2, 2.2, 2.35]) {
  assert.equal(JSON.stringify(compiled.at(t)), baseline.get(t));
}
destination.values['camera.position'][0] = 999;
assert.deepEqual(compiled.at(2.35).values['camera.position'], [0, 0, 0]);
assert.equal(JSON.stringify(score), original);

const reject = (edit, pattern) => {
  const changed = JSON.parse(original); edit(changed);
  assert.throws(() => createChoreography(changed, timing), pattern);
};
reject(s => s.tracks.push(s.tracks[0]), /one track writer/);
reject(s => s.tracks.push({id:'camera.position.x',keys:[{at:0,value:0}]}), /overlapping property/);
reject(s => s.moments.arrival = {onset: 999}, /unknown onset/);
reject(s => s.moments.arrival = {moment: 'preparation'}, /cyclic moment/);
reject(s => s.moments.arrival = {beat: 99}, /unknown beat/);
reject(s => s.moments.arrival = {onset: 917, beat: 2}, /exactly one/);
reject(s => s.stages[1].start = 2.4, /gap\/overlap/);
reject(s => s.stages[1].end = 5.9, /whole song/);
reject(s => delete s.stages[0].change, /focus\/change/);
reject(s => s.tracks[1].keys[0].ease = 'linear', /require hold/);
assert.throws(() => compiled.at(NaN), /finite/);
const noGrid = {...timing, RHYTHM_MAP: {...timing.RHYTHM_MAP, beats: []}};
assert.throws(() => createChoreography(score, noGrid), /real beats/);
const nonMetric = JSON.parse(original);
nonMetric.moments.preparation = 1.5;
nonMetric.tracks = nonMetric.tracks.filter(t => !t.pace);
assert.equal(createChoreography(nonMetric, noGrid).at(2.35).values['subject.scale'], 2);
console.log('Choreography: measured anchors, variable-grid offsets, coordinated arrival, retained pacing, single writers and seek order passed.');
