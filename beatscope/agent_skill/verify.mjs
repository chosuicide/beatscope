#!/usr/bin/env node
// Timing observations, not an aesthetic verdict or proof that the beat grid is right.
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {existsSync} from 'node:fs';
import {options,number,jsonFile,saveJson,processTool,probe,hashFile} from './tool-utils.mjs';
import * as music from './visual-state.js';
import plan from './edit-plan.json' with {type:'json'};
import {resolveEditPlan} from './edit-plan.js';
import {createEditScore} from './edit-score.js';
import {demoTiming} from './examples/directing/draw.mjs';

function nearestTime(rows,time){
 let lo=0,hi=rows.length;
 while(lo<hi){const mid=(lo+hi)>>>1;if(rows[mid].time<time)lo=mid+1;else hi=mid;}
 const before=rows[lo-1],after=rows[lo];
 return !before?after:!after?before:time-before.time<=after.time-time?before:after;
}

async function main(){
 const opts=options(process.argv.slice(2),['help'],['example','score','video','start','threshold','tolerance-ms','out']);
 if(opts.help){console.log('node verify.mjs --score ../score.json [--video ../sample.mp4 --start 0] [--tolerance-ms 80 --threshold 0.06 --out ../sync.json]\nTutorial: --example accent --video ../accent.mp4');return;}
 const root=dirname(fileURLToPath(import.meta.url));
 const names=['accent','transition','transition-late','buildup','dense','pause','return'];
 if(opts.example&&!names.includes(opts.example))throw Error('Unknown example');
 if(!opts.score&&!opts.example)throw Error('Provide --score or --example');
 if(opts.score&&opts.example)throw Error('Choose --score or --example');
 const score=await jsonFile(opts.example?resolve(root,`examples/directing/${opts.example}.json`):resolve(opts.score));
 const timing=opts.example?demoTiming(score):music;
 const map=timing.RHYTHM_MAP;
 const resolved=resolveEditPlan(map,opts.example?{schema:'beatscope-edit-plan-1',duration:map.duration,source_sha256:map.source.sha256,boundaries:[],cues:[]}:plan);
 const compiled=createEditScore(score,timing);
 if(!opts.example&&score.source?.sha256&&score.source.sha256!==map.source?.sha256)throw Error('Score source does not match timing source');
 const tolerance=number(opts['tolerance-ms'],80,0,2000,'tolerance-ms');
 const threshold=number(opts.threshold,.06,0,1,'threshold');
 let start=number(opts.start,0,0,map.duration,'start'),fps=30,duration=null,changes=[],binding=null,audioPresent=null;
 if(opts.video){
  const file=resolve(opts.video),info=await probe(file),v=info.streams?.find(s=>s.codec_type==='video');
  if(!v)throw Error('No video stream');
  audioPresent=info.streams.some(s=>s.codec_type==='audio');
  const [n,d]=v.avg_frame_rate.split('/').map(Number);fps=n/d;
  if(!Number.isFinite(fps)||fps<=0||fps>240)throw Error('Unsupported frame rate');
  duration=Number(info.format.duration);
  const renderReport=file+'.render.json';
  if(existsSync(renderReport)){
   binding=await jsonFile(renderReport);
   if(binding.sha256!==await hashFile(file))throw Error('Render report does not match video bytes');
   if(opts.start!==undefined&&Math.abs(start-binding.settings.start)>1e-8)throw Error('--start conflicts with render report');
   start=binding.settings.start;
   if(!opts.example&&binding.audio_sha256&&map.source?.sha256&&binding.audio_sha256!==map.source.sha256&&!(binding.audioIdentity==='transcoded-match'&&binding.sourceAudioSha256===map.source.sha256&&binding.referenceSha256===map.source.sha256))throw Error('Render audio does not match timing source');
  }
  if(!Number.isFinite(start)||start<0||start+duration>map.duration+1/fps)throw Error('Video interval exceeds score duration');
  let previous=null,pending=Buffer.alloc(0),index=0;
  const diffs=[];
  await processTool(process.env.BEATSCOPE_FFMPEG||'ffmpeg',['-v','error','-i',file,'-an','-vf',`fps=${fps},scale=64:64:flags=area,format=gray`,'-f','rawvideo','pipe:1'],{timeout:300000,onData:data=>{
   pending=Buffer.concat([pending,data]);
   while(pending.length>=4096){
    const frame=Buffer.from(pending.subarray(0,4096));pending=pending.subarray(4096);
    let diff=0;if(previous){for(let i=0;i<4096;i++)diff+=Math.abs(frame[i]-previous[i]);diff/=4096*255;diffs.push({frame:index,time:start+index/fps,magnitude:diff});}
    previous=frame;index++;
   }
  }}).done;
  changes=diffs.filter((x,i)=>x.magnitude>=threshold&&x.magnitude>=(diffs[i-1]?.magnitude??0)&&x.magnitude>(diffs[i+1]?.magnitude??0));
 }
 const end=duration===null?map.duration:start+duration;
 const declarations=score.sync??[];
 if(!Array.isArray(declarations)||declarations.length>10000)throw Error('sync must be an array of at most 10000 events');
 const cueById=new Map(resolved.cues.map(c=>[c.id,c]));
 const events=declarations.map(event=>{
  if(!event||typeof event!=='object'||typeof event.cueId!=='string')throw Error('Each sync event needs at and cueId');
  const at=compiled.choreography.resolve(event.at),cue=cueById.get(event.cueId);
  const offset=cue?(at-cue.time)*1000:null;
  const valid=Boolean(cue)&&Math.abs(offset)<1e-6;
  const inVideo=opts.video&&at>=start&&at<end;
  const expectedFrame=opts.video&&!inVideo?null:Math.max(0,Math.ceil((at-start)*fps-1e-8));
  const nearest=inVideo?nearestTime(changes,at):null;
  const cutPresent=event.kind!=='cut'||compiled.cuts.some(c=>Math.abs(c.time-at)<1e-8);
  return {kind:event.kind??'action',cueId:event.cueId,at,cueTime:cue?.time??null,sourceTime:cue?.sourceTime??null,
   authoredOffsetMs:offset,binding:valid&&cutPresent?'matched':!cue?'missing/deleted cue':!cutPresent?'declared cut absent':'stale or shifted cue',
   expectedFrame,quantizationMs:expectedFrame===null?null:(start+expectedFrame/fps-at)*1000,
   observed:!opts.video?'not inspected':!inVideo?'outside excerpt':nearest&&Math.abs(nearest.time-at)*1000<=tolerance+1000/fps?'change candidate':'unverified',
   nearestChange:nearest?{time:nearest.time,offsetMs:(nearest.time-at)*1000,magnitude:nearest.magnitude}:null};
 });
 const cuts=compiled.cuts.filter(c=>c.time>0&&c.time>=start&&c.time<end).map(c=>{
  const cue=nearestTime(resolved.cues,c.time),change=nearestTime(changes,c.time);
  return {at:c.time,shot:c.shot,nearestCue:cue?.id??null,offsetMs:cue?(c.time-cue.time)*1000:null,nearestPictureChange:change?{time:change.time,offsetMs:(change.time-c.time)*1000}:null};
 });
 const stageBinding=opts.example||compiled.choreography.stages.length===resolved.stages.length&&compiled.choreography.stages.every((s,i)=>Math.abs(s.start-resolved.stages[i].start)<1e-8&&Math.abs(s.end-resolved.stages[i].end)<1e-8);
 const report={schema:'beatscope-sync/1',scope:'Declared events versus saved edited cues; coarse picture-change candidates. No proof of musical correctness, event causality or aesthetics.',
  interval:[start,end],fps,framePrecisionMs:1000/fps,threshold,toleranceMs:tolerance,
  scoreValid:true,savedStages:stageBinding?'matched':'stale stage boundaries',audioPresent,audioIdentity:binding?'bound by render report':'unverified',audioMatch:binding?.audioIdentity??null,declaredEvents:events,cuts,
  observedChangeCount:changes.length,observedChangesTruncated:changes.length>500,observedChanges:changes.slice(0,500).map(c=>{const cue=nearestTime(resolved.cues,c.time);return {...c,nearestCue:cue?.id??null,cueTime:cue?.time??null,offsetMs:cue?(c.time-cue.time)*1000:null};}),
  frameWarnings:compiled.frameWarnings(fps),
  unboundCuts:cuts.filter(c=>!declarations.some(d=>d.kind==='cut'&&Math.abs(compiled.choreography.resolve(d.at)-c.at)<1e-8)).length,
  limitations:['Fades, subject motion, color shifts and flashes can all produce candidates.','Subtle, continuous or half-covered transitions need visual review; absence of a candidate is unverified.','Frame quantization is reported; source cues are never moved.']};
 if(opts.out)await saveJson(resolve(opts.out),report);
 console.log(JSON.stringify(report,null,2));
 if(!stageBinding||events.some(e=>e.binding!=='matched'))process.exitCode=1;
}
main().catch(error=>{console.error(error.message);process.exitCode=2;});
