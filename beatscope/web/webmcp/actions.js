/**
 * Director action tools (v0.10 plan sections 13-15).
 *
 * Actions are the only place where a tool changes the page. Each action
 * validates every input FIRST, then commits its mutations in one pass, so a
 * rejected call leaves the page byte-identical (plan section 5.4). Player
 * and UI capabilities arrive through injected adapters; state mutations go
 * through the shared store so the user's next view and the Agent's next
 * query read the same truth.
 *
 * deps = {
 *   getState,             // () => live state
 *   hasAudio,             // () => boolean (audio element with a source)
 *   seek, play, pause,    // player adapters
 *   readAudioTime,        // () => audio element currentTime
 *   setFollowPlayback,    // (enabled) => void, unchecks the checkbox
 *   scrollPlayerIntoView, // () => void, respects reduced motion
 * }
 */

import {
  setAgentFocus,
  clearAgentFocus,
  setStartBar,
  setLoopSelection,
  setLoopEnabled,
  appendAgentAction,
  pushAgentUndo,
  popAgentUndo,
} from '../state.js';
import { timeAtBar, metrics } from '../grid.js';
import { WebMcpError, round4, sanitizeLine, barSpanLabel } from './responses.js';
import { barRange, previousBeatTime, storedBeatTime } from './queries.js';

function requireProject(state) {
  if (!state.project) throw new WebMcpError('NO_TRACK');
  return state.project;
}

function barsOf(project) {
  return Math.max(0, Math.floor(Number(project?.grid?.bars) || 0));
}

function trackDuration(project) {
  return Math.max(0, Number(project?.source?.duration) || 0);
}

function timeSignatureBeatsPerBar(project) {
  const meter = project?.meter || {};
  return Math.max(1, Math.min(32, Math.floor(Number(meter.beats_per_bar ?? meter.beatsPerBar) || 4)));
}

/** Snapshot taken BEFORE an action mutates anything (plan section 24, Phase 3). */
function snapshotOf(state) {
  return {
    focus: state.agentFocus ? { ...state.agentFocus } : null,
    startBar: state.startBar,
    loop: state.loop,
    loopSelection: state.loopSelection ? { ...state.loopSelection } : null,
    playbackTime: state.playbackTime,
    isPlaying: state.isPlaying,
  };
}

/** Deterministic ledger labels for every tool (bounded, no raw input echo). */
export function ledgerEntryFor(toolName, input = {}) {
  switch (toolName) {
    case 'get_project_context':
      return { kind: 'inspect_context', label: 'Inspected project context' };
    case 'get_state_at_time':
      return { kind: 'inspect_state', label: 'Inspected state at one moment' };
    case 'get_events': {
      const bars = input.startBar !== undefined && input.endBar !== undefined
        ? ` in ${barSpanLabel(Number(input.startBar), Number(input.endBar))}`
        : '';
      return { kind: 'inspect_events', label: `Inspected events${bars || ' in a bounded window'}` };
    }
    case 'find_visual_moments':
      return { kind: 'find_moments', label: 'Found visual moment candidates' };
    case 'compare_ranges': {
      const ranges = Array.isArray(input.ranges) ? input.ranges : [];
      const first = ranges[0];
      const last = ranges[ranges.length - 1];
      const span = first && last
        ? ` ${barSpanLabel(Number(first.startBar), Number(last.endBar))}`
        : '';
      return { kind: 'compare_ranges', label: `Compared${span || ' ranges'}` };
    }
    case 'focus_range':
      return {
        kind: 'focus_range',
        label: `Focused ${barSpanLabel(Number(input.startBar), Number(input.endBar))}`,
      };
    case 'control_playback': {
      const action = String(input.action || 'play');
      if (action === 'pause') return { kind: 'control_playback', label: 'Paused playback' };
      if (action === 'play') return { kind: 'control_playback', label: 'Started playback' };
      const at = input.bar !== undefined ? `bar ${Number(input.bar)}` : `${round4(input.time)}s`;
      return { kind: 'control_playback', label: `Sought to ${at}` };
    }
    case 'set_loop_range':
      return input.enabled
        ? {
          kind: 'set_loop_range',
          label: `Looped ${barSpanLabel(Number(input.startBar), Number(input.endBar))}`,
        }
        : { kind: 'set_loop_range', label: 'Stopped looping' };
    default:
      return { kind: 'inspect_context', label: 'Used BeatScope Director' };
  }
}

// ---------------------------------------------------------------------------
// Tool 6: focus_range (plan section 13). Selects and shows; never plays.
// ---------------------------------------------------------------------------

