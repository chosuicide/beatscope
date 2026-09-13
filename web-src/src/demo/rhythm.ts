/**
 * Deterministic rhythm evidence for the bundled "Beyond the Fog" demo.
 *
 * The demo song is synthetic and repository-owned: its measured facts are
 * generated from a fixed-seed PRNG (never Math.random), so the same build
 * always yields the same evidence. Energy envelopes are intentionally absent
 * so energy-driven response chains surface their honest "unavailable" state
 * (plan §2.3 — never fabricate data).
 *
 * Musical facts (must stay consistent with the frozen references):
 * BPM 120, 4/4, bar = 2.0 s, duration 242 s (121 bars, 04:02).
 */

import type { DirectionDocument } from '../direction/types';

export const DEMO_BPM = 120;
export const DEMO_BEATS_PER_BAR = 4;
export const DEMO_BAR_SECONDS = 240 / DEMO_BPM; // 2.0
export const DEMO_DURATION = 242; // 04:02
export const DEMO_BAR_COUNT = 121;

/** Deterministic PRNG (mulberry32). Fixed seed per purpose — never Math.random. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface DemoOnset {
  id: string;
  time: number;
  band: 'low' | 'mid' | 'high';
  strength: number;
}

export interface DemoEnergy {
  fps: number;
  start: number;
  bands: { low: number[]; mid: number[]; high: number[] };
}

export interface DemoRhythm {
  project_id: string;
  duration: number;
  bpm: number;
  bar_seconds: number;
  beats: { time: number; bar: number; beat: number }[];
  onsets: DemoOnset[];
  /** measured downbeats; empty when the project has no valid grid */
  downbeats: number[];
  /** measured energy envelopes; null when the project has no energy stream */
  energy: DemoEnergy | null;
  /** structural boundary times; empty when no structure was found */
  boundaries: number[];
  /** structure segments (bar/time spans); empty when none */
  segments: { start_time: number; end_time: number }[];
}

/** Demo structural boundaries: the scene starts of the frozen document. */
export const DEMO_BOUNDARY_BARS = [13, 27, 39, 53, 64, 76, 90, 99, 107];

/** Demo segment spans (seconds) matching the frozen ten-scene table. */
export const DEMO_SEGMENT_SPANS: Array<{ start_time: number; end_time: number }> = [
  { start_time: 0, end_time: 24 },
  { start_time: 24, end_time: 52 },
  { start_time: 52, end_time: 76 },
  { start_time: 76, end_time: 104 },
  { start_time: 104, end_time: 126 },
  { start_time: 126, end_time: 150 },
  { start_time: 150, end_time: 178 },
  { start_time: 178, end_time: 196 },
  { start_time: 196, end_time: 212 },
  { start_time: 212, end_time: 242 },
];

let cachedRhythm: DemoRhythm | null = null;

