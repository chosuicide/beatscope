/**
 * Studio Director v2 — types (v0.12 WebMCP plan sections 3, 4, 7).
 *
 * Types only: no runtime values live here, so the contract snapshots stay
 * byte-stable and the registration layer can import them without pulling in
 * any behaviour. The Studio keeps owning product state; these types describe
 * the narrow views the WebMCP adapter is allowed to hand to an Agent.
 */
import type { MovieRhythm } from '../movie/types.js';

/** Stages the visible Studio can actually be in. */
export type StudioStage =
  | 'idle'
  | 'uploading'
  | 'analyzing'
  | 'preview'
  | 'rendering'
  | 'complete'
  | 'failed'
  | 'cancelled';

/** Which media element currently owns the authoritative clock. */
export type StudioClock = 'audio' | 'film' | 'none';

/** Compact facts about the loaded song. Never the whole Rhythm IR. */
export interface StudioTrackFacts {
  display_name: string;
  duration: number;
  global_bpm: number | null;
  bars: number;
  structural_segments: number;
  beat_grid_available: boolean;
  response_relevance_available: boolean;
}

export interface StudioPlaybackState {
  time: number;
  playing: boolean;
  clock: StudioClock;
}

export interface StudioRenderJob {
  id: string;
  state: string;
  progress: number;
  video_ready: boolean;
}

export interface StudioMovieState {
  template: string;
  plan_version: string;
  seed: number | null;
  renderer_available: boolean;
  job: StudioRenderJob | null;
}

export interface StudioCapabilities {
  timing_queries: boolean;
  ranked_events: boolean;
  movie_explanation: boolean;
  playback_actions: boolean;
  rendering: boolean;
  timing_export: boolean;
}

/**
 * The v0.11 ordering sidecar as the browser reads it (the document served by
 * GET /api/projects/<id>/response-relevance). `schema` is load-bearing: the
 * shared runtime only honours a sidecar whose schema it recognises, so a
 * malformed document degrades to "no ranking" instead of half-working.
 * `response_relevance` is an ordering value, never a probability or confidence.
 */
export interface ResponseRelevanceSidecar {
  schema: 'beatscope-response-relevance-1';
  method: string;
  evidence_schema: string;
  semantics: 'bounded-ranking-value-not-probability-or-confidence';
  project_id: string;
  model_sha256: string;
  events: { onset_id: number; response_relevance: number }[];
}

/** One read of the mounted Studio. Copied values only — never live objects. */
export interface StudioDirectorSnapshot {
  stage: StudioStage;
  projectId: string | null;
  name: string;
  rhythm: MovieRhythm | null;
  responseRelevance: ResponseRelevanceSidecar | null;
  seed: number | null;
  movieJob: StudioRenderJob | null;
  /** The studio's own failure text; classified at the boundary, never returned. */
  movieFailureText: string | null;
  currentTime: number;
  duration: number;
  playing: boolean;
  rendererAvailable: boolean;
}

export interface AuditionResult {
  started: boolean;
  start: number;
  end: number;
  requires_user_gesture: boolean;
}

export interface RestoreResult {
  restored: boolean;
  time: number;
  playing: boolean;
}

export interface MovieActionResult {
  action: 'start' | 'cancel';
  job: StudioRenderJob | null;
  seed: number | null;
}

export interface ExportResult {
  filename: string;
  started: boolean;
  requires_user_action: boolean;
}

/** Page-changing kinds only; read-only queries never record activity. */
export type AgentActivityKind = 'playback' | 'render' | 'export';

export interface AgentActivity {
  kind: AgentActivityKind;
  action: string;
  /** Frozen code-table text, never echoed prompt or project content. */
  label: string;
  restorable: boolean;
}

/**
 * The adapter boundary (plan section 3.3). Registration happens once; every
 * callback reads the current port through a ref, so a song change can never
 * let an older call mutate the new session.
 */
export interface StudioDirectorPort {
  snapshot(): StudioDirectorSnapshot;
  seek(time: number): void;
  play(): Promise<{ playing: boolean; requiresUserGesture: boolean }>;
  pause(): void;
  audition(start: number, end: number, autoplay: boolean, signal: AbortSignal): Promise<AuditionResult>;
  restoreAudition(): Promise<RestoreResult>;
  render(action: 'start' | 'cancel', seed?: number, signal?: AbortSignal): Promise<MovieActionResult>;
  exportTimingPackage(): Promise<ExportResult>;
  recordAgentAction(entry: AgentActivity): void;
}

export const ERROR_CODES = [
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
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

export type ToolName =
  | 'beatscope_get_studio_state'
  | 'beatscope_inspect_timing'
  | 'beatscope_get_response_events'
  | 'beatscope_explain_movie'
  | 'beatscope_control_playback'
  | 'beatscope_render_movie'
  | 'beatscope_export_timing_package';

export type ToolKind = 'read' | 'action';

export interface ToolDefinition {
  name: ToolName;
  title: string;
  description: string;
  kind: ToolKind;
  inputSchema: {
    type: 'object';
    properties: Record<string, unknown>;
    required?: string[];
    additionalProperties: false;
  };
  annotations: WebMCP.ToolAnnotations;
}

export interface ToolSuccess<T = unknown> {
  ok: true;
  tool: ToolName;
  summary: string;
  data: T;
}

export interface ToolFailure {
  ok: false;
  tool: ToolName;
  error: {
    code: ErrorCode;
    message: string;
    next_action: string;
  };
}

export type ToolResult<T = unknown> = ToolSuccess<T> | ToolFailure;