export function focusRange(deps, input = {}) {
  const state = deps.getState();
  const project = requireProject(state);

  const startBar = Number(input.startBar);
  const endBar = Number(input.endBar);
  if (!Number.isInteger(startBar) || !Number.isInteger(endBar) || endBar < startBar) {
    throw new WebMcpError('INVALID_RANGE', 'Bar ranges need 1 <= startBar <= endBar.');
  }
  const bars = barsOf(project);
  if (bars < 1 || startBar < 1 || endBar > bars) {
    throw new WebMcpError('OUT_OF_RANGE', `The track has ${bars} bar(s).`);
  }
  const reason = sanitizeLine(input.reason, 120);
  if (!reason) throw new WebMcpError('INVALID_RANGE', 'A non-empty reason is required.');

  const startTime = Number(timeAtBar(startBar, project, state.adjustments)) || 0;
  const endTime = endBar >= bars
    ? trackDuration(project)
    : Number(timeAtBar(endBar + 1, project, state.adjustments)) || startTime;

  pushAgentUndo(snapshotOf(state));
  setStartBar(Math.floor((startBar - 1) / Math.max(1, state.viewBars)) * Math.max(1, state.viewBars));
  if (typeof deps.setFollowPlayback === 'function') deps.setFollowPlayback(false);
  setAgentFocus({
    startTime,
    endTime,
    startBar,
    endBar,
    reason,
    source: 'webmcp',
    createdAt: Date.now(), // Ledger display only; never read by queries or rendering.
  });
  appendAgentAction(ledgerEntryFor('focus_range', { startBar, endBar }));
  if (typeof deps.scrollPlayerIntoView === 'function') deps.scrollPlayerIntoView();

  return {
    ok: true,
    focus: {
      startBar,
      endBar,
      startTime: round4(startTime),
      endTime: round4(endTime),
      reason,
    },
    message: `Focused bars ${startBar}\u2013${endBar} in the BeatScope timeline. Playback was not changed.`,
  };
}

// ---------------------------------------------------------------------------
// Tool 7: control_playback (plan section 14). Idempotent transport control.
// ---------------------------------------------------------------------------

export async function controlPlayback(deps, input = {}) {
  const state = deps.getState();
  const project = requireProject(state);

  const action = input.action;
  if (!['play', 'pause', 'seek', 'seek_and_play'].includes(action)) {
    throw new WebMcpError('INVALID_RANGE', 'action must be play, pause, seek, or seek_and_play.');
  }
  const wantsPosition = action === 'seek' || action === 'seek_and_play';
  const carriesPosition = input.time !== undefined || input.bar !== undefined
    || input.beat !== undefined || input.preRollBeats !== undefined;
  if (!wantsPosition && carriesPosition) {
    throw new WebMcpError('INVALID_RANGE', 'play and pause take no position fields.');
  }
  if (wantsPosition && input.time !== undefined && input.bar !== undefined) {
    throw new WebMcpError('INVALID_RANGE', 'Give a time or a bar, never both.');
  }
  if (typeof deps.hasAudio === 'function' && !deps.hasAudio()) {
    throw new WebMcpError('PLAYBACK_UNAVAILABLE');
  }

  if (action === 'play' || action === 'pause') {
    pushAgentUndo(snapshotOf(state));
    if (action === 'pause') {
      deps.pause();
      appendAgentAction(ledgerEntryFor('control_playback', { action }));
      return { ok: true, action, playing: false, requiresUserGesture: false };
    }
    const started = await deps.play();
    appendAgentAction(ledgerEntryFor('control_playback', { action }));
    return {
      ok: true,
      action,
      playing: Boolean(started),
      requiresUserGesture: !started,
    };
  }

  const duration = trackDuration(project);
  const hasStoredBeats = Array.isArray(project.beats) && project.beats.length > 0;
  const timingSource = hasStoredBeats ? 'stored-beats' : 'synthetic-grid';
  const preRoll = input.preRollBeats === undefined
    ? 0
    : Math.max(0, Math.min(16, Math.floor(Number(input.preRollBeats) || 0)));

  let targetTime;
  let seekTime;
  if (input.time !== undefined) {
    const requested = Number(input.time);
    if (!Number.isFinite(requested) || requested < 0) {
      throw new WebMcpError('INVALID_RANGE', 'time must be a finite number of seconds.');
    }
    targetTime = Math.max(0, Math.min(requested, duration));
    if (preRoll > 0 && hasStoredBeats) {
      seekTime = previousBeatTime(project, targetTime, preRoll).time;
    } else if (preRoll > 0) {
      const beatLength = 60 / (Number(project?.tempo?.global_bpm ?? project?.tempo?.bpm) || 120);
      seekTime = Math.max(0, targetTime - preRoll * beatLength);
    } else {
      seekTime = targetTime;
    }
  } else if (input.bar !== undefined) {
    const bar = Number(input.bar);
    const beat = input.beat === undefined ? 1 : Number(input.beat);
    if (!Number.isInteger(bar) || !Number.isInteger(beat) || bar < 1) {
      throw new WebMcpError('INVALID_RANGE', 'bar and beat must be integers.');
    }
    if (barsOf(project) < 1 || bar > barsOf(project)) {
      throw new WebMcpError('OUT_OF_RANGE', `The track has ${barsOf(project)} bar(s).`);
    }
    if (beat < 1 || beat > timeSignatureBeatsPerBar(project)) {
      throw new WebMcpError(
        'OUT_OF_RANGE',
        `Beat ${beat} does not exist in a ${timeSignatureBeatsPerBar(project)}/4 bar.`,
      );
    }
    const stored = hasStoredBeats ? storedBeatTime(project, bar, beat) : null;
    if (stored !== null) {
      targetTime = stored;
      if (preRoll > 0) {
        seekTime = previousBeatTime(project, targetTime, preRoll).time;
      } else {
        seekTime = targetTime;
      }
    } else {
      // Beat-less project: the runtime's synthetic grid is the only honest clock.
      const gridTime = Number(timeAtBar(bar, project, state.adjustments)) || 0;
      const bpm = Number(project?.tempo?.global_bpm ?? project?.tempo?.bpm) || 120;
      targetTime = gridTime + (beat - 1) * (60 / bpm);
      seekTime = Math.max(0, targetTime - preRoll * (60 / bpm));
      targetTime = Math.min(targetTime, duration);
    }
  } else {
    throw new WebMcpError('INVALID_RANGE', 'seek needs a time or a bar.');
  }

  seekTime = Math.max(0, Math.min(seekTime, duration));
  // The undo snapshot lands only after every seek input resolved cleanly, so
  // a rejected call leaves even the undo stack untouched (plan section 5.4).
  pushAgentUndo(snapshotOf(state));
  deps.seek(seekTime);

  let playing = false;
  let requiresUserGesture = false;
  if (action === 'seek_and_play') {
    const started = await deps.play();
    playing = Boolean(started);
    requiresUserGesture = !started;
  } else {
    playing = Boolean(deps.isPlaying ? deps.isPlaying() : state.isPlaying);
  }

  appendAgentAction(ledgerEntryFor('control_playback', input));
  return {
    ok: true,
    action,
    targetTime: round4(targetTime),
    seekTime: round4(seekTime),
    preRollBeats: preRoll,
    timingSource,
    currentTime: round4(deps.readAudioTime ? deps.readAudioTime() : seekTime),
    playing,
    requiresUserGesture,
  };
}

