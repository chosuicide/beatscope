// BeatScope module Worker example — transport stays on the main thread.
import * as beatScope from './visual-state.js';

self.onmessage = ({ data = {} }) => {
  const time = Number(data.time);
  if (!Number.isFinite(time) || time < 0) {
    self.postMessage({ id: data.id ?? null, error: 'time must be a finite number >= 0' });
    return;
  }
  const frame = typeof beatScope.getBeatScopeFrame === 'function'
    ? beatScope.getBeatScopeFrame(time, data.options)
    : { timing: beatScope.getVisualState(time) };
  self.postMessage({ id: data.id ?? null, time, ...frame });
};
