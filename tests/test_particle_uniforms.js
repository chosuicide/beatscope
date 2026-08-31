/**
 * Director-frame -> shader-uniform conversion tests (v0.6.1 plan section
 * 13.3). The conversion is the only bridge between the motion director and
 * the GPU; it must clamp exactly, never emit NaN, and keep musical envelopes
 * independent of viewport sizing.
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { createTrack } from '../beatscope/runtime/runtime.js';
import { createMotionDirector } from '../beatscope/runtime/visual-profile.js';
import { frameToUniforms } from '../beatscope/web/particle-field.js';
import { assertFiniteFrame } from './helpers/visual-frame.js';

const project = JSON.parse(
  await readFile(new URL('./fixtures/runtime/characterization-project.json', import.meta.url), 'utf-8'),
);
const director = createMotionDirector(createTrack(project));
const layout = { width: 1400, height: 520 };

// Every uniform is finite for every interesting frame, including the
// time extremes the stage can pass during seeks.
{
  for (const time of [-5, 0, 0.5, 2.5, 3.3, 100, 1e6]) {
    const frame = director.at(time);
    assertFiniteFrame(frame, [], `director frame at ${time}`);
    const uniforms = frameToUniforms(frame, layout, { quality: 1, reducedMotion: false });
    for (const [key, value] of Object.entries(uniforms)) {
      assert.ok(Number.isFinite(value), `uniform ${key} not finite at t=${time}: ${value}`);
    }
  }
}

// Exact clamping: synthetic over-range frames cannot overdrive the GPU.
{
  const wild = {
    time: 2.5,
    low: 4, mid: -2, high: 7, all: 100,
    ambient: -1,
    anticipation: 2.5, hold: 3, impact: 2.5, recoil: -0.5, aftershock: 9,
    tension: -4, hero: 2, shockProgress: 17,
    beatWave: 8, waveProgress: -2, coreAperture: 4, diffusion: 7, beatExpand: 3,
    lobeSplit: 5,
    lobeWeights: [1.4, -0.2, 0.5],
    direction: [9, 0, 0],
  };
  const uniforms = frameToUniforms(wild, layout);
  assert.equal(uniforms.uLow, 1);
  assert.equal(uniforms.uMid, 0);
  assert.equal(uniforms.uHigh, 1);
  assert.equal(uniforms.uAmbient, 0);
  assert.equal(uniforms.uAnticipation, 1);
  assert.equal(uniforms.uHold, 1);
  assert.equal(uniforms.uImpact, 1);
  assert.equal(uniforms.uRecoil, 0);
  assert.equal(uniforms.uAftershock, 1);
  assert.equal(uniforms.uTension, 0);
  assert.equal(uniforms.uHero, 1);
  assert.equal(uniforms.uShockProgress, 1);
  assert.equal(uniforms.uBeatWave, 1);
  assert.equal(uniforms.uWaveProgress, 0);
  assert.equal(uniforms.uCoreAperture, 1);
  assert.equal(uniforms.uDiffusion, 1);
  assert.equal(uniforms.uBeatExpand, 1);
  assert.equal(uniforms.uLobeSplit, 1);
  assert.equal(uniforms.uLobeWeights0, 1);
  assert.equal(uniforms.uLobeWeights1, 0);
  // Direction renormalizes to a unit vector no matter the input magnitude.
  const dx = uniforms.uDirection0, dy = uniforms.uDirection1, dz = uniforms.uDirection2;
  assert.ok(Math.abs(Math.sqrt(dx * dx + dy * dy + dz * dz) - 1) < 1e-9);
}

// Bands pass through with their separation intact (sqrt-compressed frames).
{
  const frame = director.at(2.5);
  const uniforms = frameToUniforms(frame, layout);
  assert.equal(uniforms.uLow, frame.low);
  assert.equal(uniforms.uMid, frame.mid);
  assert.equal(uniforms.uHigh, frame.high);
  // The per-beat breath channel maps through unchanged on real frames
  // (t=2.6 sits at phase 0.2 inside the beat, on the expansion plateau).
  const breathing = director.at(2.6);
  assert.ok(breathing.beatExpand > 0);
  assert.equal(frameToUniforms(breathing, layout).uBeatExpand, breathing.beatExpand);
}

// Hero asymmetry: the hero flag and rotated asymmetric lobe weights survive.
{
  const heroFrame = director.at(2.5);
  assert.equal(heroFrame.hero, 1);
  const uniforms = frameToUniforms(heroFrame, layout);
  assert.equal(uniforms.uHero, 1);
  assert.ok(uniforms.uLobeWeights0 !== uniforms.uLobeWeights1
    || uniforms.uLobeWeights1 !== uniforms.uLobeWeights2);
  assert.equal(uniforms.uLobeWeights0, heroFrame.lobeWeights[0]);
  assert.equal(uniforms.uLobeWeights1, heroFrame.lobeWeights[1]);
  assert.equal(uniforms.uLobeWeights2, heroFrame.lobeWeights[2]);
}

// Reduced-motion caps: the flag is forwarded, channels untouched here.
{
  const frame = director.at(2.5);
  const on = frameToUniforms(frame, layout, { quality: 1, reducedMotion: true });
  const off = frameToUniforms(frame, layout, { quality: 1, reducedMotion: false });
  assert.equal(on.uReducedMotion, 1);
  assert.equal(off.uReducedMotion, 0);
  assert.equal(on.uImpact, off.uImpact);
  assert.equal(on.uAnticipation, off.uAnticipation);
}

// Viewport/radius values never alter the musical envelopes.
{
  const frame = director.at(2.5);
  const small = frameToUniforms(frame, { width: 640, height: 360, radiusPx: 90 });
  const large = frameToUniforms(frame, { width: 2560, height: 1440, radiusPx: 420 });
  for (const key of ['uLow', 'uMid', 'uHigh', 'uAmbient', 'uAnticipation', 'uHold',
    'uImpact', 'uRecoil', 'uAftershock', 'uTension', 'uHero', 'uShockProgress',
    'uBeatWave', 'uWaveProgress', 'uCoreAperture', 'uDiffusion', 'uBeatExpand']) {
    assert.equal(small[key], large[key], `layout changed ${key}`);
  }
  assert.ok(small.uRadiusPx !== large.uRadiusPx);
  assert.ok(small.uWorldScale !== large.uWorldScale);
}

// Stable output for fixed input, including the reused-target path.
{
  const frame = director.at(2.5);
  const first = frameToUniforms(frame, layout);
  const second = frameToUniforms(frame, layout);
  assert.deepEqual(first, second);

  const scratch = {};
  frameToUniforms(frame, layout, { quality: 0.75, reducedMotion: true }, scratch);
  frameToUniforms(frame, layout, {}, scratch);
  assert.deepEqual({ ...scratch }, first);
}

console.log('Particle uniforms OK: finite, clamped, layout-independent, stable.');
