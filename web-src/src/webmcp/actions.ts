/**
 * Studio Director v2 — page actions (v0.12 WebMCP plan sections 5.5, 5.6, 5.7,
 * 7.3, 9).
 *
 * The kernels here validate an Agent's request against the current snapshot
 * and then call exactly one port method. They own no state: playback is the
 * media element's, render lifecycle is MovieJobs', and the visible buttons go
 * through the same port methods these kernels call.
 *
 * A blocked autoplay, a busy render and a refused download are reported as
 * such — never as success.
 */
import { LIMITS } from './contracts.js';
import { ToolError, failure, success } from './responses.js';
import { downbeatsOf, resolveRange } from './timing.js';
import type { MovieRhythm } from '../movie/types.js';
import type { AgentActivity, StudioDirectorPort, ToolResult } from './types.js';

export interface PlaybackInput {
  action: 'play' | 'pause' | 'seek' | 'audition' | 'restore';
  time?: number;
  bar?: number;
  beat?: number;
  start_time?: number;
  end_time?: number;
  start_bar?: number;
  end_bar?: number;
  autoplay?: boolean;
}

export interface RenderInput {
  action: 'start' | 'cancel';
  seed?: number;
}

const POSITION_FIELDS = ['time', 'bar', 'beat', 'start_time', 'end_time', 'start_bar', 'end_bar'] as const;

function present(input: object, field: string): boolean {
  const value = (input as Record<string, unknown>)[field];
  return value !== undefined && value !== null;
}

