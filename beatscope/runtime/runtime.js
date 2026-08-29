/**
 * BeatScope Rhythm Runtime: pure time-fact queries over a rhythm map.
 *
 * Responsibilities (plan section 32): answer "what is true at time t" for
 * beats, onsets, energy, sections, and cues. It never touches audio
 * playback, canvas/DOM, requestAnimationFrame, randomness, files, or the
 * network. Callers pass the only clock: `track.at(audio.currentTime)`.
 *
 * The runtime accepts both stored formats (v4 `time`/`beat_in_bar` and
 * legacy `raw_time`/`beat`) through the same fallback reads the consumers
 * previously duplicated.
 */

const clamp = (value, min = 0, max = 1) => Math.max(min, Math.min(max, Number(value) || 0));
const lerp = (a, b, amount) => a + (b - a) * amount;

function timeOf(item) {
  return Number(item?.time ?? item?.raw_time) || 0;
}

/**
 * Normalize the two accepted input shapes without mutating the input:
 * stored projects (v4/v3: tempo.global_bpm, grid.origin, patterns.bars)
 * and the agent rhythm map (top-level bpm, origin, subdivision, sections).
 */
export function normalizeMap(rhythmMap) {
  const map = rhythmMap || {};
  const tempo = map.tempo || {};
  const grid = map.grid || {};
  const patterns = map.patterns || {};
  const sections = patterns.bars || patterns.segments || map.overview || map.sections || [];
  return {
    source: map,
    bpm: Number(tempo.global_bpm || tempo.bpm || map.bpm) || 120,
    origin: Number(grid.origin ?? map.origin ?? 0) || 0,
    defaultSubdivision: Number(grid.default_subdivision || grid.subdivision || map.subdivision) || 16,
    duration: Number(map.source?.duration ?? map.duration ?? 0) || 0,
    beats: Array.isArray(map.beats) ? map.beats : [],
    onsets: Array.isArray(map.onsets) ? map.onsets : [],
    energy: map.energy || {},
    patterns,
    sections: Array.isArray(sections) ? sections : [],
    cues: map.cues || {},
  };
}

/**
 * One-time indexes so per-frame queries never scan every event
 * (plan section 34).
 */
export function buildIndexes(map) {
  return {
    beatTimes: map.beats.map(timeOf),
    onsetTimes: map.onsets.map(timeOf),
    onsetIds: map.onsets.map((onset) => onset.id),
    accentIds: new Set(Array.isArray(map.cues?.accent) ? map.cues.accent.map((cue) => cue.onset) : []),
    barSpans: buildBarSpans(map),
    cueTimes: Object.fromEntries(
      Object.entries(map.cues || {})
        .filter(([, items]) => Array.isArray(items))
        .map(([name, items]) => [name, items.map((cue) => Number(cue.time) || 0)]),
    ),
  };
}

