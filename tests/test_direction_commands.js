/**
 * Round 2 Commit 2 canvas command tests (node, no browser).
 *
 * The command factories are compiled from web-src/src/direction by
 * tests/tsconfig.direction.json and exercised through a miniature history
 * harness that mirrors the store reducer exactly: commit pre-binds invert
 * with the pre-apply state, undo applies the inverse, redo re-applies the
 * original command. Every structural round-trip must restore the document
 * to the same canonical bytes the Python contract produces.
 */
import assert from 'node:assert/strict';
import { compileDirectionContract } from './helpers/direction-contract.mjs';

compileDirectionContract();
const contract = await import(new URL('./.generated/direction/contract.js', import.meta.url).href);
const commands = await import(new URL('./.generated/direction/commands.js', import.meta.url).href);
const layout = await import(new URL('./.generated/direction/layout.js', import.meta.url).href);

/* ------------------------------------------------------------------ */
/* fixture: a minimal contract-valid three-scene document              */

const SOURCE_SHA = 'c'.repeat(64);

function layer(id) {
  return {
    id,
    kind: 'media-slice',
    label: `slice ${id}`,
    visible: true,
    locked: false,
    opacity: 1,
    blend: 'normal',
    transform: { x: 0, y: 0, w: 1, h: 1, rotation: 0 },
    props: { src: 'demo-media/fog-ridge.png' },
  };
}

function response(id, layerId) {
  return {
    id,
    target_layer_id: layerId,
    label: 'Downbeat pulse',
    driver: { kind: 'ranked_onsets', band: 'low', tier: 'primary', max_events_per_bar: 4, refractory_beats: 0.6 },
    motion: { kind: 'scale_pulse', amount: 0.03, attack_seconds: 0.03, release_seconds: 0.25 },
  };
}

function scene(n, startBar, endBar, startTime, endTime, transitionOut) {
  const nn = String(n).padStart(2, '0');
  return {
    id: `scene-${nn}`,
    title: `Scene ${nn}`,
    family: 'print',
    anchor: { kind: 'bars', start_bar: startBar, end_bar: endBar },
    start_time: startTime,
    end_time: endTime,
    transition_out: transitionOut,
    layers: [layer(`lay-${nn}`)],
    responses: [response(`response-${nn}`, `lay-${nn}`)],
  };
}

function makeDoc() {
  return {
    schema: 'beatscope-direction-1',
    version: '0.12.0',
    project_id: 'c235e01f04b7',
    project_title: 'Beyond the Fog',
    source_rhythm_sha256: SOURCE_SHA,
    composition: { primary_ratio: '16:9', width: 1920, height: 1080, background: '#F5F1E8' },
    theme: {},
    assets: [],
    scenes: [scene(1, 1, 9, 0, 16, 'dissolve'), scene(2, 9, 17, 16, 32, 'dissolve'), scene(3, 17, 25, 32, 48, 'hold-through')],
    transitions: [],
    diagnostics: {},
  };
}

const BAR_TIMES = Object.fromEntries(Array.from({ length: 25 }, (_, i) => [i + 1, i * 2]));

function assertCoverage(doc) {
  for (let i = 1; i < doc.scenes.length; i++) {
    const prev = doc.scenes[i - 1];
    const cur = doc.scenes[i];
    assert.equal(cur.start_time, prev.end_time, `scene ${i} time continuity`);
    if (prev.anchor.kind === 'bars' && cur.anchor.kind === 'bars') {
      assert.equal(cur.anchor.start_bar, prev.anchor.end_bar, `scene ${i} bar continuity`);
    }
  }
}

function assertValid(doc, context) {
  const { errors } = contract.validateDirection(doc);
  assert.deepEqual(errors, [], `${context}: document must satisfy the contract`);
}

function makeState(doc) {
  const boards = {};
  doc.scenes.forEach((s, i) => {
    boards[s.id] = { x: i * 300, y: 100, w: 240, bodyH: 170, rotation: 0 };
  });
  return {
    doc,
    layout: { boards },
    saveState: 'saved',
    transport: { time: 12.4, playing: true, loopStart: 0, loopEnd: 48 },
  };
}

