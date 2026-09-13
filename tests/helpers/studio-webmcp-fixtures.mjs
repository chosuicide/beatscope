/**
 * Fixtures for the Studio Director v2 query tests.
 *
 * The rhythm documents are the repository's existing frozen Rhythm IR
 * fixtures. The ranking sidecar is synthesized deterministically (a
 * multiplicative hash of the onset id) because the real v0.11 ranking sidecar
 * is licensed data — the tests then prove the explanation matches a direct
 * `makePlan` call with that same sidecar, which is the property that matters.
 */
import { readFileSync } from 'node:fs';

const FIXTURE_DIR = new URL('../fixtures/', import.meta.url);

export function loadRhythmFixture(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, FIXTURE_DIR), 'utf8'));
}

/** Deterministic 0..1 ordering values; never random, never time-based. */
export function syntheticRelevance(rhythm, projectId = 'studio-fixture') {
  const events = (rhythm.onsets ?? []).map((onset) => {
    const id = Number(onset.id) || 0;
    return { onset_id: id, response_relevance: ((id * 2654435761) % 1000) / 1000 };
  });
  return {
    schema: 'beatscope-response-relevance-1',
    method: 'synthetic-studio-fixture',
    evidence_schema: 'beatscope-event-evidence-1',
    semantics: 'bounded-ranking-value-not-probability-or-confidence',
    project_id: projectId,
    model_sha256: '0'.repeat(64),
    events,
  };
}

/** A snapshot shaped exactly like the port's, for the pure query kernels. */
export function makeSnapshot(rhythm, overrides = {}) {
  return {
    stage: 'preview',
    projectId: rhythm === null ? null : '0a1b2c3d4e5f',
    name: 'fixture.wav',
    rhythm,
    responseRelevance: rhythm === null ? null : syntheticRelevance(rhythm),
    seed: 7,
    movieJob: null,
    movieFailureText: null,
    currentTime: 0,
    duration: rhythm === null ? 0 : Number(rhythm.source?.duration ?? 0),
    playing: false,
    rendererAvailable: true,
    ...overrides,
  };
}

/** The three shapes the plan calls out: structured, plain, variable tempo. */
export const FIXTURES = {
  structured: 'structure/aba.rhythm.json',
  plain: 'runtime/characterization-project.json',
  variableTempo: 'runtime/variable-tempo-project.json',
};

export function downbeatsOf(rhythm) {
  return (rhythm.beats ?? [])
    .filter((beat) => beat.beat_in_bar === 1 || beat.downbeat === true)
    .map((beat) => beat.time)
    .sort((left, right) => left - right);
}
