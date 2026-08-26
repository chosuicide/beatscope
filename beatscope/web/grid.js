/**
 * Pure functions for timing, metrics, and beatgrid quantization.
 */

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
 * Returns: { bar, beat, stepInBar, step (absolute), quantizedTime, offsetMs, confidence, preGrid }
 */
export function gridPosition(rawTime, project, subdivision = 16, adjustments = null) {
  const t = Number(rawTime) || 0;
  const beats = project?.beats || [];
  const partsPerBeat = subdivision / 4;
  const m = metrics(project, subdivision, adjustments);

  // Fallback if no explicit beats array
  if (!beats.length || adjustments?.bpm) {
    if (!m.step) {
      return { step: 0, bar: 0, beat: 0, stepInBar: 0, quantizedTime: 0, offsetMs: 0, preGrid: true };
    }
    const nearest = Math.round((t - m.origin) / m.step);
    const inGrid = nearest >= 0;
    const quantized = m.origin + nearest * m.step;
    return {
      step: nearest,
      bar: inGrid ? Math.floor(nearest / subdivision) + 1 : 0,
      beat: inGrid ? Math.floor((nearest % subdivision) / partsPerBeat) + 1 : 0,
      stepInBar: inGrid ? (nearest % subdivision) + 1 : 0,
      quantizedTime: Number(quantized.toFixed(4)),
      offsetMs: Number(((t - quantized) * 1000).toFixed(2)),
      preGrid: !inGrid,
    };
  }

  // Real beat interpolation
  const beatTimes = beats.map((b) => Number(b.time));

  // Case 1: t is before first beat
  if (t < beatTimes[0]) {
    const avgBeatLen = beatTimes.length > 1 ? beatTimes[1] - beatTimes[0] : (60 / m.bpm);
    const stepLen = avgBeatLen / partsPerBeat;
    const stepsBefore = Math.round((beatTimes[0] - t) / stepLen);
    const quantized = beatTimes[0] - stepsBefore * stepLen;
    return {
      step: -stepsBefore,
      bar: 0,
      beat: 0,
      stepInBar: 0,
      quantizedTime: Number(quantized.toFixed(4)),
      offsetMs: Number(((t - quantized) * 1000).toFixed(2)),
      preGrid: true,
    };
  }

  // Case 2: t is after last beat
  if (t >= beatTimes[beatTimes.length - 1]) {
    const lastBeat = beats[beats.length - 1];
    const avgBeatLen = beatTimes.length > 1 ? beatTimes[beatTimes.length - 1] - beatTimes[beatTimes.length - 2] : (60 / m.bpm);
    const stepLen = avgBeatLen / partsPerBeat;
    const stepsAfter = Math.round((t - beatTimes[beatTimes.length - 1]) / stepLen);
    const quantized = beatTimes[beatTimes.length - 1] + stepsAfter * stepLen;
    
    const curBeatIdx = (lastBeat.beat - 1) + Math.floor(stepsAfter / partsPerBeat);
    const curBar = lastBeat.bar + Math.floor(curBeatIdx / 4);
    const curBeat = (curBeatIdx % 4) + 1;
    const curStepInBar = (curBeat - 1) * partsPerBeat + (stepsAfter % partsPerBeat) + 1;
    const absStep = (curBar - 1) * subdivision + curStepInBar - 1;

    return {
      step: absStep,
      bar: curBar,
      beat: curBeat,
      stepInBar: curStepInBar,
      quantizedTime: Number(quantized.toFixed(4)),
      offsetMs: Number(((t - quantized) * 1000).toFixed(2)),
      preGrid: false,
    };
  }

  // Case 3: Binary search for adjacent beat segment
  let low = 0;
  let high = beatTimes.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (beatTimes[mid] <= t) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  const idx = Math.max(0, low - 1);
  const leftBeat = beats[idx];
  const rightBeat = beats[idx + 1] || leftBeat;
  const leftT = beatTimes[idx];
  const rightT = idx + 1 < beatTimes.length ? beatTimes[idx + 1] : leftT + (60 / m.bpm);
  const beatSpan = rightT - leftT;

  const candidates = [];
  for (let p = 0; p <= partsPerBeat; p += 1) {
    candidates.push(leftT + (beatSpan * p) / partsPerBeat);
  }

  let bestP = 0;
  let minDiff = Infinity;
  for (let p = 0; p <= partsPerBeat; p += 1) {
    const diff = Math.abs(candidates[p] - t);
    if (diff < minDiff) {
      minDiff = diff;
      bestP = p;
    }
  }

  const quantized = candidates[bestP];
  let targetBeat = leftBeat;
  let stepInBeat = bestP;

  if (bestP === partsPerBeat && idx + 1 < beats.length) {
    targetBeat = rightBeat;
    stepInBeat = 0;
  }

  const bar = targetBeat.bar || 0;
  const beatNum = targetBeat.beat || 1;
  const stepInBar = (beatNum - 1) * partsPerBeat + stepInBeat + 1;
  const absStep = (bar > 0 ? bar - 1 : 0) * subdivision + stepInBar - 1;

  return {
    step: absStep,
    bar,
    beat: beatNum,
    stepInBar,
    quantizedTime: Number(quantized.toFixed(4)),
    offsetMs: Number(((t - quantized) * 1000).toFixed(2)),
    preGrid: bar === 0,
  };
}

export function timeAtBar(barNumber, project, adjustments = null) {
  const beats = project?.beats || [];
  if (beats.length) {
    const downbeat = beats.find((b) => b.bar === barNumber && b.beat === 1);
    if (downbeat) return Number(downbeat.time);
  }
  const m = metrics(project, 16, adjustments);
  return m.origin + Math.max(0, barNumber - 1) * m.bar;
}
