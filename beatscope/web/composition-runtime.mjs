/** Portable foreground evaluation. Original times are never snapped to beat grids. */
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
function after(events, t) {
  let lo = 0, hi = events.length;
  while (lo < hi) { const mid = (lo + hi) >>> 1; if (events[mid].time <= t) lo = mid + 1; else hi = mid; }
  return lo;
}
export function compileComposition(document, rhythm, relevance = null) {
  if (document.project_id !== rhythm.project_id || document.source_rhythm_sha256 !== rhythm.source?.sha256) throw Error('Composition/audio identity mismatch');
  const ranking = new Map((relevance?.events ?? []).map(e => [String(e.onset_id), e.response_relevance]));
  const diagnostics = [];
  const chains = document.responses.map(response => {
    const source = response.driver === 'beats' ? rhythm.beats ?? [] : rhythm.onsets ?? [];
    let candidates = source.filter(e => Number.isFinite(e.time) && e.time >= 0 && (response.driver === 'beats' || response.band === 'all' || Number(e.bands?.[response.band]) > 0))
      .map((e, index) => ({ time: e.time, id: String(e.id ?? index), value: response.driver === 'beats' ? 1 : clamp(Number(ranking.get(String(e.id)) ?? e.strength ?? 0), 0, 1) }));
    candidates.sort((a, b) => b.value - a.value || a.time - b.time || a.id.localeCompare(b.id, 'en'));
    // Sparse ordered insertion: only adjacent accepted events can violate min_gap.
    const selected = [];
    for (const event of candidates) {
      const index = after(selected, event.time), left = selected[index - 1], right = selected[index];
      if ((left && event.time - left.time < response.min_gap) || (right && right.time - event.time < response.min_gap)) continue;
      selected.splice(index, 0, event);
    }
    diagnostics.push({ id: response.id, eligible: candidates.length, selected: selected.length,
      source: response.driver === 'beats' ? 'measured-beats' : ranking.size ? 'response-relevance' : 'onset-strength-fallback', unavailable: candidates.length === 0 });
    return { ...response, selected };
  });
  return {
    diagnostics,
    eventTimes: chains.map(c => ({ id: c.id, times: c.selected.map(e => e.time) })),
    at(time, reducedMotion = false) {
      if (!Number.isFinite(time)) throw Error('Time must be finite');
      const state = Object.fromEntries(document.objects.map(o => [o.id, { scale: 1, opacity: o.opacity }]));
      for (const chain of chains) {
        const target = state[chain.target_id]; if (!target) continue;
        const index = after(chain.selected, time) - 1;
        let pulse = 0;
        for (let i = index; i >= 0 && time - chain.selected[i].time <= chain.release; i--) {
          const age = time - chain.selected[i].time;
          const envelope = Math.pow(1 - age / chain.release, 3);
          pulse = Math.max(pulse, envelope * chain.selected[i].value);
        }
        if (chain.motion === 'scale_pulse') target.scale = clamp(target.scale + pulse * chain.amount * (reducedMotion ? 0 : 1), 1, 2);
        if (chain.motion === 'opacity_dip') target.opacity *= 1 - pulse * chain.amount * (reducedMotion ? 0 : 1);
      }
      return state;
    },
  };
}
