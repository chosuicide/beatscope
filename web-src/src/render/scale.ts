/**
 * Board container scale: world units per reference pixel. Kept in its own
 * module so layer systems can import it without pulling the board renderer
 * (which imports the system registry).
 */
import { FIRST_RUN_ZOOM } from '../demo/document.js';

export const BOARD_SCALE = 1 / FIRST_RUN_ZOOM;
