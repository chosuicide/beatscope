import { state, subscribe, setProject, setSubdivision, setStartBar, setSelectedOnset, toggleLoop, clearAgentFocus, setAgentFocusActive } from './state.js';
import { fetchProject, fetchVisualArtifacts, getAudioUrl, getMidiExportUrl, getCsvExportUrl, getCodexExportUrl } from './api.js';
import { initAudio, setAudioSource, togglePlay, seek, previewTransient, play, pause } from './audio.js';
import { renderStaticMap, renderOverlay, renderOverview, exportStaticPng, structuralSegmentAt, structureSummary } from './renderer.js';
import { createVisualStage, installVisualDebug } from './visual-stage.js';
import { updateInspector } from './inspector.js';
import { initImportHandlers, showEmptyState, showErrorState } from './import.js';
import { gridPosition, metrics, formatTime, timeAtBar } from './grid.js';
import { undoLastAgentAction } from './webmcp/actions.js';
import { installWebMCP } from './webmcp/register.js';

const $ = (selector) => document.querySelector(selector);
const app = $('#app');
const audioElement = $('#audio');
const mapStatic = $('#mapStatic');
const mapOverlay = $('#mapOverlay');
const mapStack = $('#mapStack');
const overviewCanvas = $('#overview');
const visualStageStack = $('#visualStageStack');
const visualStage = $('#visualStage');
const particleStage = $('#particleStage');
// Layered signal player (plan section 7.2): the controller owns the render
// call order; app.js keeps the single rAF loop and the audio clock.
const visualStageController = createVisualStage({ particleCanvas: particleStage, overlayCanvas: visualStage });
// Localhost-only deterministic snapshot/forcing entry (plan section 12).
if (['localhost', '127.0.0.1'].includes(window.location.hostname)) {
  window.__BEATSCOPE_VISUAL_DEBUG__ = installVisualDebug(visualStageController);
}
const seekRange = $('#seekRange');
const volumeRange = $('#volumeRange');
const followPlayback = $('#followPlayback');
const followStructureControl = $('#followStructureControl');
const followStructure = $('#followStructure');
// Agent collaboration surfaces (v0.10 plan sections 5.2-5.3).
const agentFocusReadout = $('#agentFocusReadout');
const agentFocusText = $('#agentFocusText');
const clearAgentFocusButton = $('#clearAgentFocus');
const agentCollab = $('#agentCollab');
const agentLedgerSummary = $('#agentLedgerSummary');
const agentLedgerList = $('#agentLedgerList');
const undoAgentActionButton = $('#undoAgentAction');
// Topbar WebMCP status (v0.10 plan section 5.1).
const webmcpStatus = $('#webmcpStatus');

const controls = {
  filename: $('#filename'), status: $('#status'), timecode: $('#timecode'), currentTime: $('#currentTime'),
  play: $('#play'), stagePlay: $('#stagePlay'), loop: $('#loop'), prev: $('#prev'), next: $('#next'),
  subdivision: $('#subdivision'), range: $('#rangeLabel'), window: $('#windowLabel'), visualReadout: $('#visualReadout'),
  structureReadout: $('#structureReadout'), structureHint: $('#structureHint'),
  duration: $('#durationLabel'), seekBack: $('#seekBack'), seekForward: $('#seekForward'),
  stageTrack: $('#stageTrackName'), factBpm: $('#factBpm'), factBars: $('#factBars'), factDuration: $('#factDuration'), factBackend: $('#factBackend'),
  analysisMeta: $('#analysisMeta'),
  exportMidi: $('#exportMidi'), exportCsv: $('#exportCsv'), exportPng: $('#exportPng'), exportCodex: $('#exportCodex'),
  copyPrompt: $('#copyPrompt'), copyStatus: $('#copyStatus'), openProject: $('#openProject'), projectFile: $('#projectFile'),
  replaceAudio: $('#replaceAudio'), audioInput: $('#audioFileInput'),
};

let animationFrame = null;
let mapRefreshFrame = null;
let visualStageVisible = true;
let lastOverlayFrame = 0;
let lastOverviewFrame = 0;