/* mini history harness — mirrors the store reducer's command/undo/redo */
function makeHistory(state) {
  const h = { state, past: [], future: [] };
  return {
    get state() {
      return h.state;
    },
    commit(cmd) {
      const before = h.state;
      const next = cmd.apply(h.state);
      h.state = next;
      h.past = [...h.past, { cmd, invert: () => cmd.invert(before) }];
      h.future = [];
      return this;
    },
    undo() {
      const entry = h.past[h.past.length - 1];
      const inverse = entry.invert(h.state);
      h.state = inverse.apply(h.state);
      h.past = h.past.slice(0, -1);
      h.future = [entry.cmd, ...h.future];
      return this;
    },
    redo() {
      const cmd = h.future[0];
      h.state = cmd.apply(h.state);
      h.past = [...h.past, cmd];
      h.future = h.future.slice(1);
      return this;
    },
  };
}

const canonical = (doc) => contract.canonicalDirectionString(doc);

/* ------------------------------------------------------------------ */
/* split                                                               */

{
  const doc = makeDoc();
  assertValid(doc, 'fixture');
  const h = makeHistory(makeState(doc));
  const pre = h.state;

  h.commit(commands.splitSceneCommand(pre.doc, 'scene-02', pre.layout, undefined, BAR_TIMES));

  const post = h.state;
  assert.equal(post.doc.scenes.length, 4, 'split adds one scene');
  assertCoverage(post.doc);
  assertValid(post.doc, 'after split');
  assert.equal(post.doc.scenes[2].id, 'scene-02-b');
  assert.equal(post.doc.scenes[1].transition_out, 'cut', 'first half takes the hard cut');
  assert.equal(post.doc.scenes[2].transition_out, 'dissolve', 'second half keeps the original transition');
  assert.equal(post.doc.scenes[1].end_time, post.doc.scenes[2].start_time);
  assert.deepEqual(
    post.doc.scenes[2].layers.map((l) => l.id),
    ['lay-02-b'],
    'second-half layer ids are deterministic',
  );
  assert.equal(post.doc.scenes[2].responses[0].target_layer_id, 'lay-02-b', 'responses follow their layer');
  assert.equal(post.doc.scenes[2].anchor.start_bar, 13, 'bar midpoint of 9..17');
  assert.equal(post.doc.scenes[2].start_time, 24, 'bar midpoint resolves through bar seconds');
  assert.ok(post.layout.boards['scene-02-b'], 'split board gets a slot');
  assert.equal(post.layout.boards['scene-02-b'].y, post.layout.boards['scene-02'].y);
  assert.ok(post.layout.boards['scene-02-b'].x > post.layout.boards['scene-02'].x);
  assert.equal(post.saveState, 'offline', 'structural edit marks the document dirty');

  h.undo();
  assert.equal(canonical(h.state.doc), canonical(pre.doc), 'undo restores the pre-split document bytes');
  assert.deepEqual(h.state.layout, pre.layout, 'undo restores the pre-split layout');
  h.redo();
  assert.equal(canonical(h.state.doc), canonical(post.doc), 'redo reproduces the split bytes');

  // explicit split bar
  const doc2 = makeDoc();
  const st2 = makeState(doc2);
  const explicit = commands.splitSceneCommand(doc2, 'scene-01', st2.layout, { kind: 'bars', bar: 5 }, BAR_TIMES).apply(st2);
  assert.equal(explicit.doc.scenes[0].anchor.end_bar, 5);
  assert.equal(explicit.doc.scenes[1].anchor.start_bar, 5);
  assertValid(explicit.doc, 'explicit split');

  // degenerate: a one-bar scene cannot split
  const doc3 = makeDoc();
  doc3.scenes = [scene(1, 1, 2, 0, 2, 'cut')];
  const st3 = makeState(doc3);
  const noop = commands.splitSceneCommand(doc3, 'scene-01', st3.layout, undefined, BAR_TIMES).apply(st3);
  assert.equal(noop, st3, 'one-bar scene refuses to split');
}

/* ------------------------------------------------------------------ */
/* merge                                                               */

