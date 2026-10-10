// Synthetic images/song only: no analysis or rerendering of user music.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {chromium} from 'playwright';
const base=process.argv[2]??'http://127.0.0.1:8772',project='0a1b2c3d4e5f';
const ci=process.argv.includes('--ci');
const root='output/playwright/custom-media';fs.mkdirSync(root,{recursive:true});
const browser=await chromium.launch({channel:process.platform==='win32'?'msedge':undefined});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),errors=[];
await context.addInitScript(project=>{if(window===window.top)localStorage.setItem('beathi.movie.session.1',JSON.stringify({name:'synthetic.wav',projectId:project,seed:17,template:'material-mix'}));},project);
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
if(ci){
 const rhythm=await(await context.request.get(`${base}/api/projects/${project}`)).json(),duration=rhythm.source.duration;
 const timeline={duration,assets:{fixture:{kind:'image',files:['image.png']}},frames:Array.from({length:Math.ceil(duration*30)},(_,i)=>({sinceCut:i/30%2,setup:{sourceId:'fixture',mode:'subject',subjectZoom:[1],phases:[0],attack:.1,settle:.2,phrase:[0,duration],palette:{base:'#202124',accent:'#393a3d',secondary:'#666'},group:'gray'},values:{}}))};
 await context.route('**/api/materials/prepare**',route=>route.fulfill({json:{state:'ready',base:'/test-material/'}}));
 await context.route('**/test-material/material-timeline.json',route=>route.fulfill({json:timeline}));
 const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=16;c.getContext('2d').fillRect(0,0,16,16);return c.toDataURL().split(',')[1];});
 await context.route('**/test-material/image.png',route=>route.fulfill({contentType:'image/png',body:Buffer.from(png,'base64')}));
}
const ready=async()=>{try{await page.waitForFunction(()=>document.querySelector('iframe.mv-preview')?.contentWindow?.previewReady===true,{},{timeout:30000});}catch(error){console.log(await page.evaluate(()=>document.querySelector('iframe.mv-preview')?.contentDocument?.querySelector('#fallback-reason')?.textContent));throw error;}};
const doc=async()=>{const r=await context.request.get(`${base}/api/projects/${project}/custom-media`);assert.ok(r.ok());return r.json();};
const render=async(aspect,resolution,template='voxel')=>{
 const response=await context.request.post(base+'/api/movies',{data:{project_id:project,seed:17,template,output:{aspect,resolution}}});
 assert.equal(response.status(),202,await response.text());let job=await response.json();
 for(let n=0;n<180&&['queued','running'].includes(job.state);n++){await page.waitForTimeout(1000);job=await(await context.request.get(base+'/api/movies/'+job.id)).json();}
 assert.equal(job.state,'complete',JSON.stringify(job));
 const video=await context.request.get(base+job.video_url);assert.ok(video.ok());
 const file=`${root}/${template}-${aspect.replace(':','x')}-${resolution}.mp4`;fs.writeFileSync(file,await video.body());return {file,job};
};
try{
 await page.goto(base+'/app/');await ready();console.log('Custom media preview ready.');
 const images=await page.evaluate(()=>[0,1,2].map(n=>{
  const c=document.createElement('canvas');c.width=400;c.height=300;const q=c.getContext('2d');q.fillStyle=['#203a6a','#713431','#777777'][n];q.fillRect(0,0,400,300);q.fillStyle='#ded6c8';q.beginPath();q.arc(310,110,40,0,Math.PI*2);q.fill();q.fillStyle='#111';q.font='24px sans-serif';q.fillText('FOCUS '+n,30,270);return c.toDataURL('image/png').split(',')[1];
 }));
 const oriented=await page.evaluate(async()=>{
  const c=document.createElement('canvas');c.width=80;c.height=40;c.getContext('2d').fillRect(0,0,80,40);
  const original=await new Promise(resolve=>c.toBlob(resolve,'image/jpeg'));
  const jpeg=new Uint8Array(await original.arrayBuffer());
  const exif=Uint8Array.from([69,120,105,102,0,0,73,73,42,0,8,0,0,0,1,0,18,1,3,0,1,0,0,0,6,0,0,0,0,0,0,0]);
  const rotated=new Blob([jpeg.slice(0,2),Uint8Array.from([255,225,0,exif.length+2]),exif,jpeg.slice(2)],{type:'image/jpeg'});
  const bitmap=await createImageBitmap(rotated);const size=[bitmap.width,bitmap.height];bitmap.close();return size;
 });assert.deepEqual(oriented,[40,80],'EXIF rotation must be applied before computing focus');
 await page.locator('.media-panel input[type=file]').setInputFiles(images.map((b,n)=>({name:`image-${n}.png`,mimeType:'image/png',buffer:Buffer.from(b,'base64')})));
 await page.waitForFunction(()=>document.querySelectorAll('.media-thumb').length===3);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 let saved=await doc();assert.equal(saved.assets.length,3);assert.ok(saved.slots.length>0);console.log('Custom media originals and proxies saved.');
 assert.ok(saved.assets.every(a=>a.proxy),'preview and thumbnails must have small proxies');
 const frame=page.frames().find(f=>f.url().includes('movie-preview'));
 await frame.evaluate(b=>{
  const bytes=Uint8Array.from(atob(b),c=>c.charCodeAt(0)),transfer=new DataTransfer();transfer.items.add(new File([bytes],'dragged.png',{type:'image/png'}));
  document.dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));
 },images[0]);
 await page.waitForTimeout(200);await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 const songName=await page.locator('.tb-name').textContent();
 await page.evaluate(b=>{const bytes=Uint8Array.from(atob(b),c=>c.charCodeAt(0)),transfer=new DataTransfer();transfer.items.add(new File([bytes,Uint8Array.of(0)],'frame-drop.png',{type:'image/png'}));document.querySelector('.mv-frame').dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));},images[0]);
 await page.waitForFunction(()=>document.querySelectorAll('.media-thumb').length===4);
 assert.equal(await page.locator('.tb-name').textContent(),songName,'image drop must not replace the song');
 await page.locator('.media-delete').last().click();await page.waitForFunction(()=>document.querySelectorAll('.media-thumb').length===3);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 const seekChecks=await page.evaluate(async({doc,project})=>{
  const {attachMedia,createMediaSource}=await import('/custom-media.mjs');
  const out=document.createElement('canvas'),source=document.createElement('canvas');out.width=source.width=320;out.height=source.height=180;
  const q=source.getContext('2d');
  const a={...doc,aspect:'16:9',slots:[{start:0,end:4,asset:doc.assets[0].id,fixed:true}]};
  const pictures=createMediaSource(a,id=>`/api/projects/${project}/assets/${id}`,{width:320,height:180,aspect:'16:9'});
  const base=async t=>{await pictures.prepare([t]);q.fillStyle='#101010';q.fillRect(0,0,320,180);const picture=pictures.at(t);if(picture){q.filter='invert(1)';q.drawImage(picture.bitmap,0,0,320,180);q.filter='none';}};
  const render=await attachMedia(out,source,base,pictures);
  await render(1);const initial=out.toDataURL();render.setMedia({...a,slots:[]},2);await render(1);const waiting=out.toDataURL();
  await render(2.5);const after=out.toDataURL();await render(0);await render(2.5);const revisit=out.toDataURL();render.dispose();
  return {waits:initial===waiting,changes:after!==waiting,seek:after===revisit};
 },{doc:saved,project});assert.deepEqual(seekChecks,{waits:true,changes:true,seek:true});
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 await page.locator('.media-thumb').first().locator('button').first().click();
 await page.getByRole('button',{name:'Pin at playhead',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('.media-placement .fixed').length>0);
 saved=await doc();assert.equal(saved.slots[0].fixed,true);
 await page.locator('.media-delete').first().click();
 await page.waitForFunction(()=>document.querySelectorAll('.media-thumb').length===2);
 await page.locator('.media-panel').getByRole('button',{name:'Undo',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('.media-thumb').length===3);
 saved=await doc();assert.ok(saved.slots.some(s=>s.fixed));
 await page.reload();await ready();assert.equal(await page.locator('.media-thumb').count(),3);
 const screenshots=[];
 for(const template of ['voxel','material-mix']){
  await page.locator('.template-select').selectOption(template);await ready();
  assert.equal(await page.locator('.media-panel').count(),template==='voxel'?0:1,'only Prismatic Echo accepts custom images');
  for(const aspect of ['1:1','16:9','9:16']){
   await page.getByLabel('Aspect ratio',{exact:true}).selectOption(aspect);await ready();
   const dimensions=await page.frameLocator('iframe.mv-preview').locator('canvas').evaluate(c=>[c.width,c.height]);
   assert.deepEqual(dimensions,aspect==='16:9'?[960,540]:aspect==='9:16'?[540,960]:[540,540]);
   const frame=page.frames().find(f=>f.url().includes('movie-preview'));await frame.evaluate(()=>window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:parent,data:{type:'t',value:5.2}})));
   await page.waitForTimeout(150);const file=`${root}/${template}-${aspect.replace(':','x')}.png`;await page.screenshot({path:file});screenshots.push(file);
  }
 }
 const exports=[];
 if(!ci){for(const aspect of ['1:1','16:9','9:16'])for(const resolution of [720,1080])exports.push(await render(aspect,resolution));exports.push(await render('9:16',720,'material-mix'));}
 assert.deepEqual(errors,[]);
 fs.writeFileSync(root+(ci?'/ui-verified.json':'/verified.json'),JSON.stringify({screenshots,exports,seekChecks,errors},null,2));
 console.log(ci?'Image import/drop, pin, undo, refresh, scheduled switches, seek parity and three preview aspects passed.':'Import, pin, undo, refresh, six output formats and both template exports passed.');
}finally{await browser.close();}
