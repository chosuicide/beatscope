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
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const TESTS_DIR = new URL('../', import.meta.url);
const TSCONFIG = fileURLToPath(new URL('tsconfig.direction.json', TESTS_DIR));
const TSC = fileURLToPath(new URL('../web-src/node_modules/typescript/bin/tsc', TESTS_DIR));
const OUTPUT = new URL('.generated/direction/contract.js', TESTS_DIR).href;
const LOCK = fileURLToPath(new URL('.generated/direction.lock', TESTS_DIR));
const MARKER = fileURLToPath(new URL('.generated/direction.sha256', TESTS_DIR));
const SOURCE_ROOT = fileURLToPath(new URL('../web-src/src/', TESTS_DIR));
const INCLUDED_DIRS = ['direction', 'demo', 'motion'];
const GENERATED = fileURLToPath(new URL('.generated/', TESTS_DIR));

function sourceInputs() {
  const files = [TSCONFIG];
  const visit = (path) => {
    for (const name of readdirSync(path).sort()) {
      const child = join(path, name);
      if (statSync(child).isDirectory()) visit(child);
      else if (/\.tsx?$/.test(name)) files.push(child);
    }
  };
  for (const dir of INCLUDED_DIRS) visit(join(SOURCE_ROOT, dir));
  return files;
}

function inputHash() {
  const hash = createHash('sha256');
  for (const path of sourceInputs()) hash.update(path).update('\0').update(readFileSync(path));
  hash.update(readFileSync(TSC));
  return hash.digest('hex');
}

export function compileDirectionContract() {
  const expected = inputHash();
  mkdirSync(GENERATED, { recursive: true });
  const deadline = Date.now() + 120_000;
  for (;;) {
    try {
      mkdirSync(LOCK);
      break;
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      if (Date.now() > deadline) throw new Error(`TypeScript test compilation lock timed out: ${LOCK}`);
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 25);
    }
  }
  try {
    let actual = '';
    try { actual = readFileSync(MARKER, 'utf8').trim(); } catch { /* first compile */ }
    if (actual !== expected || !existsSync(fileURLToPath(OUTPUT))) {
      // Remove only this compiler's output, never trust files from retired modules.
      for (const dir of [...INCLUDED_DIRS, 'systems', 'render']) {
        rmSync(join(GENERATED, dir), { recursive: true, force: true });
      }
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
