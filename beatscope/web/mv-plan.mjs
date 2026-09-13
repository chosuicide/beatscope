// A consumer editing policy, not inferred musical truth. Original event times survive.
export const POLICY = Object.freeze({anchor: .82, support: .74, neighbour: .48, spacing: .16});
// Family -> the backgrounds that family owns, in rotation order. Each shot takes
// the next entry of its family's list, so a repeated section returns to the same
// material while the cut palette keeps moving. 0..10 are the original worlds;
// 11..15 were added later (halftone print, CRT phosphor, blueprint, ink wash,
// data rain). mv-visual.js imports this table for its plan-less fallback path.
export const WORLD_SETS = {
  A: [1, 2, 13, 0, 11],
  B: [10, 4, 12, 6, 15, 5],
  C: [8, 3, 9, 7, 14],
};
// The analysis can report families past C; those sections still cycle through
// every world, offset per family so two sections do not open on the same shot.
const ALL_WORLDS = [...new Set(Object.values(WORLD_SETS).flat())];
export function worldsFor(family, seed = 0) {
  const key = String(family ?? "");
  // The analysis labels most segments with a single letter, but it also reports
  // words such as "BREAK"; an unknown family must not break the plan, so it
  // falls back to the full palette the way mv-visual.js does.
  const authored = Object.prototype.hasOwnProperty.call(WORLD_SETS, key) ? WORLD_SETS[key] : null;
  if (authored) return authored.slice();
  const offset = ([...key].reduce((hash, ch) => (hash * 31 + ch.charCodeAt(0)) >>> 0, 7) + (seed >>> 0)) % ALL_WORLDS.length;
  return ALL_WORLDS.map((_, i) => ALL_WORLDS[(i + offset) % ALL_WORLDS.length]);
}
export function selectResponses(events) {
  const ordered = [...events].sort((a,b)=>a.time-b.time||a.id-b.id);
  const anchors = ordered.filter(e=>e.response_relevance>=POLICY.anchor);
  const eligible = ordered.filter(e=>e.response_relevance>=POLICY.support && anchors.some(a=>Math.abs(a.time-e.time)<=POLICY.neighbour));
  const selected = [];
  for (const event of eligible.sort((a,b)=>b.response_relevance-a.response_relevance||a.time-b.time||a.id-b.id)) {
    if (selected.every(e=>Math.abs(e.time-event.time)>=POLICY.spacing)) selected.push(event);
  }
  return selected.sort((a,b)=>a.time-b.time||a.id-b.id);
}
export function makePlan(map, response, seed=0) {
  const duration = map.source?.duration ?? map.duration;
  if (!Number.isFinite(duration) || duration<=0 || duration>600) throw Error('Audio must be between 0 and 600 seconds');
  if (!response.available) throw Error('Response ranking is unavailable; no substitute beat grid was invented');
  const details = selectResponses(response.events.filter(e=>e.time>=0&&e.time<duration));
  const segments = map.patterns?.segments ?? [];
  const boundaries = segments.filter(s=>s.start_time>0&&s.start_time<duration).map(s=>({time:s.start_time,id:s.id,kind:'structure'}));
  // The cut list stays ranked events only, exactly as before: responses are
  // spent on the v0.11 ordering, never on the metre. (Cutting every bar was
  // measured and removed — it answers the grid instead of the evidence, and the
  // ranker's whole point is that not every transient deserves a response.)
  const cuts = [{time:0,id:'start',kind:'start'},...boundaries,...details.filter(e=>e.time>=POLICY.spacing&&boundaries.every(b=>Math.abs(b.time-e.time)>=POLICY.spacing)).map(e=>({...e,kind:'onset'}))].sort((a,b)=>a.time-b.time);
  const unique = cuts.filter((c,i)=>!i||c.time!==cuts[i-1].time);
  const counters = {};
  const shots = unique.map((e,i)=>{
    const family = segments.find(s=>s.start_time<=e.time&&s.end_time>e.time)?.family ?? 'A';
    const worlds = worldsFor(family, seed), n=counters[family]??0; counters[family]=n+1;
    return {start:e.time,end:unique[i+1]?.time??duration,eventId:e.id,kind:e.kind,family,world:worlds[(n+(seed>>>0)%worlds.length)%worlds.length]};
  });
  return {version:'voxel-phrase-2',duration,fps:30,size:1080,seed,shots,details,policy:POLICY};
}
