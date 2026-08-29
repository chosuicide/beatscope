import { state, subscribe, setProject, setSubdivision, setStartBar, setSelectedOnset, toggleLoop } from './state.js';
import { fetchProject, getAudioUrl, getMidiExportUrl, getCsvExportUrl, getCodexExportUrl } from './api.js';
import { initAudio, setAudioSource, togglePlay, seek, previewTransient } from './audio.js';
import { renderStaticMap, renderOverlay, renderOverview, renderVisualStage, exportStaticPng } from './renderer.js';
import { updateInspector } from './inspector.js';
import { initImportHandlers, showEmptyState, showErrorState } from './import.js';
import { gridPosition, metrics, formatTime, timeAtBar } from './grid.js';

const $ = (selector) => document.querySelector(selector);
const app = $('#app');
const audioElement = $('#audio');
const mapStatic = $('#mapStatic');
const mapOverlay = $('#mapOverlay');
const mapStack = $('#mapStack');
const overviewCanvas = $('#overview');
const visualStage = $('#visualStage');
const seekRange = $('#seekRange');
const volumeRange = $('#volumeRange');
const followPlayback = $('#followPlayback');

const controls = {
  filename: $('#filename'), status: $('#status'), timecode: $('#timecode'), currentTime: $('#currentTime'),
  play: $('#play'), stagePlay: $('#stagePlay'), loop: $('#loop'), prev: $('#prev'), next: $('#next'),
  subdivision: $('#subdivision'), range: $('#rangeLabel'), window: $('#windowLabel'), visualReadout: $('#visualReadout'),
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

function renderAll() {
  renderStaticMap(mapStatic, state);
  renderOverlay(mapOverlay, state);
  renderOverview(overviewCanvas, state);
  renderVisualStage(visualStage, state);
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
    setDisabled(true);
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
  setDisabled(false);
  controls.prev.disabled = state.startBar <= 0;
  controls.next.disabled = state.startBar + state.viewBars >= bars;
  renderAll();
}

function updatePlaybackUI() {
  const formatted = formatTime(state.playbackTime);
  controls.timecode.textContent = formatted;
  controls.currentTime.textContent = formatted;
  seekRange.value = String(state.playbackTime);
  const position = state.project ? gridPosition(state.playbackTime, state.project, state.subdivision, state.adjustments) : null;
  controls.visualReadout.textContent = position ? `BAR ${String(position.bar || 1).padStart(2, '0')} · BEAT ${position.beat || 1}` : 'BAR — · BEAT —';
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
  if (visualStageVisible) renderVisualStage(visualStage, state);
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
  if (visualStageVisible) renderVisualStage(visualStage, state);
  renderOverview(overviewCanvas, state);
}

subscribe((event, payload) => {
  if (['projectLoaded', 'startBarChanged', 'viewBarsChanged', 'subdivisionChanged', 'adjustmentsChanged'].includes(event)) {
    updateProjectUI();
    queueMapRefresh();
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
  }
});

if (mapStack && 'ResizeObserver' in window) {
  const mapResizeObserver = new ResizeObserver(() => queueMapRefresh());
  mapResizeObserver.observe(mapStack);
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
    if (visible && state.project) renderVisualStage(visualStage, state);
  }, { rootMargin: '140px 0px' });
  visualStageObserver.observe(visualStage);
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
seekRange.oninput = (event) => seek(Number(event.target.value));
controls.seekBack.onclick = () => seek(state.playbackTime - 5);
controls.seekForward.onclick = () => seek(state.playbackTime + 5);
volumeRange.oninput = (event) => { audioElement.volume = Number(event.target.value); };
controls.replaceAudio.onclick = () => controls.audioInput.click();

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
    setProject(project, project.project_id || null);
    if (project.project_id) setAudioSource(getAudioUrl(project.project_id));
  } catch (error) {
    showErrorState(`Could not read project JSON: ${error.message}`);
  }
};

window.addEventListener('keydown', (event) => {
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
  if (event.code === 'Space') { event.preventDefault(); togglePlay(); }
  else if (event.code === 'ArrowRight') { event.preventDefault(); setStartBar(state.startBar + state.viewBars); }
  else if (event.code === 'ArrowLeft') { event.preventDefault(); setStartBar(state.startBar - state.viewBars); }
  else if (event.code === 'KeyL') { event.preventDefault(); toggleLoop(); }
});

window.addEventListener('resize', renderAll);
initAudio(audioElement);
initImportHandlers({
  onLoaded: () => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    $('#visualSection')?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
  },
});

(async () => {
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
