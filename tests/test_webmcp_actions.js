/**
 * Director action-tool contract tests (v0.10 plan sections 13-15, 18.2).
 *
 * Actions run against the real state.js store and fake player adapters:
 * they validate every input before the first mutation, drive the shared
 * store (not a private copy), and stay reversible through the undo stack.
 */
import assert from 'node:assert/strict';

import {
  focusRange,
  controlPlayback,
  setLoopRange,
  undoLastAgentAction,
  ledgerEntryFor,
} from '../beatscope/web/webmcp/actions.js';
import { WebMcpError } from '../beatscope/web/webmcp/responses.js';
import { clearAgentFocus } from '../beatscope/web/state.js';
import {
  makeStructuredProject,
  makeQuietProject,
  loadProject,
  makeFakePlayer,
  state,
  BAR,
} from './webmcp_fixtures.mjs';

function setup() {
  const project = makeStructuredProject();
  loadProject(project);
  const player = makeFakePlayer();
  return { project, player, deps: player.deps };
}

async function assertCode(callable, code) {
  try {
    await callable();
  } catch (error) {
    assert.ok(error instanceof WebMcpError, `expected WebMcpError, got ${error}`);
    assert.equal(error.code, code);
    return;
  }
  assert.fail(`expected WebMcpError ${code}`);
}

/** Everything an action may touch; used to prove rejected calls mutate nothing. */
function fingerprint() {
  return JSON.stringify({
    focus: state.agentFocus,
    actions: state.agentActions,
    undo: state.agentUndo,
    loop: state.loop,
    loopSelection: state.loopSelection,
    startBar: state.startBar,
    playbackTime: state.playbackTime,
    isPlaying: state.isPlaying,
  });
}

// --- 1. focus_range aligns the 8-bar window ---------------------------------
{
  const { deps } = setup();
  const result = focusRange(deps, { startBar: 17, endBar: 24, reason: 'transition into the chorus' });
  assert.equal(result.ok, true);
  assert.equal(state.startBar, 16);
  assert.equal(state.agentFocus.startBar, 17);
  assert.equal(state.agentFocus.endBar, 24);
  assert.equal(state.agentFocus.startTime, 16 * BAR);
  assert.equal(state.agentFocus.endTime, 24 * BAR);
  assert.equal(state.agentFocus.source, 'webmcp');
  focusRange(deps, { startBar: 9, endBar: 12, reason: 'verse' });
  assert.equal(state.startBar, 8);
}

// --- 2. two-beat pre-roll walks the stored beat array ------------------------
{
  const { deps, player } = setup();
  const result = await controlPlayback(deps, { action: 'seek', bar: 17, beat: 1, preRollBeats: 2 });
  assert.equal(result.ok, true);
  assert.equal(result.timingSource, 'stored-beats');
  assert.equal(result.targetTime, 16 * BAR);
  assert.equal(result.seekTime, 16 * BAR - 1); // two 0.5 s beats before the target
  assert.equal(result.preRollBeats, 2);
  assert.deepEqual(player.calls, [['seek', 16 * BAR - 1]]);
}

// --- 3. song-start pre-roll clamps to 0 --------------------------------------
{
  const { deps, player } = setup();
  const result = await controlPlayback(deps, { action: 'seek', bar: 1, beat: 1, preRollBeats: 2 });
  assert.equal(result.targetTime, 0);
  assert.equal(result.seekTime, 0);
  assert.deepEqual(player.calls, [['seek', 0]]);
}

// --- 4. focus_range never seeks, plays, or loops -----------------------------
{
  const { deps, player } = setup();
  focusRange(deps, { startBar: 1, endBar: 8, reason: 'intro' });
  assert.deepEqual(player.calls, [['follow', false], ['scroll']]);
  assert.equal(state.loop, false);
  assert.equal(state.playbackTime, 0);
  assert.equal(state.isPlaying, false);
}

