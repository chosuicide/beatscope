/**
 * Motion engine stop-gate tests (v0.12 Round 3 Commit 2, plan §4.4-§4.8,
 * §10.2). Runs the compiled evaluator on sparse, dense, off-grid and
 * no-grid songs and pins the rules that make response chains seek-safe:
 *
 * - identical output for ascending, descending and shuffled query orders;
 * - exact event timestamps (no onset is ever moved onto a beat);
 * - dense material stays inside the authored budget instead of returning to
 *   "everything moves";
 * - no-grid projects disable metric drivers but keep onset/energy behavior;
 * - transitions stay stable at the boundary ±1 ms;
 * - combine rules and reduced-motion mapping are bounded and deterministic;
 * - the motion sources never touch wall-clock or Math.random.
 */
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';

import { compileDirectionContract } from './helpers/direction-contract.mjs';
compileDirectionContract();
const {
  compileDirection,
  getDirectionState,
  applyReducedMotion,
  registeredDriverKinds,
  registeredOperatorKinds,
  videoSourceTime,
} = await import('./.generated/motion/evaluate.js');

const BAR = 2.0; // 120 bpm, 4/4

/* ---------------- synthetic material ---------------- */

function layer(id, opacity = 1) {
  return {
    id,
    kind: 'editorial-typography',
    label: id,
    visible: true,
    locked: false,
    opacity,
    blend: 'normal',
    transform: { x: 0, y: 0, w: 1, h: 1, rotation: 0 },
    props: {},
  };
}

function chain(id, layerId, driver, motion) {
  return { id, target_layer_id: layerId, label: id, driver, motion };
}

function scene(id, start, end, layers, responses, transition = 'dissolve') {
  return {
    id,
    title: id,
    family: 'section',
    anchor: { kind: 'time', start_seconds: start, end_seconds: end },
    start_time: start,
    end_time: end,
    transition_out: transition,
    layers,
    responses,
  };
}

function documentOf(scenes) {
  return {
    schema: 'beatscope-direction-1',
    version: '0.12.0',
    project_id: 'c235e01f04b7',
    project_title: 'motion test',
    source_rhythm_sha256: 'c'.repeat(64),
    composition: { primary_ratio: '16:9', width: 1920, height: 1080, background: '#F5F1E8' },
    theme: {},
    assets: [],
    scenes,
    transitions: [],
    diagnostics: {},
  };
}

function rhythmOf({ duration, bpm = 120, onsets = [], beats = [], downbeats = [], energy = null, boundaries = [] }) {
  return {
    project_id: 'c235e01f04b7',
    duration,
    bpm,
    bar_seconds: bpm > 0 ? (60 / bpm) * 4 : 0,
    beats,
    onsets,
    downbeats,
    energy,
    boundaries,
    segments: [],
  };
}

function gridBeats(bars, barSeconds = BAR, perBar = 4) {
  const beats = [];
  for (let bar = 1; bar <= bars; bar++) {
    for (let beat = 1; beat <= perBar; beat++) {
      beats.push({ time: (bar - 1) * barSeconds + ((beat - 1) * barSeconds) / perBar, bar, beat });
    }
  }
  return beats;
}

function onset(id, time, band, strength) {
  return { id, time, band, strength };
}

const RANKED = (band, tier, maxPerBar, refractory = 0.25) => ({
  kind: 'ranked_onsets',
  band,
  tier,
  max_events_per_bar: maxPerBar,
  refractory_beats: refractory,
});

const SCALE = (amount = 0.05) => ({ kind: 'scale_pulse', amount, attack_seconds: 0.02, release_seconds: 0.2 });
const TRANSLATE = (amount = 0.05) => ({
  kind: 'translate_recoil',
  axis: [1, 0],
  amount,
  attack_seconds: 0.02,
  release_seconds: 0.2,
});

const round6 = (v) => Math.round(v * 1e6) / 1e6;

function serializeState(state) {
  const layers = {};
  for (const id of [...state.layers.keys()].sort()) {
    const out = state.layers.get(id);
    layers[id] = {
      scale: round6(out.scale),
      tx: round6(out.translate.x),
      ty: round6(out.translate.y),
      rotation: round6(out.rotation),
      opacity: round6(out.opacity),
      crop: round6(out.crop),
      strip: round6(out.strip),
      blur: round6(out.blur),
      invert: round6(out.invert),
    };
  }
  return JSON.stringify({
    scene: state.scene.id,
    transition: state.transition
      ? {
          kind: state.transition.kind,
          progress: round6(state.transition.progress),
          from: state.transition.fromSceneId,
          to: state.transition.toSceneId,
        }
      : null,
    layers,
  });
}

