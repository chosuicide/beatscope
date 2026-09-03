/**
 * Deterministic fixtures for the Director tests (v0.10 plan section 18).
 *
 * The checked-in runtime fixtures are tiny (1-2 bars), so the windowed
 * Director queries get synthetic projects built here: same Rhythm IR v4
 * shape, fixed arithmetic, no randomness, no clock. Every builder returns a
 * fresh object tree so tests can mutate freely.
 */

import { state, setProject } from '../beatscope/web/state.js';

const BPM = 120;
const BEAT = 60 / BPM; // 0.5s
const BAR = 4 * BEAT; // 2s

function rangeOf(n) {
  return Array.from({ length: n }, (_, index) => index);
}

function sectionForBar(bar) {
  if (bar <= 8) return { family: 'A', variant: 0, label: 'A' };
  if (bar <= 16) return { family: 'A', variant: 1, label: "A'" };
  if (bar <= 24) return { family: 'B', variant: 0, label: 'B' };
  return { family: 'A', variant: 1, label: "A'" };
}

function energyProfileForBar(bar) {
  const section = sectionForBar(bar);
  if (section.family === 'B') return { low: 0.82, mid: 0.7, high: 0.66 };
  if (section.variant === 1) return { low: 0.47, mid: 0.4, high: 0.52 };
  return { low: 0.45, mid: 0.38, high: 0.28 };
}

/**
 * 32 bars at 120 BPM: A (1-8), A' (9-16), B (17-24), A' (25-32). A sections
 * carry eighth-note onsets, B carries sixteenths, so structure boundaries,
 * energy lifts/drops, quiet windows, and a high-band difference between the
 * two A sections are all real, measurable facts of the fixture.
 */
export function makeStructuredProject() {
  const bars = 32;
  const duration = bars * BAR; // 64s

  const beats = [];
  for (const index of rangeOf(bars * 4)) {
    beats.push({
      time: Number((index * BEAT).toFixed(6)),
      index,
      bar: Math.floor(index / 4) + 1,
      beat_in_bar: (index % 4) + 1,
      downbeat: index % 4 === 0,
    });
  }

  const onsets = [];
  const accents = [];
  let onsetId = 0;
  for (const bar of rangeOf(bars)) {
    const barNumber = bar + 1;
    const section = sectionForBar(barNumber);
    const perBar = section.family === 'B' ? 16 : 8;
    const step = BAR / perBar;
    for (const k of rangeOf(perBar)) {
      onsetId += 1;
      const time = Number((bar * BAR + k * step).toFixed(6));
      const isDownbeat = k === 0;
      const isBackbeat = section.family === 'B' && k === 8;
      let strength;
      if (section.family === 'B') strength = isDownbeat ? 0.95 : isBackbeat ? 0.8 : 0.6 + 0.05 * (k % 2);
      else if (section.variant === 1) strength = isDownbeat ? 0.8 : 0.5;
      else strength = isDownbeat ? 0.75 : 0.45;
      const accent = isDownbeat || isBackbeat;
      const highShare = section.family === 'B' ? 0.62 : section.variant === 1 ? 0.55 : 0.3;
      const onset = {
        id: onsetId,
        time,
        bar: barNumber,
        beat_in_bar: Math.floor((k * step) / BEAT) + 1,
        strength: Number(strength.toFixed(4)),
        accent,
        bands: {
          all: Number(strength.toFixed(4)),
          low: Number((strength * 0.8).toFixed(4)),
          mid: Number((strength * 0.55).toFixed(4)),
          high: Number((strength * highShare).toFixed(4)),
        },
      };
      onsets.push(onset);
      if (accent) accents.push({ onset: onsetId, time, strength: onset.strength });
    }
  }

  const fps = 20;
  const frameCount = Math.floor(duration * fps);
  const bands = { all: new Array(frameCount), low: new Array(frameCount), mid: new Array(frameCount), high: new Array(frameCount) };
  for (let frame = 0; frame < frameCount; frame += 1) {
    const time = frame / fps;
    const bar = Math.min(bars, Math.floor(time / BAR) + 1);
    const profile = energyProfileForBar(bar);
    const wobble = 0.04 * Math.sin(time * 3.1);
    bands.low[frame] = Number(Math.min(1, Math.max(0, profile.low + wobble)).toFixed(4));
    bands.mid[frame] = Number(Math.min(1, Math.max(0, profile.mid + wobble * 0.8)).toFixed(4));
    bands.high[frame] = Number(Math.min(1, Math.max(0, profile.high + wobble * 0.5)).toFixed(4));
    bands.all[frame] = Number(Math.min(1, Math.max(0, (profile.low + profile.mid + profile.high) / 3 + wobble)).toFixed(4));
  }

  const segments = [];
  const sectionSpans = [
    { startBar: 1, endBar: 8, family: 'A', variant: 0, label: 'A' },
    { startBar: 9, endBar: 16, family: 'A', variant: 1, label: "A'" },
    { startBar: 17, endBar: 24, family: 'B', variant: 0, label: 'B' },
    { startBar: 25, endBar: 32, family: 'A', variant: 1, label: "A'" },
  ];
  sectionSpans.forEach((span, index) => {
    segments.push({
      id: `segment-${String(index + 1).padStart(3, '0')}`,
      index,
      start_bar: span.startBar,
      end_bar: span.endBar,
      start_time: Number(((span.startBar - 1) * BAR).toFixed(6)),
      end_time: span.endBar >= bars ? duration : Number((span.endBar * BAR).toFixed(6)),
      family: span.family,
      variant: span.variant,
      display_label: span.label,
      bar_count: span.endBar - span.startBar + 1,
      descriptors: [],
      mean_energy: 0,
    });
  });

  const boundaries = [
    { bar: 9, time: 16, novelty: 0.55, drivers: { harmony: 0.5, timbre: 0.4, rhythm: 0.3, energy: 0.42 } },
    { bar: 17, time: 32, novelty: 0.9, drivers: { harmony: 0.8, timbre: 0.7, rhythm: 0.6, energy: 0.85 } },
    { bar: 25, time: 48, novelty: 0.72, drivers: { harmony: 0.6, timbre: 0.55, rhythm: 0.5, energy: 0.7 } },
  ];

  const patternBars = rangeOf(bars).map((bar) => ({
    bar: bar + 1,
    label: sectionForBar(bar + 1).label,
    group: sectionForBar(bar + 1).family,
    mean_strength: 0.6,
    similarity_previous: bar === 0 ? 0 : 0.5,
    vector: new Array(16).fill(0.1),
  }));

  return {
    schema_version: '4.0',
    project_id: 'webmcp-structure-fixture',
    source: {
      display_name: 'Director Fixture',
      file: 'director-fixture.wav',
      duration,
      sample_rate: 44100,
      channels: 2,
      sha256: 'ab'.repeat(32),
    },
    analysis: { backend: 'fixture', pipeline_version: 'test' },
    tempo: {
      global_bpm: BPM,
      segments: [{ start: 0, end: duration, bpm: BPM, method: 'fixture', score: null }],
    },
    meter: { beats_per_bar: 4, beat_unit: 4 },
    grid: { origin: 0, default_subdivision: 16, bars },
    beats,
    onsets,
    energy: { fps, start: 0, bands },
    patterns: { method: 'fixture', bars: patternBars, segments, boundaries, repetitions: [] },
    cues: { accent: accents },
    exports: {},
  };
}

