/**
 * Record the Studio Director v2 contract snapshots (v0.12 WebMCP plan §11.1).
 *
 *   node tests/record_studio_webmcp_snapshots.mjs
 *
 * Snapshots are canonical JSON bytes: code-point-sorted keys, six-decimal
 * numbers, LF newline. Re-record only when a frozen contract or query changes
 * on purpose, and say why in the commit message.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { loadStudioWebmcp, loadStudioWebmcpResponses, loadStudioWebmcpModule } from './helpers/studio-webmcp.mjs';
import { FIXTURES, loadRhythmFixture, makeSnapshot } from './helpers/studio-webmcp-fixtures.mjs';

const OUT_DIR = new URL('./snapshots/studio-webmcp/', import.meta.url);
mkdirSync(OUT_DIR, { recursive: true });

const { TOOL_DEFINITIONS, ERROR_CODE_SET, LIMITS, RETIRED_TOKENS, FORBIDDEN_INPUT_KEYS } =
  await loadStudioWebmcp();
const { canonicalJson } = await loadStudioWebmcpResponses();
const timing = await loadStudioWebmcpModule('timing');
const movie = await loadStudioWebmcpModule('movie');

const plain = loadRhythmFixture(FIXTURES.plain);
const structured = loadRhythmFixture(FIXTURES.structured);

const snapshots = {
  'tool-definitions': {
    tools: TOOL_DEFINITIONS,
    error_codes: ERROR_CODE_SET,
    limits: LIMITS,
    retired_tokens: RETIRED_TOKENS,
    forbidden_input_keys: FORBIDDEN_INPUT_KEYS,
  },
  'idle-state': timing.studioState(makeSnapshot(null, { stage: 'idle', name: '', duration: 0 })),
  'loaded-state': timing.studioState(makeSnapshot(structured, { stage: 'complete', currentTime: 38.6 })),
  'timing-window': timing.inspectTiming(makeSnapshot(plain), {
    start_time: 1, end_time: 3, include: ['beats', 'onsets', 'cues'], limit: 50,
  }),
  'ranked-events': timing.responseEvents(makeSnapshot(structured), {
    start_time: 0, end_time: 48, budget: 6,
  }),
  'movie-explanation': movie.explainMovie(makeSnapshot(structured), { time: 20, context: 1 }),
};

for (const [name, payload] of Object.entries(snapshots)) {
  const bytes = canonicalJson(payload);
  const target = new URL(`${name}.json`, OUT_DIR);
  writeFileSync(target, bytes, 'utf8');
  process.stdout.write(bytes);
  console.error(`recorded ${name} -> ${fileURLToPath(target)}`);
}
