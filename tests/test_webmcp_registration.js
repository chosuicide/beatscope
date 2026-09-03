/**
 * Director registration lifecycle tests (v0.10 plan sections 6, 18.3).
 *
 * A mock document.modelContext stands in for the browser host: it records
 * every registration and models the host rule that aborting a registration
 * signal unregisters that tool. Node has no `document`, so the unsupported
 * case runs before the mock is installed.
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import {
  installWebMCP,
  disposeWebMCP,
  webMCPSessionActive,
} from '../beatscope/web/webmcp/register.js';
import {
  TOOL_NAMES,
  READ_TOOL_NAMES,
  ACTION_TOOL_NAMES,
  ERROR_MESSAGES,
} from '../beatscope/web/webmcp/schemas.js';
import {
  makeStructuredProject,
  makeQuietProject,
  loadProject,
  makeFakePlayer,
  state,
} from './webmcp_fixtures.mjs';

class MockModelContext {
  constructor() {
    this.tools = new Map();
    this.aborted = [];
  }

  registerTool(definition, options) {
    if (this.tools.has(definition.name)) {
      throw new Error(`duplicate registration: ${definition.name}`);
    }
    const entry = { definition, options };
    // Host rule: aborting the registration signal unregisters the tool.
    options.signal.addEventListener('abort', () => {
      this.aborted.push(definition.name);
      if (this.tools.get(definition.name) === entry) this.tools.delete(definition.name);
    });
    this.tools.set(definition.name, entry);
    return { addEventListener() {} };
  }
}

const originalDocument = globalThis.document;
const originalConsoleError = console.error;

// --- 1. no modelContext support: no exception, no session --------------------
{
  const outcome = installWebMCP({ getState: () => state });
  assert.equal(outcome.status, 'unsupported');
  assert.equal(typeof outcome.dispose, 'function');
  outcome.dispose();
  assert.equal(webMCPSessionActive(), false);
}

// --- 2-4. exactly 8 unique tools, frozen definitions, correct annotations ----
const mock = new MockModelContext();
globalThis.document = { modelContext: mock };
const player = makeFakePlayer();
const statuses = [];
const session = installWebMCP({
  ...player.deps,
  getState: () => state,
  sceneAt: null,
  onStatus: (status) => statuses.push(status),
});
{
  assert.equal(session.status, 'ready');
  assert.equal(webMCPSessionActive(), true);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(statuses, ['registering', 'ready']);
  assert.equal(mock.tools.size, 8);
  assert.deepEqual([...mock.tools.keys()], [...TOOL_NAMES]);
}

{
  const frozen = JSON.parse(
    await readFile(new URL('./snapshots/webmcp/tool-definitions.json', import.meta.url), 'utf-8'),
  );
  assert.equal(frozen.length, 8);
  for (const [index, name] of TOOL_NAMES.entries()) {
    const definition = mock.tools.get(name).definition;
    assert.equal(definition.name, frozen[index].name, name);
    assert.equal(definition.title, frozen[index].title, name);
    assert.equal(definition.description, frozen[index].description, name);
    assert.deepEqual(definition.inputSchema, frozen[index].inputSchema, name);
    assert.deepEqual(definition.annotations, frozen[index].annotations, name);
    assert.equal(typeof definition.execute, 'function', name);
  }
}

{
  for (const name of READ_TOOL_NAMES) {
    assert.equal(mock.tools.get(name).definition.annotations.readOnlyHint, true, name);
  }
  for (const name of ACTION_TOOL_NAMES) {
    assert.equal(mock.tools.get(name).definition.annotations.readOnlyHint, false, name);
  }
}

// --- 5. execute reads the live state, not the install-time state -------------
{
  loadProject(makeStructuredProject());
  const contextA = await mock.tools.get('get_project_context').definition.execute({}, {});
  assert.equal(contextA.track.bars, 32);
  loadProject(makeQuietProject());
  const contextB = await mock.tools.get('get_project_context').definition.execute({}, {});
  assert.equal(contextB.track.bars, 4);
  assert.equal(state.agentActions.length, 0, 'read-only tools must not mutate the Agent ledger');
}

// --- 6. dispose aborts every registration signal ------------------------------
{
  session.dispose();
  assert.deepEqual([...mock.aborted].sort(), [...TOOL_NAMES].sort());
  assert.equal(mock.tools.size, 0);
  assert.equal(webMCPSessionActive(), false);
}

// --- 7. re-installing frees the old names before claiming them ----------------
{
  const second = installWebMCP({ ...player.deps, getState: () => state, sceneAt: null });
  assert.equal(second.status, 'ready');
  assert.equal(mock.tools.size, 8);
  assert.equal(webMCPSessionActive(), true);
  const third = installWebMCP({ ...player.deps, getState: () => state, sceneAt: null });
  assert.equal(third.status, 'ready');
  assert.equal(mock.tools.size, 8); // never 16: the second session was freed first
  assert.equal(mock.aborted.length, 16); // both earlier sessions' tools aborted
  assert.equal(webMCPSessionActive(), true);
}

// --- 8. handler failures become stable, leak-free errors ----------------------
{
  loadProject(makeStructuredProject());
  const consoleErrors = [];
  console.error = (...args) => consoleErrors.push(args);
  try {
    const failing = installWebMCP({
      getState: () => {
        throw new Error('boom');
      },
      hasAudio: () => true,
      seek: () => {},
      play: async () => true,
      pause: () => {},
      readAudioTime: () => 0,
      setFollowPlayback: () => {},
      scrollPlayerIntoView: () => {},
      sceneAt: null,
    });
    assert.equal(failing.status, 'ready'); // registration succeeds; calls fail
    const result = await mock.tools.get('get_project_context').definition.execute({}, {});
    assert.equal(result.ok, false);
    assert.equal(result.error.code, 'INTERNAL_ERROR');
    assert.equal(result.error.message, ERROR_MESSAGES.INTERNAL_ERROR);
    assert.ok(!JSON.stringify(result).includes('boom'));
    assert.equal(consoleErrors.length, 1);
    // A healthy session turns expected validation errors into actionable,
    // quiet error results (no console noise).
    installWebMCP({ ...player.deps, getState: () => state, sceneAt: null });
    const invalid = await mock.tools.get('find_visual_moments').definition.execute({ kind: 'nope' }, {});
    assert.equal(invalid.ok, false);
    assert.equal(invalid.error.code, 'INVALID_RANGE');
    assert.equal(consoleErrors.length, 1);
  } finally {
    console.error = originalConsoleError;
  }
}

// --- 9. a canceled call runs no action ----------------------------------------
{
  loadProject(makeStructuredProject());
  const freshPlayer = makeFakePlayer();
  installWebMCP({ ...freshPlayer.deps, getState: () => state, sceneAt: null });
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    () => mock.tools.get('control_playback').definition.execute({ action: 'play' }, { signal: controller.signal }),
    (error) => error instanceof DOMException && error.name === 'AbortError',
  );
  assert.deepEqual(freshPlayer.calls, []);
  assert.equal(state.agentActions.filter((entry) => entry.kind === 'control_playback').length, 0);
}

// --- 10. all eight tools execute and return JSON-safe values ------------------
{
  loadProject(makeStructuredProject());
  const freshPlayer = makeFakePlayer();
  installWebMCP({ ...freshPlayer.deps, getState: () => state, sceneAt: null });
  const inputs = {
    get_project_context: {},
    get_state_at_time: { time: 4 },
    get_events: { startBar: 1, endBar: 8 },
    find_visual_moments: { kind: 'structural_transition' },
    compare_ranges: { ranges: [{ startBar: 1, endBar: 4 }, { startBar: 5, endBar: 8 }] },
    focus_range: { startBar: 1, endBar: 8, reason: 'intro' },
    control_playback: { action: 'play' },
    set_loop_range: { enabled: false },
  };
  for (const [name, input] of Object.entries(inputs)) {
    const result = await mock.tools.get(name).definition.execute(input, {});
    const text = JSON.stringify(result);
    assert.deepEqual(JSON.parse(text), result, `${name} must round-trip through JSON`);
  }
}

disposeWebMCP();
assert.equal(mock.tools.size, 0);
assert.equal(webMCPSessionActive(), false);
if (originalDocument === undefined) delete globalThis.document;
else globalThis.document = originalDocument;
