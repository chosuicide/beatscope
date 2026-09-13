/**
 * Studio Director v2 registration tests (v0.12 WebMCP plan §11.4).
 *
 * The module is imported once and driven against fake globals, so the real
 * detection order, the single shared signal and the disposal rules are all
 * exercised as written.
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { loadStudioWebmcpModule } from './helpers/studio-webmcp.mjs';
import { createModelContextHarness } from './helpers/studio-webmcp-harness.mjs';

const { installStudioWebMCP } = await loadStudioWebmcpModule('register');
const { TOOL_NAMES } = await loadStudioWebmcpModule('contracts');

const GLOBALS = ['document', 'window', 'navigator'];

/* Node 24 defines navigator as a getter, so the fakes are installed with
   defineProperty and the original descriptors restored afterwards. */
function withGlobals({ documentContext, navigatorContext }, run) {
  const listeners = new Map();
  const previous = Object.fromEntries(GLOBALS.map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  const define = (name, value) => Object.defineProperty(globalThis, name, { value, configurable: true, writable: true, enumerable: true });
  define('document', documentContext === undefined ? {} : { modelContext: documentContext });
  define('navigator', navigatorContext === undefined ? {} : { modelContext: navigatorContext });
  define('window', {
    addEventListener: (type, handler) => listeners.set(type, handler),
    removeEventListener: (type, handler) => { if (listeners.get(type) === handler) listeners.delete(type); },
  });
  return Promise.resolve(run({ listeners })).finally(() => {
    for (const name of GLOBALS) {
      const descriptor = previous[name];
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  });
}

const fakePort = { snapshot: () => ({ stage: 'idle' }) };

test('seven tools register exactly once through document.modelContext', async () => {
  const harness = createModelContextHarness();
  const statuses = [];
  await withGlobals({ documentContext: harness.modelContext }, async () => {
    const session = installStudioWebMCP(() => fakePort, (status, count) => statuses.push([status, count]));
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.deepEqual(harness.names(), [...TOOL_NAMES], 'all seven, in catalog order');
    assert.equal(session.status, 'ready');
    assert.equal(session.count, 7);
    assert.deepEqual(statuses, [['registering', 0], ['ready', 7]]);
    session.dispose();
  });
});

test('every registration shares one signal, and disposal aborts it exactly once', async () => {
  const harness = createModelContextHarness();
  await withGlobals({ documentContext: harness.modelContext }, async () => {
    const session = installStudioWebMCP(() => fakePort, () => {});
    await new Promise((resolve) => setTimeout(resolve, 0));
    const signals = new Set(harness.registered.map((record) => record.options.signal));
    assert.equal(signals.size, 1, 'one AbortController for all seven');
    session.dispose();
    session.dispose();
    assert.equal(harness.abortCount(), 1, 'idempotent');
    assert.deepEqual(harness.names(), []);
  });
});

test('reinstalling disposes the previous session first', async () => {
  const first = createModelContextHarness();
  const second = createModelContextHarness();
  await withGlobals({ documentContext: first.modelContext }, async () => {
    const session = installStudioWebMCP(() => fakePort, () => {});
    await new Promise((resolve) => setTimeout(resolve, 0));
    await withGlobals({ documentContext: second.modelContext }, async () => {
      session.dispose();
      const next = installStudioWebMCP(() => fakePort, () => {});
      await new Promise((resolve) => setTimeout(resolve, 0));
      assert.equal(first.abortCount(), 1);
      assert.equal(second.names().length, 7);
      next.dispose();
    });
  });
});

test('document.modelContext wins, and the navigator path is only a fallback', async () => {
  const documentHarness = createModelContextHarness();
  const navigatorHarness = createModelContextHarness();
  await withGlobals({ documentContext: documentHarness.modelContext, navigatorContext: navigatorHarness.modelContext }, async () => {
    const session = installStudioWebMCP(() => fakePort, () => {});
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(documentHarness.names().length, 7);
    assert.equal(navigatorHarness.names().length, 0, 'the compat shim stays silent');
    session.dispose();
  });

  const only = createModelContextHarness();
  await withGlobals({ documentContext: undefined, navigatorContext: only.modelContext }, async () => {
    const session = installStudioWebMCP(() => fakePort, () => {});
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(only.names().length, 7);
    session.dispose();
  });
});

test('an unsupported browser changes nothing and disposes safely', async () => {
  const statuses = [];
  await withGlobals({}, async () => {
    const session = installStudioWebMCP(() => fakePort, (status, count) => statuses.push([status, count]));
    assert.equal(session.status, 'unsupported');
    assert.equal(session.count, 0);
    assert.deepEqual(statuses, [['unsupported', 0]]);
    session.dispose();
    assert.equal(session.status, 'unsupported');
  });
});

test('callbacks read the current port, so a song change needs no re-registration', async () => {
  const harness = createModelContextHarness();
  await withGlobals({ documentContext: harness.modelContext }, async () => {
    let state = { stage: 'idle' };
    const session = installStudioWebMCP(() => ({ snapshot: () => state }), () => {});
    await new Promise((resolve) => setTimeout(resolve, 0));

    const idle = await harness.execute('beatscope_get_studio_state');
    assert.equal(idle.ok, true);
    assert.equal(idle.data.stage, 'idle');
    assert.equal(idle.data.track, null);

    state = { stage: 'preview' };
    const loaded = await harness.execute('beatscope_get_studio_state');
    assert.equal(loaded.data.stage, 'preview');
    assert.equal(harness.registered.length, 7, 'still seven registrations');
    session.dispose();
  });
});

test('a rejected registration reports error without throwing, and cancellation is an envelope', async () => {
  let calls = 0;
  const failing = {
    registerTool: () => {
      calls += 1;
      return calls === 3 ? Promise.reject(new Error('registration refused')) : Promise.resolve();
    },
  };
  const statuses = [];
  await withGlobals({ documentContext: failing }, async () => {
    const session = installStudioWebMCP(() => fakePort, (status, count, detail) => statuses.push([status, count, detail]));
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(session.status, 'error');
    assert.equal(session.count, 2);
    assert.deepEqual(statuses.at(-1), ['error', 2, 'registration refused']);
    session.dispose();
  });

  const harness = createModelContextHarness();
  await withGlobals({ documentContext: harness.modelContext }, async () => {
    const session = installStudioWebMCP(() => ({ snapshot: () => ({ stage: 'idle' }) }), () => {});
    await new Promise((resolve) => setTimeout(resolve, 0));
    const controller = new AbortController();
    controller.abort();
    const cancelled = await harness.execute('beatscope_render_movie', { action: 'start' }, { signal: controller.signal });
    assert.equal(cancelled.ok, false);
    assert.equal(cancelled.error.code, 'canceled');
    session.dispose();
  });
});

test('pagehide disposes the session', async () => {
  const harness = createModelContextHarness();
  await withGlobals({ documentContext: harness.modelContext }, async ({ listeners }) => {
    const session = installStudioWebMCP(() => fakePort, () => {});
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.ok(listeners.has('pagehide'));
    listeners.get('pagehide')();
    assert.equal(harness.abortCount(), 1);
    assert.equal(harness.names().length, 0);
    assert.equal(listeners.has('pagehide'), false);
    session.dispose();
    assert.equal(harness.abortCount(), 1, 'dispose after pagehide stays idempotent');
  });
});
