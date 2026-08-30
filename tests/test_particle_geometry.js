/**
 * Particle geometry tests (v0.6.1 plan section 13.1): the deterministic
 * three-lobe field must be byte-stable, correctly layered, and free of any
 * Math.random influence.
 */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

import {
  createParticleGeometry,
  findRingCrossings,
  mulberry32,
  RING_DEFS,
  ringPointLocal,
  rotationXYZMatrix,
  RING_SLOTS,
} from '../beatscope/web/particle-geometry.js';

function geometryHash(geometry) {
  return createHash('sha256')
    .update(Buffer.from(geometry.positions.buffer, geometry.positions.byteOffset, geometry.positions.byteLength))
    .update(Buffer.from(geometry.seeds.buffer, geometry.seeds.byteOffset, geometry.seeds.byteLength))
    .update(Buffer.from(geometry.meta.buffer, geometry.meta.byteOffset, geometry.meta.byteLength))
    .digest('hex');
}

// Same seed/count => identical typed-array bytes (plan section 4.1).
const a = createParticleGeometry({ count: 2048, seed: 0x42534350 });
const b = createParticleGeometry({ count: 2048, seed: 0x42534350 });
assert.equal(geometryHash(a), geometryHash(b));
assert.deepEqual(a.positions, b.positions);
assert.deepEqual(a.seeds, b.seeds);
assert.deepEqual(a.meta, b.meta);

// Canonical baseline: change only with an explicit visual-baseline update.
assert.equal(
  geometryHash(a),
  '0f7491367f3c8bb215258af3bcea7848d36feffe86dad5fa68f8b986274b50af',
  'canonical geometry {count: 2048, seed: 0x42534350} changed',
);

// Different seed => different positions but same bounds.
const c = createParticleGeometry({ count: 2048, seed: 0x12345678 });
assert.notEqual(geometryHash(a), geometryHash(c));
{
  const bounds = (geometry) => {
    const result = { min: Infinity, max: -Infinity };
    for (let i = 0; i < geometry.count; i += 1) {
      const radius = geometry.meta[i * 4 + 2];
      result.min = Math.min(result.min, radius);
      result.max = Math.max(result.max, radius);
    }
    return result;
  };
  const boundsA = bounds(a);
  const boundsC = bounds(c);
  assert.ok(boundsA.min <= 0.09 && boundsA.max >= 1.0);
  assert.ok(Math.abs(boundsA.min - boundsC.min) < 0.05);
  assert.ok(Math.abs(boundsA.max - boundsC.max) < 0.05);
}

// Exact body/core/orbit ratios within one particle rounding unit.
{
  const counts = [0, 0, 0];
  for (let i = 0; i < a.count; i += 1) counts[a.meta[i * 4]] += 1;
  const roundingUnit = 1;
  assert.ok(Math.abs(counts[0] - Math.round(a.count * 0.89)) <= roundingUnit);
  assert.ok(Math.abs(counts[1] - Math.round(a.count * 0.07)) <= roundingUnit);
  assert.ok(Math.abs(counts[2] - (a.count - counts[0] - counts[1])) <= roundingUnit);
}

// All numbers finite across every array.
{
  for (const array of [a.positions, a.seeds, a.meta]) {
    for (const value of array) assert.ok(Number.isFinite(value));
  }
}

// Radius bounds per layer (plan section 4.2).
{
  const radii = { body: [], core: [], orbit: [] };
  for (let i = 0; i < a.count; i += 1) {
    const layer = a.meta[i * 4];
    const radius = a.meta[i * 4 + 2];
    if (layer === 0) radii.body.push(radius);
    else if (layer === 1) radii.core.push(radius);
    else radii.orbit.push(radius);
  }
  for (const [layer, list] of Object.entries(radii)) {
    for (const radius of list) {
      if (layer === 'body') assert.ok(radius >= 0.04 && radius <= 0.90);
      if (layer === 'core') assert.ok(radius >= 0.08 - 1e-9 && radius <= 0.33 + 1e-9);
      if (layer === 'orbit') assert.ok(radius >= 0.84 - 1e-9 && radius <= 1.08 + 1e-9);
    }
  }
}

// All three lobe ids populated within +/-5% of an even split.
{
  const lobes = [0, 0, 0];
  for (let i = 0; i < a.count; i += 1) {
    if (a.meta[i * 4] === 0) lobes[a.meta[i * 4 + 1]] += 1;
  }
  const even = radiiEvenShare(a.count);
  for (const count of lobes) {
    assert.ok(Math.abs(count - even) <= even * 0.05, `lobe count ${count} vs even ${even}`);
  }
  for (let lobe = 0; lobe < 3; lobe += 1) assert.ok(lobes[lobe] > 0);
  function radiiEvenShare(total) {
    return Math.round(total * 0.89) / 3;
  }
}

