/**
 * API client and job polling utilities.
 */

export async function uploadAudio(file, subdivision = 16) {
  const url = `/api/jobs/analyze?subdivision=${subdivision}`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Length': String(file.size),
      'X-Filename': encodeURIComponent(file.name),
    },
    body: file,
  });
  if (!response.ok) {
    const errText = await response.text();
    throw new Error(errText || `Upload failed with status ${response.status}`);
  }
  const data = await response.json();
  return data.job_id;
}

export function pollJob(jobId, onUpdate, intervalMs = 500) {
  let timer = null;
  let isCancelled = false;

  const check = async () => {
    if (isCancelled) return;
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) throw new Error(`Job poll failed: ${res.status}`);
      const job = await res.json();
      onUpdate(job);

      if (job.state === 'complete' || job.state === 'failed' || job.state === 'cancelled') {
        return;
      }
      timer = setTimeout(check, intervalMs);
    } catch (err) {
      onUpdate({ id: jobId, state: 'failed', error: err.message, message: '通信错误' });
    }
  };

  timer = setTimeout(check, 100);

  return () => {
    isCancelled = true;
    if (timer) clearTimeout(timer);
  };
}

export async function cancelJob(jobId) {
  const res = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
  return res.ok;
}

export async function fetchProject(projectId) {
  const res = await fetch(`/api/projects/${projectId}`);
  if (!res.ok) throw new Error(`Failed to load project ${projectId}`);
  return await res.json();
}

export async function fetchRecentProjects() {
  const res = await fetch('/api/projects');
  if (!res.ok) return [];
  const data = await res.json();
  return data.projects || [];
}

export async function saveAdjustments(projectId, adjustments) {
  const res = await fetch(`/api/projects/${projectId}/adjustments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(adjustments),
  });
  return res.ok;
}

export function getAudioUrl(projectId) {
  return `/api/projects/${projectId}/audio`;
}

export function getMidiExportUrl(projectId, subdivision = 16) {
  return projectId
    ? `/api/projects/${projectId}/export/rhythm.mid?subdivision=${subdivision}`
    : `/api/project/export/rhythm.mid?subdivision=${subdivision}`;
}

export function getCsvExportUrl(projectId, subdivision = 16) {
  return projectId
    ? `/api/projects/${projectId}/export/rhythm.csv?subdivision=${subdivision}`
    : `/api/project/export/rhythm.csv?subdivision=${subdivision}`;
}

export function getCodexExportUrl(projectId) {
  return projectId ? `/api/projects/${projectId}/export/codex.zip` : '/api/project/export/codex.zip';
}
