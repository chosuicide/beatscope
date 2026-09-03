/**
 * Pure Director queries (v0.10 plan sections 8-12, 16).
 *
 * Every function here is a deterministic function of (project, runtime
 * track, input): no DOM, no audio element, no wall clock, no randomness.
 * The same query over the same project returns byte-identical JSON. All
 * seconds leave this module rounded to four decimals; all arrays are
 * hard-capped; nothing reads or mutates page state beyond the `page`
 * snapshot handed in by the caller.
 *
 * `page` is a plain snapshot object:
 *   { project, track, playbackTime, isPlaying, loop, loopSelection,
 *     subdivision, adjustments }
 */

import { previousIndex } from '../../runtime/runtime.js';
import { timeAtBar, metrics } from '../grid.js';
import { WebMcpError, round4, sanitizeLine } from './responses.js';

// ---------------------------------------------------------------------------
// Numeric helpers (plan section 16.1): small, local, no utility framework.
// ---------------------------------------------------------------------------

function finite(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function clampN(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function mean(values) {
  if (!values.length) return 0;
  let total = 0;
  for (const value of values) total += value;
  return total / values.length;
}

function maxOf(values) {
  let best = 0;
  for (const value of values) {
    if (value > best) best = value;
  }
  return best;
}

/** Percentage delta that degrades to an absolute delta near zero (plan 12.4). */
function safePercentDelta(a, b) {
  const base = Math.abs(a);
  if (base > 0.01) return Math.round(Math.abs(b - a) / base * 100);
  return null;
}

/** Overlap of two closed ranges relative to the shorter one, in [0, 1]. */
function overlapRatio(aStart, aEnd, bStart, bEnd) {
  const aLength = Math.max(0, aEnd - aStart);
  const bLength = Math.max(0, bEnd - bStart);
  if (aLength <= 0 || bLength <= 0) return 0;
  const intersection = Math.min(aEnd, bEnd) - Math.max(aStart, bStart);
  if (intersection <= 0) return 0;
  return intersection / Math.min(aLength, bLength);
}

// ---------------------------------------------------------------------------
// Shared project facts
// ---------------------------------------------------------------------------

function trackDuration(project) {
  return Math.max(0, finite(project?.source?.duration, 0));
}

function barsCount(project) {
  return Math.max(0, Math.floor(finite(project?.grid?.bars, 0)));
}

function beatsPerBar(project) {
  const meter = project?.meter || {};
  return clampN(Math.floor(finite(meter.beats_per_bar ?? meter.beatsPerBar, 4)), 1, 32);
}

function segmentsOf(project) {
  const segments = project?.patterns?.segments;
  return Array.isArray(segments) ? segments : [];
}

function boundariesOf(project) {
  const boundaries = project?.patterns?.boundaries;
  return Array.isArray(boundaries) ? boundaries : [];
}

function accentIdSet(project) {
  const accents = project?.cues?.accent;
  if (!Array.isArray(accents)) return new Set();
  return new Set(accents.map((cue) => cue?.onset).filter((id) => id !== undefined && id !== null));
}

function baseName(value) {
  const text = String(value ?? '');
  const cut = Math.max(text.lastIndexOf('/'), text.lastIndexOf('\\'));
  return cut >= 0 ? text.slice(cut + 1) : text;
}

function displayNameOf(project) {
  return sanitizeLine(project?.source?.display_name || baseName(project?.source?.file) || 'rhythm.json', 96);
}

/** True only when stored tempo segments actually disagree with the global BPM. */
function variableTempoOf(project) {
  const segments = project?.tempo?.segments;
  if (!Array.isArray(segments)) return false;
  const globalBpm = finite(project?.tempo?.global_bpm ?? project?.tempo?.bpm, 0);
  return segments.some((segment) => Math.abs(finite(segment?.bpm, 0) - globalBpm) > 0.01);
}

/**
 * Real time span for a 1-based inclusive bar range. The end uses the next
 * bar's downbeat; the final bar ends at the track duration (plan 3.2).
 */
export function barRange(page, startBar, endBar) {
  const project = page.project;
  const bars = barsCount(project);
  const start = Number(startBar);
  const end = Number(endBar);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start) {
    throw new WebMcpError('INVALID_RANGE', 'Bar ranges need 1 <= startBar <= endBar.');
  }
  if (bars < 1 || end > bars) {
    throw new WebMcpError('OUT_OF_RANGE', `The track has ${bars} bar(s); requested bar ${end}.`);
  }
  const startTime = finite(timeAtBar(start, project, page.adjustments), 0);
  const endTime = end >= bars
    ? trackDuration(project)
    : finite(timeAtBar(end + 1, project, page.adjustments), startTime);
  if (endTime <= startTime) {
    throw new WebMcpError('INVALID_RANGE', 'The bar range resolves to an empty time span.');
  }
  return { startBar: start, endBar: end, startTime, endTime };
}

/** Index of the last stored beat at or before ``anchorTime``, or -1. */
export function beatIndexAt(project, anchorTime) {
  const times = (project?.beats || []).map((beat) => finite(beat?.time ?? beat?.raw_time, 0));
  return previousIndex(times, finite(anchorTime, 0));
}

/**
 * Walk ``count`` real beats back from ``anchorTime`` (plan 14.3). Stored
 * beats win; only beat-less projects use the global-BPM grid, and the
 * result says which. The song start clamps to 0.
 */
export function previousBeatTime(project, anchorTime, count) {
  const beats = project?.beats || [];
  const back = clampN(Math.floor(finite(count, 0)), 0, 1024);
  if (!beats.length) {
    const bpm = finite(project?.tempo?.global_bpm ?? project?.tempo?.bpm, 120) || 120;
    const time = Math.max(0, finite(anchorTime, 0) - back * (60 / bpm));
    return { time, source: 'synthetic-grid' };
  }
  const index = beatIndexAt(project, anchorTime);
  if (index < 0) return { time: 0, source: 'stored-beats' };
  const target = Math.max(0, index - back);
  return { time: finite(beats[target]?.time ?? beats[target]?.raw_time, 0), source: 'stored-beats' };
}

/** Time of a stored (bar, beat) pair, or null when the grid does not hold it. */
export function storedBeatTime(project, bar, beat) {
  const beats = project?.beats || [];
  for (const item of beats) {
    const itemBar = Math.floor(finite(item?.bar, 0));
    const itemBeat = Math.floor(finite(item?.beat_in_bar ?? item?.beat, 0));
    if (itemBar === bar && itemBeat === beat) return finite(item.time ?? item.raw_time, 0);
  }
  return null;
}

/** Sampled mean/peak energy for one band over a time span (plan 16.2). */
export function sampleEnergy(page, startTime, endTime, band) {
  const duration = Math.max(0, endTime - startTime);
  if (duration <= 0) return { mean: 0, peak: 0 };
  const requested = Math.ceil(duration * 20);
  const count = clampN(requested, 2, 2048);
  const values = new Array(count);
  for (let i = 0; i < count; i += 1) {
    const t = startTime + ((i + 0.5) / count) * duration;
    values[i] = clampN(finite(page.track.energyAt(t, band), 0), 0, 1);
  }
  return { mean: mean(values), peak: maxOf(values) };
}

function onsetFacts(page, startTime, endTime) {
  const onsets = page.track.between(startTime, endTime);
  let peak = 0;
  for (const onset of onsets) {
    const strength = clampN(finite(onset?.strength, 0), 0, 1);
    if (strength > peak) peak = strength;
  }
  const seconds = Math.max(1e-9, endTime - startTime);
  return {
    count: onsets.length,
    density: onsets.length / seconds,
    peak,
  };
}

/** The band (low/mid/high) with the highest sampled mean; ties pick the lower band. */
function dominantBandOf(page, startTime, endTime) {
  let best = 'low';
  let bestMean = -1;
  for (const band of ['low', 'mid', 'high']) {
    const { mean: bandMean } = sampleEnergy(page, startTime, endTime, band);
    if (bandMean > bestMean) {
      bestMean = bandMean;
      best = band;
    }
  }
  return best;
}

function familiesIn(project, startTime, endTime) {
  const families = [];
  for (const segment of segmentsOf(project)) {
    const segmentStart = finite(segment?.start_time, 0);
    const segmentEnd = finite(segment?.end_time, 0);
    if (segmentStart < endTime && segmentEnd > startTime) {
      const family = String(segment?.family ?? '?');
      if (!families.includes(family)) families.push(family);
    }
  }
  return families;
}

// ---------------------------------------------------------------------------
// Tool 1: get_project_context (plan section 8)
// ---------------------------------------------------------------------------

function loopSummary(page) {
  if (!page.loopSelection || !page.project) {
    return { enabled: Boolean(page.loop), startTime: null, endTime: null };
  }
  const timing = metrics(page.project, page.subdivision, page.adjustments);
  const step = finite(timing.step, 0);
  if (step <= 0) return { enabled: Boolean(page.loop), startTime: null, endTime: null };
  const origin = finite(timing.origin, 0);
  return {
    enabled: Boolean(page.loop),
    startTime: round4(origin + page.loopSelection.start * step),
    endTime: round4(origin + (page.loopSelection.end + 1) * step),
  };
}

function structureSummary(page, atTime) {
  const segments = segmentsOf(page.project);
  if (!segments.length) {
    return { available: false, current: null, segments: [], total: 0, truncated: false };
  }
  const state = page.track.at(atTime);
  const structure = state.structure;
  let current = null;
  if (structure) {
    const owning = segments.find(
      (segment) => Math.abs(finite(segment?.start_time, 0) - finite(structure.startTime, 0)) < 1e-6,
    ) || null;
    current = {
      family: structure.family,
      label: structure.label || structure.family,
      variant: Math.floor(finite(structure.variant, 0)),
      startBar: Math.floor(finite(owning?.start_bar, 0)) || null,
      endBar: Math.floor(finite(owning?.end_bar, 0)) || null,
      phase: round4(structure.phase),
    };
  }
  const capped = segments.slice(0, 32).map((segment) => ({
    family: String(segment?.family ?? '?'),
    label: String(segment?.display_label || segment?.family || '?'),
    variant: Math.floor(finite(segment?.variant, 0)),
    startBar: Math.floor(finite(segment?.start_bar, 0)),
    endBar: Math.floor(finite(segment?.end_bar, 0)),
    startTime: round4(segment?.start_time),
    endTime: round4(segment?.end_time),
  }));
  return {
    available: true,
    current,
    segments: capped,
    total: segments.length,
    truncated: segments.length > capped.length,
  };
}

export function projectContext(page) {
  const project = page.project;
  if (!project) throw new WebMcpError('NO_TRACK');
  const time = Math.max(0, finite(page.playbackTime, 0));
  const signal = page.track.at(time);
  return {
    ok: true,
    track: {
      displayName: displayNameOf(project),
      duration: round4(trackDuration(project)),
      globalBpm: Number(finite(project?.tempo?.global_bpm ?? project?.tempo?.bpm, 0).toFixed(2)),
      bars: barsCount(project),
      timeSignature: [beatsPerBar(project), Math.floor(finite(project?.meter?.beat_unit, 4)) || 4],
      variableTempo: variableTempoOf(project),
    },
    playback: {
      time: round4(time),
      playing: Boolean(page.isPlaying),
      bar: Math.floor(finite(signal.bar, 0)),
      beat: Math.floor(finite(signal.beat, 0)),
      loop: loopSummary(page),
    },
    structure: structureSummary(page, time),
    capabilities: [
      'get_state_at_time',
      'get_events',
      'find_visual_moments',
      'compare_ranges',
      'focus_range',
      'control_playback',
      'set_loop_range',
    ],
  };
}

// ---------------------------------------------------------------------------
// Tool 2: get_state_at_time (plan section 9)
// ---------------------------------------------------------------------------

export function stateAtTime(page, input = {}, sceneAt = null) {
  if (!page.project) throw new WebMcpError('NO_TRACK');
  const duration = trackDuration(page.project);
  const explicit = input.time !== undefined && input.time !== null;
  const requested = explicit ? finite(input.time, 0) : finite(page.playbackTime, 0);
  if (explicit && !Number.isFinite(Number(input.time))) {
    throw new WebMcpError('INVALID_RANGE', 'time must be a finite number of seconds.');
  }
  const time = clampN(requested, 0, duration);
  const includeScene = input.includeScene !== false;
  const signal = page.track.at(time);

  const onsetPresent = signal.onset.item && signal.onset.value > 0;
  const onset = onsetPresent
    ? {
        impulse: round4(signal.onset.value),
        age: round4(signal.onset.age),
        strength: round4(signal.onset.item?.strength),
        accent: Boolean(signal.accent),
      }
    : { impulse: 0, age: null, strength: null, accent: null };

  const structure = signal.structure
    ? {
        family: signal.structure.family,
        label: signal.structure.label || signal.structure.family,
        variant: Math.floor(finite(signal.structure.variant, 0)),
        phase: round4(signal.structure.phase),
        secondsToBoundary: round4(signal.structure.secondsToBoundary),
      }
    : null;

  let scene = { available: false };
  if (includeScene && typeof sceneAt === 'function') {
    const frame = sceneAt(time);
    if (frame && frame.scene) {
      scene = {
        available: true,
        family: frame.scene.family ?? null,
        motif: frame.scene.motif ?? null,
        phase: round4(frame.scene.phase),
        transitionStage: frame.transition?.stage ?? null,
      };
    }
  }

  const result = {
    ok: true,
    time: round4(time),
    position: {
      bar: Math.floor(finite(signal.bar, 0)),
      beat: Math.floor(finite(signal.beat, 0)),
      beatPhase: round4(signal.beatPhase),
      barPhase: round4(signal.barPhase),
    },
    energy: {
      all: round4(signal.all),
      low: round4(signal.low),
      mid: round4(signal.mid),
      high: round4(signal.high),
    },
    onset,
    structure,
    scene,
  };
  if (!explicit) result.playing = Boolean(page.isPlaying);
  return result;
}

// ---------------------------------------------------------------------------
// Tool 3: get_events (plan section 10)
// ---------------------------------------------------------------------------

const EVENT_INCLUDES = Object.freeze(['beats', 'onsets', 'segments', 'boundaries', 'cues']);
const KIND_ORDER = Object.freeze({ segment: 0, boundary: 1, beat: 2, onset: 3, cue: 4 });
const MAX_EVENT_SPAN_BARS = 64;
const MAX_EVENT_SPAN_SECONDS = 180;

function resolveEventWindow(page, input) {
  const project = page.project;
  const hasTime = input.startTime !== undefined || input.endTime !== undefined;
  const hasBars = input.startBar !== undefined || input.endBar !== undefined;
  if (hasTime && hasBars) {
    throw new WebMcpError('INVALID_RANGE', 'Give a time range or a bar range, never both.');
  }
  if (hasTime) {
    if (input.startTime === undefined || input.endTime === undefined) {
      throw new WebMcpError('INVALID_RANGE', 'A time range needs both startTime and endTime.');
    }
    const startTime = finite(input.startTime, NaN);
    const endTime = finite(input.endTime, NaN);
    if (!Number.isFinite(startTime) || !Number.isFinite(endTime) || startTime < 0 || endTime <= startTime) {
      throw new WebMcpError('INVALID_RANGE', 'Time ranges need 0 <= startTime < endTime.');
    }
    const duration = trackDuration(project);
    const clampedEnd = Math.min(endTime, duration);
    if (clampedEnd - startTime > MAX_EVENT_SPAN_SECONDS) {
      throw new WebMcpError('INVALID_RANGE', `Time windows are capped at ${MAX_EVENT_SPAN_SECONDS} seconds.`);
    }
    return { startTime, endTime: clampedEnd, startBar: null, endBar: null };
  }
  if (hasBars) {
    if (input.startBar === undefined || input.endBar === undefined) {
      throw new WebMcpError('INVALID_RANGE', 'A bar range needs both startBar and endBar.');
    }
    if (input.endBar - input.startBar + 1 > MAX_EVENT_SPAN_BARS) {
      throw new WebMcpError('INVALID_RANGE', `Bar windows are capped at ${MAX_EVENT_SPAN_BARS} bars.`);
    }
    const range = barRange(page, input.startBar, input.endBar);
    return {
      startTime: range.startTime,
      endTime: range.endTime,
      startBar: range.startBar,
      endBar: range.endBar,
    };
  }
  throw new WebMcpError('INVALID_RANGE', 'Give a time range (startTime/endTime) or a bar range (startBar/endBar).');
}

export function eventsWindow(page, input = {}) {
  if (!page.project) throw new WebMcpError('NO_TRACK');
  const project = page.project;

  let includes;
  if (input.include === undefined || input.include === null) {
    includes = ['beats', 'onsets', 'boundaries'];
  } else if (!Array.isArray(input.include)) {
    throw new WebMcpError('INVALID_RANGE', 'include must be an array of event kinds.');
  } else {
    includes = input.include;
  }
  if (includes.length < 1 || includes.length > 5 || new Set(includes).size !== includes.length
    || includes.some((name) => !EVENT_INCLUDES.includes(name))) {
    throw new WebMcpError('INVALID_RANGE', 'include must be 1-5 unique event kinds.');
  }
  const limit = clampN(Math.floor(finite(input.limit, 100)), 1, 200);
  const window = resolveEventWindow(page, input);
  const { startTime, endTime } = window;
  const accents = accentIdSet(project);
  const events = [];

  if (includes.includes('beats')) {
    const beats = project.beats || [];
    const times = beats.map((beat) => finite(beat?.time ?? beat?.raw_time, 0));
    const from = previousIndex(times, startTime) + 1;
    for (let i = from; i < beats.length && times[i] <= endTime; i += 1) {
      const beat = beats[i];
      events.push({
        kind: 'beat',
        time: round4(times[i]),
        bar: Math.floor(finite(beat?.bar, 0)),
        beat: Math.floor(finite(beat?.beat_in_bar ?? beat?.beat, 0)),
      });
    }
  }

  if (includes.includes('onsets')) {
    for (const onset of page.track.between(startTime, endTime)) {
      events.push({
        kind: 'onset',
        time: round4(finite(onset?.time ?? onset?.raw_time, 0)),
        strength: round4(clampN(finite(onset?.strength, 0), 0, 1)),
        accent: Boolean(onset?.accent) || accents.has(onset?.id),
      });
    }
  }

  if (includes.includes('segments')) {
    for (const segment of segmentsOf(project)) {
      const segmentStart = finite(segment?.start_time, 0);
      const segmentEnd = finite(segment?.end_time, 0);
      if (segmentStart < endTime && segmentEnd > startTime) {
        events.push({
          kind: 'segment',
          family: String(segment?.family ?? '?'),
          label: String(segment?.display_label || segment?.family || '?'),
          variant: Math.floor(finite(segment?.variant, 0)),
          startBar: Math.floor(finite(segment?.start_bar, 0)),
          endBar: Math.floor(finite(segment?.end_bar, 0)),
          startTime: round4(segmentStart),
          endTime: round4(segmentEnd),
        });
      }
    }
  }

  if (includes.includes('boundaries')) {
    for (const boundary of boundariesOf(project)) {
      const time = finite(boundary?.time, 0);
      if (time > startTime && time <= endTime) {
        events.push({
          kind: 'boundary',
          time: round4(time),
          bar: Math.floor(finite(boundary?.bar, 0)),
          novelty: boundary?.novelty === undefined || boundary?.novelty === null
            ? null
            : round4(clampN(finite(boundary.novelty, 0), 0, 1)),
        });
      }
    }
  }

  if (includes.includes('cues')) {
    for (const cue of project.cues?.accent || []) {
      const time = finite(cue?.time, NaN);
      if (Number.isFinite(time) && time > startTime && time <= endTime) {
        events.push({
          kind: 'cue',
          cue: 'accent',
          time: round4(time),
          onset: cue?.onset === undefined ? null : cue.onset,
        });
      }
    }
  }

  events.sort((a, b) => {
    if (a.time !== b.time) return a.time - b.time;
    return KIND_ORDER[a.kind] - KIND_ORDER[b.kind];
  });

  return {
    ok: true,
    range: {
      startTime: round4(window.startTime),
      endTime: round4(window.endTime),
      startBar: window.startBar,
      endBar: window.endBar,
    },
    events: events.slice(0, limit),
    total: events.length,
    truncated: events.length > limit,
  };
}

// ---------------------------------------------------------------------------
// Tool 4: find_visual_moments (plan section 11)
// ---------------------------------------------------------------------------

const MOMENT_KINDS = Object.freeze([
  'structural_transition',
  'strong_transient',
  'energy_lift',
  'energy_drop',
  'quiet_contrast',
]);
const MOMENT_REASONS = Object.freeze({
  structural_transition: 'Strong structural boundary with a large adjacent energy change.',
  strong_transient: 'Highest measured transient strength.',
  energy_lift: 'Energy rises across this range.',
  energy_drop: 'Energy falls across this range.',
  quiet_contrast: 'Quietest measured window in the track.',
});
const MAX_CANDIDATES = 8;

function windowBarsFor(startBar, windowBars, bars) {
  const start = clampN(startBar, 1, Math.max(1, bars));
  const end = Math.min(bars, start + windowBars - 1);
  return { startBar: start, endBar: Math.max(start, end) };
}

function candidateFacts(page, window) {
  const onsets = onsetFacts(page, window.startTime, window.endTime);
  return {
    onsetDensity: round4(onsets.density),
    peakStrength: round4(onsets.peak),
    dominantBand: dominantBandOf(page, window.startTime, window.endTime),
  };
}

function energyAroundBoundary(page, window) {
  const beforeStartBar = Math.max(1, window.startBar - (window.endBar - window.startBar + 1));
  const before = beforeStartBar < window.startBar
    ? barRange(page, beforeStartBar, window.startBar - 1)
    : null;
  const beforeSpan = before
    ? { startTime: before.startTime, endTime: before.endTime }
    : { startTime: 0, endTime: window.startTime };
  const beforeMean = sampleEnergy(page, beforeSpan.startTime, beforeSpan.endTime, 'all').mean;
  const afterMean = sampleEnergy(page, window.startTime, window.endTime, 'all').mean;
  return { energyBefore: round4(beforeMean), energyAfter: round4(afterMean) };
}

function structuralTransitionCandidates(page, windowBars) {
  const project = page.project;
  const bars = barsCount(project);
  const candidates = [];
  for (const boundary of boundariesOf(project)) {
    const boundaryBar = Math.floor(finite(boundary?.bar, 1));
    if (boundaryBar < 1) continue;
    const span = windowBarsFor(boundaryBar, windowBars, bars);
    if (span.endBar < span.startBar) continue;
    const range = barRange(page, span.startBar, span.endBar);
    const novelty = boundary?.novelty === undefined || boundary?.novelty === null
      ? null
      : clampN(finite(boundary.novelty, 0), 0, 1);
    const adjacent = energyAroundBoundary(page, { ...range, ...span });
    const score = novelty !== null ? novelty : adjacent.energyAfter - adjacent.energyBefore;
    const facts = candidateFacts(page, range);
    candidates.push({
      startBar: span.startBar,
      endBar: span.endBar,
      startTime: range.startTime,
      endTime: range.endTime,
      anchorTime: finite(boundary?.time, range.startTime),
      score,
      facts: {
        boundaryNovelty: novelty,
        energyBefore: adjacent.energyBefore,
        energyAfter: adjacent.energyAfter,
        onsetDensity: facts.onsetDensity,
        peakStrength: facts.peakStrength,
        dominantBand: facts.dominantBand,
      },
    });
  }
  return candidates;
}

function strongTransientCandidates(page, windowBars) {
  const project = page.project;
  const bars = barsCount(project);
  const duration = trackDuration(project);
  const seenBars = new Set();
  const sorted = (project.onsets || [])
    .map((onset) => ({
      onset,
      strength: clampN(finite(onset?.strength, 0), 0, 1),
      accent: Boolean(onset?.accent),
      time: finite(onset?.time ?? onset?.raw_time, 0),
    }))
    .sort((a, b) => {
      if (b.strength !== a.strength) return b.strength - a.strength;
      if (b.accent !== a.accent) return b.accent ? -1 : 1;
      return a.time - b.time;
    });
  const candidates = [];
  for (const entry of sorted) {
    const bar = Math.floor(finite(entry.onset?.bar, 0));
    if (bar < 1 || seenBars.has(bar)) continue;
    seenBars.add(bar);
    const start = Math.floor((bar - 1) / windowBars) * windowBars + 1;
    const span = windowBarsFor(start, windowBars, bars);
    if (span.endBar < span.startBar) continue;
    const range = barRange(page, span.startBar, span.endBar);
    const facts = candidateFacts(page, range);
    candidates.push({
      startBar: span.startBar,
      endBar: span.endBar,
      startTime: range.startTime,
      endTime: range.endTime,
      anchorTime: Math.min(entry.time, duration),
      score: entry.strength,
      facts: {
        boundaryNovelty: null,
        energyBefore: null,
        energyAfter: null,
        onsetDensity: facts.onsetDensity,
        peakStrength: Math.max(entry.strength, facts.peakStrength),
        dominantBand: facts.dominantBand,
      },
    });
  }
  return candidates;
}

function energySlopeCandidates(page, windowBars) {
  const bars = barsCount(page.project);
  const candidates = [];
  for (let bar = 2; bar <= bars; bar += 1) {
    const beforeRange = barRange(page, bar - 1, bar - 1);
    const afterRange = barRange(page, bar, bar);
    const beforeMean = sampleEnergy(page, beforeRange.startTime, beforeRange.endTime, page.band).mean;
    const afterMean = sampleEnergy(page, afterRange.startTime, afterRange.endTime, page.band).mean;
    const delta = afterMean - beforeMean;
    if (delta <= 0) continue;
    const span = windowBarsFor(bar, windowBars, bars);
    const range = barRange(page, span.startBar, span.endBar);
    const facts = candidateFacts(page, range);
    candidates.push({
      startBar: span.startBar,
      endBar: span.endBar,
      startTime: range.startTime,
      endTime: range.endTime,
      anchorTime: range.startTime,
      score: delta,
      facts: {
        boundaryNovelty: null,
        energyBefore: round4(beforeMean),
        energyAfter: round4(afterMean),
        onsetDensity: facts.onsetDensity,
        peakStrength: facts.peakStrength,
        dominantBand: facts.dominantBand,
      },
    });
  }
  return candidates;
}

function energyDropCandidates(page, windowBars) {
  const bars = barsCount(page.project);
  const candidates = [];
  for (let bar = 2; bar <= bars; bar += 1) {
    const beforeRange = barRange(page, bar - 1, bar - 1);
    const afterRange = barRange(page, bar, bar);
    const beforeMean = sampleEnergy(page, beforeRange.startTime, beforeRange.endTime, page.band).mean;
    const afterMean = sampleEnergy(page, afterRange.startTime, afterRange.endTime, page.band).mean;
    const delta = beforeMean - afterMean;
    if (delta <= 0) continue;
    const span = windowBarsFor(bar, windowBars, bars);
    const range = barRange(page, span.startBar, span.endBar);
    const facts = candidateFacts(page, range);
    candidates.push({
      startBar: span.startBar,
      endBar: span.endBar,
      startTime: range.startTime,
      endTime: range.endTime,
      anchorTime: range.startTime,
      score: delta,
      facts: {
        boundaryNovelty: null,
        energyBefore: round4(beforeMean),
        energyAfter: round4(afterMean),
        onsetDensity: facts.onsetDensity,
        peakStrength: facts.peakStrength,
        dominantBand: facts.dominantBand,
      },
    });
  }
  return candidates;
}

function quietContrastCandidates(page, windowBars) {
  const project = page.project;
  const bars = barsCount(project);
  const boundaryByBar = new Map();
  for (const boundary of boundariesOf(project)) {
    const bar = Math.floor(finite(boundary?.bar, 0));
    const novelty = clampN(finite(boundary?.novelty, 0), 0, 1);
    if (bar >= 1 && (!boundaryByBar.has(bar) || novelty > boundaryByBar.get(bar))) {
      boundaryByBar.set(bar, novelty);
    }
  }
  const candidates = [];
  for (let start = 1; start + windowBars - 1 <= bars; start += windowBars) {
    const span = windowBarsFor(start, windowBars, bars);
    const range = barRange(page, span.startBar, span.endBar);
    const sampled = sampleEnergy(page, range.startTime, range.endTime, page.band);
    const facts = candidateFacts(page, range);
    const noveltyBonus = boundaryByBar.get(span.startBar) || 0;
    candidates.push({
      startBar: span.startBar,
      endBar: span.endBar,
      startTime: range.startTime,
      endTime: range.endTime,
      anchorTime: range.startTime,
      // Uniform desc-by-score ordering: quieter windows score "higher".
      score: -sampled.mean,
      quietBonus: noveltyBonus,
      facts: {
        boundaryNovelty: noveltyBonus > 0 ? noveltyBonus : null,
        energyBefore: null,
        energyAfter: round4(sampled.mean),
        onsetDensity: facts.onsetDensity,
        peakStrength: facts.peakStrength,
        dominantBand: facts.dominantBand,
      },
    });
  }
  return candidates;
}

function dedupeCandidates(candidates) {
  const ordered = candidates.slice().sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const bonusA = a.quietBonus || 0;
    const bonusB = b.quietBonus || 0;
    if (bonusB !== bonusA) return bonusB - bonusA;
    if (a.startTime !== b.startTime) return a.startTime - b.startTime;
    return a.startBar - b.startBar;
  });
  const kept = [];
  for (const candidate of ordered) {
    const overlaps = kept.some((existing) => overlapRatio(
      existing.startTime,
      existing.endTime,
      candidate.startTime,
      candidate.endTime,
    ) > 0.5);
    if (overlaps) continue;
    kept.push(candidate);
  }
  return kept;
}

