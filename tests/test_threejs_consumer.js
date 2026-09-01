/**
 * Three.js reference consumer tests (v0.9 plan section 11).
 *
 * The mapping and geometry modules stay Three.js-free so Node can pin
 * them directly: checkpoint parity through the package's own probe,
 * deterministic mapping (sequential playback vs direct seek), seeded
 * geometry reproducibility, and declaration honesty.
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
  readFileSync(new URL('../examples/threejs-geometry/beatscope-consumer.json', import.meta.url), 'utf8'),
);
const mapping = await import(
  pathToFileURL(fileURLToPath(new URL('../examples/threejs-geometry/src/beatscope-mapping.js', import.meta.url))).href
);
const geometry = await import(
  pathToFileURL(fileURLToPath(new URL('../examples/threejs-geometry/src/seeded-geometry.js', import.meta.url))).href
);

// --- the frame source the mapping consumes reproduces the checkpoints --------

{
  const suite = runCheckpointSuite(moduleNamespace, checkpoints, {});
  assert.equal(suite.ok, true, `checkpoint suite failed: ${JSON.stringify(suite.errors)}`);
}

// --- declaration honesty -------------------------------------------------------

{
  assert.equal(declaration.schema, 'beatscope-consumer-1');
  assert.equal(declaration.framework, 'three');
  assert.equal(declaration.clock, 'audio.currentTime');
  assert.equal(declaration.capabilities.playback, true);
  assert.equal(declaration.capabilities.reduced_motion, true);
  assert.equal(typeof declaration.draw_call_budget, 'number');
  assert.ok(declaration.draw_call_budget >= 1);
}

// --- mapping is pure and matches the plan contract -----------------------------

{
  const frame = moduleNamespace.getBeatScopeFrame(1.0);
  const a = mapping.mapFrame(frame, 1.0);
  const b = mapping.mapFrame(moduleNamespace.getBeatScopeFrame(1.0), 1.0);
  assert.deepEqual(b, a, 'mapFrame must be a pure function of (frame, time)');
  assert.equal(a.scale, 1 + frame.timing.low * 0.25);
  assert.equal(a.twist, frame.scene.composition.twist);
  assert.equal(a.transition, frame.scene.transition.cross);
  assert.equal(a.cameraPhase, 1.0 * 0.08);
}

// --- sequential playback and direct seek produce identical mappings -------------

{
  const sequential = [];
  for (const time of checkpoints.times) {
    sequential.push(mapping.mapFrame(moduleNamespace.getBeatScopeFrame(time), time));
  }
  // Now traverse the whole seek sequence, then re-derive the checkpoint
  // frames again — accumulated state would make the second pass differ.
  for (const time of checkpoints.seek_sequence) {
    mapping.mapFrame(moduleNamespace.getBeatScopeFrame(time), time);
  }
  const afterSeek = checkpoints.times.map((time) =>
    mapping.mapFrame(moduleNamespace.getBeatScopeFrame(time), time),
  );
  assert.deepEqual(afterSeek, sequential, 'mapping drifted after seeks');
}

// --- reduced motion lowers the motion-scaled amplitudes only --------------------

{
  const time = 15.365075;
  const fullFrame = moduleNamespace.getBeatScopeFrame(time);
  const reducedFrame = moduleNamespace.getBeatScopeFrame(time, { reducedMotion: true });
  assert.deepEqual(
    JSON.parse(JSON.stringify(fullFrame.timing)),
    JSON.parse(JSON.stringify(reducedFrame.timing)),
  );
  const base = 0.6 + fullFrame.scene.composition.contrast * 0.35;
  const fullOpacity = mapping.pointOpacity(fullFrame, false);
  const reducedOpacity = mapping.pointOpacity(reducedFrame, true);
  // Reduced motion halves the boundary easing, so opacity stays closer
  // to its base while timing state is untouched.
  assert.ok(Math.abs(reducedOpacity - base) <= Math.abs(fullOpacity - base));
}

// --- seeded geometry is reproducible and finite ---------------------------------

{
  const a = geometry.seededShell(200, 42);
  const b = geometry.seededShell(200, 42);
  assert.deepEqual(Array.from(b), Array.from(a), 'same seed must reproduce geometry');
  assert.ok(Array.from(a).every((v) => Number.isFinite(v)));
  assert.notDeepEqual(Array.from(geometry.seededShell(200, 7)), Array.from(a));
}

console.log('Three.js consumer OK: checkpoint parity, pure mapping, seek equality, seeded geometry.');
