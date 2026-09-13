// BeatScope module Worker example — transport stays on the main thread.
import { getVisualState } from './visual-state.js';

self.onmessage = ({ data = {} }) => {
  const time = Number(data.time);
  if (!Number.isFinite(time) || time < 0) {
    self.postMessage({ id: data.id ?? null, error: 'time must be a finite number >= 0' });
    return;
  }
  self.postMessage({ id: data.id ?? null, time, timing: getVisualState(time) });
};
