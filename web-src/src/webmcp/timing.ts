/**
 * Studio Director v2 — bounded timing queries (v0.12 WebMCP plan sections 5.2,
 * 5.3, 6, 9.2).
 *
 * Everything here is pure: it reads one Studio snapshot (or a fixture shaped
 * like one) and returns a result envelope. No page state is touched, no
 * playback moves, and every timestamp and identity is the measured one —
 * nothing is quantised, moved, merged or renamed.
 *
 * Two boundary conventions, deliberately distinct and both pinned by tests:
 *
 * - a **time window** follows the runtime: `(start, end]`;
 * - a **measured bar window** is a span of stored downbeats: `[start, end)`,
 *   so the first bar's downbeat is included and adjacent windows partition
 *   cleanly. Bars are inclusive; the final bar ends at the source duration.
 */
import { createTrack, type RuntimeTrack } from '../../../beatscope/runtime/runtime.js';
import { LIMITS } from './contracts.js';
import { ToolError, failure, fitPageToBudget, sanitizeLabel, sanitizeNumber, success } from './responses.js';
import type { MovieRhythm } from '../movie/types.js';
import type { ResponseRelevanceSidecar, StudioDirectorSnapshot, ToolResult } from './types.js';

export interface RangeInput {
  start_time?: number;
  end_time?: number;
  start_bar?: number;
  end_bar?: number;
}

export interface ResolvedRange {
  start: number;
  end: number;
  source: 'time' | 'measured-bars';
  startBar: number | null;
  endBar: number | null;
  /** True for measured bar windows: their first bar's downbeat is included. */
  startInclusive: boolean;
}

export interface RangeLimits {
  maxSeconds: number;
  maxBars: number;
}

interface CachedTrack {
  track: RuntimeTrack;
  /** Stored downbeats, ascending — the only bar authority. */
  downbeats: number[];
}

/**
 * Two-key identity cache (plan section 6.2): rhythm object identity, then
 * relevance identity. `UNAVAILABLE` stands in for "no sidecar" so a project
 * without ranking is cached without pretending one exists.
 */
const UNAVAILABLE = Object.freeze({ unavailable: 'response-relevance' });
const trackCache = new WeakMap<MovieRhythm, Map<unknown, CachedTrack>>();

function relevanceKey(sidecar: ResponseRelevanceSidecar | null): unknown {
  return sidecar ?? UNAVAILABLE;
}

/** Stored downbeats (measured), never BPM arithmetic. */
export function downbeatsOf(rhythm: MovieRhythm | null): number[] {
  if (!rhythm) return [];
  const times: number[] = [];
  for (const beat of rhythm.beats ?? []) {
    const isDownbeat = beat.downbeat === true || beat.beat_in_bar === 1 || beat.beat === 1;
    const time = Number(beat.time);
    if (isDownbeat && Number.isFinite(time)) times.push(time);
  }
  return times.sort((left, right) => left - right);
}

export function trackFor(snapshot: StudioDirectorSnapshot): CachedTrack {
  const rhythm = snapshot.rhythm;
  if (!rhythm) throw new ToolError('track_required', 'No song is loaded in the studio.', 'Ask the user to upload a song.');
  const key = relevanceKey(snapshot.responseRelevance);
  let byRelevance = trackCache.get(rhythm);
  if (!byRelevance) {
    byRelevance = new Map();
    trackCache.set(rhythm, byRelevance);
  }
  const cached = byRelevance.get(key);
  if (cached) return cached;
  const entry: CachedTrack = {
    track: createTrack(rhythm, { responseRelevance: snapshot.responseRelevance ?? undefined }),
    downbeats: downbeatsOf(rhythm),
  };
  byRelevance.set(key, entry);
  return entry;
}

function durationOf(snapshot: StudioDirectorSnapshot): number {
  const duration = Number(snapshot.rhythm?.source?.duration ?? snapshot.duration);
  return Number.isFinite(duration) && duration > 0 ? duration : 0;
}

function requireFinite(value: unknown, field: string): number {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    throw new ToolError('invalid_input', `${field} must be a finite number.`, 'Send a finite second or bar value.');
  }
  return number;
}

function requireInteger(value: unknown, field: string): number {
  const number = Number(value);
  if (!Number.isInteger(number)) {
    throw new ToolError('invalid_input', `${field} must be an integer.`, 'Send a whole bar number.');
  }
  return number;
}

/**
 * One range resolver for every tool that takes a window (plan section 6.1).
 * Rejects mixed modes, partial pairs, non-finite values and reversed spans
 * instead of guessing; clamps only a valid final end to the track duration.
 */
