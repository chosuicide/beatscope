/**
 * Binary search helpers for the compiled evaluator (plan §4.6: never scan
 * every onset per frame, use binary search for scene, event and boundary
 * windows).
 */

/** First index with values[index] >= target (values must be sorted). */
export function lowerBound(values: readonly number[], target: number): number {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (values[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** First index with values[index] > target (values must be sorted). */
export function upperBound(values: readonly number[], target: number): number {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (values[mid] <= target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}
