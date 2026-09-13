/// <reference types="webmcp-types" />
/**
 * Studio Director v2 — frozen contracts (v0.12 WebMCP plan sections 4, 5, 9).
 *
 * Every tool name, title, description, schema and annotation below is a frozen
 * literal: no song name, project id, server message or user text may ever be
 * interpolated into a definition. `tests/test_studio_webmcp_contracts.js`
 * pins the canonical bytes of this catalog, so a contract change is always a
 * deliberate, reviewed snapshot change.
 *
 * Vocabulary is deliberately narrow. The retired director's words
 * (visual_recipe, visual_timeline, scene_director, focus_range, set_loop_range)
 * and its inputs (arbitrary project_id, paths, URLs, style or template text)
 * must never come back through this surface.
 */
import type { ErrorCode, ToolDefinition } from './types.js';

/** Resource limits, frozen with the contracts (plan section 9.2). */
export const LIMITS = Object.freeze({
  /** Longest accepted query or audition span, in seconds. */
  timing_seconds: 180,
  /** Longest accepted bar window, inclusive bars. */
  timing_bars: 64,
  /** Most events one timing query may return. */
  timing_events: 200,
  /** Most events the ranked response query may return. */
  response_events: 64,
  /** Most shots one movie explanation may return, including context. */
  explanation_shots: 7,
  /** Internal over-fetch ceiling before the band filter (plan section 5.3). */
  response_overfetch: 256,
  /** Internal over-fetch multiplier before the band filter. */
  response_overfetch_factor: 4,
  /** Hard ceiling for one serialized tool result, in UTF-16 code units. */
  result_code_units: 16000,
  /** Longest sanitized project-derived label, in characters. */
  label_characters: 160,
  /** Highest accepted render seed (24-bit unsigned). */
  seed_max: 16777215,
});

export const READ_ANNOTATIONS: WebMCP.ToolAnnotations = Object.freeze({
  readOnlyHint: true,
  untrustedContentHint: true,
  consequentialHint: false,
});

export const PAGE_ACTION_ANNOTATIONS: WebMCP.ToolAnnotations = Object.freeze({
  readOnlyHint: false,
  untrustedContentHint: true,
  consequentialHint: false,
});

export const CONSEQUENCE_ANNOTATIONS: WebMCP.ToolAnnotations = Object.freeze({
  readOnlyHint: false,
  untrustedContentHint: true,
  consequentialHint: true,
});

const INCLUDE_VALUES = ['beats', 'onsets', 'cues', 'segments', 'boundaries'] as const;
const CUE_TYPE_VALUES = ['accent', 'impact', 'scale', 'flow', 'flash', 'bloom'] as const;
const BAND_VALUES = ['all', 'low', 'mid', 'high'] as const;

/**
 * One range representation per call: either a time window or an inclusive bar
 * window. The resolver enforces the pairing rules; the schema only offers the
 * fields (plan section 6.1).
 */
const RANGE_PROPERTIES = {
  start_time: { type: 'number', minimum: 0, description: 'Window start in measured seconds; the window is (start, end].' },
  end_time: { type: 'number', minimum: 0, description: 'Window end in measured seconds; exclusive of the start.' },
  start_bar: { type: 'integer', minimum: 1, description: 'First bar of an inclusive measured bar window.' },
  end_bar: { type: 'integer', minimum: 1, description: 'Last bar of an inclusive measured bar window.' },
} as const;

