import assert from 'node:assert/strict';
import test from 'node:test';
import {arrangeMedia,normalizeMediaSlot,mediaRatio,focusRect,snapPoints,snapTime,beatLength,placeSlot,freeRange,clipWindow} from '../beatscope/web/custom-media.mjs';
import {movieOutput} from '../beatscope/web/movie-output.mjs';
const rhythm={source:{duration:16},beats:Array.from({length:32},(_,i)=>({time:i*.5}))};
const asset=id=>({id,focus:{x:.5,y:.5,zoom:1,fit:'cover'},overrides:{}});
const doc={schema:'beathi-media-1',source_sha256:'hash',target:.8,seed:11,assets:[asset('a'),asset('b')],slots:[]};

test('mixed-media swaps remove image offsets and fit short videos without moving starts',()=>{
 const video={...asset('v'),kind:'video',duration:1};
 const slot={start:2,end:4,asset:'v',fixed:false};
 assert.deepEqual(normalizeMediaSlot(slot,video),{...slot,end:3,offset:0});
 assert.deepEqual(normalizeMediaSlot({...slot,asset:'a',offset:.5},asset('a')),{...slot,asset:'a'});
 const swapped=arrangeMedia({...doc,slots:[{start:0,end:2,asset:'a',fixed:true,offset:1}]},rhythm,null);
 assert.ok(!('offset' in swapped.slots[0]));
});
test('time coverage is deterministic, avoids adjacent repeats and preserves unaffected assignments',()=>{
 const arranged=arrangeMedia(doc,rhythm,null);
 assert.deepEqual(arranged,arrangeMedia(doc,rhythm,null));
 assert.ok(mediaRatio(arranged,16)<=.8);
 for(let i=1;i<arranged.slots.length;i++)if(arranged.slots[i-1].end===arranged.slots[i].start)assert.notEqual(arranged.slots[i-1].asset,arranged.slots[i].asset);
 const added=arrangeMedia({...arranged,assets:[...arranged.assets,asset('c')]},rhythm,null);
 assert.deepEqual(added.slots,arranged.slots);
});
test('pins count toward duration and survive low targets and reshuffling',()=>{
 const fixed={start:0,end:8,asset:'a',fixed:true};
 const low=arrangeMedia({...doc,target:.1,slots:[fixed]},rhythm,null,true);
 assert.deepEqual(low.slots,[fixed]);assert.equal(mediaRatio(low,16),.5);
});
test('new placements can prioritize the playhead without moving existing slots',()=>{
 const initial=arrangeMedia({...doc,target:.125},rhythm,null,false,9);
 assert.equal(initial.slots.length,1);assert.equal(initial.slots[0].start,8);
 const added=arrangeMedia({...initial,target:.25},rhythm,null,false,1);
 assert.ok(added.slots.some(s=>s.start===0));assert.ok(added.slots.some(s=>s.start===8&&s.asset===initial.slots[0].asset));
});
test('pinning evicts a same-image automatic neighbor but never another user pin',()=>{
 const a={start:0,end:2,asset:'a',fixed:true},b={start:2,end:4,asset:'a',fixed:false};
 const result=arrangeMedia({...doc,slots:[a,b]},rhythm,null);
 assert.notEqual(result.slots.find(s=>s.start===2)?.asset,'a');
 const pins=arrangeMedia({...doc,slots:[a,{...b,fixed:true}]},rhythm,null);
 assert.ok(pins.slots.some(s=>s.start===2&&s.asset==='a'&&s.fixed));
});
test('snap points are the sorted unique beats, boundaries and song edges',()=>{
 const plan={boundaries:[{time:4},{time:10}],cues:[{id:'u:1',time:3.7,deleted:true}]};
 const points=snapPoints(rhythm,plan);
 assert.equal(points[0],0);assert.equal(points.at(-1),16);
 assert.ok(points.includes(4)&&points.includes(10)&&points.includes(7.5));
 assert.ok(!points.includes(3.7),'cues are not snap points');assert.equal(new Set(points).size,points.length);
 assert.equal(snapTime(4.26,points),4.5);assert.equal(snapTime(0.2,points),0);
 assert.equal(beatLength(rhythm),.5);
 assert.equal(beatLength({source:{duration:8},beats:[{time:0},{time:1},{time:2}]}),1);
 assert.equal(beatLength({source:{duration:8}}),.5);
});
test('placeSlot replaces non-fixed overlaps and the moved copy, keeps other pins',()=>{
 const fixed={start:0,end:2,asset:'a',fixed:true},auto={start:2,end:6,asset:'b',fixed:false},moved={start:6,end:8,asset:'a',fixed:true};
 const next=placeSlot({...doc,slots:[fixed,auto,moved]},{start:8,end:10,asset:'a'},{start:6,asset:'a'});
 assert.deepEqual(next.slots,[fixed,auto,{start:8,end:10,asset:'a',fixed:true}]);
 const shorter=placeSlot(doc,{start:1,end:1.02,asset:'a'});
 assert.equal(shorter,doc,'a slot under 50ms is a no-op');
 const overPin=placeSlot({...doc,slots:[fixed]},{start:1,end:3,asset:'b'});
 assert.ok(overPin.slots.some(s=>s.fixed&&s.asset==='a'),'pins are not evicted');
 assert.ok(!overPin.slots.some(s=>!s.fixed),'non-fixed overlap removed');
});
test('video assets respect clip length, keep deterministic offsets and keep valid ones',()=>{
 const video=()=>({id:'v',kind:'video',clip:'c',duration:2,focus:{x:.5,y:.5,zoom:1,fit:'cover'},overrides:{}});
 const vdoc={...doc,assets:[asset('a'),video()],seed:7};
 const a1=arrangeMedia(vdoc,rhythm,null),a2=arrangeMedia(vdoc,rhythm,null);
 assert.deepEqual(a1,a2,'same seed, same offsets');
 for(const s of a1.slots.filter(s=>s.asset==='v')){
  assert.equal(typeof s.offset,'number');
  assert.ok(s.offset>=0&&s.offset+(s.end-s.start)<=2+1/30+1e-6,`offset ${s.offset} fits the 2s clip`);
 }
 // A clip shorter than every ≥1s cell would be skipped; a 2s clip fills 1–2s cells only.
 for(const s of a1.slots)if(s.asset==='v')assert.ok(s.end-s.start<=2);
 // Kept slots preserve a still-valid offset; invalid ones get healed.
 const kept=arrangeMedia({...a1,slots:a1.slots},rhythm,null);
 for(const s of kept.slots.filter(s=>s.asset==='v'))assert.ok(s.offset+s.end-s.start<=2+1/30+1e-6);
 const healed=arrangeMedia({...vdoc,slots:[{start:0,end:2,asset:'v',fixed:true,offset:1.5}]},rhythm,null);
 assert.equal(healed.slots[0].offset,0,'offset 1.5 overflows a 2s clip in a 2s slot → healed to 0');
});
test('clipWindow trims the left edge into the offset and caps the right edge at the clip',()=>{
 const slot={start:4,end:6,asset:'v',fixed:true,offset:1};
 // Left edge slides the clip window 1:1 with the start move.
 assert.deepEqual(clipWindow(4,slot,'l',5,.5),{start:5,end:6,offset:2});
 assert.deepEqual(clipWindow(4,slot,'l',3,.5),{start:3,end:6,offset:0},'offset clamps at 0');
 assert.deepEqual(clipWindow(4,slot,'l',5.8,.5),{start:5.5,end:6,offset:2.5},'min length wins');
 assert.deepEqual(clipWindow(4,slot,'r',8,.5),{start:4,end:7,offset:1},'right edge stops at the clip end');
 assert.deepEqual(clipWindow(4,slot,'r',5,.5),{start:4,end:5,offset:1});
 const placed=placeSlot(doc,{start:0,end:2,asset:'v',offset:.5});
 assert.equal(placed.slots[0].offset,.5,'placeSlot carries the offset');
 assert.equal(placed.slots[0].fixed,true);
});
test('freeRange is bounded by neighbouring pins and resumes after an occupied hit',()=>{
 const slots=[{start:0,end:2,asset:'a',fixed:true},{start:6,end:8,asset:'b',fixed:true}];
 const d={...doc,slots};
 assert.deepEqual(freeRange(d,4,16),{min:2,max:6});
 assert.deepEqual(freeRange(d,1,16),{min:2,max:6},'a drop inside a pin resumes after it');
 assert.deepEqual(freeRange(d,9,16),{min:8,max:16});
 assert.deepEqual(freeRange(d,1,16,{start:0,asset:'a'}),{min:0,max:6},'ignored key frees its own span');
});
test('focus follows aspect ratio without distortion or exposed edges',()=>{
 for(const aspect of ['1:1','16:9','9:16']){
  const {width,height}=movieOutput(aspect,1080),r=focusRect(1800,1200,width,height,{x:.8,y:.2,zoom:1,fit:'cover'},.7);
  assert.equal(r.width/r.height,1.5);assert.ok(r.x<=0&&r.y<=0&&r.x+r.width>=width&&r.y+r.height>=height);
 }
});
