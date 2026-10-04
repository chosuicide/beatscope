import assert from 'node:assert/strict';
import fs from 'node:fs';
import {makeMaterialScore,compileMaterialScore} from '../beatscope/web/material-plan.mjs';
const library=JSON.parse(fs.readFileSync('beatscope/web/material-library.json')),setups=JSON.parse(fs.readFileSync('beatscope/web/material-setups.json'));
const plan={duration:12,seed:7,stages:[{start:0},{start:4},{start:8}],shots:Array.from({length:12},(_,i)=>({start:i,end:i+1,stageId:`s${Math.floor(i/4)}`,family:'A',kind:i%4===0?'stage':'cue',eventId:i}))};
assert.equal(library.assets.length,51);
assert.equal(new Set(library.assets.map(a=>a.id)).size,51);
for(const id of ['material-mix']){
 const score=makeMaterialScore(plan,library,setups,id),compiled=compileMaterialScore(score);
 assert.deepEqual(makeMaterialScore(plan,library,setups,id),score);
 for(const s of score.shots){assert.equal(s.setup.rgb,false);assert.ok(!['rupture','ridgeSlice','card','mosaic'].includes(s.setup.mode));}
 for(const t of [0,2.4,7.1,11.9,3.3]){const a=compiled.at(t);compiled.at(0);assert.deepEqual(compiled.at(t),a);}
 assert.equal(compiled.cuts.length,12);
 if(id==='material-mix')assert.deepEqual([...new Set(score.shots.map(s=>s.setup.group))],['gray','blue','red']);
 else assert.ok(score.shots.every(s=>s.setup.group===id.replace('material-','')));
}
const edited={...plan,shots:plan.shots.filter(s=>s.start!==2).map(s=>s.start===3?{...s,start:3.25}:s)};
const compiled=compileMaterialScore(makeMaterialScore(edited,library,setups,'material-mix'));
assert.ok(compiled.cuts.some(c=>c.time===3.25));assert.ok(!compiled.cuts.some(c=>c.time===2));
console.log('Material score: source library, deterministic seek, edited cues and prohibited layouts checked.');

const longPlan={duration:24,seed:17,stages:[{start:0}],shots:Array.from({length:4},(_,i)=>({start:i*6,end:(i+1)*6,stageId:'long',kind:'cue'}))};
assert.ok(makeMaterialScore(longPlan,library,setups,'material-mix').shots.every(s=>!['water','birdB'].includes(s.setup.sourceId)));
const dense={duration:60,seed:17,stages:[{start:0}],shots:Array.from({length:180},(_,i)=>({start:i/3,end:(i+1)/3,stageId:'same',kind:'cue'}))};
const d=makeMaterialScore(dense,library,setups,'material-mix'),bursts=d.cuts.filter((c,i)=>d.shots[i].setup.surfaceBurst);
assert.ok(bursts.length<13);for(let i=1;i<bursts.length;i++)assert.ok(bursts[i].at-bursts[i-1].at>=5);
assert.ok(d.shots.every(s=>s.setup.mediaHold===0&&s.setup.blankFrames===null&&s.setup.flashFrames===0));
for(let i=1;i<d.shots.length;i++){const a=d.shots[i-1].setup,b=d.shots[i].setup;if(i%4&&a.sourceId===b.sourceId)assert.ok(Math.abs(a.retime[1][1]-b.retime[0][1])<1e-5,'Motion must continue across motif cuts');}
const gaps={duration:100,seed:17,stages:[{start:0},{start:2},{start:42},{start:82}],shots:[{start:0,end:2,stageId:'a'},{start:2,end:42,stageId:'b'},{start:42,end:82,stageId:'c'},{start:82,end:100,stageId:'d'}]};
const g=makeMaterialScore(gaps,library,setups,'material-mix');assert.equal(g.shots[0].setup.sourceId,g.shots[3].setup.sourceId);assert.ok(Math.abs(g.shots[0].setup.retime[1][1]-g.shots[3].setup.retime[0][1])<1e-5,'Unused wall time must not consume source footage');
const longDense={duration:120,seed:17,stages:[{start:0},{start:40},{start:80}],shots:Array.from({length:60},(_,i)=>({start:i*2,end:(i+1)*2,stageId:`s${Math.floor(i/20)}`,kind:'cue'}))};
const v4=makeMaterialScore(longDense,library,setups,'material-mix');
assert.ok(v4.shots.every(s=>library.assets.find(a=>a.id===s.setup.sourceId).kind==='video'),'Long passages must never use photography');
assert.ok(v4.shots.some(s=>s.setup.surfaceBurst&&s.setup.negativeBurstFrames>=16),'Negatives need readable longer episodes');
assert.ok(v4.shots.some(s=>s.setup.surfaceBurst&&s.setup.negativeBurstFrames===3),'Brief negative accents remain available');
assert.ok(v4.shots.some(s=>s.setup.waterLandscape),'Scenery receives the approved relay');
assert.ok(v4.shots.every(s=>!(s.setup.waterLandscape&&s.setup.surfaceBurst)),'Contour and negative effects must not collide');