/** Four bars of pure silence with one structure segment: no Infinity/NaN. */
export function makeQuietProject() {
  const bars = 4;
  const duration = bars * BAR;
  const beats = [];
  for (const index of rangeOf(bars * 4)) {
    beats.push({
      time: index * BEAT,
      index,
      bar: Math.floor(index / 4) + 1,
      beat_in_bar: (index % 4) + 1,
      downbeat: index % 4 === 0,
    });
  }
  return {
    schema_version: '4.0',
    project_id: 'webmcp-quiet-fixture',
    source: { display_name: 'Quiet Fixture', duration, sample_rate: 44100, channels: 2 },
    tempo: { global_bpm: BPM, segments: [{ start: 0, end: duration, bpm: BPM, method: 'fixture', score: null }] },
    meter: { beats_per_bar: 4, beat_unit: 4 },
    grid: { origin: 0, default_subdivision: 16, bars },
    beats,
    onsets: [],
    energy: {
      fps: 20,
      start: 0,
      bands: {
        all: new Array(Math.floor(duration * 20)).fill(0),
        low: new Array(Math.floor(duration * 20)).fill(0),
        mid: new Array(Math.floor(duration * 20)).fill(0),
        high: new Array(Math.floor(duration * 20)).fill(0),
      },
    },
    patterns: {
      method: 'fixture',
      bars: [],
      segments: [{
        id: 'segment-001', index: 0, start_bar: 1, end_bar: 4,
        start_time: 0, end_time: duration, family: 'A', variant: 0,
        display_label: 'A', bar_count: 4, descriptors: [], mean_energy: 0,
      }],
      boundaries: [],
      repetitions: [],
    },
    cues: {},
    exports: {},
  };
}

/** Structure facts without segments: the legacy/no-structure case. */
export function makeLegacyProject() {
  const project = makeStructuredProject();
  const legacy = JSON.parse(JSON.stringify(project));
  legacy.project_id = 'webmcp-legacy-fixture';
  legacy.source.display_name = 'Legacy Fixture';
  legacy.patterns.segments = [];
  legacy.patterns.boundaries = [];
  return legacy;
}

/**
 * Fake player adapters for action tests. Calls are recorded as
 * [name, ...args] tuples; the real state.js store holds the truth.
 */
export function makeFakePlayer() {
  const calls = [];
  return {
    calls,
    deps: {
      getState: () => state,
      hasAudio: () => true,
      seek: (time) => {
        calls.push(['seek', time]);
        state.playbackTime = time;
        return time;
      },
      play: async () => {
        calls.push(['play']);
        state.isPlaying = true;
        return true;
      },
      pause: () => {
        calls.push(['pause']);
        state.isPlaying = false;
      },
      readAudioTime: () => state.playbackTime,
      isPlaying: () => state.isPlaying,
      setFollowPlayback: (enabled) => calls.push(['follow', enabled]),
      scrollPlayerIntoView: () => calls.push(['scroll']),
    },
  };
}


/** Load a project into the shared store and reset transient player state. */
export function loadProject(project) {
  setProject(project, project.project_id || null);
  state.loop = false;
  state.isPlaying = false;
  state.playbackTime = 0;
  state.startBar = 0;
  state.loopSelection = null;
  state.hoverStep = null;
  state.selectedOnset = null;
  state.selectedCell = null;
  return state;
}

export { state };
export { BPM, BEAT, BAR };
