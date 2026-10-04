// Authored shot combinations over real music time. No fixed cut pattern or style.
import {createChoreography} from './choreography.js';
const finite = n => typeof n === 'number' && Number.isFinite(n);
const clone = value => structuredClone(value);
function check(ok, message) { if (!ok) throw new Error(`BeatScope edit score: ${message}`); }
function floorIndex(times, t) {
  let lo = 0, hi = times.length;
  while (lo < hi) { const m = (lo + hi) >>> 1; if (times[m] <= t) lo = m + 1; else hi = m; }
  return lo - 1;
}
const overlaps = (a, b) => a === b || a.startsWith(b + '.') || b.startsWith(a + '.');

/** A shot is a reusable renderer setup with optional local-second tracks.
 * Global tracks remain in music time. Cuts may bind beats, onsets or moments.
 * Groups coordinate a whole authored sequence; null cells keep the current shot.
 * Shot clocks: continuous advances offscreen; visible pauses offscreen;
 * restart starts again on each explicit visit, including a same-shot cut.
 */
export function createEditScore(score, timing) {
  const choreography = createChoreography({...score, tracks: score.tracks || []}, timing);
  const duration = timing.RHYTHM_MAP.duration;
  check(Array.isArray(score.shots) && score.shots.length, 'shots required');
  const globals = (score.tracks || []).map(t => t.id);
  const shots = new Map();
  for (const definition of score.shots) {
    const s = clone(definition);
    check(typeof s.id === 'string' && s.id && !shots.has(s.id), 'unique shot id required');
    check(typeof s.relation === 'string' && s.relation.trim(), `shot ${s.id} needs a visual relation`);
    const clock = {mode: score.intent === 'music-video' ? 'continuous' : 'visible',
      offset: 0, rate: 1, ...(s.clock || {})};
    check(['continuous', 'visible', 'restart'].includes(clock.mode)
      && finite(clock.offset) && clock.offset >= 0 && finite(clock.rate) && clock.rate >= 0, 'invalid shot clock');
    const shotDuration = s.duration ?? duration;
    check(finite(shotDuration) && shotDuration > 0, 'invalid shot duration');
    const tracks = s.tracks || [];
    check(Array.isArray(tracks), 'shot tracks must be an array');
    const localIds = new Set([...Object.keys(s.values || {}), ...tracks.map(t => t.id)]);
    check(!globals.some(g => [...localIds].some(id => overlaps(g, id))), `global/local writer overlap in ${s.id}`);
    for (const track of tracks) {
      check(!track.pace && !track.activity && track.keys?.every(k => finite(k.at)),
        'shot tracks use local seconds; metric/activity tracks belong to global music time');
    }
    const local = createChoreography({stages: [{id: s.id, start: 0, end: shotDuration,
      focus: s.id, change: s.relation}], tracks}, {
      RHYTHM_MAP: {duration: shotDuration, beats: [], onsets: []},
      getVisualState: t => ({time: t}),
    });
    shots.set(s.id, {definition: s, clock, local});
  }
  const cuts = [];
  function cut(anchor, shot, origin) {
    if (shot === null) return; // musical event retained without a shot switch
    check(shots.has(shot), `unknown shot ${shot}`);
    const time = choreography.resolve(anchor);
    check(time >= 0 && time < duration, 'cut outside song');
    cuts.push({time, shot, origin});
  }
  for (const stage of choreography.stages) {
    if (stage.entry !== undefined) cut(stage.start, stage.entry, `stage:${stage.id}`);
  }
  for (const row of score.cuts || []) cut(row.at, row.shot, 'direct');
  const groupIds = new Set();
  for (const group of score.groups || []) {
    check(typeof group.id === 'string' && group.id && !groupIds.has(group.id), 'unique group id required');
    groupIds.add(group.id);
    check(Array.isArray(group.anchors) && group.anchors.length > 0
      && Array.isArray(group.sequence) && group.sequence.length > 0, 'group anchors/sequence required');
    check(group.repeat === true || group.sequence.length === group.anchors.length,
      'sequence length must match anchors unless repetition is explicitly authored');
    const times = group.anchors.map(a => choreography.resolve(a));
    check(times.every((t, i) => finite(t) && (!i || t > times[i - 1])), 'group anchors must increase');
    if (group.stage !== undefined) {
      const stage = choreography.stages.find(s => s.id === group.stage);
      check(stage && times.every(t => t >= stage.start && t < stage.end), 'group crosses its declared stage');
    }
    group.anchors.forEach((a, i) => cut(a, group.sequence[i % group.sequence.length], `group:${group.id}`));
  }
  cuts.sort((a, b) => a.time - b.time);
  check(cuts.length && cuts[0].time === 0, 'initial shot at time zero required');
  cuts.forEach((c, i) => check(!i || c.time > cuts[i - 1].time, 'conflicting cuts at the same time'));
  for (const stage of choreography.stages) {
    check(cuts.some(c => Math.abs(c.time - stage.start) < 1e-9) || stage.carry === true,
      `stage ${stage.id} needs an entry cut or explicit carry`);
  }
  const histories = new Map();
  cuts.forEach((c, i) => {
    const prior = histories.get(c.shot) || {first: c.time, visible: 0, visits: 0};
    c.first = prior.first; c.visibleBefore = prior.visible; c.visit = prior.visits;
    c.end = cuts[i + 1]?.time ?? duration;
    histories.set(c.shot, {first: prior.first, visible: prior.visible + c.end - c.time, visits: prior.visits + 1});
  });
  const times = cuts.map(c => c.time);
  // MV rhythm is authored before local animation. Verify the declared edit is
  // actually present, rather than accepting labels over one drifting picture.
  const rhythm = [];
  for (const stage of choreography.stages) {
    const blocks = stage.rhythm || [];
    check(Array.isArray(blocks), 'stage rhythm must be an array');
    if (score.intent === 'music-video') check(blocks.length, `stage ${stage.id} needs rhythm blocks`);
    let cursor = stage.start;
    for (const block of blocks) {
      const start = choreography.resolve(block.start), end = choreography.resolve(block.end);
      check(Math.abs(start - cursor) < 1e-9 && end > start && end <= stage.end,
        `rhythm blocks must cover stage ${stage.id} without gaps or overlaps`);
      check(['hold', 'switch', 'alternate'].includes(block.mode), 'unknown rhythm mode');
      check(typeof block.music === 'string' && block.music.trim()
        && typeof block.reason === 'string' && block.reason.trim(), 'rhythm needs music and visual reason');
      check(Array.isArray(block.anchors) && block.anchors.length, 'rhythm needs music anchors');
      const anchors = block.anchors.map(a => choreography.resolve(a));
      check(anchors.every((t, i) => t >= start && t < end && (!i || t > anchors[i - 1])),
        'rhythm music anchors must increase inside the block');
      const visits = cuts.filter(c => c.time < end && c.end > start);
      let switches = 0;
      visits.forEach((c, i) => { if (i && c.shot !== visits[i - 1].shot) switches++; });
      if (block.mode === 'hold') {
        check(switches === 0, 'hold block contains a shot switch');
        check(typeof block.action === 'string' && block.action.trim(), 'hold needs an action and destination');
      } else check(switches >= (block.mode === 'alternate' ? 2 : 1),
        `${block.mode} block has no matching shot changes`);
      const longestVisit = Math.max(...visits.map(c => Math.min(end, c.end) - Math.max(start, c.time)));
      rhythm.push({stage: stage.id, start, end, mode: block.mode, music: block.music,
        reason: block.reason, action: block.action ?? null, anchors, switches, longestVisit});
      cursor = end;
    }
    if (blocks.length) check(Math.abs(cursor - stage.end) < 1e-9, `rhythm ends before stage ${stage.id}`);
  }
  return {
    choreography,
    rhythm: clone(rhythm),
    cuts: cuts.map(c => ({...c})),
    // Flag sub-frame visits for the actual output FPS; never silently move cues.
    frameWarnings(fps) {
      check(finite(fps) && fps > 0, 'fps must be positive');
      return cuts.filter(c => Math.ceil((c.end - 1e-10) * fps) <= Math.ceil((c.time - 1e-10) * fps))
        .map(c => ({shot: c.shot, start: c.time, end: c.end, reason: 'no output frame samples this visit'}));
    },
    at(time) {
      const global = choreography.at(time), t = global.time;
      const cutIndex = Math.max(0, floorIndex(times, t)), visit = cuts[cutIndex];
      const shot = shots.get(visit.shot), clock = shot.clock;
      const elapsed = clock.mode === 'continuous' ? t - visit.first
        : clock.mode === 'visible' ? visit.visibleBefore + t - visit.time : t - visit.time;
      const localTime = clock.offset + elapsed * clock.rate;
      const local = shot.local.at(localTime);
      return {...global,
        rhythm: clone(rhythm.find(b => t >= b.start && (t < b.end || t === duration && b.end === duration)) ?? null),
        values: {...clone(shot.definition.values || {}), ...local.values, ...global.values},
        view: {id: visit.shot, relation: shot.definition.relation,
          setup: clone(shot.definition.setup || {}), visit: visit.visit,
          cutIndex, sinceCut: t - visit.time, localTime, sampleTime: local.time,
          clockMode: clock.mode, previous: cuts[cutIndex - 1]?.shot ?? null},
      };
    },
  };
}