// --- 5. seek_and_play orders seek before play --------------------------------
{
  const { deps, player } = setup();
  const result = await controlPlayback(deps, { action: 'seek_and_play', bar: 9 });
  assert.deepEqual(player.calls, [['seek', 8 * BAR], ['play']]);
  assert.equal(result.playing, true);
  assert.equal(result.requiresUserGesture, false);
  assert.equal(state.isPlaying, true);
}

// --- 6. an autoplay rejection keeps the seek ---------------------------------
{
  const { deps, player } = setup();
  player.deps.play = async () => {
    player.calls.push(['play']);
    return false;
  };
  const result = await controlPlayback(deps, { action: 'seek_and_play', bar: 9 });
  assert.deepEqual(player.calls, [['seek', 8 * BAR], ['play']]);
  assert.equal(result.playing, false);
  assert.equal(result.requiresUserGesture, true);
  assert.equal(state.playbackTime, 8 * BAR);
}

// --- 7. play and pause are idempotent ----------------------------------------
{
  const { deps, player } = setup();
  const paused = await controlPlayback(deps, { action: 'pause' });
  assert.equal(paused.ok, true);
  assert.equal(paused.playing, false);
  const pausedAgain = await controlPlayback(deps, { action: 'pause' });
  assert.equal(pausedAgain.ok, true);
  assert.deepEqual(player.calls, [['pause'], ['pause']]);
  const played = await controlPlayback(deps, { action: 'play' });
  assert.equal(played.playing, true);
  const playedAgain = await controlPlayback(deps, { action: 'play' });
  assert.equal(playedAgain.playing, true);
  await assertCode(() => controlPlayback(deps, { action: 'play', time: 4 }), 'INVALID_RANGE');
  await assertCode(() => controlPlayback(deps, { action: 'seek' }), 'INVALID_RANGE');
  await assertCode(() => controlPlayback(deps, { action: 'seek', time: 2, bar: 3 }), 'INVALID_RANGE');
}

// --- 8. loop converts bars into the inclusive step range ----------------------
{
  const { deps } = setup();
  const result = setLoopRange(deps, { enabled: true, startBar: 9, endBar: 16 });
  assert.equal(result.ok, true);
  assert.deepEqual(state.loopSelection, { start: 8 * 16, end: 16 * 16 - 1 });
  assert.equal(state.loop, true);
  assert.equal(result.loop.startTime, 8 * BAR);
  assert.equal(result.loop.endTime, 16 * BAR);
}

// --- 9. enabled=false stops looping without seeking ---------------------------
{
  const { deps, player } = setup();
  setLoopRange(deps, { enabled: true, startBar: 9, endBar: 16 });
  player.calls.length = 0;
  const stopped = setLoopRange(deps, { enabled: false });
  assert.equal(stopped.ok, true);
  assert.equal(stopped.loop.enabled, false);
  assert.equal(stopped.loop.startBar, 9);
  assert.equal(stopped.loop.endBar, 16);
  assert.deepEqual(state.loopSelection, { start: 8 * 16, end: 16 * 16 - 1 });
  assert.equal(state.loop, false);
  assert.deepEqual(player.calls, []);
}

// --- 10. failed validation mutates nothing ------------------------------------
{
  const { deps, player } = setup();
  const before = fingerprint();
  await assertCode(() => controlPlayback(deps, { action: 'seek', bar: 999 }), 'OUT_OF_RANGE');
  await assertCode(() => controlPlayback(deps, { action: 'seek', time: -1 }), 'INVALID_RANGE');
  await assertCode(() => controlPlayback(deps, { action: 'seek', bar: 3, beat: 9 }), 'OUT_OF_RANGE');
  await assertCode(() => setLoopRange(deps, { enabled: true }), 'INVALID_RANGE');
  await assertCode(() => setLoopRange(deps, { enabled: true, startBar: 1, endBar: 99 }), 'OUT_OF_RANGE');
  await assertCode(() => setLoopRange(deps, { enabled: 'yes' }), 'INVALID_RANGE');
  await assertCode(() => focusRange(deps, { startBar: 5, endBar: 3, reason: 'inverted' }), 'INVALID_RANGE');
  await assertCode(() => focusRange(deps, { startBar: 1, endBar: 8, reason: '   ' }), 'INVALID_RANGE');
  await assertCode(() => focusRange(deps, { startBar: 1, endBar: 33, reason: 'past the end' }), 'OUT_OF_RANGE');
  assert.equal(fingerprint(), before);
  assert.deepEqual(player.calls, []);
}