const isIdentity = (out) =>
  out.scale === 1 && out.translate.x === 0 && out.translate.y === 0 && out.opacity === 1 && out.rotation === 0;

/* ---------------- registry completeness ---------------- */

assert.deepEqual(registeredDriverKinds(), [
  'beat_phase',
  'downbeat_impulse',
  'energy_envelope',
  'ranked_onsets',
  'scene_phase',
  'structure_boundary',
  'transition_phase',
]);
assert.deepEqual(registeredOperatorKinds(), [
  'blur_focus',
  'crop_reveal',
  'invert_palette',
  'opacity_fade',
  'opacity_lift',
  'radial_expand',
  'rotate_recoil',
  'scale_pulse',
  'strip_offset',
  'translate_drift',
  'translate_recoil',
]);

/* ---------------- sparse song ---------------- */

{
  const onsets = [0.5, 6.5, 12.5, 18.5, 24.5].map((t, i) => onset(`s${i}`, t, 'low', 0.8));
  const rhythm = rhythmOf({ duration: 30, onsets, beats: gridBeats(15), downbeats: gridBeats(15).filter((b) => b.beat === 1).map((b) => b.time), boundaries: [15] });
  const doc = documentOf([
    scene('scene-01', 0, 30, [layer('lay-01')], [chain('r1', 'lay-01', RANKED('low', 'primary', 4), TRANSLATE(0.05))]),
  ]);
  const compiled = compileDirection(doc, rhythm);
  assert.equal(compiled.diagnostics.responses, 1);
  assert.equal(compiled.diagnostics.unavailable, 0);

  // exact measured timestamp: the envelope ramps from the onset at 0.5 s,
  // not from the beat grid (attack 20 ms -> peak at 0.52)
  const atOnset = getDirectionState(compiled, 0.5).layers.get('lay-01').translate.x;
  const atPeak = getDirectionState(compiled, 0.52).layers.get('lay-01').translate.x;
  const atBeat = getDirectionState(compiled, 0.0).layers.get('lay-01').translate.x;
  assert.equal(atOnset, 0, 'a positive attack starts from zero at the exact event');
  assert.ok(Math.abs(atPeak) > 1, 'the envelope peaks just after the measured onset');
  assert.equal(atBeat, 0, 'no response on an unrelated beat');
  // between events the layer is at rest
  assert.ok(isIdentity(getDirectionState(compiled, 3.0).layers.get('lay-01')));

  // sparse song: the layer moves only around its five events
  let active = 0;
  const samples = 600;
  for (let i = 0; i < samples; i++) {
    if (!isIdentity(getDirectionState(compiled, (i * 30) / samples).layers.get('lay-01'))) active += 1;
  }
  assert.ok(active / samples < 0.15, `sparse active fraction ${(active / samples).toFixed(3)}`);
}

/* ---------------- dense song must not move everything ---------------- */

