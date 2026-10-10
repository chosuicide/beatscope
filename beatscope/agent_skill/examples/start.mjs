#!/usr/bin/env node
// A runnable geometry example using this song's saved stages/cues. Never overwrites a project.
import {mkdir,writeFile,access} from 'node:fs/promises';
import {dirname,relative,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {options,number} from '../tool-utils.mjs';
import * as music from '../visual-state.js';
import plan from '../edit-plan.json' with {type:'json'};
import {resolveEditPlan} from '../edit-plan.js';
import {createEditScore} from '../edit-score.js';
try{
 const opts=options(process.argv.slice(2),['help'],['out','start','seconds']);
 if(opts.help){console.log('node examples/start.mjs --out ../sample-project [--start 0 --seconds 3]');process.exit(0);}
 if(!opts.out)throw Error('Provide a new --out project directory');
 const out=resolve(opts.out),root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
 const map=music.RHYTHM_MAP,edited=resolveEditPlan(map,plan);
 const start=number(opts.start,0,0,map.duration,'start'),seconds=number(opts.seconds,Math.min(3,map.duration-start),.01,map.duration-start,'seconds');
 const events=edited.cues.filter(c=>c.time>=start&&c.time<start+seconds).sort((a,b)=>b.strength-a.strength);
 const chosen=events[0]??null;
 const stages=edited.stages.map(s=>({id:s.id,start:s.start,end:s.end,entry:'main',focus:'One geometric subject',change:'Recover after one selected response; preserve saved stage boundaries.',rhythm:[{
  start:s.start,end:s.end,mode:'hold',music:'Saved passage timing; one candidate response when present.',reason:'Keep one subject; a measured response changes its scale.',anchors:[chosen&&chosen.time>=s.start&&chosen.time<s.end?chosen.time:s.start],action:'Briefly compress, respond, recover to the original scale.'}]}));
 const keys=[{at:0,value:1,ease:'hold'}];
 if(chosen){const at=chosen.time;for(const [t,value,ease] of [[Math.max(0,at-5/30),1,'in-cubic'],[Math.max(0,at-1/30),.85,'hold'],[at,1.45,'out-cubic'],[Math.min(map.duration,at+8/30),1,'hold']]){
  if(t===keys.at(-1).at)keys[keys.length-1]={at:t,value,ease};else keys.push({at:t,value,ease});
 }}
 const score={intent:'music-video',source:{sha256:map.source.sha256},stages,shots:[{id:'main',relation:'One subject responding to a selected edited cue',setup:{mode:'accent'},clock:{mode:'continuous'}}],cuts:[],tracks:[{id:'actor.scale',keys}],sync:chosen?[{at:chosen.time,cueId:chosen.id,kind:'impact',sourceTime:chosen.sourceTime}]:[]};
 createEditScore(score,music);
 for(const name of ['score.json','scene.html']){try{await access(resolve(out,name));throw Error(`Already exists: ${name}; choose a new directory`);}catch(e){if(e.code!=='ENOENT')throw e;}}
 await mkdir(out,{recursive:true});
 const modulePath=name=>JSON.stringify((relative(out,resolve(root,name)).replaceAll('\\','/').startsWith('.')?'':'./')+relative(out,resolve(root,name)).replaceAll('\\','/'));
 const html=`<!doctype html><meta charset="utf-8"><style>html,body{margin:0}canvas{display:block}</style><canvas id="frame" width="640" height="640"></canvas><script type="module">
import * as music from ${modulePath('visual-state.js')};
import {createEditScore} from ${modulePath('edit-score.js')};
import {draw} from ${modulePath('examples/directing/draw.mjs')};
const score=await (await fetch('./score.json')).json(),edit=createEditScore(score,music),canvas=document.querySelector('canvas');
window.beatscopeRender={duration:music.RHYTHM_MAP.duration,selector:'#frame',ready:Promise.resolve(),resize(w,h){canvas.width=w;canvas.height=h},renderAt(t){draw(canvas,edit.at(t),t)}};
window.beatscopeRender.renderAt(${start});
</script>`;
 await writeFile(resolve(out,'score.json'),JSON.stringify(score,null,2)+'\n',{flag:'wx'});
 await writeFile(resolve(out,'scene.html'),html,{flag:'wx'});
 console.log(JSON.stringify({project:out,start,seconds,selectedCue:chosen?.id??null,scope:'New instructional sample only; no song reanalysis or existing project changes.'}));
}catch(error){console.error(error.message);process.exitCode=1;}
