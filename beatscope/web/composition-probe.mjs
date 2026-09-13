import { readFile, realpath } from 'node:fs/promises';
import { resolve, relative, isAbsolute } from 'node:path';
import { createHash } from 'node:crypto';
const root = await realpath(process.argv[2] || '.');
const manifest = JSON.parse(await readFile(resolve(root, 'composition-package.json'), 'utf8'));
if (manifest.schema !== 'beatscope-composition-package-1' || Object.keys(manifest.files).length > 1000) throw Error('Invalid manifest');
for (const [name, expected] of Object.entries(manifest.files)) {
  const path = await realpath(resolve(root, name)), rel = relative(root, path);
  if (rel.startsWith('..') || isAbsolute(rel)) throw Error('Unsafe member path');
  const actual = createHash('sha256').update(await readFile(path)).digest('hex');
  if (actual !== expected) throw Error('Integrity mismatch: ' + name);
}
// Inspect authored content as JSON only. Never import scripts from an untrusted package.
const doc = JSON.parse(await readFile(resolve(root, 'composition.json'), 'utf8'));
const rhythm = JSON.parse(await readFile(resolve(root, 'timing/rhythm-map.json'), 'utf8'));
if (doc.source_rhythm_sha256 !== rhythm.source.sha256 || doc.project_id !== rhythm.project_id) throw Error('Song identity mismatch');
console.log('Composition package verified; ' + Object.keys(manifest.files).length + ' files. Audio relinking required.');
