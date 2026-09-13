/**
 * Studio Director v2 — movie plan explanations (v0.12 WebMCP plan section 5.4).
 *
 * The explanation is derived from the shipping plan function, called the same
 * way the live preview and the renderer call it:
 *
 *   const track = createTrack(rhythm, { responseRelevance: ranking });
 *   const plan = makePlan(rhythm, track.responseBetween(0, duration), seed);
 *
 * Nothing here invents a cut, a mood or a section name. A shot's cut is
 * reported as the song start, a stored structural boundary, or a ranked
 * original onset with its measured id and time.
 */
import { makePlan } from '../../../beatscope/web/mv-plan.mjs';
import { LIMITS } from './contracts.js';
import { ToolError, failure, sanitizeNumber, success } from './responses.js';
import { trackFor } from './timing.js';
import type { MovieShot } from '../../../beatscope/web/mv-plan.mjs';
import type { StudioDirectorSnapshot, ToolResult } from './types.js';

export interface ExplainMovieInput {
  time?: number;
  shot_index?: number;
  context?: number;
}

interface CachedPlan {
  plan: ReturnType<typeof makePlan>;
}

/**
 * Plan cache keyed by rhythm identity, relevance identity and seed (plan
 * section 6.3). Callers only ever receive selected fields; the plan object
 * never leaves this module.
 */
const planCache = new WeakMap<object, Map<object | null, Map<number, CachedPlan>>>();

function planFor(snapshot: StudioDirectorSnapshot) {
  const rhythm = snapshot.rhythm;
  if (!rhythm) {
    throw new ToolError('track_required', 'No song is loaded in the studio.', 'Ask the user to upload a song.');
  }
  if (!snapshot.responseRelevance) {
    throw new ToolError(
      'ranking_unavailable',
      'This song has no response-relevance sidecar, so there is no deterministic cut list to explain.',
      'Explain timing instead, or ask the user to analyse the song again.',
    );
  }
  const seed = Number.isInteger(snapshot.seed) ? Number(snapshot.seed) : 0;
  let byRelevance = planCache.get(rhythm);
  if (!byRelevance) {
    byRelevance = new Map();
    planCache.set(rhythm, byRelevance);
  }
  const key = snapshot.responseRelevance;
  let bySeed = byRelevance.get(key);
  if (!bySeed) {
    bySeed = new Map();
    byRelevance.set(key, bySeed);
  }
  const cached = bySeed.get(seed);
  if (cached) return { rhythm, seed, plan: cached.plan };

  const { track } = trackFor(snapshot);
  const duration = Number(rhythm.source?.duration ?? snapshot.duration);
  let plan;
  try {
    plan = makePlan(rhythm, track.responseBetween(0, duration), seed);
  } catch (error) {
    throw new ToolError(
      'movie_plan_unavailable',
      `The deterministic plan cannot be built for this song: ${error instanceof Error ? error.message : String(error)}`,
      'Check that the song is between 0 and 600 seconds and has a response-relevance sidecar.',
    );
  }
  bySeed.set(seed, { plan });
  return { rhythm, seed, plan };
}

function shotIndexAt(shots: MovieShot[], time: number): number {
  if (shots.length === 0) return -1;
  let low = 0;
  let high = shots.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (time >= shots[middle].start && time < shots[middle].end) return middle;
    if (time < shots[middle].start) high = middle - 1;
    else { found = middle; low = middle + 1; }
  }
  return found;
}

/** Resolve one cut's cause without inventing anything. */
function entryOf(rhythm: NonNullable<StudioDirectorSnapshot['rhythm']>, shot: MovieShot) {
  if (shot.kind === 'start') {
    return { kind: 'start' as const, time: 0 };
  }
  if (shot.kind === 'structure') {
    const segment = (rhythm.patterns?.segments ?? []).find((candidate) => candidate.id === shot.eventId);
    return {
      kind: 'structure' as const,
      segment_id: segment?.id ?? shot.eventId,
      family: segment?.family ?? shot.family,
      label: segment?.display_label ?? null,
      time: sanitizeNumber(segment?.start_time ?? shot.start),
    };
  }
  const onset = (rhythm.onsets ?? []).find((candidate) => candidate.id === shot.eventId);
  return {
    kind: 'onset' as const,
    onset_id: shot.eventId,
    time: sanitizeNumber(onset?.time ?? shot.start),
    strength: sanitizeNumber(onset?.strength ?? null),
    bands: onset?.bands ?? null,
  };
}

