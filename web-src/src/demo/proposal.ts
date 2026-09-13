/**
 * The demo direction proposal shown in frozen frame D. In the full product
 * this arrives from beatscope.propose_direction_patch over WebMCP; Commit 2
 * ships the frame-D example so the review UI is exercised end to end.
 */
import type { Proposal } from '../app/store';

export const demoProposal: Proposal = {
  index: 3,
  intent: 'Reveal strips earlier on high-band onsets; protect the dense passage.',
  scope: 'Pressure, Undertow',
  basis: 'ranked onsets · T1–T2',
  changes: [
    {
      sign: '+',
      scene: 'Pressure',
      system: 'media-slice',
      detail: 'boundary → directional wipe · 240 ms',
    },
    {
      sign: '+',
      scene: 'Undertow',
      system: 'graphic-field',
      detail: 'downbeat → invert region · 120 ms',
    },
    {
      sign: '±',
      scene: 'Pressure',
      system: 'editorial-typography',
      detail: 'max events per bar',
      before: '6',
      after: '4',
    },
  ],
  preview: [
    { scene: 'Pressure', rect: { x: 0, y: 0.58, w: 1, h: 0.3 }, label: 'media-slice · strips earlier' },
    { scene: 'Undertow', rect: { x: 0.18, y: 0.22, w: 0.64, h: 0.52 }, label: 'graphic-field · invert 120 ms' },
  ],
  rawLines: [
    '{',
    '  "schema": "beatscope-direction-patch-1",',
    '  "basis": { "driver": "ranked_onsets", "tiers": ["T1", "T2"] },',
    '  "add": [',
    '    { "scene": "Pressure", "system": "media-slice", "motion": "directional-wipe", "duration_ms": 240 },',
    '    { "scene": "Undertow", "system": "graphic-field", "motion": "invert-region", "duration_ms": 120 }',
    '  ],',
    '  "change": [',
    '    { "scene": "Pressure", "system": "editorial-typography", "field": "max_events_per_bar", "from": 6, "to": 4 }',
    '  ],',
    '  "remove": []',
    '}',
  ],
};
