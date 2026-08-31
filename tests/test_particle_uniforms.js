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

// --- v0.8 commit 4: scene uniforms (plan section 11). -----------------------
// The combined stage frame carries a scene block; the conversion must clamp
// every scene channel and follow the spread combination rule exactly.
{
  const sceneBlock = {
    composition: { spread: 0.14, twist: 0.5, flow: 0.32, orbit: 0.44, void: 0.18, contrast: 0.72, paletteMix: 0.3 },
    transition: { channels: { phaseTurn: 0.6, radialPart: 0.4, aperture: 0.8, flowShear: -1 } },
  };
  const beat = director.at(2.5);
  const uniforms = frameToUniforms({ ...beat, scene: sceneBlock }, layout);
  const expectedSpread = Math.max(0, Math.min(
    0.46 - sceneBlock.transition.channels.radialPart * 0.10,
    sceneBlock.composition.spread + beat.lobeSplit * (0.24 - sceneBlock.composition.spread * 0.12),
  ));
  assert.ok(Math.abs(uniforms.uSceneSpread - expectedSpread) < 1e-12);
  assert.ok(Math.abs(uniforms.uRadialPart - 0.4) < 1e-12);
  assert.equal(uniforms.uSceneTwist, 0.5);
  assert.equal(uniforms.uSceneFlow, 0.32);
  assert.equal(uniforms.uSceneOrbit, 0.44);
  assert.equal(uniforms.uSceneVoid, 0.18);
  assert.equal(uniforms.uSceneContrast, 0.72);
  assert.equal(uniforms.uPaletteMix, 0.3);
  assert.equal(uniforms.uPhaseTurn, 0.6);
  assert.equal(uniforms.uApertureTransition, 0.8);
  assert.equal(uniforms.uFlowShear, -1);

  // The wrapped form ({motion, scene}) produces identical uniforms.
  const wrapped = frameToUniforms({ motion: beat, scene: sceneBlock }, layout);
  assert.deepEqual(wrapped, uniforms);

  // Wild scene values clamp exactly like the beat channels do.
  const wildScene = {
    composition: { spread: 5, twist: -3, flow: 2, orbit: -1, void: 9, contrast: 4, paletteMix: -2 },
    transition: { channels: { phaseTurn: 7, radialPart: -1, aperture: 3, flowShear: 5 } },
  };
  const wild = frameToUniforms({ ...beat, scene: wildScene }, layout);
  assert.equal(wild.uSceneSpread, 0.46); // spread 1 + beat term, under the combined cap
  assert.equal(wild.uRadialPart, 0);
  assert.equal(wild.uSceneTwist, 0);
  assert.equal(wild.uSceneFlow, 1);
  assert.equal(wild.uSceneOrbit, 0);
  assert.equal(wild.uSceneVoid, 1);
  assert.equal(wild.uSceneContrast, 1);
  assert.equal(wild.uPaletteMix, 0);
  assert.equal(wild.uPhaseTurn, 1);
  assert.equal(wild.uApertureTransition, 1);
  assert.equal(wild.uFlowShear, 1);
}

// Scene absent (structure off / bare director frames): the scene translation
// falls back to the exact v0.7 lobe shape and every other scene channel is 0.
{
  const beat = director.at(2.5);
  const bare = frameToUniforms(beat, layout);
  assert.ok(Math.abs(bare.uSceneSpread - beat.lobeSplit * (0.20 + 0.08 * beat.hero)) < 1e-12);
  assert.equal(bare.uRadialPart, 0);
  assert.equal(bare.uSceneTwist, 0);
  assert.equal(bare.uSceneFlow, 0);
  assert.equal(bare.uSceneOrbit, 0);
  assert.equal(bare.uSceneVoid, 0);
  assert.equal(bare.uSceneContrast, 0);
  assert.equal(bare.uPaletteMix, 0);
  assert.equal(bare.uPhaseTurn, 0);
  assert.equal(bare.uApertureTransition, 0);
  assert.equal(bare.uFlowShear, 0);
}

console.log('Particle uniforms OK: finite, clamped, layout-independent, stable.');
