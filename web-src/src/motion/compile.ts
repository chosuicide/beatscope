/**
 * Deterministic compiled evaluator (plan §4.6/§4.7).
 *
 * `compileDirection` resolves anchors, builds binary-searchable driver
 * indexes and applies the response budget once. `getDirectionState(time)`
 * is then a pure query: no wall-clock, no accumulated state, no allocation
 * proportional to song length, identical output for play, pause, seek,
 * replay and offline render.
 */
import type {
  DirectionDocument,
  DirectionScene,
  ResponseChain,
} from '../direction/types';
import type { DemoRhythm } from '../demo/rhythm';
import { driverFor, type CompiledDriver } from './drivers.js';
import { operatorFor, type MotionOperatorDefinition, type OperatorContext } from './operators.js';
import { clamp, freshAccumulator, finalizeOutput, BASE_OUTPUT } from './types.js';
import type { DirectionState, LayerOutput, TransitionState } from './types.js';
import { lowerBound, upperBound } from './search.js';
import { quantize } from './noise.js';
import { applyReducedMotion } from './reduced-motion.js';

export const DEFAULT_TRANSITION_SECONDS = 0.24;

export interface CompileOptions {
  /** v0.11 response-relevance values keyed by onset id (never retrained). */
  relevance?: Map<string, number> | null;
}

export interface ResponseDiagnostics {
  eligible: number;
  selected: number;
  suppressed: number;
  tier: 'primary' | 'secondary';
  relevance: boolean;
}

export interface CompiledResponse {
  chain: ResponseChain;
  layerId: string;
  operator: MotionOperatorDefinition;
  driver: CompiledDriver;
  /** selected events in time order (exact measured timestamps) */
  times: number[];
  strengths: number[];
  /** Internal selection metadata, kept parallel to `times`. */
  eventIds: string[];
  ranks: number[];
  refractorySeconds: number;
  lookBehind: number;
  continuous: boolean;
  unavailableReason: string | null;
  diagnostics: ResponseDiagnostics;
}

export interface CompiledScene {
  scene: DirectionScene;
  start: number;
  end: number;
  transitionDuration: number;
  /** responses in authored order (stable combine order) */
  responses: CompiledResponse[];
  layerOrder: string[];
}

export interface CompiledDirection {
  doc: DirectionDocument;
  rhythm: DemoRhythm;
  scenes: CompiledScene[];
  sceneStarts: number[];
  duration: number;
  barStarts: number[];
  barSeconds: number;
  diagnostics: {
    responses: number;
    unavailable: number;
    selected: number;
    suppressed: number;
    relevance: boolean;
  };
}

/** Envelope around one event's exact measured timestamp (§4.4). */
export function envelopeValue(time: number, eventTime: number, attack: number, release: number): number {
  const dt = time - eventTime;
  if (dt < 0 || dt > attack + release) return 0;
  if (dt <= attack) return attack === 0 ? 1 : dt / attack;
  const fall = (dt - attack) / release;
  return clamp(1 - fall * fall * 0.999, 0, 1);
}

function transitionDuration(doc: DirectionDocument, scene: DirectionScene, barSeconds: number): number {
  const entries = Array.isArray(doc.transitions) ? doc.transitions : [];
  for (const entry of entries) {
    if (!entry || typeof entry !== 'object') continue;
    const record = entry as Record<string, unknown>;
    const from = record.from_scene_id ?? record.from;
    if (from !== scene.id) continue;
    const seconds = Number(record.duration_seconds);
    if (Number.isFinite(seconds) && seconds > 0) return seconds;
    const beats = Number(record.duration_beats);
    if (Number.isFinite(beats) && beats > 0) return beats * barSeconds * 0.25;
  }
  return DEFAULT_TRANSITION_SECONDS;
}

/** Measured bar start times (falls back to the constant bar length). */
function measuredBarStarts(rhythm: DemoRhythm): number[] {
  const starts: number[] = [];
  let previousBar = -Infinity;
  for (const beat of rhythm.beats) {
    if (beat.bar !== previousBar) {
      starts.push(beat.time);
      previousBar = beat.bar;
    }
  }
  return starts;
}

function budgetBucketAt(starts: number[], time: number): number {
  if (starts.length > 0) return Math.max(0, upperBound(starts, time) - 1);
  // No-grid projects have no honest bar length. The authored numeric cap is
  // therefore applied per real second, never against a BPM-derived pseudo bar.
  return Math.floor(Math.max(0, time));
}

/**
 * Deterministic budget selection (§4.7). Returns selected events in time
 * order plus diagnostics; never mutates evidence.
 */
