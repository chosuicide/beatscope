/**
 * Type declarations for the shared runtime the browser ships
 * (beatscope/runtime/runtime.js). Only the surface WebMCP reads is declared:
 * creating a track and asking it for measured onsets. Same convention as
 * beatscope/web/music-grid.d.mts.
 */

export interface RuntimeOnset {
  id: number | string;
  time: number;
  strength?: number;
  bands?: Record<string, number>;
  accent?: boolean;
  [key: string]: unknown;
}

export interface RuntimeResponseSelection {
  /** False when the project carries no response-relevance sidecar. */
  available: boolean;
  semantics: string | null;
  strategy: string;
  total: number;
  selected: number;
  events: (RuntimeOnset & { response_relevance?: number | null })[];
}

export interface RuntimeTrack {
  readonly map: Record<string, unknown>;
  readonly indexes: Record<string, unknown>;
  at(time: number): Record<string, unknown>;
  between(start: number, end: number): RuntimeOnset[];
  responseBetween(start: number, end: number, budget?: number | null): RuntimeResponseSelection;
}

export function createTrack(
  rhythmMap: unknown,
  options?: { responseRelevance?: unknown; bpm?: number | null; origin?: number | null },
): RuntimeTrack;
