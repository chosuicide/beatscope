/**
 * WebMCP performance benchmark (v0.10 plan sections 18.7, 19).
 *
 * Every Director query must stay interactive-scale on a ten-minute
 * project. The baseline file freezes machine-independent hard thresholds;
 * this test fails when an observed batch exceeds its threshold. Observed
 * values are informational (they vary by machine) and are rewritten only
 * by the explicit flag:
 *
 *     node tests/test_webmcp_benchmark.js --accept-baseline
 */
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';

import {
  projectContext,
  stateAtTime,
  eventsWindow,
  findVisualMoments,
  compareRanges,
} from '../beatscope/web/webmcp/queries.js';
import { focusRange, controlPlayback, setLoopRange, undoLastAgentAction } from '../beatscope/web/webmcp/actions.js';
import { installWebMCP, disposeWebMCP } from '../beatscope/web/webmcp/register.js';
import { trackForProject } from '../beatscope/runtime/runtime.js';
import { makeStructuredProject, makeFakePlayer, loadProject, state, BPM } from './webmcp_fixtures.mjs';

const BASELINE_URL = new URL('./fixtures/webmcp/webmcp-baseline.json', import.meta.url);
const baseline = JSON.parse(readFileSync(BASELINE_URL, 'utf-8'));
const acceptBaseline = process.argv.includes('--accept-baseline');

const MOMENT_KINDS = ['structural_transition', 'strong_transient', 'energy_lift', 'energy_drop', 'quiet_contrast'];
const INCLUDES = ['beats', 'onsets', 'segments', 'boundaries', 'cues'];
const BAR_SECONDS = 4 * (60 / BPM);

/** Same shape as makeStructuredProject, parameterized by bar count. */
function makeBenchProject(bars) {
  const duration = bars * BAR_SECONDS;
  const beats = [];
  for (let index = 0; index < bars * 4; index += 1) {
    beats.push({ time: index * (BAR_SECONDS / 4), index, bar: Math.floor(index / 4) + 1, downbeat: index % 4 === 0 });
  }
  const onsets = [];
  for (let bar = 0; bar < bars; bar += 1) {
    for (let k = 0; k < 8; k += 1) {
      const time = bar * BAR_SECONDS + k * (BAR_SECONDS / 8);
      const strength = k === 0 ? 0.8 : 0.5;
      onsets.push({
        id: bar * 8 + k + 1,
        time,
        bar: bar + 1,
        strength,
        bands: { all: strength, low: strength * 0.8, mid: strength * 0.55, high: strength * 0.4 },
      });
    }
  }
  const fps = 20;
  const frameCount = Math.floor(duration * fps);
  const bands = { all: new Array(frameCount), low: new Array(frameCount), mid: new Array(frameCount), high: new Array(frameCount) };
  for (let frame = 0; frame < frameCount; frame += 1) {
    const value = 0.5 + 0.1 * Math.sin(frame / fps);
    bands.all[frame] = value;
    bands.low[frame] = value;
    bands.mid[frame] = value * 0.9;
    bands.high[frame] = value * 0.8;
  }
  const segmentCount = Math.max(1, Math.floor(bars / 16));
  const segments = [];
  const boundaries = [];
  for (let index = 0; index < segmentCount; index += 1) {
    const startBar = index * 16 + 1;
    const endBar = Math.min(bars, startBar + 15);
    segments.push({
      id: `segment-${String(index + 1).padStart(3, '0')}`,
      index,
      start_bar: startBar,
      end_bar: endBar,
      start_time: (startBar - 1) * BAR_SECONDS,
      end_time: endBar >= bars ? duration : endBar * BAR_SECONDS,
      family: index % 2 === 0 ? 'A' : 'B',
      variant: 0,
      display_label: index % 2 === 0 ? 'A' : 'B',
      bar_count: endBar - startBar + 1,
      descriptors: [],
      mean_energy: 0.5,
    });
    if (index > 0) {
      boundaries.push({ bar: startBar, time: (startBar - 1) * BAR_SECONDS, novelty: 0.6, drivers: { harmony: 0.5, timbre: 0.5, rhythm: 0.5, energy: 0.5 } });
    }
  }
  return {
    schema_version: '4.0',
    project_id: `webmcp-bench-${bars}`,
    source: { display_name: `Bench ${bars}`, duration, sample_rate: 44100, channels: 2 },
    tempo: { global_bpm: BPM, segments: [{ start: 0, end: duration, bpm: BPM, method: 'bench', score: null }] },
    meter: { beats_per_bar: 4, beat_unit: 4 },
    grid: { origin: 0, default_subdivision: 16, bars },
    beats,
    onsets,
    energy: { fps, start: 0, bands },
    patterns: { method: 'bench', bars: [], segments, boundaries, repetitions: [] },
    cues: { accent: [] },
    exports: {},
  };
}

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

const now = () => performance.now();

function measure(batch) {
  const started = now();
  batch();
  return Math.round((now() - started) * 100) / 100;
}

