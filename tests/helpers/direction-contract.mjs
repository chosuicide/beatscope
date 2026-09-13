/**
 * Compile the direction contract (web-src/src/direction/contract.ts) with
 * web-src's TypeScript and load it as an ES module for Node tests.
 *
 * The mirror compiles fresh on every load (noEmitOnError keeps a failed
 * compile from leaving stale output), so the contract tests always exercise
 * the exact source the browser ships.
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const TESTS_DIR = new URL('../', import.meta.url);
const TSCONFIG = fileURLToPath(new URL('tsconfig.direction.json', TESTS_DIR));
const TSC = fileURLToPath(new URL('../web-src/node_modules/typescript/bin/tsc', TESTS_DIR));
const OUTPUT = new URL('.generated/direction/contract.js', TESTS_DIR).href;
const LOCK = fileURLToPath(new URL('.generated/direction.lock', TESTS_DIR));
const MARKER = fileURLToPath(new URL('.generated/direction.sha256', TESTS_DIR));
const INPUTS = [
  TSCONFIG,
  fileURLToPath(new URL('../web-src/src/direction/contract.ts', TESTS_DIR)),
  fileURLToPath(new URL('../web-src/src/direction/types.ts', TESTS_DIR)),
  fileURLToPath(new URL('../web-src/src/direction/commands.ts', TESTS_DIR)),
  fileURLToPath(new URL('../web-src/src/direction/layout.ts', TESTS_DIR)),
];

function inputHash() {
  const hash = createHash('sha256');
  for (const path of INPUTS) hash.update(readFileSync(path));
  return hash.digest('hex');
}

export function compileDirectionContract() {
  const expected = inputHash();
  for (;;) {
    try {
      mkdirSync(LOCK);
      break;
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 25);
    }
  }
  try {
    let actual = '';
    try { actual = readFileSync(MARKER, 'utf8').trim(); } catch { /* first compile */ }
    if (actual !== expected) {
      execFileSync(process.execPath, [TSC, '-p', TSCONFIG], { stdio: 'pipe' });
      writeFileSync(MARKER, `${expected}\n`);
    }
  } finally {
    rmSync(LOCK, { recursive: true, force: true });
  }
}

export async function loadDirectionContract() {
  compileDirectionContract();
  return import(OUTPUT);
}