/** `mm:ss.s`, frozen formatting for action labels — never a wall clock. */
function stamp(seconds: number): string {
  const safe = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${String(minutes).padStart(2, '0')}:${rest.toFixed(1).padStart(4, '0')}`;
}

function activityFor(kind: AgentActivity['kind'], action: string, label: string, restorable: boolean): AgentActivity {
  return { kind, action, label, restorable };
}

function fromError(tool: Parameters<typeof failure>[0], error: unknown): ToolResult {
  if (error instanceof ToolError) return failure(tool, error.code, error.message, error.nextAction);
  return failure(tool, 'internal_error', 'The action failed.', 'Report this to the user; the studio console has the details.');
}

/** Bar (and optional beat) to a measured time, from stored beats only. */
export function timeAtPosition(
  rhythm: MovieRhythm,
  bar: number,
  beat?: number,
): number {
  const downbeats = downbeatsOf(rhythm);
  if (downbeats.length < 2) {
    throw new ToolError('beat_grid_unavailable', 'This song has no measured beat grid.', 'Seek by time instead.');
  }
  if (!Number.isInteger(bar) || bar < 1 || bar > downbeats.length) {
    throw new ToolError('out_of_range', `Bar must be from 1 to ${downbeats.length}.`, 'Use a measured bar.');
  }
  if (beat === undefined || beat === 1) return downbeats[bar - 1];
  const inBar = (rhythm.beats ?? [])
    .filter((entry) => Number(entry.bar) === bar)
    .sort((left, right) => left.time - right.time);
  if (!Number.isInteger(beat) || beat < 1 || beat > inBar.length) {
    throw new ToolError('out_of_range', `That bar has ${inBar.length} measured beats.`, 'Use a beat inside the bar.');
  }
  return inBar[beat - 1].time;
}

const PLAYBACK_TOOL = 'beatscope_control_playback' as const;

/** `beatscope_control_playback` (plan section 5.5). */
export async function controlPlayback(
  port: StudioDirectorPort,
  input: PlaybackInput,
  signal?: AbortSignal,
): Promise<ToolResult> {
  const tool = PLAYBACK_TOOL;
  try {
    if (signal?.aborted) throw new ToolError('canceled', 'The call was cancelled.', 'Retry when the page is ready.');
    const snapshot = port.snapshot();
    if (snapshot.duration <= 0 || !snapshot.rhythm) {
      throw new ToolError('playback_unavailable', 'No song is loaded, so there is nothing to play.', 'Ask the user to upload a song.');
    }

    const action = input.action;
    if (!['play', 'pause', 'seek', 'audition', 'restore'].includes(action)) {
      throw new ToolError('invalid_input', 'action must be play, pause, seek, audition or restore.', 'Pick one of those actions.');
    }

    if (action === 'play' || action === 'pause') {
      const stray = POSITION_FIELDS.filter((field) => present(input, field));
      if (stray.length) {
        throw new ToolError('invalid_input', `${action} does not take a position (${stray.join(', ')}).`, 'Send the action alone.');
      }
      if (action === 'play') {
        const outcome = await port.play();
        if (signal?.aborted) throw new ToolError('canceled', 'The call was cancelled.', 'Retry when the page is ready.');
        port.recordAgentAction(activityFor('playback', 'play', 'Playing', false));
        return success(tool, outcome.playing ? `Playing from ${stamp(snapshot.currentTime)} s.` : 'Playback needs a user gesture.', {
          action,
          playing: outcome.playing,
          requires_user_gesture: outcome.requiresUserGesture,
        });
      }
      port.pause();
      port.recordAgentAction(activityFor('playback', 'pause', 'Paused', false));
      return success(tool, `Paused at ${stamp(snapshot.currentTime)} s.`, { action, playing: false });
    }

    if (action === 'restore') {
      const stray = POSITION_FIELDS.filter((field) => present(input, field));
      if (stray.length) {
        throw new ToolError('invalid_input', `restore does not take a position (${stray.join(', ')}).`, 'Send the action alone.');
      }
      const restored = await port.restoreAudition();
      if (!restored.restored) {
        throw new ToolError('playback_unavailable', 'There is no audition to restore.', 'Audition a range first.');
      }
      port.recordAgentAction(activityFor('playback', 'restore', `Restored ${stamp(restored.time)}`, false));
      return success(tool, `Restored ${stamp(restored.time)}${restored.playing ? ' and playing' : ''}.`, {
        action, time: restored.time, playing: restored.playing,
      });
    }

    if (action === 'seek') {
      const hasTime = present(input, 'time');
      const hasBar = present(input, 'bar');
      if (hasTime === hasBar) {
        throw new ToolError('invalid_input', 'seek needs exactly one of time or bar.', 'Send a single position.');
      }
      if (input.beat !== undefined && !hasBar) {
        throw new ToolError('invalid_input', 'beat only accompanies bar.', 'Send bar with beat, or use time.');
      }
      const stray = (['start_time', 'end_time', 'start_bar', 'end_bar'] as const).filter((field) => present(input, field));
      if (stray.length) {
        throw new ToolError('invalid_input', `seek does not take a range (${stray.join(', ')}).`, 'Use the audition action for ranges.');
      }
      let target: number;
      if (hasTime) {
        const value = Number(input.time);
        if (!Number.isFinite(value) || value < 0) {
          throw new ToolError('invalid_input', 'time must be a finite number of seconds.', 'Send a time inside the song.');
        }
        if (value > snapshot.duration) {
          throw new ToolError('out_of_range', `time is past the end of the song (${snapshot.duration} s).`, 'Use a time inside the song.');
        }
        target = value;
      } else {
        target = timeAtPosition(snapshot.rhythm, Number(input.bar), input.beat === undefined ? undefined : Number(input.beat));
      }
      port.seek(target);
      port.recordAgentAction(activityFor('playback', 'seek', `Seeked to ${stamp(target)}`, false));
      return success(tool, `Seeked to ${stamp(target)}.`, { action, time: target, bar: input.bar ?? null });
    }

    // audition
    const hasRange = present(input, 'start_time') || present(input, 'end_time') || present(input, 'start_bar') || present(input, 'end_bar');
    if (!hasRange) {
      throw new ToolError('invalid_input', 'audition needs a range.', 'Send start_time/end_time or start_bar/end_bar.');
    }
    if (present(input, 'time') || present(input, 'bar') || present(input, 'beat')) {
      throw new ToolError('invalid_input', 'audition takes a range, not a single position.', 'Send the range only.');
    }
    const range = resolveRange(port.snapshot(), input, { maxSeconds: LIMITS.timing_seconds, maxBars: LIMITS.timing_bars });
    const span = range.end - range.start;
    if (!(span > 0) || span > LIMITS.timing_seconds) {
      throw new ToolError('invalid_range', `An audition must be longer than 0 and at most ${LIMITS.timing_seconds} s.`, 'Narrow the range.');
    }
    const autoplay = input.autoplay !== false;
    const result = await port.audition(range.start, range.end, autoplay, signal ?? new AbortController().signal);
    if (signal?.aborted) throw new ToolError('canceled', 'The call was cancelled.', 'Retry when the page is ready.');
    port.recordAgentAction(activityFor(
      'playback', 'audition', `Auditioning ${stamp(range.start)}—${stamp(range.end)}`, true,
    ));
    return success(
      tool,
      result.started
        ? `Auditioning ${stamp(range.start)}—${stamp(range.end)}.`
        : `Waiting at ${stamp(range.start)}; playback needs a user gesture.`,
      {
        action,
        start: range.start,
        end: range.end,
        autoplay,
        started: result.started,
        requires_user_gesture: result.requires_user_gesture,
      },
    );
  } catch (error) {
    return fromError(tool, error);
  }
}

const RENDER_TOOL = 'beatscope_render_movie' as const;

/** `beatscope_render_movie` (plan section 5.6). Returns as soon as the job exists. */
export async function renderMovie(
  port: StudioDirectorPort,
  input: RenderInput,
  signal?: AbortSignal,
): Promise<ToolResult> {
  const tool = RENDER_TOOL;
  try {
    if (signal?.aborted) throw new ToolError('canceled', 'The call was cancelled.', 'Retry when the page is ready.');
    const snapshot = port.snapshot();
    if (input.action !== 'start' && input.action !== 'cancel') {
      throw new ToolError('invalid_input', 'action must be start or cancel.', 'Pick one of those actions.');
    }
    if (input.action === 'start' && input.seed !== undefined) {
      const seed = Number(input.seed);
      if (!Number.isInteger(seed) || seed < 0 || seed > LIMITS.seed_max) {
        throw new ToolError('invalid_input', `seed must be an integer from 0 to ${LIMITS.seed_max}.`, 'Send a 24-bit seed.');
      }
    }
    const active = snapshot.movieJob && ['queued', 'running', 'rendering'].includes(String(snapshot.movieJob.state));

    if (input.action === 'cancel') {
      if (input.seed !== undefined) {
        throw new ToolError('invalid_input', 'cancel does not take a seed.', 'Send the action alone.');
      }
      if (!active) {
        throw new ToolError('render_not_active', 'No render is running.', 'Start one with action=start.');
      }
      const result = await port.render('cancel', undefined, signal);
      port.recordAgentAction(activityFor('render', 'cancel', 'Render cancelled', false));
      return success(tool, 'Cancelled the active render.', { action: 'cancel', seed: result.seed, job: result.job });
    }

    if (!snapshot.rhythm || !snapshot.projectId) {
      throw new ToolError('render_unavailable', 'No song is loaded, so there is nothing to render.', 'Ask the user to upload a song.');
    }
    if (!snapshot.rendererAvailable) {
      throw new ToolError('render_unavailable', 'The local renderer is not available in this session.', 'Check the studio setup and try again.');
    }
    if (active) {
      const progress = Math.round(Number(snapshot.movieJob?.progress ?? 0) * 100);
      throw new ToolError('render_busy', `A movie render is already running at ${progress}%.`, 'Wait for it to finish or call this tool with action=cancel.');
    }
    const seed = input.seed === undefined ? undefined : Number(input.seed);
    const result = await port.render('start', seed, signal);
    if (signal?.aborted) {
      // The render is already accepted: stopping a wait must not cancel it.
      throw new ToolError('canceled', 'Stopped waiting for the render; the render itself continues.', 'Read progress with beatscope_get_studio_state.');
    }
    port.recordAgentAction(activityFor('render', 'start', `Rendering seed ${result.seed}`, false));
    return success(tool, `Render started with seed ${result.seed}.`, {
      action: 'start', seed: result.seed, job: result.job,
    });
  } catch (error) {
    return fromError(tool, error);
  }
}

const EXPORT_TOOL = 'beatscope_export_timing_package' as const;

/** `beatscope_export_timing_package` (plan section 5.7). Never returns bytes. */
export async function exportTimingPackage(port: StudioDirectorPort): Promise<ToolResult> {
  const tool = EXPORT_TOOL;
  try {
    const snapshot = port.snapshot();
    if (!snapshot.projectId) {
      throw new ToolError('track_required', 'No song is loaded, so there is nothing to export.', 'Ask the user to upload a song.');
    }
    const result = await port.exportTimingPackage();
    port.recordAgentAction(activityFor('export', 'start', `Exported ${result.filename}`, false));
    if (result.requires_user_action) {
      throw new ToolError(
        'download_requires_user_action',
        'The browser blocked the download.',
        'Use the Data export button in the studio; it is now highlighted.',
      );
    }
    return success(tool, `Started the timing-package download (${result.filename}).`, {
      filename: result.filename,
      started: result.started,
      includes: ['timing facts', 'runtime', 'probe', 'Skill', 'Agent guidance', 'MIDI', 'CSV'],
      excludes: ['source audio', 'movie', 'visual template', 'scenes', 'task statement'],
    });
  } catch (error) {
    return fromError(tool, error);
  }
}
