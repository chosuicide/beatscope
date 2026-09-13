/**
 * Type declarations for the deterministic movie plan
 * (beatscope/web/mv-plan.mjs) — the same function the preview and the renderer
 * call. Only what WebMCP explains is declared. Same convention as
 * beatscope/web/music-grid.d.mts.
 */

export type ShotEntryKind = 'start' | 'structure' | 'onset';

export interface MovieShot {
  start: number;
  end: number;
  /** Onset id, structure segment id, or the literal 'start'. */
  eventId: number | string;
  kind: ShotEntryKind;
  family: string;
  world: number;
}

export interface MoviePlan {
  version: string;
  duration: number;
  fps: number;
  size: number;
  seed: number;
  shots: MovieShot[];
  details: unknown[];
  policy: Readonly<Record<string, number>>;
}

/** Throws when the audio length is unusable or no ranking is available. */
export function makePlan(map: unknown, response: unknown, seed?: number): MoviePlan;

export function worldsFor(family: unknown, seed?: number): number[];

export function selectResponses(events: unknown[]): unknown[];

export const POLICY: Readonly<Record<string, number>>;
export const WORLD_SETS: Readonly<Record<string, number[]>>;