// v0.8 structure-following visuals (plan section 12): artifacts ride the
// project load, the preference lives only for this browser session, and the
// readout/aria labels refresh only when the scene identity changes.
const FOLLOW_STRUCTURE_KEY = 'beatscope.followStructure';
const BASE_STAGE_ARIA = 'Audio-reactive particle instrument driven by playback time';
let sceneArtifactsAvailable = false;
let artifactsLoadToken = 0;
let lastReadoutKey = null;
let lastSceneKey = null;
// Frozen WebMCP demo (v0.10 plan section 17.2): /?demo=webmcp loads a
// pre-analysed track plus its visual artifacts instead of the local API.
const staticDemoMode = document.documentElement.dataset.staticDemo === 'true';
const demoMode = staticDemoMode || new URLSearchParams(window.location.search).get('demo') === 'webmcp';
let demoArtifacts = null;

function applyStaticDemoControls() {
  if (!staticDemoMode) return;
  const dropZone = $('#dropZone');
  const selectAudio = $('#selectAudioBtn');
  const label = dropZone?.querySelector('.drop-zone-label');
  const meta = dropZone?.querySelector('.drop-zone-meta');
  if (label) label.textContent = 'Static Director demo';
  if (meta) meta.textContent = 'Included synthetic track · run BeatScope locally to analyze your own audio';
  if (dropZone) {
    dropZone.removeAttribute('role');
    dropZone.removeAttribute('tabindex');
    dropZone.removeAttribute('aria-label');
    dropZone.setAttribute('aria-disabled', 'true');
  }
  if (selectAudio) {
    selectAudio.disabled = true;
    selectAudio.textContent = 'Local Studio required';
  }
  controls.audioInput.disabled = true;
  controls.replaceAudio.disabled = true;
  controls.replaceAudio.textContent = 'Demo track';
  for (const control of [controls.exportMidi, controls.exportCsv, controls.exportCodex]) {
    control.disabled = true;
    control.title = 'Available when BeatScope Studio is running locally';
  }
}

function followStructurePreference() {
  try {
    return sessionStorage.getItem(FOLLOW_STRUCTURE_KEY) !== 'off';
  } catch (_) {
    return true;
  }
}

async function loadVisualArtifacts() {
  const token = ++artifactsLoadToken;
  let artifacts = null;
  if (demoArtifacts) {
    artifacts = demoArtifacts;
  } else {
    try {
      artifacts = await fetchVisualArtifacts(state.projectId);
    } catch (_) {
      artifacts = null;
    }
  }
  let available = false;
  try {
    visualStageController.setVisualArtifacts(artifacts?.recipe ?? null, artifacts?.timeline ?? null);
    available = Boolean(artifacts);
  } catch (_) {
    // Malformed artifacts must never take the player down; fall back to
    // the neutral legacy composition (plan section 12.1).
    visualStageController.setVisualArtifacts(null, null);
    available = false;
  }
  if (token !== artifactsLoadToken) return; // a newer project load won the race
  sceneArtifactsAvailable = available;
  lastReadoutKey = null;
  lastSceneKey = null;
  if (followStructureControl) followStructureControl.hidden = !available;
  if (available) {
    visualStageController.render(state);
    updatePlaybackUI();
  }
}

function queueMapRefresh() {
  if (mapRefreshFrame !== null) cancelAnimationFrame(mapRefreshFrame);
  mapRefreshFrame = requestAnimationFrame(() => {
    mapRefreshFrame = null;
    if (!state.project || !mapStack || mapStack.clientWidth <= 0 || mapStack.clientHeight <= 0) return;
    renderStaticMap(mapStatic, state);
    renderOverlay(mapOverlay, state);
  });
}

function setDisabled(disabled) {
  [controls.play, controls.stagePlay, controls.loop, controls.prev, controls.next, controls.exportMidi,
    controls.exportCsv, controls.exportPng, controls.exportCodex, controls.copyPrompt,
    controls.seekBack, controls.seekForward].forEach((element) => { if (element) element.disabled = disabled; });
}

let stagedProjectRef = null;

function syncStageProject() {
  if (stagedProjectRef === state.project) return;
  stagedProjectRef = state.project;
  visualStageController.setProject(state.project);
}

function renderAll() {
  syncStageProject();
  renderStaticMap(mapStatic, state);
  renderOverlay(mapOverlay, state);
  renderOverview(overviewCanvas, state);
  visualStageController.render(state);
  updateInspector(state);
}

