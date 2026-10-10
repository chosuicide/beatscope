// Actual paint code, real built-in frames and synthetic custom media; no song analysis.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {chromium} from 'playwright';
const base=process.argv[2]??'http://127.0.0.1:8772';
const root='output/playwright/paint-template';fs.mkdirSync(root,{recursive:true});
const browser=await chromium.launch({channel:process.platform==='win32'?'msedge':undefined});
const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/__paint-test',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><title>Paint regression</title>'}));
try{
 await page.goto(base+'/__paint-test');
 const fixture=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=32;const q=c.getContext('2d');q.fillStyle='#a46328';q.fillRect(0,0,32,32);return c.toDataURL();});
 await page.route('**/custom/a.png',route=>route.fulfill({contentType:'image/png',body:Buffer.from(fixture.split(',')[1],'base64')}));
 const result=await page.evaluate(async()=>{
  const {createPaintMovie}=await import('/paint-frame.mjs');
  const {createMediaSource}=await import('/custom-media.mjs');
  const {createTemplateMovie}=await import('/movie-factory.mjs');
  const map={source:{duration:4},beats:Array.from({length:8},(_,i)=>({time:i*.5})),energy:{fps:30,bands:{low:Array(120).fill(.1)}}};
  const plan={template:'paint',seed:1,duration:4,paintScore:{shots:[[0,'dandelion','oil'],[2,'hibiscus','charcoal'],[4,'rose','ink'],[6,'tulips','raw']]}};
  const rows=[],capture=c=>c.toDataURL(),make=(w,h)=>{const c=document.createElement('canvas');c.width=w;c.height=h;return c;};
  const picture=make(320,320),q=picture.getContext('2d');q.fillStyle='#253654';q.fillRect(0,0,320,320);q.fillStyle='#e99036';q.fillRect(24,60,200,120);q.fillStyle='#eee';q.beginPath();q.arc(260,260,30,0,7);q.fill();const url=picture.toDataURL();
  const doc={assets:[{id:'a',focus:{x:.5,y:.5,zoom:1,fit:'cover'},overrides:{}}],slots:[{start:0,end:4,asset:'a',fixed:true}]};
  // A delayed playback clock must catch up once, not replay growing history.
  const linear=make(240,240),jumped=make(240,240),oilPlan={...plan,paintScore:{shots:[[0,'dandelion','oil']]}};
  const lr=await createPaintMovie(linear,map,null,oilPlan),jr=await createPaintMovie(jumped,map,null,oilPlan);
  for(let i=1;i<=36;i++)await lr(i/30);
  for(let i=3;i<=36;i+=3)await jr(i/30);
  if(capture(linear)!==capture(jumped))throw Error('Skipped clock frames changed the paint');
  if(jr.diagnostics().paintSteps!==37)throw Error('Skipped clock frames replayed old painting history');
  if(jr.diagnostics().loads>4)throw Error('Oil-only playback decoded unused movie frames');
  lr.dispose();jr.dispose();
  for(const [w,h]of [[320,180],[240,240],[180,320]]){
   const canvas=make(w,h),render=await createPaintMovie(canvas,map,null,plan);
   const diag=render.diagnostics();if(JSON.stringify(diag.shots.map(s=>s.start))!=='[0,1,2,3]')throw Error('Whole-second shots were interpreted as beat indices');
   for(let i=1;i<=5;i++)await render(i/30);const first=capture(canvas);
   await render(1.2);await render(5/30);if(first!==capture(canvas))throw Error('Built-in paint seek changed the frame');
   const stats=render.diagnostics();if(stats.decodedFrames>12||stats.decodedBytes>32*1024*1024||stats.preparedFrames>8)throw Error('Frame cache exceeded its bounds');
   rows.push({aspect:`${w}:${h}`,builtin:first,stats});render.dispose();
   const custom=make(w,h),media=createMediaSource(doc,()=>url,{width:w,height:h,aspect:w===h?'1:1':w>h?'16:9':'9:16'});
   const painted=await createPaintMovie(custom,map,null,plan,{mediaSource:media});await painted(5/30);const changed=capture(custom);
   if(changed===first)throw Error('Custom picture did not enter the paint pipeline');
   await painted(1.2);await painted(5/30);if(changed!==capture(custom))throw Error('Custom paint seek changed the frame');
   media.set({...doc,color:{enabled:true,strength:.8}});painted.invalidate();await painted(5/30);if(changed===capture(custom))throw Error('Palette did not reach paint');
   media.set(doc);painted.invalidate();await painted(5/30);if(changed!==capture(custom))throw Error('Restoring original color left stale strokes');
   rows.at(-1).custom=changed;painted.dispose();media.dispose();
  }
  // Video export's pre-extracted frames share the same source path; each is unique.
  const frames={};for(let i=0;i<20;i++){q.fillStyle=i<10?'#1c5296':'#a22d36';q.fillRect(0,0,320,320);q.fillStyle='#fafafa';q.fillRect(20+i*8,50,40,150);frames[i]=picture.toDataURL();}
  const video={...doc,assets:[{...doc.assets[0],kind:'video',duration:4}],slots:[{start:0,end:4,asset:'a',fixed:true,offset:0}]};
  const vc=make(320,180),vp={...plan,media:video,mediaFiles:{a:'mp4'},mediaFrames:{0:120},paintScore:{shots:[[0,'dandelion','raw']]}};
  const source=createMediaSource(video,()=>url,{width:320,height:180,mediaFrames:{0:120},frameUrl:(i,k)=>frames[k]??url});
  const vr=await createPaintMovie(vc,map,null,vp,{mediaSource:source});await vr(.1);const va=capture(vc);await vr(.5);if(va===capture(vc))throw Error('Video frames stopped');await vr(.1);if(va!==capture(vc))throw Error('Video seek is not deterministic');vr.dispose();source.dispose();
  // A slot can start/end between beats inside one accumulating paint shot.
  const partial={...doc,slots:[{start:.4,end:.9,asset:'a',fixed:true}]},pc=make(240,240);
  const pm=createMediaSource(partial,()=>url,{width:240,height:240});
  const pr=await createPaintMovie(pc,map,null,{...plan,paintScore:{shots:[[0,'dandelion','oil']]}},{mediaSource:pm});
  for(let i=1;i<=24;i++)await pr(i/30);const middle=capture(pc);
  await pr(1.1);await pr(.8);if(middle!==capture(pc))throw Error('Fractional material boundary retained stale paint');pr.dispose();pm.dispose();
  const fc=make(240,240),factory=await createTemplateMovie(fc,map,null,{...plan,media:doc,mediaFiles:{a:'png'}},{editableMedia:false});factory.dispose();
  // Painterly events must also work after seek, with the actual aspect layout.
  for(const effect of ['trips','sgraf','silk','fold','sketch']){
   const c=make(180,320),m=createMediaSource(doc,()=>url,{width:180,height:320,aspect:'9:16'});
   const score={shots:[[0,'dandelion','oil']],[effect]:[[0,2]]};
   const r=await createPaintMovie(c,map,null,{...plan,paintScore:score},{mediaSource:m});
   await r(.3);const before=capture(c);await r(.7);await r(.3);
   if(before!==capture(c))throw Error(effect+' event is not seek-safe');r.dispose();m.dispose();
  }
  return rows;
 });
 for(const row of result)for(const key of ['builtin','custom']){fs.writeFileSync(`${root}/${row.aspect.replace(':','x')}-${key}.png`,Buffer.from(row[key].split(',')[1],'base64'));delete row[key];}
 assert.deepEqual(errors,[]);fs.writeFileSync(root+'/verified.json',JSON.stringify(result,null,2));console.log('Paint media, palette, time units, three aspects, seek and bounded caches passed.');
}finally{await browser.close();}
