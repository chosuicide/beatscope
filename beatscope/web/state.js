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
  state.loop = !state.loop;
  notify('loopToggled', state.loop);
  return state.loop;
}