function describeAnalysis(project) {
  const analysis = project?.analysis;
  if (!analysis || typeof analysis !== 'object') return '';
  const parts = [];
  if (analysis.backend) parts.push(`backend ${analysis.backend}`);
  if (analysis.pipeline_version) parts.push(`pipeline ${analysis.pipeline_version}`);
  const provenance = analysis.provenance && typeof analysis.provenance === 'object' ? analysis.provenance : {};
  for (const fact of ['beats', 'onsets']) {
    const method = provenance[fact]?.method;
    if (method && method !== 'unknown') parts.push(`${fact}: ${method}`);
  }
  const diagnostics = analysis.diagnostics && typeof analysis.diagnostics === 'object' ? analysis.diagnostics : {};
  if (diagnostics.migrated_from) parts.push(`migrated from ${diagnostics.migrated_from}`);
  const pregrid = Number(diagnostics.pregrid_beats_merged) || 0;
  if (pregrid > 0) parts.push(`${pregrid} pregrid beat${pregrid === 1 ? '' : 's'} merged`);
  if (analysis.separation_used) parts.push('stems separated');
  const warnings = Array.isArray(analysis.warnings) ? analysis.warnings.length : 0;
  if (warnings > 0) parts.push(`${warnings} warning${warnings === 1 ? '' : 's'}`);
  return parts.join(' · ');
}

function updateProjectUI() {
  const project = state.project;
  if (!project) {
    app.dataset.state = 'empty';
    controls.filename.textContent = 'No audio selected';
    controls.status.textContent = 'Local processing';
    controls.stageTrack.textContent = 'No track';
    controls.range.textContent = 'No track loaded';
    controls.window.textContent = '01—08';
    controls.factBpm.textContent = '—';
    controls.factBars.textContent = '—';
    controls.factDuration.textContent = '—';
    controls.factBackend.textContent = '—';
    controls.analysisMeta.hidden = true;
    controls.analysisMeta.textContent = '';
    controls.structureHint.hidden = true;
    controls.structureReadout.hidden = true;
    overviewCanvas.setAttribute('aria-label', 'Song structure and whole-track energy navigation');
    if (visualStageStack) {
      visualStageStack.setAttribute('aria-label', BASE_STAGE_ARIA);
      lastSceneKey = null;
    }
    setDisabled(true);
    refreshWebMcpStatus();
    renderAll();
    return;
  }

  app.dataset.state = 'loaded';
  const name = project.source?.display_name || project.source?.file || 'rhythm.json';
  const bars = Number(project.grid?.bars) || 1;
  const endBar = Math.min(state.startBar + state.viewBars, bars);
  const bpm = Number(project.tempo?.global_bpm || project.tempo?.bpm || 0);
  const duration = Number(project.source?.duration || 0);
  controls.filename.textContent = name;
  controls.stageTrack.textContent = name;
  controls.status.textContent = `${project.onsets?.length || 0} onsets · local`;
  controls.range.textContent = `Bars ${String(state.startBar + 1).padStart(2, '0')}—${String(endBar).padStart(2, '0')} / ${bars}`;
  controls.window.textContent = `${String(state.startBar + 1).padStart(2, '0')}—${String(endBar).padStart(2, '0')}`;
  controls.factBpm.textContent = bpm ? bpm.toFixed(1) : '—';
  controls.factBars.textContent = String(bars);
  controls.factDuration.textContent = duration ? formatTime(duration).slice(0, 5) : '—';
  controls.factBackend.textContent = project.analysis?.backend || '—';
  const analysisSummary = describeAnalysis(project);
  controls.analysisMeta.textContent = analysisSummary;
  controls.analysisMeta.hidden = !analysisSummary;
  // Accessible structure name (plan 15.3): "Song structure: A bars 1 to 8, ...";
  // falls back to the static label on legacy projects without segments.
  const structureSummaryText = structureSummary(project);
  overviewCanvas.setAttribute('aria-label', structureSummaryText || 'Song structure and whole-track energy navigation');
  controls.structureHint.hidden = !structureSummaryText;
  setDisabled(false);
  controls.prev.disabled = state.startBar <= 0;
  controls.next.disabled = state.startBar + state.viewBars >= bars;
  refreshWebMcpStatus();
  renderAll();
}

