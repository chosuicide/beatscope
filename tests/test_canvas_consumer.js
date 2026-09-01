/**
 * Canvas reference consumer tests (v0.9 plan section 10).
 *
 * The example's geometry module (visual-field.js) must be pure, seeded,
 * and seek-safe, and the frame source it paints must reproduce the
 * frozen shared checkpoints bit for bit through the package's own
 * probe. These checks run in Node; interactive browser behaviour is
 * covered by the browser validation layer.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

import {
  runCheckpointSuite,
} from '../beatscope/runtime/consumer-probe.js';

const moduleNamespace = await import(
  pathToFileURL(fileURLToPath(new URL('../examples/shared/fixture.beatscope/visual-state.js', import.meta.url))).href
);
const checkpoints = JSON.parse(
  readFileSync(new URL('../examples/shared/checkpoints.json', import.meta.url), 'utf8'),
);
const declaration = JSON.parse(
  readFileSync(new URL('../examples/canvas-particles/beatscope-consumer.json', import.meta.url), 'utf8'),
);
const fieldModule = await import(
  pathToFileURL(fileURLToPath(new URL('../examples/canvas-particles/visual-field.js', import.meta.url))).href
);

const { createParticleField, particlePoints, particleLayout, framePalette, hash01 } = fieldModule;

// --- the consumer's frame source reproduces the frozen checkpoints -----------

{
  const suite = runCheckpointSuite(moduleNamespace, checkpoints, {});
  assert.equal(suite.ok, true, `checkpoint suite failed: ${JSON.stringify(suite.errors)}`);
}

// --- declaration sanity -------------------------------------------------------

{
  assert.equal(declaration.schema, 'beatscope-consumer-1');
  assert.equal(declaration.clock, 'audio.currentTime');
  assert.equal(declaration.debug_hook, '__BEATSCOPE_CONSUMER__');
  assert.equal(declaration.capabilities.playback, true);
  assert.equal(declaration.capabilities.seek, true);
  assert.equal(declaration.capabilities.reduced_motion, true);
}

// --- seeded field is deterministic and pure -----------------------------------

{
  const a = createParticleField();
  const b = createParticleField();
  assert.deepEqual(b, a, 'field must be a pure function of the grid');
  assert.equal(a.length, 56 * 30);
  assert.ok(a.every((p) => p.jitter >= 0 && p.jitter < 1));
  assert.equal(hash01(1, 7), hash01(1, 7), 'hash must be deterministic');
}

// --- every checkpoint renders finite points, and seek is exact ----------------

{
  const field = createParticleField();
  const size = { width: 960, height: 540 };
  const times = [...checkpoints.times, ...checkpoints.seek_sequence];
  for (const time of times) {
    const frame = moduleNamespace.getBeatScopeFrame(time);
    const points = particlePoints(field, frame, size, false);
    assert.equal(points.length, field.length);
    for (const point of points) {
      assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y), `non-finite point at t=${time}`);
      assert.ok(Number.isFinite(point.radius) && Number.isFinite(point.alpha), `non-finite style at t=${time}`);
      assert.ok(point.alpha >= 0 && point.alpha <= 1, `alpha out of range at t=${time}`);
    }
  }

  // Seek determinism: revisiting a media time reproduces the exact same
  // geometry — no accumulated state, no frame-count dependence.
  const [first, second] = checkpoints.seek_sequence.slice(0, 2);
  const before = particlePoints(field, moduleNamespace.getBeatScopeFrame(first), size, false);
  particlePoints(field, moduleNamespace.getBeatScopeFrame(second), size, false);
  const after = particlePoints(field, moduleNamespace.getBeatScopeFrame(first), size, false);
  assert.deepEqual(after, before, 'geometry drifted after an intervening seek');
}

// --- reduced motion lowers displacement without changing timing ---------------

{
  const field = createParticleField();
  const size = { width: 960, height: 540 };
  const time = 15.365075; // a boundary checkpoint with scene motion
  const fullFrame = moduleNamespace.getBeatScopeFrame(time);
  const reducedFrame = moduleNamespace.getBeatScopeFrame(time, { reducedMotion: true });
  assert.deepEqual(
    JSON.parse(JSON.stringify(fullFrame.timing)),
    JSON.parse(JSON.stringify(reducedFrame.timing)),
    'reduced motion must not change timing state',
  );

  const full = particlePoints(field, fullFrame, size, false);
  // Same frame, geometry-level flag only: the runtime's own reducedMotion
  // handling (timing equality above) is separate from displacement scaling.
  const reduced = particlePoints(field, fullFrame, size, true);
  assert.equal(reduced.length, full.length);

  // Every displacement term is linear in one motion factor (0.25 under
  // reduced motion), so displacement shrinks exactly per particle while
  // the motion-free layout stays put.
  const layout = particleLayout(field, fullFrame, size);
  for (let i = 0; i < full.length; i += 1) {
    const fullDx = full[i].x - layout[i].x;
    const fullDy = full[i].y - layout[i].y;
    const reducedDx = reduced[i].x - layout[i].x;
    const reducedDy = reduced[i].y - layout[i].y;
    assert.ok(
      Math.abs(reducedDx - fullDx * 0.25) < 1e-9 && Math.abs(reducedDy - fullDy * 0.25) < 1e-9,
      `displacement not scaled exactly at particle ${i}`,
    );
  }
  const magnitude = (points) =>
    points.reduce(
      (sum, point, i) =>
        sum + Math.hypot(point.x - layout[i].x, point.y - layout[i].y),
      0,
    );
  assert.ok(magnitude(reduced) < magnitude(full), 'reduced motion must lower displacement');
  assert.ok(magnitude(full) > 0, 'the frame should carry actual displacement');
}

// --- palettes follow family identity and stay bounded --------------------------

{
  const frame = moduleNamespace.getBeatScopeFrame(checkpoints.times[0]);
  const palette = framePalette(frame);
  assert.equal(palette.length, 3);
  assert.ok(palette.every((tone) => typeof tone === 'string'));
  const unknown = framePalette({ scene: { family: 'Z', composition: {} } });
  assert.ok(unknown.every((tone) => typeof tone === 'string'));
}

console.log('Canvas consumer OK: checkpoint parity, seeded purity, seek determinism, reduced motion, palettes.');