const CATALOG: ToolDefinition[] = [
  {
    name: 'beatscope_get_studio_state',
    title: 'Read the BeatScope studio state',
    kind: 'read',
    description:
      "Report what the user's BeatScope studio currently shows: the loaded song's measured summary, " +
      'playback position and which media clock owns it, the deterministic movie template and seed, ' +
      'any active render job, and which of the other tools can work right now. Call this first. ' +
      'It describes the visible document only and never lists songs the user has not opened.',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false },
    annotations: READ_ANNOTATIONS,
  },
  {
    name: 'beatscope_inspect_timing',
    title: 'Inspect measured timing',
    kind: 'read',
    description:
      'Read the loaded song\'s measured facts inside one bounded window: beats, onsets, cues, structural ' +
      'segments and boundaries. Every time is the exact measured second - nothing is quantised, moved, ' +
      'merged or renamed, and no instrument identity is invented. Give either a time window or an ' +
      'inclusive measured bar window, never both. Read-only: playback does not move.',
    inputSchema: {
      type: 'object',
      properties: {
        ...RANGE_PROPERTIES,
        include: {
          type: 'array',
          items: { type: 'string', enum: [...INCLUDE_VALUES] },
          description: 'Which facts to return. Defaults to beats, onsets and cues.',
        },
        cue_types: {
          type: 'array',
          items: { type: 'string', enum: [...CUE_TYPE_VALUES] },
          description: 'Cue families to include when cues are requested.',
        },
        limit: { type: 'integer', minimum: 1, maximum: 200, default: 100, description: 'Events per page.' },
        offset: { type: 'integer', minimum: 0, default: 0, description: 'Pagination offset.' },
      },
      additionalProperties: false,
    },
    annotations: READ_ANNOTATIONS,
  },
  {
    name: 'beatscope_get_response_events',
    title: 'Get ranked response events',
    kind: 'read',
    description:
      "Return a caller-sized set of the loaded song's existing onsets that are worth considering for " +
      'animation, editing or scene changes, selected by the measured response-relevance sidecar. A budget ' +
      'is a count, not a threshold: the events are the original onsets, unshifted, and come back in ' +
      'chronological order. When the song has no relevance sidecar this fails with ranking_unavailable ' +
      'instead of passing chronological order off as a ranking.',
    inputSchema: {
      type: 'object',
      properties: {
        ...RANGE_PROPERTIES,
        budget: { type: 'integer', minimum: 1, maximum: 64, description: 'How many events to return.' },
        band: {
          type: 'string',
          enum: [...BAND_VALUES],
          default: 'all',
          description: 'Prefer events with the strongest evidence in one measured band.',
        },
      },
      required: ['budget'],
      additionalProperties: false,
    },
    annotations: READ_ANNOTATIONS,
  },
  {
    name: 'beatscope_explain_movie',
    title: 'Explain the current movie cut',
    kind: 'read',
    description:
      'Explain a real decision in the current deterministic movie plan for the loaded song: which shot ' +
      'covers a time or shot index, where its cut came from (the song start, a structural boundary, or a ' +
      'ranked onset with its original id and measured time), and which visual world the plan assigned to ' +
      'it. The plan is produced by the same deterministic function the live preview and the renderer use. ' +
      'A structural family is recurrence evidence, never a section name.',
    inputSchema: {
      type: 'object',
      properties: {
        time: { type: 'number', minimum: 0, description: 'Media time to explain; defaults to the current playhead.' },
        shot_index: { type: 'integer', minimum: 0, description: 'Zero-based shot index instead of a time.' },
        context: { type: 'integer', minimum: 0, maximum: 3, default: 1, description: 'Adjacent shots to include.' },
      },
      additionalProperties: false,
    },
    annotations: READ_ANNOTATIONS,
  },
  {
    name: 'beatscope_control_playback',
    title: 'Control playback',
    kind: 'action',
    description:
      'Operate the visible media element: play, pause, seek to a time or a measured bar, audition a range ' +
      '(it stops at the range end), or restore the position and play state that were saved before the last ' +
      'audition. It never changes the song, the seed, the movie plan or any export. A blocked autoplay is ' +
      'reported honestly instead of being hidden.',
    inputSchema: {
      type: 'object',
      properties: {
        action: { type: 'string', enum: ['play', 'pause', 'seek', 'audition', 'restore'] },
        time: { type: 'number', minimum: 0, description: 'Seek target in measured seconds.' },
        bar: { type: 'integer', minimum: 1, description: 'Seek target bar, converted from measured downbeats.' },
        beat: { type: 'integer', minimum: 1, description: 'Beat inside the target bar; only with bar.' },
        start_time: { type: 'number', minimum: 0, description: 'Audition start in measured seconds.' },
        end_time: { type: 'number', minimum: 0, description: 'Audition end in measured seconds.' },
        start_bar: { type: 'integer', minimum: 1, description: 'Audition start bar, inclusive.' },
        end_bar: { type: 'integer', minimum: 1, description: 'Audition end bar, inclusive.' },
        autoplay: { type: 'boolean', default: true, description: 'Audition plays immediately unless false.' },
      },
      required: ['action'],
      additionalProperties: false,
    },
    annotations: PAGE_ACTION_ANNOTATIONS,
  },
  {
    name: 'beatscope_render_movie',
    title: 'Render the movie',
    kind: 'action',
    description:
      'Start one deterministic render of the loaded song using the current seed or a supplied 24-bit seed, ' +
      'or cancel the active render. Starting uses the same path as the visible Generate button: a supplied ' +
      'seed becomes the visible seed before the preview and the render begin. It returns as soon as the job ' +
      'exists - read progress with beatscope_get_studio_state - and it never replaces a running render. ' +
      'Cancelling uses the same path as the visible Cancel button.',
    inputSchema: {
      type: 'object',
      properties: {
        action: { type: 'string', enum: ['start', 'cancel'] },
        seed: {
          type: 'integer',
          minimum: 0,
          maximum: 16777215,
          description: 'Deterministic variation seed; start only.',
        },
      },
      required: ['action'],
      additionalProperties: false,
    },
    annotations: CONSEQUENCE_ANNOTATIONS,
  },
  {
    name: 'beatscope_export_timing_package',
    title: 'Export the timing package',
    kind: 'action',
    description:
      'Start the visible timing-package download for the loaded song: measured timing facts, the ' +
      'deterministic runtime, the self-check probe, the Skill and agent guidance, MIDI and CSV. Source ' +
      'audio, the movie, the visual template, scenes and any task statement are excluded. The archive bytes ' +
      'never enter the result.',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false },
    annotations: CONSEQUENCE_ANNOTATIONS,
  },
];

