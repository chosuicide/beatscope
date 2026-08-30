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
 *
 * v0.6.1 adds `createMotionDirector` (plan section 6): the same tier
 * vocabulary expanded into deterministic anticipation/hold/impact/recoil/
 * aftershock phrase envelopes with tempo-aware beat-index cooldowns. It is
 * a pure function of audio time — seek-safe by construction.
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

// ---------------------------------------------------------------------------
// v0.6.1 motion director (plan section 6): deterministic tension and recovery
// envelopes computed from the analysed rhythm map alone. No clocks, no
// accumulated physics, no Math.random — at(time) is a pure function of audio
// time, so random-order queries equal sequential ones and seeks return the
// exact frame a continuous playback would have shown.
// ---------------------------------------------------------------------------

const clampBetween = (value, low, high) => Math.min(high, Math.max(low, Number(value)));
const timeOfOnset = (onset) => Number(onset.time ?? onset.raw_time) || 0;

function progress01(start, end, time) {
  if (end <= start) return time >= end ? 1 : 0;
  return clamp01((time - start) / (end - start));
}

function smoothstepValue(p) {
  const x = clamp01(p);
  return x * x * (3 - 2 * x);
}

function smoothstepBetween(edge0, edge1, value) {
  return smoothstepValue((value - edge0) / Math.max(1e-9, edge1 - edge0));
}

function easeInCubic(p) {
  const x = clamp01(p);
  return x * x * x;
}

// Forced exact endpoints: the generic 1 - 2^(-10x) curve saturates at
// 0.99902..., which would leave a ~1e-3 step at the impact/recoil boundary.
function easeOutExpo(p) {
  const x = clamp01(p);
  if (x >= 1) return 1;
  if (x <= 0) return 0;
  return 1 - Math.pow(2, -10 * x);
}

/**
 * Phase lengths for one event's phrase (plan section 6.4), derived from the
 * ADJACENT beat duration so variable-tempo tracks stretch and compress the
 * phrase with the local groove, clamped to human-readable ranges. Dense
 * passages stretch the aftershock slightly instead of repeating impacts.
 */
function phaseDurations(beatSpan, density = 0) {
  const span = Number(beatSpan) > 0 ? Number(beatSpan) : 0.5;
  const dense = smoothstepBetween(0.55, 0.90, density);
  return {
    anticipation: clampBetween(0.28 * span, 0.10, 0.22),
    hold: clampBetween(0.06 * span, 0.025, 0.045),
    impact: clampBetween(0.12 * span, 0.045, 0.085),
    recoil: clampBetween(0.42 * span, 0.16, 0.30),
    aftershock: clampBetween(1.15 * span, 0.38, 0.82) * (1 + 0.15 * dense),
  };
}

/** Named curve helpers, exported for boundary tests (plan section 6.4). */
export const envelopeMath = {
  clamp01,
  progress: progress01,
  smoothstep: smoothstepValue,
  smoothstepBetween,
  easeInCubic,
  easeOutExpo,
  phaseDurations,
};

// Adaptive band normalization (plan section 6.2): the trailing FIR smoothing
// replaces a mutable EMA with a pure function of audio time.
const SMOOTH_OFFSETS = [0, 0.025, 0.055, 0.095, 0.145];
const SMOOTH_WEIGHTS = [0.40, 0.25, 0.17, 0.11, 0.07];
// Ambient circulation reads a much slower low-band window (plan section 5.2).
const AMBIENT_OFFSETS = [0, 0.08, 0.18, 0.30, 0.46];
const DIRECTOR_BANDS = ['low', 'mid', 'high', 'all'];

function normalizeBand(value, p20, p95) {
  return clamp01((Math.sqrt(value) - p20) / Math.max(0.08, p95 - p20));
}

function smoothedBand(track, time, band, offsets = SMOOTH_OFFSETS) {
  let sum = 0;
  for (let i = 0; i < offsets.length; i += 1) {
    sum += track.energyAt(Math.max(0, time - offsets[i]), band) * SMOOTH_WEIGHTS[i];
  }
  return sum;
}

function projectDuration(track) {
  const map = track.map;
  const beatEnd = map.beats.length ? Number(map.beats[map.beats.length - 1].time) || 0 : 0;
  const onsetEnd = map.onsets.length ? timeOfOnset(map.onsets[map.onsets.length - 1]) : 0;
  return Math.max(map.duration, beatEnd, onsetEnd, 1);
}