{
  const doc = makeDoc();
  const h = makeHistory(makeState(doc));
  const pre = h.state;

  h.commit(commands.mergeSceneCommand(pre.doc, 'scene-03', pre.layout));

  const post = h.state;
  assert.equal(post.doc.scenes.length, 2, 'merge removes one scene');
  assertCoverage(post.doc);
  assertValid(post.doc, 'after merge');
  const merged = post.doc.scenes[1];
  assert.equal(merged.id, 'scene-02', 'merged scene keeps the predecessor identity');
  assert.equal(merged.end_time, 48, 'merged scene spans both anchors');
  assert.equal(merged.transition_out, 'hold-through', 'merged scene inherits the removed scene transition');
  assert.deepEqual(
    merged.layers.map((l) => l.id),
    ['lay-02', 'scene-03-lay-03'],
    'merged scene carries both layer sets',
  );
  assert.equal(post.layout.boards['scene-03'], undefined, 'merged-away board is removed');
  assert.equal(post.saveState, 'offline');

  h.undo();
  assert.equal(canonical(h.state.doc), canonical(pre.doc), 'undo restores the pre-merge document');
  assert.deepEqual(h.state.layout, pre.layout, 'undo restores the pre-merge layout');
  h.redo();
  assert.equal(canonical(h.state.doc), canonical(post.doc), 'redo reproduces the merge');

  // colliding layer ids are remapped deterministically
  const doc2 = makeDoc();
  doc2.scenes[1].layers.push(layer('lay-03')); // collides with scene-03's layer
  const st2 = makeState(doc2);
  const merged2 = commands.mergeSceneCommand(doc2, 'scene-03', st2.layout).apply(st2);
  const ids = merged2.doc.scenes[1].layers.map((l) => l.id).sort();
  assert.ok(ids.includes('scene-03-lay-03'), `merged source gains a deterministic scene prefix: ${ids.join(', ')}`);
  assert.equal(new Set(ids).size, ids.length, 'merged layer ids stay unique');

  // merging the first scene is a no-op
  const doc3 = makeDoc();
  const st3 = makeState(doc3);
  assert.equal(commands.mergeSceneCommand(doc3, 'scene-01', st3.layout).apply(st3), st3);
}

/* ------------------------------------------------------------------ */
/* split + merge composition round-trip                                */

{
  const doc = makeDoc();
  const h = makeHistory(makeState(doc));
  const pre = h.state;
  h.commit(commands.splitSceneCommand(pre.doc, 'scene-01', pre.layout, undefined, BAR_TIMES));
  h.commit(commands.mergeSceneCommand(h.state.doc, 'scene-01-b', h.state.layout));
  h.undo();
  h.undo();
  assert.equal(canonical(h.state.doc), canonical(pre.doc), 'split then merge undoes to the original');
}

/* ------------------------------------------------------------------ */
/* layer crop / lock / visibility / rename                             */

{
  const doc = makeDoc();
  const h = makeHistory(makeState(doc));
  const pre = h.state;

  h.commit(commands.setLayerCropCommand(pre.doc, 'scene-01', 'lay-01', { left: 0.1, top: 0.2, right: 0.9, bottom: 0.8 }));
  assert.deepEqual(h.state.doc.scenes[0].layers[0].transform.crop, { left: 0.1, top: 0.2, right: 0.9, bottom: 0.8 });
  assertValid(h.state.doc, 'after crop');
  h.undo();
  assert.equal(h.state.doc.scenes[0].layers[0].transform.crop, undefined, 'undo restores no crop');
  assert.equal(canonical(h.state.doc), canonical(pre.doc));

  h.commit(commands.toggleLayerLockedCommand(pre.doc, 'scene-01', 'lay-01'));
  assert.equal(h.state.doc.scenes[0].layers[0].locked, true);
  h.commit(commands.toggleLayerVisibleCommand(pre.doc, 'scene-01', 'lay-01'));
  assert.equal(h.state.doc.scenes[0].layers[0].visible, false);
  h.commit(commands.renameSceneCommand(pre.doc, 'scene-01', 'Scene 01', 'Cold Open'));
  assert.equal(h.state.doc.scenes[0].title, 'Cold Open');
  assertValid(h.state.doc, 'after rename');
  h.undo();
  assert.equal(h.state.doc.scenes[0].title, 'Scene 01');
  h.undo();
  assert.equal(h.state.doc.scenes[0].layers[0].visible, true);
  h.undo();
  assert.equal(h.state.doc.scenes[0].layers[0].locked, false);
}

/* ------------------------------------------------------------------ */
/* ratio switch                                                        */

{
  const doc = makeDoc();
  const h = makeHistory(makeState(doc));
  const pre = h.state;

  h.commit(commands.setPrimaryRatioCommand(pre.doc, '9:16'));
  assert.equal(h.state.doc.composition.primary_ratio, '9:16');
  assert.equal(h.state.doc.composition.width, 1080);
  assert.equal(h.state.doc.composition.height, 1920);
  assert.equal(canonical({ ...h.state.doc, composition: pre.doc.composition }), canonical({ ...pre.doc, composition: pre.doc.composition }), 'ratio switch never touches timing or scenes');
  assertValid(h.state.doc, 'after 9:16 switch');

  h.commit(commands.setPrimaryRatioCommand(h.state.doc, '1:1'));
  assert.equal(h.state.doc.composition.width, 1080);
  assertValid(h.state.doc, 'after 1:1 switch');

  h.undo();
  h.undo();
  assert.equal(canonical(h.state.doc), canonical(pre.doc), 'ratio switches undo back');
}

