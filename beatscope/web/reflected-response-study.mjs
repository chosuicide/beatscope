/** Local experiment: martin / Butterchurn material, BeatScope action ownership.
 * Controls are seek-safe. Feedback pixels are NOT history-independent. */
import { compileComposition } from './composition-runtime.mjs';
export const STUDY_PRESET = 'martin - reflections on black tiles';
export function compileReflectedResponse(rhythm, relevance, { gap = .38, release = .32, amount = .8 } = {}) {
  const doc = { project_id: rhythm.project_id, source_rhythm_sha256: rhythm.source.sha256,
    objects: [{ id: 'field', opacity: 1 }], responses: [{ id: 'light', target_id: 'field',
      driver: 'ranked_onsets', band: 'all', min_gap: gap, release, amount: 1, motion: 'scale_pulse' }] };
  const runtime = compileComposition(doc, rhythm, relevance), times = runtime.eventTimes[0].times;
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const ranking = new Map((relevance?.events ?? []).map(e => [String(e.onset_id), e.response_relevance]));
  const source = new Map((rhythm.onsets ?? []).map(e => [e.time, e]));
  const events = times.map(time => { const e = source.get(time); return { time, weight: clamp(ranking.get(String(e?.id)) ?? e?.strength ?? 0) }; });
  const energy = rhythm.energy, fps = Number(energy?.fps), start = Number(energy?.start ?? 0);
  const hasEnergy = Number.isFinite(fps) && fps > 0 && Number.isFinite(start);
  function sample(band, t) {
    const values = energy?.bands?.[band]; if (!hasEnergy || !values?.length) return 0;
    const index = (t - start) * fps; if (index < 0 || index > values.length - 1) return 0;
    const i = Math.floor(index), f = index - i;
    return clamp((Number(values[i]) || 0) * (1 - f) + (Number(values[Math.min(i + 1, values.length - 1)]) || 0) * f);
  }
  const duration = Math.max(Number(rhythm.source.duration) || 0, (times.at(-1) ?? 0) + 4,
    hasEnergy ? start + (energy.bands?.all?.length ?? 0) / fps : 0);
  if (duration > 7200) throw Error('Flow study supports up to two hours');
  const hz = 120, dt = 1 / hz, count = Math.ceil(duration * hz) + 1;
  const tracks = Array.from({ length: 7 }, () => new Float64Array(count));
  let low = 0, mid = 0, high = 0, force = 0, phase = 0, turn = 0, first = 0;
  const tau = .35 + release * 1.8;
  for (let i = 1; i < count; i++) {
    const t = i * dt;
    // Causal smoothing of OUR measured bands; not reconstructed FFT bins.
    const follow = (v, input) => v + (input - v) * (1 - Math.exp(-dt / (input > v ? .055 : .28)));
    low = follow(low, sample('low', t)); mid = follow(mid, sample('mid', t)); high = follow(high, sample('high', t));
    while (first < events.length && t - events[first].time > 6 * tau) first++;
    let input = 0;
    for (let j = first; j < events.length && events[j].time <= t; j++) {
      const age = t - events[j].time;
      input += events[j].weight * (1 - Math.exp(-age / .022)) * Math.exp(-age / tau);
    }
    force = follow(force, 1 - Math.exp(-input));
    const speed = amount * (.85 * low + .65 * mid + .32 * high + 1.4 * force);
    phase += dt * speed; turn += dt * amount * (.18 * low + .36 * mid + .16 * force);
    [low, mid, high, force, phase, turn, speed].forEach((v, k) => { tracks[k][i] = v; });
  }
  return { diagnostics: { ...runtime.diagnostics[0], energy: hasEnergy ? 'measured-bands' : 'unavailable' }, times,
    at(time, enabled = true) {
      if (!Number.isFinite(time)) throw Error('Finite music time required');
      const position = clamp(time * hz, 0, count - 1), i = Math.floor(position), f = position - i;
      const values = tracks.map(track => enabled ? track[i] * (1 - f) + track[Math.min(i + 1, count - 1)] * f : 0);
      const [low, mid, high, force, phase, turn, speed] = values;
      return { time, pulse: force * amount, phase, low, mid, high, speed,
        x: .5 + .34 * Math.sin(phase * .87), y: .5 + .3 * Math.cos(phase * .63),
        angle: turn, frequency: 1.5 + .6 * mid + .3 * force, persistence: enabled && speed > .001 ? .992 : .95 };
    } };
}
export function createReflectedPreset(original, getState) {
  const preset = structuredClone(original);
  delete preset.init_eqs_str; delete preset.frame_eqs_str;
  preset.init_eqs = a => a; preset.pixel_eqs = '';
  preset.baseVals.wave_a = 0; preset.baseVals.modwavealphabyvolume = 0;
  // Retain refraction/composite, gate transport and illumination with our flow.
  if (!preset.warp.includes('* 8.0') || !preset.warp.includes('0.03 * texture')) throw Error('Unsupported reflection shader revision');
  preset.warp = preset.warp.replace('* 8.0', '* (8.0 * q30)').replace('0.03 * texture', '(0.03 * q31) * texture');
  preset.frame_eqs = a => {
    const s = getState();
    return Object.assign(a, { q1: Math.cos(s.angle), q2: Math.sin(s.angle), q3: -Math.sin(s.angle), q4: Math.cos(s.angle),
      q20: s.phase, q21: 0, q22: 0, q23: 0, q24: 0, q26: 0, q27: s.frequency,
      q30: Math.min(2, s.speed), q31: Math.min(1, s.speed), q32: s.persistence, wave_a: 0, zoom: 1, rot: 0 });
  };
  const seed = { ...original.shapes[0].baseVals, enabled: 1, sides: 64, textured: 0, additive: 1,
    r: .48, g: .68, b: .85, r2: .1, g2: .22, b2: .35, a2: 0, border_a: 0 };
  // Persistent sources follow integrated band/event trajectories. No teleporting.
  preset.shapes = [0, 1, 2, 3].map(i => ({ baseVals: { ...seed }, init_eqs: a => a, frame_eqs: a => {
    const s = getState(), phase = s.phase + i * Math.PI / 2, power = Math.min(1, s.speed);
    return Object.assign(a, { x: .5 + .36 * Math.sin(phase * (1 + .07 * i)), y: .5 + .34 * Math.cos(phase * .73 + i),
      rad: .2 + .2 * s.low + .12 * s.pulse, ang: phase,
      r: i === 1 ? .95 : .35, g: i === 1 ? .62 : .7, b: i === 1 ? .32 : 1,
      a: power * (.22 + .15 * s.pulse), a2: 0 });
  } }));
  // These ribbons use our integrated features, never waveform value1/value2.
  preset.waves = [{ baseVals: { enabled: 1, samples: 256, additive: 1, dots: 0, thick: 0, a: .25 },
    init_eqs: a => a, frame_eqs: a => a, point_eqs: a => {
      const s = getState(), u = a.sample * Math.PI * 2;
      return Object.assign(a, { x: .5 + .34 * Math.sin(u + s.phase) + .07 * s.low * Math.sin(3 * u - s.phase),
        y: .5 + .32 * Math.cos(u * 2 - s.phase * .71) + .06 * s.mid * Math.sin(5 * u + s.phase),
        r: .35 + .3 * s.high, g: .7, b: 1, a: .22 * Math.min(1, s.speed) });
    } }, ...[0, 1, 2].map(() => ({ baseVals: { enabled: 0 } }))];
  return preset;
}
