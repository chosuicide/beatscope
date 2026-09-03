/**
 * BeatScope Director tool contracts (v0.10 plan sections 6-7).
 *
 * The eight WebMCP tools and their JSON Schemas are frozen literals: the
 * descriptions are never assembled from song names, file metadata, or user
 * input (plan section 20.2), so a hostile project cannot poison the tool
 * catalog. Handlers re-validate every input; the schemas are the published
 * shape, not the only line of defense.
 */

export const TOOL_NAMES = Object.freeze([
  'get_project_context',
  'get_state_at_time',
  'get_events',
  'find_visual_moments',
  'compare_ranges',
  'focus_range',
  'control_playback',
  'set_loop_range',
]);

const READ_ANNOTATIONS = Object.freeze({ readOnlyHint: true });
const ACTION_ANNOTATIONS = Object.freeze({ readOnlyHint: false });

const get_project_context = Object.freeze({
  name: 'get_project_context',
  title: 'Get project context',
  description:
    'Read a compact summary of the loaded BeatScope track: tempo, bar grid, ' +
    'playback position, loop state, and neutral structural segments. Call ' +
    'this first to understand what the page currently holds. Read-only: it ' +
    'never changes playback, the loop, or the UI.',
  inputSchema: Object.freeze({
    type: 'object',
    properties: {},
    additionalProperties: false,
  }),
  annotations: READ_ANNOTATIONS,
});

const get_state_at_time = Object.freeze({
  name: 'get_state_at_time',
  title: 'Get state at time',
  description:
    'Inspect the deterministic musical state at one moment: bar/beat ' +
    'position, band energy, onset impulse, structural segment phase, and ' +
    '(when visual artifacts are loaded) the scene state. Omit time to ' +
    'inspect the current playback position. Read-only: the player does not move.',
  inputSchema: Object.freeze({
    type: 'object',
    properties: {
      time: {
        description:
          'Seconds from the start of the loaded track. Omit to inspect the current playback time.',
        type: 'number',
        minimum: 0,
      },
      includeScene: { type: 'boolean', default: true },
    },
    additionalProperties: false,
  }),
  annotations: READ_ANNOTATIONS,
});

const get_events = Object.freeze({
  name: 'get_events',
  title: 'Get events',
  description:
    'List discrete musical facts inside one bounded window: beats, onsets, ' +
    'structural segments, boundaries, and accent cues. Give a time range ' +
    '(startTime and endTime) or a bar range (startBar and endBar), never ' +
    'both. Bars are 1-based and inclusive; time windows follow the runtime ' +
    'event slicing where beats and onsets use (startTime, endTime]. Windows ' +
    'are capped at 64 bars or 180 seconds. Read-only.',
  inputSchema: Object.freeze({
    type: 'object',
    properties: {
      startTime: { type: 'number', minimum: 0 },
      endTime: { type: 'number', minimum: 0 },
      startBar: { type: 'integer', minimum: 1 },
      endBar: { type: 'integer', minimum: 1 },
      include: {
        type: 'array',
        minItems: 1,
        maxItems: 5,
        uniqueItems: true,
        items: {
          type: 'string',
          enum: ['beats', 'onsets', 'segments', 'boundaries', 'cues'],
        },
        default: ['beats', 'onsets', 'boundaries'],
      },
      limit: { type: 'integer', minimum: 1, maximum: 200, default: 100 },
    },
    required: ['include'],
    additionalProperties: false,
  }),
  annotations: READ_ANNOTATIONS,
});

const find_visual_moments = Object.freeze({
  name: 'find_visual_moments',
  title: 'Find visual moments',
  description:
    'Rank candidate ranges for a visual change or audition using measured ' +
    'facts only: structural_transition, strong_transient, energy_lift, ' +
    'energy_drop, or quiet_contrast. Returns at most 8 candidates with ' +
    'stable ids and bar-aligned windows. It reports neutral facts and never ' +
    'labels a range verse, chorus, drop, kick, or snare. Read-only.',
  inputSchema: Object.freeze({
    type: 'object',
    properties: {
      kind: {
        type: 'string',
        enum: [
          'structural_transition',
          'strong_transient',
          'energy_lift',
          'energy_drop',
          'quiet_contrast',
        ],
      },
      windowBars: { type: 'integer', enum: [4, 8, 16], default: 8 },
      band: { type: 'string', enum: ['all', 'low', 'mid', 'high'], default: 'all' },
      limit: { type: 'integer', minimum: 1, maximum: 8, default: 3 },
    },
    required: ['kind'],
    additionalProperties: false,
  }),
  annotations: READ_ANNOTATIONS,
});