/* ------------------------------------------------------------------ */
/* board scale / move: workspace only, transport never touched         */

{
  const doc = makeDoc();
  const st = makeState(doc);
  const transportBefore = st.transport;

  const box1 = st.layout.boards['scene-01'];
  const moved = commands.moveBoardCommand('scene-01', { x: box1.x, y: box1.y }, { x: 42, y: 77 }).apply(st);
  assert.deepEqual(moved.transport, transportBefore, 'board move leaves transport values untouched');
  assert.equal(moved.transport, transportBefore, 'board move keeps the transport object identity');
  assert.equal(moved.layout.boards['scene-01'].x, 42);
  assert.equal(moved.layout.boards['scene-01'].y, 77);
  assert.equal(moved.doc, st.doc, 'board move never forks the document');
  assert.deepEqual(
    commands.moveBoardCommand('scene-01', { x: box1.x, y: box1.y }, { x: 42, y: 77 }).invert().apply(moved).layout.boards['scene-01'],
    box1,
    'move undo restores the board box',
  );

  const box = st.layout.boards['scene-02'];
  const scaled = commands.scaleBoardCommand('scene-02', { w: box.w, bodyH: box.bodyH }, { w: box.w * 1.5, bodyH: box.bodyH * 1.5 }).apply(st);
  assert.deepEqual(scaled.transport, transportBefore, 'board scale leaves transport values untouched');
  assert.equal(scaled.layout.boards['scene-02'].w, box.w * 1.5);
  const unscaled = commands.scaleBoardCommand('scene-02', { w: box.w, bodyH: box.bodyH }, { w: box.w * 1.5, bodyH: box.bodyH * 1.5 }).invert().apply(scaled);
  assert.deepEqual(unscaled.layout.boards['scene-02'], box, 'scale undo restores the board box');
}

/* ------------------------------------------------------------------ */
/* deterministic layout derivation                                     */

{
  const doc = makeDoc();
  const filled = layout.fillLayoutSlots(doc);
  const again = layout.fillLayoutSlots(doc);
  assert.deepEqual(again, filled, 'slot fill is deterministic');
  assert.deepEqual(Object.keys(filled.boards).sort(), ['scene-01', 'scene-02', 'scene-03'], 'every scene gets a board');
  const b1 = filled.boards['scene-01'];
  const b2 = filled.boards['scene-02'];
  assert.ok(b2.x > b1.x && b2.y === b1.y, 'chronological slots fill row-major');

  const prev = { boards: { 'scene-01': { x: 5, y: 6, w: 7, bodyH: 8, rotation: 9 } } };
  const kept = layout.fillLayoutSlots(doc, prev);
  assert.deepEqual(kept.boards['scene-01'], prev.boards['scene-01'], 'existing boards are kept');
  assert.ok(kept.boards['scene-02'], 'missing boards are filled');
  assert.equal(kept.boards['scene-01'].rotation, 9);
}

/* ------------------------------------------------------------------ */
/* composite command                                                   */

{
  const doc = makeDoc();
  const h = makeHistory(makeState(doc));
  const pre = h.state;
  h.commit(
    commands.compositeCommand('Agent apply', [
      commands.renameSceneCommand(pre.doc, 'scene-01', 'Scene 01', 'Cold Open'),
      commands.moveBoardCommand('scene-02', { x: h.state.layout.boards['scene-02'].x, y: h.state.layout.boards['scene-02'].y }, { x: 10, y: 10 }),
    ]),
  );
  assert.equal(h.state.doc.scenes[0].title, 'Cold Open');
  assert.equal(h.state.layout.boards['scene-02'].x, 10);
  h.undo();
  assert.equal(canonical(h.state.doc), canonical(pre.doc), 'composite undo restores the document');
  assert.deepEqual(h.state.layout, pre.layout, 'composite undo restores the layout');
}