function relevanceOf(snapshot: StudioDirectorSnapshot, onsetId: unknown): number | null {
  const events = snapshot.responseRelevance?.events ?? [];
  const row = events.find((entry) => String(entry.onset_id) === String(onsetId));
  return row ? sanitizeNumber(row.response_relevance) : null;
}

function describe(
  rhythm: NonNullable<StudioDirectorSnapshot['rhythm']>,
  snapshot: StudioDirectorSnapshot,
  shot: MovieShot,
  index: number,
) {
  const entry = entryOf(rhythm, shot);
  return {
    index,
    start: sanitizeNumber(shot.start),
    end: sanitizeNumber(shot.end),
    family: shot.family,
    world: shot.world,
    entry: entry.kind === 'onset'
      ? { ...entry, response_relevance: relevanceOf(snapshot, shot.eventId) }
      : entry,
  };
}

/** `beatscope_explain_movie` (plan section 5.4). */
export function explainMovie(snapshot: StudioDirectorSnapshot, input: ExplainMovieInput): ToolResult {
  const tool = 'beatscope_explain_movie' as const;
  try {
    if (input.time !== undefined && input.shot_index !== undefined) {
      throw new ToolError('invalid_input', 'Send either time or shot_index, not both.', 'Pick one way to select the shot.');
    }
    const context = Math.min(Math.max(0, Math.floor(Number(input.context ?? 1) || 0)), 3);
    const { rhythm, seed, plan } = planFor(snapshot);
    const shots = plan.shots ?? [];
    if (shots.length === 0) {
      throw new ToolError('movie_plan_unavailable', 'The plan has no shots.', 'Check the song and its ranking sidecar.');
    }

    let index: number;
    if (input.shot_index !== undefined) {
      const requested = Math.floor(Number(input.shot_index));
      if (!Number.isFinite(requested) || requested < 0 || requested >= shots.length) {
        throw new ToolError('out_of_range', `shot_index must be from 0 to ${shots.length - 1}.`, 'Use a shot inside the plan.');
      }
      index = requested;
    } else {
      const time = Number(input.time ?? snapshot.currentTime);
      if (!Number.isFinite(time) || time < 0) {
        throw new ToolError('invalid_input', 'time must be a finite number of seconds.', 'Send a time inside the song.');
      }
      if (time >= Number(plan.duration)) {
        throw new ToolError('out_of_range', `time is past the end of the song (${plan.duration} s).`, 'Use a time inside the song.');
      }
      index = shotIndexAt(shots, time);
      if (index < 0) {
        throw new ToolError('out_of_range', 'That time is outside every shot.', 'Use a time inside the song.');
      }
    }

    const first = Math.max(0, index - context);
    const last = Math.min(shots.length - 1, index + context);
    const window = [];
    for (let position = first; position <= last; position += 1) {
      window.push(describe(rhythm, snapshot, shots[position], position));
    }
    const shot = window[index - first];
    const neighbors = window.filter((entry) => entry.index !== index);
    const cause = shot.entry.kind === 'onset'
      ? `ranked onset ${shot.entry.onset_id} at ${shot.entry.time} s`
      : shot.entry.kind === 'structure'
        ? `structural boundary ${shot.entry.segment_id} (family ${shot.entry.family})`
        : 'the start of the song';
    return success(
      tool,
      `Shot ${index} begins at ${shot.start} s on ${cause}.`,
      {
        seed,
        plan_version: plan.version,
        shot,
        neighbors,
      },
    );
  } catch (error) {
    if (error instanceof ToolError) return failure(tool, error.code, error.message, error.nextAction);
    return failure(tool, 'internal_error', 'The movie explanation failed.', 'Report this to the user; the studio console has the details.');
  }
}

export { LIMITS as EXPLANATION_LIMITS };
