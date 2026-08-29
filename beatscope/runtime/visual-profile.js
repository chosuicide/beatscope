/**
 * Visual motion profile (plan section 41): derives the motion-tier budget
 * (pulse / turbulence / burst / hero) from a runtime track's onsets and
 * sections. Pure data work — no canvas, no audio, no clocks; callers
 * sample it with the same audio time they pass to `track.at()`.
 *
 * Options:
 *   onsetDecay         decay rate reserved for the signal-driven impulse
 *                      path (the impulse itself already carries this rate
 *                      inside track.at; the event pulse below uses its own
 *                      slower decay of 12, unchanged from the renderer).
 *   heroCooldownBars   minimum bars between hero events (default 8).
 *   burstCooldownBeats minimum beats between burst events (default 2).
 */

const clamp01 = (value) => Math.max(0, Math.min(1, Number(value) || 0));

function quantile(sorted, ratio) {
  if (!sorted.length) return 0;
  const position = clamp01(ratio) * (sorted.length - 1);
  const left = Math.floor(position);
  const right = Math.min(sorted.length - 1, left + 1);
  const amount = position - left;
  return sorted[left] + (sorted[right] - sorted[left]) * amount;
}

export function createVisualProfile(track, options = {}) {
  const {
    onsetDecay = 16,
    heroCooldownBars = 8,
    burstCooldownBeats = 2,
  } = options;

  const map = track.map;
  const source = map.onsets;
  const beatLength = 60 / Math.max(1, map.bpm);
  const origin = map.origin;
  const overview = map.sections;
  const heroCooldown = beatLength * heroCooldownBars;
  const burstCooldown = beatLength * burstCooldownBeats;

  const strengths = source.map((item) => clamp01(item.strength)).sort((a, b) => a - b);
  const p78 = quantile(strengths, .78);
  const p92 = quantile(strengths, .92);
  const p98 = quantile(strengths, .98);

  const events = [];
  let densityLeft = 0;
  let densityRight = 0;
  let lastBurst = -Infinity;
  let lastHero = -Infinity;

  for (let index = 0; index < source.length; index += 1) {
    const onset = source[index];
    const time = Number(onset.time ?? onset.raw_time) || 0;
    while (densityLeft < source.length && Number(source[densityLeft].time ?? source[densityLeft].raw_time) < time - 1) densityLeft += 1;
    while (densityRight < source.length && Number(source[densityRight].time ?? source[densityRight].raw_time) <= time + 1) densityRight += 1;
    const density = clamp01((densityRight - densityLeft - 3) / 11);
    const strength = clamp01(onset.strength);
    const computedBar = Math.floor(Math.max(0, time - origin) / (beatLength * 4));
    const barIndex = Math.max(0, Number(onset.bar) > 0 ? Number(onset.bar) - 1 : computedBar);
    const section = overview[barIndex]?.group || overview[barIndex]?.label || null;
    const previousSection = overview[Math.max(0, barIndex - 1)]?.group || overview[Math.max(0, barIndex - 1)]?.label || null;
    const sectionChanged = barIndex > 0 && section && previousSection && section !== previousSection;
    const heroCandidate = (strength >= p98 && density < .86)
      || (sectionChanged && strength >= p92);
    const burstCandidate = strength >= p92 && density < .72;
    let tier = 'pulse';
    if (heroCandidate && time - lastHero >= heroCooldown) {
      tier = 'hero';
      lastHero = time;
      lastBurst = time;
    } else if (burstCandidate && time - lastBurst >= burstCooldown) {
      tier = 'burst';
      lastBurst = time;
    } else if (strength >= p78 || density >= .62) {
      tier = 'turbulence';
    }
    events.push({ time, strength, density, tier });
  }

  function at(time, signal = null) {
    if (!events.length) return { pulse: 0, turbulence: 0, burst: 0, hero: 0, impactAge: Infinity };
    let low = 0;
    let high = events.length - 1;
    let index = -1;
    while (low <= high) {
      const middle = (low + high) >> 1;
      if (events[middle].time <= time) {
        index = middle;
        low = middle + 1;
      } else {
        high = middle - 1;
      }
    }
    if (index < 0) return { pulse: 0, turbulence: 0, burst: 0, hero: 0, impactAge: Infinity };

    let pulse = 0;
    let turbulence = 0;
    let burst = 0;
    let hero = 0;
    let impactAge = Infinity;
    for (let cursor = index; cursor >= 0; cursor -= 1) {
      const event = events[cursor];
      const age = Math.max(0, time - event.time);
      if (age > 1.15) break;
      pulse = Math.max(pulse, event.strength * Math.exp(-age * 12));
      turbulence = Math.max(turbulence, event.density * Math.exp(-age * 1.9));
      if (event.tier === 'turbulence') {
        turbulence = Math.max(turbulence, event.strength * (.35 + event.density * .65) * Math.exp(-age * 2.6));
      } else if (event.tier === 'burst') {
        const value = event.strength * Math.exp(-age * 8);
        if (value > burst) {
          burst = value;
          impactAge = age;
        }
      } else if (event.tier === 'hero') {
        const value = event.strength * Math.exp(-age * 4.5);
        if (value > hero) {
          hero = value;
          impactAge = age;
        }
      }
    }
    return {
      pulse: clamp01(pulse),
      turbulence: clamp01(turbulence),
      burst: clamp01(burst),
      hero: clamp01(hero),
      impactAge,
    };
  }

  return Object.freeze({ events, beatLength, at, onsetDecay });
}
