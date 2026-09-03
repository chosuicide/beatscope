/**
 * Explicit snapshot recorder for the frozen WebMCP tool contracts
 * (v0.10 plan section 18.6).
 *
 * The snapshots in tests/snapshots/webmcp/ freeze the exact bytes of the
 * eight tool definitions and five representative read-tool responses.
 * Normal test runs only read them; recording requires the explicit
 * --accept flag:
 *
 *     node tests/record_webmcp_snapshots.mjs --accept
 *
 * Never hand-edit the snapshot files or delete fields to pass a test.
 */
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';

import { TOOL_DEFINITIONS } from '../beatscope/web/webmcp/schemas.js';
import {
  projectContext,
  stateAtTime,
  eventsWindow,
  findVisualMoments,
  compareRanges,
} from '../beatscope/web/webmcp/queries.js';
import { trackForProject } from '../beatscope/runtime/runtime.js';
import { makeStructuredProject, loadProject, state } from './webmcp_fixtures.mjs';

const accept = process.argv.includes('--accept');
if (!accept) {
  console.error('Refusing to record without --accept (plan section 18.6).');
  console.error('Usage: node tests/record_webmcp_snapshots.mjs --accept');
  process.exit(2);
}

const MOMENT_KINDS = [
  'structural_transition',
  'strong_transient',
  'energy_lift',
  'energy_drop',
  'quiet_contrast',
];
const INCLUDES = ['beats', 'onsets', 'segments', 'boundaries', 'cues'];

function pageFor(project) {
  loadProject(project);
  return {
    project: state.project,
    track: trackForProject(state.project),
    playbackTime: 0,
    isPlaying: false,
    loop: false,
    loopSelection: null,
    subdivision: 16,
    adjustments: state.adjustments,
  };
}

const page = pageFor(makeStructuredProject());

const snapshots = {
  'tool-definitions': TOOL_DEFINITIONS.map((definition) => ({
    name: definition.name,
    title: definition.title,
    description: definition.description,
    inputSchema: definition.inputSchema,
    annotations: definition.annotations,
  })),
  'project-context': projectContext(page),
  'state-at-boundary': {
    before: stateAtTime(page, { time: 31.9 }),
    at: stateAtTime(page, { time: 32 }),
    after: stateAtTime(page, { time: 32.1 }),
  },
  'events-window': eventsWindow(page, { startBar: 17, endBar: 24, include: INCLUDES, limit: 200 }),
  'visual-moments': Object.fromEntries(
    MOMENT_KINDS.map((kind) => [kind, findVisualMoments(page, { kind })]),
  ),
  'range-comparison': compareRanges(page, {
    ranges: [
      { label: 'First A', startBar: 1, endBar: 8 },
      { label: 'A-prime', startBar: 9, endBar: 16 },
    ],
  }),
};

for (const [name, payload] of Object.entries(snapshots)) {
  const target = new URL(`./snapshots/webmcp/${name}.json`, import.meta.url);
  writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`, 'utf-8');
  console.log(`recorded ${name}.json`);
}

assert.ok(snapshots['tool-definitions'].length === 8, 'expected exactly eight tool definitions');
console.log('done');