{
  const onsets = [];
  let id = 0;
  for (let t = 0; t < 30; t += 0.02) {
    onsets.push(onset(`d${id++}`, t, id % 3 === 0 ? 'low' : id % 3 === 1 ? 'mid' : 'high', 0.3 + ((id * 37) % 100) / 150));
  }
  const beats = gridBeats(15);
  const rhythm = rhythmOf({
    duration: 30,
    onsets,
    beats,
    downbeats: beats.filter((b) => b.beat === 1).map((b) => b.time),
    boundaries: [10, 20],
  });
  const doc = documentOf([
    scene(
      'scene-01',
      0,
      30,
      [layer('lay-low'), layer('lay-mid'), layer('lay-high')],
      [
        chain('r-low', 'lay-low', RANKED('low', 'primary', 4), TRANSLATE(0.05)),
        chain('r-mid', 'lay-mid', RANKED('mid', 'secondary', 2), SCALE(0.04)),
        chain('r-high', 'lay-high', RANKED('high', 'primary', 6), TRANSLATE(0.03)),
      ],
    ),
  ]);
  const compiled = compileDirection(doc, rhythm);
  const diag = compiled.scenes[0].responses.map((r) => r.diagnostics);
  // budget: 15 bars of 2 s; per-bar caps are respected
  assert.ok(diag[0].selected <= 15 * 4, `low selected ${diag[0].selected}`);
  assert.ok(diag[1].selected <= 15 * 2, `mid selected ${diag[1].selected}`);
  assert.ok(diag[2].selected <= 15 * 6, `high selected ${diag[2].selected}`);
  assert.ok(diag.every((d) => d.suppressed > 0), 'dense material is suppressed, not amplified');

  // sample the whole song: never "everything moves" all the time
  let activeTotal = 0;
  let allThree = 0;
  let worst = 0;
  const samples = 900;
  const ids = ['lay-low', 'lay-mid', 'lay-high'];
  for (let i = 0; i < samples; i++) {
    const state = getDirectionState(compiled, (i * 30) / samples);
    const active = ids.filter((lid) => !isIdentity(state.layers.get(lid))).length;
    activeTotal += active;
    worst = Math.max(worst, active);
    if (active === 3) allThree += 1;
  }
  const meanActive = activeTotal / samples;
  assert.ok(meanActive < 2.0, `dense mean active layers ${meanActive.toFixed(3)}`);
  assert.ok(allThree / samples < 0.35, `all three layers moved in ${((allThree / samples) * 100).toFixed(1)}% of frames`);
  assert.ok(worst <= 3);

  // every output stays inside the documented bounds
  for (let i = 0; i < samples; i++) {
    const state = getDirectionState(compiled, (i * 30) / samples);
    for (const lid of ids) {
      const out = state.layers.get(lid);
      assert.ok(Math.abs(out.translate.x) <= 40 && Math.abs(out.translate.y) <= 40, 'translate bound');
      assert.ok(out.scale >= 0.25 && out.scale <= 4, 'scale bound');
      assert.ok(out.opacity >= 0 && out.opacity <= 1, 'opacity bound');
    }
  }
}

/* ---------------- query-order and seek determinism ---------------- */

{
  const onsets = Array.from({ length: 80 }, (_, i) => onset(`q${i}`, i * 0.5, 'low', 0.5 + ((i * 13) % 50) / 100));
  const beats = gridBeats(25);
  const rhythm = rhythmOf({ duration: 50, onsets, beats });
  const doc = documentOf([
    scene('scene-01', 0, 25, [layer('lay-01')], [chain('r1', 'lay-01', RANKED('low', 'primary', 3), TRANSLATE(0.04))]),
    scene('scene-02', 25, 50, [layer('lay-02')], [chain('r2', 'lay-02', RANKED('low', 'secondary', 3), SCALE(0.04))]),
  ]);
  const compiled = compileDirection(doc, rhythm);
  const times = Array.from({ length: 200 }, (_, i) => i * 0.25);
  const ascending = times.map((t) => serializeState(getDirectionState(compiled, t)));
  const descending = [...times].reverse().map((t) => serializeState(getDirectionState(compiled, t))).reverse();
  const shuffled = [...times].sort((a, b) => Math.sin(a * 12.9898) - Math.sin(b * 12.9898)).map((t) => serializeState(getDirectionState(compiled, t)));
  assert.deepEqual(descending, ascending, 'descending queries agree');
  assert.deepEqual([...shuffled].sort(), [...ascending].sort(), 'shuffled queries agree');
  // seek away and back reproduces the same frame
  const probe = 12.375;
  const before = serializeState(getDirectionState(compiled, probe));
  getDirectionState(compiled, 40.5);
  getDirectionState(compiled, 3.125);
  assert.equal(serializeState(getDirectionState(compiled, probe)), before, 'seek is stateless');
}

/* ---------------- off-grid: irregular measured bars ---------------- */