// --- 11. the action ledger caps at 8 entries ----------------------------------
{
  const { deps } = setup();
  for (let i = 0; i < 10; i += 1) {
    focusRange(deps, { startBar: 1, endBar: 8, reason: `take ${i}` });
  }
  assert.equal(state.agentActions.length, 8);
  assert.equal(state.agentUndo.length, 8);
  assert.equal(state.agentActions.at(-1).label, 'Focused bars 01—08');
}

// --- 12. clearing focus leaves loop and playback alone ------------------------
{
  const { deps } = setup();
  setLoopRange(deps, { enabled: true, startBar: 9, endBar: 16 });
  await controlPlayback(deps, { action: 'seek', bar: 5 });
  focusRange(deps, { startBar: 17, endBar: 24, reason: 'chorus' });
  clearAgentFocus();
  assert.equal(state.agentFocus, null);
  assert.equal(state.loop, true);
  assert.deepEqual(state.loopSelection, { start: 8 * 16, end: 16 * 16 - 1 });
  assert.equal(state.playbackTime, 4 * BAR);
}

// --- 13. undo restores page state, never the project --------------------------
{
  const project = makeStructuredProject();
  loadProject(project);
  const player = makeFakePlayer();
  focusRange(player.deps, { startBar: 9, endBar: 16, reason: 'first focus' });
  setLoopRange(player.deps, { enabled: true, startBar: 1, endBar: 8 });
  await controlPlayback(player.deps, { action: 'seek', bar: 25 });

  let result = await undoLastAgentAction(player.deps);
  assert.equal(result.undone, true);
  assert.equal(state.playbackTime, 0);
  assert.equal(state.isPlaying, false);
  assert.equal(state.loop, true);
  assert.equal(state.agentFocus.startBar, 9);

  result = await undoLastAgentAction(player.deps);
  assert.equal(state.loop, false);
  assert.equal(state.agentFocus.startBar, 9);

  result = await undoLastAgentAction(player.deps);
  assert.equal(state.agentFocus, null);
  assert.equal(state.startBar, 0);
  assert.equal(state.loop, false);
  // The project object itself is untouched by every undo.
  assert.deepEqual(state.project, project);

  result = await undoLastAgentAction(player.deps);
  assert.equal(result.ok, false);
  assert.equal(result.undone, false);
}

// --- 14. switching projects clears Agent collaboration state ------------------
{
  const { deps } = setup();
  focusRange(deps, { startBar: 1, endBar: 8, reason: 'intro' });
  await controlPlayback(deps, { action: 'play' });
  assert.ok(state.agentActions.length >= 1);
  loadProject(makeQuietProject());
  assert.equal(state.agentFocus, null);
  assert.deepEqual(state.agentActions, []);
  assert.deepEqual(state.agentUndo, []);
  assert.equal(state.isPlaying, false);
  assert.equal(state.loop, false);
}

// --- 15. ledger labels are deterministic and bounded --------------------------
{
  assert.deepEqual(ledgerEntryFor('get_project_context'), {
    kind: 'inspect_context',
    label: 'Inspected project context',
  });
  assert.deepEqual(ledgerEntryFor('control_playback', { action: 'seek', bar: 17 }), {
    kind: 'control_playback',
    label: 'Sought to bar 17',
  });
  assert.deepEqual(ledgerEntryFor('set_loop_range', { enabled: true, startBar: 9, endBar: 16 }), {
    kind: 'set_loop_range',
    label: 'Looped bars 09—16',
  });
}
