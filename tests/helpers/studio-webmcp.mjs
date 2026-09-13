/**
 * Compile the Studio Director v2 modules (web-src/src/webmcp) with web-src's
 * TypeScript and load them as an ES module for Node tests.
 *
 * Same convention as helpers/direction-contract.mjs: the mirror compiles fresh
 * whenever an input changed (noEmitOnError keeps a failed compile from leaving
 * stale output), so the tests always exercise the exact source the browser
 * ships — there is no second JavaScript implementation of this logic.
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const TESTS_DIR = new URL('../', import.meta.url);
const TSCONFIG = fileURLToPath(new URL('tsconfig.studio-webmcp.json', TESTS_DIR));
const TSC = fileURLToPath(new URL('../web-src/node_modules/typescript/bin/tsc', TESTS_DIR));
const SOURCE_ROOT = fileURLToPath(new URL('../web-src/src/', TESTS_DIR));
const INCLUDED_DIRS = ['webmcp', 'movie'];
const GENERATED = fileURLToPath(new URL('.generated/', TESTS_DIR));
const OUTPUT = new URL('.generated/webmcp/contracts.js', TESTS_DIR).href;
const LOCK = fileURLToPath(new URL('.generated/studio-webmcp.lock', TESTS_DIR));
const MARKER = fileURLToPath(new URL('.generated/studio-webmcp.sha256', TESTS_DIR));

/** Only the module tree this contract owns — never the whole app source. */
function sourceInputs() {
  const files = [TSCONFIG];
  const visit = (path) => {
    for (const name of readdirSync(path).sort()) {
      const child = join(path, name);
      if (statSync(child).isDirectory()) visit(child);
      else if (/\.tsx?$/.test(name)) files.push(child);
    }
  };
  visit(join(SOURCE_ROOT, 'webmcp'));
  files.push(join(SOURCE_ROOT, 'movie', 'types.ts'));
  return files;
}

function inputHash() {
  const hash = createHash('sha256');
  for (const path of sourceInputs()) hash.update(path).update('\0').update(readFileSync(path));
  hash.update(readFileSync(TSC));
  return hash.digest('hex');
}

export function compileStudioWebmcp() {
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
      for (const dir of INCLUDED_DIRS) rmSync(join(GENERATED, dir), { recursive: true, force: true });
      execFileSync(process.execPath, [TSC, '-p', TSCONFIG], { stdio: 'pipe' });
      writeFileSync(MARKER, `${expected}\n`);
    }
  } finally {
    rmSync(LOCK, { recursive: true, force: true });
  }
}

export async function loadStudioWebmcpModule(name) {
  compileStudioWebmcp();
  return import(new URL(`.generated/webmcp/${name}.js`, TESTS_DIR).href);
}

/** The frozen catalog: tool definitions, limits, error codes, forbidden sets. */
export async function loadStudioWebmcp() {
  return loadStudioWebmcpModule('contracts');
}

/** Envelopes, sanitizers and the canonical serializer. */
export async function loadStudioWebmcpResponses() {
  return loadStudioWebmcpModule('responses');
}
