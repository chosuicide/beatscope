// Generic authored choreography. No objects, styles, renderer or random emitters.
const finite = x => typeof x === 'number' && Number.isFinite(x);
const clamp = x => Math.max(0, Math.min(1, x));
const copy = x => Array.isArray(x) ? [...x] : x;
const numeric = x => finite(x) || (Array.isArray(x) && x.length > 0 && x.every(finite));
const sameShape = (a, b) => finite(a) && finite(b)
  || Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every(finite) && b.every(finite);
const interpolate = (a, b, p) => Array.isArray(a) ? a.map((v, i) => v + (b[i] - v) * p) : a + (b - a) * p;
const add = (a, b, p) => Array.isArray(a) ? a.map((v, i) => v + b[i] * p) : a + b * p;
const curves = {
  linear: p => p,
  smooth: p => p * p * (3 - 2 * p),
  'in-cubic': p => p ** 3,
  'out-cubic': p => 1 - (1 - p) ** 3,
  hold: () => 0,
};
function check(ok, message) { if (!ok) throw new Error(`BeatScope choreography: ${message}`); }
function floorIndex(list, t) {
  let lo = 0, hi = list.length;
  while (lo < hi) { const m = (lo + hi) >>> 1; if (list[m] <= t) lo = m + 1; else hi = m; }
  return lo - 1;
}

/** Compile a job-local score once; at(t) is independent of playback/query order.
 * Anchors: seconds, {beat: zeroBasedIndex}, {onset: measuredId}, {moment: name}.
 * Optional offsetBeats respects real beat spacing; offset seconds is added last.
 * Tracks own one named renderer value each. All tracks may share any moment.
 */
