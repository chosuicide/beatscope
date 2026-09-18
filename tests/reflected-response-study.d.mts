export const STUDY_PRESET: string;
export interface ReflectedState { time: number; pulse: number; phase: number; low: number; mid: number; high: number; speed: number; x: number; y: number; angle: number; frequency: number; persistence: number }
export function compileReflectedResponse(rhythm: any, relevance: any, options?: { gap?: number; release?: number; amount?: number }): { diagnostics: { selected: number; source: string }; times: number[]; at(time: number, enabled?: boolean): ReflectedState };
export function createReflectedPreset(original: any, getState: () => ReflectedState): any;
