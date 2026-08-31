/**
 * Visual profile tests (plan section 41, Commit D): the motion-tier budget
 * moved out of renderer.js must produce identical values from the shared
 * runtime track.
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { createTrack } from '../beatscope/runtime/runtime.js';
import {
  createMotionDirector,
  createVisualProfile,
  envelopeMath,
} from '../beatscope/runtime/visual-profile.js';
import { assertBounded, assertFiniteFrame, deepFreeze } from './helpers/visual-frame.js';

const project = JSON.parse(
  await readFile(new URL('./fixtures/runtime/characterization-project.json', import.meta.url), 'utf-8'),
);

const track = createTrack(project);
const profile = createVisualProfile(track);

// Tiers on the fixture: p78=0.846, p92=0.922, p98=0.943 -> exactly one hero
// (strength 0.95 at t=2.5), no bursts, one turbulence-tier event (0.9 at 0).
{
  const hit = profile.at(2.5);
  assert.equal(hit.hero, 0.95);
  assert.equal(hit.pulse, 0.95);
  assert.ok(Math.abs(hit.turbulence - 2 / 11) < 1e-12); // density (5-3)/11 at age 0
  assert.equal(hit.burst, 0);
  assert.equal(hit.impactAge, 0);

  // Formula-driven decay at +0.25 s (only events within the 1.15 s window).
  const decayed = profile.at(2.75);
  assert.ok(Math.abs(decayed.hero - 0.95 * Math.exp(-0.25 * 4.5)) < 1e-12);
  assert.ok(Math.abs(decayed.pulse - 0.95 * Math.exp(-0.25 * 12)) < 1e-12);
  assert.ok(Math.abs(decayed.turbulence - (2 / 11) * Math.exp(-0.25 * 1.9)) < 1e-12);
  assert.equal(decayed.burst, 0);
  assert.ok(Math.abs(decayed.impactAge - 0.25) < 1e-12);

  // Turbulence-tier events blend strength with density (event 0 at age 0).
  const start = profile.at(0);
  assert.ok(Math.abs(start.pulse - 0.9) < 1e-12);
  assert.ok(Math.abs(start.turbulence - 0.9 * 0.35) < 1e-12);
  assert.equal(start.hero, 0);
  assert.equal(start.burst, 0);
  assert.equal(start.impactAge, Infinity);

  // Before the first event everything is zero.
  assert.deepEqual(profile.at(-5), { pulse: 0, turbulence: 0, burst: 0, hero: 0, impactAge: Infinity });
}

// Cooldown options: hero needs 8 bars between events, bursts 2 beats. At
// 60 BPM (beatLength 1 s) the strong onset at t=2 lands inside the hero
// cooldown but clears the 2-beat burst cooldown -> burst; the one at t=10
// clears the 8 s hero cooldown -> hero again.
{
  const cooldownTrack = createTrack({
    tempo: { global_bpm: 60 },
    grid: { origin: 0 },
    beats: [],
    onsets: [
      { id: 1, time: 0.0, strength: 1.0 },
      { id: 2, time: 2.0, strength: 1.0 },
      { id: 3, time: 10.0, strength: 1.0 },
    ],
    energy: {},
  });
  const cooldownProfile = createVisualProfile(cooldownTrack);

  const first = cooldownProfile.at(0);
  assert.equal(first.hero, 1);
  assert.equal(first.impactAge, 0);

  const second = cooldownProfile.at(2);
  assert.equal(second.burst, 1); // demoted: inside the 8-bar hero cooldown
  assert.equal(second.hero, 0); // the t=0 hero is beyond the 1.15 s window
  assert.equal(second.impactAge, 0);

  const third = cooldownProfile.at(10);
  assert.equal(third.hero, 1); // 10 s later clears the 8 s cooldown
  assert.equal(third.impactAge, 0);
}

// Purity: frozen profile, frozen input, deterministic output.
{
  assert.ok(Object.isFrozen(profile));
  const frozen = JSON.parse(JSON.stringify(project));
  (function deepFreeze(value) {
    Object.freeze(value);
    for (const item of Object.values(value)) {
      if (item && typeof item === 'object') deepFreeze(item);
    }
  })(frozen);
  const frozenProfile = createVisualProfile(createTrack(frozen));
  assert.doesNotThrow(() => {
    frozenProfile.at(2.5);
    frozenProfile.at(-1);
  });
  assert.deepEqual(profile.at(2.5), profile.at(2.5));
}

// Empty onsets: stable zero budget.
{
  const empty = createVisualProfile(createTrack({ tempo: {}, grid: {}, beats: [], onsets: [], energy: {} }));
  assert.deepEqual(empty.at(1.0), { pulse: 0, turbulence: 0, burst: 0, hero: 0, impactAge: Infinity });
}

console.log('Visual profile OK: tiers, decay formulas, cooldowns, purity.');

// ===========================================================================
// v0.6.1 motion director (plan section 13.2): deterministic tension and
// recovery envelopes. `at(time)` must stay a pure function of audio time.
// ===========================================================================

// Deterministic energy frames so band normalization has something to chew on.
function makeEnergy(seconds = 26, fps = 20) {
  const count = Math.round(seconds * fps) + 1;
  const wave = (i, base, amp) => base + amp * Math.sin(i / 9) + amp * 0.5 * Math.sin(i / 3.1);
  return {
    start: 0,
    fps,
    bands: {
      low: Array.from({ length: count }, (_, i) => wave(i, 0.42, 0.08)),
      mid: Array.from({ length: count }, (_, i) => wave(i, 0.36, 0.07)),
      high: Array.from({ length: count }, (_, i) => wave(i, 0.3, 0.09)),
      all: Array.from({ length: count }, (_, i) => wave(i, 0.38, 0.06)),
    },
  };
}

// A real beat grid from consecutive beat spans (variable tempo allowed).
function beatsFromSpans(spans) {
  const beats = [];
  let time = 0;
  let bar = 1;
  let beatInBar = 1;
  for (const span of spans) {
    beats.push({ time: Number(time.toFixed(6)), bar, beat_in_bar: beatInBar });
    beatInBar += 1;
    if (beatInBar > 4) {
      beatInBar = 1;
      bar += 1;
    }
    time += span;
  }
  return beats;
}

const MOTION_CHANNELS = [
  'ambient', 'anticipation', 'hold', 'impact', 'recoil', 'aftershock',
  'lobeSplit', 'tension', 'memory',
];

// Envelope curve helpers: exact endpoints and clamps (plan section 6.4).
{
  assert.equal(envelopeMath.easeOutExpo(0), 0);
  assert.equal(envelopeMath.easeOutExpo(1), 1); // no 2^-10 residue at the seam
  assert.ok(Math.abs(envelopeMath.easeOutExpo(0.5) - (1 - Math.pow(2, -5))) < 1e-12);
  assert.equal(envelopeMath.easeInCubic(0), 0);
  assert.equal(envelopeMath.easeInCubic(1), 1);
  assert.equal(envelopeMath.smoothstep(-1), 0);
  assert.equal(envelopeMath.smoothstep(2), 1);
  assert.ok(Math.abs(envelopeMath.smoothstep(0.5) - 0.5) < 1e-12);
  assert.equal(envelopeMath.progress(1, 2, 0), 0);
  assert.equal(envelopeMath.progress(1, 2, 3), 1);
  assert.equal(envelopeMath.progress(1, 2, 1.5), 0.5);

  // Phase lengths clamp to human ranges and stretch with the beat span.
  assert.deepEqual(envelopeMath.phaseDurations(0.5, 0), {
    anticipation: 0.14, hold: 0.03, impact: 0.06, recoil: 0.21, aftershock: 0.575,
  });
  assert.deepEqual(envelopeMath.phaseDurations(0.05, 0), {
    anticipation: 0.10, hold: 0.025, impact: 0.045, recoil: 0.16, aftershock: 0.38,
  });
  assert.deepEqual(envelopeMath.phaseDurations(3, 0), {
    anticipation: 0.22, hold: 0.045, impact: 0.085, recoil: 0.30, aftershock: 0.82,
  });
  // Dense passages stretch only the aftershock (plan section 6.6).
  assert.ok(Math.abs(envelopeMath.phaseDurations(3, 1).aftershock - 0.82 * 1.15) < 1e-12);

  // Per-beat expand-contract breath: exact zero at the beat and before the
  // next one, a full plateau across the first half, fast attack.
  assert.equal(envelopeMath.beatPulseEnvelope(0), 0);
  assert.equal(envelopeMath.beatPulseEnvelope(0.3), 1);
  assert.equal(envelopeMath.beatPulseEnvelope(0.88), 0);
  assert.equal(envelopeMath.beatPulseEnvelope(1), 0);
  assert.ok(envelopeMath.beatPulseEnvelope(0.05) > 0.5);
  assert.ok(envelopeMath.beatPulseEnvelope(0.6) > 0);
  assert.ok(envelopeMath.beatPulseEnvelope(0.6) < 1);

  const splitEvent = {
    phrased: true, time: 2, amplitude: 1,
    impactDuration: 0.06, recoilDuration: 0.21,
  };
  assert.equal(envelopeMath.lobeSplitEnvelope(splitEvent, 2 - 1e-8), 0);
  assert.equal(envelopeMath.lobeSplitEnvelope(splitEvent, 2), 1);
  assert.equal(envelopeMath.lobeSplitEnvelope(splitEvent, 2.115), 1);
  assert.ok(envelopeMath.lobeSplitEnvelope(splitEvent, 2.25) < 1);
  assert.ok(envelopeMath.lobeSplitEnvelope(splitEvent, 2.25) > 0);
  assert.equal(envelopeMath.lobeSplitEnvelope(splitEvent, 2.405), 0);
}

// One silent hero at t=20 on a 120 BPM fallback grid: beatSpan 0.5 s gives
// preRoll .14 / hold .03 / impact .06 / recoil .21 / aftershock .575.
function boundaryProject() {
  return {
    tempo: { global_bpm: 120 },
    grid: { origin: 0 },
    beats: [],
    onsets: [
      { id: 20, time: 20, strength: 1 },
      { id: 21, time: 30, strength: 0.5 },
      { id: 22, time: 31.5, strength: 0.5 },
      { id: 23, time: 33, strength: 0.5 },
      ...[5, 6.5, 8, 9.5, 11, 12.5, 14, 15.5].map((time, i) => ({ id: 30 + i, time, strength: 0.05 })),
    ],
    energy: makeEnergy(),
  };
}

const boundaryDirector = createMotionDirector(createTrack(boundaryProject()));

// 1. Exact phase boundaries at anticipation, hold, impact, recoil, aftershock.
{
  const EPS = 1e-8;
  const d = boundaryDirector;
  assert.equal(d.at(19.86 - EPS).anticipation, 0);
  assert.ok(d.at(19.86 + EPS).anticipation > 0);
  assert.equal(d.at(19.97).anticipation, 1); // plateau reached exactly
  assert.equal(d.at(19.97).hold, 0);
  assert.ok(d.at(19.97 + EPS).hold > 0);

  const strike = d.at(20);
  assert.equal(strike.anticipation, 1);
  assert.equal(strike.hold, 1);
  assert.equal(strike.impact, 1); // amplitude 1 x hero x gate(0)
  assert.equal(strike.recoil, 0);
  assert.equal(strike.aftershock, 0);
  assert.equal(strike.lobeSplit, 1);
  assert.equal(strike.hero, 1);
  assert.equal(strike.tier, 'hero');

  const negative = d.at(20.08);

  const handover = d.at(20.06); // impact window end
  assert.equal(handover.impact, 0);
  assert.equal(handover.hold, 0);
  assert.equal(handover.recoil, 0);
  assert.ok(d.at(20.06 + EPS).recoil > 0);
  assert.equal(d.at(20.10).lobeSplit, 1);
  assert.ok(d.at(20.25).lobeSplit > 0);
  assert.equal(d.at(20.405).lobeSplit, 0);

  assert.equal(d.at(20.27).recoil, 0); // recoil window end
  assert.equal(d.at(20.27).aftershock, 0);
  assert.ok(d.at(20.27 + EPS).aftershock > 0);

  assert.equal(d.at(20.845).aftershock, 0); // aftershock window end
  assert.equal(d.at(20.9).aftershock, 0);
}

// 2. Continuity immediately before/after every boundary (epsilon 1e-6). The
// single intended exception is the strike itself: impact fires 0 -> 1 at t0.
{
  const EPS = 1e-8;
  for (const boundary of [19.86, 19.97, 20, 20.06, 20.27, 20.845]) {
    const before = boundaryDirector.at(boundary - EPS);
    const after = boundaryDirector.at(boundary + EPS);
    for (const channel of MOTION_CHANNELS) {
      if (boundary === 20 && (channel === 'impact' || channel === 'lobeSplit')) continue;
      assert.ok(
        Math.abs(before[channel] - after[channel]) <= 1e-6,
        `boundary ${boundary}: ${channel} jumped ${before[channel]} -> ${after[channel]}`,
      );
    }
  }
  assert.equal(boundaryDirector.at(20 - EPS).impact, 0);
  assert.ok(boundaryDirector.at(20 + EPS).impact > 0.999);
}

// 3. Finite bounded frames before zero and after the duration.
{
  for (const time of [-5, 200]) {
    const frame = boundaryDirector.at(time);
    assertFiniteFrame(frame, [], `director.at(${time})`);
    assertBounded(frame, {
      low: [0, 1], mid: [0, 1], high: [0, 1], all: [0, 1], ambient: [0, 1],
      anticipation: [0, 1], hold: [0, 1], impact: [0, 1], recoil: [0, 1],
      aftershock: [-1, 1], tension: [0, 1], memory: [0, 1], hero: [0, 1],
      shockProgress: [0, 1], beatWave: [0, 1], waveProgress: [0, 1],
      coreAperture: [0, 1], diffusion: [0, 1], beatExpand: [0, 1], lobeSplit: [0, 1],
      beatPhase: [0, 1], barPhase: [0, 1],
    }, `director.at(${time})`);
    assert.equal(frame.tier, 'ambient');
  }
}

// 4. Random-order queries equal sequential queries (no hidden state).
{
  const order = [20.9, -2, 20.03, 40, 20, 0.5, 20.5, 19.9];
  const recorded = order.map((time) => boundaryDirector.at(time));
  order.forEach((time, i) => assert.deepEqual(boundaryDirector.at(time), recorded[i]));
}

// 5. Seek 1s -> 40s -> 3s lands on the same frame as a direct 3s query; a
// freshly created director agrees sample-for-sample.
{
  boundaryDirector.at(1);
  boundaryDirector.at(40);
  const seekFrame = boundaryDirector.at(3);
  assert.deepEqual(seekFrame, createMotionDirector(createTrack(boundaryProject())).at(3));
}

// 6. Dense streams reduce impact amplitude through the density gate but
// retain surface memory.
{
  function gateFixture(spacing) {
    return createTrack({
      tempo: { global_bpm: 120 },
      grid: { origin: 0 },
      beats: [],
      onsets: [
        { id: 50, time: 10, strength: 1 },
        ...[-0.9, -0.7, -0.5, -0.3, -0.1, 0.1, 0.3, 0.5, 0.7]
          .map((offset) => ({ id: 60 + (offset * 100), time: 10 + offset * spacing, strength: 0.5 })),
        ...[30, 32, 34].map((time, i) => ({ id: 70 + i, time, strength: 0.5 })),
      ],
      energy: makeEnergy(),
    });
  }
  const sparse = createMotionDirector(gateFixture(3)).at(10);
  const dense = createMotionDirector(gateFixture(1)).at(10);
  // 10 onsets share the dense +/-1s window: density (10-3)/11.
  const expectedGate = 1 - 0.58 * envelopeMath.smoothstepBetween(0.55, 0.90, 7 / 11);
  assert.ok(dense.impact < sparse.impact);
  assert.ok(Math.abs(dense.impact - sparse.impact * expectedGate) < 1e-12);
  const sparseMemory = createMotionDirector(gateFixture(3)).at(10.1).memory;
  const denseMemory = createMotionDirector(gateFixture(0.25)).at(10.1).memory;
  assert.ok(denseMemory > 0.5);
  assert.ok(denseMemory > sparseMemory + 0.1);
}

// 7. Ordinary pulses rotate deterministic lobe assignment from the beat grid.
{
  const pulseDirector = createMotionDirector(createTrack({
    tempo: { global_bpm: 120 },
    grid: { origin: 0 },
    beats: [],
    onsets: [
      ...[0, 2, 4].map((time, i) => ({ id: 11 + i, time, strength: 0.05 })),
      ...[6, 8, 10, 12, 14].map((time, i) => ({ id: 14 + i, time, strength: 0.05 })),
      ...[30, 32, 34].map((time, i) => ({ id: 40 + i, time, strength: 0.5 })),
    ],
    energy: makeEnergy(),
  }));
  const rotations = [
    { id: 11, time: 0, weights: [1, 0, 0] },
    { id: 12, time: 2, weights: [0, 0, 1] },
    { id: 13, time: 4, weights: [0, 1, 0] },
  ];
  for (const { id, time, weights } of rotations) {
    const frame = pulseDirector.at(time + 0.01);
    assert.equal(frame.tier, 'pulse');
    assert.equal(frame.eventId, id);
    assert.deepEqual(frame.lobeWeights, weights);
    const [x, y, z] = frame.direction;
    assert.ok(Math.abs(Math.sqrt(x * x + y * y + z * z) - 1) < 1e-9);
  }
}

// 8. Hero cooldown spans 32 REAL beat indices. With 0.6 s beats the 31-beat
// gap is 18.6 s -- past any seconds-based 8-bar window at 120 BPM (16 s) --
// and must still be demoted; 32 beats passes.
{
  function heroFixture(secondStrongTime) {
    return createTrack({
      tempo: { global_bpm: 120 },
      grid: { origin: 0 },
      beats: beatsFromSpans(Array.from({ length: 40 }, () => 0.6)),
      onsets: [
        { id: 1, time: 0, strength: 1 },
        { id: 2, time: secondStrongTime, strength: 1 },
        ...Array.from({ length: 10 }, (_, i) => ({ id: 10 + i, time: 40 + i * 2, strength: 0.05 })),
      ],
      energy: makeEnergy(30),
    });
  }
  const demoted = createMotionDirector(heroFixture(18.6));
  assert.equal(demoted.events[1].tier, 'burst');
  assert.equal(demoted.at(18.6).tier, 'burst');
  const accepted = createMotionDirector(heroFixture(19.2));
  assert.equal(accepted.events[1].tier, 'hero');
  assert.equal(accepted.at(19.2).tier, 'hero');
}

// 9. Burst cooldown spans exactly two real beat indices.
{
  function burstFixture(secondStrongTime) {
    return createTrack({
      tempo: { global_bpm: 120 },
      grid: { origin: 0 },
      beats: beatsFromSpans(Array.from({ length: 24 }, () => 0.5)),
      onsets: [
        { id: 1, time: 0, strength: 1 },
        { id: 2, time: secondStrongTime, strength: 1 },
        ...Array.from({ length: 10 }, (_, i) => ({ id: 10 + i, time: 30 + i * 2, strength: 0.05 })),
      ],
      energy: makeEnergy(30),
    });
  }
  const allowed = createMotionDirector(burstFixture(1.0)); // two beats later
  assert.equal(allowed.events[1].tier, 'burst');
  assert.equal(allowed.at(1.0).impact, 1); // burst scale x gate(0)
  const demoted = createMotionDirector(burstFixture(0.5)); // one beat later
  assert.equal(demoted.events[1].tier, 'turbulence');
  assert.equal(demoted.at(0.5).impact, 0.5); // turbulence amplitude, no phrase
}

// 10. Variable-tempo grids derive phase lengths from the LOCAL beat span,
// not from the (deliberately wrong) global BPM.
{
  const spans = [0.4, 0.4, 0.8, ...Array.from({ length: 37 }, () => 0.4)];
  const variableTempo = createMotionDirector(createTrack({
    tempo: { global_bpm: 150 }, // wrong on purpose: beats must win
    grid: { origin: 0 },
    beats: beatsFromSpans(spans),
    onsets: [
      { id: 1, time: 0, strength: 1 },   // hero: local span 0.4 -> preRoll 0.112
      { id: 2, time: 0.8, strength: 1 }, // burst: local span 0.8 -> preRoll 0.22
      ...Array.from({ length: 10 }, (_, i) => ({ id: 10 + i, time: 6 + i * 2, strength: 0.05 })),
    ],
    energy: makeEnergy(24),
  }));
  const EPS = 1e-8;
  assert.equal(variableTempo.at(-0.112 - EPS).anticipation, 0);
  assert.ok(variableTempo.at(-0.112 + EPS).anticipation > 0);
  assert.equal(variableTempo.at(0.8 - 0.22 - EPS).anticipation, 0);
  assert.ok(variableTempo.at(0.8 - 0.22 + EPS).anticipation > 0);
}

// 11. Empty onsets and silence produce a calm finite state.
{
  const silent = createMotionDirector(createTrack({ tempo: {}, grid: {}, beats: [], onsets: [], energy: {} }));
  const calm = silent.at(1.0);
  assertFiniteFrame(calm, [], 'calm frame');
  assert.equal(calm.tier, 'ambient');
  assert.equal(calm.eventId, -1);
  for (const channel of MOTION_CHANNELS) assert.equal(calm[channel], 0);
  assert.equal(calm.hero, 0);
  assert.equal(calm.beatWave, 0);
  assert.equal(calm.waveProgress, 0);
  assert.equal(calm.coreAperture, 0);
  assert.equal(calm.diffusion, 0);
  assert.equal(calm.beatExpand, 0);
  assert.deepEqual(calm.lobeWeights, [0.34, 0.33, 0.33]);

  // With energy but no nearby events the director stays ambient and reports
  // the normalized bands.
  const quiet = boundaryDirector.at(0.5);
  assert.equal(quiet.tier, 'ambient');
  assert.ok(quiet.low > 0 && quiet.low <= 1);
  assert.equal(quiet.impact, 0);
}

// 12. Reduced motion scales the motion channels; beat/phase facts unchanged.
{
  const time = 20.02;
  const frame = boundaryDirector.at(time);
  const calm = boundaryDirector.at(time, { reducedMotion: true });
  assert.equal(calm.hold, 0);
  assert.ok(Math.abs(calm.anticipation - frame.anticipation * 0.25) < 1e-12);
  assert.ok(Math.abs(calm.impact - frame.impact * 0.25) < 1e-12);
  assert.ok(Math.abs(calm.lobeSplit - frame.lobeSplit * 0.20) < 1e-12);
  assert.ok(frame.ambient > 0);
  assert.ok(Math.abs(calm.ambient - frame.ambient * 0.15) < 1e-12);
  assert.ok(Math.abs(calm.tension - Math.min(1, calm.anticipation + 0.35 * calm.memory)) < 1e-12);
  for (const fact of ['time', 'tier', 'eventId', 'hero', 'low', 'mid', 'high', 'all',
    'memory', 'shockProgress', 'beatPhase', 'barPhase']) {
    assert.deepEqual(calm[fact], frame[fact], `reduced motion changed ${fact}`);
  }
  assert.deepEqual(calm.lobeWeights, frame.lobeWeights);
  assert.deepEqual(calm.direction, frame.direction);
  assert.ok(Math.abs(calm.beatWave - frame.beatWave * 0.25) < 1e-12);
  assert.ok(Math.abs(calm.coreAperture - frame.coreAperture * 0.25) < 1e-12);
  assert.ok(Math.abs(calm.beatExpand - frame.beatExpand * 0.25) < 1e-12);
  assert.ok(calm.diffusion <= frame.diffusion * 0.21 + 1e-12);
  assert.equal(calm.waveProgress, frame.waveProgress);

  // Recoil and aftershock scale on their own windows.
  const recoilFrame = boundaryDirector.at(20.15);
  const recoilCalm = boundaryDirector.at(20.15, { reducedMotion: true });
  assert.ok(recoilFrame.recoil > 0);
  assert.ok(Math.abs(recoilCalm.recoil - recoilFrame.recoil * 0.25) < 1e-12);
  const afterFrame = boundaryDirector.at(20.35);
  const afterCalm = boundaryDirector.at(20.35, { reducedMotion: true });
  assert.ok(afterFrame.aftershock > 0);
  assert.ok(Math.abs(afterCalm.aftershock - afterFrame.aftershock * 0.25) < 1e-12);

  // The creation option applies the same scaling by default.
  assert.deepEqual(createMotionDirector(createTrack(boundaryProject()), { reducedMotion: true }).at(time), calm);
}

// 13. Per-beat expand-contract: every beat diffuses outward and recovers
// before the next one; the onsets landing on a beat set its amplitude and
// the current energy gates the floor. Flat energy isolates the strength
// ladder from band movement (bands normalize to 0 on constant energy).
{
  const flatEnergy = (seconds = 26, value = 0.5) => ({
    start: 0,
    fps: 20,
    bands: {
      low: Array.from({ length: seconds * 20 + 1 }, () => value),
      mid: Array.from({ length: seconds * 20 + 1 }, () => value),
      high: Array.from({ length: seconds * 20 + 1 }, () => value),
      all: Array.from({ length: seconds * 20 + 1 }, () => value),
    },
  });
  const pulseDirector = createMotionDirector(createTrack({
    tempo: { global_bpm: 120 },
    grid: { origin: 0 },
    beats: [],
    onsets: [
      { id: 1, time: 10, strength: 1 },
      { id: 2, time: 12.5, strength: 0.3 },
      { id: 3, time: 15, strength: 0 },
    ],
    energy: flatEnergy(),
  }));

  // Same phase (0.2 into the beat), three different beat strengths.
  const strong = pulseDirector.at(10.1);
  const weak = pulseDirector.at(12.6);
  const quiet = pulseDirector.at(15.1);
  assert.ok(strong.beatExpand > 0.35);                 // full-beat diffusion
  assert.ok(weak.beatExpand < strong.beatExpand * 0.5);
  assert.ok(quiet.beatExpand < weak.beatExpand * 0.6); // breath floor remains
  assert.ok(quiet.beatExpand > 0.02);

  // The envelope contracts within the beat: late in the beat the form is
  // most of the way back to rest (band movement cannot hide the ratio).
  const hit = boundaryDirector.at(20.1);
  const late = boundaryDirector.at(20.425); // phase 0.85
  assert.ok(late.beatExpand < 0.08);
  assert.ok(late.beatExpand < hit.beatExpand * 0.3);

  // Silent on both sides of the beat boundary: the amplitude switch from
  // one beat's strength to the next happens while the envelope is zero.
  assert.equal(boundaryDirector.at(20 - 1e-8).beatExpand, 0);
  assert.ok(boundaryDirector.at(20 + 1e-8).beatExpand < 1e-4);

  // Deterministic and frozen like every other channel.
  assert.deepEqual(pulseDirector.at(10.1), strong);
}

// Purity: frozen director, frozen frame, frozen project.
{
  const frozen = deepFreeze(JSON.parse(JSON.stringify(boundaryProject())));
  const director = createMotionDirector(createTrack(frozen));
  assert.ok(Object.isFrozen(director));
  const frame = director.at(20);
  assert.ok(Object.isFrozen(frame));
  assert.ok(Object.isFrozen(frame.lobeWeights));
  assert.doesNotThrow(() => {
    director.at(19.9);
    director.at(-1);
    director.at(20, { reducedMotion: true });
  });
}

console.log('Motion director OK: phrase boundaries, continuity, beat-index cooldowns, reduced motion.');
