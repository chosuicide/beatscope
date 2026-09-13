/// <reference types="webmcp-types" />
/**
 * Studio Director v2 — registration lifecycle (v0.12 WebMCP plan section 7).
 *
 * One call per mounted Studio document. The definitions are the frozen
 * literals from contracts.ts; every callback reads the current port through
 * `getPort()` and delegates to the pure kernels, so nothing here owns state
 * and no song name, project id or server text can reach a tool definition.
 */
import { TOOL_DEFINITIONS } from './contracts.js';
import { controlPlayback, exportTimingPackage, renderMovie } from './actions.js';
import { explainMovie } from './movie.js';
import { inspectTiming, responseEvents, studioState } from './timing.js';
import { failure } from './responses.js';
import type { StudioDirectorPort, ToolName, ToolResult } from './types.js';

export type DirectorStatus = 'unsupported' | 'registering' | 'ready' | 'error';

export interface DirectorSession {
  status: DirectorStatus;
  /** Registered tool count, for the visible status chip. */
  count: number;
  detail?: string;
  dispose(): void;
}

function getModelContext(): WebMCP.ModelContext | null {
  if (typeof document === 'undefined') return null;
  const current = document.modelContext;
  if (current && typeof current.registerTool === 'function') return current;
  // Compatibility only, for browsers carrying the earlier draft: the canonical
  // entry point above is what the implementation and the docs use.
  const legacy = (navigator as Navigator & { modelContext?: WebMCP.ModelContext }).modelContext;
  return legacy && typeof legacy.registerTool === 'function' ? legacy : null;
}

type Handler = (port: StudioDirectorPort, input: Record<string, unknown>, signal: AbortSignal) => Promise<ToolResult> | ToolResult;

const HANDLERS: Record<ToolName, Handler> = {
  beatscope_get_studio_state: (port) => studioState(port.snapshot()),
  beatscope_inspect_timing: (port, input) => inspectTiming(port.snapshot(), input),
  beatscope_get_response_events: (port, input) => responseEvents(port.snapshot(), input as never),
  beatscope_explain_movie: (port, input) => explainMovie(port.snapshot(), input),
  beatscope_control_playback: (port, input, signal) => controlPlayback(port, input as never, signal),
  beatscope_render_movie: (port, input, signal) => renderMovie(port, input as never, signal),
  beatscope_export_timing_package: (port) => exportTimingPackage(port),
};

/**
 * Install the seven tools once per document. Reinstalling disposes the
 * previous session first, so Vite hot reload and tests behave like a fresh
 * page. `dispose()` is idempotent and also runs on `pagehide`.
 */
export function installStudioWebMCP(
  getPort: () => StudioDirectorPort,
  onStatus: (status: DirectorStatus, count: number, detail?: string) => void,
): DirectorSession {
  const modelContext = getModelContext();
  if (!modelContext) {
    onStatus('unsupported', 0);
    return { status: 'unsupported', count: 0, dispose() {} };
  }

  const controller = new AbortController();
  let disposed = false;
  const session: DirectorSession = {
    status: 'registering',
    count: 0,
    dispose() {
      if (disposed) return;
      disposed = true;
      controller.abort();
      window.removeEventListener('pagehide', session.dispose);
    },
  };

  const execute = (name: ToolName) => async (
    input: Record<string, unknown>,
    options: { signal: AbortSignal },
  ): Promise<unknown> => {
    if (options?.signal?.aborted) {
      return failure(name, 'canceled', 'The call was cancelled.', 'Retry when the page is ready.');
    }
    try {
      return await HANDLERS[name](getPort(), input ?? {}, options?.signal ?? controller.signal);
    } catch (error) {
      // The kernels already return envelopes; this is the last net so a bug
      // never leaks a stack trace into an Agent's context.
      console.error('beatscope webmcp handler failed', name, error);
      return failure(name, 'internal_error', 'The tool failed.', 'Report this to the user; the studio console has the details.');
    }
  };

  onStatus('registering', 0);
  window.addEventListener('pagehide', session.dispose);
  void (async () => {
    try {
      for (const definition of TOOL_DEFINITIONS) {
        if (controller.signal.aborted) throw new Error('aborted');
        await modelContext.registerTool(
          { ...definition, execute: execute(definition.name) },
          { signal: controller.signal },
        );
        session.count += 1;
      }
      session.status = 'ready';
      onStatus('ready', session.count);
    } catch (error) {
      session.status = 'error';
      session.detail = error instanceof Error ? error.message : String(error);
      onStatus('error', session.count, session.detail);
    }
  })();

  return session;
}