export function resolveRange(
  snapshot: StudioDirectorSnapshot,
  input: RangeInput,
  limits: RangeLimits,
): ResolvedRange {
  const duration = durationOf(snapshot);
  if (duration <= 0) {
    throw new ToolError('track_required', 'No song is loaded in the studio.', 'Ask the user to upload a song.');
  }
  const hasTime = input.start_time !== undefined || input.end_time !== undefined;
  const hasBar = input.start_bar !== undefined || input.end_bar !== undefined;
  if (hasTime && hasBar) {
    throw new ToolError('invalid_input', 'Send either a time window or a bar window, not both.', 'Pick one range representation.');
  }
  if (!hasTime && !hasBar) {
    throw new ToolError('invalid_input', 'A time window or a bar window is required.', 'Send start_time/end_time or start_bar/end_bar.');
  }

  if (hasTime) {
    if (input.start_time === undefined || input.end_time === undefined) {
      throw new ToolError('invalid_input', 'A time window needs both start_time and end_time.', 'Send the missing end of the window.');
    }
    const start = requireFinite(input.start_time, 'start_time');
    let end = requireFinite(input.end_time, 'end_time');
    if (start < 0 || end < 0) {
      throw new ToolError('out_of_range', 'Time values cannot be negative.', `Use seconds between 0 and ${duration}.`);
    }
    if (end <= start) {
      throw new ToolError('invalid_range', 'end_time must be greater than start_time.', 'Widen the window instead of reversing it.');
    }
    if (start >= duration) {
      throw new ToolError('out_of_range', `start_time is past the end of the song (${duration} s).`, 'Use a time inside the song.');
    }
    if (end - start > limits.maxSeconds) {
      throw new ToolError('invalid_range', `The window spans more than ${limits.maxSeconds} s.`, 'Split the range into smaller queries.');
    }
    // Only a valid end is clamped, so an oversized request is refused instead
    // of being silently narrowed to the song.
    end = Math.min(end, duration);
    return { start, end, source: 'time', startBar: null, endBar: null, startInclusive: false };
  }

  const startBar = requireInteger(input.start_bar, 'start_bar');
  const endBar = requireInteger(input.end_bar, 'end_bar');
  if (startBar < 1 || endBar < 1) {
    throw new ToolError('out_of_range', 'Bars are 1-based.', 'Use bars starting at 1.');
  }
  if (endBar < startBar) {
    throw new ToolError('invalid_range', 'end_bar must be greater than or equal to start_bar.', 'Order the bars ascending.');
  }
  if (endBar - startBar + 1 > limits.maxBars) {
    throw new ToolError('invalid_range', `The window spans more than ${limits.maxBars} bars.`, 'Split the range into smaller queries.');
  }
  const { downbeats } = trackFor(snapshot);
  if (downbeats.length < 2) {
    throw new ToolError(
      'beat_grid_unavailable',
      'This song has no measured beat grid, so bars cannot be resolved.',
      'Query a time window instead.',
    );
  }
  if (startBar > downbeats.length) {
    throw new ToolError('out_of_range', `The song has ${downbeats.length} measured bars.`, 'Use bars inside the measured grid.');
  }
  const start = downbeats[startBar - 1];
  // The bar after the last requested one opens the window's exclusive end; the
  // final measured bar ends at the source duration.
  const nextDownbeat = downbeats[endBar];
  const end = nextDownbeat === undefined ? duration : Math.min(nextDownbeat, duration);
  if (!(end > start)) {
    throw new ToolError('invalid_range', 'That bar window is empty.', 'Widen the bar range.');
  }
  return { start, end, source: 'measured-bars', startBar, endBar, startInclusive: true };
}

function inRange(time: number, range: ResolvedRange): boolean {
  if (range.startInclusive) return time >= range.start && time < range.end;
  return time > range.start && time <= range.end;
}

type EventRow = Record<string, unknown> & { kind: string; time: number };

function sortRows(rows: EventRow[]): EventRow[] {
  return rows.sort((left, right) => (
    left.time - right.time
    || left.kind.localeCompare(right.kind)
    || String(left.id ?? '').localeCompare(String(right.id ?? ''))
  ));
}

const DEFAULT_INCLUDE = ['beats', 'onsets', 'cues'] as const;
const ALL_CUE_TYPES = ['accent', 'impact', 'scale', 'flow', 'flash', 'bloom'] as const;

export interface InspectTimingInput extends RangeInput {
  include?: string[];
  cue_types?: string[];
  limit?: number;
  offset?: number;
}