function runQueryBatches(label, bars) {
  const page = pageFor(makeBenchProject(bars));
  const duration = bars * BAR_SECONDS;
  const observed = {};
  observed.context_x100 = measure(() => {
    for (let index = 0; index < 100; index += 1) projectContext(page);
  });
  observed.state_at_time_x1000 = measure(() => {
    for (let index = 0; index < 1000; index += 1) stateAtTime(page, { time: (index * 7) % duration });
  });
  observed.events_max_window_x10 = measure(() => {
    for (let index = 0; index < 10; index += 1) {
      eventsWindow(page, { startBar: 1, endBar: Math.min(64, bars), include: INCLUDES, limit: 200 });
    }
  });
  observed.moments_all_kinds_x10 = measure(() => {
    for (const kind of MOMENT_KINDS) {
      findVisualMoments(page, { kind });
      findVisualMoments(page, { kind, band: 'high' });
    }
  });
  observed.compare_four_ranges_x10 = measure(() => {
    const quarter = Math.floor(bars / 4);
    for (let index = 0; index < 10; index += 1) {
      compareRanges(page, {
        ranges: [
          { startBar: 1, endBar: quarter },
          { startBar: quarter + 1, endBar: quarter * 2 },
          { startBar: quarter * 2 + 1, endBar: quarter * 3 },
          { startBar: quarter * 3 + 1, endBar: bars },
        ],
      });
    }
  });
  return { label, observed };
}

function runActionBatch() {
  const { deps } = makeFakePlayer();
  loadProject(makeStructuredProject());
  const observed = {};
  observed.actions_x1000 = measure(() => {
    for (let index = 0; index < 200; index += 1) {
      focusRange(deps, { startBar: 1, endBar: 8, reason: 'Benchmark' });
      controlPlayback(deps, { action: 'seek_and_play', bar: 2, preRollBeats: 2 });
      setLoopRange(deps, { enabled: true, startBar: 1, endBar: 8 });
      controlPlayback(deps, { action: 'pause' });
      undoLastAgentAction(deps);
    }
  });
  return observed;
}

class MockModelContext {
  constructor() { this.tools = new Map(); this.registrations = 0; }
  registerTool(definition, options = {}) {
    if (this.tools.has(definition.name)) throw new Error(`duplicate tool ${definition.name}`);
    const entry = { definition, signal: options.signal || null };
    this.tools.set(definition.name, entry);
    this.registrations += 1;
    if (entry.signal) {
      entry.signal.addEventListener('abort', () => {
        if (this.tools.get(definition.name) === entry) this.tools.delete(definition.name);
      });
    }
    return Promise.resolve();
  }
}

function runLifecycleBatch() {
  const mock = new MockModelContext();
  const previousDocument = globalThis.document;
  globalThis.document = { modelContext: mock };
  loadProject(makeStructuredProject());
  const observed = {};
  try {
    observed.install_dispose_x100 = measure(() => {
      for (let index = 0; index < 100; index += 1) {
        const session = installWebMCP({ getState: () => state });
        assert.equal(mock.tools.size, 8, 'install must register exactly eight tools');
        session.dispose();
        assert.equal(mock.tools.size, 0, 'dispose must unregister every tool');
      }
    });
  } finally {
    disposeWebMCP();
    globalThis.document = previousDocument;
  }
  return observed;
}

// --- run ----------------------------------------------------------------------
const results = {
  short: runQueryBatches('short', 32),
  typical: runQueryBatches('typical', 90),
  long: runQueryBatches('long', 300),
};
results.actions = runActionBatch();
results.lifecycle = runLifecycleBatch();

const observed = {
  short: results.short.observed,
  typical: results.typical.observed,
  long: results.long.observed,
  actions: results.actions,
  lifecycle: results.lifecycle,
};

if (acceptBaseline) {
  baseline.observed_ms = observed;
  baseline.updated = new Date().toISOString().slice(0, 10);
  writeFileSync(BASELINE_URL, `${JSON.stringify(baseline, null, 2)}\n`, 'utf-8');
  console.log(`baseline observed values updated in ${BASELINE_URL.pathname}`);
} else {
  for (const size of ['short', 'typical', 'long']) {
    for (const [key, value] of Object.entries(observed[size])) {
      const threshold = baseline.thresholds_ms[size][key];
      assert.ok(typeof threshold === 'number', `baseline threshold missing: ${size}.${key}`);
      assert.ok(value <= threshold, `${size}.${key}: observed ${value}ms exceeds hard threshold ${threshold}ms`);
    }
  }
  for (const size of ['actions', 'lifecycle']) {
    for (const [key, value] of Object.entries(observed[size])) {
      const threshold = baseline.thresholds_ms[size][key];
      assert.ok(value <= threshold, `${size}.${key}: observed ${value}ms exceeds hard threshold ${threshold}ms`);
    }
  }
}

for (const [size, entries] of Object.entries(observed)) {
  for (const [key, value] of Object.entries(entries)) {
    const threshold = baseline.thresholds_ms[size]?.[key];
    console.log(`${size}.${key}: ${value}ms (threshold ${threshold ?? 'n/a'}ms)`);
  }
}
console.log('webmcp benchmark ok');
