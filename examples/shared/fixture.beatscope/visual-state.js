// BeatScope visual state contract — deterministic and seek-safe.
import { createTrack } from './beatscope-runtime.js';

import RHYTHM_MAP from './rhythm-map.json' with { type: 'json' };
export { RHYTHM_MAP };

const track = createTrack(RHYTHM_MAP);

export function getVisualState(time) {
  return track.at(time);
}