{
  // bar lengths 1.7 s, 2.3 s, 1.9 s, 2.1 s ... (no constant tempo)
  const barStarts = [0];
  const lengths = [1.7, 2.3, 1.9, 2.1, 1.6, 2.4];
  for (let i = 0; i < 8; i++) barStarts.push(barStarts[barStarts.length - 1] + lengths[i % lengths.length]);
  const beats = [];
  barStarts.forEach((start, index) => {
    const end = barStarts[index + 1] ?? start + 2;
    for (let k = 0; k < 4; k++) beats.push({ time: start + ((end - start) * k) / 4, bar: index + 1, beat: k + 1 });
  });
  const duration = barStarts[barStarts.length - 1];
  const onsets = [];
  for (let i = 0; i < 90; i++) onsets.push(onset(`o${i}`, (i * duration) / 90, 'mid', 0.5 + ((i * 7) % 40) / 100));
  const rhythm = rhythmOf({ duration, onsets, beats });
  const doc = documentOf([
    scene('scene-01', 0, duration, [layer('lay-01')], [chain('r1', 'lay-01', RANKED('mid', 'secondary', 2), SCALE(0.04))]),
  ]);
  const compiled = compileDirection(doc, rhythm);
  const diag = compiled.scenes[0].responses[0].diagnostics;
  assert.ok(diag.selected > 0, 'off-grid onsets still fire');
  assert.ok(diag.selected <= 8 * 2, `off-grid per-bar budget respected (${diag.selected})`);
  // beat phase still works from measured beats
  const beatDoc = documentOf([
    scene('scene-01', 0, duration, [layer('lay-01')], [
      chain('r1', 'lay-01', { kind: 'beat_phase', subdivision: 2 }, SCALE(0.03)),
    ]),
  ]);
  const beatCompiled = compileDirection(beatDoc, rhythm);
  assert.equal(beatCompiled.scenes[0].responses[0].unavailableReason, null);
  const beatState = getDirectionState(beatCompiled, beats[2].time + 0.02);
  assert.ok(beatState.layers.get('lay-01').scale > 1, 'beat phase fires on measured beats');
}

/* ---------------- no-grid: metric drivers unavailable ---------------- */

{
  const onsets = [0.4, 2.2, 4.6, 8.1].map((t, i) => onset(`n${i}`, t, 'high', 0.7));
  const energy = {
    fps: 4,
    start: 0,
    bands: { low: [0.2, 0.4, 0.6, 0.8, 0.5], mid: [0.1, 0.2, 0.3, 0.2, 0.1], high: [0.05, 0.1, 0.15, 0.1, 0.05] },
  };
  const rhythm = rhythmOf({ duration: 10, bpm: 0, onsets, beats: [], downbeats: [], boundaries: [], energy });
  const doc = documentOf([
    scene(
      'scene-01',
      0,
      10,
      [layer('lay-01'), layer('lay-02'), layer('lay-03')],
      [
        chain('r-onset', 'lay-01', RANKED('high', 'primary', 2), SCALE(0.05)),
        chain('r-beat', 'lay-02', { kind: 'beat_phase', subdivision: 2 }, SCALE(0.05)),
        chain('r-down', 'lay-02', { kind: 'downbeat_impulse' }, TRANSLATE(0.05)),
        chain('r-energy', 'lay-03', { kind: 'energy_envelope', band: 'low' }, { kind: 'opacity_fade', amount: 0.3, attack_seconds: 0.05, release_seconds: 0.4 }),
      ],
    ),
  ]);
  const compiled = compileDirection(doc, rhythm);
  const [rOnset, rBeat, rDown, rEnergy] = compiled.scenes[0].responses;
  assert.equal(rOnset.unavailableReason, null, 'onsets remain available');
  assert.match(rBeat.unavailableReason, /grid/, 'beat phase honestly unavailable');
  assert.match(rDown.unavailableReason, /grid/, 'downbeat honestly unavailable');
  assert.equal(rEnergy.unavailableReason, null, 'energy remains available');
  assert.equal(rEnergy.continuous, true);

  const state = getDirectionState(compiled, 0.42);
  assert.ok(state.layers.get('lay-01').scale > 1, 'onset driver works without a grid');
  assert.equal(state.layers.get('lay-02').scale, 1, 'unavailable chains do not fabricate motion');
  assert.ok(state.layers.get('lay-03').opacity < 1, 'energy envelope drives opacity');
  // energy is a slow occupancy signal: consecutive 60 Hz frames change little
  let maxDelta = 0;
  let previous = getDirectionState(compiled, 0).layers.get('lay-03').opacity;
  for (let i = 1; i <= 120; i++) {
    const value = getDirectionState(compiled, i / 60).layers.get('lay-03').opacity;
    maxDelta = Math.max(maxDelta, Math.abs(value - previous));
    previous = value;
  }
  assert.ok(maxDelta < 0.2, `energy steps stay smooth (${maxDelta.toFixed(4)})`);
}

