/**
 * Particle geometry tests (v0.6.1 plan section 13.1): the deterministic
 * three-lobe field must be byte-stable, correctly layered, and free of any
 * Math.random influence.
 */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

import { createParticleGeometry, mulberry32 } from '../beatscope/web/particle-geometry.js';

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
  '7c428558cbd80a97ba84106dc54fb63ccae65ddd71c699696b00629fc185e28e',
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
  assert.ok(boundsA.min <= 0.72 && boundsA.max >= 1.0);
  assert.ok(Math.abs(boundsA.min - boundsC.min) < 0.05);
  assert.ok(Math.abs(boundsA.max - boundsC.max) < 0.05);
}

// Exact body/core/orbit ratios within one particle rounding unit.
{
  const counts = [0, 0, 0];
  for (let i = 0; i < a.count; i += 1) counts[a.meta[i * 4]] += 1;
  const roundingUnit = 1;
  assert.ok(Math.abs(counts[0] - Math.round(a.count * 0.72)) <= roundingUnit);
  assert.ok(Math.abs(counts[1] - Math.round(a.count * 0.18)) <= roundingUnit);
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
      if (layer === 'body') assert.ok(radius >= 0.72 - 0.035 - 1e-9 && radius <= 1.0 + 0.035 + 1e-9);
      if (layer === 'core') assert.ok(radius >= 0.18 - 1e-9 && radius <= 0.70 + 1e-9);
      if (layer === 'orbit') assert.ok(radius >= 1.10 - 1e-9 && radius <= 1.62 + 1e-9);
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
    return Math.round(total * 0.72) / 3;
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

console.log('Particle geometry OK: byte-stable, layered, three lobes, canonical hash pinned.');
