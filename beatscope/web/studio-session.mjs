/** The last successful film is independent of the job being tracked. */
/** The model-backed analyzer, selectable per upload. */
export const HIGH_PRECISION_BACKEND = 'enhanced';

/**
 * The analyze endpoint for one upload.
 *
 * Defaults are omitted rather than sent, so a request that asks for
 * nothing looks like it always did and the server's own defaults stay the
 * single place they are defined.
 */
export function analyzeUrl({ backend, subdivision } = {}) {
  const query = new URLSearchParams();
  if (backend) query.set('backend', backend);
  if (subdivision) query.set('subdivision', String(subdivision));
  const suffix = query.toString();
  return suffix ? `/api/jobs/analyze?${suffix}` : '/api/jobs/analyze';
}

export function applyJobToSession(session, job) {
  const next = { ...session, job };
  if (job?.state === 'complete' && job.video_url) {
    next.videoUrl = job.video_url;
    next.videoJobId = job.id;
  }
  return next;
}

export function lastFilmUrl(session) {
  return session?.videoUrl || null;
}

export function shouldKeepTracking(error) {
  const status = Number(error?.status);
  return !status || status === 408 || status === 429 || status >= 500;
}

export function pollRetryDelayMs(failures) {
  return Math.min(1000 * 2 ** Math.max(0, failures), 10000);
}

/** Re-check ownership after every await: a superseded session cannot publish results. */
export async function trackJob({ read, accept, isCurrent, sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) {
  let failures = 0;
  while (isCurrent()) {
    let job;
    try {
      job = await read();
    } catch (error) {
      if (!isCurrent()) return;
      if (!shouldKeepTracking(error) || failures >= 30) throw error;
      await sleep(pollRetryDelayMs(failures++));
      continue;
    }
    if (!isCurrent()) return;
    failures = 0;
    if (await accept(job)) return;
    if (!isCurrent()) return;
    await sleep(1000);
  }
}