/** Numerical onset runs for bounded inspection, not confirmed musical phrases.
 * Caller chooses gap/minimum; no default cut assignment or effect selection.
 */
export function groupOnsets(rhythmMap, start, end, {maxGap, minEvents = 2}) {
  check(finite(start) && finite(end) && start >= 0 && end > start && end <= rhythmMap.duration,
    'invalid onset window');
  check(finite(maxGap) && maxGap > 0 && Number.isInteger(minEvents) && minEvents > 0, 'invalid grouping options');
  const events = (rhythmMap.onsets || []).filter(o => {
    const t = o.time ?? o.raw_time; return finite(t) && t >= start && t < end;
  }).slice().sort((a, b) => (a.time ?? a.raw_time) - (b.time ?? b.raw_time));
  const runs = [];
  for (const event of events) {
    const t = event.time ?? event.raw_time, last = runs.at(-1);
    if (!last || t - last.at(-1).time > maxGap) runs.push([{id: event.id, time: t}]);
    else last.push({id: event.id, time: t});
  }
  return runs.filter(run => run.length >= minEvents).map(run => ({
    start: run[0].time, end: run.at(-1).time, events: run,
    gaps: run.slice(1).map((e, i) => e.time - run[i].time),
    status: 'numerical adjacency, not listening-confirmed phrase',
  }));
}
