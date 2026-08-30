/**
 * Stage controller skeleton tests (v0.6.1 plan commit 1): the controller
 * contract gates rendering on project + visibility before commit 4 rewires
 * the player onto it. Draw-path behaviour is exercised in the browser; here
 * we pin the Node-testable lifecycle decisions.
 */
import assert from 'node:assert/strict';

import {
  createVisualStage,
  installVisualDebug,
  normalizeTier,
  QUALITY_TIERS,
  qualityTierDecision,
} from '../beatscope/web/visual-stage.js';

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

console.log('Visual stage OK: lifecycle gating, diagnostics, debug entry contract.');