function sampleBandStatistics(track, duration) {
  const stats = {};
  const step = 0.05; // 20 Hz sampling (plan section 6.1)
  for (const band of DIRECTOR_BANDS) {
    const samples = [];
    for (let t = 0; t <= duration + 1e-9; t += step) {
      samples.push(Math.sqrt(track.energyAt(Math.min(t, duration), band)));
    }
    const sorted = samples.sort((a, b) => a - b);
    stats[band] = {
      p20: quantile(sorted, 0.20),
      p50: quantile(sorted, 0.50),
      p85: quantile(sorted, 0.85),
      p95: quantile(sorted, 0.95),
    };
  }
  return stats;
}

const TIER_RANK = { pulse: 0, turbulence: 1, burst: 2, hero: 3 };
const TIER_SCALE = { pulse: 0.35, turbulence: 0.5, burst: 1, hero: 1 };
const MEMORY_WEIGHT = { pulse: 0.35, turbulence: 0.45, burst: 0.7, hero: 0.9 };

function beatSpanAt(beatTimes, beatIndex, fallback) {
  if (!beatTimes.length || !Number.isFinite(beatIndex)) return fallback;
  const index = Math.min(Math.max(0, Math.floor(beatIndex)), beatTimes.length - 1);
  const leftTime = beatTimes[index];
  const rightTime = index + 1 < beatTimes.length
    ? beatTimes[index + 1]
    : leftTime + (index > 0 ? leftTime - beatTimes[index - 1] : fallback);
  return Math.max(0.05, rightTime - leftTime);
}

function lobeBase(tier) {
  if (tier === 'hero') return [1.0, 0.72, 0.48];
  if (tier === 'burst') return [1.0, 0.62, 0];
  return [1.0, 0, 0];
}

function rotateWeights(base, id) {
  const shift = ((Math.round(id) % 3) + 3) % 3;
  return [base[shift], base[(shift + 1) % 3], base[(shift + 2) % 3]];
}

/** Unit direction on the sphere from the golden-angle sequence (§6.1 step 6). */
function goldenDirection(id) {
  const h = Math.abs(Math.round(id)) + 1;
  const y = 1 - 2 * ((h * 0.618033988749895) % 1);
  const radius = Math.sqrt(Math.max(0, 1 - y * y));
  const angle = h * 2.399963229728657;
  return [radius * Math.cos(angle), y, radius * Math.sin(angle)];
}

/**
 * Build the time-sorted event list: tier classification mirrors the
 * compatibility profile's quantile thresholds, but cooldowns compare REAL
 * beat indices (plan section 6.3) so variable tempo cannot fake proximity.
 */
