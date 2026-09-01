/**
 * Consumer probe tests (v0.9 plan section 6).
 *
 * The probe ships inside every handoff package and the wheel, so these
 * tests pin the whole self-verification contract against the frozen
 * fixture in examples/shared: the embedded sha256 agrees with node:crypto,
 * frames canonicalize (sorted keys, -0 normalized, non-finite rejected),
 * inspectPackage honors the manifest capability set, runCheckpointSuite
 * reproduces the Python-computed frames digest bit for bit, seek
 * determinism holds under reordering, and tampering fails loudly.
 */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

import {
  assertSeekDeterminism,
  canonicalFrame,
  canonicalFrameJson,
  inspectPackage,
  runCheckpointSuite,
  sha256Hex,
} from '../beatscope/runtime/consumer-probe.js';

const manifest = JSON.parse(
  readFileSync(new URL('../examples/shared/fixture.beatscope/beatscope-package.json', import.meta.url), 'utf8'),
);
const checkpoints = JSON.parse(
  readFileSync(new URL('../examples/shared/checkpoints.json', import.meta.url), 'utf8'),
);
const moduleNamespace = await import(
  pathToFileURL(fileURLToPath(new URL('../examples/shared/fixture.beatscope/visual-state.js', import.meta.url))).href
);

// --- sha256 -----------------------------------------------------------------

{
  let long = '';
  for (let i = 0; i < 500; i += 1) long += String.fromCharCode(32 + (i % 90));
  for (const text of ['', 'abc', long, long + long, 'ビートスコープ ♪']) {
    assert.equal(sha256Hex(text), createHash('sha256').update(text, 'utf8').digest('hex'));
  }
}

// --- canonicalization -------------------------------------------------------

{
  const fakeNamespace = {
    getBeatScopeFrame: (time) => ({ zeta: time, alpha: { b: -0, a: 1 / 3 }, keep: 0.1 + 0.2 }),
  };
  assert.deepEqual(canonicalFrame(fakeNamespace, 5), {
    alpha: { a: 1 / 3, b: 0 },
    keep: 0.30000000000000004,
    zeta: 5,
  });
  // Sorted-key insertion order makes JSON.stringify the canonical form.
  assert.equal(
    canonicalFrameJson(fakeNamespace, 5),
    '{"alpha":{"a":0.3333333333333333,"b":0},"keep":0.30000000000000004,"zeta":5}',
  );

  const unserializable = [
    { frame: () => ({ bad: Number.NaN }), error: /not finite/ },
    { frame: () => ({ bad: Infinity }), error: /not finite/ },
    { frame: () => ({ bad: undefined }), error: /not JSON-serializable/ },
    { frame: () => ({ bad: () => 1 }), error: /not JSON-serializable/ },
    { frame: () => ({ bad: Symbol('x') }), error: /not JSON-serializable/ },
    { frame: () => ({ bad: 10n }), error: /not JSON-serializable/ },
    { frame: () => ({ bad: new Date(0) }), error: /not a plain object/ },
  ];
  for (const { frame, error } of unserializable) {
    assert.throws(() => canonicalFrame({ getBeatScopeFrame: frame }, 0), error);
  }
  const cyclic = { name: 'loop' };
  cyclic.self = cyclic;
  assert.throws(() => canonicalFrame({ getBeatScopeFrame: () => cyclic }, 0), /cyclic/);
}

// --- inspectPackage ---------------------------------------------------------

{
  const report = await inspectPackage(manifest, moduleNamespace);
  assert.equal(report.ok, true);
  assert.deepEqual(report.errors, []);
  for (const check of Object.values(report.checks)) {
    assert.equal(check, true, `inspectPackage check failed: ${JSON.stringify(report.checks)}`);
  }
}

{
  const lying = { ...manifest, capabilities: { ...manifest.capabilities, scenes: false } };
  const report = await inspectPackage(lying, moduleNamespace);
  assert.equal(report.ok, false);
  assert.ok(report.errors.some((error) => error.includes('functions.frame:requires-scenes')));
}

{
  const drifted = { ...manifest, duration: manifest.duration + 1 };
  const report = await inspectPackage(drifted, moduleNamespace);
  assert.equal(report.ok, false);
  assert.ok(report.errors.some((error) => error.startsWith('duration:mismatch:')));
}

{
  const report = await inspectPackage({ ...manifest, schema: 'nope' }, moduleNamespace);
  assert.equal(report.ok, false);
  assert.ok(report.errors.some((error) => error.includes('schema:expected')));
}

// --- runCheckpointSuite -----------------------------------------------------

{
  const report = runCheckpointSuite(moduleNamespace, checkpoints, {});
  assert.deepEqual(report.errors, []);
  assert.equal(report.ok, true);
  assert.equal(report.frames_sha256, checkpoints.frames_sha256);
  assert.equal(report.times, checkpoints.times.length);
}

{
  const wrong = runCheckpointSuite(moduleNamespace, checkpoints, { packageSha256: 'f'.repeat(64) });
  assert.ok(wrong.errors.includes('package_sha256:mismatch'));
  const right = runCheckpointSuite(moduleNamespace, checkpoints, {
    packageSha256: checkpoints.package_sha256,
  });
  assert.equal(right.ok, true);
}

{
  const tampered = { ...checkpoints, frames_sha256: 'a'.repeat(64) };
  const report = runCheckpointSuite(moduleNamespace, tampered, {});
  assert.equal(report.ok, false);
  assert.ok(report.errors.includes('frames_sha256:mismatch'));
}

{
  // Frames genuinely re-evaluate: a digest recorded over slightly shifted
  // times (one side of every boundary triplet) must not verify.
  const shifted = checkpoints.times.map((time) => time + 0.0005);
  const tampered = {
    ...checkpoints,
    frames_sha256: sha256Hex(
      JSON.stringify(shifted.map((time) => canonicalFrame(moduleNamespace, time))),
    ),
  };
  const report = runCheckpointSuite(moduleNamespace, tampered, {});
  assert.equal(report.ok, false);
  assert.ok(report.errors.includes('frames_sha256:mismatch'));
}

{
  const tampered = { ...checkpoints, seek_sequence: [0.5] };
  const report = runCheckpointSuite(moduleNamespace, tampered, {});
  assert.equal(report.ok, false);
  assert.ok(report.errors.some((error) => error.includes('seek_sequence:unrecorded-time')));
}

// --- assertSeekDeterminism --------------------------------------------------

{
  const result = assertSeekDeterminism(moduleNamespace, checkpoints.seek_sequence, {});
  assert.equal(result.ok, true);
  assert.equal(result.queries, checkpoints.seek_sequence.length * 3);
}

{
  let calls = 0;
  const flaky = { getBeatScopeFrame: (time) => ({ time, counter: (calls += 1) }) };
  assert.throws(() => assertSeekDeterminism(flaky, [0, 1, 2]), /seek-determinism:drift/);
}

console.log('Consumer probe OK: sha256 parity, canonicalization, manifest inspection, checkpoint replay, seek determinism.');