// ---------------------------------------------------------------------------
// Tool 8: set_loop_range (plan section 15). Loop only; never seeks or plays.
// ---------------------------------------------------------------------------

export function setLoopRange(deps, input = {}) {
  const state = deps.getState();
  const project = requireProject(state);

  if (typeof input.enabled !== 'boolean') {
    throw new WebMcpError('INVALID_RANGE', 'enabled must be a boolean.');
  }

  // Pure validation first: barRange throws before anything is snapshotted.
  let range = null;
  if (input.enabled) {
    if (input.startBar === undefined || input.endBar === undefined) {
      throw new WebMcpError('INVALID_RANGE', 'enabled=true requires startBar and endBar.');
    }
    range = barRange({ project, adjustments: state.adjustments }, input.startBar, input.endBar);
  }

  pushAgentUndo(snapshotOf(state));

  if (!input.enabled) {
    setLoopEnabled(false);
    appendAgentAction(ledgerEntryFor('set_loop_range', { enabled: false }));
    const selection = state.loopSelection;
    let startTime = null;
    let endTime = null;
    let startBar = null;
    let endBar = null;
    if (selection) {
      const timing = metrics(project, state.subdivision, state.adjustments);
      startBar = Math.floor(selection.start / state.subdivision) + 1;
      endBar = Math.floor((selection.end + 1) / state.subdivision);
      startTime = round4(timing.origin + selection.start * timing.step);
      endTime = round4(timing.origin + (selection.end + 1) * timing.step);
    }
    return {
      ok: true,
      loop: { enabled: false, startBar, endBar, startTime, endTime },
      message: 'Loop stopped. The range is kept for later.',
    };
  }

  const subdivision = Math.max(1, Math.floor(Number(state.subdivision) || 16));
  const startStep = (range.startBar - 1) * subdivision;
  const endStep = range.endBar * subdivision - 1;

  setLoopSelection({ start: startStep, end: endStep });
  setLoopEnabled(true);
  appendAgentAction(ledgerEntryFor('set_loop_range', { enabled: true, ...range }));

  return {
    ok: true,
    loop: {
      enabled: true,
      startBar: range.startBar,
      endBar: range.endBar,
      startTime: round4(range.startTime),
      endTime: round4(range.endTime),
    },
    message: `Looping bars ${range.startBar}\u2013${range.endBar}.`,
  };
}

// ---------------------------------------------------------------------------
// Undo (plan section 24, Phase 3): page state only, never the project file.
// ---------------------------------------------------------------------------

export async function undoLastAgentAction(deps) {
  const state = deps.getState();
  const snapshot = popAgentUndo();
  if (!snapshot) return { ok: false, undone: false };

  if (snapshot.focus) setAgentFocus(snapshot.focus);
  else clearAgentFocus();
  setStartBar(snapshot.startBar);
  if (snapshot.loopSelection) setLoopSelection(snapshot.loopSelection);
  setLoopEnabled(Boolean(snapshot.loop));
  if (typeof deps.seek === 'function') deps.seek(snapshot.playbackTime);
  if (snapshot.isPlaying && typeof deps.play === 'function') await deps.play();
  else if (!snapshot.isPlaying && typeof deps.pause === 'function') deps.pause();
  appendAgentAction({ kind: 'undo', label: 'Undid the last agent action' });
  return { ok: true, undone: true };
}