function buildEvents(track, options) {
  const map = track.map;
  const source = map.onsets;
  const heroCooldownBeats = Math.max(1, Number(options.heroCooldownBeats) || 32);
  const burstCooldownBeats = Math.max(1, Number(options.burstCooldownBeats) || 2);
  const globalBeatLength = 60 / Math.max(1, map.bpm);
  const heroFallbackSeconds = globalBeatLength * 4 * (Number(options.heroCooldownBars) || 8);

  const strengths = source.map((item) => clamp01(item.strength)).sort((a, b) => a - b);
  const p78 = quantile(strengths, 0.78);
  const p92 = quantile(strengths, 0.92);
  const p98 = quantile(strengths, 0.98);

  const beatTimes = track.indexes.beatTimes;
  const ordered = source
    .map((onset, index) => ({ onset, index }))
    .sort((a, b) => (timeOfOnset(a.onset) - timeOfOnset(b.onset)) || (a.index - b.index));

  const events = [];
  let densityLeft = 0;
  let lastHeroBeat = -Infinity;
  let lastBurstBeat = -Infinity;
  let lastHeroTime = -Infinity;
  let lastBurstTime = -Infinity;

  for (const { onset, index } of ordered) {
    const time = timeOfOnset(onset);
    while (densityLeft < ordered.length && timeOfOnset(ordered[densityLeft].onset) < time - 1) densityLeft += 1;
    let densityRight = densityLeft;
    while (densityRight < ordered.length && timeOfOnset(ordered[densityRight].onset) <= time + 1) densityRight += 1;
    const density = clamp01((densityRight - densityLeft - 3) / 11);

    const position = track.positionAt(time);
    const beatIndex = Number(position.beatIndex);
    const hasBeatIndex = Number.isFinite(beatIndex);
    const strength = clamp01(onset.strength);
    const id = Number.isFinite(Number(onset.id)) ? Number(onset.id) : index;

    const computedBar = Math.floor(Math.max(0, time - map.origin) / (globalBeatLength * 4));
    const barIndex = Math.max(0, Number(onset.bar) > 0 ? Number(onset.bar) - 1 : computedBar);
    const section = map.sections[barIndex]?.group || map.sections[barIndex]?.label || null;
    const previousSection = map.sections[Math.max(0, barIndex - 1)]?.group
      || map.sections[Math.max(0, barIndex - 1)]?.label || null;
    const sectionChanged = barIndex > 0 && section && previousSection && section !== previousSection;

    const heroCandidate = (strength >= p98 && density < 0.86) || (sectionChanged && strength >= p92);
    const burstCandidate = strength >= p92 && density < 0.72;
    const heroReady = hasBeatIndex
      ? beatIndex - lastHeroBeat >= heroCooldownBeats
      : time - lastHeroTime >= heroFallbackSeconds;
    const burstReady = hasBeatIndex
      ? beatIndex - lastBurstBeat >= burstCooldownBeats
      : time - lastBurstTime >= globalBeatLength * burstCooldownBeats;

    let tier = 'pulse';
    if (heroCandidate && heroReady) {
      tier = 'hero';
      lastHeroBeat = beatIndex;
      lastHeroTime = time;
      lastBurstBeat = beatIndex;
      lastBurstTime = time;
    } else if (burstCandidate && burstReady) {
      tier = 'burst';
      lastBurstBeat = beatIndex;
      lastBurstTime = time;
    } else if (strength >= p78 || density >= 0.62) {
      tier = 'turbulence';
    }

    // §6.6: the density gate shrinks burst/hero displacement in dense
    // passages but never touches the subtle surface channels.
    const gate = 1 - 0.58 * smoothstepBetween(0.55, 0.90, density);
    const durations = phaseDurations(beatSpanAt(beatTimes, beatIndex, globalBeatLength), density);
    const phrased = tier === 'burst' || tier === 'hero';
    const amplitude = strength * TIER_SCALE[tier] * (phrased ? gate : 1);

    events.push({
      index,
      id,
      time,
      strength,
      density,
      tier,
      rank: TIER_RANK[tier],
      beatIndex,
      gate,
      phrased,
      amplitude,
      preRoll: durations.anticipation,
      holdDuration: durations.hold,
      impactDuration: durations.impact,
      recoilDuration: durations.recoil,
      aftershockDuration: durations.aftershock,
      lobeWeights: rotateWeights(lobeBase(tier), id),
      direction: goldenDirection(id),
    });
  }
  return events;
}

/**
 * One event's contribution to each phrase channel at `time`. Every window
 * boundary is C1-continuous by construction except the strike itself: the
 * impact channel is 0 before t0 and fires to its full amplitude at t0 —
 * that step IS the hit. `impact` carries its amplitude; anticipation/hold
 * are shapes in [0, 1] (the shader applies its own hero-aware scaling).
 */
function eventChannels(event, time) {
  const t0 = event.time;
  const strikeEnd = t0 + event.impactDuration;
  const channels = { anticipation: 0, hold: 0, impact: 0, recoil: 0, aftershock: 0, dominance: 0 };

  if (event.phrased) {
    // Release fades both the anticipation plateau and the hold down across
    // the impact window, so neither snaps to zero at the strike.
    const release = 1 - smoothstepValue(progress01(t0, strikeEnd, time));
    const holdStart = t0 - event.holdDuration;
    channels.anticipation = easeInCubic(progress01(t0 - event.preRoll, holdStart, time)) * release;
    channels.hold = smoothstepValue(progress01(holdStart, t0, time)) * release;
    if (time >= strikeEnd) {
      const recoilP = progress01(strikeEnd, strikeEnd + event.recoilDuration, time);
      channels.recoil = Math.sin(Math.PI * recoilP) * (1 - recoilP) * 0.25;
      const afterStart = strikeEnd + event.recoilDuration;
      const afterP = progress01(afterStart, afterStart + event.aftershockDuration, time);
      channels.aftershock = Math.exp(-4.2 * afterP) * Math.sin(Math.PI * 3.5 * afterP)
        * (1 - smoothstepBetween(0.85, 1, afterP));
    }
  } else if (time < t0 || time > strikeEnd) {
    return channels; // pulses and turbulence contribute only their strike
  }

  if (time >= t0) {
    // The exponential strike decays only to 2^-10 at p=1, so the last 15%
    // fades it the rest of the way — without the fade the window edge
    // would carry a ~1e-3 step (plan section 13.2 item 2).
    const strikeP = progress01(t0, strikeEnd, time);
    channels.impact = (1 - easeOutExpo(strikeP)) * (1 - smoothstepBetween(0.85, 1, strikeP));
  }
  channels.impact *= event.amplitude;
  channels.recoil *= event.amplitude;
  channels.aftershock *= event.amplitude;
  channels.dominance = channels.impact * 2 + channels.anticipation
    + channels.hold * 0.5 + channels.recoil + channels.aftershock * 0.5;
  return channels;
}

