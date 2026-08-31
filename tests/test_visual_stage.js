/**
 * Stage controller skeleton tests (v0.6.1 plan commit 1): the controller
 * contract gates rendering on project + visibility before commit 4 rewires
 * the player onto it. Draw-path behaviour is exercised in the browser; here
 * we pin the Node-testable lifecycle decisions.
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import {
  createVisualStage,
  installVisualDebug,
  normalizeTier,
  QUALITY_TIERS,
  qualityTierDecision,
} from '../beatscope/web/visual-stage.js';
import { SPREAD_LIMITS } from '../beatscope/runtime/visual-profile.js';
import { assertFiniteFrame } from './helpers/visual-frame.js';
import { makeVisualRecipe, makeVisualTimeline } from './helpers/visual-artifacts.js';

const fixtureProject = JSON.parse(
  await readFile(new URL('./fixtures/runtime/characterization-project.json', import.meta.url), 'utf-8'),
);

// An overlay canvas is required; the layering split arrives with commit 4.
assert.throws(() => createVisualStage({}), /overlayCanvas/);

const stage = createVisualStage({ overlayCanvas: {} });

// Without a project nothing renders (and the canvas is never touched).
assert.doesNotThrow(() => stage.render({ playbackTime: 1.0 }));
assert.equal(stage.getDiagnostics().framesRendered, 0);

// Hidden stages never render, even with a project set.
stage.setProject({ tempo: { global_bpm: 120 } });
stage.setVisible(false);
stage.render({ playbackTime: 1.0 });
assert.equal(stage.getDiagnostics().framesRendered, 0);

// Diagnostics are honest numbers.
const diagnostics = stage.getDiagnostics();
assert.equal(diagnostics.backend, 'canvas-compat');
assert.equal(diagnostics.visible, false);
assert.ok(Number.isFinite(diagnostics.lastFrameCostMs));

// Debug API: fixed-time render, honest diagnostics, backend forcing.
const debug = installVisualDebug(stage, { isLocal: () => true });
assert.deepEqual(debug.renderAt(0, { quality: 'high', reducedMotion: false }), stage.getDiagnostics());
assert.equal(debug.forceBackend('canvas').backend, 'canvas');
assert.equal(debug.forceBackend('webgl2').backend, 'webgl2');
assert.equal(debug.forceBackend('bogus').backend, 'canvas-compat');
assert.equal(typeof debug.diagnostics(), 'object');

// Commit 5: tier presets match the plan table (section 7.3).
assert.deepEqual(QUALITY_TIERS.high, { dprCap: 1.5, count: 18000 });
assert.deepEqual(QUALITY_TIERS.medium, { dprCap: 1.25, count: 11000 });
assert.deepEqual(QUALITY_TIERS.low, { dprCap: 1, count: 6000 });
assert.equal(normalizeTier('medium'), 'medium');
assert.equal(normalizeTier('extreme'), null);

// Hysteresis (section 8.2): three hot windows downgrade one tier.
let walk = { tier: 'high', overWindows: 0, underWindows: 0 };
for (let index = 0; index < 2; index += 1) {
  walk = qualityTierDecision({ ...walk, p95: 20, playing: true, visible: true, msSinceChange: 100000 });
}
assert.equal(walk.overWindows, 2);
walk = qualityTierDecision({ ...walk, p95: 20, playing: true, visible: true, msSinceChange: 100000 });
assert.equal(walk.tier, 'medium');
assert.equal(walk.overWindows, 0);

// The five-second cooldown gates the change without losing the streak.
const blocked = qualityTierDecision({
  tier: 'high', p95: 25, overWindows: 2, underWindows: 0, playing: true, visible: true, msSinceChange: 4999,
});
assert.equal(blocked.tier, 'high');
assert.equal(blocked.overWindows, 3);
const changed = qualityTierDecision({
  tier: 'high', p95: 25, overWindows: 2, underWindows: 0, playing: true, visible: true, msSinceChange: 5000,
});
assert.equal(changed.tier, 'medium');

// Five cool windows upgrade one tier.
let up = { tier: 'low', overWindows: 0, underWindows: 0 };
for (let index = 0; index < 4; index += 1) {
  up = qualityTierDecision({ ...up, p95: 5, playing: true, visible: true, msSinceChange: 100000 });
}
assert.equal(up.tier, 'low');
up = qualityTierDecision({ ...up, p95: 5, playing: true, visible: true, msSinceChange: 100000 });
assert.equal(up.tier, 'medium');

// Paused or hidden stages reset streaks instead of acting on stale frames.
const paused = qualityTierDecision({
  tier: 'high', p95: 25, overWindows: 2, underWindows: 0, playing: false, visible: true, msSinceChange: 100000,
});
assert.equal(paused.tier, 'high');
assert.equal(paused.overWindows, 0);

// Forced tiers, manual tiers and forced backends all stay usable.
const debug2 = installVisualDebug(stage, { isLocal: () => true });
assert.equal(debug2.forceTier('low').tier, 'low');
assert.equal(debug2.forceTier('low').qualitySource, 'fixed');
assert.doesNotThrow(() => stage.render({ playbackTime: 2.0, reducedMotion: true }));
assert.equal(debug2.forceTier(null).qualitySource, 'adaptive');
assert.equal(debug2.forceTier('bogus').qualitySource, 'adaptive');
assert.equal(debug2.setTier('low').tier, 'low');
assert.equal(debug2.forceBackend('canvas').backend, 'canvas');
assert.doesNotThrow(() => stage.render({ playbackTime: 2.0 }));
assert.ok(Number.isFinite(debug2.diagnostics().lastFrameCostMs));
debug2.forceBackend(null);
debug2.setTier('high');

stage.dispose();
assert.equal(stage.getDiagnostics().framesRendered, 0);

// --- v0.8 commit 4: the three-source frame and scene artifacts (plan
// sections 10 and 12). A stub 2d context keeps the Node-testable surface
// honest: the frame construction and gating logic run exactly as in the
// browser, while the drawing itself is exercised there.
function stubStageCanvas() {
  const gradient = { addColorStop() {} };
  const methods = {};
  const ctx = new Proxy(methods, {
    get(target, prop) {
      if (prop === 'createRadialGradient' || prop === 'createLinearGradient') return () => gradient;
      if (prop === 'canvas') return null;
      if (!(prop in target)) target[prop] = () => {};
      return target[prop];
    },
    set(target, prop, value) {
      target[prop] = value;
      return true;
    },
  });
  return {
    getContext: () => ctx,
    clientWidth: 1200,
    clientHeight: 520,
    width: 1200,
    height: 520,
    style: {},
  };
}

{
  const frames = [];
  const sceneStage = createVisualStage({
    overlayCanvas: stubStageCanvas(),
    onFrame: (frame) => frames.push(frame),
  });
  sceneStage.setVisible(true);
  sceneStage.setProject(fixtureProject);
  sceneStage.render({ playbackTime: 2.5, isPlaying: false, reducedMotion: false });
  assert.equal(frames.length, 1);
  const legacyFrame = frames[0];
  // The combined frame: beat fields at the top, sources in named slots.
  assertFiniteFrame(legacyFrame, ['impactAge', 'age'], 'stage frame');
  assert.ok(legacyFrame.signal && legacyFrame.motion && legacyFrame.compat && legacyFrame.layout);
  // Beat fields ride the top level; the .motion slot is the same director frame.
  assert.equal(legacyFrame.lobeSplit, legacyFrame.motion.lobeSplit);
  assert.equal(legacyFrame.scene, null); // no artifacts attached yet
  assert.equal(sceneStage.getDiagnostics().sceneAvailable, false);
  assert.equal(sceneStage.sceneAt(2.5), null);

  // Attach valid artifacts: the scene block arrives and sceneAt agrees.
  sceneStage.setVisualArtifacts(makeVisualRecipe(), makeVisualTimeline());
  assert.equal(sceneStage.getDiagnostics().sceneAvailable, true);
  const sceneBlock = sceneStage.sceneAt(4);
  assert.equal(sceneBlock.scene.family, 'A');
  assert.equal(sceneBlock.scene.motif, 'compact-triad');

  frames.length = 0;
  sceneStage.render({ playbackTime: 4, isPlaying: false, reducedMotion: false });
  const sceneFrame = frames[0];
  assert.equal(sceneFrame.scene.scene.family, 'A');
  assert.ok(sceneFrame.scene.composition.spread >= 0
    && sceneFrame.scene.composition.spread <= SPREAD_LIMITS.steadyMax);
  assert.ok(Number.isFinite(sceneFrame.scene.composition.paletteMix));

  // FOLLOW STRUCTURE OFF: neutral legacy composition, beats still reactive.
  sceneStage.setFollowStructure(false);
  assert.equal(sceneStage.getDiagnostics().followStructure, false);
  frames.length = 0;
  sceneStage.render({ playbackTime: 4, isPlaying: false, reducedMotion: false });
  assert.equal(frames[0].scene, null);
  assert.ok(Number.isFinite(frames[0].beatExpand));

  // ON again restores the scene block without re-fetching artifacts.
  sceneStage.setFollowStructure(true);
  frames.length = 0;
  sceneStage.render({ playbackTime: 4, isPlaying: false, reducedMotion: false });
  assert.ok(frames[0].scene);

  // Clearing artifacts returns the stage to legacy mode.
  sceneStage.setVisualArtifacts(null, null);
  assert.equal(sceneStage.getDiagnostics().sceneAvailable, false);
  assert.equal(sceneStage.sceneAt(4), null);

  // Malformed artifacts are rejected loudly and never poison the stage.
  assert.throws(() => sceneStage.setVisualArtifacts({ schema: 'nope' }, makeVisualTimeline()), /scene director/);
  sceneStage.setVisualArtifacts(null, null);
  assert.equal(sceneStage.getDiagnostics().sceneAvailable, false);

  sceneStage.dispose();
}

// --- v0.8 commit 6: reduced-motion frame flag, canvas fallback with a live
// scene block, and the shipped toggle/aria contract (plan sections 9/12.4).
{
  const frames = [];
  const accessStage = createVisualStage({
    overlayCanvas: stubStageCanvas(),
    onFrame: (frame) => frames.push(frame),
  });
  accessStage.setVisible(true);
  accessStage.setProject(fixtureProject);
  accessStage.setVisualArtifacts(makeVisualRecipe(), makeVisualTimeline());

  // The reduced-motion preference rides the frame for every consumer.
  accessStage.render({ playbackTime: 4, isPlaying: false, reducedMotion: true });
  assert.equal(frames[0].reducedMotion, true);
  assert.ok(frames[0].scene, 'reduced motion keeps the scene block');
  frames.length = 0;
  accessStage.render({ playbackTime: 4, isPlaying: false, reducedMotion: false });
  assert.equal(frames[0].reducedMotion, false);

  // Live preference changes must reach the scene director, not merely ride
  // along as a frame marker for the renderer.
  frames.length = 0;
  accessStage.render({ playbackTime: 7.75, isPlaying: false, reducedMotion: false });
  const fullPhaseTurn = frames[0].scene.transition.channels.phaseTurn;
  frames.length = 0;
  accessStage.render({ playbackTime: 7.75, isPlaying: false, reducedMotion: true });
  const reducedPhaseTurn = frames[0].scene.transition.channels.phaseTurn;
  assert.ok(fullPhaseTurn > 0);
  assert.ok(Math.abs(reducedPhaseTurn - fullPhaseTurn * 0.2) < 1e-12);

  // Canvas fallback still renders the scene-driven frame (plan section 9).
  const accessDebug = installVisualDebug(accessStage, { isLocal: () => true });
  assert.equal(accessDebug.forceBackend('canvas').backend, 'canvas');
  frames.length = 0;
  accessStage.render({ playbackTime: 4, isPlaying: false, reducedMotion: true });
  assert.ok(frames[0].scene, 'canvas fallback keeps the scene block');
  assert.ok(Number.isFinite(accessDebug.diagnostics().lastFrameCostMs));
  accessDebug.forceBackend(null);

  accessStage.dispose();
}

{
  const markup = await readFile(new URL('../beatscope/web/index.html', import.meta.url), 'utf-8');
  // The follow-structure toggle ships checked, hidden until artifacts land.
  assert.match(markup, /id="followStructureControl"[^>]*hidden/);
  assert.match(markup, /id="followStructure" type="checkbox" checked/);
  // The stage stack and seek control stay reachable for assistive tech.
  assert.match(markup, /id="visualStageStack"[^>]*role="img"/);
  assert.match(markup, /id="visualStageStack"[^>]*aria-label="Audio-reactive particle instrument driven by playback time"/);
  assert.match(markup, /id="seekRange"[^>]*aria-label="Seek audio"/);
}

console.log('Visual stage OK: lifecycle gating, diagnostics, debug entry contract.');
