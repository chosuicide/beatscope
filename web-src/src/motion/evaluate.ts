/**
 * Deterministic direction evaluator — first-cut subset for Commit 2.
 *
 * Rules that are contract (plan §4.6/§4.7) and already enforced here:
 * - musical output is a pure function of media time; no Date.now,
 *   performance.now, ticker delta or accumulated state;
 * - envelopes evaluate around each event's original measured timestamp;
 * - response budget: exact timestamps, deterministic sort, per-bar caps,
 *   refractory suppression — presentation only, never edits evidence.
 */
import type { DirectionDocument, DirectionScene, ResponseChain, DirectionLayer } from '../direction/types';
import type { DemoRhythm } from '../demo/rhythm';

export interface LayerOutput {
  scale: number;
  translate: { x: number; y: number };
  opacity: number;
}

export interface SceneEvaluation {
  scene: DirectionScene;
  layers: Map<string, LayerOutput>;
}

const BASE_OUTPUT: LayerOutput = { scale: 1, translate: { x: 0, y: 0 }, opacity: 1 };

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** Envelope around one event's exact measured timestamp (§4.4). */
function envelopeValue(time: number, eventTime: number, attack: number, release: number): number {
  const dt = time - eventTime;
  if (dt < 0 || dt > attack + release) return 0;
  if (dt <= attack) return attack === 0 ? 1 : dt / attack;
  const fall = (dt - attack) / release;
  return clamp(1 - fall * fall * 0.999, 0, 1);
}

/** Deterministic budget selection per chain (§4.7, compile-time subset). */
function selectEvents(chain: ResponseChain, rhythm: DemoRhythm, scene: DirectionScene): number[] {
  if (chain.driver.kind === 'beat_phase') return [];
  if (chain.driver.kind === 'energy_envelope') return []; // unavailable → no fabricated data
  const band = chain.driver.band;
  const inScene = rhythm.onsets.filter((o) => o.band === band && o.time >= scene.start_time && o.time < scene.end_time);
  const sorted = [...inScene].sort(
    (a, b) => b.strength - a.strength || a.time - b.time || (a.id < b.id ? -1 : 1),
  );
  const maxPerBar = chain.driver.max_events_per_bar;
  const refractory = chain.driver.refractory_beats * (60 / rhythm.bpm);
  const barSeconds = 240 / rhythm.bpm;
  const perBar = new Map<number, number>();
  const selected: number[] = [];
  for (const onset of sorted) {
    const bar = Math.floor(onset.time / barSeconds);
    const used = perBar.get(bar) ?? 0;
    if (used >= maxPerBar) continue;
    // refractory: skip when too close to an already-selected event (same chain)
    if (selected.some((t) => Math.abs(t - onset.time) < refractory)) continue;
    perBar.set(bar, used + 1);
    selected.push(onset.time);
  }
  return selected.sort((a, b) => a - b);
}

export function sceneAtTime(doc: DirectionDocument, time: number): DirectionScene {
  const scenes = doc.scenes;
  for (const scene of scenes) {
    if (time >= scene.start_time && time < scene.end_time) return scene;
  }
  return scenes[scenes.length - 1];
}

export function evaluateScene(scene: DirectionScene, time: number, rhythm: DemoRhythm): SceneEvaluation {
  const layers = new Map<string, LayerOutput>();
  for (const layer of scene.layers) layers.set(layer.id, { ...BASE_OUTPUT, translate: { x: 0, y: 0 } });

  for (const chain of scene.responses) {
    if (chain.unavailable_reason) continue;
    const target = layers.get(chain.target_layer_id);
    if (!target) continue;
    let value = 0;
    if (chain.driver.kind === 'beat_phase') {
      const beatSeconds = 60 / rhythm.bpm / chain.driver.subdivision;
      const phase = ((time - scene.start_time) / beatSeconds) % 1;
      value = Math.max(0, 1 - phase) ** 2; // impulse at each subdivision hit
    } else {
      const { attack_seconds: attack, release_seconds: release } = chain.motion;
      let best = 0;
      for (const eventTime of selectEvents(chain, rhythm, scene)) {
        best = Math.max(best, envelopeValue(time, eventTime, attack, release));
      }
      value = best;
    }
    const motion = chain.motion;
    if (motion.kind === 'scale_pulse') {
      target.scale *= 1 + motion.amount * value;
    } else if (motion.kind === 'translate_recoil') {
      target.translate.x += motion.axis[0] * motion.amount * value * 100;
      target.translate.y += motion.axis[1] * motion.amount * value * 100;
    } else if (motion.kind === 'opacity_lift') {
      target.opacity = Math.min(1, target.opacity + motion.amount * value * 0.5);
    }
  }
  return { scene, layers };
}

export function layerOutputAt(evaluation: SceneEvaluation, layer: DirectionLayer): LayerOutput {
  return evaluation.layers.get(layer.id) ?? BASE_OUTPUT;
}
