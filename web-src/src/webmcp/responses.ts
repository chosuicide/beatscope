/**
 * Studio Director v2 — result envelopes and canonicalization
 * (v0.12 WebMCP plan sections 4.2, 6.4, 9.3).
 *
 * Two jobs:
 *
 * 1. Build the small JSON envelope every tool returns, with sanitized labels
 *    and one concrete next action on failure.
 * 2. Provide the canonical representation tests and probes compare bytes on:
 *    code-point-sorted keys, six-decimal finite numbers, normalized negative
 *    zero, LF final newline.
 *
 * Production callbacks return the envelope object directly; canonical JSON is
 * the test/probe representation, never a second output format.
 */
import { LIMITS } from './contracts.js';
import type { ErrorCode, ToolFailure, ToolName, ToolSuccess } from './types.js';

/**
 * An honest failure with a stable code and one concrete next action. The pure
 * query and action kernels throw it; the tool boundary turns it into a failure
 * envelope, so nothing internal (stack traces, server text) can leak out.
 */
export class ToolError extends Error {
  readonly code: ErrorCode;
  readonly nextAction: string;

  constructor(code: ErrorCode, message: string, nextAction: string) {
    super(message);
    this.name = 'ToolError';
    this.code = code;
    this.nextAction = nextAction;
  }
}

export function success<T>(tool: ToolName, summary: string, data: T): ToolSuccess<T> {
  return { ok: true, tool, summary: sanitizeLabel(summary), data };
}

export function failure(
  tool: ToolName,
  code: ErrorCode,
  message: string,
  nextAction: string,
): ToolFailure {
  return {
    ok: false,
    tool,
    error: {
      code,
      message: sanitizeLabel(message),
      next_action: sanitizeLabel(nextAction),
    },
  };
}

/** One line, no control characters, at most `LIMITS.label_characters`. */
export function sanitizeLabel(value: unknown, maxLength: number = LIMITS.label_characters): string {
  const text = typeof value === 'string' ? value : String(value ?? '');
  const flat = text
    .replace(/[\u0000-\u001f\u007f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return flat.length > maxLength ? flat.slice(0, maxLength) : flat;
}

/**
 * Six-decimal, finite, never negative zero. Returns null for values that must
 * not travel to an Agent (NaN, ±Infinity, non-numbers).
 */
export function sanitizeNumber(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  const rounded = Math.round(value * 1e6) / 1e6;
  return rounded === 0 ? 0 : rounded;
}

export function round6(value: number): number {
  if (!Number.isFinite(value)) throw new TypeError('Cannot canonicalize a non-finite number');
  const rounded = Math.round(value * 1e6) / 1e6;
  return rounded === 0 ? 0 : rounded;
}

function byCodePoint(a: string, b: string): number {
  const left = Array.from(a);
  const right = Array.from(b);
  const shared = Math.min(left.length, right.length);
  for (let index = 0; index < shared; index += 1) {
    const difference = left[index].codePointAt(0)! - right[index].codePointAt(0)!;
    if (difference !== 0) return difference;
  }
  return left.length - right.length;
}

function canonicalValue(node: unknown): unknown {
  if (typeof node === 'number') return round6(node);
  if (Array.isArray(node)) return node.map(canonicalValue);
  if (node !== null && typeof node === 'object') {
    const source = node as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(source).sort(byCodePoint)) out[key] = canonicalValue(source[key]);
    return out;
  }
  return node;
}

/** Canonical JSON bytes for tests, probes and snapshots. */
export function canonicalJson(value: unknown): string {
  return `${JSON.stringify(canonicalValue(value))}\n`;
}

/** UTF-16 code units of the serialized result, the unit the budget uses. */
export function resultCodeUnits(value: unknown): number {
  return JSON.stringify(value).length;
}

export function withinResultBudget(value: unknown): boolean {
  return resultCodeUnits(value) <= LIMITS.result_code_units;
}

/**
 * Keep a paginated result inside the code-unit budget by shrinking the page,
 * never by truncating an event (plan sections 4.2 and 9.2). `total`,
 * `has_more` and `next_offset` stay honest, so the caller simply pages on.
 */
export function fitPageToBudget<T>(
  rows: T[],
  offset: number,
  limit: number,
  build: (page: T[], nextOffset: number, hasMore: boolean, count: number) => unknown,
): { page: T[]; nextOffset: number; hasMore: boolean; count: number } {
  const slice = (size: number) => {
    const page = rows.slice(offset, offset + size);
    const nextOffset = offset + size;
    return { page, nextOffset, hasMore: nextOffset < rows.length, count: page.length };
  };
  const wanted = Math.max(0, Math.min(limit, Math.max(0, rows.length - offset)));
  let candidate = slice(wanted);
  let envelope = build(candidate.page, candidate.nextOffset, candidate.hasMore, candidate.count);
  if (resultCodeUnits(envelope) <= LIMITS.result_code_units || wanted <= 1) return candidate;
  const units = resultCodeUnits(envelope) || 1;
  let size = Math.max(1, Math.min(wanted - 1, Math.floor(wanted * (LIMITS.result_code_units / units) * 0.95)));
  for (;;) {
    candidate = slice(size);
    envelope = build(candidate.page, candidate.nextOffset, candidate.hasMore, candidate.count);
    if (resultCodeUnits(envelope) <= LIMITS.result_code_units || size === 1) return candidate;
    size = Math.max(1, size - Math.max(1, Math.floor(size * 0.1)));
  }
}