/** `beatscope_inspect_timing` (plan section 5.2). Read-only, bounded, paginated. */
export function inspectTiming(snapshot: StudioDirectorSnapshot, input: InspectTimingInput): ToolResult {
  const tool = 'beatscope_inspect_timing' as const;
  try {
    const rhythm = snapshot.rhythm;
    if (!rhythm) {
      throw new ToolError('track_required', 'No song is loaded in the studio.', 'Ask the user to upload a song.');
    }
    const range = resolveRange(snapshot, input, { maxSeconds: LIMITS.timing_seconds, maxBars: LIMITS.timing_bars });
    const include = new Set(input.include ?? DEFAULT_INCLUDE);
    const cueTypes = new Set(input.cue_types ?? ALL_CUE_TYPES);
    const limit = Math.min(Math.max(1, Math.floor(Number(input.limit ?? 100) || 100)), LIMITS.timing_events);
    const offset = Math.max(0, Math.floor(Number(input.offset ?? 0) || 0));

    const rows: EventRow[] = [];
    if (include.has('onsets')) {
      const { track } = trackFor(snapshot);
      const onsets = range.startInclusive
        ? (track.map.onsets as unknown as EventRow[]).filter((onset) => inRange(Number(onset.time), range))
        : track.between(range.start, range.end);
      for (const onset of onsets) rows.push({ ...(onset as EventRow), kind: 'onset' });
    }
    if (include.has('beats')) {
      for (const beat of rhythm.beats ?? []) {
        if (inRange(Number(beat.time), range)) rows.push({ kind: 'beat', ...beat });
      }
    }
    if (include.has('cues')) {
      for (const [type, cues] of Object.entries(rhythm.cues ?? {})) {
        if (!cueTypes.has(type)) continue;
        for (const cue of cues ?? []) {
          if (inRange(Number(cue.time), range)) rows.push({ kind: 'cue', type, ...cue });
        }
      }
    }
    if (include.has('segments')) {
      for (const segment of rhythm.patterns?.segments ?? []) {
        if (Number(segment.start_time) < range.end && Number(segment.end_time) > range.start) {
          rows.push({
            kind: 'segment',
            time: Number(segment.start_time),
            end: Number(segment.end_time),
            id: segment.id ?? null,
            family: segment.family,
            label: segment.display_label ?? null,
            index: segment.index ?? null,
          });
        }
      }
    }
    if (include.has('boundaries')) {
      for (const boundary of rhythm.patterns?.boundaries ?? []) {
        if (inRange(Number(boundary.time), range)) {
          rows.push({ kind: 'boundary', novelty: boundary.novelty ?? null, ...boundary });
        }
      }
    }

    const sorted = sortRows(rows);
    const envelope = (page: EventRow[], next: number, more: boolean, count: number) => success(
      tool,
      `${sorted.length} event(s) between ${sanitizeNumber(range.start)} s and ${sanitizeNumber(range.end)} s.`,
      {
        start: sanitizeNumber(range.start),
        end: sanitizeNumber(range.end),
        source: range.source,
        start_bar: range.startBar,
        end_bar: range.endBar,
        include: [...include].sort(),
        total: sorted.length,
        count,
        offset,
        has_more: more,
        next_offset: more ? next : null,
        events: page,
      },
    );
    const fitted = fitPageToBudget(sorted, offset, limit, envelope);
    return envelope(fitted.page, fitted.nextOffset, fitted.hasMore, fitted.count) as ToolResult;
  } catch (error) {
    if (error instanceof ToolError) return failure(tool, error.code, error.message, error.nextAction);
    return failure(tool, 'internal_error', 'The timing query failed.', 'Report this to the user; the studio console has the details.');
  }
}

export interface ResponseEventsInput extends RangeInput {
  budget: number;
  band?: 'all' | 'low' | 'mid' | 'high';
}

/**
 * `beatscope_get_response_events` (plan section 5.3).
 *
 * The name promises ranking, so a missing sidecar fails honestly instead of
 * falling back to chronological order. Band preference is applied as one
 * frozen ordering: band evidence, then relevance, then time, then id — and the
 * returned set is restored to chronological order for direct scheduling.
 */
