/** Display coordinates only. Onsets retain their measured seconds; never snap them. */
export function createMusicGrid(rhythm) {
  const duration = Math.max(0, Number(rhythm?.source?.duration) || 0);
  const numerator = Number(rhythm?.grid?.time_signature?.[0] ?? rhythm?.meter?.numerator) || 4;
  const subdivision = rhythm?.grid?.default_subdivision === 32 ? 32 : 16;
  const knots = [];
  for (const beat of rhythm?.beats ?? []) {
    const x = Number.isInteger(beat.bar) && Number.isInteger(beat.beat_in_bar)
      ? (beat.bar - 1) * numerator + beat.beat_in_bar - 1 : knots.length;
    const y = beat.time;
    const prev = knots.at(-1);
    if (Number.isFinite(y) && y >= 0 && y <= duration && (!prev || (x > prev[0] && y > prev[1]))) knots.push([x, y]);
  }
  const available = knots.length >= 2;
  if (available) {
    const last = knots.at(-1), previous = knots.at(-2);
    const end = Math.min(duration, last[1] + (last[1] - previous[1]) / (last[0] - previous[0]));
    if (end > last[1]) knots.push([last[0] + 1, end]);
  }
  const interpolate = (value, input, output) => {
    if (!available) return 0;
    let lo = 0, hi = knots.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >>> 1;
      if (knots[mid][input] <= value) lo = mid; else hi = mid;
    }
    const a = knots[lo], b = knots[hi];
    return a[output] + (value - a[input]) / (b[input] - a[input]) * (b[output] - a[output]);
  };
  const bars = available ? Math.max(1, Math.ceil(knots.at(-1)[0] / numerator)) : 0;
  const timeAtStep = step => Math.max(0, Math.min(duration, interpolate(step * numerator / subdivision, 0, 1)));
  const stepAtTime = time => interpolate(time, 1, 0) * subdivision / numerator;
  return { available, bars, subdivision, timeAtStep, stepAtTime,
    barAtTime: time => available ? Math.max(1, Math.min(bars, Math.floor(stepAtTime(time) / subdivision) + 1)) : null };
}
