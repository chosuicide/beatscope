/**
 * Pure functions for timing, metrics, and beatgrid quantization.
 * Quantization itself lives in the shared runtime (beatscope/runtime).
 */

import { trackForProject } from '../runtime/runtime.js';

export function metrics(project, subdivision = 16, adjustments = null) {
  const bpm = Number(adjustments?.bpm || project?.tempo?.global_bpm || project?.tempo?.bpm || 120);
  const origin = Number(adjustments?.origin ?? project?.grid?.origin ?? 0);
  const step = bpm > 0 ? 60 / bpm / (subdivision / 4) : 0;
  const bar = bpm > 0 ? 240 / bpm : 0;
  return { bpm, origin, step, bar };
}

export function formatTime(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  const mins = Math.floor(s / 60);
  const secs = Math.floor(s % 60);
  const ms = Math.floor((s * 1000) % 1000);
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

/**
 * Quantize a raw timestamp against real project beats if available, otherwise global BPM grid.
 * Returns: { bar, beat, stepInBar, step (absolute), quantizedTime, offsetMs, preGrid }
 */
export function gridPosition(rawTime, project, subdivision = 16, adjustments = null) {
  return trackForProject(project).quantize(rawTime, subdivision, adjustments);
}

export function timeAtBar(barNumber, project, adjustments = null) {
  const beats = project?.beats || [];
  if (beats.length) {
    const downbeat = beats.find((b) => b.bar === barNumber && (b.beat_in_bar ?? b.beat) === 1);
    if (downbeat) return Number(downbeat.time);
  }
  const m = metrics(project, 16, adjustments);
  return m.origin + Math.max(0, barNumber - 1) * m.bar;
}