function selectEvents(
  driver: CompiledDriver,
  spec: Extract<ResponseChain['driver'], { kind: 'ranked_onsets' }>,
  rhythm: DemoRhythm,
  relevance: Map<string, number> | null,
  barStarts: number[],
): { times: number[]; strengths: number[]; eventIds: string[]; ranks: number[]; refractorySeconds: number; diagnostics: ResponseDiagnostics } {
  const candidates = driver.events();
  const ranked = candidates
    .map((event) => ({
      event,
      rank: relevance?.get(event.id) ?? event.strength,
    }))
    .sort((a, b) => b.rank - a.rank || a.event.time - b.event.time || (a.event.id < b.event.id ? -1 : 1));
  const tierCount = spec.tier === 'primary' ? Math.ceil(ranked.length / 2) : ranked.length;
  const pool = ranked.slice(0, tierCount);

  const hasGrid = barStarts.length > 0 && rhythm.bpm > 0;
  const refractory = hasGrid ? Math.max(0, spec.refractory_beats) * (60 / rhythm.bpm) : 0;
  const perBucket = new Map<number, number>();
  const selected: Array<{ time: number; strength: number; id: string; rank: number }> = [];
  let suppressed = 0;

  for (const { event, rank } of pool) {
    const bucket = budgetBucketAt(barStarts, event.time);
    const used = perBucket.get(bucket) ?? 0;
    if (used >= spec.max_events_per_bar) {
      suppressed += 1;
      continue;
    }
    perBucket.set(bucket, used + 1);
    selected.push({ time: event.time, strength: event.strength, id: event.id, rank });
  }

  selected.sort((a, b) => a.time - b.time);
  return {
    times: selected.map((s) => s.time),
    strengths: selected.map((s) => s.strength),
    eventIds: selected.map((s) => s.id),
    ranks: selected.map((s) => s.rank),
    refractorySeconds: refractory,
    diagnostics: {
      eligible: candidates.length,
      selected: selected.length,
      suppressed,
      tier: spec.tier,
      relevance: relevance !== null && candidates.some((c) => relevance.has(c.id)),
    },
  };
}

/**
 * Refractory suppression is shared by every ranked-onset response targeting
 * the same layer/operator. It is deliberately a post-pass: two separate
 * chains must not evade the density guard and make one visual channel twitch
 * twice for the same musical moment.
 */
function suppressSharedRefractory(responses: CompiledResponse[]): number {
  const groups = new Map<string, CompiledResponse[]>();
  for (const response of responses) {
    if (response.chain.driver.kind !== 'ranked_onsets' || response.unavailableReason) continue;
    const key = `${response.layerId}\u0000${response.operator.kind}`;
    const group = groups.get(key) ?? [];
    group.push(response);
    groups.set(key, group);
  }
  let suppressedTotal = 0;
  for (const group of groups.values()) {
    const candidates = group.flatMap((response, responseIndex) =>
      response.times.map((time, eventIndex) => ({
        response,
        responseIndex,
        eventIndex,
        time,
        id: response.eventIds[eventIndex],
        rank: response.ranks[eventIndex],
        span: response.lookBehind,
        refractory: response.refractorySeconds,
      })),
    ).sort((a, b) => b.rank - a.rank || a.time - b.time || (a.id < b.id ? -1 : a.id > b.id ? 1 : a.responseIndex - b.responseIndex));
    const kept: typeof candidates = [];
    const rejected = new Map<CompiledResponse, Set<number>>();
    for (const candidate of candidates) {
      const collision = kept.some((other) => {
        const envelopesOverlap = candidate.time < other.time + other.span && other.time < candidate.time + candidate.span;
        const refractory = Math.max(candidate.refractory, other.refractory);
        return envelopesOverlap && refractory > 0 && Math.abs(candidate.time - other.time) < refractory;
      });
      if (!collision) {
        kept.push(candidate);
        continue;
      }
      const indexes = rejected.get(candidate.response) ?? new Set<number>();
      indexes.add(candidate.eventIndex);
      rejected.set(candidate.response, indexes);
    }
    for (const response of group) {
      const indexes = rejected.get(response);
      if (!indexes?.size) continue;
      const keep = response.times.map((_, index) => !indexes.has(index));
      response.times = response.times.filter((_, index) => keep[index]);
      response.strengths = response.strengths.filter((_, index) => keep[index]);
      response.eventIds = response.eventIds.filter((_, index) => keep[index]);
      response.ranks = response.ranks.filter((_, index) => keep[index]);
      response.diagnostics.selected -= indexes.size;
      response.diagnostics.suppressed += indexes.size;
      suppressedTotal += indexes.size;
    }
  }
  return suppressedTotal;
}

