/**
 * Studio session-state kernel tests (recovery work, item 2).
 *
 * The studio must keep "the film the user already has" separate from "the job
 * currently running": regenerating must never take the previous MP4's
 * download entry away, and a transient poll failure must not end tracking of
 * a job the server is still running.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  applyJobToSession,
  lastFilmUrl,
  pollRetryDelayMs,
  shouldKeepTracking,
  trackJob,
} from '../beatscope/web/studio-session.mjs';

const doneJob = (id, url) => ({ id, state: 'complete', progress: 1, message: '', video_url: url });

test('a finished film stays downloadable while a new render runs and after it fails', () => {
  let session = applyJobToSession({ videoUrl: null }, { id: 'j1', state: 'complete', progress: 1, message: '', video_url: '/api/movies/j1/video' });
  assert.equal(lastFilmUrl(session), '/api/movies/j1/video');

  session = applyJobToSession(session, { id: 'j2', state: 'running', progress: 0.2, message: '' });
  assert.equal(lastFilmUrl(session), '/api/movies/j1/video', 'regeneration must not hide the previous film');

  session = applyJobToSession(session, { id: 'j2', state: 'failed', progress: 0.3, message: 'boom', error: 'boom' });
  assert.equal(lastFilmUrl(session), '/api/movies/j1/video', 'failure must not take the film away');

  session = applyJobToSession(session, { id: 'j2', state: 'cancelled', progress: 0.3, message: '' });
  assert.equal(lastFilmUrl(session), '/api/movies/j1/video', 'cancellation keeps the previous film too');
});

test('a cancelled or failed terminal state does not keep advertising the dead job film', () => {
  let session = applyJobToSession({ videoUrl: null }, { id: 'j1', state: 'failed', progress: 0, message: 'no renderer' });
  assert.equal(lastFilmUrl(session), null);
  session = applyJobToSession(session, { id: 'j2', state: 'cancelled', progress: 0, message: '' });
  assert.equal(lastFilmUrl(session), null);
});

test('a newer completed job replaces the film it belongs to', () => {
  let session = applyJobToSession({ videoUrl: null }, { id: 'j1', state: 'complete', progress: 1, message: '', video_url: '/v1' });
  session = applyJobToSession(session, { id: 'j2', state: 'complete', progress: 1, message: '', video_url: '/v2' });
  assert.equal(lastFilmUrl(session), '/v2');
});

test('retry classification uses status codes, not digits in error messages', () => {
  assert.equal(pollRetryDelayMs(0), 1000);
  assert.equal(pollRetryDelayMs(3), 8000);
  assert.equal(pollRetryDelayMs(10), 10000);
  for (const status of [400, 401, 403, 404, 410, 422]) assert.equal(shouldKeepTracking({ status }), false);
  for (const status of [408, 429, 500, 503]) assert.equal(shouldKeepTracking({ status }), true);
  assert.equal(shouldKeepTracking(new TypeError('Failed to fetch job 404abc')), true);
});

test('polling recovers from network errors and resets backoff after success', async () => {
  const steps = [new TypeError('offline'), { state: 'running' }, { status: 503 }, { status: 503 }, doneJob('j1', '/v1')];
  const delays = [], received = [];
  await trackJob({
    read: async () => { const next = steps.shift(); if (!next.state) throw next; return next; },
    accept: (job) => { received.push(job.state); return job.state === 'complete'; },
    isCurrent: () => true,
    sleep: async (ms) => { delays.push(ms); },
  });
  assert.deepEqual(received, ['running', 'complete']);
  assert.deepEqual(delays, [1000, 1000, 1000, 2000]);
});

test('permanent errors surface immediately and repeated outages have a finite budget', async () => {
  for (const status of [404, 410, 503]) {
    let reads = 0, waits = 0;
    const failure = Object.assign(new Error('unavailable'), { status });
    await assert.rejects(trackJob({
      read: async () => { reads++; throw failure; },
      accept: () => assert.fail('no successful response'),
      isCurrent: () => true,
      sleep: async () => { waits++; },
    }), (error) => error === failure);
    assert.equal(reads, status === 503 ? 31 : 1);
    assert.equal(waits, status === 503 ? 30 : 0);
  }
});

test('superseded sessions discard in-flight results and stop during backoff', async () => {
  for (const outcome of ['success', 'failure', 'backoff']) {
    let current = true, reads = 0;
    await trackJob({
      read: async () => {
        reads++;
        if (outcome !== 'backoff') current = false;
        if (outcome !== 'success') throw new TypeError('offline');
        return doneJob('old', '/old');
      },
      accept: () => assert.fail('stale session mutated'),
      isCurrent: () => current,
      sleep: async () => { current = false; },
    });
    assert.equal(reads, 1);
  }
});

test('persisted film survives refresh after a failed regeneration', () => {
  const complete = applyJobToSession({}, doneJob('j1', '/v1'));
  const failed = applyJobToSession(complete, { id: 'j2', state: 'failed' });
  assert.equal(lastFilmUrl(JSON.parse(JSON.stringify(failed))), '/v1');
  assert.equal(lastFilmUrl(applyJobToSession(failed, { id: 'j3', state: 'complete' })), '/v1');
});