export function responseEvents(snapshot: StudioDirectorSnapshot, input: ResponseEventsInput): ToolResult {
  const tool = 'beatscope_get_response_events' as const;
  try {
    if (!snapshot.rhythm) {
      throw new ToolError('track_required', 'No song is loaded in the studio.', 'Ask the user to upload a song.');
    }
    const budget = Number(input.budget);
    if (!Number.isInteger(budget) || budget < 1 || budget > LIMITS.response_events) {
      throw new ToolError('invalid_input', `budget must be an integer from 1 to ${LIMITS.response_events}.`, 'Pick a budget inside that range.');
    }
    const band = input.band ?? 'all';
    if (!['all', 'low', 'mid', 'high'].includes(band)) {
      throw new ToolError('invalid_input', 'band must be all, low, mid or high.', 'Pick one of the measured bands.');
    }
    const range = resolveRange(snapshot, input, { maxSeconds: LIMITS.timing_seconds, maxBars: LIMITS.timing_bars });
    const { track } = trackFor(snapshot);
    const filter = (events: Record<string, unknown>[]) => (range.startInclusive
      ? events.filter((event) => inRange(Number(event.time), range))
      : events);

    const overfetch = band === 'all'
      ? budget
      : Math.min(LIMITS.response_overfetch, budget * LIMITS.response_overfetch_factor);
    const selection = track.responseBetween(range.start, range.end, overfetch);
    if (!selection.available || !snapshot.responseRelevance) {
      throw new ToolError(
        'ranking_unavailable',
        'This song has no response-relevance sidecar.',
        'Use beatscope_inspect_timing for chronological raw events.',
      );
    }
    const candidates = filter(selection.events ?? []);
    const evidence = (event: Record<string, unknown>) => {
      const bands = (event.bands ?? {}) as Record<string, number>;
      const value = band === 'all' ? bands.all ?? event.strength : bands[band];
      return Number.isFinite(Number(value)) ? Number(value) : 0;
    };
    const selected = band === 'all'
      ? candidates.slice(0, budget)
      : [...candidates]
        .sort((left, right) => (
          evidence(right) - evidence(left)
          || (Number(right.response_relevance) || 0) - (Number(left.response_relevance) || 0)
          || Number(left.time) - Number(right.time)
          || (Number(left.id) || 0) - (Number(right.id) || 0)
        ))
        .slice(0, budget)
        .sort((left, right) => Number(left.time) - Number(right.time) || (Number(left.id) || 0) - (Number(right.id) || 0));

    const strategy = band === 'all' ? selection.strategy : 'band-evidence-then-response-relevance';
    return success(
      tool,
      `${selected.length} of ${candidates.length} candidate onset(s) between ${sanitizeNumber(range.start)} s and ${sanitizeNumber(range.end)} s.`,
      {
        available: true,
        semantics: selection.semantics,
        strategy,
        band,
        budget,
        start: sanitizeNumber(range.start),
        end: sanitizeNumber(range.end),
        candidate_count: candidates.length,
        selected_count: selected.length,
        events: selected,
      },
    );
  } catch (error) {
    if (error instanceof ToolError) return failure(tool, error.code, error.message, error.nextAction);
    return failure(tool, 'internal_error', 'The response query failed.', 'Report this to the user; the studio console has the details.');
  }
}

/**
 * `beatscope_get_studio_state` (plan section 5.1). The clock is derived from
 * the stage exactly as the studio switches media elements: the song's audio
 * before a film exists, the film afterwards.
 */
export function studioState(snapshot: StudioDirectorSnapshot): ToolResult {
  const tool = 'beatscope_get_studio_state' as const;
  const rhythm = snapshot.rhythm ?? null;
  const duration = durationOf(snapshot);
  const downbeats = downbeatsOf(rhythm);
  const relevanceAvailable = Boolean(snapshot.responseRelevance);
  const clock = snapshot.stage === 'complete' || snapshot.stage === 'rendering'
    ? 'film'
    : snapshot.stage === 'preview'
      ? 'audio'
      : 'none';
  const data = {
    stage: snapshot.stage,
    track: rhythm === null
      ? null
      : {
        display_name: sanitizeLabel(snapshot.name),
        duration: sanitizeNumber(duration),
        global_bpm: sanitizeNumber(rhythm.tempo?.global_bpm ?? null),
        bars: downbeats.length > 1 ? downbeats.length : Number(rhythm.grid?.bars ?? 0),
        structural_segments: (rhythm.patterns?.segments ?? []).length,
        beat_grid_available: downbeats.length >= 2,
        response_relevance_available: relevanceAvailable,
      },
    playback: {
      time: sanitizeNumber(snapshot.currentTime) ?? 0,
      playing: snapshot.playing,
      clock,
    },
    movie: {
      template: 'VOXEL INTERFERENCE',
      plan_version: 'voxel-phrase-2',
      seed: snapshot.seed,
      renderer_available: snapshot.rendererAvailable,
      job: snapshot.movieJob,
    },
    capabilities: {
      timing_queries: rhythm !== null,
      ranked_events: rhythm !== null && relevanceAvailable,
      movie_explanation: rhythm !== null && relevanceAvailable,
      playback_actions: duration > 0,
      rendering: rhythm !== null && snapshot.rendererAvailable,
      timing_export: Boolean(snapshot.projectId),
    },
  };
  const summary = rhythm === null
    ? `Nothing is loaded; the studio is ${snapshot.stage}.`
    : `${sanitizeLabel(snapshot.name)} is ${snapshot.stage} at ${sanitizeNumber(snapshot.currentTime)} s${snapshot.seed === null ? '' : `, seed ${snapshot.seed}`}.`;
  return success(tool, summary, data);
}
