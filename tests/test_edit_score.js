import assert from 'node:assert/strict';
import {createEditScore, groupOnsets} from '../beatscope/runtime/edit-score.js';

const timing = {RHYTHM_MAP: {duration: 6,
  beats: [0, .5, 1.1, 1.8, 2.6, 3.5, 4.5, 5.5].map((time, index) => ({time, index})),
  onsets: [{id: 1, time: 1.21}, {id: 2, time: 1.32}, {id: 3, time: 1.48}, {id: 4, time: 3.3}]},
  getVisualState: time => ({time, low: .3, mid: .2, high: .4, all: .5})};
const score = {
  moments: {later: 4},
  stages: [
    {id: 'first', start: 0, end: 4, focus: 'body', change: 'detail becomes readable', entry: 'A'},
    {id: 'second', start: 4, end: 6, focus: 'detail', change: 'detail becomes new space', entry: 'B'},
  ],
  shots: [
    {id: 'A', relation: 'body of the same subject', clock: {mode: 'visible'},
      tracks: [{id: 'camera.z', keys: [{at: 0, value: 10}, {at: 6, value: 4}]}]},
    {id: 'B', relation: 'detail from that body', clock: {mode: 'restart'},
      values: {'camera.z': 2}, setup: {sourceId: 'same-source'}},
  ],
  groups: [{id: 'phrase', stage: 'first', anchors: [{onset: 1}, {onset: 2}, {onset: 3}],
    sequence: ['B', null, 'A']}],
  tracks: [{id: 'material.accent', keys: [{at: 0, value: 0, ease: 'hold'},
    {at: {onset: 2}, value: 1, ease: 'hold'}, {at: {moment: 'later'}, value: 2}]}],
};
const original = JSON.stringify(score);
const edit = createEditScore(score, timing);
assert.deepEqual(edit.cuts.map(c => [c.time, c.shot]), [[0, 'A'], [1.21, 'B'], [1.48, 'A'], [4, 'B']]);
assert.equal(edit.at(1.21).view.id, 'B');
assert.equal(edit.at(1.21 - 1e-8).view.id, 'A');
assert.equal(edit.at(1.32).view.id, 'B'); // one onset modifies material without cutting
assert.equal(edit.at(1.32).values['material.accent'], 1);
assert.equal(edit.at(1.48).view.visit, 1);
assert.ok(Math.abs(edit.at(1.48).view.localTime - 1.21) < 1e-12); // same picture continues, not reset
assert.ok(Math.abs(edit.at(1.98).values['camera.z'] - 8.29) < 1e-12);
assert.equal(edit.at(4).stage.id, 'second');
assert.equal(edit.at(4).view.localTime, 0); // deliberate restart
assert.equal(edit.at(4).values['material.accent'], 2);
assert.equal(edit.at(6).view.id, 'B');
const expected = new Map([0, 1.21, 1.32, 1.48, 4, 5, 6].map(t => [t, JSON.stringify(edit.at(t))]));
for (const t of [6, 0, 1.48, 4, 1.21, 5, 1.32, 0]) assert.equal(JSON.stringify(edit.at(t)), expected.get(t));
const mutated = edit.at(4); mutated.view.setup.sourceId = 'wrong';
assert.equal(edit.at(4).view.setup.sourceId, 'same-source');
assert.equal(JSON.stringify(score), original);

const alternate = mode => {
  const s = JSON.parse(original); s.shots[0].clock = {mode, offset: 1, rate: 2};
  return createEditScore(s, timing);
};
assert.ok(Math.abs(alternate('continuous').at(1.48).view.localTime - 3.96) < 1e-12);
assert.ok(Math.abs(alternate('visible').at(1.48).view.localTime - 3.42) < 1e-12);
assert.equal(alternate('restart').at(1.48).view.localTime, 1);

