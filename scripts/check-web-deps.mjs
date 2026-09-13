/**
 * Reproducible-build check for the web-src frontend workspace (v0.12 plan §3.1):
 * "Pin all JavaScript dependencies in the lockfile. No CDN or runtime network
 * dependency." Fails when any dependency uses a version range, when the
 * lockfile disagrees with the manifest, or when any resolved artifact points
 * outside the default npm registry.
 *
 * Usage: node scripts/check-web-deps.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const webSrc = path.join(repoRoot, 'web-src');
const errors = [];

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

const EXACT = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;

const manifestPath = path.join(webSrc, 'package.json');
const lockPath = path.join(webSrc, 'package-lock.json');

if (!fs.existsSync(manifestPath)) {
  console.error('FAIL: web-src/package.json missing');
  process.exit(1);
}
if (!fs.existsSync(lockPath)) {
  console.error('FAIL: web-src/package-lock.json missing');
  process.exit(1);
}

const manifest = readJson(manifestPath);
const lock = readJson(lockPath);

for (const [name, spec] of Object.entries({
  ...manifest.dependencies,
  ...manifest.devDependencies,
})) {
  if (!EXACT.test(spec)) {
    errors.push(`${name}: "${spec}" is not an exact pinned version`);
  }
}

if (lock.lockfileVersion !== 3) {
  errors.push(`lockfileVersion ${lock.lockfileVersion} !== 3`);
}
if (lock.name !== manifest.name || lock.version !== manifest.version) {
  errors.push(`lockfile identity (${lock.name}@${lock.version}) does not match manifest (${manifest.name}@${manifest.version})`);
}

const pinned = { ...manifest.dependencies, ...manifest.devDependencies };
for (const [name, spec] of Object.entries(pinned)) {
  const entry = lock.packages?.[`node_modules/${name}`];
  if (!entry) {
    errors.push(`${name}: missing from lockfile`);
    continue;
  }
  if (entry.version !== spec) {
    errors.push(`${name}: lockfile ${entry.version} !== pinned ${spec}`);
  }
  if (typeof entry.resolved === 'string' && !entry.resolved.startsWith('https://registry.npmjs.org/')) {
    errors.push(`${name}: resolved outside default registry: ${entry.resolved}`);
  }
}

// Transitive packages must also resolve from the default registry; integrity
// is required for every entry so CI builds are bit-reproducible from the lock.
for (const [loc, entry] of Object.entries(lock.packages ?? {})) {
  if (loc === '' || loc.startsWith('workspace:')) continue;
  if (typeof entry.resolved === 'string' && !entry.resolved.startsWith('https://registry.npmjs.org/')) {
    errors.push(`${loc}: resolved outside default registry: ${entry.resolved}`);
  }
  if (entry.resolved && !entry.integrity) {
    errors.push(`${loc}: missing integrity hash`);
  }
}

if (errors.length) {
  console.error('FAIL\n' + errors.map((e) => ' - ' + e).join('\n'));
  process.exit(1);
}
console.log(`web-src dependency lock verified (${Object.keys(pinned).length} direct pins, ${Object.keys(lock.packages ?? {}).length - 1} locked packages)`);