/* no-grid caps use real one-second buckets, never a fabricated BPM bar */
{
  const onsets = [0.1, 0.2, 1.1, 1.2].map((t, i) => onset(`ng${i}`, t, 'high', 1 - i * 0.01));
  const rhythm = rhythmOf({ duration: 3, bpm: 0, onsets, beats: [], downbeats: [] });
  // Deliberately poison the fallback duration: a pseudo-bar implementation
  // would keep only one event across both seconds.
  rhythm.bar_seconds = 99;
  const doc = documentOf([
    scene('scene-01', 0, 3, [layer('lay-01')], [
      chain('r1', 'lay-01', RANKED('high', 'secondary', 1, 0), SCALE(0.05)),
    ]),
  ]);
  assert.deepEqual(
    compileDirection(doc, rhythm).scenes[0].responses[0].times,
    [0.1, 1.1],
    'one strongest onset survives in each real-second bucket',
  );
}

/* refractory suppression is shared across chains on one layer/operator */
{
  const rhythm = rhythmOf({
    duration: 4,
    onsets: [onset('high-rank', 0.1, 'low', 0.6), onset('low-rank', 0.15, 'low', 0.9)],
    beats: gridBeats(2),
  });
  const doc = documentOf([
    scene('scene-01', 0, 4, [layer('lay-01')], [
      chain('r1', 'lay-01', RANKED('low', 'secondary', 4, 0.5), SCALE(0.05)),
      chain('r2', 'lay-01', RANKED('low', 'secondary', 4, 0.5), SCALE(0.08)),
    ]),
  ]);
  const relevance = new Map([['high-rank', 0.95], ['low-rank', 0.1]]);
  const compiled = compileDirection(doc, rhythm, { relevance });
  const selected = compiled.scenes[0].responses.flatMap((response) => response.eventIds);
  assert.deepEqual(selected, ['high-rank'], 'the higher-ranked exact event wins across both chains');
  assert.equal(compiled.scenes[0].responses.reduce((n, r) => n + r.diagnostics.suppressed, 0), 3);
}

/* ---------------- transitions stable at boundary ±1 ms ---------------- */

{
  const rhythm = rhythmOf({ duration: 20, onsets: [], beats: gridBeats(10) });
  const doc = documentOf([
    scene('scene-01', 0, 10, [layer('lay-01')], [], 'dissolve'),
    scene('scene-02', 10, 20, [layer('lay-02')], [], 'hold-through'),
  ]);
  const compiled = compileDirection(doc, rhythm);
  const before = getDirectionState(compiled, 10 - 0.001);
  const after = getDirectionState(compiled, 10 + 0.001);
  assert.equal(before.scene.id, 'scene-01');
  assert.equal(after.scene.id, 'scene-02');
  assert.ok(before.transition, 'outgoing transition is visible before the boundary');
  assert.ok(before.transition.progress > 0.99 && before.transition.progress <= 1, 'progress approaches 1');
  assert.equal(after.transition, null, 'no stale transition after the boundary');
  assert.ok(Number.isFinite(before.transition.progress) && Number.isFinite(after.time));
  // progress is monotone across the transition window
  let previous = -1;
  for (let i = 0; i <= 24; i++) {
    const state = getDirectionState(compiled, 9.76 + i * 0.01);
    const progress = state.transition ? state.transition.progress : 1;
    assert.ok(progress >= previous - 1e-9, 'transition progress is monotone');
    previous = progress;
  }
  // custom transition duration from the document
  const withDuration = documentOf([
    scene('scene-01', 0, 10, [layer('lay-01')], [], 'dissolve'),
    scene('scene-02', 10, 20, [layer('lay-02')], [], 'hold-through'),
  ]);
  withDuration.transitions = [{ from_scene_id: 'scene-01', to_scene_id: 'scene-02', duration_seconds: 1.0 }];
  const custom = compileDirection(withDuration, rhythm);
  const customState = getDirectionState(custom, 9.5);
  assert.ok(customState.transition && Math.abs(customState.transition.progress - 0.5) < 1e-9, 'authored transition duration is used');
}