/**
 * Create the motion director for a runtime track (plan section 6.7).
 * `at(time, { reducedMotion })` returns a frozen frame; reduced motion
 * scales the motion channels (§10.1) and leaves every beat/phase fact
 * untouched.
 */
export function createMotionDirector(track, options = {}) {
  const statistics = sampleBandStatistics(track, projectDuration(track));
  const events = buildEvents(track, options);
  const defaultReducedMotion = Boolean(options.reducedMotion);

  function eventsInWindow(from, to) {
    let low = 0;
    let high = events.length - 1;
    let start = events.length;
    while (low <= high) {
      const middle = (low + high) >> 1;
      if (events[middle].time >= from) {
        start = middle;
        high = middle - 1;
      } else {
        low = middle + 1;
      }
    }
    const result = [];
    for (let i = start; i < events.length && events[i].time <= to; i += 1) result.push(events[i]);
    return result;
  }

  function at(time, overrides = null) {
    const t = Number(time) || 0;
    const reducedMotion = overrides ? Boolean(overrides.reducedMotion) : defaultReducedMotion;
    const position = track.positionAt(t);

    const bands = {};
    for (const band of DIRECTOR_BANDS) {
      const stat = statistics[band];
      bands[band] = normalizeBand(smoothedBand(track, t, band), stat.p20, stat.p95);
    }
    const ambient = normalizeBand(
      smoothedBand(track, t, 'low', AMBIENT_OFFSETS),
      statistics.low.p20,
      statistics.low.p95,
    );

    // Soft memory scans [t - 1.25s, t + anticipation headroom] (§6.5).
    const relevant = eventsInWindow(t - 1.25, t + 0.24);
    let anticipation = 0;
    let hold = 0;
    let impact = 0;
    let recoil = 0;
    let aftershock = 0;
    let primary = null;
    let primaryDominance = 0;
    let memorySum = 0;

    for (const event of relevant) {
      const channels = eventChannels(event, t);
      if (channels.anticipation > anticipation) anticipation = channels.anticipation;
      if (channels.hold > hold) hold = channels.hold;
      if (channels.impact > impact) impact = channels.impact;
      if (channels.recoil > recoil) recoil = channels.recoil;
      if (channels.aftershock > aftershock) aftershock = channels.aftershock;
      if (channels.dominance > primaryDominance) {
        primaryDominance = channels.dominance;
        primary = event;
      }
      const age = t - event.time;
      // Symmetric exponential weight: continuous across age=0, so an event
      // contributes the same surface memory a moment before and after it.
      const weight = Math.exp(-Math.abs(age) * 2.2);
      memorySum += event.strength * MEMORY_WEIGHT[event.tier] * weight;
    }

    let ambientValue = ambient;
    let anticipationValue = anticipation;
    let holdValue = hold;
    let impactValue = impact;
    let recoilValue = recoil;
    let aftershockValue = aftershock;
    if (reducedMotion) {
      ambientValue = ambient * 0.15;
      anticipationValue = anticipation * 0.25;
      holdValue = 0;
      impactValue = impact * 0.25;
      recoilValue = recoil * 0.25;
      aftershockValue = aftershock * 0.25;
    }

    const memory = 1 - Math.exp(-memorySum);
    const tension = clamp01(anticipationValue + 0.35 * memory);
    const shockSpan = primary
      ? primary.impactDuration + primary.recoilDuration + primary.aftershockDuration
      : 1;

    const frame = {
      time: t,
      low: bands.low,
      mid: bands.mid,
      high: bands.high,
      all: bands.all,
      tier: primary ? primary.tier : 'ambient',
      eventId: primary ? primary.id : -1,
      ambient: ambientValue,
      anticipation: anticipationValue,
      hold: holdValue,
      impact: impactValue,
      recoil: recoilValue,
      aftershock: aftershockValue,
      tension,
      memory,
      hero: primary && primary.tier === 'hero' ? 1 : 0,
      lobeWeights: primary ? primary.lobeWeights.slice() : [0.34, 0.33, 0.33],
      direction: primary ? primary.direction.slice() : [0, 1, 0],
      shockProgress: primary ? clamp01((t - primary.time) / Math.max(1e-6, shockSpan)) : 0,
      beatPhase: position.beatPhase,
      barPhase: position.barPhase,
    };
    Object.freeze(frame.lobeWeights);
    Object.freeze(frame.direction);
    return Object.freeze(frame);
  }

  return Object.freeze({ events, statistics, at });
}
