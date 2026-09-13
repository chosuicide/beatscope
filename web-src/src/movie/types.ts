/**
 * Shape of the rhythm facts the movie screen reads from
 * `GET /api/projects/<id>` (the raw Rhythm IR). Only the fields the UI renders
 * are named here; everything else passes through untouched.
 */
export interface MovieRhythm {
  source: { duration: number };
  tempo?: { global_bpm?: number };
  beats?: { time: number; bar: number; beat?: number; beat_in_bar?: number; downbeat?: boolean }[];
  onsets?: { id?: string | number; time: number; strength: number; bands?: Record<string, number>; accent?: boolean }[];
  patterns?: {
    segments?: {
      family: string;
      display_label?: string;
      start_bar?: number;
      end_bar?: number;
      start_time: number;
      end_time: number;
    }[];
    boundaries?: { time: number; novelty?: number }[];
  };
  grid?: { bars?: number; origin?: number; default_subdivision?: number };
  meter?: { numerator?: number };
  energy?: { fps: number; start: number; bands?: Record<string, number[]> };
  cues?: Record<string, { time: number; onset?: number }[]>;
}
