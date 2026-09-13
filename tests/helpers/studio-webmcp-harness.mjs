/**
 * Test-only fixtures for the Studio Director v2 surface.
 *
 * Two things the later rounds need, kept out of production code:
 *
 * 1. `createModelContextHarness()` — a minimal `document.modelContext` that
 *    records registrations and runs the real callbacks, so registration and
 *    cancellation can be tested without native WebMCP support. It is never
 *    bundled into the app (plan section 11.5).
 * 2. `createFakePort()` — a recording `StudioDirectorPort`, so action tests
 *    can assert call counts and that invalid input never reaches the page.
 */

export function createModelContextHarness() {
  const registered = [];
  const signals = new Set();
  const abortedSignals = new Set();
  const modelContext = {
    registerTool(tool, options = {}) {
      const record = { tool, options };
      registered.push(record);
      const signal = options.signal;
      if (signal) {
        signals.add(signal);
        signal.addEventListener('abort', () => { abortedSignals.add(signal); }, { once: true });
      }
      return Promise.resolve();
    },
    getTools() {
      return Promise.resolve(registered.map((record) => ({ name: record.tool.name })));
    },
  };
  return {
    modelContext,
    registered,
    /** Distinct signals aborted — one shared controller counts once. */
    abortCount: () => abortedSignals.size,
    names: () => registered.filter((record) => !record.options.signal?.aborted).map((record) => record.tool.name),
    /** Invoke one registered tool exactly as the browser would. */
    async execute(name, input = {}, { signal } = {}) {
      const record = registered.find(
        (entry) => entry.tool.name === name && !entry.options.signal?.aborted,
      );
      if (!record) throw new Error(`tool not registered: ${name}`);
      const controller = signal === undefined ? new AbortController() : null;
      return record.tool.execute(input, { signal: signal ?? controller.signal });
    },
  };
}

export function createFakePort(overrides = {}) {
  const calls = [];
  const snapshot = {
    stage: 'preview',
    projectId: '0a1b2c3d4e5f',
    name: 'fixture.wav',
    rhythm: null,
    responseRelevance: null,
    seed: 1,
    movieJob: null,
    currentTime: 0,
    duration: 8,
    playing: false,
    rendererAvailable: true,
    ...(overrides.snapshot ?? {}),
  };
  const record = (name, payload) => calls.push({ name, payload });
  const base = {
    seek: (time) => record('seek', { time }),
    play: async () => { record('play'); return { playing: true, requiresUserGesture: false }; },
    pause: () => record('pause'),
    audition: async (start, end, autoplay) => {
      record('audition', { start, end, autoplay });
      return { started: true, start, end, requires_user_gesture: false };
    },
    restoreAudition: async () => { record('restoreAudition'); return { restored: true, time: 0, playing: false }; },
    render: async (action, seed) => {
      record('render', { action, seed });
      return { action, job: { id: 'job-1', state: 'running', progress: 0, video_ready: false }, seed: seed ?? snapshot.seed };
    },
    exportTimingPackage: async () => {
      record('exportTimingPackage');
      return { filename: 'fixture.beatscope.zip', started: true, requires_user_action: false };
    },
    recordAgentAction: (entry) => record('recordAgentAction', entry),
  };
  // Overrides keep the recording behaviour, so action tests can assert that a
  // rejected call still reached (or never reached) the page exactly once.
  const wrapped = {};
  for (const [key, value] of Object.entries(base)) {
    wrapped[key] = typeof overrides[key] === 'function' && key !== 'snapshot'
      ? (...args) => { record(key, args.length === 1 ? args[0] : args); return overrides[key](...args); }
      : value;
  }
  return { calls, snapshot: () => ({ ...snapshot, ...(overrides.snapshotNow ? overrides.snapshotNow() : {}) }), ...wrapped };
}
