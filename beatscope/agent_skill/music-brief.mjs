// One cheap bounded query. No audio decoding, rendering, network or dependencies.
import * as timing from './visual-state.js';
import {createChoreography} from './choreography.js';
import {createEditScore, groupOnsets} from './edit-score.js';
import {createTrack} from './beatscope-runtime.js';
import plan from './edit-plan.json' with {type: 'json'};
import {resolveEditPlan} from './edit-plan.js';
import {options,number} from './tool-utils.mjs';
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
    if(args[2]==='--mv'&&(choreography.stages.length!==resolvedPlan.stages.length||choreography.stages.some((s,i)=>Math.abs(s.start-resolvedPlan.stages[i].start)>1e-8||Math.abs(s.end-resolvedPlan.stages[i].end)>1e-8)))
      throw Error('Score stage boundaries do not match the latest saved edit-plan.json');
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
try{
 const positional=args.filter(x=>!x.startsWith('--')).slice(0,args[0]?.startsWith('--')?0:args[1]?.startsWith('--')?1:2);
 const opts=options(args.slice(positional.length),['accents','beats','stages','onsets','help'],['limit','min-strength','activity-points']);
 if(opts.help){console.log('node query.mjs [start end] [--accents] [--beats] [--stages] [--onsets] [--limit 24] [--min-strength 0.8] [--activity-points 16]');process.exit(0);}
 const start=number(positional[0],0,0,map.duration,'start'),end=number(positional[1],map.duration,0,map.duration,'end');
 if(end<=start)throw Error('Query end must follow start');
 const limit=number(opts.limit,24,1,100,'limit'),minStrength=number(opts['min-strength'],0,0,1,'min-strength');
 const pointCount=number(opts['activity-points'],16,1,64,'activity-points');
 if(!Number.isInteger(limit)||!Number.isInteger(pointCount))throw Error('Output limits must be integers');
 const round=n=>Number.isFinite(n)?Math.round(n*1e5)/1e5:null;
 const inWindow=x=>x.time>=start&&x.time<end;
 const bounded=rows=>({total:rows.length,shown:rows.slice(0,limit),truncated:rows.length>limit});
 const segments=(map.patterns?.segments||[]).map(s=>({id:s.id,start:s.start_time??s.start,end:s.end_time??s.end,family:s.family,label:s.display_label??s.label,rms:s.mean_rms??null})).filter(s=>s.start<end&&s.end>start);
 function activity(a,b){
  const result={};
  for(const band of ['low','mid','high','all']){
   const e=map.energy||{},v=e.bands?.[band];if(!v?.length)continue;
   const fps=e.fps||100,origin=e.start||0,lo=Math.max(0,Math.ceil((a-origin)*fps)),hi=Math.min(v.length,Math.ceil((b-origin)*fps));let sum=0,max=0;
   for(let i=lo;i<hi;i++){sum+=v[i];max=Math.max(max,v[i]);}
   result[band]={mean:hi>lo?round(sum/(hi-lo)):null,max:hi>lo?round(max):null};
  }return result;
 }
 function windowSummary(a,b){
  const beats=(map.beats||[]).filter(x=>x.time>=a&&x.time<b),onsets=(map.onsets||[]).filter(x=>(x.time??x.raw_time)>=a&&(x.time??x.raw_time)<b);
  const selection=typeof timing.getResponseEvents==='function'?timing.getResponseEvents(a,b,3):track.responseBetween(a,b,3);
  return {interval:[a,b],beatCount:beats.length,onsetCount:onsets.length,onsetDensity:round(onsets.length/(b-a)),firstBeat:beats[0]?{index:beats[0].index,time:beats[0].time}:null,activity:activity(a,b),selectionStrategy:selection.strategy,measuredAnchorCandidates:selection.events.map(x=>({id:x.onset_id??x.id,time:x.time??x.raw_time}))};
 }
 const stages=resolvedPlan.stages.filter(s=>s.start<end&&s.end>start).map(s=>({id:s.id,...windowSummary(Math.max(start,s.start),Math.min(end,s.end)),interval:[s.start,s.end],queriedInterval:[Math.max(start,s.start),Math.min(end,s.end)],musicalRole:null,roleSource:'unlabelled'}));
 const bins=Array.from({length:pointCount},(_,i)=>{const a=start+(end-start)*i/pointCount,b=start+(end-start)*(i+1)/pointCount;return {interval:[round(a),round(b)],...activity(a,b)};});
 const edited=resolvedPlan.cues.filter(c=>c.manual&&inWindow(c));
 const brief={stages:stages.slice(0,limit),stageCount:stages.length,stagesTruncated:stages.length>limit,
  activityTrend:{semantics:'normalized spectral novelty; activity, not loudness',bins},
  source:map.source?.display_name,duration:map.duration,bpm:map.bpm,interval:[start,end],
  semantics:'Editor stages and resolved cues are authoritative. Musical roles are unlabelled; add authored annotations only after listening or user direction. Strength/support are not calibrated confidence. Measured anchors are candidates, not a cut schedule.',
  timing:map.analysis?.diagnostics?.timing_quality?Object.fromEntries(Object.entries(map.analysis.diagnostics.timing_quality).map(([key,value])=>[key,Array.isArray(value)?{...bounded(value.filter(x=>!Array.isArray(x.interval)||x.interval[0]<end&&x.interval[1]>start)),totalInSong:value.length}:value])):null,
  automaticSections:segments.slice(0,limit).map(s=>({id:s.id,interval:[s.start,s.end],family:s.family,candidateLabel:s.label,waveformRms:s.rms})),
  automaticSectionCount:segments.length,automaticSectionsTruncated:segments.length>limit,
  cueEdits:{deletedInPlan:plan.cues.filter(c=>c.deleted).length,totalInWindow:edited.length,shown:edited.slice(0,limit),truncated:edited.length>limit},window:windowSummary(start,end)};
 const filtered=opts.accents||opts.beats||opts.stages||opts.onsets;
 const accentIds=new Set((map.cues?.accent||[]).map(c=>c.onset_id??c.onset??c.id));
 if(opts.accents)brief.accents=bounded(resolvedPlan.cues.filter(c=>inWindow(c)&&c.strength>=minStrength&&(c.manual||accentIds.has(c.sourceId))));
 if(opts.beats)brief.beats=bounded((map.beats||[]).filter(inWindow).map(({index,time,bar,beat_in_bar,downbeat})=>({index,time,bar,beat_in_bar,downbeat})));
 if(opts.onsets)brief.onsets=bounded(resolvedPlan.cues.filter(c=>inWindow(c)&&c.strength>=minStrength));
 if(filtered){delete brief.automaticSections;delete brief.cueEdits;if(!opts.stages)delete brief.stages;}
 console.log(JSON.stringify(brief,null,2));
}catch(error){console.error(error.message);process.exitCode=2;}
}
