/**
 * Inspector panel updating selection details.
 */

import { gridPosition } from './grid.js';

export function updateInspector(state) {
  const cellLabel = document.querySelector('#cellLabel');
  const rawTime = document.querySelector('#rawTime');
  const quantizedTime = document.querySelector('#quantizedTime');
  const offset = document.querySelector('#offset');
  const strength = document.querySelector('#strength');
  const bands = document.querySelector('#bands');

  const onset = state.selectedOnset;
  const cell = state.selectedCell;

  if (!onset && !cell) {
    if (cellLabel) cellLabel.textContent = 'Nothing selected';
    if (rawTime) rawTime.textContent = '—';
    if (quantizedTime) quantizedTime.textContent = '—';
    if (offset) offset.textContent = '—';
    if (strength) strength.textContent = '—';
    if (bands) bands.textContent = '—';
    return;
  }

  const q = onset
    ? gridPosition(onset.time ?? onset.raw_time, state.project, state.subdivision, state.adjustments)
    : cell;

  if (cellLabel) {
    cellLabel.textContent = q.bar > 0
      ? `Bar ${q.bar} · Beat ${q.beat} · Step ${q.stepInBar}`
      : `Pre-grid · Step ${q.step}`;
  }

  if (onset) {
    if (rawTime) rawTime.textContent = `${Number(onset.time ?? onset.raw_time).toFixed(4)} s`;
    if (quantizedTime) quantizedTime.textContent = `${Number(q.quantizedTime).toFixed(4)} s`;
    const sign = q.offsetMs >= 0 ? '+' : '';
    if (offset) offset.textContent = `${sign}${Number(q.offsetMs).toFixed(2)} ms`;
    if (strength) strength.textContent = Number(onset.strength).toFixed(4) + (onset.accent ? ' · accent' : '');
    
    const b = onset.bands || {};
    if (bands) {
      bands.textContent = `ALL ${Number(b.all || 0).toFixed(3)} | LOW ${Number(b.low || 0).toFixed(3)} | MID ${Number(b.mid || 0).toFixed(3)} | HIGH ${Number(b.high || 0).toFixed(3)}`;
    }
  } else {
    if (rawTime) rawTime.textContent = 'No onset';
    if (quantizedTime) quantizedTime.textContent = `${Number(q.quantizedTime).toFixed(4)} s`;
    if (offset) offset.textContent = '0.00 ms';
    if (strength) strength.textContent = '0.0000';
    if (bands) bands.textContent = 'No band energy';
  }
}
