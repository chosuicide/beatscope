// Exercise the real template, GPU and Canvas fallback with asymmetric images.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {chromium} from 'playwright';
const base=process.argv[2]??'http://127.0.0.1:8773';
const browser=await chromium.launch({channel:process.platform==='win32'?'msedge':undefined});
const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
const root='output/playwright/custom-media-effects';fs.mkdirSync(root,{recursive:true});
try{
 await page.route('**/__media-effects-test',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><title>Media effects regression</title>'}));
 await page.goto(base+'/__media-effects-test');
 const result=await page.evaluate(async()=>{
  const {createMediaSource}=await import('/custom-media.mjs');
  const {createMaterialMovie}=await import('/material-frame.mjs');
  const {createMediaColor}=await import('/media-color.mjs');
  const urls={};
  for(const [id,bg]of [['a','#193674'],['b','#861d30']]){
   const c=document.createElement('canvas');c.width=c.height=400;const q=c.getContext('2d');q.fillStyle=bg;q.fillRect(0,0,400,400);
   q.fillStyle='#ead755';q.fillRect(250,20,90,270);q.fillStyle='#eeeeeb';q.beginPath();q.arc(130,160,65,0,7);q.fill();q.fillStyle='#101015';
   for(let i=0;i<15;i++)q.fillRect(i*24,300+(i%3)*12,8,70);urls[id]=c.toDataURL();
  }
  const doc={assets:['a','b'].map(id=>({id,focus:{x:.5,y:.5,zoom:1,fit:'cover'},overrides:{}})),slots:[{start:0,end:8,asset:'a',fixed:true}]};
  const pixels=new Map();let gpuTolerance=false;
  const capture=c=>{const out=document.createElement('canvas');out.width=c.width;out.height=c.height;const q=out.getContext('2d');q.drawImage(c,0,0);const png=out.toDataURL();pixels.set(png,q.getImageData(0,0,out.width,out.height).data);return png;};
  const rows=[];
  const colorInput=await createImageBitmap(await(await fetch(urls.a)).blob()),palette={base:'#16283a',accent:'#3b6686',secondary:'#adc3cc'};
  const cpuGrade=createMediaColor(false),gpuGrade=createMediaColor(true);
  if(gpuGrade.at(colorInput,palette,{enabled:false,strength:1})!==colorInput)throw Error('Disabled color changed the input');
  const cpuPixels=pixels.get(capture(cpuGrade.at(colorInput,palette,{enabled:true,strength:.65})));
  const gpuPixels=pixels.get(capture(gpuGrade.at(colorInput,palette,{enabled:true,strength:.65})));
  for(let i=0;i<cpuPixels.length;i++)if(Math.abs(cpuPixels[i]-gpuPixels[i])>2)throw Error('CPU/GPU palette calculations differ');
  cpuGrade.dispose();gpuGrade.dispose();colorInput.close();
  for(const gpu of [false,true]){
   gpuTolerance=gpu;
   const pictures=createMediaSource(doc,id=>urls[id],{width:320,height:320});
   const samples={};
   for(const mode of ['subject','mirrorSeam','kaleid','negative','trail','palette']){
    pictures.set(mode==='palette'?{...doc,color:{enabled:true,strength:.65}}:doc);
    const canvas=document.createElement('canvas');canvas.width=canvas.height=320;
    const frames=Array.from({length:240},(_,i)=>({sinceCut:i/30%2,setup:{sourceId:'fixture',mode:['negative','trail','palette'].includes(mode)?'subject':mode,subjectZoom:[1],phases:[0],attack:.1,settle:.2,phrase:[0,2],sectors:10,group:'blue',variant:1,trail:mode==='trail',trailAxis:'x',trailDirection:1,surfaceBurst:mode==='negative',negativeBurstFrames:12,negativeWindowCount:2,surfacePose:0,palette:{base:'#16283a',accent:'#3b6686',secondary:'#adc3cc'}},values:{}}));
    const timeline={duration:8,assets:{fixture:{kind:'image',files:['missing-builtin.png']}},frames};
    const render=await createMaterialMovie(canvas,timeline,'/never/',{gpu,mediaSource:pictures});
    await render(.1);const first=capture(canvas);await render(3);await render(.1);assertEqual(first,capture(canvas),`${gpu}:${mode}:seek`);
    if(mode==='negative')for(let visit=0;visit<10;visit++){await render(3);await render(.1);assertEqual(first,capture(canvas),`${gpu}:${mode}:repeat-${visit}`);}
    if(mode==='trail'){
     pictures.set({...doc,slots:[{start:0,end:8,asset:'b',fixed:true}]});render.invalidate();await render(.1);const changed=capture(canvas);if(changed===first)throw Error('Edited source retained old trail cache');
     await render(0);await render(.1);assertEqual(changed,capture(canvas),'edited seek');
     pictures.set(doc);
    }
    if(mode==='palette'){
     pictures.set({...doc,color:{enabled:true,strength:0}});render.invalidate();await render(.1);assertEqual(samples.subject,capture(canvas),'zero strength preserves original');
     pictures.set({...doc,color:{enabled:false,strength:.65}});render.invalidate();await render(.1);assertEqual(samples.subject,capture(canvas),'disabled preserves original');
     pictures.set({...doc,color:{enabled:true,strength:.65}});render.invalidate();await render(.1);assertEqual(first,capture(canvas),'palette restored without stale cache');
    }
    samples[mode]=first;rows.push({gpu,mode,acceleration:render.acceleration.effects,png:first});render.dispose();
   }
   if(new Set(Object.values(samples)).size!==6)throw Error('An effect did not transform the custom picture');
   pictures.dispose();
  }
  return rows;
  function assertEqual(a,b,label){
   if(a===b)return;
   // Hardware multisample resolves can round a few antialiased edge pixels
   // differently. CPU output stays byte-exact; GPU tolerance is tightly bounded.
   if(gpuTolerance){const x=pixels.get(a),y=pixels.get(b);let changed=0,max=0;
    for(let i=0;i<x.length;i+=4){let delta=0;for(let j=0;j<4;j++)delta=Math.max(delta,Math.abs(x[i+j]-y[i+j]));if(delta)changed++;max=Math.max(max,delta);}
    if(changed<=8&&max<=8)return;
   }
   window.effectFailure={a,b,label};throw Error(label+' changed the picture');
  }
 });
 for(const row of result){fs.writeFileSync(`${root}/${row.gpu?'gpu':'cpu'}-${row.mode}.png`,Buffer.from(row.png.split(',')[1],'base64'));delete row.png;}
 assert.deepEqual(errors,[]);fs.writeFileSync(root+'/verified.json',JSON.stringify(result,null,2));
 console.log('Custom pictures share template mirrors, kaleidoscopes, negatives and trails; seek and edited-cache checks passed on both renderer paths.');
}catch(error){const failure=await page.evaluate(()=>window.effectFailure);if(failure){for(const key of ['a','b'])fs.writeFileSync(`${root}/failure-${key}.png`,Buffer.from(failure[key].split(',')[1],'base64'));}throw error;}finally{await browser.close();}