function updatePlaybackUI() {
  const formatted = formatTime(state.playbackTime);
  controls.timecode.textContent = formatted;
  controls.currentTime.textContent = formatted;
  seekRange.value = String(state.playbackTime);
  const position = state.project ? gridPosition(state.playbackTime, state.project, state.subdivision, state.adjustments) : null;
  controls.visualReadout.textContent = position ? `BAR ${String(position.bar || 1).padStart(2, '0')} · BEAT ${position.beat || 1}` : 'BAR — · BEAT —';
  // Signal player structure label (plan 15.2), extended in v0.8 (plan 12.3):
  // `A′ · 42% THROUGH · OPEN TRIAD`. The motif is visual vocabulary, not a
  // musical role, and hides first on narrow layouts (CSS).
  const structureSegments = state.project?.patterns?.segments;
  if (Array.isArray(structureSegments) && structureSegments.length) {
    const segment = structuralSegmentAt(state.project, state.playbackTime);
    if (segment) {
      const start = Number(segment.start_time) || 0;
      const end = Number(segment.end_time) || start;
      const through = Math.round(Math.max(0, Math.min(1, (state.playbackTime - start) / (end - start || 1))) * 100);
      const prefix = `${segment.display_label || segment.family || '—'} · ${through}% THROUGH`;
      const sceneFrame = sceneArtifactsAvailable
        ? visualStageController.sceneAt(state.playbackTime)
        : null;
      const sceneBlock = sceneFrame?.scene || null;
      const motif = sceneBlock?.motif ? sceneBlock.motif.toUpperCase().replaceAll('-', ' ') : '';
      const readoutKey = `${prefix}|${motif}`;
      if (readoutKey !== lastReadoutKey) {
        lastReadoutKey = readoutKey;
        const motifSpan = document.createElement('span');
        motifSpan.className = 'readout-motif';
        motifSpan.textContent = motif ? ` · ${motif}` : '';
        controls.structureReadout.replaceChildren(document.createTextNode(prefix), motifSpan);
      }
      controls.structureReadout.hidden = false;
      // Canvas aria-label (plan 12.5): family + motif when a scene is known.
      const sceneKey = sceneBlock ? `${sceneBlock.id}|${motif}` : '';
      if (sceneKey !== lastSceneKey) {
        lastSceneKey = sceneKey;
        visualStageStack.setAttribute('aria-label', sceneBlock
          ? `Audio-reactive particle instrument — scene ${sceneBlock.family}${motif ? `, ${motif}` : ''}, driven by playback time`
          : BASE_STAGE_ARIA);
      }
    } else {
      controls.structureReadout.hidden = true;
    }
  } else if (!controls.structureReadout.hidden) {
    controls.structureReadout.hidden = true;
  }
  controls.play.textContent = state.isPlaying ? 'Pause' : 'Play';
  controls.stagePlay.textContent = state.isPlaying ? 'Ⅱ' : '▶';
  controls.stagePlay.dataset.playing = state.isPlaying ? 'true' : 'false';
}

function keepWindowFollowing() {
  if (!followPlayback?.checked || !state.project) return;
  const bar = gridPosition(state.playbackTime, state.project, state.subdivision, state.adjustments).bar;
  if (bar <= 0) return;
  const target = Math.floor((bar - 1) / state.viewBars) * state.viewBars;
  if (target !== state.startBar) setStartBar(target);
}

function animate(timestamp = performance.now()) {
  if (!state.isPlaying) {
    animationFrame = null;
    return;
  }
  state.playbackTime = audioElement.currentTime || 0;
  updatePlaybackUI();
  keepWindowFollowing();
  if (timestamp - lastOverlayFrame >= 34) {
    renderOverlay(mapOverlay, state);
    lastOverlayFrame = timestamp;
  }
  if (visualStageVisible) visualStageController.render(state);
  if (timestamp - lastOverviewFrame >= 100) {
    renderOverview(overviewCanvas, state);
    lastOverviewFrame = timestamp;
  }
  animationFrame = requestAnimationFrame(animate);
}

function startAnimation() {
  if (!animationFrame) animationFrame = requestAnimationFrame(animate);
}

function stopAnimation() {
  if (animationFrame) cancelAnimationFrame(animationFrame);
  animationFrame = null;
  updatePlaybackUI();
  renderOverlay(mapOverlay, state);
  if (visualStageVisible) visualStageController.render(state);
  renderOverview(overviewCanvas, state);
}

