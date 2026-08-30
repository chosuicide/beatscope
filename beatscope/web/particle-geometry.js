/**
 * Deterministic three-lobe particle geometry (v0.6.1 plan section 4).
 * DOM-free and Node-testable: the same {count, seed} always produces
 * byte-identical typed arrays, so snapshots and fallback comparisons stay
 * honest. No Math.random anywhere — the only entropy source is mulberry32.
 *
 * Distribution (visual correction after v0.6.1 review):
 *   89% surface/body particles split across three actual petal volumes,
 *    7% compact inner-core particles,
 *    4% restrained orbital/detached particles.
 */

const TAU = Math.PI * 2;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const DEG = Math.PI / 180;

/**
 * Orbit-ring definitions (user-approved 3-ring spec). Each ring is a circle
 * of radius `a` squashed by `squash` on Y, rotated by `phi` in-plane, then
 * tilted by `incl` about X. Dots revolve along their own ellipse at `speed`
 * rad/s (signed); `color` is the ring's stable [r, g, b] tint.
 */
export const RING_DEFS = [
  { a: 1.92, squash: 0.62, phi: -18 * DEG, incl: 16 * DEG, speed: 0.16, color: [0.7765, 0.3137, 0.1961] },
  { a: 2.06, squash: 0.55, phi: 52 * DEG, incl: -14 * DEG, speed: -0.11, color: [0.3137, 0.3059, 0.2824] },
  { a: 1.72, squash: 0.7, phi: 8 * DEG, incl: 22 * DEG, speed: 0.13, color: [0.5059, 0.4902, 0.451] },
];
RING_DEFS.forEach((def) => { Object.freeze(def); Object.freeze(def.color); });
Object.freeze(RING_DEFS);

// Dense grain samples form a translucent orbit belt rather than a dotted
// necklace. A small seeded skip preserves texture without breaking the band.
export const RING_SLOTS = 720;
const RING_DUTY_SKIP = 0.04;

/** Point on a ring's ellipse at parameter theta, in body-local world units. */
export function ringPointLocal(def, theta) {
  const ex = def.a * Math.cos(theta);
  const ey = def.a * def.squash * Math.sin(theta);
  const cosPhi = Math.cos(def.phi);
  const sinPhi = Math.sin(def.phi);
  const x2 = ex * cosPhi - ey * sinPhi;
  const y2 = ex * sinPhi + ey * cosPhi;
  const cosI = Math.cos(def.incl);
  const sinI = Math.sin(def.incl);
  return [x2, y2 * cosI, y2 * sinI];
}

/**
 * JS mirror of the shader's rotationXYZ(yaw, pitch, roll), returned row-major
 * so that out = M · v with out[i] = Σ m[i * 3 + j] * v[j].
 */
export function rotationXYZMatrix(yaw, pitch, roll) {
  const cy = Math.cos(yaw); const sy = Math.sin(yaw);
  const cp = Math.cos(pitch); const sp = Math.sin(pitch);
  const cr = Math.cos(roll); const sr = Math.sin(roll);
  return [
    cy * cr + sy * sp * sr, -cy * sr + sy * sp * cr, sy * cp,
    cp * sr, cp * cr, -sp,
    -sy * cr + cy * sp * sr, sy * sr + cy * sp * cr, cy * cp,
  ];
}

/**
 * Where a ring's (static) dashed path crosses the screen-vertical axis once
 * the instrument rotation and per-beat scale are applied. X(theta) is a
 * linear combination c1·cos(theta) + c2·sin(theta), so the two roots are
 * exact — no sampling — and always antipodal. Returns the two world-space
 * points sorted top first.
 */
