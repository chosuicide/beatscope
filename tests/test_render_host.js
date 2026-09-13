/**
 * Render-host invariants (v0.12 Round 3 Commit 1).
 *
 * Node-testable parts of the single-renderer pipeline: live-board
 * arbitration, the deterministic LRU poster cache and the layer-system
 * registry metadata. Pixi rendering itself is exercised in the browser;
 * here we pin the decisions that must never depend on wall-clock state.
 */
import assert from 'node:assert/strict';

import { arbitrateLiveBoard, implicitPin } from './.generated/render/arbitration.js';
import { PosterCache, estimateTextureBytes } from './.generated/render/poster-cache.js';
import {
  registeredKinds,
  registerSystem,
  renderLayerSystem,
  systemFor,
  validateLayerProps,
  withDefaults,
} from './.generated/systems/registry.js';
import './.generated/systems/index.js';

/* ---------------- live-board arbitration (§3.2) ---------------- */

// selected board is live while editing
assert.equal(
  arbitrateLiveBoard({ selectedSceneId: 'scene-02', pinnedSceneId: null, currentSceneId: 'scene-05', playing: false }),
  'scene-02',
);
// during playback the chronological board wins
assert.equal(
  arbitrateLiveBoard({ selectedSceneId: 'scene-02', pinnedSceneId: null, currentSceneId: 'scene-05', playing: true }),
  'scene-05',
);
// an explicit pin keeps the edit board live during playback
assert.equal(
  arbitrateLiveBoard({ selectedSceneId: 'scene-02', pinnedSceneId: 'scene-02', currentSceneId: 'scene-05', playing: true }),
  'scene-02',
);
// no selection, no playback: the current board stays live
assert.equal(
  arbitrateLiveBoard({ selectedSceneId: null, pinnedSceneId: null, currentSceneId: 'scene-03', playing: false }),
  'scene-03',
);
// selection while paused acts as an implicit pin, never during playback
assert.equal(implicitPin('scene-01', false), 'scene-01');
assert.equal(implicitPin('scene-01', true), null);

/* ---------------- poster cache (§3.2/§10.5) ---------------- */

let created = 0;
const destroyed = [];
const cache = new PosterCache({
  budgetBytes: 1000,
  create: (sceneId) => {
    created += 1;
    return { texture: { id: `${sceneId}-${created}` }, width: 10, height: 5 };
  },
  destroy: (texture) => destroyed.push(texture.id),
});

assert.equal(estimateTextureBytes(10, 5), 200);
assert.equal(estimateTextureBytes(10, 5, 2), 800);

const first = cache.ensure('scene-01', 'rep');
assert.equal(first.id, 'scene-01-1');
// same key reuses without regenerating
assert.equal(cache.ensure('scene-01', 'rep'), first);
assert.equal(created, 1);
// a different key replaces the entry and destroys the old texture
const hover = cache.ensure('scene-01', 'hover');
assert.notEqual(hover, first);
assert.deepEqual(destroyed, ['scene-01-1']);
// invalidation is scoped to the named scenes only
cache.ensure('scene-02', 'rep');
cache.invalidate(['scene-01']);
assert.equal(cache.has('scene-01', 'hover'), false);
assert.equal(cache.has('scene-02', 'rep'), true);
// LRU eviction keeps the most recently used posters under budget
const tiny = new PosterCache({
  budgetBytes: 500,
  create: (sceneId) => ({ texture: { id: sceneId }, width: 10, height: 5 }),
  destroy: () => {},
});
tiny.ensure('a', 'rep');
tiny.ensure('b', 'rep');
tiny.ensure('a', 'rep'); // touch a
tiny.ensure('c', 'rep'); // evicts b (least recently used)
assert.equal(tiny.has('a', 'rep'), true);
assert.equal(tiny.has('b', 'rep'), false);
assert.equal(tiny.has('c', 'rep'), true);
assert.ok(tiny.stats.bytes <= tiny.budgetBytes);
tiny.clear();
assert.equal(tiny.stats.count, 0);

/* ---------------- system registry (§4.3) ---------------- */

assert.deepEqual(registeredKinds(), ['editorial-typography', 'graphic-field', 'media-slice']);
for (const kind of registeredKinds()) {
  const definition = systemFor(kind);
  assert.ok(definition, `${kind} definition`);
  assert.ok(Object.keys(definition.defaults).length > 0, `${kind} defaults`);
  assert.ok(definition.inspector.length > 0, `${kind} inspector`);
}

// media-slice requires a source; graphic-field accepts a partial object
assert.deepEqual(validateLayerProps('media-slice', {}), ['system/media-slice/src: a source reference is required']);
assert.deepEqual(validateLayerProps('media-slice', {
  src: 'asset:demo', source_offset_seconds: -1, loop_duration_seconds: 0, loop: 'yes',
}), [
  'system/media-slice/source-offset: must be a finite number >= 0',
  'system/media-slice/loop-duration: must be a finite number > 0',
  'system/media-slice/loop: must be a boolean',
]);
assert.deepEqual(validateLayerProps('graphic-field', { tilePx: 120 }), []);
assert.deepEqual(validateLayerProps('graphic-field', { tilePx: 'big' }), [
  'system/graphic-field/tilePx: must be a finite number',
]);
// unknown kinds validate clean and are never rejected (§4.3)
assert.deepEqual(validateLayerProps('future-system', { anything: true }), []);

// defaults merge under authored props
const merged = withDefaults('graphic-field', { fill: '#fff' });
assert.equal(merged.fill, '#fff');
assert.equal(merged.tilePx, 230);

// dispatch: unregistered kinds render the unsupported placeholder, which
// names the kind instead of throwing away the layer
const placeholder = renderLayerSystem({
  kind: 'future-system',
  props: {},
  textures: { fogRidge: null, fogBright: null, paperFiber: null, halftone: null },
  assets: { textureFor: () => null, missingAsset: () => false },
  bodyW: 100,
  bodyH: 60,
  dark: false,
});
assert.equal(placeholder.constructor.name, 'Container');
assert.ok(placeholder.children.length >= 2, 'placeholder carries label + detail');

// registering a kind makes it dispatchable without touching the renderer
registerSystem({
  kind: 'editorial-typography', // re-registering replaces the definition
  label: 'Editorial typography',
  summary: 'test double',
  defaults: {},
  fields: [],
  inspector: [{ section: 'content', fields: [] }],
  validate: () => [],
  render: () => placeholder,
});
assert.equal(systemFor('editorial-typography').summary, 'test double');

console.log('render host: arbitration, poster LRU and system registry agree with the contract');
