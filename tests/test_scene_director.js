/**
 * Scene director tests (v0.8 plan sections 9 and 19.2).
 *
 * The director is the shared seek-safe orchestrator for browser, MCP, and
 * export, so these tests pin the whole contract: exact scene ownership
 * (half-open interior ends, boundary ownership, final-scene duration),
 * approach/cross/settle envelope endpoints, composition interpolation
 * exactness, treatment channel mapping, purity under shuffled queries,
 * seek determinism, reduced-motion scaling, legacy neutrality, malformed
 * artifact rejection, frozen/finite frames, and O(log S) behavior on a
 * large synthetic timeline.
 */
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';

import {
  buildSceneIndexes,
  createSceneDirector,
  normalizeVisualArtifacts,
  sceneAt,
  transitionAt,
} from '../beatscope/runtime/scene-director.js';

const ZEROS = Object.freeze({ spread: 0, twist: 0, flow: 0, orbit: 0, void: 0, contrast: 0 });

const COMPOSITION_A = { spread: 0.14, twist: 0.08, flow: 0.32, orbit: 0.44, void: 0.18, contrast: 0.72 };
const COMPOSITION_B = { spread: 0.26, twist: 0.1, flow: 0.36, orbit: 0.62, void: 0.16, contrast: 0.74 };

function makeRecipe(overrides = {}) {
  return {
    schema: 'beatscope-visual-recipe-1',
    recipe_version: '0.8.0',
    project_id: 'a1b2c3d4e5f6',
    source_rhythm_sha256: '0'.repeat(64),
    seed: 'a1b2c3d4e5f6:visual-recipe-1',
    mode: 'structure',
    tokens: {
      palette: { paper: '#f4f1e9', ink: '#171713', accent: '#c65032', warm: '#fff1ce' },
      transition: { lead_beats: 1.0, settle_beats: 1.5, max_lead_seconds: 0.8, max_settle_seconds: 0.9 },
      motion: { max_scene_spread: 0.32, max_scene_twist: 0.28, max_palette_mix: 0.42 },
    },
    families: {
      A: { motif: 'compact-triad', palette_slot: 0, composition: { ...COMPOSITION_A } },
      B: { motif: 'orbital-weave', palette_slot: 1, composition: { ...COMPOSITION_B } },
    },
    diagnostics: { family_count: 2, motif_bank_version: 'motif-bank-1', warnings: [] },
    ...overrides,
  };
}

function makeTimeline(overrides = {}) {
  return {
    schema: 'beatscope-visual-timeline-1',
    recipe_version: '0.8.0',
    project_id: 'a1b2c3d4e5f6',
    duration: 16,
    mode: 'structure',
    scenes: [
      {
        id: 'scene-001', segment_id: 'segment-001', segment_index: 0, family: 'A', variant: 0,
        label: 'A', start_time: 0, end_time: 8, motif: 'compact-triad', variant_delta: { ...ZEROS },
      },
      {
        id: 'scene-002', segment_id: 'segment-002', segment_index: 1, family: 'B', variant: 0,
        label: 'B', start_time: 8, end_time: 16, motif: 'orbital-weave', variant_delta: { ...ZEROS },
      },
    ],
    transitions: [
      {
        id: 'transition-001', boundary_bar: 5, time: 8, from_scene: 'scene-001', to_scene: 'scene-002',
        treatment: 'phase-turn', strength: 0.8, driver: 'harmony', lead_seconds: 0.5, settle_seconds: 0.75,
      },
    ],
    diagnostics: { scene_count: 2, transition_count: 1, warnings: [] },
    ...overrides,
  };
}

function makeLegacyArtifacts() {
  const recipe = makeRecipe({
    mode: 'legacy',
    families: { LEGACY: { motif: 'compact-triad', palette_slot: 0, composition: { ...ZEROS } } },
  });
  const timeline = makeTimeline({
    mode: 'legacy',
    duration: 48,
    scenes: [
      {
        id: 'scene-001', segment_id: null, segment_index: 0, family: 'LEGACY', variant: 0,
        label: 'LEGACY', start_time: 0, end_time: 48, motif: 'compact-triad', variant_delta: { ...ZEROS },
      },
    ],
    transitions: [],
  });
  return { recipe, timeline };
}