const repeat = JSON.parse(original);
repeat.groups[0].sequence = ['B', 'A']; repeat.groups[0].repeat = true;
assert.deepEqual(createEditScore(repeat, timing).cuts.slice(1, 4).map(c => c.shot), ['B', 'A', 'B']);
const tiny = JSON.parse(original); tiny.cuts = [{at: 2.001, shot: 'B'}, {at: 2.002, shot: 'A'}];
assert.equal(createEditScore(tiny, timing).frameWarnings(30).length, 1);
assert.equal(edit.frameWarnings(30).length, 0);
const reject = (change, pattern) => { const s = JSON.parse(original); change(s); assert.throws(() => createEditScore(s, timing), pattern); };
reject(s => s.cuts = [{at: 1.21, shot: 'A'}], /conflicting cuts/);
reject(s => s.groups[0].sequence = ['B'], /sequence length/);
reject(s => s.groups[0].sequence[0] = 'unknown', /unknown shot/);
reject(s => s.groups[0].anchors.reverse(), /must increase/);
reject(s => s.groups[0].stage = 'second', /crosses/);
reject(s => delete s.stages[1].entry, /entry cut or explicit carry/);
reject(s => s.tracks.push({id: 'camera.z', keys: [{at: 0, value: 1}]}), /writer overlap/);
reject(s => s.shots[0].tracks[0].keys[0].at = {beat: 0}, /local seconds/);
const carry = JSON.parse(original); delete carry.stages[1].entry; carry.stages[1].carry = true;
assert.equal(createEditScore(carry, timing).at(4).view.id, 'A');
const runs = groupOnsets(timing.RHYTHM_MAP, 0, 6, {maxGap: .17, minEvents: 3});
// Regression: an MV cannot claim alternation while executing slow scalar motion.
const mv = JSON.parse(original); mv.intent = 'music-video';
mv.stages[0].rhythm = [{start: 0, end: 4, mode: 'alternate',
  music: 'three closely spaced attacks', reason: 'body/detail/body', anchors: [{onset: 1}, {onset: 3}]}];
mv.stages[1].rhythm = [{start: 4, end: 6, mode: 'hold',
  music: 'resolved passage', reason: 'arrive inside the detail', anchors: [4],
  action: 'camera passes through the detail into the next space'}];
const mvEdit = createEditScore(mv, timing);
assert.equal(mvEdit.rhythm[0].switches, 2);
assert.equal(mvEdit.rhythm[1].longestVisit, 2);
assert.equal(mvEdit.at(4).rhythm.mode, 'hold');
assert.equal(mvEdit.at(6).rhythm.mode, 'hold');
assert.equal(mvEdit.at(1).rhythm.mode, 'alternate');
const ongoing = structuredClone(mv);
delete ongoing.shots[0].clock;
ongoing.tracks.push({id: 'world.travel', keys: [{at: 0, value: 0}],
  pace: {from: .5, to: 5.5, every: 1, step: 1, mode: 'travel'}});
const ongoingEdit = createEditScore(ongoing, timing);
assert.equal(ongoingEdit.at(1.48).view.clockMode, 'continuous');
assert.equal(ongoingEdit.at(1.48).view.localTime, 1.48);
assert.ok(ongoingEdit.at(1.48).values['world.travel'] > ongoingEdit.at(1.32).values['world.travel']);
assert.ok(ongoingEdit.at(4.9).values['world.travel'] > ongoingEdit.at(4.6).values['world.travel']);
assert.equal(ongoingEdit.at(6).values['world.travel'], ongoingEdit.at(5.5).values['world.travel']);
const journey = JSON.stringify(ongoingEdit.at(4.9)); ongoingEdit.at(.1);
assert.equal(JSON.stringify(ongoingEdit.at(4.9)), journey);
const paused = structuredClone(ongoing); paused.shots[0].clock = {mode: 'visible'};
assert.equal(createEditScore(paused, timing).at(1.48).view.localTime, 1.21);
const rejectMv = (change, pattern) => {
  const s = structuredClone(mv); change(s); assert.throws(() => createEditScore(s, timing), pattern);
};
rejectMv(s => delete s.stages[1].rhythm, /needs rhythm blocks/);
rejectMv(s => s.groups = [], /no matching shot changes/);
rejectMv(s => s.groups[0].sequence = ['A', 'A', 'A'], /no matching shot changes/);
rejectMv(s => s.stages[0].rhythm[0].mode = 'hold', /hold block contains/);
rejectMv(s => delete s.stages[1].rhythm[0].action, /hold needs/);
rejectMv(s => s.stages[0].rhythm[0].end = 3, /ends before stage/);
rejectMv(s => s.stages[0].rhythm[0].start = .1, /without gaps/);
rejectMv(s => s.stages[0].rhythm[0].anchors = [4], /inside the block/);
rejectMv(s => s.stages[0].rhythm[0].anchors.reverse(), /must increase/);
const switching = structuredClone(mv);
switching.groups[0].sequence = ['B', null, null];
switching.stages[0].rhythm[0].mode = 'switch';
assert.equal(createEditScore(switching, timing).rhythm[0].switches, 1);
assert.deepEqual(runs[0].events.map(e => e.id), [1, 2, 3]);
assert.equal(runs[0].start, 1.21); assert.equal(runs[0].end, 1.48);
assert.equal(groupOnsets(timing.RHYTHM_MAP, 0, 6, {maxGap: .1}).length, 0);
assert.throws(() => groupOnsets(timing.RHYTHM_MAP, 0, 6, {maxGap: 0}), /grouping options/);
console.log('Edit score: grouped cuts/holds, real onset timestamps, returning clocks, stage entry/carry, independent layer cues, frame visibility and seek order passed.');