subscribe((event, payload) => {
  if (['projectLoaded', 'startBarChanged', 'viewBarsChanged', 'subdivisionChanged', 'adjustmentsChanged'].includes(event)) {
    updateProjectUI();
    queueMapRefresh();
    if (event === 'projectLoaded') loadVisualArtifacts();
  } else if (event === 'selectionChanged') {
    updateInspector(state);
    renderOverlay(mapOverlay, state);
  } else if (event === 'playbackUpdated') {
    updatePlaybackUI();
    keepWindowFollowing();
    if (payload.isPlaying) startAnimation(); else stopAnimation();
  } else if (event === 'loopToggled') {
    controls.loop.textContent = payload ? 'Loop on' : 'Loop 8 bars';
    controls.loop.classList.toggle('is-active', payload);
  } else if (event === 'agentFocusChanged' || event === 'agentFocusActiveChanged') {
    updateAgentFocusUI();
    renderOverview(overviewCanvas, state);
  } else if (event === 'agentActionsChanged') {
    updateAgentLedgerUI();
  }
});

// --- Agent collaboration UI (v0.10 plan sections 5.2-5.4) --------------------

function updateAgentFocusUI() {
  if (!agentFocusReadout || !agentFocusText) return;
  const focus = state.agentFocus;
  if (!focus) {
    agentFocusReadout.hidden = true;
    return;
  }
  const active = state.agentFocusActive !== false;
  const bars = `BARS ${String(focus.startBar).padStart(2, '0')}—${String(focus.endBar).padStart(2, '0')}`;
  const reason = focus.reason ? focus.reason.toUpperCase() : '';
  agentFocusText.textContent = `AGENT FOCUS · ${bars}${reason ? ` · ${reason}` : ''}${active ? '' : ' · OVERRIDDEN'}`;
  agentFocusReadout.classList.toggle('is-inactive', !active);
  agentFocusReadout.hidden = false;
}

function updateAgentLedgerUI() {
  if (!agentCollab || !agentLedgerSummary || !agentLedgerList) return;
  const actions = state.agentActions;
  agentCollab.hidden = actions.length === 0;
  agentLedgerSummary.textContent = `Agent actions (${actions.length})`;
  agentLedgerList.replaceChildren(...actions.map((action, index) => {
    const row = document.createElement('li');
    const indexSpan = document.createElement('span');
    indexSpan.className = 'agent-ledger-index';
    indexSpan.textContent = String(index + 1).padStart(2, '0');
    const labelSpan = document.createElement('span');
    labelSpan.className = 'agent-ledger-label';
    labelSpan.textContent = action.label;
    row.append(indexSpan, labelSpan);
    return row;
  }));
}

// User control (plan section 5.4): clicking the overview or dragging a cue-map
// selection keeps the Agent's focus but shows it as overridden. Clear removes
// the focus only - playback, the loop, and the window selection stay put.
function markAgentFocusOverridden() {
  if (state.agentFocus && state.agentFocusActive !== false) setAgentFocusActive(false);
}

if (clearAgentFocusButton) {
  clearAgentFocusButton.onclick = () => {
    clearAgentFocus();
    renderOverview(overviewCanvas, state);
  };
}

if (undoAgentActionButton) {
  undoAgentActionButton.onclick = async () => {
    const result = await undoLastAgentAction({
      getState: () => state,
      seek: (time) => seek(time),
      play: async () => { play(); return state.isPlaying; },
      pause: () => pause(),
    });
    if (result.undone) {
      updateProjectUI();
      updatePlaybackUI();
    }
  };
}

if (mapStack && 'ResizeObserver' in window) {
  const mapResizeObserver = new ResizeObserver(() => queueMapRefresh());
  mapResizeObserver.observe(mapStack);
}

// One ResizeObserver owns stage sizing (plan section 7.3): both canvases
// update inside the controller's resize() and the paused frame is repainted.
if (visualStageStack && 'ResizeObserver' in window) {
  const stageResizeObserver = new ResizeObserver(() => visualStageController.resize());
  stageResizeObserver.observe(visualStageStack);
}

if (mapStack && 'IntersectionObserver' in window) {
  const mapVisibilityObserver = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) queueMapRefresh();
  }, { rootMargin: '180px 0px' });
  mapVisibilityObserver.observe(mapStack);
}