// --- exact scene lookup -----------------------------------------------------
{
  const director = createSceneDirector(makeRecipe(), makeTimeline());
  assert.equal(director.at(0).scene.id, 'scene-001');
  assert.equal(director.at(0).scene.phase, 0);
  assert.equal(director.at(4).scene.id, 'scene-001');
  assert.equal(director.at(4).scene.phase, 0.5);
  assert.equal(director.at(7.999).scene.id, 'scene-001');
  // The next scene owns the exact boundary time.
  assert.equal(director.at(8).scene.id, 'scene-002');
  assert.equal(director.at(15.999).scene.id, 'scene-002');
  // The final scene owns the exact duration.
  assert.equal(director.at(16).scene.id, 'scene-002');
  assert.equal(director.at(16).scene.phase, 1);
  assert.equal(director.at(16).transition.stage, 'idle');
}

// --- half-open semantics at boundary +/- 1ms --------------------------------
{
  const director = createSceneDirector(makeRecipe(), makeTimeline());
  assert.equal(director.at(8 - 0.001).scene.id, 'scene-001');
  assert.equal(director.at(8 + 0.001).scene.id, 'scene-002');
  assert.equal(director.at(8 + 0.001).transition.stage, 'settle');
}

// --- before-zero and after-duration behavior --------------------------------
{
  const director = createSceneDirector(makeRecipe(), makeTimeline());
  const early = director.at(-1);
  assert.equal(early.scene.id, 'scene-001');
  assert.equal(early.scene.phase, 0);
  assert.equal(director.at(16.5), null);
  const clamped = createSceneDirector(makeRecipe(), makeTimeline(), { clamp: true });
  const late = clamped.at(40);
  assert.equal(late.scene.id, 'scene-002');
  assert.equal(late.scene.phase, 1);
  // Seek far beyond the duration stays stable across repeats.
  const stripTime = (frame) => {
    const { time, ...rest } = JSON.parse(JSON.stringify(frame));
    return rest;
  };
  assert.deepEqual(stripTime(clamped.at(40)), stripTime(clamped.at(99)));
}

// --- approach/cross/settle endpoints ----------------------------------------
{
  const director = createSceneDirector(makeRecipe(), makeTimeline());
  const idleBefore = director.at(7.4);
  assert.equal(idleBefore.transition.stage, 'idle');
  assert.equal(idleBefore.composition.spread, COMPOSITION_A.spread);

  const approachStart = director.at(7.5);
  assert.equal(approachStart.transition.stage, 'approach');
  assert.equal(approachStart.transition.approach, 0);
  assert.equal(approachStart.transition.channels.phaseTurn, 0);

  const approachMid = director.at(7.75);
  assert.equal(approachMid.transition.approach, 0.5);
  assert.equal(approachMid.transition.channels.phaseTurn, 0.5);
  // Approach must not reveal the next scene: composition stays on A.
  assert.equal(approachMid.composition.spread, COMPOSITION_A.spread);

  const cross = director.at(8);
  assert.equal(cross.transition.stage, 'cross');
  assert.equal(cross.transition.approach, 1);
  assert.equal(cross.transition.cross, 0.8);
  assert.equal(cross.transition.impulse, 0.8);
  assert.equal(cross.composition.spread, COMPOSITION_A.spread, 'composition is continuous at the boundary');

  const settleMid = director.at(8.375);
  assert.equal(settleMid.transition.stage, 'settle');
  assert.equal(settleMid.transition.settle, 0.5);
  assert.equal(settleMid.scene.id, 'scene-002');
  assert.equal(settleMid.transition.channels.contrastHit, 0.4);

  // The settle window is (b, b + settle]; 8.75 is its final instant.
  const settleEnd = director.at(8.75);
  assert.equal(settleEnd.transition.stage, 'settle');
  assert.equal(settleEnd.transition.settle, 0);
  assert.ok(Math.abs(settleEnd.composition.spread - COMPOSITION_B.spread) < 1e-12);
  const afterSettle = director.at(8.75 + 1e-3);
  assert.equal(afterSettle.transition.stage, 'idle');
  assert.ok(Math.abs(afterSettle.composition.spread - COMPOSITION_B.spread) < 1e-12);
}

// --- interpolation exactness -------------------------------------------------
{
  const director = createSceneDirector(makeRecipe(), makeTimeline());
  // smoothstep(0.5) = 0.5, so the settle midpoint is the exact lerp midpoint.
  const mid = director.at(8.375).composition;
  assert.ok(Math.abs(mid.spread - (COMPOSITION_A.spread + COMPOSITION_B.spread) / 2) < 1e-12);
  assert.ok(Math.abs(mid.contrast - (COMPOSITION_A.contrast + COMPOSITION_B.contrast) / 2) < 1e-12);
  assert.ok(Math.abs(mid.paletteMix - 0.5 * 0.42) < 1e-12);
  assert.ok(mid.spread >= 0 && mid.spread <= 1);
  // Quarter point: smoothstep(0.25) = 0.15625.
  const quarter = director.at(8 + 0.75 * 0.25).composition;
  assert.ok(Math.abs(quarter.paletteMix - 0.15625 * 0.42) < 1e-12);
}