export function findRingCrossings(def, yaw, pitch, roll, scale = 1) {
  const m = rotationXYZMatrix(yaw, pitch, roll);
  const apply = (theta) => {
    const p = ringPointLocal(def, theta);
    return [
      scale * (m[0] * p[0] + m[1] * p[1] + m[2] * p[2]),
      scale * (m[3] * p[0] + m[4] * p[1] + m[5] * p[2]),
      scale * (m[6] * p[0] + m[7] * p[1] + m[8] * p[2]),
    ];
  };
  // c1 = X(0), c2 = X(pi/2) by linearity of the ellipse parameterisation.
  const c1 = apply(0)[0];
  const c2 = apply(Math.PI / 2)[0];
  const theta = Math.atan2(-c1, c2);
  const a = apply(theta);
  const b = apply(theta + Math.PI);
  return a[1] >= b[1] ? [a, b] : [b, a];
}

/**
 * Small deterministic integer PRNG (plan section 4.1). Returns floats in
 * [0, 1). Seeded per geometry, never re-seeded during a render loop.
 */
export function mulberry32(seed) {
  let state = seed >>> 0;
  return function next() {
    state = (state + 0x6D2B79F5) | 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Create the particle field geometry.
 *
 * Output (plan section 4.1):
 *   positions: Float32Array(count * 3) — base position in body-radius units
 *   seeds:     Float32Array(count * 4) — four stable [0,1) values each
 *   meta:      Float32Array(count * 4) — layer, lobe/ringId, shellRadius/theta, pointSizeBias
 *
 * Layers: 0 = body, 1 = core, 2 = orbit, 3 = orbit-ring dot. Lobes: 0..2
 * from wrapped longitude. With `rings` > 0 the matching RING_DEFS entries
 * append a dashed layer-3 ring AFTER the body budget; calls without `rings`
 * stay byte-identical to the canonical three-lobe field.
 */
export function createParticleGeometry({ count, seed = 0x42534350, rings = 0 }) {
  const total = Math.max(1, Math.floor(Number(count) || 0));
  const random = mulberry32(seed);

  const bodyCount = Math.round(total * 0.89);
  const coreCount = Math.round(total * 0.07);
  const orbitCount = Math.max(0, total - bodyCount - coreCount);

  const positions = new Float32Array(total * 3);
  const seeds = new Float32Array(total * 4);
  const meta = new Float32Array(total * 4);

  for (let i = 0; i < total; i += 1) {
    // Fibonacci sphere base direction (plan section 4.2).
    const y = 1 - 2 * (i + 0.5) / total;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = i * GOLDEN_ANGLE;
    const dirX = Math.cos(theta) * r;
    const dirY = y;
    const dirZ = Math.sin(theta) * r;

    // Four stable seeds per particle; radii derive from them so the output
    // is a pure function of (i, count, seed).
    const seedX = random();
    const seedY = random();
    const seedZ = random();
    const seedW = random();
    seeds[i * 4] = seedX;
    seeds[i * 4 + 1] = seedY;
    seeds[i * 4 + 2] = seedZ;
    seeds[i * 4 + 3] = seedW;

    const layer = i < bodyCount ? 0 : i < bodyCount + coreCount ? 1 : 2;
    const lobe = layer === 0 ? i % 3 : Math.floor(seedX * 3) % 3;
    let radius;
    let px = dirX;
    let py = dirY;
    let pz = dirZ;

    if (layer === 0) {
      // Three independent petal volumes. The previous cosine-modulated
      // sphere still read as a hollow globe; these radially arranged,
      // slightly curled ellipsoids leave visible clefts between lobes.
      const localIndex = Math.floor(i / 3);
      const localCount = Math.ceil(bodyCount / 3);
      const localY = 1 - 2 * (localIndex + 0.5) / localCount;
      const localRing = Math.sqrt(Math.max(0, 1 - localY * localY));
      const localTheta = localIndex * GOLDEN_ANGLE + lobe * 0.71;
      const localX = Math.cos(localTheta) * localRing;
      const localZ = Math.sin(localTheta) * localRing;
      const petalAngle = -Math.PI / 2 + lobe * TAU / 3;
      const shell = 0.82 + seedW * 0.18;
      // Each lobe is a tapered tube following a short spiral, not a radial
      // ellipsoid. Three copies form the comma-like internal folds seen in
      // the reference while retaining a compact, nearly circular outline.
      const curveAngle = petalAngle + localY * 0.72 + Math.sin(localY * Math.PI) * 0.08;
      const curveRadius = 0.05 + (localY + 1) * 0.27;
      const cosCurve = Math.cos(curveAngle);
      const sinCurve = Math.sin(curveAngle);
      const tubeWidth = (0.24 + 0.18 * (1 - localY * localY)) * shell;
      const tubeDepth = (0.25 + 0.16 * (1 - localY * localY)) * shell;
      px = cosCurve * curveRadius - sinCurve * localX * tubeWidth;
      py = sinCurve * curveRadius + cosCurve * localX * tubeWidth;
      pz = localZ * tubeDepth + (lobe - 1) * 0.014;
      px *= 1.42;
      py *= 1.42;
      pz *= 1.42;
      radius = Math.hypot(px, py, pz);
    } else if (layer === 1) {
      // A compact light source, not thousands of oversized warm discs.
      radius = 0.08 + seedW * 0.25;
    } else {
      // A close, sparse orbital shell. It supports the silhouette without
      // spilling through the charts below the instrument.
      radius = 0.84 + seedW * 0.24;
      const equatorBias = 0.55 + 0.45 * seedZ;
      py = dirY * equatorBias;
      const orbitR = Math.sqrt(Math.max(0, 1 - py * py));
      px = Math.cos(theta) * orbitR;
      pz = Math.sin(theta) * orbitR;
    }

    positions[i * 3] = px * radius;
    positions[i * 3 + 1] = py * radius;
    positions[i * 3 + 2] = pz * radius;
    meta[i * 4] = layer;
    meta[i * 4 + 1] = lobe;
    meta[i * 4 + 2] = radius;
    meta[i * 4 + 3] = 0.82 + seedY * 0.36; // tighter point-size variance
  }

  // Typed-array views cannot be Object.freeze'd; the container is frozen and
  // every consumer treats the arrays as immutable (tests pin byte identity).
  const geometry = { count: total, positions, seeds, meta };
  if (!(Number(rings) > 0)) {
    Object.freeze(geometry);
    return geometry;
  }

  // --- Orbit-belt grain (layer 3), appended after the body budget. ----------
  // Each grain stores its ellipse parameter in meta.z; the vertex shader
  // revolves it, spreads it across the belt width and applies the ring basis.
  const ringDefs = RING_DEFS.slice(0, Math.min(RING_DEFS.length, Math.floor(Number(rings))));
  const ringPositions = [];
  const ringSeeds = [];
  const ringMeta = [];
  let ringDots = 0;
  for (let r = 0; r < ringDefs.length; r += 1) {
    const def = ringDefs[r];
    for (let slot = 0; slot < RING_SLOTS; slot += 1) {
      if (random() < RING_DUTY_SKIP) continue; // seeded grain, never Math.random
      const theta = ((slot + 0.5) / RING_SLOTS) * TAU
        + (random() - 0.5) * (TAU / RING_SLOTS) * 0.55;
      const seedX = random();
      const seedY = random();
      const seedZ = random();
      const seedW = random();
      const point = ringPointLocal(def, theta);
      ringPositions.push(point[0], point[1], point[2]);
      ringSeeds.push(seedX, seedY, seedZ, seedW);
      ringMeta.push(3, r, theta, 0.82 + seedY * 0.36);
      ringDots += 1;
    }
  }

  const ringCount = total + ringDots;
  const positionsOut = new Float32Array(ringCount * 3);
  positionsOut.set(positions);
  positionsOut.set(ringPositions, total * 3);
  const seedsOut = new Float32Array(ringCount * 4);
  seedsOut.set(seeds);
  seedsOut.set(ringSeeds, total * 4);
  const metaOut = new Float32Array(ringCount * 4);
  metaOut.set(meta);
  metaOut.set(ringMeta, total * 4);
  const withRings = { count: ringCount, positions: positionsOut, seeds: seedsOut, meta: metaOut };
  Object.freeze(withRings);
  return withRings;
}