/** Generic binary search: last index whose time is <= the query (§35). */
export function previousIndex(sortedTimes, time) {
  let low = 0;
  let high = sortedTimes.length - 1;
  let answer = -1;

  while (low <= high) {
    const middle = (low + high) >> 1;
    if (sortedTimes[middle] <= time) {
      answer = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }

  return answer;
}

function metricsFor(map, options = {}) {
  const bpm = Number(options.bpm || map.bpm) || 120;
  const origin = Number(options.origin ?? map.origin) || 0;
  return { bpm, origin };
}

/**
 * Downbeat spans (plan section 37): for every stored bar, the interval
 * between its downbeat and the next one. The final bar extrapolates with
 * the previous bar's length.
 */
function buildBarSpans(map) {
  const spans = [];
  for (const beat of map.beats) {
    const inBar = Number(beat.beat_in_bar ?? beat.beat) || 0;
    const bar = Number(beat.bar) || 0;
    if (inBar === 1 && bar > 0) {
      spans.push({ bar, start: Number(beat.time) || 0, end: 0 });
    }
  }
  for (let i = 0; i + 1 < spans.length; i += 1) {
    spans[i].end = spans[i + 1].start;
  }
  if (spans.length > 1) {
    const last = spans[spans.length - 1];
    const previous = spans[spans.length - 2];
    const length = previous.end - previous.start;
    last.end = length > 0 ? last.start + length : last.start;
  }
  return spans;
}

/** Bar phase for ``bar`` at ``t`` from stored spans, or the synthetic grid. */
function barPhaseAt(map, indexes, t, bar, bpm, origin) {
  const spans = indexes.barSpans;
  if (spans.length) {
    const span = spans.find((item) => item.bar === bar);
    if (span && span.end > span.start) {
      return clamp((t - span.start) / (span.end - span.start));
    }
    const last = spans[spans.length - 1];
    if (bar > last.bar) {
      const length = Math.max(1e-6, last.end - last.start);
      return clamp((t - (last.end + (bar - last.bar - 1) * length)) / length);
    }
    if (bar <= spans[0].bar) return 0;
  }
  const barLength = 240 / Math.max(1, bpm);
  const phase = ((t - origin) / barLength) % 1;
  return phase < 0 ? phase + 1 : phase;
}

function lastInterval(times, index, bpm) {
  const span = index > 0 ? times[index] - times[index - 1] : 60 / Math.max(1, bpm);
  return Math.max(1e-6, span);
}

/**
 * Beat position from ADJACENT REAL BEATS (plan section 36): beatPhase
 * interpolates between the two beats surrounding the query instead of
 * deriving from a global-BPM phase, so variable-tempo grids stay honest.
 * Past the last stored beat the position continues with the last beat
 * interval and carries bar/beat counting forward; before the first beat
 * (or without beats) it falls back to the clamped global-BPM grid.
 */
export function positionAt(map, indexes, time, options = {}) {
  const t = Math.max(0, Number(time) || 0);
  const { bpm, origin } = metricsFor(map, options);
  const times = indexes.beatTimes;

  if (!map.beats.length || t < times[0]) {
    const beatLength = 60 / Math.max(1, bpm);
    const phase = Math.max(0, (t - origin) / beatLength);
    const beatIndex = Math.floor(phase);
    const stored = map.beats[beatIndex];
    const bar = Number(stored?.bar) || Math.floor(beatIndex / 4) + 1;
    return {
      time: t,
      beatIndex,
      bar,
      beat: Number(stored?.beat_in_bar ?? stored?.beat) || (beatIndex % 4) + 1,
      beatPhase: phase - Math.floor(phase),
      barPhase: barPhaseAt(map, indexes, t, bar, bpm, origin),
    };
  }

  const index = previousIndex(times, t);
  const leftTime = times[index];
  const rightTime = index + 1 < map.beats.length
    ? times[index + 1]
    : leftTime + lastInterval(times, index, bpm);
  let beatIndex = index;
  let fraction = (t - leftTime) / Math.max(1e-9, rightTime - leftTime);
  if (fraction >= 1) {
    beatIndex += Math.floor(fraction);
    fraction -= Math.floor(fraction);
  }

  const stored = map.beats[beatIndex];
  let bar;
  let beat;
  if (stored) {
    bar = Number(stored.bar) || 1;
    beat = Number(stored.beat_in_bar ?? stored.beat) || 1;
  } else {
    // Past the stored grid: carry the last real beat forward (the same
    // counting rule quantize uses for its post-grid case).
    const lastBeat = map.beats[map.beats.length - 1];
    const advanced = beatIndex - (map.beats.length - 1);
    const carried = (Number(lastBeat.beat_in_bar ?? lastBeat.beat) || 1) - 1 + advanced;
    bar = (Number(lastBeat.bar) || 1) + Math.floor(carried / 4);
    beat = (carried % 4) + 1;
  }

  return {
    time: t,
    beatIndex,
    bar,
    beat,
    beatPhase: fraction,
    barPhase: barPhaseAt(map, indexes, t, bar, bpm, origin),
  };
}

/** Raw (fact-level) energy with linear interpolation between frames (§38). */
export function energyAt(map, time, band = 'all') {
  const energy = map.energy || {};
  const bands = energy.bands?.[band];
  if (Array.isArray(bands) && bands.length) {
    const fps = Number(energy.fps) || 100;
    const position = clamp((Number(time) - (Number(energy.start) || 0)) * fps, 0, bands.length - 1);
    const left = Math.floor(position);
    const right = Math.min(bands.length - 1, left + 1);
    return clamp(lerp(Number(bands[left]) || 0, Number(bands[right]) || 0, position - left));
  }
  const frames = energy.frames;
  if (!Array.isArray(frames) || !frames.length) return 0;
  const start = Number(frames[0]?.time) || 0;
  const frameStep = frames.length > 1 ? Math.max(.0001, Number(frames[1].time) - start) : .01;
  const position = clamp((Number(time) - start) / frameStep, 0, frames.length - 1);
  const left = Math.floor(position);
  const right = Math.min(frames.length - 1, left + 1);
  return clamp(lerp(Number(frames[left]?.[band]) || 0, Number(frames[right]?.[band]) || 0, position - left));
}

/** Last onset at or before ``time`` with its age (§39). */
export function previousOnset(map, indexes, time) {
  const index = previousIndex(indexes.onsetTimes, Number(time) || 0);
  if (index < 0) return { item: null, age: Infinity };
  const item = map.onsets[index];
  return { item, age: Math.max(0, (Number(time) || 0) - timeOf(item)) };
}

/** Nearest onset regardless of direction with its absolute distance (D7). */
export function nearestOnset(map, indexes, time) {
  const t = Number(time) || 0;
  const times = indexes.onsetTimes;
  if (!times.length) return { item: null, distance: Infinity };
  const index = previousIndex(times, t);
  const candidates = [];
  if (index >= 0) candidates.push(index);
  if (index + 1 < times.length) candidates.push(index + 1);
  let best = null;
  let bestDistance = Infinity;
  for (const candidate of candidates) {
    const distance = Math.abs(times[candidate] - t);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = map.onsets[candidate];
    }
  }
  return { item: best, distance: bestDistance };
}

