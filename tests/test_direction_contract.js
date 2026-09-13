/**
 * Cross-language contract test (v0.12 Round 2 Commit 1).
 *
 * Compiles web-src/src/direction/contract.ts (the exact source the browser
 * ships) and asserts it against tests/fixtures/direction/contract-corpus.json:
 * stable error/notice codes, the canonical number formatter, and byte-identical
 * canonical JSON + SHA-256 versus beatscope/direction.py.
 */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

import { loadDirectionContract } from './helpers/direction-contract.mjs';

const contract = await loadDirectionContract();
const corpus = JSON.parse(
  await readFile(new URL('./fixtures/direction/contract-corpus.json', import.meta.url), 'utf-8'),
);

// --- number formatter ------------------------------------------------------
for (const [value, expected] of corpus.number_cases) {
  assert.equal(contract.canonicalNumber(value), expected, `canonicalNumber(${value})`);
}
assert.throws(() => contract.canonicalNumber(NaN), /non-finite/);
assert.throws(() => contract.canonicalNumber(Infinity), /non-finite/);

// --- validator + canonical bytes per corpus case ---------------------------
let validated = 0;
for (const testCase of corpus.doc_cases) {
  const { errors, notices } = contract.validateDirection(testCase.doc);
  const codes = (messages) => messages.map((m) => m.split(': ', 1)[0]);
  assert.deepEqual(
    codes(errors),
    testCase.expected_error_codes,
    `${testCase.name} error codes`,
  );
  assert.deepEqual(
    codes(notices),
    testCase.expected_notice_codes,
    `${testCase.name} notice codes`,
  );
  validated += 1;

  if (testCase.expected_error_codes.length === 0) {
    const bytes = contract.canonicalDirectionBytes(testCase.doc);
    const text = new TextDecoder().decode(bytes);
    assert.equal(text, testCase.canonical, `${testCase.name} canonical bytes`);
    assert.equal(
      createHash('sha256').update(bytes).digest('hex'),
      testCase.canonical_sha256,
      `${testCase.name} canonical sha256`,
    );
    // determinism: reparse and re-canonicalize must be a fixed point
    const reparsed = JSON.parse(text);
    assert.equal(
      contract.canonicalDirectionString(reparsed),
      testCase.canonical,
      `${testCase.name} canonical fixed point`,
    );
  }
}
assert.ok(validated >= 20, `expected the full corpus, ran ${validated} cases`);

// --- hand-written props literal (formatting case) --------------------------
const formatting = corpus.doc_cases.find((c) => c.name === 'formatting');
const canonicalText = contract.canonicalDirectionString(formatting.doc);
assert.ok(
  canonicalText.includes(corpus.expected_props_canonical),
  `props canonical form mismatch:\n  expected: ${corpus.expected_props_canonical}\n  actual:   ${canonicalText.match(/"props":\{[^}]*\}/)?.[0]}`,
);

// --- canonicalize refuses invalid documents --------------------------------
const badRatio = corpus.doc_cases.find((c) => c.name === 'bad-ratio');
assert.throws(() => contract.canonicalDirectionString(badRatio.doc), /direction\/ratio/);

// --- the shipped demo document satisfies the contract ----------------------
// (autosave validates before writing; a demo doc outside the contract would
// break saving in static-demo mode on first edit)
const demo = await import(new URL('./.generated/demo/document.js', import.meta.url).href);
const demoErrors = contract.validateDirection(demo.demoDocument).errors;
assert.deepEqual(demoErrors, [], `demo document must validate: ${demoErrors.join('; ')}`);
const demoCanonical = contract.canonicalDirectionString(demo.demoDocument);
assert.equal(
  createHash('sha256').update(demoCanonical, 'utf8').digest('hex'),
  createHash('sha256').update(contract.canonicalDirectionBytes(demo.demoDocument)).digest('hex'),
);

console.log(`direction contract: ${corpus.number_cases.length} number cases + ${validated} doc cases agree with Python`);
