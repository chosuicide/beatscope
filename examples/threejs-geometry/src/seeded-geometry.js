// Seeded geometry for the Three.js reference consumer. Positions are a
// pure function of vertex identity (deterministic hashes), never
// Math.random, so the same seed reproduces the same geometry everywhere.

export function hash01(a, b) {
  let h = Math.imul(a, 0x27d4eb2d) ^ Math.imul(b, 0x165667b1);
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

/**
 * Deterministic point cloud on a slightly perturbed sphere shell. The
 * same seed and count always produce the same positions; the frame
 * scales and rotates them, it never regenerates them.
 */
export function seededShell(count, seed, radius = 1) {
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {
    // Golden-angle spiral plus bounded hash jitter: reproducible and
    // evenly spread without any random state.
    const t = i / count;
    const elevation = 1 - 2 * t;
    const shellRadius = Math.sqrt(Math.max(0, 1 - elevation * elevation));
    const angle = i * 2.399963229728653 + seed;
    const jitter = (hash01(i, seed) - 0.5) * 0.18;
    const r = radius * (1 + jitter);
    positions[i * 3] = Math.cos(angle) * shellRadius * r;
    positions[i * 3 + 1] = elevation * r * 0.85;
    positions[i * 3 + 2] = Math.sin(angle) * shellRadius * r;
  }
  return positions;
}