/* ---------------- combine rules (§4.8) ---------------- */

{
  const rhythm = rhythmOf({
    duration: 8,
    onsets: [onset('one', 0.0, 'low', 1)],
    beats: gridBeats(4),
  });
  const peak = (doc) => getDirectionState(compileDirection(doc, rhythm), 0.0);

  const additive = documentOf([
    scene('scene-01', 0, 8, [layer('lay-01')], [
      chain('a', 'lay-01', RANKED('low', 'primary', 4, 0), { kind: 'translate_recoil', axis: [1, 0], amount: 1.0, attack_seconds: 0, release_seconds: 0.5 }),
      chain('b', 'lay-01', RANKED('low', 'primary', 4, 0), { kind: 'translate_recoil', axis: [1, 0], amount: 1.0, attack_seconds: 0, release_seconds: 0.5 }),
    ]),
  ]);
  assert.equal(peak(additive).layers.get('lay-01').translate.x, 40, 'additive sums then clamps to the channel bound');

  const multiplicative = documentOf([
    scene('scene-01', 0, 8, [layer('lay-01')], [
      chain('a', 'lay-01', RANKED('low', 'primary', 4, 0), { kind: 'scale_pulse', amount: 1.0, attack_seconds: 0, release_seconds: 0.5 }),
      chain('b', 'lay-01', RANKED('low', 'primary', 4, 0), { kind: 'scale_pulse', amount: 1.0, attack_seconds: 0, release_seconds: 0.5 }),
    ]),
  ]);
  assert.equal(peak(multiplicative).layers.get('lay-01').scale, 4, 'multiplicative multiplies deltas around 1 and clamps');

  const maxRule = documentOf([
    scene('scene-01', 0, 8, [layer('lay-01')], [
      chain('a', 'lay-01', RANKED('low', 'primary', 4, 0), { kind: 'opacity_fade', amount: 1.0, attack_seconds: 0, release_seconds: 0.5 }),
      chain('b', 'lay-01', RANKED('low', 'primary', 4, 0), { kind: 'opacity_fade', amount: 0.5, attack_seconds: 0, release_seconds: 0.5 }),
    ]),
  ]);
  assert.equal(peak(maxRule).layers.get('lay-01').opacity, 0, 'max keeps the strongest influence');

  const booleanLow = documentOf([
    scene('scene-01', 0, 8, [layer('lay-01')], [
      chain('a', 'lay-01', RANKED('low', 'primary', 4), { kind: 'invert_palette', amount: 0.4, attack_seconds: 0, release_seconds: 0.5 }),
    ]),
  ]);
  assert.equal(peak(booleanLow).layers.get('lay-01').invert, 0.4, 'below the crossing stays an influence');
  const booleanHigh = documentOf([
    scene('scene-01', 0, 8, [layer('lay-01')], [
      chain('a', 'lay-01', RANKED('low', 'primary', 4), { kind: 'invert_palette', amount: 0.6, attack_seconds: 0, release_seconds: 0.5 }),
    ]),
  ]);
  assert.equal(peak(booleanHigh).layers.get('lay-01').invert, 1, 'crossing 0.5 flips deterministically');

  // authored opacity is the resting value; lift needs headroom, fade always works
  const dimmed = documentOf([
    scene('scene-01', 0, 8, [layer('lay-01', 0.5)], [
      chain('a', 'lay-01', RANKED('low', 'primary', 4), { kind: 'opacity_lift', amount: 0.5, attack_seconds: 0, release_seconds: 0.5 }),
    ]),
  ]);
  assert.equal(peak(dimmed).layers.get('lay-01').opacity, 1, 'lift brightens existing headroom');
  assert.equal(getDirectionState(compileDirection(dimmed, rhythm), 4).layers.get('lay-01').opacity, 0.5, 'resting opacity returns between events');
}

/* ---------------- v0.11 response relevance (never retrained) ---------------- */

