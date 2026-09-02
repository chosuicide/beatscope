import { DURATION_SECONDS, frameTime, sceneState } from "./state.js";

export const duration = DURATION_SECONDS;

/** Stable adapter used by validate-consumer; no React or renderer required. */
export function frameAt(frame, fps, startFrame = 0) {
  return sceneState(frameTime(frame, fps, startFrame));
}
