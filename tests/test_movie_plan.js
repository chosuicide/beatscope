import assert from 'node:assert/strict';
import {makePlan, selectResponses} from '../beatscope/web/mv-plan.mjs';
const e=(id,time,response_relevance)=>({id,time,response_relevance});
const events=[e(1,1,.9),e(2,1.24,.78),e(3,1.45,.86),e(4,4,.3),e(5,7,.88)];
assert.deepEqual(selectResponses(events).map(e=>e.time),[1,1.24,1.45,7]);
assert.deepEqual(selectResponses([...events].reverse()),selectResponses(events));
const map={source:{duration:10},patterns:{segments:[{id:'s1',start_time:0,end_time:5,family:'A'},{id:'s2',start_time:5,end_time:10,family:'B'}]}};
const response={available:true,events};
const a=makePlan(map,response,10),b=makePlan(map,response,10),c=makePlan(map,response,11);
assert.deepEqual(a,b);assert.notDeepEqual(a.shots.map(s=>s.world),c.shots.map(s=>s.world));
assert.deepEqual(a.shots.map(s=>s.start),c.shots.map(s=>s.start));
assert.equal(a.shots[0].start,0);assert.equal(a.shots.at(-1).end,10);
for(let i=1;i<a.shots.length;i++)assert.equal(a.shots[i-1].end,a.shots[i].start);
assert.throws(()=>makePlan(map,{available:false,events:[]}));
assert.equal(makePlan({source:{duration:2}},{available:true,events:[]}).shots.length,1);
assert.throws(()=>makePlan({source:{duration:601}},response));

// The analysis labels most segments with a single letter, but it also reports
// words: a word family must fall back to the full world palette instead of
// breaking the plan (a real song shipped with a segment family of "BREAK").
const wordy={...map,patterns:{segments:[
  {id:'s1',start_time:0,end_time:5,family:'BREAK'},
  {id:'s2',start_time:5,end_time:10,family:'K'}]}};
const wordyPlan=makePlan(wordy,response,10);
assert.deepEqual(wordyPlan.shots.map(s=>s.start),a.shots.map(s=>s.start));
for(const shot of wordyPlan.shots){
  assert.ok(Number.isInteger(shot.world)&&shot.world>=0&&shot.world<=15,`world out of range: ${shot.world}`);
}
const wordyWorlds=wordyPlan.shots.filter(s=>s.family==='BREAK').map(s=>s.world);
const otherWorlds=wordyPlan.shots.filter(s=>s.family==='K').map(s=>s.world);
assert.ok(wordyWorlds.length&&otherWorlds.length,'both word families must appear');
assert.notDeepEqual(wordyWorlds,otherWorlds.slice(0,wordyWorlds.length),'word families must not open on the same rotation');
// Letter families keep their authored rotation.
const letterWorlds=a.shots.filter(s=>s.family==='A').map(s=>s.world);
assert.deepEqual(letterWorlds,[1,2,13,0,11].slice(0,letterWorlds.length));

console.log('Movie planning: precise times, no-grid, silence, seed, coverage, unavailable gates passed');