/** Decaying impulse over the previous onset (the web player's semantics). */
export function onsetImpulse(map, indexes, time, decay = 16, maxAge = 0.24) {
  const { item, age } = previousOnset(map, indexes, time);
  if (!item || age >= maxAge) return { item, age, value: 0 };
  return { item, age, value: clamp(item.strength) * Math.exp(-age * decay) };
}

export function isAccentOnset(map, indexes, onset) {
  if (!onset) return false;
  if (indexes.accentIds.size) return indexes.accentIds.has(onset.id);
  return Boolean(onset.accent);
}

function sectionForBar(map, bar) {
  return map.sections[Math.max(0, bar - 1)] || null;
}

/**
 * Full visual query with the web player's semantics: bar/beat/phase from
 * the adjacent-beat position core, onset as the decaying impulse over the
 * PREVIOUS onset (looked up with the unclamped time), energy raw (callers
 * apply their own compression), section from the extrapolated bar.
 */
export function stateAt(map, indexes, time, options = {}) {
  const rawTime = Number(time) || 0;
  const position = positionAt(map, indexes, rawTime, options);
  const impulse = onsetImpulse(map, indexes, rawTime);
  const accent = isAccentOnset(map, indexes, impulse.item) && impulse.value > 0
    ? { item: impulse.item, age: impulse.age, value: impulse.value }
    : null;
  return {
    time: rawTime,
    bar: position.bar,
    beat: position.beat,
    beatIndex: position.beatIndex,
    beatPhase: position.beatPhase,
    barPhase: position.barPhase,
    low: energyAt(map, rawTime, 'low'),
    mid: energyAt(map, rawTime, 'mid'),
    high: energyAt(map, rawTime, 'high'),
    all: energyAt(map, rawTime, 'all'),
    onset: { item: impulse.item, age: impulse.age, value: impulse.value },
    accent,
    section: sectionForBar(map, position.bar),
  };
}

/**
 * Quantize a raw timestamp against real beats with adjacent-beat
 * interpolation; falls back to the global-BPM grid without beats or when a
 * bpm adjustment forces the synthetic grid. Ported 1:1 from grid.js.
 */
