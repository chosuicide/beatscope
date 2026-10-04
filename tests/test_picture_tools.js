import assert from 'node:assert/strict';
import {frame2D, frame3D, createPictureBindings} from '../beatscope/runtime/picture-tools.js';
import {createEditScore} from '../beatscope/runtime/edit-score.js';

const near = (actual, expected) => assert.ok(Math.abs(actual-expected)<1e-10, `${actual} != ${expected}`);
const rect = {x:180,y:70,width:240,height:120}, viewport = {width:1280,height:720};
const pose = frame2D(rect, viewport, {coverage:[.75,.6],anchor:[.6,.4]});
near((rect.x+rect.width/2)*pose.scale+pose.x, 768);
near((rect.y+rect.height/2)*pose.scale+pose.y, 288);
assert.ok(rect.width*pose.scale<=960 && rect.height*pose.scale<=432);
near(rect.height*pose.scale,432);
assert.deepEqual(pose.matrix, [pose.scale,0,0,pose.scale,pose.x,pose.y]);
// Viewport aspect is significant; framing is not a fixed camera-distance preset.
assert.notEqual(frame2D(rect, {width:720,height:1280}, {coverage:.75}).scale, pose.scale);
assert.throws(()=>frame2D(rect,viewport), /coverage/);
assert.throws(()=>frame2D({...rect,width:0},viewport,{coverage:.8}), /rectangle/);
assert.throws(()=>frame2D(rect,viewport,{coverage:.8,anchor:[1.1,.5]}), /anchor/);

const box = {min:[-2,-1,-3],max:[2,1,3]};
const cam = frame3D(box,{direction:[0,0,1],fov:60,aspect:16/9,coverage:.8,near:.1});
near(cam.target[0],0); near(cam.target[1],0); near(cam.target[2],0);
// Front face is three units nearer than the center; ignoring depth crops it.
near(cam.position[2],3+2/(Math.tan(Math.PI/6)*(16/9)*.8));
const translated = frame3D({min:[3,1,-5],max:[7,3,1]},
  {direction:[0,0,1],fov:60,aspect:16/9,coverage:.8,near:.1});
near(translated.position[0],cam.position[0]+5);
near(translated.position[1],cam.position[1]+2);
near(translated.position[2],cam.position[2]-2);
assert.throws(()=>frame3D(box,{direction:[0,1,0],fov:60,aspect:1,coverage:.8}), /parallel/);
assert.throws(()=>frame3D(box,{direction:[0,0,1],fov:180,aspect:1,coverage:.8}), /perspective/);

const timing = {RHYTHM_MAP:{duration:4,beats:[0,.4,1.1,1.7,2.8,4].map(time=>({time})),onsets:[]},
  getVisualState: time=>({time})};
const edit = createEditScore({stages:[{id:'all',start:0,end:4,focus:'subject',change:'retained change',entry:'A'}],
  shots:[{id:'A',relation:'whole',setup:{coverage:.8}},{id:'B',relation:'detail',setup:{coverage:.95}}],
  cuts:[{at:.4,shot:'B'},{at:1.7,shot:'A'}],
  tracks:[{id:'world.travel',keys:[{at:0,value:0}],pace:{from:0,to:4,every:1,step:1,mode:'travel'}}]},timing);
const drawn = {}, order=[];
const view = setup=>{order.push('view');drawn.camera=frame2D(rect,viewport,setup)};
const binding = createPictureBindings(edit,{views:{A:view,B:view},values:{'world.travel':[
  v=>{order.push('near');drawn.near=v*40},v=>{order.push('far');drawn.far=v*7},
]}});
const expected = new Map([0,.4,1.2,1.7,3,4].map(t=>{binding.apply(t);return[t,JSON.stringify(drawn)]}));
for(const t of [4,0,1.7,.4,3,1.2,4]) {binding.apply(t);assert.equal(JSON.stringify(drawn),expected.get(t))}
order.length=0; binding.apply(1.7);
assert.deepEqual(order,['view','near','far']);
assert.ok(drawn.near>drawn.far && drawn.far>0); // one musical progress drives multiple layers after returning
assert.throws(()=>createPictureBindings(edit,{views:{A:view}}), /unbound shot B/);
const incomplete=createPictureBindings(edit,{views:{A:view,B:view}});
order.length=0;
assert.throws(()=>incomplete.apply(1), /unbound property world.travel/);
assert.deepEqual(order,[]); // reject a missing binding before mutating the picture
console.log('Picture framing, musical fan-out, returns, reverse seeks and binding failures passed');
