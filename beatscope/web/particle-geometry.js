/**
 * Deterministic three-lobe particle geometry (v0.6.1 plan section 4).
 * DOM-free and Node-testable: the same {count, seed} always produces
 * byte-identical typed arrays, so snapshots and fallback comparisons stay
 * honest. No Math.random anywhere — the only entropy source is mulberry32.
 *
 * Distribution (plan section 4.2):
 *   72% surface/body particles on the three-lobed shell,
 *   18% soft inner-core particles (the warm light source),
 *   10% orbital/detached particles.
 */

const TAU = Math.PI * 2;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

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
 *   meta:      Float32Array(count * 4) — layer, lobe, shellRadius, pointSizeBias
 *
 * Layers: 0 = body, 1 = core, 2 = orbit. Lobes: 0..2 from wrapped longitude.
 */
export function createParticleGeometry({ count, seed = 0x42534350 }) {
  const total = Math.max(1, Math.floor(Number(count) || 0));
  const random = mulberry32(seed);

  const bodyCount = Math.round(total * 0.72);
  const coreCount = Math.round(total * 0.18);
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

    const longitude = Math.atan2(dirZ, dirX);
    const latitude = Math.asin(Math.max(-1, Math.min(1, dirY)));
    const lobeWave = 0.5 + 0.5 * Math.cos(3 * longitude + 1.35 * Math.sin(2 * latitude));
    const bodyR = 0.72 + 0.28 * lobeWave * lobeWave;
    const lobe = ((Math.round((longitude / TAU) * 3) % 3) + 3) % 3;

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
    let radius;
    let px = dirX;
    let py = dirY;
    let pz = dirZ;

    if (layer === 0) {
      // Body: three-lobed shell plus a seeded +/-0.035 thickness.
      radius = bodyR + (seedW * 2 - 1) * 0.035;
    } else if (layer === 1) {
      // Core: soft interior from 0.18 out to 0.70 body radii.
      radius = 0.18 + seedW * 0.52;
    } else {
      // Orbit: detached shell biased toward the equator without flattening
      // into a ring; latitude keeps a 0.35..1 spread of its natural value.
      radius = 1.10 + seedW * 0.52;
      const equatorBias = 0.35 + 0.65 * seedZ;
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
    meta[i * 4 + 3] = 0.75 + seedY * 0.5; // point size bias in [0.75, 1.25]
  }

  // Typed-array views cannot be Object.freeze'd; the container is frozen and
  // every consumer treats the arrays as immutable (tests pin byte identity).
  const geometry = { count: total, positions, seeds, meta };
  Object.freeze(geometry);
  return geometry;
}
