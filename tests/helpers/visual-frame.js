/**
 * Shared helpers for visual-frame tests: every motion/state object the
 * stage produces must be finite and bounded so the renderers never draw
 * NaN geometry (v0.6.1 plan section 13.1 "test helpers for finite/bounded
 * visual frames").
 */

/**
 * Assert every own numeric property is finite. Properties named in
 * ``allowInfinite`` may be Infinity (e.g. the legacy impactAge sentinel).
 */
export function assertFiniteFrame(frame, allowInfinite = [], label = 'frame') {
  for (const [key, value] of Object.entries(frame)) {
    if (typeof value === 'number') {
      if (Number.isFinite(value)) continue;
      if (value === Infinity && allowInfinite.includes(key)) continue;
      throw new Error(`${label}.${key} must be finite, got ${value}`);
    }
    if (Array.isArray(value)) {
      value.forEach((item, index) => {
        if (typeof item === 'number' && !Number.isFinite(item)) {
          throw new Error(`${label}.${key}[${index}] must be finite, got ${item}`);
        }
      });
    }
    if (value && typeof value === 'object') {
      assertFiniteFrame(value, allowInfinite, `${label}.${key}`);
    }
  }
  return frame;
}

/** Assert every numeric property stays inside the given [min, max] keys. */
export function assertBounded(frame, bounds, label = 'frame') {
  for (const [key, [min, max]] of Object.entries(bounds)) {
    const value = frame[key];
    if (typeof value !== 'number') continue;
    if (!(value >= min && value <= max)) {
      throw new Error(`${label}.${key}=${value} outside [${min}, ${max}]`);
    }
  }
  return frame;
}

/** Deep-freeze a plain object and return it (purity checks). */
export function deepFreeze(value) {
  Object.freeze(value);
  for (const item of Object.values(value ?? {})) {
    if (item && typeof item === 'object') deepFreeze(item);
  }
  return value;
}
