/**
 * Seeded presentation noise (plan §4.6): a pure function of stable identity
 * plus an explicitly quantized presentation sample index. Never Math.random,
 * never wall-clock — the same identity and sample always yield the same value.
 */

/** FNV-1a over the identity string. */
export function hashSeed(key: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < key.length; i++) {
    hash ^= key.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Deterministic 32-bit mixer (mulberry32) over hash + sample. */
export function seededUnit(seed: number, sample: number): number {
  let a = (seed ^ Math.imul(sample | 0, 0x9e3779b9)) >>> 0;
  a = (a + 0x6d2b79f5) | 0;
  let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}

/**
 * Noise for one stable identity at a quantized sample index. `key` is
 * conventionally `project_id + scene_id + layer_id`; callers quantize their
 * sample explicitly so the value cannot drift with frame timing.
 */
export function seededNoise(key: string, sample: number): number {
  return seededUnit(hashSeed(key), sample);
}

/** Quantize a continuous value to a stable sample index. */
export function quantize(value: number, step: number): number {
  if (!(step > 0)) return 0;
  return Math.floor(value / step + 1e-9);
}
