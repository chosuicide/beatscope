/**
 * Shared runtime tests (plan sections 32-35, Commit B).
 *
 * The runtime is pure: no DOM/audio/file access, no mutation of the input
 * map, deterministic outputs. Fixed-tempo grid facts are asserted against
 * the characterization fixture (120 BPM, origin 0, beats at 0..3.5 s).
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import {
  buildIndexes,
  createTrack,
  normalizeMap,
  previousIndex,
  trackForProject,
} from '../beatscope/runtime/runtime.js';

const project = JSON.parse(
  await readFile(new URL('./fixtures/runtime/characterization-project.json', import.meta.url), 'utf-8'),
);

const track = createTrack(project);

// --- normalizeMap understands both input shapes ---------------------------
{
  const map = normalizeMap(project);
  assert.equal(map.bpm, 120);
  assert.equal(map.origin, 0);
  assert.equal(map.defaultSubdivision, 16);
  assert.equal(map.sections.length, 2);
  assert.equal(map.beats.length, 8);
  assert.equal(map.onsets.length, 8);

  // Agent rhythm-map shape: top-level bpm/origin/subdivision/sections.
  const rhythmMap = normalizeMap({
    bpm: 96,
    origin: 0.25,
    subdivision: 8,
    sections: [{ bar: 1, label: 'A' }],
    beats: [],
    onsets: [],
    energy: {},
    cues: {},
  });
  assert.equal(rhythmMap.bpm, 96);
  assert.equal(rhythmMap.origin, 0.25);
  assert.equal(rhythmMap.defaultSubdivision, 8);
  assert.equal(rhythmMap.sections.length, 1);
}

// --- input is never mutated ------------------------------------------------
{
  const frozen = JSON.parse(JSON.stringify(project));
  (function deepFreeze(value) {
    Object.freeze(value);
    for (const item of Object.values(value)) {
      if (item && typeof item === 'object') deepFreeze(item);
    }
  })(frozen);
  const frozenTrack = createTrack(frozen);
  assert.doesNotThrow(() => {
    frozenTrack.at(1.0);
    frozenTrack.positionAt(1.0);
    frozenTrack.quantize(1.0, 16);
    frozenTrack.energyAt(0.01, 'low');
    frozenTrack.sectionAt(1.0);
    frozenTrack.between(0, 1);
    frozenTrack.nextCue(0);
    frozenTrack.previousOnset(1);
    frozenTrack.nearestOnset(1);
  });
  assert.deepEqual(JSON.parse(JSON.stringify(frozen)), project);
}

// --- positionAt: global-BPM grid with extrapolation (Commit-B semantics) ---
{
  const p0 = track.positionAt(0);
  assert.equal(p0.bar, 1);
  assert.equal(p0.beat, 1);
  assert.equal(p0.beatIndex, 0);
  assert.equal(p0.beatPhase, 0);
  assert.equal(p0.barPhase, 0);

  const p1 = track.positionAt(0.125);
  assert.equal(p1.bar, 1);
  assert.equal(p1.beat, 1);
  assert.ok(Math.abs(p1.beatPhase - 0.25) < 1e-12);
  assert.ok(Math.abs(p1.barPhase - 0.0625) < 1e-12);

  const p2 = track.positionAt(1.375);
  assert.equal(p2.bar, 1);
  assert.equal(p2.beat, 3);
  assert.ok(Math.abs(p2.beatPhase - 0.75) < 1e-12);

  // Beyond the stored beats the global BPM extrapolates (D6 parity).
  const p3 = track.positionAt(10);
  assert.equal(p3.bar, 6);
  assert.equal(p3.beat, 1);

  // Negative clocks clamp to t=0 (the export contract).
  const p4 = track.positionAt(-0.2);
  assert.equal(p4.time, 0);
  assert.equal(p4.bar, 1);
}

// --- at(): impulses, raw energy, sections ----------------------------------
{
  const s = track.at(0.6);
  assert.equal(s.bar, 1);
  assert.equal(s.beat, 2); // last stored beat <= 0.6 is beat 2 at t=0.5
  assert.ok(Math.abs(s.beatPhase - 0.2) < 1e-12);
  assert.equal(s.section?.label, 'A');

  // D2 carrier: decaying impulse over the previous onset.
  const expectedImpulse = 0.5 * Math.exp(-0.1 * 16);
  assert.ok(Math.abs(s.onset.value - expectedImpulse) < 1e-12);
  assert.equal(s.onset.item.id, 2);
  assert.ok(Math.abs(s.onset.age - 0.1) < 1e-12);

  // D3: the accent cue points at onset 2 -> accent shares the impulse.
  assert.equal(s.accent.item.id, 2);
  assert.equal(s.accent.value, s.onset.value);

  // D1 carrier: RAW band energy (callers apply sqrt).
  assert.equal(s.low, track.energyAt(0.6, 'low'));
  assert.equal(s.all, 0.3); // clamped to the last frame (fixture spans 0.08 s)
  assert.equal(s.low, 0.2);

  // Linear interpolation between frames at fps 100.
  assert.ok(Math.abs(track.energyAt(0.035, 'high') - 0.125) < 1e-12);

  // Past the impulse window the value decays to exactly 0.
  const late = track.at(0.75);
  assert.equal(late.onset.value, 0);
  assert.equal(late.onset.item.id, 2);
  assert.equal(late.accent, null);

  // D6 (Commit C): past the grid the web extrapolates exactly like the
  // export — bar/beat carry forward, sections beyond stored bars are null.
  const beyond = track.at(4.0);
  assert.equal(beyond.bar, 3);
  assert.equal(beyond.beat, 1);
  assert.equal(beyond.beatPhase, 0);
  assert.equal(beyond.section, null);
  assert.equal(beyond.onset.value, 0);

  // D4: negative time clamps phase but reports no onset.
  const negative = track.at(-0.2);
  assert.equal(negative.bar, 1);
  assert.equal(negative.beat, 1);
  assert.equal(negative.beatPhase, 0);
  assert.equal(negative.onset.item, null);
  assert.equal(negative.onset.value, 0);
  assert.equal(negative.accent, null);

  // v3-shaped onsets (raw_time, accent boolean, no cues) still work.
  const legacy = createTrack({
    tempo: { bpm: 120 },
    grid: { origin: 0 },
    beats: [{ time: 0, beat: 1, bar: 1 }],
    onsets: [{ id: 1, raw_time: 0.1, strength: 0.8, accent: true }],
    energy: {},
  });
  const legacyState = legacy.at(0.2);
  assert.ok(Math.abs(legacyState.onset.value - 0.8 * Math.exp(-0.1 * 16)) < 1e-12);
  assert.equal(legacyState.accent.item.id, 1);
}

// --- quantize: fixed-tempo parity with the previous grid.js outputs --------
{
  const onStep = track.quantize(0.125, 16);
  assert.deepEqual(onStep, {
    step: 1,
    bar: 1,
    beat: 1,
    stepInBar: 2,
    quantizedTime: 0.125,
    offsetMs: 0,
    preGrid: false,
  });

  const nearStep = track.quantize(0.06, 16);
  assert.equal(nearStep.step, 0);
  assert.equal(nearStep.bar, 1);
  assert.equal(nearStep.stepInBar, 1);
  assert.equal(nearStep.quantizedTime, 0);
  assert.equal(nearStep.offsetMs, 60);

  const betweenBeats = track.quantize(0.6, 16);
  assert.equal(betweenBeats.bar, 1);
  assert.equal(betweenBeats.beat, 2);
  assert.equal(betweenBeats.stepInBar, 6);
  assert.equal(betweenBeats.quantizedTime, 0.625);

  const before = track.quantize(-0.3, 16);
  assert.equal(before.preGrid, true);
  assert.equal(before.step, -2);
  assert.equal(before.quantizedTime, -0.25);
  assert.equal(before.offsetMs, -50);

  const after = track.quantize(3.75, 16);
  assert.deepEqual(after, {
    step: 30,
    bar: 2,
    beat: 4,
    stepInBar: 15,
    quantizedTime: 3.75,
    offsetMs: 0,
    preGrid: false,
  });

  // A bpm adjustment forces the synthetic grid (same rule as grid.js).
  const adjusted = track.quantize(0.125, 16, { bpm: 60 });
  assert.equal(adjusted.step, 1);
  assert.equal(adjusted.bar, 1);
  assert.equal(adjusted.beat, 1);
  assert.equal(adjusted.stepInBar, 2);
  assert.equal(adjusted.quantizedTime, 0.25);
  assert.equal(adjusted.offsetMs, -125);

  // Empty project: no beats -> synthetic grid at the 120 BPM default
  // (identical to the previous grid.js fallback).
  const empty = createTrack({ tempo: {}, grid: {}, beats: [], onsets: [], energy: {} });
  assert.deepEqual(empty.quantize(1.0, 16), {
    step: 8,
    bar: 1,
    beat: 3,
    stepInBar: 9,
    quantizedTime: 1,
    offsetMs: 0,
    preGrid: false,
  });
  assert.equal(empty.at(1.0).bar, 1);
  assert.equal(empty.at(1.0).beat, 3);
}

// --- windows and cues -------------------------------------------------------
{
  assert.deepEqual(
    track.between(0.4, 1.2).map((onset) => onset.id),
    [2, 3],
  );
  assert.deepEqual(track.between(10, 20), []);

  assert.deepEqual(track.nextCue(0), { time: 0.5, onset: 2 });
  assert.equal(track.nextCue(0.6), null);
  assert.equal(track.nextCue(0, 'impact'), null);

  const prev = track.previousOnset(0.7);
  assert.equal(prev.item.id, 2);
  assert.ok(Math.abs(prev.age - 0.2) < 1e-12);
  assert.equal(track.previousOnset(-1).item, null);

  const nearest = track.nearestOnset(0.45);
  assert.equal(nearest.item.id, 2);
  assert.ok(Math.abs(nearest.distance - 0.05) < 1e-12);
}

// --- variable tempo: adjacent-beat phase + downbeat spans (Commit C) -------
{
  const variable = createTrack({
    tempo: { global_bpm: 120 }, // deliberately misleading: real intervals differ
    grid: { origin: 0 },
    beats: [
      { time: 0.0, bar: 1, beat_in_bar: 1 },
      { time: 0.5, bar: 1, beat_in_bar: 2 },
      { time: 0.9, bar: 1, beat_in_bar: 3 },
      { time: 1.4, bar: 2, beat_in_bar: 1 },
    ],
    onsets: [],
    energy: {},
  });

  // Inside the grid the phase interpolates between the two real beats
  // (the old global-BPM phase would report 0.4 here).
  const mid = variable.at(0.7);
  assert.equal(mid.bar, 1);
  assert.equal(mid.beat, 2);
  assert.ok(Math.abs(mid.beatPhase - 0.5) < 1e-12); // (0.7 - 0.5) / (0.9 - 0.5)
  assert.ok(Math.abs(mid.barPhase - 0.5) < 1e-12); // bar 1 spans [0, 1.4]

  const near = variable.at(0.95);
  assert.equal(near.beat, 3);
  assert.ok(Math.abs(near.beatPhase - 0.1) < 1e-12); // (0.95 - 0.9) / 0.5

  // barPhase tracks the bar's own downbeat, not a synthetic 4-beat window.
  const bar2 = variable.at(1.5);
  assert.equal(bar2.bar, 2);
  assert.equal(bar2.beat, 1);
  assert.ok(Math.abs(bar2.beatPhase - 0.2) < 1e-12); // last interval: 0.5 s
  assert.ok(Math.abs(bar2.barPhase - 0.1 / 1.4) < 1e-9); // bar 2: [1.4, 2.8)

  // Past the grid the beat count carries forward from the last real beat.
  const past = variable.at(2.1);
  assert.equal(past.bar, 2);
  assert.equal(past.beat, 2); // next beat lands at 1.4 + 0.5 = 1.9
  assert.ok(Math.abs(past.beatPhase - 0.4) < 1e-12); // (2.1 - 1.9) / 0.5
  assert.ok(Math.abs(past.barPhase - 0.7 / 1.4) < 1e-9);
}

// --- sectionAt / previousIndex / track cache --------------------------------
{
  assert.equal(track.sectionAt(1.0)?.label, 'A');
  assert.equal(track.sectionAt(3.9)?.label, 'B');

  assert.equal(previousIndex([0, 1, 2], 1.5), 1);
  assert.equal(previousIndex([0, 1, 2], -1), -1);
  assert.equal(previousIndex([], 5), -1);
  assert.equal(previousIndex([0, 1, 2], 2), 2);

  assert.equal(trackForProject(project), trackForProject(project));
  assert.equal(trackForProject(project).map.bpm, 120);
}

// --- variable-tempo characterization fixture (plan section 18.2) -----------
{
  const variableProject = JSON.parse(
    await readFile(new URL('./fixtures/runtime/variable-tempo-project.json', import.meta.url), 'utf-8'),
  );
  const untouched = JSON.stringify(variableProject);
  const variableTrack = createTrack(variableProject);

  const segments = variableProject.tempo.segments;
  assert.equal(segments.length, 2);
  const boundary = segments[1].start; // 7.9935: the last beat of segment 1

  // Checkpoints: middle of segment 1, boundary +/- 1 ms, midpoint between two
  // non-uniform adjacent beats, and past the last real beat.
  const beats = variableProject.beats.map((beat) => beat.time);
  const lastBeat = beats[beats.length - 1];
  const prevBeat = beats[beats.length - 2];
  const checkpoints = [
    ['mid-segment-1', segments[0].start + (segments[0].end - segments[0].start) / 2],
    ['before-change', boundary - 0.001],
    ['at-change', boundary],
    ['after-change', boundary + 0.001],
    ['midpoint-unequal-beats', (lastBeat + prevBeat) / 2],
    ['past-last-beat', lastBeat + 0.5],
  ];

  let lastBar = 0;
  const positions = new Map();
  for (const [name, time] of checkpoints) {
    const state = variableTrack.at(time);
    const position = variableTrack.positionAt(time);
    positions.set(name, position);

    assert.ok(
      Number.isFinite(state.beatPhase) && state.beatPhase >= 0 && state.beatPhase < 1,
      `${name}: beatPhase ${state.beatPhase} must stay in [0, 1)`,
    );
    assert.ok(position.beatIndex >= 0, `${name}: beatIndex must stay valid`);
    assert.ok(position.bar >= lastBar, `${name}: bar must never go backwards`);
    lastBar = position.bar;

    // Seek safety: repeated queries return identical state.
    assert.deepEqual(variableTrack.at(time), state);
    assert.deepEqual(variableTrack.positionAt(time), position);
  }

  // The beat index runs on continuously through the segment boundary: the
  // boundary beat follows its predecessor and nothing resets to bar 1.
  const before = positions.get('before-change');
  const atChange = positions.get('at-change');
  const after = positions.get('after-change');
  assert.equal(atChange.beatIndex, before.beatIndex + 1);
  assert.equal(after.beatIndex, atChange.beatIndex);
  assert.ok(atChange.bar > 1);

  // Phase is continuous across the boundary (no snap at the tempo seam).
  assert.ok(Math.abs(after.beatPhase - atChange.beatPhase) < 0.01);

  // The runtime never mutates the input project.
  assert.equal(JSON.stringify(variableProject), untouched);
}

// --- determinism + purity ---------------------------------------------------
{
  assert.deepEqual(track.at(1.375), track.at(1.375));
  assert.deepEqual(track.quantize(1.3, 16), track.quantize(1.3, 16));

  const source = await readFile(new URL('../beatscope/runtime/runtime.js', import.meta.url), 'utf-8');
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
  assert.ok(
    !/document\.|window\.|navigator\.|requestAnimationFrame|AudioContext|localStorage|fetch\(/.test(code),
    'runtime must stay DOM/audio/network free',
  );
}

console.log('Runtime OK: createTrack contract, immutability, quantize parity, purity.');
