// Authored timing, separate from measured facts. No renderer or visual style.
export function resolveEditPlan(rhythm, plan) {
  const duration = rhythm.source?.duration ?? rhythm.duration;
  if (plan?.schema !== 'beatscope-edit-plan-1' || plan.duration !== duration ||
      plan.source_sha256 !== (rhythm.source?.sha256 ?? '')) throw Error('edit-plan/source-mismatch');
  if (!Array.isArray(plan.boundaries) || !Array.isArray(plan.cues)) throw Error('edit-plan/schema');
  let previous = 0;
  const ids = new Set();
  for (const b of plan.boundaries) {
    if (!b || typeof b.id !== 'string' || ids.has(b.id) || !Number.isFinite(b.time) || b.time <= previous || b.time >= duration) throw Error('edit-plan/boundary-order');
    ids.add(b.id); previous = b.time;
  }
  const onsets = rhythm.onsets ?? [];
  const overrides = new Map();
  for (const c of plan.cues) {
    if (!c || typeof c.id !== 'string' || overrides.has(c.id)) throw Error('edit-plan/cue-id');
    const original = /^o:(0|[1-9]\d*)$/.test(c.id);
    if (original && Number(c.id.slice(2)) >= onsets.length || !original && !c.id.startsWith('u:')) throw Error('edit-plan/unknown-onset');
    if (!(original && c.deleted === true) && (!Number.isFinite(c.time) || c.time < 0 || c.time >= duration)) throw Error('edit-plan/cue-time');
    overrides.set(c.id, c);
  }
  const cues = onsets.flatMap((o, i) => {
    const id = `o:${i}`, change = overrides.get(id);
    const sourceTime = o.time ?? o.raw_time;
    return change?.deleted ? [] : [{id, time: change?.time ?? sourceTime, sourceTime, sourceId: o.id ?? i, manual: !!change, strength: o.strength ?? 0}];
  });
  for (const c of plan.cues) if (c.id.startsWith('u:')) cues.push({id:c.id, time:c.time, sourceTime:null, sourceId:null, manual:true, strength:1});
  cues.sort((a,b) => a.time-b.time || a.id.localeCompare(b.id));
  const starts = [{id:'start',time:0}, ...plan.boundaries];
  const stages = starts.map((s,i) => ({id:s.id, start:s.time, end:starts[i+1]?.time ?? duration, index:i}));
  return {stages, cues};
}
