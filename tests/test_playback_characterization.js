/**
 * Characterization for the SHARED runtime contract (plan sections 43-45).
 *
 * After Commits B-E both time-query consumers sample the same
 * beatscope/runtime implementation:
 *
 *  1. renderer.js::playbackState  - web adapter: track.at() + sqrt energy
 *     compression + legacy number-shaped fields.
 *  2. exports.py visual-state.js::getVisualState - thin shim over
 *     track.at(time); the raw runtime state object.
 *
 * Remaining documented differences between the carriers:
 *
 *   D1  energy: the web adapter returns sqrt-compressed values, the
 *       runtime state carries raw band energy.
 *   D2  onset: the web adapter flattens the impulse to a number
 *       (strength * exp(-age * 16)); the export carries
 *       {item, age, value}.
 *   D3  accent: same impulse, number on the web, {item, age, value} or
 *       null on the export.
 *   D5  section objects: the export carries the whitelisted rhythm-map
 *       section (no vector); the web keeps the raw patterns.bars entry.
 *
 * Resolved along the way: D4 (both sides now look up the previous onset
 * with the unclamped query time), D6 (both sides extrapolate past the
 * stored grid, Commit C) and D7 (the export's nearest-onset rule was
 * replaced by the shared previous-onset impulse, Commit E).
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

import { playbackState } from '../beatscope/web/renderer.js';
import { createTrack } from '../beatscope/runtime/runtime.js';
import { createMotionDirector } from '../beatscope/runtime/visual-profile.js';
import { frameToUniforms } from '../beatscope/web/particle-field.js';

const project = JSON.parse(
  await readFile(new URL('./fixtures/runtime/characterization-project.json', import.meta.url), 'utf-8'),
);
const LAST_BEAT_TIME = project.beats[project.beats.length - 1].time;

// Materialise the shared runtime + the export shim for the same map.
const scratch = mkdtempSync(join(tmpdir(), 'beatscope-characterization-'));
const modulePath = join(scratch, 'visual-state.mjs');
execFileSync(
  'python',
  [
    '-c',
    [
      'import json, sys, pathlib',
      'from beatscope.exports import _codex_rhythm_map, _visual_state_source, _runtime_source',
      'project = json.loads(sys.argv[1])',
      'out = pathlib.Path(sys.argv[2])',
      '(out / "beatscope-runtime.js").write_text(_runtime_source(), encoding="utf-8")',
      'shim = _visual_state_source(_codex_rhythm_map(project))',
      '(out / "visual-state.mjs").write_text(shim, encoding="utf-8")',
    ].join('\n'),
    JSON.stringify(project),
    scratch,
  ],
  { encoding: 'utf-8' },
);
const { getVisualState } = await import(pathToFileURL(modulePath).href);

const TIMES = [-0.2, 0.0, 0.125, 0.25, 0.6, 1.0, 1.375, 2.0, 3.3, 3.5, 4.0, 5.5, 10.0];
const accentIds = new Set(project.cues.accent.map((cue) => cue.onset));

// Independent expectation for the shared previous-onset impulse rule.
function expectedImpulse(time) {
  let previous = null;
  for (const onset of project.onsets) {
    if (onset.time <= time) previous = onset;
  }
  if (!previous) return { value: 0, age: Infinity, item: null };
  const age = time - previous.time;
  if (age >= 0.24) return { value: 0, age, item: previous };
  return { value: previous.strength * Math.exp(-age * 16), age, item: previous };
}

for (const time of TIMES) {
  const web = playbackState(project, time);
  const exported = getVisualState(time);

  // One position core and one clock: identical facts on both carriers.
  assert.equal(web.time, time);
  assert.equal(exported.time, time);
  assert.equal(web.bar, exported.bar, `bar mismatch at t=${time}`);
  assert.equal(web.beat, exported.beat, `beat mismatch at t=${time}`);
  assert.ok(Math.abs(web.beatPhase - exported.beatPhase) < 1e-12, `beatPhase mismatch at t=${time}`);
  assert.ok(Math.abs(web.barPhase - exported.barPhase) < 1e-12, `barPhase mismatch at t=${time}`);

  // D1: sqrt compression on the web side only.
  for (const band of ['all', 'low', 'mid', 'high']) {
    assert.ok(
      Math.abs(web[band] - Math.sqrt(exported[band])) < 1e-9,
      `D1 energy mismatch (${band}) at t=${time}`,
    );
  }

  // D2: the impulse rule, checked independently of both implementations.
  const expected = expectedImpulse(time);
  assert.ok(
    Math.abs((exported.onset.value || 0) - expected.value) < 1e-9,
    `impulse value mismatch at t=${time}`,
  );

  // D2/D3 carriers: number on the web, {item, age, value} on the export.
  assert.equal(exported.onset.value, web.onset, `onset carrier mismatch at t=${time}`);
  if (exported.onset.item) {
    assert.ok(Math.abs(exported.onset.age - web.onsetAge) < 1e-12);
    assert.equal(exported.onset.item.id, expected.item.id);
  } else {
    // v0.9: no onset yet reports age null (JSON-serializable "none yet")
    // instead of Infinity, which the consumer probe must be able to hash.
    assert.equal(web.onsetAge, null);
  }
  const exportedAccent = exported.accent ? exported.accent.value : 0;
  assert.equal(exportedAccent, web.accent, `accent carrier mismatch at t=${time}`);
  const expectedAccent = expected.item && accentIds.has(expected.item.id) ? expected.value : 0;
  assert.ok(Math.abs(exportedAccent - expectedAccent) < 1e-9, `accent value mismatch at t=${time}`);

  if (time > LAST_BEAT_TIME) {
    // D6 (unified): both sides extrapolate; no stored section that far out.
    assert.ok(web.bar >= 3, `D6 bar should continue past the grid at t=${time}`);
    assert.equal(web.section, null, `D6 web section should be null at t=${time}`);
    assert.equal(exported.section, null, `D6 export section should be null at t=${time}`);
  } else if (web.section || exported.section) {
    // D5: same section identity, different object shapes.
    assert.equal(web.section?.group, exported.section?.group, `section group mismatch at t=${time}`);
    assert.equal(web.section?.label, exported.section?.label, `section label mismatch at t=${time}`);
    assert.ok(!('vector' in exported.section), 'D5 export section must be stripped');
  }
}

// Known accent cue: onset id 2 at t=0.5 (strength 0.5).
const onAccent = playbackState(project, 0.5);
const onAccentExport = getVisualState(0.5);
assert.equal(onAccent.accent, 0.5); // impulse value == raw strength at age 0
assert.equal(onAccentExport.accent.value, 0.5);
assert.equal(onAccentExport.accent.item.id, 2);
const offAccent = playbackState(project, 0.75);
const offAccentExport = getVisualState(0.75);
assert.equal(offAccent.accent, 0); // impulse decayed past the 0.24 s window
assert.equal(offAccentExport.accent, null);

// Determinism: identical calls return identical objects.
assert.deepEqual(playbackState(project, 1.375), playbackState(project, 1.375));
assert.deepEqual(getVisualState(1.375), getVisualState(1.375));

// v0.8 (plan section 10): the stage frame wraps the beat director frame in a
// `motion` slot. The uniform conversion must treat bare frames and wrapped
// frames identically, so v0.7-era callers keep byte-identical GPU behavior.
{
  const director = createMotionDirector(createTrack(project));
  for (const time of [0, 0.5, 2.5, 3.3]) {
    const beat = director.at(time);
    const bare = frameToUniforms(beat, { width: 800, height: 400 });
    const wrapped = frameToUniforms({ motion: beat }, { width: 800, height: 400 });
    assert.deepEqual(wrapped, bare, `uniform parity at t=${time}`);
  }
}

console.log('Characterization OK: shared runtime pinned at both carriers (D1/D2/D3/D5 documented).');