export function compileDirection(
  doc: DirectionDocument,
  rhythm: DemoRhythm,
  options: CompileOptions = {},
): CompiledDirection {
  const relevance = options.relevance ?? null;
  const scenes = [...doc.scenes].sort((a, b) => a.start_time - b.start_time);
  const barStarts = measuredBarStarts(rhythm);
  const sceneStarts = scenes.map((s) => s.start_time);
  const duration = scenes.length > 0 ? scenes[scenes.length - 1].end_time : rhythm.duration;

  let responseCount = 0;
  let unavailable = 0;
  let selectedTotal = 0;
  let suppressedTotal = 0;

  const compiledScenes: CompiledScene[] = scenes.map((scene) => {
    const transition = transitionDuration(doc, scene, rhythm.bar_seconds);
    const responses: CompiledResponse[] = [];
    for (const chain of scene.responses) {
      responseCount += 1;
      const operator = operatorFor(chain.motion.kind);
      const definition = driverFor(chain.driver.kind);
      if (!operator || !definition) {
        // unknown-but-preserved kinds never crash the evaluator
        unavailable += 1;
        responses.push({
          chain,
          layerId: chain.target_layer_id,
          operator: operator ?? fallbackOperator(chain.motion.kind),
          driver: definition
            ? definition.compile(rhythm, chain.driver, scene, { transitionDuration: transition })
            : unavailableDriver(chain.driver.kind),
          times: [],
          strengths: [],
          eventIds: [],
          ranks: [],
          refractorySeconds: 0,
          lookBehind: 0,
          continuous: false,
          unavailableReason: chain.unavailable_reason ?? `unregistered ${!definition ? 'driver' : 'motion'}`,
          diagnostics: { eligible: 0, selected: 0, suppressed: 0, tier: 'primary', relevance: false },
        });
        continue;
      }
      const driver = definition.compile(rhythm, chain.driver, scene, { transitionDuration: transition });
      const authoredReason = chain.unavailable_reason ?? null;
      if (!driver.availability.available) {
        unavailable += 1;
        responses.push({
          chain,
          layerId: chain.target_layer_id,
          operator,
          driver,
          times: [],
          strengths: [],
          eventIds: [],
          ranks: [],
          refractorySeconds: 0,
          lookBehind: 0,
          continuous: false,
          unavailableReason: authoredReason ?? driver.availability.reason ?? 'driver unavailable',
          diagnostics: { eligible: 0, selected: 0, suppressed: 0, tier: 'primary', relevance: false },
        });
        continue;
      }
      if (driver.continuous(0) !== null) {
        responses.push({
          chain,
          layerId: chain.target_layer_id,
          operator,
          driver,
          times: [],
          strengths: [],
          eventIds: [],
          ranks: [],
          refractorySeconds: 0,
          lookBehind: 0,
          continuous: true,
          unavailableReason: authoredReason,
          diagnostics: { eligible: 0, selected: 0, suppressed: 0, tier: 'primary', relevance: false },
        });
        continue;
      }
      if (chain.driver.kind !== 'ranked_onsets') {
        // beat/downbeat/boundary event streams: no relevance budget, keep all
        const events = driver.events();
        responses.push({
          chain,
          layerId: chain.target_layer_id,
          operator,
          driver,
          times: events.map((e) => e.time),
          strengths: events.map((e) => e.strength),
          eventIds: events.map((e) => e.id),
          ranks: events.map((e) => e.strength),
          refractorySeconds: 0,
          lookBehind: chain.motion.attack_seconds + chain.motion.release_seconds,
          continuous: false,
          unavailableReason: authoredReason,
          diagnostics: { eligible: events.length, selected: events.length, suppressed: 0, tier: 'primary', relevance: false },
        });
        continue;
      }
      const selection = selectEvents(driver, chain.driver, rhythm, relevance, barStarts);
      selectedTotal += selection.times.length;
      suppressedTotal += selection.diagnostics.suppressed;
      responses.push({
        chain,
        layerId: chain.target_layer_id,
        operator,
        driver,
        times: selection.times,
        strengths: selection.strengths,
        eventIds: selection.eventIds,
        ranks: selection.ranks,
        refractorySeconds: selection.refractorySeconds,
        lookBehind: chain.motion.attack_seconds + chain.motion.release_seconds,
        continuous: false,
        unavailableReason: authoredReason,
        diagnostics: selection.diagnostics,
      });
    }
    const sharedSuppressed = suppressSharedRefractory(responses);
    selectedTotal -= sharedSuppressed;
    suppressedTotal += sharedSuppressed;
    return {
      scene,
      start: scene.start_time,
      end: scene.end_time,
      transitionDuration: transition,
      responses,
      layerOrder: scene.layers.map((l) => l.id),
    };
  });

  return {
    doc,
    rhythm,
    scenes: compiledScenes,
    sceneStarts,
    duration,
    barStarts,
    barSeconds: rhythm.bar_seconds,
    diagnostics: {
      responses: responseCount,
      unavailable,
      selected: selectedTotal,
      suppressed: suppressedTotal,
      relevance: relevance !== null && relevance.size > 0,
    },
  };
}