if (visualStage && 'IntersectionObserver' in window) {
  const visualStageObserver = new IntersectionObserver((entries) => {
    const visible = entries.some((entry) => entry.isIntersecting);
    if (visible === visualStageVisible) return;
    visualStageVisible = visible;
    visualStageController.setVisible(visible);
    if (visible && state.project) visualStageController.render(state);
  }, { rootMargin: '140px 0px' });
  visualStageObserver.observe(visualStageStack);
}

window.addEventListener('resize', queueMapRefresh, { passive: true });

function mapHit(event) {
  if (!state.project) return null;
  const rect = mapOverlay.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const left = 124;
  const right = 18;
  const top = 54;
  if (x < left || x > mapOverlay.clientWidth - right || y < top - 20) return null;
  const columns = state.viewBars * state.subdivision;
  const cellWidth = (mapOverlay.clientWidth - left - right) / columns;
  const column = Math.floor((x - left) / cellWidth);
  if (column < 0 || column >= columns) return null;
  const absoluteStep = state.startBar * state.subdivision + column;
  const matches = (state.project.onsets || [])
    .filter((onset) => gridPosition(onset.time ?? onset.raw_time, state.project, state.subdivision, state.adjustments).step === absoluteStep)
    .sort((a, b) => Number(b.strength) - Number(a.strength));
  const timing = metrics(state.project, state.subdivision, state.adjustments);
  const quantizedTime = timing.origin + absoluteStep * timing.step;
  return {
    onset: matches[0] || null,
    time: quantizedTime,
    cell: {
      step: absoluteStep,
      bar: Math.floor(absoluteStep / state.subdivision) + 1,
      beat: Math.floor((absoluteStep % state.subdivision) / (state.subdivision / 4)) + 1,
      stepInBar: (absoluteStep % state.subdivision) + 1,
      quantizedTime,
      offsetMs: 0,
    },
  };
}

if (mapOverlay) {
  let pointer = null;
  let dragging = false;
  mapOverlay.onpointerdown = (event) => {
    const hit = mapHit(event);
    if (!hit) return;
    pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, step: hit.cell.step };
    dragging = false;
    mapOverlay.setPointerCapture?.(event.pointerId);
  };
  mapOverlay.onpointermove = (event) => {
    const hit = mapHit(event);
    if (pointer && Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > 4) dragging = true;
    if (pointer && dragging && hit) {
      state.loopSelection = { start: Math.min(pointer.step, hit.cell.step), end: Math.max(pointer.step, hit.cell.step) };
      renderOverlay(mapOverlay, state);
      return;
    }
    state.hoverStep = hit?.cell.step ?? null;
    renderOverlay(mapOverlay, state);
  };
  mapOverlay.onpointerup = (event) => {
    const hit = mapHit(event);
    if (pointer && dragging) markAgentFocusOverridden();
    if (pointer && !dragging && hit) {
      setSelectedOnset(hit.onset, hit.cell);
      previewTransient(hit.onset?.time ?? hit.onset?.raw_time ?? hit.time);
    }
    try { mapOverlay.releasePointerCapture?.(event.pointerId); } catch (_) { /* already released */ }
    pointer = null;
    dragging = false;
    renderOverlay(mapOverlay, state);
  };
  mapOverlay.onpointercancel = () => { pointer = null; dragging = false; };
  mapOverlay.onpointerleave = () => { if (!pointer) { state.hoverStep = null; renderOverlay(mapOverlay, state); } };
}

overviewCanvas.onclick = (event) => {
  if (!state.project) return;
  markAgentFocusOverridden();
  const rect = overviewCanvas.getBoundingClientRect();
  const bars = Number(state.project.grid?.bars) || 1;
  const margin = 18;
  const localX = Math.max(0, Math.min(overviewCanvas.clientWidth - margin * 2, event.clientX - rect.left - margin));
  const clickedBar = Math.max(0, Math.min(bars - 1, Math.floor(localX / (overviewCanvas.clientWidth - margin * 2) * bars)));
  followPlayback.checked = false;
  setStartBar(Math.floor(clickedBar / state.viewBars) * state.viewBars);
  seek(timeAtBar(clickedBar + 1, state.project, state.adjustments));
};