{
  const rhythm = rhythmOf({
    duration: 8,
    onsets: [onset('strong-early', 0.1, 'low', 0.9), onset('relevant-late', 0.6, 'low', 0.3)],
    beats: gridBeats(4),
  });
  const doc = documentOf([
    scene('scene-01', 0, 8, [layer('lay-01')], [
      chain('r1', 'lay-01', RANKED('low', 'primary', 1, 0), { kind: 'translate_recoil', axis: [1, 0], amount: 0.05, attack_seconds: 0.01, release_seconds: 0.05 }),
    ]),
  ]);
  const without = compileDirection(doc, rhythm);
  assert.ok(Math.abs(getDirectionState(without, 0.11).layers.get('lay-01').translate.x) > 0, 'strength fallback picks the stronger onset');
  assert.equal(getDirectionState(without, 0.61).layers.get('lay-01').translate.x, 0, 'budget of one suppresses the weaker onset');

  const relevance = new Map([
    ['relevant-late', 0.95],
    ['strong-early', 0.1],
  ]);
  const withRelevance = compileDirection(doc, rhythm, { relevance });
  assert.equal(getDirectionState(withRelevance, 0.11).layers.get('lay-01').translate.x, 0, 'relevance outranks strength');
  assert.ok(Math.abs(getDirectionState(withRelevance, 0.61).layers.get('lay-01').translate.x) > 0, 'the relevant onset fires');
  // exact timestamps survive relevance selection
  const times = withRelevance.scenes[0].responses[0].times;
  assert.deepEqual(times, [0.6], 'no event timestamp was moved');
  assert.equal(withRelevance.diagnostics.relevance, true);
}

/* ---------------- reduced motion preserves edit meaning ---------------- */

{
  const out = { scale: 1.4, translate: { x: 20, y: -8 }, rotation: 6, opacity: 0.5, crop: 0.3, strip: 0.8, blur: 4, invert: 1 };
  const reduced = applyReducedMotion(out);
  assert.equal(reduced.translate.x, 5);
  assert.equal(reduced.translate.y, -2);
  assert.equal(reduced.rotation, 1.5);
  assert.ok(Math.abs(reduced.scale - 1.2) < 1e-9);
  assert.equal(reduced.strip, 0.2);
  assert.equal(reduced.blur, 2);
  // meaning-carrying channels are untouched
  assert.equal(reduced.opacity, 0.5);
  assert.equal(reduced.crop, 0.3);
  assert.equal(reduced.invert, 1);

  const rhythm = rhythmOf({ duration: 4, onsets: [onset('one', 0, 'low', 1)], beats: gridBeats(2) });
  const doc = documentOf([
    scene('scene-01', 0, 4, [layer('lay-01')], [
      chain('r1', 'lay-01', RANKED('low', 'primary', 4), { kind: 'translate_recoil', axis: [1, 0], amount: 0.2, attack_seconds: 0, release_seconds: 0.5 }),
    ]),
  ]);
  const compiled = compileDirection(doc, rhythm);
  const full = getDirectionState(compiled, 0).layers.get('lay-01');
  const calm = getDirectionState(compiled, 0, { reducedMotion: true }).layers.get('lay-01');
  assert.ok(Math.abs(calm.translate.x) < Math.abs(full.translate.x), 'reduced motion suppresses aggressive movement');
  assert.equal(calm.translate.x, full.translate.x * 0.25);
}

/* ---------------- video source time (§4.6) ---------------- */

assert.equal(videoSourceTime(5, 0, 0, 2, true), 1);
assert.equal(videoSourceTime(-0.5, 0, 0, 2, true), 1.5, 'negative local time wraps positively');
assert.equal(videoSourceTime(9, 2, 1, 3, false), 3, 'non-looping clamps to the authored duration');
assert.equal(videoSourceTime(4, 2, 1, 3, true), 0);

/* ---------------- no wall-clock or randomness in musical code ---------------- */

{
  const dir = new URL('./../web-src/src/motion/', import.meta.url);
  const files = (await readdir(dir)).filter((name) => name.endsWith('.ts'));
  for (const file of files) {
    const source = await readFile(new URL(file, dir), 'utf-8');
    assert.ok(!/Math\.random\s*\(/.test(source), `${file} must not use Math.random`);
    assert.ok(!/Date\.now\s*\(/.test(source), `${file} must not use Date.now`);
    assert.ok(!/performance\.now\s*\(/.test(source), `${file} must not use performance.now`);
  }
}

console.log(
  'motion chains: sparse/dense/off-grid/no-grid budgets, exact-time envelopes, ' +
    'seek determinism, transitions ±1 ms, combine bounds, relevance and reduced motion agree with the contract',
);
