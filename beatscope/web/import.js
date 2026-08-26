/**
 * Drag & Drop, file upload, progress reporting, and job cancellations.
 */

import { state, setJob, setProject } from './state.js';
import { uploadAudio, pollJob, cancelJob, fetchProject, getAudioUrl } from './api.js';
import { setAudioSource } from './audio.js';

let cancelPoll = null;

export function initImportHandlers(callbacks = {}) {
  const app = document.querySelector('#app');
  const dropOverlay = document.querySelector('#dropOverlay');
  const fileInput = document.querySelector('#audioFileInput');
  const cancelBtn = document.querySelector('#cancelAnalysisBtn');
  const selectAudioBtn = document.querySelector('#selectAudioBtn');
  const dropZone = document.querySelector('#dropZone');

  // File picker trigger
  if (selectAudioBtn && fileInput) {
    selectAudioBtn.onclick = () => fileInput.click();
  }
  if (dropZone && fileInput) {
    dropZone.onclick = (event) => { if (event.target !== selectAudioBtn) fileInput.click(); };
    dropZone.onkeydown = (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); fileInput.click(); } };
    dropZone.ondragover = (event) => { event.preventDefault(); dropZone.classList.add('dragging'); };
    dropZone.ondragleave = () => dropZone.classList.remove('dragging');
    dropZone.ondrop = (event) => { event.preventDefault(); dropZone.classList.remove('dragging'); const file = event.dataTransfer?.files?.[0]; if (file) handleAudioFile(file, callbacks); };
  }

  if (fileInput) {
    fileInput.onchange = (e) => {
      const file = e.target.files?.[0];
      if (file) handleAudioFile(file, callbacks);
    };
  }

  // Drag and drop events on window
  window.addEventListener('dragenter', (e) => {
    e.preventDefault();
    if (dropOverlay) dropOverlay.classList.add('active');
  });

  window.addEventListener('dragover', (e) => {
    e.preventDefault();
    if (dropOverlay) dropOverlay.classList.add('active');
  });

  window.addEventListener('dragleave', (e) => {
    if (e.relatedTarget === null && dropOverlay) {
      dropOverlay.classList.remove('active');
    }
  });

  window.addEventListener('drop', (e) => {
    e.preventDefault();
    if (dropOverlay) dropOverlay.classList.remove('active');
    const file = e.dataTransfer?.files?.[0];
    if (file) handleAudioFile(file, callbacks);
  });

  if (cancelBtn) {
    cancelBtn.onclick = async () => {
      if (state.activeJob?.id) {
        await cancelJob(state.activeJob.id);
        if (cancelPoll) cancelPoll();
        setJob(null);
        showEmptyState();
      }
    };
  }
}

export async function handleAudioFile(file, callbacks = {}) {
  const allowed = ['.wav', '.mp3', '.flac', '.ogg', '.m4a'];
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  if (!allowed.includes(ext)) {
    showErrorState(`不支持的音频格式 (${ext})。请使用 WAV / FLAC / MP3 / OGG / M4A。`);
    return;
  }

  showProgressState('正在上传音频并建立任务...', 0.05);
  const dropZone = document.querySelector('#dropZone');
  if (dropZone) {
    const label = dropZone.querySelector('.drop-zone-label');
    if (label) label.textContent = file.name;
  }

  try {
    const jobId = await uploadAudio(file, state.subdivision);
    if (cancelPoll) cancelPoll();

    cancelPoll = pollJob(jobId, async (job) => {
      setJob(job);
      if (job.state === 'running' || job.state === 'queued') {
        showProgressState(job.message || '正在分析...', job.progress || 0.1);
      } else if (job.state === 'complete') {
        showProgressState('分析完成，正在载入...', 1.0);
        try {
          const projectData = await fetchProject(job.project_id);
          setProject(projectData, job.project_id);
          setAudioSource(getAudioUrl(job.project_id));
          hideOverlay();
          if (callbacks.onLoaded) callbacks.onLoaded(projectData);
        } catch (loadErr) {
          showErrorState(`无法载入项目: ${loadErr.message}`);
        }
      } else if (job.state === 'failed') {
        showErrorState(`分析失败: ${job.error || job.message}`);
      } else if (job.state === 'cancelled') {
        showEmptyState();
      }
    });
  } catch (err) {
    showErrorState(`上传或启动分析失败: ${err.message}`);
  }
}

export function showProgressState(message, progressVal = 0) {
  const app = document.querySelector('#app');
  const progressBox = document.querySelector('#analysisProgressBox');
  const progressMsg = document.querySelector('#progressMessage');
  const progressBar = document.querySelector('#progressBarInner');

  if (app) app.dataset.state = 'analyzing';
  if (progressBox) progressBox.hidden = false;
  if (progressMsg) progressMsg.textContent = message;
  if (progressBar) progressBar.style.width = `${Math.min(100, Math.max(0, Math.round(progressVal * 100)))}%`;
}

export function showErrorState(errorMsg) {
  const app = document.querySelector('#app');
  const progressBox = document.querySelector('#analysisProgressBox');
  const statusEl = document.querySelector('#status');

  if (app) app.dataset.state = 'error';
  if (progressBox) progressBox.hidden = true;
  if (statusEl) statusEl.textContent = errorMsg;
}

export function showEmptyState() {
  const app = document.querySelector('#app');
  const progressBox = document.querySelector('#analysisProgressBox');
  const statusEl = document.querySelector('#status');

  if (app) app.dataset.state = 'empty';
  if (progressBox) progressBox.hidden = true;
  if (statusEl) statusEl.textContent = '拖入一首歌建立节奏地图';
}

export function hideOverlay() {
  const app = document.querySelector('#app');
  const progressBox = document.querySelector('#analysisProgressBox');
  if (app) app.dataset.state = 'loaded';
  if (progressBox) progressBox.hidden = true;
}
