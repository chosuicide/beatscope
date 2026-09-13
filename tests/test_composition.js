import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { test } from 'node:test';

mkdirSync('build', { recursive: true });
const output = mkdtempSync(resolve('build/composition-test-'));
execFileSync(process.execPath, ['web-src/node_modules/typescript/bin/tsc',
  'web-src/src/composition/model.ts', 'web-src/src/composition/persistence.ts',
  '--target', 'es2022', '--module', 'commonjs', '--moduleResolution', 'node',
  '--resolveJsonModule', '--esModuleInterop', '--skipLibCheck', '--strict',
  '--rootDir', '.', '--outDir', output], { stdio: 'pipe' });
writeFileSync(join(output, 'package.json'), '{"type":"commonjs"}');
const require = createRequire(import.meta.url);
const { validateComposition, serializeComposition, CompositionHistory } = require(join(output, 'web-src/src/composition/model.js'));
const { CompositionWriter, readDraft } = require(join(output, 'web-src/src/composition/persistence.js'));
const doc = {
  schema: 'beatscope-composition-1', project_id: '62bce8192088', source_rhythm_sha256: 'a'.repeat(64), title: '文字 🎵',
  artwork: { width: 1920, height: 1080, color: '#17191c' },
  background: { preset_id: '', mode: 'solid', opacity: 1 }, objects: [], responses: [], author_notes: '',
};

test('canonical corpus agrees with Python and invalid values are rejected', () => {
  const corpus = [doc, ...[0, -0, 0.1234565, 0.9999994, 0.5].map(opacity => ({ ...doc, background: { ...doc.background, opacity } }))];
  const python = execFileSync(process.env.PYTHON || 'python', ['-c',
    'import sys,json; from beatscope.composition import composition_bytes; print(json.dumps([composition_bytes(d).decode() for d in json.loads(sys.stdin.buffer.read().decode("utf-8"))]))'],
    { input: JSON.stringify(corpus), encoding: 'utf8' });
  assert.deepEqual(corpus.map(serializeComposition), JSON.parse(python));
  for (const invalid of [null, { ...doc, extra: true }, { ...doc, project_id: doc.project_id + '\n' }, { ...doc, title: '\ud800' },
    { ...doc, artwork: { ...doc.artwork, width: NaN } }]) assert.ok(validateComposition(invalid).length);
});

test('undo and redo restore exact bytes, and unchanged edits do not create history', () => {
  const history = new CompositionHistory(doc);
  assert.equal(history.edit(() => {}), false);
  assert.equal(history.canUndo, false);
  history.edit(d => { d.title = 'Changed'; });
  const changed = serializeComposition(history.current);
  history.undo(); assert.equal(serializeComposition(history.current), serializeComposition(doc));
  history.redo(); assert.equal(serializeComposition(history.current), changed);
});

function storage() {
  const data = new Map();
  return { setItem: (k, v) => data.set(k, v), getItem: k => data.get(k) ?? null, removeItem: k => data.delete(k) };
}

test('writes serialize, pending edits coalesce and ETag advances only after success', async () => {
  const calls = [], states = [], store = storage();
  let release;
  const first = new Promise(r => { release = r; });
  const writer = new CompositionWriter('/composition', 'v0', doc, s => states.push(s), async (_, options) => {
    calls.push(options);
    if (calls.length === 1) await first;
    return new Response('{}', { headers: { ETag: 'v' + calls.length } });
  }, store);
  writer.enqueue({ ...doc, title: '1' });
  writer.enqueue({ ...doc, title: '2' });
  writer.enqueue({ ...doc, title: '3' });
  assert.equal(calls.length, 1);
  assert.equal(readDraft(store, writer.draftKey).document.title, '3');
  release(); await writer.flush();
  assert.equal(calls.length, 2);
  assert.equal(calls[1].headers['If-Match'], 'v1');
  assert.equal(JSON.parse(calls[1].body).title, '3');
  assert.equal(states.at(-1), 'saved');
  assert.equal(store.getItem(writer.draftKey), null);
});

test('conflicts stop the queue and preserve a recoverable draft', async () => {
  const store = storage(), states = []; let calls = 0;
  const writer = new CompositionWriter('/composition', 'v0', doc, s => states.push(s), async () => {
    calls++; return new Response('{}', { status: 409 });
  }, store);
  writer.enqueue({ ...doc, title: 'local' }); await writer.flush();
  writer.enqueue({ ...doc, title: 'still local' }); await writer.flush();
  assert.equal(calls, 1); assert.equal(states.at(-1), 'conflict');
  assert.equal(readDraft(store, writer.draftKey).document.title, 'still local');
  writer.dispose();
});

test('native request receiver is the global object, not the writer instance', async () => {
  const writer = new CompositionWriter('/composition', 'v0', doc, () => {}, async function () {
    assert.equal(this, globalThis);
    return new Response('{}', { headers: { ETag: 'v1' } });
  }, storage());
  writer.enqueue({ ...doc, title: 'receiver' }); await writer.flush();
  assert.equal(writer.version, 'v1');
});
