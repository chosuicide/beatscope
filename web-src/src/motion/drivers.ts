/**
 * Driver registry. Drivers turn measured evidence into a
 * queryable stream for one scene. Nothing here creates, moves or quantizes
 * an event: ranked onsets keep their exact measured timestamps and the
 * selection budget is applied at compile time (§4.7).
 *
 * Two kinds of drivers exist:
 * - event drivers produce discrete events consumed by an envelope;
 * - continuous drivers return a value at any time (energy, scene phase,
 *   transition phase) and never trigger per-event explosions.
 */
import type { DriverSpec, DirectionScene } from '../direction/types';
import type { DemoRhythm } from '../demo/rhythm';
import { clamp } from './types.js';
import { lowerBound, upperBound } from './search.js';

export interface DriverEvent {
  time: number;
  strength: number;
  id: string;
}

export interface DriverAvailability {
  available: boolean;
  reason?: string;
}

export interface CompiledDriver {
  kind: string;
  availability: DriverAvailability;
  /** events inside [t0, t1); empty when unavailable */
  query(t0: number, t1: number): DriverEvent[];
  /** continuous value at `t` (0..1), or null for event drivers */
  continuous(t: number): number | null;
  /** all compiled events in time order (event drivers only) */
  events(): DriverEvent[];
}

export interface DriverCompileContext {
  /** resolved transition duration for transition_phase */
  transitionDuration: number;
}

export interface DriverDefinition {
  kind: string;
  label: string;
  availability(rhythm: DemoRhythm): DriverAvailability;
  compile(rhythm: DemoRhythm, spec: DriverSpec, scene: DirectionScene, context: DriverCompileContext): CompiledDriver;
}

const registry = new Map<string, DriverDefinition>();

export function registerDriver(definition: DriverDefinition): void {
  registry.set(definition.kind, definition);
}

export function driverFor(kind: string): DriverDefinition | null {
  return registry.get(kind) ?? null;
}

export function registeredDriverKinds(): string[] {
  return [...registry.keys()].sort();
}

function eventDriver(kind: string, availability: DriverAvailability, events: DriverEvent[]): CompiledDriver {
  const sorted = [...events].sort((a, b) => a.time - b.time || (a.id < b.id ? -1 : 1));
  const times = sorted.map((e) => e.time);
  return {
    kind,
    availability,
    events: () => sorted,
    continuous: () => null,
    query(t0, t1) {
      if (!availability.available || sorted.length === 0) return [];
      const start = lowerBound(times, t0);
      const end = lowerBound(times, t1);
      return sorted.slice(start, end);
    },
  };
}

function continuousDriver(kind: string, availability: DriverAvailability, value: (t: number) => number): CompiledDriver {
  return {
    kind,
    availability,
    events: () => [],
    continuous: (t) => (availability.available ? clamp(value(t), 0, 1) : null),
    query: () => [],
  };
}

const NO_GRID: DriverAvailability = { available: false, reason: 'no beat grid' };

function inScene(events: DriverEvent[], scene: DirectionScene): DriverEvent[] {
  return events.filter((e) => e.time >= scene.start_time && e.time < scene.end_time);
}

/* ------------------------------------------------------------------ */
/* ranked onsets                                                       */

const rankedOnsets: DriverDefinition = {
  kind: 'ranked_onsets',
  label: 'Ranked onsets',
  availability: (rhythm) =>
    rhythm.onsets.length > 0 ? { available: true } : { available: false, reason: 'no onsets' },
  compile(rhythm, spec, scene) {
    if (spec.kind !== 'ranked_onsets') throw new Error('driver spec mismatch');
    const availability = rankedOnsets.availability(rhythm);
    const events = inScene(
      rhythm.onsets
        .filter((o) => o.band === spec.band)
        .map((o) => ({ time: o.time, strength: o.strength, id: o.id })),
      scene,
    );
    return eventDriver(spec.kind, availability, events);
  },
};
registerDriver(rankedOnsets);

/* ------------------------------------------------------------------ */
/* beat phase and downbeat impulse                                     */