export function findVisualMoments(page, input = {}) {
  if (!page.project) throw new WebMcpError('NO_TRACK');
  const kind = input.kind;
  if (!MOMENT_KINDS.includes(kind)) {
    throw new WebMcpError('INVALID_RANGE', `kind must be one of ${MOMENT_KINDS.join(', ')}.`);
  }
  const windowBars = input.windowBars === undefined ? 8 : Math.floor(finite(input.windowBars, 8));
  if (![4, 8, 16].includes(windowBars)) {
    throw new WebMcpError('INVALID_RANGE', 'windowBars must be 4, 8, or 16 bars.');
  }
  const band = input.band === undefined ? 'all' : String(input.band);
  if (!['all', 'low', 'mid', 'high'].includes(band)) {
    throw new WebMcpError('INVALID_RANGE', 'band must be all, low, mid, or high.');
  }
  const limit = clampN(Math.floor(finite(input.limit, 3)), 1, MAX_CANDIDATES);
  const scopedPage = { ...page, band };

  let candidates;
  if (kind === 'structural_transition') candidates = structuralTransitionCandidates(scopedPage, windowBars);
  else if (kind === 'strong_transient') candidates = strongTransientCandidates(scopedPage, windowBars);
  else if (kind === 'energy_lift') candidates = energySlopeCandidates(scopedPage, windowBars);
  else if (kind === 'energy_drop') candidates = energyDropCandidates(scopedPage, windowBars);
  else candidates = quietContrastCandidates(scopedPage, windowBars);

  const kept = dedupeCandidates(candidates).slice(0, limit);
  if (!kept.length) throw new WebMcpError('NO_CANDIDATES');

  return {
    ok: true,
    query: { kind, windowBars, band },
    candidates: kept.map((candidate, index) => ({
      id: `${kind}:${candidate.startBar}-${candidate.endBar}`,
      rank: index + 1,
      startBar: candidate.startBar,
      endBar: candidate.endBar,
      startTime: round4(candidate.startTime),
      endTime: round4(candidate.endTime),
      anchorTime: round4(candidate.anchorTime),
      reason: MOMENT_REASONS[kind],
      facts: candidate.facts,
    })),
  };
}

