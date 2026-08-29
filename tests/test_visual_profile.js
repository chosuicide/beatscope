/**
 * Visual profile tests (plan section 41, Commit D): the motion-tier budget
 * moved out of renderer.js must produce identical values from the shared
 * runtime track.
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { createTrack } from '../beatscope/runtime/runtime.js';
import { createVisualProfile } from '../beatscope/runtime/visual-profile.js';

const project = JSON.parse(
  await readFile(new URL('./fixtures/runtime/characterization-project.json', import.meta.url), 'utf-8'),
);

const track = createTrack(project);
const profile = createVisualProfile(track);

// Tiers on the fixture: p78=0.846, p92=0.922, p98=0.943 -> exactly one hero
// (strength 0.95 at t=2.5), no bursts, one turbulence-tier event (0.9 at 0).
{
  const hit = profile.at(2.5);
  assert.equal(hit.hero, 0.95);
  assert.equal(hit.pulse, 0.95);
  assert.ok(Math.abs(hit.turbulence - 2 / 11) < 1e-12); // density (5-3)/11 at age 0
  assert.equal(hit.burst, 0);
  assert.equal(hit.impactAge, 0);

  // Formula-driven decay at +0.25 s (only events within the 1.15 s window).
  const decayed = profile.at(2.75);
  assert.ok(Math.abs(decayed.hero - 0.95 * Math.exp(-0.25 * 4.5)) < 1e-12);
  assert.ok(Math.abs(decayed.pulse - 0.95 * Math.exp(-0.25 * 12)) < 1e-12);
  assert.ok(Math.abs(decayed.turbulence - (2 / 11) * Math.exp(-0.25 * 1.9)) < 1e-12);
  assert.equal(decayed.burst, 0);
  assert.ok(Math.abs(decayed.impactAge - 0.25) < 1e-12);

  // Turbulence-tier events blend strength with density (event 0 at age 0).
  const start = profile.at(0);
  assert.ok(Math.abs(start.pulse - 0.9) < 1e-12);
  assert.ok(Math.abs(start.turbulence - 0.9 * 0.35) < 1e-12);
  assert.equal(start.hero, 0);
  assert.equal(start.burst, 0);
  assert.equal(start.impactAge, Infinity);

  // Before the first event everything is zero.
  assert.deepEqual(profile.at(-5), { pulse: 0, turbulence: 0, burst: 0, hero: 0, impactAge: Infinity });
}

// Cooldown options: hero needs 8 bars between events, bursts 2 beats. At
// 60 BPM (beatLength 1 s) the strong onset at t=2 lands inside the hero
// cooldown but clears the 2-beat burst cooldown -> burst; the one at t=10
// clears the 8 s hero cooldown -> hero again.
{
  const cooldownTrack = createTrack({
    tempo: { global_bpm: 60 },
    grid: { origin: 0 },
    beats: [],
    onsets: [
      { id: 1, time: 0.0, strength: 1.0 },
      { id: 2, time: 2.0, strength: 1.0 },
      { id: 3, time: 10.0, strength: 1.0 },
    ],
    energy: {},
  });
  const cooldownProfile = createVisualProfile(cooldownTrack);

  const first = cooldownProfile.at(0);
  assert.equal(first.hero, 1);
  assert.equal(first.impactAge, 0);

  const second = cooldownProfile.at(2);
  assert.equal(second.burst, 1); // demoted: inside the 8-bar hero cooldown
  assert.equal(second.hero, 0); // the t=0 hero is beyond the 1.15 s window
  assert.equal(second.impactAge, 0);

  const third = cooldownProfile.at(10);
  assert.equal(third.hero, 1); // 10 s later clears the 8 s cooldown
  assert.equal(third.impactAge, 0);
}

// Purity: frozen profile, frozen input, deterministic output.
{
  assert.ok(Object.isFrozen(profile));
  const frozen = JSON.parse(JSON.stringify(project));
  (function deepFreeze(value) {
    Object.freeze(value);
    for (const item of Object.values(value)) {
      if (item && typeof item === 'object') deepFreeze(item);
    }
  })(frozen);
  const frozenProfile = createVisualProfile(createTrack(frozen));
  assert.doesNotThrow(() => {
    frozenProfile.at(2.5);
    frozenProfile.at(-1);
  });
  assert.deepEqual(profile.at(2.5), profile.at(2.5));
}

// Empty onsets: stable zero budget.
{
  const empty = createVisualProfile(createTrack({ tempo: {}, grid: {}, beats: [], onsets: [], energy: {} }));
  assert.deepEqual(empty.at(1.0), { pulse: 0, turbulence: 0, burst: 0, hero: 0, impactAge: Infinity });
}

console.log('Visual profile OK: tiers, decay formulas, cooldowns, purity.');
