export function compileComposition(document: import('../../web-src/src/composition/model').Composition, rhythm: any, relevance?: any): {
  diagnostics: { id: string; eligible: number; selected: number; source: string; unavailable: boolean }[];
  eventTimes: { id: string; times: number[] }[];
  at(time: number, reducedMotion?: boolean): Record<string, { scale: number; opacity: number }>;
};