/** Deep-frozen so a caller can never mutate a registered contract in place. */
function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const item of Object.values(value as Record<string, unknown>)) deepFreeze(item);
  }
  return value;
}

export const TOOL_DEFINITIONS: readonly ToolDefinition[] = deepFreeze(CATALOG);

export const TOOL_NAMES = Object.freeze(TOOL_DEFINITIONS.map((tool) => tool.name));

/** Frozen failure vocabulary (plan section 7.4). */
export const ERROR_CODE_SET: readonly ErrorCode[] = Object.freeze([
  'track_required',
  'service_unavailable',
  'invalid_input',
  'invalid_range',
  'out_of_range',
  'beat_grid_unavailable',
  'ranking_unavailable',
  'movie_plan_unavailable',
  'playback_unavailable',
  'render_unavailable',
  'render_busy',
  'render_not_active',
  'download_requires_user_action',
  'canceled',
  'internal_error',
]);

/** Bounded reasons a render can fail, plus one frozen next action each. */
export const MOVIE_FAILURE_CODES = Object.freeze([
  'audio_digest_mismatch',
  'renderer_unavailable',
  'mux_failed',
  'render_failed',
] as const);

export type MovieFailureCode = (typeof MOVIE_FAILURE_CODES)[number];

const FAILURE_MATCHERS: readonly (readonly [RegExp, MovieFailureCode])[] = Object.freeze([
  [/hash mismatch|digest|sha-?256/i, 'audio_digest_mismatch'],
  [/ffmpeg|mux/i, 'mux_failed'],
  [/playwright|chromium|renderer|not configured/i, 'renderer_unavailable'],
]);

/**
 * Classify the studio's own failure text into the frozen vocabulary. The text
 * itself never travels: only the code and its fixed next action leave the page.
 */
export function classifyMovieFailure(text: string | null | undefined): MovieFailureCode {
  if (typeof text === 'string') {
    for (const [pattern, code] of FAILURE_MATCHERS) if (pattern.test(text)) return code;
  }
  return 'render_failed';
}

export const MOVIE_FAILURE_ACTIONS: Readonly<Record<MovieFailureCode, string>> = Object.freeze({
  audio_digest_mismatch: 'Re-analyse the song so the analysis matches the audio on disk, then render again.',
  renderer_unavailable: 'Check the local renderer setup (Node, FFmpeg, Playwright), then render again.',
  mux_failed: 'Retry the render; if it repeats, read the studio log.',
  render_failed: 'Read the studio log, then retry the render.',
});

/** Retired vocabulary that must never reappear in a definition. */
export const RETIRED_TOKENS: readonly string[] = Object.freeze([
  'visual_recipe',
  'visual-recipe',
  'visual_timeline',
  'visual-timeline',
  'scene_director',
  'scene-director',
  'visual_profile',
  'focus_range',
  'set_loop_range',
  'agent focus',
]);

/** Input keys no tool may accept (plan section 9.1). */
export const FORBIDDEN_INPUT_KEYS: readonly string[] = Object.freeze([
  'project_id',
  'projectId',
  'path',
  'file',
  'filename',
  'url',
  'uri',
  'prompt',
  'text',
  'style',
  'template',
  'shader',
  'expression',
  'command',
  'html',
  'script',
  'audio',
  'destination',
]);
