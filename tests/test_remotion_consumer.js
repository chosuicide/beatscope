/**
 * Remotion reference consumer tests (v0.9 plan section 12).
 *
 * The composition's state module is pure and React-free, so Node can
 * pin the offline frame contract directly: the same second maps to the
 * same BeatScope state at any fps, frame N renders identically twice,
 * start offsets clamp to zero, beyond-duration frames clamp to the
 * final state, and the package surface still reproduces the frozen
 * checkpoints bit for bit.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { runCheckpointSuite } from '../beatscope/runtime/consumer-probe.js';

const moduleNamespace = await import(
  pathToFileURL(fileURLToPath(new URL('../examples/shared/fixture.beatscope/visual-state.js', import.meta.url))).href
);
const checkpoints = JSON.parse(
  readFileSync(new URL('../examples/shared/checkpoints.json', import.meta.url), 'utf8'),
);
const declaration = JSON.parse(
  readFileSync(new URL('../examples/remotion-composition/beatscope-consumer.json', import.meta.url), 'utf8'),
);
const stateModule = await import(
  pathToFileURL(fileURLToPath(new URL('../examples/remotion-composition/src/state.js', import.meta.url))).href
);

const { DURATION_SECONDS, frameTime, compositionDuration, sceneState } = stateModule;

// --- the frame source behind the composition reproduces the checkpoints -------

{
  const suite = runCheckpointSuite(moduleNamespace, checkpoints, {});
  assert.equal(suite.ok, true, `checkpoint suite failed: ${JSON.stringify(suite.errors)}`);
}

// --- declaration: offline, frame/fps clock, no promised window hook -------------

{
  assert.equal(declaration.schema, 'beatscope-consumer-1');
  assert.equal(declaration.framework, 'remotion');
  assert.equal(declaration.clock, 'frame/fps');
  assert.equal(declaration.capabilities.offline_frame, true);
  assert.equal(declaration.capabilities.playback, false);
  assert.ok(!('debug_hook' in declaration) || declaration.debug_hook === null);
}

// --- the clock rule: same second, same state, at 24 / 30 / 60 fps ---------------

{
  const at24 = sceneState(frameTime(24, 24));
  const at30 = sceneState(frameTime(30, 30));
  const at60 = sceneState(frameTime(60, 60));
  assert.deepEqual(at30, at24, '30 fps must map the same second to the same state');
  assert.deepEqual(at60, at24, '60 fps must map the same second to the same state');
  assert.equal(at24.time, 1);
}

// --- frame N renders identically twice -------------------------------------------

{
  const first = sceneState(frameTime(433, 30));
  const second = sceneState(frameTime(433, 30));
  assert.deepEqual(second, first, 'frame 433 must serialize identically twice');
  const other = sceneState(frameTime(434, 30));
  assert.notDeepEqual(other, first);
}

// --- start offsets and final-frame clamp ------------------------------------------

{
  assert.equal(frameTime(-7, 30), 0, 'negative frames clamp to zero');
  assert.deepEqual(sceneState(frameTime(0, 30)), sceneState(0));

  const final = sceneState(DURATION_SECONDS);
  const beyond = sceneState(DURATION_SECONDS + 5);
  // Scene ownership freezes on the final scene; timing keeps
  // extrapolating past the grid (the documented D6 behaviour).
  assert.deepEqual(beyond.scene, final.scene, 'scene ownership must clamp to the final scene');
  assert.deepEqual(beyond.composition, final.composition, 'composition must freeze past the end');
  assert.deepEqual(beyond.transition, final.transition);
  assert.ok(
    JSON.stringify(beyond.timing) !== JSON.stringify(final.timing),
    'timing extrapolates past the end instead of clamping',
  );
  const serialized = JSON.stringify(final);
  assert.ok(JSON.parse(serialized).scene.phase <= 1);
}

// --- composition duration derives from the package ---------------------------------

{
  assert.equal(DURATION_SECONDS, 30.0001);
  assert.equal(compositionDuration(24), 721);
  assert.equal(compositionDuration(30), 901);
  assert.equal(compositionDuration(60), 1801);
}

console.log('Remotion consumer OK: fps-invariant state, pure frames, clamps, package parity.');