controls.play.onclick = togglePlay;
controls.stagePlay.onclick = togglePlay;
controls.loop.onclick = toggleLoop;
controls.prev.onclick = () => setStartBar(state.startBar - state.viewBars);
controls.next.onclick = () => setStartBar(state.startBar + state.viewBars);
controls.subdivision.onchange = (event) => setSubdivision(Number(event.target.value));
followPlayback.onchange = () => { if (followPlayback.checked) keepWindowFollowing(); };
// FOLLOW STRUCTURE toggle (plan section 12.2): session-only preference, a
// real checkbox with accessible name/state, no artifacts are modified.
if (followStructure) {
  followStructure.checked = followStructurePreference();
  visualStageController.setFollowStructure(followStructure.checked);
  followStructure.onchange = () => {
    const enabled = Boolean(followStructure.checked);
    visualStageController.setFollowStructure(enabled);
    try {
      sessionStorage.setItem(FOLLOW_STRUCTURE_KEY, enabled ? 'on' : 'off');
    } catch (_) { /* preference is session-only by design */ }
  };
}
seekRange.oninput = (event) => seek(Number(event.target.value));
controls.seekBack.onclick = () => seek(state.playbackTime - 5);
controls.seekForward.onclick = () => seek(state.playbackTime + 5);
volumeRange.oninput = (event) => { audioElement.volume = Number(event.target.value); };
controls.replaceAudio.onclick = () => {
  if (!staticDemoMode) controls.audioInput.click();
};

audioElement.addEventListener('loadedmetadata', () => {
  seekRange.max = String(audioElement.duration || 0);
  seekRange.disabled = false;
  controls.duration.textContent = formatTime(audioElement.duration || 0);
});

controls.exportMidi.onclick = () => { if (state.project) window.location.href = getMidiExportUrl(state.projectId, state.subdivision); };
controls.exportCsv.onclick = () => { if (state.project) window.location.href = getCsvExportUrl(state.projectId, state.subdivision); };
controls.exportCodex.onclick = () => { if (state.project) window.location.href = getCodexExportUrl(state.projectId); };
controls.exportPng.onclick = () => {
  if (!state.project) return;
  const link = document.createElement('a');
  link.download = `${state.project.source?.display_name || state.project.source?.file || 'beatscope'}-8-bars.png`;
  link.href = exportStaticPng(state);
  link.click();
};
controls.copyPrompt.onclick = async () => {
  if (!state.project) return;
  const name = state.project.source?.display_name || state.project.source?.file || 'this track';
  const prompt = `Build an audio-reactive visual for ${name}. Read BEATSCOPE.md, rhythm-map.json and visual-state.js first. Do not analyse the audio again. Use audio.currentTime as the only clock and getVisualState(time) for deterministic, pause- and seek-safe motion.`;
  try { await navigator.clipboard.writeText(prompt); controls.copyStatus.textContent = 'Copied'; }
  catch (_) { controls.copyStatus.textContent = 'Copy unavailable'; }
};

controls.openProject.onclick = () => controls.projectFile.click();
controls.projectFile.onchange = async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const project = JSON.parse(await file.text());
    demoArtifacts = null; // a user project never wears the demo scene
    setProject(project, project.project_id || null);
    if (project.project_id) setAudioSource(getAudioUrl(project.project_id));
  } catch (error) {
    showErrorState(`Could not read project JSON: ${error.message}`);
  }
};

// Segment navigation (plan 15.3): Shift+arrows jump to the previous/next
// structural segment start without disturbing the plain-arrow bar navigation.
function jumpSegment(direction) {
  const segments = state.project?.patterns?.segments;
  if (!Array.isArray(segments) || !segments.length) return;
  let target = null;
  if (direction > 0) {
    target = segments.find((segment) => Number(segment.start_time) > state.playbackTime + 1e-3) || null;
  } else {
    for (const segment of segments) {
      if (Number(segment.start_time) < state.playbackTime - 1e-3) target = segment;
      else break;
    }
  }
  if (target) seek(Number(target.start_time));
}

window.addEventListener('keydown', (event) => {
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
  if (event.code === 'Space') { event.preventDefault(); togglePlay(); }
  else if (event.shiftKey && event.code === 'ArrowRight') { event.preventDefault(); jumpSegment(1); }
  else if (event.shiftKey && event.code === 'ArrowLeft') { event.preventDefault(); jumpSegment(-1); }
  else if (event.code === 'ArrowRight') { event.preventDefault(); setStartBar(state.startBar + state.viewBars); }
  else if (event.code === 'ArrowLeft') { event.preventDefault(); setStartBar(state.startBar - state.viewBars); }
  else if (event.code === 'KeyL') { event.preventDefault(); toggleLoop(); }
});

