/**
 * BeatScope single state store and event emitter.
 */

import { trackForProject } from '../runtime/runtime.js';

export const state = {
  project: null,
  projectId: null,
  subdivision: 16,
  viewBars: 8,
  startBar: 0,
  selectedOnset: null,
  selectedCell: null,
  loop: false,
  playbackTime: 0,
  isPlaying: false,
  activeJob: null,
  adjustments: { bpm: null, origin: null },
  hoverStep: null,
  loopSelection: null,
  // Director collaboration state (v0.10 plan sections 5.2-5.3): written only
  // through the explicit mutations below, read by WebMCP queries and the UI.
  agentFocus: null,
  agentActions: [],
  agentUndo: [],
};

const listeners = new Set();

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notify(event, payload) {
  listeners.forEach((fn) => {
    try {
      fn(event, payload, state);
    } catch (err) {
      console.error('State listener error:', err);
    }
  });
}

export function setProject(project, projectId = null) {
  state.project = project;
  state.projectId = projectId || project.project_id || null;
  state.startBar = 0;
  state.selectedOnset = null;
  state.selectedCell = null;
  state.loopSelection = null;
  state.playbackTime = 0;
  // A new project invalidates Agent collaboration state (plan 18.2 #14):
  // focus, ledger, and undo snapshots all describe the previous track.
  state.agentFocus = null;
  state.agentActions = [];
  state.agentUndo = [];
  state.adjustments = {
    bpm: project?.tempo?.global_bpm || project?.tempo?.bpm || null,
    origin: project?.grid?.origin ?? null,
  };
  state.subdivision = project?.grid?.default_subdivision || 16;
  state.runtimeTrack = trackForProject(project);
  notify('projectLoaded', state.project);
}

export function setJob(job) {
  state.activeJob = job;
  notify('jobUpdated', job);
}

export function updateAdjustments(bpm, origin) {
  if (bpm !== undefined) state.adjustments.bpm = bpm ? Number(bpm) : null;
  if (origin !== undefined) state.adjustments.origin = origin !== null ? Number(origin) : null;
  notify('adjustmentsChanged', state.adjustments);
}

export function setSubdivision(subdiv) {
  state.subdivision = Number(subdiv);
  notify('subdivisionChanged', state.subdivision);
}

export function setViewBars(bars) {
  state.viewBars = Number(bars);
  notify('viewBarsChanged', state.viewBars);
}

export function setStartBar(bar) {
  const maxBar = Math.max(0, (state.project?.grid?.bars || 1) - state.viewBars);
  state.startBar = Math.max(0, Math.min(bar, maxBar));
  notify('startBarChanged', state.startBar);
}

export function setSelectedOnset(onset, cellInfo = null) {
  state.selectedOnset = onset;
  state.selectedCell = cellInfo;
  notify('selectionChanged', { onset, cellInfo });
}

export function setPlayback(time, isPlaying) {
  state.playbackTime = time;
  if (isPlaying !== undefined) state.isPlaying = isPlaying;
  notify('playbackUpdated', { time, isPlaying: state.isPlaying });
}

export function toggleLoop() {
  return setLoopEnabled(!state.loop);
}

// --- Director mutations (v0.10 plan section 15.3) ---------------------------
// One mutation per concern; every UI control and every Agent action goes
// through these so the store stays the single source of truth.

const MAX_LEDGER_ENTRIES = 8;
const MAX_UNDO_SNAPSHOTS = 8;
let agentActionSequence = 0;

export function setLoopSelection(selection) {
  state.loopSelection = selection
    ? { start: Math.max(0, Math.floor(Number(selection.start) || 0)), end: Math.max(0, Math.floor(Number(selection.end) || 0)) }
    : null;
  notify('loopSelectionChanged', state.loopSelection);
}

export function setLoopEnabled(enabled) {
  state.loop = Boolean(enabled);
  notify('loopToggled', state.loop);
  return state.loop;
}

export function setAgentFocus(focus) {
  state.agentFocus = focus ? { ...focus } : null;
  notify('agentFocusChanged', state.agentFocus);
}

export function clearAgentFocus() {
  state.agentFocus = null;
  notify('agentFocusChanged', null);
}

export function appendAgentAction(action) {
  agentActionSequence += 1;
  state.agentActions = [
    ...state.agentActions.slice(-(MAX_LEDGER_ENTRIES - 1)),
    {
      id: agentActionSequence,
      kind: String(action?.kind || 'unknown'),
      label: String(action?.label || 'Unknown action'),
      at: Date.now(), // Ledger display only; never part of a tool response.
    },
  ];
  notify('agentActionsChanged', state.agentActions);
}

export function pushAgentUndo(snapshot) {
  state.agentUndo = [
    ...state.agentUndo.slice(-(MAX_UNDO_SNAPSHOTS - 1)),
    snapshot,
  ];
}

export function popAgentUndo() {
  const snapshot = state.agentUndo.length ? state.agentUndo[state.agentUndo.length - 1] : null;
  if (snapshot) state.agentUndo = state.agentUndo.slice(0, -1);
  return snapshot;
}