/* deleting one shared asset marks every reference in one undo step */
{
  const doc = makeDoc();
  const assetId = 'ab'.repeat(32);
  doc.scenes[0].layers[0].props.src = `asset:${assetId}`;
  doc.scenes[1].layers[0].props.src = `asset:${assetId}`;
  const h = makeHistory(makeState(doc));
  h.commit(commands.markAssetMissingCommand(h.state.doc, assetId));
  assert.equal(h.state.doc.scenes[0].layers[0].props.src, `missing-asset:${assetId}`);
  assert.equal(h.state.doc.scenes[1].layers[0].props.src, `missing-asset:${assetId}`);
  // A single undo must restore every affected reference, proving this is one
  // history transaction rather than one command per layer.
  h.undo();
  assert.equal(h.state.doc.scenes[0].layers[0].props.src, `asset:${assetId}`);
  assert.equal(h.state.doc.scenes[1].layers[0].props.src, `asset:${assetId}`);
}


/* ------------------------------------------------------------------ */
/* response-chain commands (Round 3 magnetic chain edits)              */

{
  const doc = makeDoc();
  const h = makeHistory(makeState(doc));
  const pre = h.state;
  const chain = {
    id: 'response-99',
    target_layer_id: 'lay-01',
    label: 'High onsets → blur focus',
    driver: { kind: 'ranked_onsets', band: 'high', tier: 'primary', max_events_per_bar: 3, refractory_beats: 0.4 },
    motion: { kind: 'blur_focus', amount: 2, attack_seconds: 0.04, release_seconds: 0.3 },
  };
  h.commit(commands.addResponseCommand(h.state.doc, 'scene-01', chain));
  assert.equal(h.state.doc.scenes[0].responses.length, 2, 'chain is appended');
  assert.equal(h.state.doc.scenes[0].responses[1].id, 'response-99');
  assertValid(h.state.doc, 'add response');
  h.undo();
  assert.equal(canonical(h.state.doc), canonical(pre.doc), 'undo restores the pre-chain bytes');
  h.redo();
  assert.equal(h.state.doc.scenes[0].responses[1].id, 'response-99', 'redo restores the chain');

  // changing the driver never rewrites the motion (§5.3)
  const motionBefore = JSON.stringify(h.state.doc.scenes[0].responses[1].motion);
  h.commit(
    commands.setResponseDriverCommand(h.state.doc, 'scene-01', 'response-99', {
      kind: 'energy_envelope',
      band: 'mid',
    }),
  );
  assert.equal(JSON.stringify(h.state.doc.scenes[0].responses[1].motion), motionBefore, 'driver change keeps the motion');
  assert.equal(h.state.doc.scenes[0].responses[1].driver.kind, 'energy_envelope');
  h.undo();
  assert.equal(h.state.doc.scenes[0].responses[1].driver.kind, 'ranked_onsets', 'driver change is reversible');

  // changing the motion never rewrites evidence selection
  const driverBefore = JSON.stringify(h.state.doc.scenes[0].responses[1].driver);
  h.commit(
    commands.setResponseMotionCommand(h.state.doc, 'scene-01', 'response-99', {
      kind: 'invert_palette',
      amount: 1,
      attack_seconds: 0.01,
      release_seconds: 0.12,
    }),
  );
  assert.equal(JSON.stringify(h.state.doc.scenes[0].responses[1].driver), driverBefore, 'motion change keeps the driver');
  h.undo();
  assert.equal(h.state.doc.scenes[0].responses[1].motion.kind, 'blur_focus', 'motion change is reversible');

  // assigning a chain to a layer that does not exist is refused
  h.commit(commands.assignResponseLayerCommand(h.state.doc, 'scene-01', 'response-99', 'lay-missing'));
  assert.equal(h.state.doc.scenes[0].responses[1].target_layer_id, 'lay-01', 'invalid assignment is refused');

  // removal restores position on undo, and redo removes it again
  h.commit(commands.removeResponseCommand(h.state.doc, 'scene-01', 'response-99'));
  assert.equal(h.state.doc.scenes[0].responses.length, 1, 'chain removed');
  h.undo();
  assert.equal(h.state.doc.scenes[0].responses[1].id, 'response-99', 'undo re-inserts at the original index');
  assertValid(h.state.doc, 'remove/insert response');
  h.redo();
  assert.equal(h.state.doc.scenes[0].responses.length, 1, 'redo removes it again');
  h.undo();
  const restored = canonical(h.state.doc);
  assert.equal(h.state.doc.scenes[0].responses[1].id, 'response-99', 'chain is back after the second undo');
  h.commit(commands.removeResponseCommand(h.state.doc, 'scene-01', 'response-99'));
  h.undo();
  assert.equal(canonical(h.state.doc), restored, 'remove/undo is byte-identical on repeat');
}

console.log('direction commands: split/merge/ratio/crop/lock/scale/move/layout/chain round-trips agree with the contract');