const beatPhase: DriverDefinition = {
  kind: 'beat_phase',
  label: 'Beat phase',
  availability: (rhythm) =>
    rhythm.beats.length > 1 && rhythm.bpm > 0 ? { available: true } : NO_GRID,
  compile(rhythm, spec, scene) {
    if (spec.kind !== 'beat_phase') throw new Error('driver spec mismatch');
    const availability = beatPhase.availability(rhythm);
    const events: DriverEvent[] = [];
    if (availability.available) {
      const division = spec.subdivision;
      const beats = rhythm.beats;
      for (let i = 0; i + 1 < beats.length; i++) {
        const a = beats[i];
        const b = beats[i + 1];
        for (let k = 0; k < division; k++) {
          const t = a.time + ((b.time - a.time) * k) / division;
          events.push({ time: t, strength: 1, id: `beat-${a.bar}-${a.beat}-${k}` });
        }
      }
    }
    return eventDriver(spec.kind, availability, inScene(events, scene));
  },
};
registerDriver(beatPhase);

const downbeatImpulse: DriverDefinition = {
  kind: 'downbeat_impulse',
  label: 'Downbeat impulse',
  availability: (rhythm) =>
    rhythm.downbeats.length > 0 ? { available: true } : NO_GRID,
  compile(rhythm, spec, scene) {
    const availability = downbeatImpulse.availability(rhythm);
    const events = rhythm.downbeats.map((time, index) => ({ time, strength: 1, id: `down-${index}` }));
    return eventDriver(spec.kind, availability, inScene(events, scene));
  },
};
registerDriver(downbeatImpulse);

/* ------------------------------------------------------------------ */
/* energy envelopes (continuous)                                       */

const energyEnvelope: DriverDefinition = {
  kind: 'energy_envelope',
  label: 'Energy envelope',
  availability: (rhythm) =>
    rhythm.energy && rhythm.energy.bands.low.length > 0
      ? { available: true }
      : { available: false, reason: 'no energy stream for this project' },
  compile(rhythm, spec, _scene) {
    if (spec.kind !== 'energy_envelope') throw new Error('driver spec mismatch');
    const availability = energyEnvelope.availability(rhythm);
    const energy = rhythm.energy;
    const samples = energy ? energy.bands[spec.band] : [];
    const fps = energy?.fps ?? 20;
    const start = energy?.start ?? 0;
    const value = (t: number): number => {
      if (!availability.available || samples.length === 0) return 0;
      const x = (t - start) * fps;
      const i = Math.floor(x);
      if (i < 0 || i >= samples.length - 1) return i < 0 ? 0 : samples[samples.length - 1];
      const frac = x - i;
      return samples[i] + (samples[i + 1] - samples[i]) * frac;
    };
    return continuousDriver(spec.kind, availability, value);
  },
};
registerDriver(energyEnvelope);

/* ------------------------------------------------------------------ */
/* structural boundary, scene phase, transition phase                  */

const structureBoundary: DriverDefinition = {
  kind: 'structure_boundary',
  label: 'Structural boundary',
  availability: (rhythm) =>
    rhythm.boundaries.length > 0 ? { available: true } : { available: false, reason: 'no structural boundaries' },
  compile(rhythm, spec, scene) {
    const availability = structureBoundary.availability(rhythm);
    const events = rhythm.boundaries.map((time, index) => ({ time, strength: 1, id: `boundary-${index}` }));
    return eventDriver(spec.kind, availability, inScene(events, scene));
  },
};
registerDriver(structureBoundary);

registerDriver({
  kind: 'scene_phase',
  label: 'Scene phase',
  availability: () => ({ available: true }),
  compile(_rhythm, spec, scene) {
    const span = Math.max(1e-6, scene.end_time - scene.start_time);
    return continuousDriver(spec.kind, { available: true }, (t) => (t - scene.start_time) / span);
  },
});

registerDriver({
  kind: 'transition_phase',
  label: 'Transition phase',
  availability: () => ({ available: true }),
  compile(_rhythm, spec, scene, context) {
    const duration = Math.max(1e-6, context.transitionDuration);
    const start = scene.end_time - duration;
    return continuousDriver(spec.kind, { available: true }, (t) => (t - start) / duration);
  },
});

export { lowerBound, upperBound };
