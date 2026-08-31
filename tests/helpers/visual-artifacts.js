/**
 * Shared v0.8 visual artifact fixtures (plan sections 4 and 6): a minimal
 * valid recipe + timeline pair used by the scene-director and stage tests.
 */

export const ZEROS = Object.freeze({ spread: 0, twist: 0, flow: 0, orbit: 0, void: 0, contrast: 0 });

export const COMPOSITION_A = { spread: 0.14, twist: 0.08, flow: 0.32, orbit: 0.44, void: 0.18, contrast: 0.72 };
export const COMPOSITION_B = { spread: 0.26, twist: 0.1, flow: 0.36, orbit: 0.62, void: 0.16, contrast: 0.74 };

export function makeVisualRecipe(overrides = {}) {
  return {
    schema: 'beatscope-visual-recipe-1',
    recipe_version: '0.8.0',
    project_id: 'a1b2c3d4e5f6',
    source_rhythm_sha256: '0'.repeat(64),
    seed: 'a1b2c3d4e5f6:visual-recipe-1',
    mode: 'structure',
    tokens: {
      palette: { paper: '#f4f1e9', ink: '#171713', accent: '#c65032', warm: '#fff1ce' },
      transition: { lead_beats: 1.0, settle_beats: 1.5, max_lead_seconds: 0.8, max_settle_seconds: 0.9 },
      motion: { max_scene_spread: 0.32, max_scene_twist: 0.28, max_palette_mix: 0.42 },
    },
    families: {
      A: { motif: 'compact-triad', palette_slot: 0, composition: { ...COMPOSITION_A } },
      B: { motif: 'orbital-weave', palette_slot: 1, composition: { ...COMPOSITION_B } },
    },
    diagnostics: { family_count: 2, motif_bank_version: 'motif-bank-1', warnings: [] },
    ...overrides,
  };
}

export function makeVisualTimeline(overrides = {}) {
  return {
    schema: 'beatscope-visual-timeline-1',
    recipe_version: '0.8.0',
    project_id: 'a1b2c3d4e5f6',
    duration: 16,
    mode: 'structure',
    scenes: [
      {
        id: 'scene-001', segment_id: 'segment-001', segment_index: 0, family: 'A', variant: 0,
        label: 'A', start_time: 0, end_time: 8, motif: 'compact-triad', variant_delta: { ...ZEROS },
      },
      {
        id: 'scene-002', segment_id: 'segment-002', segment_index: 1, family: 'B', variant: 0,
        label: 'B', start_time: 8, end_time: 16, motif: 'orbital-weave', variant_delta: { ...ZEROS },
      },
    ],
    transitions: [
      {
        id: 'transition-001', boundary_bar: 5, time: 8, from_scene: 'scene-001', to_scene: 'scene-002',
        treatment: 'phase-turn', strength: 0.8, driver: 'harmony', lead_seconds: 0.5, settle_seconds: 0.75,
      },
    ],
    diagnostics: { scene_count: 2, transition_count: 1, warnings: [] },
    ...overrides,
  };
}