// ---------------------------------------------------------------------------
// Tool 5: compare_ranges (plan section 12)
// ---------------------------------------------------------------------------

const COMPARE_ENERGY_THRESHOLD = 0.05;
const COMPARE_DENSITY_THRESHOLD = 0.5;

export function summarizeRange(page, range, label = null) {
  const project = page.project;
  const facts = onsetFacts(page, range.startTime, range.endTime);
  const energy = {};
  for (const band of ['all', 'low', 'mid', 'high']) {
    const sampled = sampleEnergy(page, range.startTime, range.endTime, band);
    energy[band] = { mean: round4(sampled.mean), peak: round4(sampled.peak) };
  }
  return {
    label: sanitizeLine(label, 48) || null,
    startBar: range.startBar,
    endBar: range.endBar,
    startTime: round4(range.startTime),
    endTime: round4(range.endTime),
    duration: round4(range.endTime - range.startTime),
    onsets: facts.count,
    onsetDensity: round4(facts.density),
    peakStrength: round4(facts.peak),
    energy,
    dominantBand: dominantBandOf(page, range.startTime, range.endTime),
    families: familiesIn(project, range.startTime, range.endTime),
  };
}

export function compareRanges(page, input = {}) {
  if (!page.project) throw new WebMcpError('NO_TRACK');
  const rangesInput = input.ranges;
  if (!Array.isArray(rangesInput) || rangesInput.length < 2 || rangesInput.length > 4) {
    throw new WebMcpError('INVALID_RANGE', 'compare_ranges needs 2-4 ranges.');
  }
  const summaries = rangesInput.map((entry, index) => {
    if (!entry || typeof entry !== 'object') {
      throw new WebMcpError('INVALID_RANGE', `ranges[${index}] must be an object.`);
    }
    const range = barRange(page, entry.startBar, entry.endBar);
    const label = entry.label === undefined || entry.label === null
      ? `range_${index + 1}`
      : sanitizeLine(entry.label, 48);
    return summarizeRange(page, range, label || `range_${index + 1}`);
  });

  const differences = [];
  for (let i = 1; i < summaries.length; i += 1) {
    const base = summaries[0];
    const other = summaries[i];
    const highDelta = other.energy.high.mean - base.energy.high.mean;
    if (Math.abs(highDelta) >= COMPARE_ENERGY_THRESHOLD) {
      const percent = safePercentDelta(base.energy.high.mean, other.energy.high.mean);
      const direction = highDelta > 0 ? 'higher' : 'lower';
      const amount = percent !== null
        ? `${percent}% ${direction}`
        : `${round4(Math.abs(highDelta))} ${direction}`;
      differences.push(`${other.label} has ${amount} high-band mean than ${base.label}.`);
    }
    const densityDelta = other.onsetDensity - base.onsetDensity;
    if (Math.abs(densityDelta) >= COMPARE_DENSITY_THRESHOLD) {
      const direction = densityDelta > 0 ? 'more' : 'fewer';
      differences.push(
        `${other.label} has ${Math.abs(densityDelta).toFixed(1)} ${direction} onsets per second than ${base.label}.`,
      );
    }
  }
  if (!differences.length) {
    differences.push('No large measured difference across the compared facts.');
  }

  return { ok: true, ranges: summaries, differences };
}
