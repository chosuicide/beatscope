/**
 * Live-board arbitration (plan §3.2): exactly one board renders live.
 *
 * - The selected board is live while the user edits.
 * - During playback the chronologically current board becomes live unless
 *   the user pinned an edit board.
 * - Hover may temporarily show one poster checkpoint; it never becomes live.
 */
export interface ArbitrationInput {
  /** user selection (edit focus) */
  selectedSceneId: string | null;
  /** explicit pin: keeps an edit board live during playback */
  pinnedSceneId: string | null;
  /** chronological board under the playhead */
  currentSceneId: string | null;
  playing: boolean;
}

export function arbitrateLiveBoard(input: ArbitrationInput): string | null {
  const { selectedSceneId, pinnedSceneId, currentSceneId, playing } = input;
  if (pinnedSceneId) return pinnedSceneId;
  if (playing) return currentSceneId ?? selectedSceneId;
  return selectedSceneId ?? currentSceneId;
}

/**
 * A scene the user is editing (selected while paused) should keep rendering
 * live during playback only when explicitly pinned; this helper tells the
 * host whether a selection counts as an implicit pin.
 */
export function implicitPin(selectedSceneId: string | null, playing: boolean): string | null {
  return !playing && selectedSceneId ? selectedSceneId : null;
}