const compare_ranges = Object.freeze({
  name: 'compare_ranges',
  title: 'Compare ranges',
  description:
    'Measure and compare 2-4 bar ranges: onset density, peak onset ' +
    'strength, per-band energy means and peaks, and the structural families ' +
    'they intersect. The response states numeric differences only; it never ' +
    'assigns musical roles or mood. Read-only.',
  inputSchema: Object.freeze({
    type: 'object',
    properties: {
      ranges: {
        type: 'array',
        minItems: 2,
        maxItems: 4,
        items: {
          type: 'object',
          properties: {
            label: { type: 'string', maxLength: 48 },
            startBar: { type: 'integer', minimum: 1 },
            endBar: { type: 'integer', minimum: 1 },
          },
          required: ['startBar', 'endBar'],
          additionalProperties: false,
        },
      },
    },
    required: ['ranges'],
    additionalProperties: false,
  }),
  annotations: READ_ANNOTATIONS,
});

const focus_range = Object.freeze({
  name: 'focus_range',
  title: 'Focus a range',
  description:
    'Select and display a bar range in the BeatScope timeline with an Agent ' +
    'Focus marker and a stated reason. It moves the eight-bar window to the ' +
    'range and turns off follow-playback so the window stays put. It does ' +
    'NOT seek, play, pause, or loop; use control_playback and set_loop_range ' +
    'for those. The user can clear the focus at any time.',
  inputSchema: Object.freeze({
    type: 'object',
    properties: {
      startBar: { type: 'integer', minimum: 1 },
      endBar: { type: 'integer', minimum: 1 },
      reason: { type: 'string', minLength: 1, maxLength: 120 },
    },
    required: ['startBar', 'endBar', 'reason'],
    additionalProperties: false,
  }),
  annotations: ACTION_ANNOTATIONS,
});

const control_playback = Object.freeze({
  name: 'control_playback',
  title: 'Control playback',
  description:
    'Seek, play, or pause the loaded track. seek and seek_and_play take a ' +
    'time or a bar (with an optional beat), never both, and can pre-roll a ' +
    'number of real beats before the target. preRollBeats walks the stored ' +
    'beat array, so variable-tempo songs stay accurate; the song start ' +
    'clamps to 0. Does not change the Agent Focus or the loop.',
  inputSchema: Object.freeze({
    type: 'object',
    properties: {
      action: { type: 'string', enum: ['play', 'pause', 'seek', 'seek_and_play'] },
      time: { type: 'number', minimum: 0 },
      bar: { type: 'integer', minimum: 1 },
      beat: { type: 'integer', minimum: 1, maximum: 32 },
      preRollBeats: { type: 'integer', minimum: 0, maximum: 16, default: 0 },
    },
    required: ['action'],
    additionalProperties: false,
  }),
  annotations: ACTION_ANNOTATIONS,
});

const set_loop_range = Object.freeze({
  name: 'set_loop_range',
  title: 'Set loop range',
  description:
    'Enable, move, or disable the playback loop. enabled=true requires ' +
    'startBar and endBar (1-based, inclusive); enabled=false stops looping ' +
    'but keeps the range so the user can re-enable it. Does not seek, play, ' +
    'pause, or change the Agent Focus.',
  inputSchema: Object.freeze({
    type: 'object',
    properties: {
      enabled: { type: 'boolean' },
      startBar: { type: 'integer', minimum: 1 },
      endBar: { type: 'integer', minimum: 1 },
    },
    required: ['enabled'],
    additionalProperties: false,
    allOf: [
      {
        if: { properties: { enabled: { const: true } } },
        then: { required: ['startBar', 'endBar'] },
      },
    ],
  }),
  annotations: ACTION_ANNOTATIONS,
});

const DEFINITIONS = Object.freeze([
  get_project_context,
  get_state_at_time,
  get_events,
  find_visual_moments,
  compare_ranges,
  focus_range,
  control_playback,
  set_loop_range,
]);

export const TOOL_DEFINITIONS = DEFINITIONS;

export const ERROR_CODES = Object.freeze([
  'NO_TRACK',
  'INVALID_RANGE',
  'OUT_OF_RANGE',
  'NO_STRUCTURE',
  'NO_CANDIDATES',
  'PLAYBACK_UNAVAILABLE',
  'CANCELED',
  'INTERNAL_ERROR',
]);

/** Stable, user-facing copy for every error code (plan section 6.4). */
export const ERROR_MESSAGES = Object.freeze({
  NO_TRACK: 'Load a BeatScope track before using this tool.',
  INVALID_RANGE: 'The requested range is not usable. Check the bars or times and try again.',
  OUT_OF_RANGE: 'The requested position is outside the loaded track.',
  NO_STRUCTURE: 'This track has no stored structural segments.',
  NO_CANDIDATES: 'No candidate matched this query on the loaded track.',
  PLAYBACK_UNAVAILABLE: 'Playback is not available in this page state.',
  CANCELED: 'The call was canceled before it finished.',
  INTERNAL_ERROR: 'The tool failed unexpectedly. The browser console has details.',
});

/** Which tools are read-only, used by registration checks and tests. */
export const READ_TOOL_NAMES = Object.freeze([
  'get_project_context',
  'get_state_at_time',
  'get_events',
  'find_visual_moments',
  'compare_ranges',
]);

export const ACTION_TOOL_NAMES = Object.freeze([
  'focus_range',
  'control_playback',
  'set_loop_range',
]);
