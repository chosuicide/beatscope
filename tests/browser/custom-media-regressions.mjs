// Mixed imports, inspector switches and retryable saves against the real API.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {chromium} from 'playwright';
const base=process.argv[2]??'http://127.0.0.1:8773',project='0a1b2c3d4e5f';
const work=fs.mkdtempSync(path.join(os.tmpdir(),'beathi-mixed-'));
const browser=await chromium.launch({channel:process.platform==='win32'?'msedge':undefined});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.addInitScript(project=>{localStorage.setItem('beathi.movie.session.1',JSON.stringify({name:'synthetic.wav',projectId:project,seed:17,template:'material-mix'}));},project);
const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
const get=()=>context.request.get(`${base}/api/projects/${project}/custom-media`);
const read=async()=> (await get()).json();
const put=async doc=>{const response=await get();return context.request.put(`${base}/api/projects/${project}/custom-media`,{headers:{'If-Match':response.headers()['etag']},data:doc});};
const upload=async(name,bytes)=>{const r=await context.request.post(`${base}/api/projects/${project}/assets`,{headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(name)},data:bytes});assert.ok(r.ok(),await r.text());return (await r.json()).asset;};
try{
 const rhythm=await(await context.request.get(`${base}/api/projects/${project}`)).json(),duration=rhythm.source.duration;
 const frames=Array.from({length:Math.ceil(duration*30)},(_,i)=>({sinceCut:i/30%2,setup:{sourceId:'fixture',mode:'subject',subjectZoom:[1],phases:[0],attack:.1,settle:.2,phrase:[0,duration],palette:{base:'#202124',accent:'#393a3d',secondary:'#666'},group:'gray'},values:{}}));
 await context.route('**/api/materials/prepare**',r=>r.fulfill({json:{state:'ready',base:'/test-material/'}}));
 await context.route('**/test-material/material-timeline.json',r=>r.fulfill({json:{duration,assets:{fixture:{kind:'image',files:['image.png']}},frames}}));
 const pngs=await page.evaluate(()=>['#365984','#d83146'].map(color=>{const c=document.createElement('canvas');c.width=c.height=96;const q=c.getContext('2d');q.fillStyle=color;q.fillRect(0,0,96,96);q.fillStyle='#eeeeee';q.fillRect(20,30,40,50);return c.toDataURL().split(',')[1];}));
 await context.route('**/test-material/image.png',r=>r.fulfill({contentType:'image/png',body:Buffer.from(pngs[0],'base64')}));
 const clips=[];
 for(const [name,length,color]of [['long',4,'red'],['short',1,'blue']]){
  const file=path.join(work,name+'.mp4');const run=spawnSync('ffmpeg',['-v','error','-y','-f','lavfi','-i',`color=${color}:size=160x96:rate=30`,'-t',String(length),'-pix_fmt','yuv420p',file],{encoding:'utf8'});assert.equal(run.status,0,run.stderr);
  clips.push({file,bytes:fs.readFileSync(file)});
 }
 const image=await upload('mixed.png',Buffer.from(pngs[0],'base64'));
 const original=await upload('long.mp4',clips[0].bytes);
 const derivedResponse=await context.request.post(`${base}/api/projects/${project}/assets/${original.asset_id}/derive`);assert.ok(derivedResponse.ok());const derived=await derivedResponse.json();
 const focus={x:.5,y:.5,zoom:1,fit:'cover'};
 const seed={...await read(),target:1,assets:[{id:image.asset_id,proxy:image.asset_id,focus,overrides:{}},{id:original.asset_id,kind:'video',proxy:derived.poster,clip:derived.clip,duration:4,focus,overrides:{}}],slots:[{start:0,end:2,asset:image.asset_id,fixed:false},{start:2,end:4,asset:original.asset_id,fixed:false,offset:0}]};
 assert.ok((await put(seed)).ok());
 await page.goto(base+'/app/');await page.waitForFunction(()=>document.querySelector('iframe.mv-preview')?.contentWindow?.previewReady===true);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button')?.disabled);
 await page.locator('.media-panel input[type=file]').setInputFiles({name:'short.mp4',mimeType:'video/mp4',buffer:clips[1].bytes});
 await page.waitForFunction(()=>document.querySelectorAll('.media-thumb.video').length===2,{},{timeout:30000});
 let saved=await read(),short=saved.assets.find(a=>a.kind==='video'&&a.duration<2);
 assert.ok(short);const shortSlot=saved.slots.find(s=>s.asset===short.id&&s.start===0);
 assert.ok(shortSlot&&shortSlot.end<=1.01&&shortSlot.offset===0,'short clip imported over a longer image cell');
 for(const asset of [saved.assets.find(a=>a.id===original.asset_id),short]){
  await page.locator(`.media-axis > button`).filter({has:page.locator(`img[src*="${asset.proxy}"]`)}).first().click();
  await page.waitForSelector('.media-inspect-image video');
  assert.equal(await page.locator('.media-inspect-image video').getAttribute('src'),`/api/projects/${project}/assets/${asset.clip}`);
 }
 // Save failure must retain the original and a retry action, then recover.
 await page.evaluate(()=>{document.querySelector('audio').currentTime=.1;});
 let rejectSave=true;
 await page.route(`**/api/projects/${project}/custom-media`,route=>{
  if(route.request().method()==='PUT'&&rejectSave){rejectSave=false;return route.fulfill({status:500,json:{message:'Synthetic save failure'}});}
  return route.continue();
 });
 await page.locator('.media-panel input[type=file]').setInputFiles({name:'retry.png',mimeType:'image/png',buffer:Buffer.from(pngs[1],'base64')});
 await page.waitForSelector('.media-upload.error');
 await page.locator('.media-upload.error button').first().click();
 await page.waitForFunction(()=>document.querySelectorAll('.media-thumb').length===4);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 saved=await read();const fresh=saved.assets.find(a=>a.kind!=='video'&&a.id!==image.asset_id),slot=saved.slots.find(s=>s.asset===fresh.id&&s.start===0);
 assert.ok(slot&&!('offset'in slot),'image imported over a video slot has no video offset');
 await page.locator(`.media-thumb[data-asset="${fresh.id}"]`).click();
 await page.getByRole('button',{name:'Move earlier',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 saved=await read();for(const slot of saved.slots){const a=saved.assets.find(a=>a.id===slot.asset);assert.equal('offset'in slot,a.kind==='video');}
 assert.deepEqual(errors,[]);
 console.log('Mixed-media import, short clips, inspector switching, failed-save retry and mixed reordering passed.');
}finally{
 await browser.close();assert.equal(path.dirname(fs.realpathSync(work)),fs.realpathSync(os.tmpdir()));assert.ok(path.basename(work).startsWith('beathi-mixed-'));fs.rmSync(work,{recursive:true,force:true});
 const r=await fetch(`${base}/api/projects/${project}/custom-media`);if(r.ok){const d=await r.json();await fetch(`${base}/api/projects/${project}/custom-media`,{method:'PUT',headers:{'Content-Type':'application/json','If-Match':r.headers.get('etag')},body:JSON.stringify({...d,assets:[],slots:[]})});}
}
