/**
 * Director registration lifecycle (v0.10 plan section 6).
 *
 * installWebMCP detects document.modelContext, registers the eight frozen
 * tools behind a single AbortController, and hands back {status, dispose}.
 * Every execute re-reads getState() so a project switch never needs a
 * re-register, and a disposed session aborts every registration signal.
 * Registration or tool failures degrade the status text only; the player
 * keeps working without WebMCP.
 */

import { TOOL_DEFINITIONS, ERROR_MESSAGES } from './schemas.js';
import { WebMcpError, errorResult } from './responses.js';
import { trackForProject } from '../../runtime/runtime.js';
import {
  projectContext,
  stateAtTime,
  eventsWindow,
  findVisualMoments,
  compareRanges,
} from './queries.js';
import {
  focusRange,
  controlPlayback,
  setLoopRange,
} from './actions.js';

/** A fresh snapshot of the page truth for one tool call (plan section 3.1). */
function buildPage(state) {
  return {
    project: state.project,
    track: trackForProject(state.project),
    playbackTime: state.playbackTime,
    isPlaying: state.isPlaying,
    loop: state.loop,
    loopSelection: state.loopSelection,
    subdivision: state.subdivision,
    adjustments: state.adjustments,
  };
}

function makeHandlers(deps) {
  return {
    get_project_context: (input, page) => projectContext(page),
    get_state_at_time: (input, page) => stateAtTime(page, input, deps.sceneAt || null),
    get_events: (input, page) => eventsWindow(page, input),
    find_visual_moments: (input, page) => findVisualMoments(page, input),
    compare_ranges: (input, page) => compareRanges(page, input),
    focus_range: (input) => focusRange(deps, input),
    control_playback: (input) => controlPlayback(deps, input),
    set_loop_range: (input) => setLoopRange(deps, input),
  };
}

export function installWebMCP(deps = {}) {
  const modelContext = typeof document !== 'undefined' ? document.modelContext : null;
  if (!modelContext || typeof modelContext.registerTool !== 'function') {
    return { status: 'unsupported', dispose() {} };
  }
  if (typeof deps.onStatus === 'function') deps.onStatus('registering');

  // Re-installing (hot reload, tests) must not leak the previous session:
  // abort the old signals first so the host frees the tool names.
  if (currentSession) currentSession.dispose();

  const controller = new AbortController();
  const handlers = makeHandlers(deps);
  const registrationResults = [];

  const executeTool = (definition) => async (input, executionInfo = {}) => {
    const signal = executionInfo?.signal ?? null;
    if (signal && signal.aborted) {
      throw new DOMException('Canceled', 'AbortError');
    }
    try {
      const state = deps.getState();
      if (!state.project) return errorResult('NO_TRACK', ERROR_MESSAGES.NO_TRACK);
      const page = buildPage(state);
      const result = await handlers[definition.name](input || {}, page);
      return result;
    } catch (error) {
      if (error instanceof WebMcpError) {
        return errorResult(error.code, error.message);
      }
      // Real details stay in the browser console; the tool response stays
      // stable and leak-free (plan section 6.4).
      if (typeof console !== 'undefined' && typeof console.error === 'function') {
        console.error(`BeatScope Director: ${definition.name} failed`, error);
      }
      return errorResult('INTERNAL_ERROR', ERROR_MESSAGES.INTERNAL_ERROR);
    }
  };

  for (const definition of TOOL_DEFINITIONS) {
    const registration = modelContext.registerTool(
      {
        name: definition.name,
        title: definition.title,
        description: definition.description,
        inputSchema: definition.inputSchema,
        annotations: definition.annotations,
        execute: executeTool(definition),
      },
      { signal: controller.signal },
    );
    registrationResults.push(Promise.resolve(registration));
  }

  Promise.all(registrationResults).then(
    () => { if (typeof deps.onStatus === 'function') deps.onStatus('ready'); },
    () => { if (typeof deps.onStatus === 'function') deps.onStatus('error'); },
  );

  const dispose = () => {
    controller.abort();
    if (typeof window !== 'undefined' && typeof window.removeEventListener === 'function') {
      window.removeEventListener('pagehide', dispose);
    }
    if (currentSession === session) currentSession = null;
  };
  const session = { dispose };
  currentSession = session;

  if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
    window.addEventListener('pagehide', dispose, { once: true });
  }

  return { status: 'ready', dispose };
}

let currentSession = null;

export function disposeWebMCP() {
  if (currentSession) currentSession.dispose();
}

/** Test/debug visibility: whether a session is currently registered. */
export function webMCPSessionActive() {
  return currentSession !== null;
}
