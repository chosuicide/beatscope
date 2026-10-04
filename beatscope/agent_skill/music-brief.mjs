// One cheap bounded query. No audio decoding, rendering, network or dependencies.
import * as timing from './visual-state.js';
import {createChoreography} from './choreography.js';
import {createEditScore, groupOnsets} from './edit-score.js';
import {createTrack} from './beatscope-runtime.js';
import plan from './edit-plan.json' with {type: 'json'};
import {resolveEditPlan} from './edit-plan.js';
const {RHYTHM_MAP: map} = timing;
const track = createTrack(map);
const resolvedPlan = resolveEditPlan(map, plan);

const args = process.argv.slice(2);
if (args[0] === '--score') {
  try {
    if (args.length !== 2 && !(args.length === 3 && args[2] === '--mv'))
      throw new Error('Usage: node music-brief.mjs --score job-score.json [--mv]');
    const {readFile} = await import('node:fs/promises');
    const score = JSON.parse(await readFile(args[1], 'utf8'));
    if (args[2] === '--mv' && (score.intent !== 'music-video' || !Array.isArray(score.shots)))
      throw new Error('MV requires intent:music-video, reusable shots and stage rhythm blocks; motion-only tracks are insufficient.');
    const edit = Array.isArray(score.shots) ? createEditScore(score, timing) : null;
    const compiled = edit || createChoreography(score, timing);
    const choreography = edit?.choreography || compiled;
    const times = [...new Set([0, map.duration, ...Object.values(choreography.moments),
      ...choreography.stages.flatMap(s => [s.start, (s.start + s.end) / 2]),
      ...(edit?.cuts.flatMap(c => [c.time, (c.time + c.end) / 2]) || [])])].filter(t => t >= 0 && t <= map.duration);
    const snapshots = times.map(t => compiled.at(t));
    times.slice().reverse().forEach(t => {
      if (JSON.stringify(compiled.at(t)) !== JSON.stringify(snapshots[times.indexOf(t)]))
        throw new Error('query-order mismatch');
    });
    console.log(JSON.stringify({ok: true, scope: 'Score times, coverage, track writers and repeat/backward query checks; no rendered picture or aesthetic judgement.',
      stages: choreography.stages.map(s => ({id: s.id, start: s.start, end: s.end, focus: s.focus, change: s.change})),
      moments: choreography.moments, checkedTimes: times.length,
      ...(edit ? {cutCount: edit.cuts.length, rhythm: edit.rhythm, frameWarnings30fps: edit.frameWarnings(30)} : {})}, null, 2));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
} else if (args[0] === '--groups') {
  try {
    if (args.length < 4 || args.length > 5) throw new Error('Usage: node music-brief.mjs --groups start end maxGap [minEvents]');
    const runs = groupOnsets(map, Number(args[1]), Number(args[2]),
      {maxGap: Number(args[3]), minEvents: args.length === 5 ? Number(args[4]) : 2});
    console.log(JSON.stringify({status: 'numerical adjacency only; no cut/effect assignment',
      totalRuns: runs.length, shownRuns: Math.min(12, runs.length), runs: runs.slice(0, 12).map(r => ({
        start: r.start, end: r.end, eventCount: r.events.length,
        shownEvents: r.events.slice(0, 24), truncated: r.events.length > 24,
      }))}, null, 2));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
} else {
const start = args.length ? Number(args[0]) : 0;
const end = args.length > 1 ? Number(args[1]) : map.duration;
if (args.length > 2 || !Number.isFinite(start) || !Number.isFinite(end)
    || start < 0 || end <= start || end > map.duration) {
  console.error('Usage: node music-brief.mjs [startSeconds endSeconds]');
  process.exit(1);
}
const round = n => Number.isFinite(n) ? Math.round(n * 1e5) / 1e5 : null;
const segments = (map.patterns?.segments || []).map(s => ({...s,
  start: s.start_time ?? s.start, end: s.end_time ?? s.end,
  label: s.display_label ?? s.label,
})).filter(s => s.start < end && s.end > start);
function windowSummary(a, b) {
  const beats = map.beats.filter(x => x.time >= a && x.time < b);
  const onsets = map.onsets.filter(x => (x.time ?? x.raw_time) >= a && (x.time ?? x.raw_time) < b);
  const activity = {};
  for (const band of ['low', 'mid', 'high', 'all']) {
    const e = map.energy || {}, values = e.bands?.[band];
    if (!values?.length) continue;
    const fps = e.fps || 100, origin = e.start || 0;
    const lo = Math.max(0, Math.ceil((a - origin) * fps));
    const hi = Math.min(values.length, Math.ceil((b - origin) * fps));
    let sum = 0, max = 0;
    for (let i = lo; i < hi; i++) { sum += values[i]; max = Math.max(max, values[i]); }
    activity[band] = {mean: hi > lo ? round(sum / (hi - lo)) : null, max: hi > lo ? round(max) : null};
  }
  const selection = typeof timing.getResponseEvents === 'function'
    ? timing.getResponseEvents(a, b, 3) : track.responseBetween(a, b, 3);
  const candidates = selection.events;
  return {interval: [a, b], beatCount: beats.length, onsetCount: onsets.length,
    firstBeat: beats[0] ? {index: beats[0].index, time: beats[0].time} : null,
    activity, selectionStrategy: selection.strategy,
    measuredAnchorCandidates: candidates.map(x => ({id: x.onset_id ?? x.id, time: x.time ?? x.raw_time}))};
}
const editedCues = resolvedPlan.cues.filter(c => c.manual && c.time >= start && c.time < end);
const brief = {
  source: map.source?.display_name, duration: map.duration, bpm: map.bpm,
  semantics: 'Spectral novelty is activity, not loudness. stages come from edit-plan.json; automaticSections and measuredAnchorCandidates are analysis evidence. Use resolveEditPlan cues for authored responses, never fire deleted cues or the old time of moved cues. No cut/effect schedule is supplied.',
  timing: map.analysis?.diagnostics?.timing_quality || null,
  interval: [start, end],
  stages: resolvedPlan.stages.filter(s => s.start < end && s.end > start).map(s => ({id: s.id, interval: [s.start, s.end],
    ...windowSummary(Math.max(start, s.start), Math.min(end, s.end))})),
  automaticSections: segments.map(s => ({id: s.id, interval: [s.start, s.end], family: s.family,
    candidateLabel: s.label, waveformRms: s.mean_rms ?? null})),
  cueEdits: {deletedInPlan: plan.cues.filter(c => c.deleted).length,
    totalInWindow: editedCues.length, shown: editedCues.slice(0, 24), truncated: editedCues.length > 24},
};
if (!segments.length || args.length) brief.window = windowSummary(start, end);
console.log(JSON.stringify(brief, null, 2));
}