export function quantize(map, indexes, rawTime, subdivision = map.defaultSubdivision, options = {}) {
  const t = Number(rawTime) || 0;
  const beats = map.beats;
  const partsPerBeat = subdivision / 4;
  const { bpm, origin } = metricsFor(map, options);
  const step = bpm > 0 ? 60 / bpm / (subdivision / 4) : 0;
  const beatTimes = indexes.beatTimes;

  if (!beats.length || options.bpm) {
    if (!step) {
      return { step: 0, bar: 0, beat: 0, stepInBar: 0, quantizedTime: 0, offsetMs: 0, preGrid: true };
    }
    const nearest = Math.round((t - origin) / step);
    const inGrid = nearest >= 0;
    const quantized = origin + nearest * step;
    return {
      step: nearest,
      bar: inGrid ? Math.floor(nearest / subdivision) + 1 : 0,
      beat: inGrid ? Math.floor((nearest % subdivision) / partsPerBeat) + 1 : 0,
      stepInBar: inGrid ? (nearest % subdivision) + 1 : 0,
      quantizedTime: Number(quantized.toFixed(4)),
      offsetMs: Number(((t - quantized) * 1000).toFixed(2)),
      preGrid: !inGrid,
    };
  }

  if (t < beatTimes[0]) {
    const avgBeatLen = beatTimes.length > 1 ? beatTimes[1] - beatTimes[0] : (60 / bpm);
    const stepLen = avgBeatLen / partsPerBeat;
    const stepsBefore = Math.round((beatTimes[0] - t) / stepLen);
    const quantized = beatTimes[0] - stepsBefore * stepLen;
    return {
      step: -stepsBefore,
      bar: 0,
      beat: 0,
      stepInBar: 0,
      quantizedTime: Number(quantized.toFixed(4)),
      offsetMs: Number(((t - quantized) * 1000).toFixed(2)),
      preGrid: true,
    };
  }

  if (t >= beatTimes[beatTimes.length - 1]) {
    const lastBeat = beats[beats.length - 1];
    const avgBeatLen = beatTimes.length > 1 ? beatTimes[beatTimes.length - 1] - beatTimes[beatTimes.length - 2] : (60 / bpm);
    const stepLen = avgBeatLen / partsPerBeat;
    const stepsAfter = Math.round((t - beatTimes[beatTimes.length - 1]) / stepLen);
    const quantized = beatTimes[beatTimes.length - 1] + stepsAfter * stepLen;

    const curBeatIdx = ((lastBeat.beat_in_bar ?? lastBeat.beat) - 1) + Math.floor(stepsAfter / partsPerBeat);
    const curBar = lastBeat.bar + Math.floor(curBeatIdx / 4);
    const curBeat = (curBeatIdx % 4) + 1;
    const curStepInBar = (curBeat - 1) * partsPerBeat + (stepsAfter % partsPerBeat) + 1;
    const absStep = (curBar - 1) * subdivision + curStepInBar - 1;

    return {
      step: absStep,
      bar: curBar,
      beat: curBeat,
      stepInBar: curStepInBar,
      quantizedTime: Number(quantized.toFixed(4)),
      offsetMs: Number(((t - quantized) * 1000).toFixed(2)),
      preGrid: false,
    };
  }

  let low = 0;
  let high = beatTimes.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (beatTimes[mid] <= t) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  const idx = Math.max(0, low - 1);
  const leftBeat = beats[idx];
  const rightBeat = beats[idx + 1] || leftBeat;
  const leftT = beatTimes[idx];
  const rightT = idx + 1 < beatTimes.length ? beatTimes[idx + 1] : leftT + (60 / bpm);
  const beatSpan = rightT - leftT;

  const candidates = [];
  for (let p = 0; p <= partsPerBeat; p += 1) {
    candidates.push(leftT + (beatSpan * p) / partsPerBeat);
  }

  let bestP = 0;
  let minDiff = Infinity;
  for (let p = 0; p <= partsPerBeat; p += 1) {
    const diff = Math.abs(candidates[p] - t);
    if (diff < minDiff) {
      minDiff = diff;
      bestP = p;
    }
  }

  const quantized = candidates[bestP];
  let targetBeat = leftBeat;
  let stepInBeat = bestP;

  if (bestP === partsPerBeat && idx + 1 < beats.length) {
    targetBeat = rightBeat;
    stepInBeat = 0;
  }

  const bar = targetBeat.bar || 0;
  const beatNum = (targetBeat.beat_in_bar ?? targetBeat.beat) || 1;
  const stepInBar = (beatNum - 1) * partsPerBeat + stepInBeat + 1;
  const absStep = (bar > 0 ? bar - 1 : 0) * subdivision + stepInBar - 1;

  return {
    step: absStep,
    bar,
    beat: beatNum,
    stepInBar,
    quantizedTime: Number(quantized.toFixed(4)),
    offsetMs: Number(((t - quantized) * 1000).toFixed(2)),
    preGrid: bar === 0,
  };
}

export function eventsBetween(map, indexes, start, end) {
  const from = Math.max(0, previousIndex(indexes.onsetTimes, Number(start) || 0) + 1);
  const to = previousIndex(indexes.onsetTimes, Number(end) || 0);
  return map.onsets.slice(from, Math.max(from, to + 1));
}

export function nextCue(map, indexes, time, type = 'accent') {
  const times = indexes.cueTimes[type] || [];
  const items = map.cues?.[type] || [];
  const index = previousIndex(times, Number(time) || 0) + 1;
  return index < items.length ? items[index] : null;
}

/**
 * Create a frozen track object. ``options`` carries the user adjustments
 * (``bpm``/``origin``) that force the synthetic grid for quantize queries.
 */
export function createTrack(rhythmMap, options = {}) {
  const map = normalizeMap(rhythmMap);
  const indexes = buildIndexes(map);

  return Object.freeze({
    map,
    indexes,
    at: (time) => stateAt(map, indexes, time, options),
    positionAt: (time) => positionAt(map, indexes, time, options),
    quantize: (time, subdivision = map.defaultSubdivision, overrides = null) =>
      quantize(map, indexes, time, subdivision, overrides ? { ...options, ...overrides } : options),
    energyAt: (time, band = 'all') => energyAt(map, time, band),
    sectionAt: (time) => sectionForBar(map, stateAt(map, indexes, time, options).bar),
    between: (start, end) => eventsBetween(map, indexes, start, end),
    nextCue: (time, type = 'accent') => nextCue(map, indexes, time, type),
    previousOnset: (time) => previousOnset(map, indexes, time),
    nearestOnset: (time) => nearestOnset(map, indexes, time),
  });
}

/**
 * Track-per-project cache: render loops call with the same project object
 * every frame, so the indexes are built once (plan section 44 note).
 */
const trackCache = new WeakMap();

export function trackForProject(project) {
  if (!trackCache.has(project)) {
    trackCache.set(project, createTrack(project));
  }
  return trackCache.get(project);
}