export function demoRhythm(): DemoRhythm {
  if (cachedRhythm) return cachedRhythm;
  const rand = mulberry32(0xbe47f06);
  const beats: DemoRhythm['beats'] = [];
  const onsets: DemoOnset[] = [];

  for (let bar = 1; bar <= DEMO_BAR_COUNT; bar++) {
    const barStart = (bar - 1) * DEMO_BAR_SECONDS;
    for (let beat = 1; beat <= DEMO_BEATS_PER_BAR; beat++) {
      beats.push({ time: barStart + (beat - 1) * 0.5, bar, beat });
    }
    // Deterministic onset pattern: downbeat pulse, mid offbeats, sparse
    // high-band ticks whose density follows an arch over the song.
    const arch = Math.sin((Math.PI * (bar - 1)) / Math.max(1, DEMO_BAR_COUNT - 1));
    onsets.push({
      id: `on-b${bar}-1`,
      time: barStart,
      band: 'low',
      strength: 0.82 + 0.12 * arch + 0.06 * rand(),
    });
    onsets.push({
      id: `on-b${bar}-3`,
      time: barStart + 1.0,
      band: 'low',
      strength: 0.66 + 0.14 * arch + 0.08 * rand(),
    });
    if (rand() < 0.55 + 0.3 * arch) {
      onsets.push({
        id: `on-b${bar}-25`,
        time: barStart + 0.75,
        band: 'mid',
        strength: 0.42 + 0.2 * arch + 0.12 * rand(),
      });
    }
    if (rand() < 0.5 + 0.3 * arch) {
      onsets.push({
        id: `on-b${bar}-35`,
        time: barStart + 1.5,
        band: 'mid',
        strength: 0.4 + 0.2 * arch + 0.12 * rand(),
      });
    }
    const ticks = Math.round(1 + 2 * arch * rand());
    for (let k = 0; k < ticks; k++) {
      const eighth = 0.25 * (1 + Math.floor(rand() * 7));
      onsets.push({
        id: `on-b${bar}-h${k}`,
        time: barStart + eighth,
        band: 'high',
        strength: 0.3 + 0.25 * arch + 0.18 * rand(),
      });
    }
  }
  onsets.sort((a, b) => a.time - b.time || (a.id < b.id ? -1 : 1));
  const downbeats = beats.filter((b) => b.beat === 1).map((b) => b.time);
  cachedRhythm = {
    project_id: DEMO_PROJECT_ID,
    duration: DEMO_DURATION,
    bpm: DEMO_BPM,
    bar_seconds: DEMO_BAR_SECONDS,
    beats,
    onsets,
    downbeats,
    energy: demoEnergy(),
    boundaries: DEMO_BOUNDARY_BARS.map((bar) => (bar - 1) * DEMO_BAR_SECONDS),
    segments: DEMO_SEGMENT_SPANS.map((s) => ({ ...s })),
  };
  return cachedRhythm;
}

/**
 * Deterministic energy envelopes (10 Hz) generated from fixed-seed PRNGs.
 * Energy is a slow occupancy signal — it must never trigger per-event
 * explosions (§2.11), so the walk is smoothed and clamped.
 */
function demoEnergy(): DemoEnergy {
  const fps = 10;
  const count = Math.ceil(DEMO_DURATION * fps) + 1;
  const band = (seed: number, base: number, drift: number): number[] => {
    const rand = mulberry32(seed);
    const out: number[] = [];
    let value = base;
    for (let i = 0; i < count; i++) {
      value += (rand() - 0.5) * drift;
      value = Math.max(0.02, Math.min(1, value));
      out.push(Math.round(value * 10000) / 10000);
    }
    return out;
  };
  return {
    fps,
    start: 0,
    bands: {
      low: band(0x51a9e1, 0.55, 0.05),
      mid: band(0x2c7b43, 0.4, 0.07),
      high: band(0x7f0d2b, 0.3, 0.09),
    },
  };
}

/**
 * Demo identity, shaped exactly like a server-derived project: project_id
 * is sha256(source label)[:12] and the digest is the full sha256 hex of a
 * fixed label ('beyond-the-fog demo rhythm v0.12'), so the shipped
 * document satisfies the `beatscope-direction-1` contract unchanged.
 */
export const DEMO_SOURCE_RHYTHM_SHA256 = 'c235e01f04b7e9e0940b30c918d6bab8b9eda06feea8cebc101e897a403ca0e5';
export const DEMO_PROJECT_ID = DEMO_SOURCE_RHYTHM_SHA256.slice(0, 12);

/**
 * Legacy v0.11 state shape for the frozen WebMCP tools: the same facts in
 * the normalizeMap-compatible wrapper (tempo/grid/source + beats/onsets).
 */
let cachedLegacy: Record<string, unknown> | null = null;
export function demoLegacyProject(): Record<string, unknown> {
  if (cachedLegacy) return cachedLegacy;
  const r = demoRhythm();
  cachedLegacy = {
    project_id: r.project_id,
    source: { duration: r.duration, file: 'beyond-the-fog.synth.wav' },
    tempo: { global_bpm: r.bpm },
    grid: { origin: 0, default_subdivision: 16 },
    beats: r.beats,
    onsets: r.onsets,
  };
  return cachedLegacy;
}

export type { DirectionDocument };