// --- continuity except the impulse -------------------------------------------
{
  const director = createSceneDirector(makeRecipe(), makeTimeline());
  let previous = director.at(7.9).composition.spread;
  for (let t = 7.9 + 1e-3; t <= 8.6 + 1e-12; t += 1e-3) {
    const current = director.at(t).composition.spread;
    assert.ok(
      Math.abs(current - previous) < 5e-3,
      `composition spread must stay continuous at t=${t}`,
    );
    previous = current;
  }
  const impulse = director.at(8).transition.impulse;
  assert.equal(impulse, 0.8);
  assert.equal(director.at(8 - 1e-9).transition.impulse, 0, 'no impulse before the boundary');
  assert.equal(director.at(8 + 1e-9).transition.impulse, 0, 'no impulse after the boundary');
}

// --- treatment channel mapping -----------------------------------------------
{
  const treatments = [
    ['phase-turn', 'phaseTurn'],
    ['radial-part', 'radialPart'],
    ['aperture', 'aperture'],
  ];
  for (const [treatment, channel] of treatments) {
    const timeline = makeTimeline({
      transitions: [
        { ...makeTimeline().transitions[0], treatment, driver: 'energy' },
      ],
    });
    const director = createSceneDirector(makeRecipe(), timeline);
    assert.equal(director.at(7.75).transition.channels[channel], 0.5, treatment);
    assert.equal(director.at(8.375).transition.channels[channel], 0.5, treatment);
    for (const key of ['phaseTurn', 'radialPart', 'aperture', 'flowShear']) {
      if (key !== channel) {
        assert.equal(director.at(8.375).transition.channels[key], 0, `${treatment} leaves ${key} at 0`);
      }
    }
  }
  // flow-shear is signed and deterministic per transition id.
  const shear = makeTimeline({
    transitions: [
      { ...makeTimeline().transitions[0], treatment: 'flow-shear', driver: 'timbre' },
    ],
  });
  const shearDirector = createSceneDirector(makeRecipe(), shear);
  const shearMid = shearDirector.at(8.375).transition.channels.flowShear;
  assert.ok(Math.abs(Math.abs(shearMid) - 0.5) < 1e-12, 'flowShear magnitude follows the envelope');
  assert.equal(shearMid, shearDirector.at(8.375).transition.channels.flowShear, 'sign is deterministic');
  // cross-settle (neutral) keeps every motion channel at zero.
  const neutral = makeTimeline({
    transitions: [
      { ...makeTimeline().transitions[0], treatment: 'cross-settle', driver: 'neutral', strength: 0.2 },
    ],
  });
  const neutralDirector = createSceneDirector(makeRecipe(), neutral);
  const neutralChannels = neutralDirector.at(8.375).transition.channels;
  assert.equal(neutralChannels.phaseTurn, 0);
  assert.equal(neutralChannels.radialPart, 0);
  assert.equal(neutralChannels.aperture, 0);
  assert.equal(neutralChannels.flowShear, 0);
  assert.ok(neutralChannels.contrastHit > 0, 'contrast accent crossfades for every treatment');
}