// The geometry object does not mutate after simulated render use: the bytes
// are identical after consumers read it, and the container is frozen.
{
  const before = geometryHash(a);
  assert.ok(Object.isFrozen(a));
  // Consumers only read positions/seeds/meta (uploads copy the bytes).
  const read = [a.positions[0], a.seeds[3], a.meta[a.count * 4 - 1]];
  assert.deepEqual([a.positions[0], a.seeds[3], a.meta[a.count * 4 - 1]], read);
  assert.equal(geometryHash(a), before);
}

// mulberry32 is deterministic and stays in [0, 1).
{
  const nextA = mulberry32(0x42534350);
  const nextB = mulberry32(0x42534350);
  for (let i = 0; i < 64; i += 1) {
    const value = nextA();
    assert.equal(value, nextB());
    assert.ok(value >= 0 && value < 1);
  }
}

// --- Orbit rings (layer 3): opt-in append; the body prefix stays identical --
{
  const withRingsA = createParticleGeometry({ count: 2048, seed: 0x42534350, rings: 3 });
  const withRingsB = createParticleGeometry({ count: 2048, seed: 0x42534350, rings: 3 });
  assert.equal(geometryHash(withRingsA), geometryHash(withRingsB));

  // Body layers 0-2 are byte-identical to the canonical rings-free field.
  for (const key of ['positions', 'seeds', 'meta']) {
    const bodyBytes = Buffer.from(a[key].buffer, a[key].byteOffset, a[key].byteLength);
    const prefixBytes = Buffer.from(withRingsA[key].buffer, withRingsA[key].byteOffset, bodyBytes.length);
    assert.ok(prefixBytes.equals(bodyBytes), `ring append mutated ${key}`);
  }
  assert.ok(withRingsA.count > a.count);

  // Layer 3 dots: meta = [3, ringId, theta, sizeBias] and each stored position
  // is exactly the ring's ellipse point at that theta.
  const ringCounts = [0, 0, 0];
  for (let i = a.count; i < withRingsA.count; i += 1) {
    assert.equal(withRingsA.meta[i * 4], 3);
    const ringId = withRingsA.meta[i * 4 + 1];
    assert.ok(ringId >= 0 && ringId <= 2);
    ringCounts[ringId] += 1;
    const theta = withRingsA.meta[i * 4 + 2];
    assert.ok(theta > 0 && theta < Math.PI * 2);
    const expected = ringPointLocal(RING_DEFS[ringId], theta);
    assert.ok(
      Math.abs(withRingsA.positions[i * 3] - expected[0]) < 1e-6
      && Math.abs(withRingsA.positions[i * 3 + 1] - expected[1]) < 1e-6
      && Math.abs(withRingsA.positions[i * 3 + 2] - expected[2]) < 1e-6,
      `ring dot ${i} off its ellipse`,
    );
  }
  // Dense seeded grain keeps roughly 96% of the slots to form three belts.
  const appended = withRingsA.count - a.count;
  assert.ok(appended >= 2000 && appended <= 2120, `unexpected ring grain count ${appended}`);
  for (const ringTotal of ringCounts) assert.ok(ringTotal > 650);

  // rings: 0 (and the default) never appends anything.
  assert.equal(createParticleGeometry({ count: 512, rings: 0 }).count, 512);
  assert.ok(withRingsA.count <= a.count + RING_DEFS.length * RING_SLOTS);
}

// findRingCrossings: exact vertical-axis crossings under instrument rotation.
{
  const yaw = 0.37; const pitch = -0.2; const roll = 0.05; const scale = 1.04;
  const crossings = findRingCrossings(RING_DEFS[0], yaw, pitch, roll, scale);
  assert.equal(crossings.length, 2);
  for (const p of crossings) {
    assert.ok(Math.abs(p[0]) < 1e-9, `crossing x should be 0, got ${p[0]}`);
    assert.ok(Number.isFinite(p[1]) && Number.isFinite(p[2]));
    const radius = Math.hypot(p[1], p[2]);
    assert.ok(radius > scale * 1.1 && radius < scale * 2.0, `crossing radius ${radius}`);
  }
  assert.ok(crossings[0][1] >= crossings[1][1], 'crossings sorted top first');
  // The two roots are exactly antipodal (theta and theta + pi).
  assert.ok(
    Math.abs(crossings[0][1] + crossings[1][1]) < 1e-9
    && Math.abs(crossings[0][2] + crossings[1][2]) < 1e-9,
  );

  // X(theta) is a pure c1*cos + c2*sin combination: exactly two sign changes.
  const m = rotationXYZMatrix(yaw, pitch, roll);
  const xAt = (theta) => {
    const p = ringPointLocal(RING_DEFS[0], theta);
    return scale * (m[0] * p[0] + m[1] * p[1] + m[2] * p[2]);
  };
  let signChanges = 0;
  const samples = 4096;
  let previous = xAt(0);
  for (let i = 1; i <= samples; i += 1) {
    const value = xAt((i / samples) * Math.PI * 2);
    if ((previous < 0) !== (value < 0)) signChanges += 1;
    previous = value;
  }
  assert.equal(signChanges, 2);
}

console.log('Particle geometry OK: byte-stable, layered, three lobes, canonical hash pinned.');