export function createChoreography(score, timing) {
  check(score && Array.isArray(score.stages) && Array.isArray(score.tracks), 'stages/tracks required');
  const map = timing?.RHYTHM_MAP;
  const duration = map?.duration;
  check(finite(duration) && duration > 0 && typeof timing.getVisualState === 'function', 'timing module required');
  const beats = (map.beats || []).map(b => b.time);
  check(beats.every((t, i) => finite(t) && (!i || t > beats[i - 1])), 'beat times must increase');
  const onsets = new Map((map.onsets || []).map(o => [o.id, o.time ?? o.raw_time]));
  const moments = score.moments || {};
  const cache = new Map();
  const resolving = new Set();
  function beatPosition(t) {
    check(beats.length >= 2, 'metric motion requires at least two real beats');
    const i = Math.max(0, Math.min(beats.length - 2, floorIndex(beats, t)));
    return i + (t - beats[i]) / (beats[i + 1] - beats[i]);
  }
  function beatTime(p) {
    check(beats.length >= 2 && finite(p), 'metric anchor requires a real beat grid');
    const i = Math.max(0, Math.min(beats.length - 2, Math.floor(p)));
    return beats[i] + (p - i) * (beats[i + 1] - beats[i]);
  }
  function resolve(anchor) {
    if (finite(anchor)) return anchor;
    check(anchor && typeof anchor === 'object', 'invalid time anchor');
    const kinds = ['beat', 'onset', 'moment'].filter(k => Object.hasOwn(anchor, k));
    check(kinds.length === 1, 'anchor needs exactly one beat/onset/moment');
    let t;
    if (kinds[0] === 'beat') {
      check(Number.isInteger(anchor.beat) && anchor.beat >= 0 && anchor.beat < beats.length, 'unknown beat index');
      t = beats[anchor.beat];
    } else if (kinds[0] === 'onset') {
      t = onsets.get(anchor.onset);
      check(finite(t), `unknown onset ${anchor.onset}`);
    } else {
      const name = anchor.moment;
      check(Object.hasOwn(moments, name) && !resolving.has(name), `unknown/cyclic moment ${name}`);
      if (cache.has(name)) t = cache.get(name);
      else { resolving.add(name); t = resolve(moments[name]); resolving.delete(name); cache.set(name, t); }
    }
    if (Object.hasOwn(anchor, 'offsetBeats')) {
      check(finite(anchor.offsetBeats), 'offsetBeats must be finite');
      if (anchor.offsetBeats !== 0) t = beatTime(beatPosition(t) + anchor.offsetBeats);
    }
    check(!Object.hasOwn(anchor, 'offset') || finite(anchor.offset), 'offset must be finite');
    return t + (anchor.offset || 0);
  }
  Object.keys(moments).forEach(name => resolve({moment: name}));
  const stageIds = new Set();
  const stages = score.stages.map(s => {
    check(typeof s.id === 'string' && s.id && !stageIds.has(s.id), 'unique stage id required');
    stageIds.add(s.id);
    check(typeof s.focus === 'string' && s.focus.trim() && typeof s.change === 'string' && s.change.trim(),
      `stage ${s.id} needs focus/change`);
    const start = resolve(s.start), end = resolve(s.end);
    check(start >= 0 && end <= duration + 1e-6 && end > start, `invalid stage span ${s.id}`);
    return {...s, start, end};
  }).sort((a, b) => a.start - b.start);
  check(stages.length > 0 && Math.abs(stages[0].start) < 1e-6
    && Math.abs(stages.at(-1).end - duration) < 1e-6, 'stages must cover the whole song');
  stages.forEach((s, i) => check(!i || Math.abs(s.start - stages[i - 1].end) < 1e-6, 'stage gap/overlap'));
  const ids = new Set();
  const tracks = score.tracks.map(track => {
    check(typeof track.id === 'string' && track.id && !ids.has(track.id), 'one track writer per id');
    check(![...ids].some(id => id.startsWith(track.id + '.') || track.id.startsWith(id + '.')),
      `overlapping property writers for ${track.id}`);
    ids.add(track.id);
    check(Array.isArray(track.keys) && track.keys.length > 0, `keys required for ${track.id}`);
    const keys = track.keys.map(k => {
      const time = resolve(k.at), ease = k.ease || 'linear';
      check(finite(time) && Object.hasOwn(curves, ease), `bad key/ease for ${track.id}`);
      check(numeric(k.value) || typeof k.value === 'string' || typeof k.value === 'boolean', 'unsupported key value');
      return {time, value: copy(k.value), ease};
    }).sort((a, b) => a.time - b.time);
    keys.forEach((k, i) => {
      check(!i || k.time > keys[i - 1].time, `duplicate key time for ${track.id}`);
      check(!i || sameShape(k.value, keys[i - 1].value) || keys[i - 1].ease === 'hold',
        `discrete/shape changes require hold for ${track.id}`);
    });
    let pace = null;
    if (track.pace) {
      const p = track.pace, start = resolve(p.from), end = resolve(p.to);
      check(end > start && finite(p.every) && p.every > 0 && sameShape(keys[0].value, p.step), 'bad beat pacing');
      check(keys.every(k => sameShape(keys[0].value, k.value)), 'paced track must stay numeric');
      const mode = p.mode || 'step';
      check(['step', 'travel'].includes(mode), 'pace mode must be step/travel');
      pace = {start, end, every: p.every, step: copy(p.step), origin: beatPosition(start), mode};
    }
    let activity = null;
    if (track.activity) {
      const a = track.activity;
      check(['low', 'mid', 'high', 'all'].includes(a.band) && sameShape(keys[0].value, a.amount), 'bad activity mapping');
      check(keys.every(k => sameShape(keys[0].value, k.value)), 'activity track must stay numeric');
      activity = {band: a.band, amount: copy(a.amount)};
    }
    return {id: track.id, keys, times: keys.map(k => k.time), pace, activity};
  });
  function sampleTrack(track, t, facts) {
    const {keys} = track;
    const i = floorIndex(track.times, t);
    let value;
    if (i < 0) value = copy(keys[0].value);
    else if (i >= keys.length - 1) value = copy(keys.at(-1).value);
    else {
      const a = keys[i], b = keys[i + 1], p = clamp((t - a.time) / (b.time - a.time));
      value = a.ease === 'hold' ? copy(a.value) : interpolate(a.value, b.value, curves[a.ease](p));
    }
    const p = track.pace;
    if (p) {
      let count = Math.max(0, (beatPosition(Math.min(p.end, Math.max(p.start, t))) - p.origin) / p.every);
      if (p.mode === 'step') count = Math.floor(count + 1e-9);
      value = add(value, p.step, count);
    }
    if (track.activity) {
      const a = track.activity;
      check(finite(facts[a.band]), `missing activity band ${a.band}`);
      value = add(value, a.amount, facts[a.band]);
    }
    return value;
  }
  const stageTimes = stages.map(s => s.start);
  return {
    // Useful to an adapter/one-shot check; these are the actual resolved times.
    moments: Object.freeze(Object.fromEntries(cache)),
    stages: stages.map(s => ({...s})),
    resolve,
    at(time) {
      check(finite(time), 'query time must be finite');
      const t = Math.max(0, Math.min(duration, time));
      const stage = stages[Math.max(0, floorIndex(stageTimes, t))];
      const facts = timing.getVisualState(t);
      const values = Object.fromEntries(tracks.map(track => [track.id, sampleTrack(track, t, facts)]));
      return {time: t, stage: {...stage}, values, facts};
    },
  };
}