// --- purity: shuffled query order never changes results ----------------------
{
  // Deterministic PRNG (mulberry32); the director itself never sees it.
  function mulberry32(seed) {
    let state = seed >>> 0;
    return () => {
      state = (state + 0x6d2b79f5) | 0;
      let t = Math.imul(state ^ (state >>> 15), 1 | state);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const director = createSceneDirector(makeRecipe(), makeTimeline());
  const times = [];
  for (let t = 0; t <= 16; t += 0.125) times.push(Number(t.toFixed(4)));
  const ordered = times.map((t) => JSON.stringify(director.at(t)));

  const random = mulberry32(0x5eed);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const shuffled = [...times];
    for (let i = shuffled.length - 1; i > 0; i -= 1) {
      const j = Math.floor(random() * (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    const results = shuffled.map((t) => JSON.stringify(director.at(t)));
    const byTime = new Map(shuffled.map((t, index) => [t, results[index]]));
    for (let i = 0; i < times.length; i += 1) {
      assert.equal(byTime.get(times[i]), ordered[i], `query order must not change t=${times[i]}`);
    }
  }
}

// --- seek determinism ---------------------------------------------------------
{
  const director = createSceneDirector(makeRecipe(), makeTimeline());
  director.at(1);
  director.at(40);
  createSceneDirector(makeRecipe(), makeTimeline(), { clamp: true }).at(40);
  assert.deepEqual(
    JSON.parse(JSON.stringify(director.at(3))),
    JSON.parse(JSON.stringify(createSceneDirector(makeRecipe(), makeTimeline()).at(3))),
    'seeking 1s -> 40s -> 3s must equal a fresh query at 3s',
  );
}

// --- reduced motion ------------------------------------------------------------
{
  const full = createSceneDirector(makeRecipe(), makeTimeline());
  const reduced = createSceneDirector(makeRecipe(), makeTimeline(), { reducedMotion: true });

  const fullMid = full.at(8.375);
  const reducedMid = reduced.at(8.375);
  // spread interpolates at 20%: 0.14 + (0.26-0.14) * 0.5 * 0.2
  assert.ok(Math.abs(reducedMid.composition.spread - 0.152) < 1e-12);
  const fullDisplacement = Math.abs(fullMid.composition.spread - COMPOSITION_A.spread);
  const reducedDisplacement = Math.abs(reducedMid.composition.spread - COMPOSITION_A.spread);
  assert.ok(reducedDisplacement <= fullDisplacement * 0.2 + 1e-12, 'reduced-motion spread moves at most 20%');
  // contrast still crossfades fully.
  assert.ok(Math.abs(reducedMid.composition.contrast - 0.73) < 1e-12);
  assert.ok(Math.abs(reducedMid.composition.paletteMix - fullMid.composition.paletteMix) < 1e-12);

  assert.equal(reduced.at(8).transition.impulse, 0.8 * 0.15, 'impulse scales to 15%');
  assert.ok(Math.abs(reduced.at(7.75).transition.channels.phaseTurn - 0.5 * 0.2) < 1e-12);
  assert.equal(reduced.at(8).transition.channels.contrastHit, 0.8, 'contrast accent keeps crossfading');
  // No channel is removed and scene identity/timing facts stay identical.
  assert.deepEqual(Object.keys(reducedMid.transition.channels), Object.keys(fullMid.transition.channels));
  assert.deepEqual(JSON.parse(JSON.stringify(reducedMid.scene)), JSON.parse(JSON.stringify(fullMid.scene)));
}

// --- legacy neutral state -------------------------------------------------------
{
  const { recipe, timeline } = makeLegacyArtifacts();
  const director = createSceneDirector(recipe, timeline);
  for (const t of [0, 12.5, 47.999, 48]) {
    const frame = director.at(t);
    assert.equal(frame.mode, 'legacy');
    assert.equal(frame.scene.family, 'LEGACY');
    assert.equal(frame.transition.stage, 'idle');
    for (const key of ['spread', 'twist', 'flow', 'orbit', 'void', 'contrast']) {
      assert.equal(frame.composition[key], 0, `legacy ${key} stays neutral`);
    }
    assert.equal(frame.composition.paletteMix, 0);
  }
}

// --- malformed artifacts are rejected -------------------------------------------
{
  const recipe = makeRecipe();
  const timeline = makeTimeline();
  assert.throws(() => normalizeVisualArtifacts(null, timeline), TypeError);
  assert.throws(() => normalizeVisualArtifacts(recipe, null), TypeError);
  assert.throws(() => normalizeVisualArtifacts({ ...recipe, schema: 'nope' }, timeline), /schema/);
  assert.throws(() => normalizeVisualArtifacts(recipe, { ...timeline, schema: 'nope' }), /schema/);
  assert.throws(() => normalizeVisualArtifacts(recipe, { ...timeline, scenes: [] }), /scene/);
  assert.throws(() => normalizeVisualArtifacts(recipe, { ...timeline, transitions: 'nope' }), /transitions/);
  assert.throws(
    () => normalizeVisualArtifacts(recipe, { ...timeline, scenes: [{ ...timeline.scenes[0], id: '' }, timeline.scenes[1]] }),
    TypeError,
  );
  assert.throws(
    () => normalizeVisualArtifacts(recipe, { ...timeline, transitions: [{ ...timeline.transitions[0], treatment: 'explode' }] }),
    /treatment/,
  );
  assert.throws(
    () => normalizeVisualArtifacts(recipe, { ...timeline, transitions: [{ ...timeline.transitions[0], time: 99 }] }),
    /boundary/,
  );
  assert.throws(
    () => createSceneDirector(recipe, { ...timeline, scenes: [{ ...timeline.scenes[0], family: 'Z' }, timeline.scenes[1]] }),
    /family/,
  );
}

// --- all frames frozen and finite ------------------------------------------------
{
  const director = createSceneDirector(makeRecipe(), makeTimeline(), { clamp: true });
  const walk = (value, path) => {
    if (value && typeof value === 'object') {
      assert.ok(Object.isFrozen(value), `${path} must be frozen`);
      for (const [key, item] of Object.entries(value)) walk(item, `${path}.${key}`);
    } else if (typeof value === 'number') {
      assert.ok(Number.isFinite(value), `${path} must be finite`);
    }
  };
  for (const t of [0, 4, 7.75, 8, 8.375, 9.5, 16, 20]) {
    walk(director.at(t), `frame(${t})`);
  }
  const frame = director.at(4);
  assert.throws(() => {
    'use strict';
    frame.composition.spread = 99;
  }, TypeError);
}

// --- standalone sceneAt / transitionAt --------------------------------------------
{
  const recipe = makeRecipe();
  const timeline = makeTimeline();
  const indexes = buildSceneIndexes(timeline);
  assert.equal(sceneAt(recipe, timeline, indexes, 4).id, 'scene-001');
  assert.equal(sceneAt(recipe, timeline, indexes, 8).id, 'scene-002');
  assert.equal(sceneAt(recipe, timeline, indexes, 99), null);
  assert.equal(sceneAt(recipe, timeline, indexes, 99, { clamp: true }).phase, 1);
  assert.equal(sceneAt(recipe, timeline, null, 4).id, 'scene-001', 'indexes built on demand');
  const active = transitionAt(recipe, timeline, indexes, 8.375);
  assert.equal(active.stage, 'settle');
  assert.equal(active.id, 'transition-001');
  assert.equal(transitionAt(recipe, timeline, indexes, 4), null);
  assert.equal(transitionAt(recipe, timeline, indexes, 8).impulse, 0.8);
}

// --- O(log S) on a large synthetic timeline ----------------------------------------
{
  const sceneCount = 50000;
  const families = ['A', 'B', 'C', 'D'];
  const compositions = {
    A: COMPOSITION_A,
    B: COMPOSITION_B,
    C: { spread: 0.2, twist: 0.12, flow: 0.56, orbit: 0.3, void: 0.24, contrast: 0.7 },
    D: { spread: 0.3, twist: 0.16, flow: 0.24, orbit: 0.52, void: 0.22, contrast: 0.66 },
  };
  const scenes = [];
  const transitions = [];
  for (let index = 0; index < sceneCount; index += 1) {
    const family = families[index % families.length];
    scenes.push({
      id: `scene-${String(index + 1).padStart(6, '0')}`,
      segment_id: `segment-${String(index + 1).padStart(6, '0')}`,
      segment_index: index,
      family,
      variant: 0,
      label: family,
      start_time: index,
      end_time: index + 1,
      motif: 'compact-triad',
      variant_delta: { ...ZEROS },
    });
    if (index > 0) {
      transitions.push({
        id: `transition-${String(index).padStart(6, '0')}`,
        boundary_bar: index * 4 + 1,
        time: index,
        from_scene: scenes[index - 1].id,
        to_scene: scenes[index].id,
        treatment: 'cross-settle',
        strength: 0.5,
        driver: 'neutral',
        lead_seconds: 0.25,
        settle_seconds: 0.35,
      });
    }
  }
  const timeline = makeTimeline({ duration: sceneCount, scenes, transitions });
  const recipe = makeRecipe({
    families: Object.fromEntries(
      families.map((family, index) => [family, { motif: 'compact-triad', palette_slot: index, composition: { ...compositions[family] } }]),
    ),
  });
  const director = createSceneDirector(recipe, timeline);

  // Correctness spot checks deep inside the timeline.
  assert.equal(director.at(37543.5).scene.id, 'scene-037544');
  assert.equal(director.at(sceneCount).scene.phase, 1);

  const queries = 2000;
  const random = mulberry32(0xc0ffee);
  const durations = [];
  for (let index = 0; index < queries; index += 1) {
    const t = random() * sceneCount;
    const start = performance.now();
    director.at(t);
    durations.push(performance.now() - start);
  }
  durations.sort((a, b) => a - b);
  const p95 = durations[Math.floor(queries * 0.95)];
  assert.ok(
    p95 < 0.1,
    `scene query p95 must stay under 0.10ms at S=${sceneCount}, got ${p95.toFixed(4)}ms`,
  );
}

function mulberry32(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