function unavailableDriver(kind: string): CompiledDriver {
  return {
    kind,
    availability: { available: false, reason: `unregistered driver '${kind}'` },
    query: () => [],
    events: () => [],
    continuous: () => null,
  };
}

function fallbackOperator(kind: string): MotionOperatorDefinition {
  return {
    kind,
    label: kind,
    channel: 'opacity',
    combine: 'max',
    bound: 1,
    applyTo: () => {},
  };
}

export interface QueryOptions {
  /** live reduced-motion preference; never alters saved artistic data */
  reducedMotion?: boolean;
}

function sceneIndexAt(starts: number[], time: number): number {
  if (starts.length === 0) return -1;
  return clamp(upperBound(starts, time) - 1, 0, starts.length - 1);
}

export function getDirectionState(
  compiled: CompiledDirection,
  time: number,
  options: QueryOptions = {},
): DirectionState {
  const t = clamp(Number.isFinite(time) ? time : 0, 0, compiled.duration);
  const index = sceneIndexAt(compiled.sceneStarts, t);
  const scene = compiled.scenes[index];
  const layers = new Map<string, LayerOutput>();
  if (!scene) {
    return { scene: compiled.scenes[0].scene, sceneIndex: 0, time: t, transition: null, layers };
  }

  let transition: TransitionState | null = null;
  if (index < compiled.scenes.length - 1) {
    const start = scene.end - scene.transitionDuration;
    if (t >= start) {
      const progress = scene.transitionDuration > 0 ? clamp((t - start) / scene.transitionDuration, 0, 1) : 1;
      transition = {
        kind: scene.scene.transition_out,
        fromSceneId: scene.scene.id,
        toSceneId: compiled.scenes[index + 1].scene.id,
        progress,
        duration: scene.transitionDuration,
      };
    }
  }

  // deterministic presentation sample: quantized to 60 Hz, shared by every
  // seeded operator in this frame
  const sample = quantize(t, 1 / 60);
  const authored = new Map(scene.scene.layers.map((l) => [l.id, l]));

  for (const layerId of scene.layerOrder) {
    const acc = freshAccumulator();
    const layer = authored.get(layerId);
    for (const response of scene.responses) {
      if (response.layerId !== layerId || response.unavailableReason) continue;
      let value = 0;
      if (response.continuous) {
        value = response.driver.continuous(t) ?? 0;
      } else {
        const attack = response.chain.motion.attack_seconds;
        const release = response.chain.motion.release_seconds;
        const from = lowerBound(response.times, t - response.lookBehind);
        // upperBound includes an event exactly at `t`; the envelope decides
        // its contribution (dt = 0 is 0 for a positive attack, 1 for attack 0)
        const to = upperBound(response.times, t);
        for (let i = from; i < to; i++) {
          const v = envelopeValue(t, response.times[i], attack, release) * (response.strengths[i] || 1);
          if (v > value) value = v;
        }
      }
      if (value <= 0) continue;
      const context: OperatorContext = {
        seedKey: `${compiled.doc.project_id}:${scene.scene.id}:${layerId}`,
        sample,
      };
      response.operator.applyTo(acc, value, response.chain.motion, context);
    }
    const output = finalizeOutput(acc, layer?.opacity ?? 1);
    layers.set(layerId, options.reducedMotion ? applyReducedMotion(output) : output);
  }

  return { scene: scene.scene, sceneIndex: index, time: t, transition, layers };
}

/** Latest authored-state output (used by tests and nonvisual consumers). */
export function outputFor(state: DirectionState, layerId: string): LayerOutput {
  return state.layers.get(layerId) ?? BASE_OUTPUT;
}

/**
 * Deterministic video source time (§4.6): positive modulo for looping
 * layers, clamped for non-looping ones. Video never drives the music clock.
 */
export function videoSourceTime(
  projectTime: number,
  layerStart: number,
  sourceOffset: number,
  loopDuration: number,
  looping = true,
): number {
  const local = projectTime - layerStart + sourceOffset;
  if (!(loopDuration > 0)) return 0;
  if (!looping) return clamp(local, 0, loopDuration);
  const mod = local % loopDuration;
  return mod < 0 ? mod + loopDuration : mod;
}
