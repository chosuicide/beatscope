export interface MusicGrid {
  available: boolean; bars: number; subdivision: number;
  timeAtStep(step: number): number;
  stepAtTime(time: number): number;
  barAtTime(time: number): number | null;
}
export function createMusicGrid(rhythm: unknown): MusicGrid;
