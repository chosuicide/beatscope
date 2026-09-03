/**
 * Bounded, stable response builders for the Director tools (v0.10 plan
 * sections 6.4 and 16). Tool data never carries paths, audio bytes, arrays
 * without hard caps, or wall-clock values; every second is rounded to four
 * decimals so the same query returns byte-identical JSON.
 */

/** Typed, actionable error. Handlers re-throw these; register formats them. */
export class WebMcpError extends Error {
  constructor(code, message = null) {
    super(message || code);
    this.name = 'WebMcpError';
    this.code = code;
  }
}

export function okResult(data) {
  return { ok: true, ...data };
}

export function errorResult(code, message = null) {
  return { ok: false, error: { code, message: message || null } };
}

/** All output seconds use four decimals (plan section 3.2). */
export function round4(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Number(parsed.toFixed(4));
}

/**
 * Collapse a free-text reason/label into a safe single line: control
 * characters dropped, whitespace collapsed, length clamped. Renderers use
 * textContent only, but the response itself must already be bounded.
 */
export function sanitizeLine(value, maxLength = 120) {
  const collapsed = String(value ?? '')
    // eslint-disable-next-line no-control-regex -- control characters are exactly what we strip
    .replace(/[\u0000-\u001f\u007f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return collapsed.slice(0, maxLength);
}

/** Deterministic "BARS 17—24" style label used by ledger entries. */
export function barSpanLabel(startBar, endBar) {
  return `bars ${String(startBar).padStart(2, '0')}—${String(endBar).padStart(2, '0')}`;
}
