/** Small, DOM-independent pointer state machine for step-grid interactions. */
export function createPointerStateMachine({ threshold = 4, onClick = () => {}, onDrag = () => {} } = {}) {
  let start = null;
  let dragging = false;
  return {
    pointerdown(point) { start = { x: point.x, y: point.y, step: point.step }; dragging = false; },
    pointermove(point) {
      if (!start) return false;
      if (!dragging && Math.hypot(point.x - start.x, point.y - start.y) > threshold) dragging = true;
      if (dragging) onDrag({ startStep: start.step, endStep: point.step });
      return dragging;
    },
    pointerup(point) {
      if (!start) return false;
      const wasDrag = dragging;
      if (!wasDrag) onClick(point);
      start = null; dragging = false;
      return wasDrag;
    },
    pointercancel() { start = null; dragging = false; },
    get dragging() { return dragging; },
  };
}
