/**
 * Deterministic workspace board geometry (Round 2 Commit 2).
 *
 * The demo's hand-authored layout stays the override for the bundled
 * "Beyond the Fog" wall; any scene without a board slot — server-derived
 * documents, split results — is filled into a chronological slot grid so
 * every scene always has a place on the wall. Slots derive from scene
 * order alone: same document, same boxes, on every machine.
 */
// .js extensions keep this graph compilable to standalone ESM for the Node
// tests (tests/tsconfig.direction.json); bundler resolution maps them back.
import type { DirectionDocument, WorkspaceLayout, BoardBox } from './types.js';
import { BOARD_HEAD, BOARD_FOOT, FIRST_RUN_ZOOM } from '../demo/document.js';

/** Reference-pixel slot grid (world units are ref px / FIRST_RUN_ZOOM). */
const SLOT_W_REF = 240;
const SLOT_BODYH_REF = 170;
const SLOT_COL_STEP_REF = 276;
const SLOT_ROW_STEP_REF = 274;
const SLOT_COLS = 5;
const SLOT_ORIGIN_REF = { x: 14, y: 120 };

/** Reference-px gap inserted between the two halves of a split board. */
const SPLIT_GAP_REF = 28;

const ref = (px: number) => px / FIRST_RUN_ZOOM;

export const SLOT_BOARD: BoardBox = {
  x: ref(SLOT_ORIGIN_REF.x),
  y: ref(SLOT_ORIGIN_REF.y),
  w: ref(SLOT_W_REF),
  bodyH: ref(SLOT_BODYH_REF),
  rotation: 0,
};

/**
 * Board boxes for every scene in the document. Boxes already present in
 * `prev` are kept untouched; missing scenes take their chronological slot.
 * Pure: returns a new layout object.
 */
export function fillLayoutSlots(doc: DirectionDocument, prev?: WorkspaceLayout): WorkspaceLayout {
  const boards: Record<string, BoardBox> = {};
  if (prev) {
    for (const [id, box] of Object.entries(prev.boards)) boards[id] = { ...box };
  }
  const scenes = [...doc.scenes].sort((a, b) => a.start_time - b.start_time);
  scenes.forEach((scene, i) => {
    if (boards[scene.id]) return;
    const col = i % SLOT_COLS;
    const row = Math.floor(i / SLOT_COLS);
    boards[scene.id] = {
      x: ref(SLOT_ORIGIN_REF.x + col * SLOT_COL_STEP_REF),
      y: ref(SLOT_ORIGIN_REF.y + row * SLOT_ROW_STEP_REF),
      w: SLOT_BOARD.w,
      bodyH: SLOT_BOARD.bodyH,
      rotation: 0,
    };
  });
  return { boards };
}

/** The box for the second half of a split board sits to the right of the first. */
export function splitBoardBox(box: BoardBox): BoardBox {
  return {
    x: box.x + box.w + ref(SPLIT_GAP_REF),
    y: box.y,
    w: box.w,
    bodyH: box.bodyH,
    rotation: box.rotation,
  };
}

/** Full board height for a layout box (world units). */
export function boardFullHeight(box: BoardBox): number {
  return BOARD_HEAD + box.bodyH + BOARD_FOOT;
}

/** Composition geometry per supported primary ratio (plan §4.1). */
export const RATIO_SIZES: Record<'16:9' | '9:16' | '1:1', { width: number; height: number }> = {
  '16:9': { width: 1920, height: 1080 },
  '9:16': { width: 1080, height: 1920 },
  '1:1': { width: 1080, height: 1080 },
};