window.addEventListener('resize', renderAll);
initAudio(audioElement);

// --- WebMCP Director registration (v0.10 plan sections 5.1, 6) ---------------
// Four status texts only: UNAVAILABLE / LOAD A TRACK / READY · 8 TOOLS / ERROR.
// Registration failure degrades to the status text alone; the player keeps
// working without WebMCP.
let webmcpState = 'unsupported';

function refreshWebMcpStatus() {
  if (!webmcpStatus) return;
  webmcpStatus.classList.toggle('is-ready', webmcpState === 'registered' && Boolean(state.project));
  if (webmcpState === 'unsupported') webmcpStatus.textContent = 'WEBMCP UNAVAILABLE';
  else if (webmcpState === 'error') webmcpStatus.textContent = 'WEBMCP ERROR';
  else if (state.project) webmcpStatus.textContent = 'WEBMCP READY · 8 TOOLS';
  else webmcpStatus.textContent = 'WEBMCP · LOAD A TRACK';
}

const webmcpSession = installWebMCP({
  getState: () => state,
  hasAudio: () => Boolean(audioElement && audioElement.src),
  seek: (time) => seek(time),
  // play() must report honest autoplay failures for requiresUserGesture, so
  // the dep awaits the media element directly (audio.js play() is
  // fire-and-forget by design).
  play: async () => {
    if (!audioElement || !audioElement.src) return false;
    try {
      await audioElement.play();
      return !audioElement.paused;
    } catch (_) {
      return false;
    }
  },
  pause: () => pause(),
  readAudioTime: () => (audioElement ? audioElement.currentTime || 0 : 0),
  setFollowPlayback: (enabled) => { if (followPlayback) followPlayback.checked = Boolean(enabled); },
  scrollPlayerIntoView: () => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    $('#visualSection')?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
  },
  sceneAt: (time) => (sceneArtifactsAvailable ? visualStageController.sceneAt(time) : null),
  onStatus: (status) => {
    // 'registering' arrives synchronously inside installWebMCP before the
    // return, so it maps to the same optimistic state the sync status check
    // sets below; 'ready'/'error' confirm or flip it once Promise.all lands.
    if (status === 'ready' || status === 'registering') webmcpState = 'registered';
    else if (status === 'error') webmcpState = 'error';
    refreshWebMcpStatus();
  },
});
if (webmcpSession.status === 'ready') webmcpState = 'registered';
refreshWebMcpStatus();
if (!staticDemoMode) {
  initImportHandlers({
    onLoaded: () => {
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      $('#visualSection')?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
    },
  });
}

(async () => {
  if (demoMode) {
    // Frozen demo entry (plan section 17.2): parallel-fetch the analysed
    // demo project, recipe and timeline; never call /api/project. Relative
    // URLs keep the page working under any static hosting base path.
    try {
      const [projectResponse, recipeResponse, timelineResponse] = await Promise.all([
        fetch('demo/project.json'),
        fetch('demo/visual-recipe.json'),
        fetch('demo/visual-timeline.json'),
      ]);
      if (!projectResponse.ok) throw new Error(`demo project ${projectResponse.status}`);
      const project = await projectResponse.json();
      // The artifacts must be in place before setProject: the projectLoaded
      // handler reads them synchronously instead of calling the visual API.
      demoArtifacts = recipeResponse.ok && timelineResponse.ok
        ? { recipe: await recipeResponse.json(), timeline: await timelineResponse.json() }
        : null;
      setProject(project, 'webmcp-demo');
      setAudioSource('demo/audio.mp3');
    } catch (_) {
      demoArtifacts = null;
      showEmptyState();
    }
    updateProjectUI();
    applyStaticDemoControls();
    return;
  }
  try {
    const response = await fetch('/api/project');
    if (response.ok) {
      const project = await response.json();
      setProject(project, project.project_id || null);
      setAudioSource('/api/project/audio');
    } else {
      showEmptyState();
    }
  } catch (_) {
    showEmptyState();
  }
  updateProjectUI();
})();
