// End-to-end video clip support: upload → derive → lane → offset trim →
// preview motion → deterministic export. Synthesizes a 4s testsrc clip with
// FFmpeg so the frames carry a visible counter.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {chromium} from 'playwright';
const base=process.argv[2]??'http://127.0.0.1:8772',project='0a1b2c3d4e5f';
const ci=process.argv.includes('--ci');
const root='output/playwright/custom-media-video';fs.mkdirSync(root,{recursive:true});
const work=fs.mkdtempSync(path.join(os.tmpdir(),'beathi-vid-'));
const clipPath=path.join(work,'clip.mp4');
const ffmpeg=(...args)=>{const run=spawnSync('ffmpeg',['-v','error','-y',...args],{encoding:'utf8'});assert.equal(run.status,0,run.stderr);};
const ffprobe=(...args)=>{const run=spawnSync('ffprobe',['-v','error',...args],{encoding:'utf8'});assert.equal(run.status,0,run.stderr);return run.stdout.trim();};
ffmpeg('-f','lavfi','-i','testsrc=size=640x360:rate=30','-t','4','-pix_fmt','yuv420p',clipPath);
const clipBytes=fs.readFileSync(clipPath);
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
// Read pixels without auto-scrolling the inspector out from under pointer coordinates.
const canvasShot=async()=>Buffer.from(await page.frames().find(f=>f.url().includes('movie-preview')).evaluate(()=>document.querySelector('canvas').toDataURL().split(',')[1]),'base64');
const render=async(tag)=>{
 const started=Date.now();
 const response=await context.request.post(base+'/api/movies',{data:{project_id:project,seed:17,template:'material-mix',output:{aspect:'1:1',resolution:720}}});
 assert.equal(response.status(),202,await response.text());let job=await response.json();
 for(let n=0;n<300&&['queued','running'].includes(job.state);n++){await page.waitForTimeout(1000);job=await(await context.request.get(base+'/api/movies/'+job.id)).json();}
 assert.equal(job.state,'complete',JSON.stringify(job));
 const video=await context.request.get(base+job.video_url);assert.ok(video.ok());
 const file=`${root}/video-${tag}.mp4`;fs.writeFileSync(file,await video.body());return {file,job,seconds:(Date.now()-started)/1000};
};
try{
 // Clean fixture: wipe the saved arrangement before the UI loads it.
 const prior=await context.request.get(`${base}/api/projects/${project}/custom-media`);
 if(prior.ok()){const d=await prior.json();if(d.assets.length||d.slots.length){
  await context.request.put(`${base}/api/projects/${project}/custom-media`,{headers:{'If-Match':prior.headers()['etag']},data:{...d,assets:[],slots:[]}});
 }}
 await page.goto(base+'/app/');await ready();console.log('Preview ready.');
 // --- upload: tile → progress → processing → video thumbnail ---
 await page.locator('.media-panel input[type=file]').setInputFiles({name:'clip.mp4',mimeType:'video/mp4',buffer:clipBytes});
 await page.waitForSelector('.media-upload',{timeout:10000});
 await page.waitForSelector('.media-upload.processing',{timeout:30000});
 await page.screenshot({path:`${root}/processing.png`});
 await page.waitForSelector('.media-thumb.video',{timeout:120000});
 const badge=await page.locator('.media-thumb.video .media-dur').textContent();
 assert.match(badge??'',/^0:0[34]$/,'duration badge shows the clip length');
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 let saved=await doc();
 const videoAsset=saved.assets.find(a=>a.kind==='video');
 assert.ok(videoAsset?.clip&&videoAsset.proxy&&videoAsset.duration>3.5,'derived video row with clip+poster+duration');
 console.log('Upload → derive → thumbnail (badge',badge.trim(),').');
 // --- drag onto the lane: fixed video slot at offset 0 ---
 const thumb=await page.locator('.media-thumb.video').boundingBox();
 const axisBox=await page.locator('.media-axis').boundingBox();
 await page.mouse.move(thumb.x+thumb.width/2,thumb.y+thumb.height/2);
 await page.mouse.down();
 await page.mouse.move(axisBox.x+axisBox.width*.3,axisBox.y+axisBox.height/2,{steps:12});
 await page.mouse.up();
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 saved=await doc();
 let vslot=saved.slots.find(s=>s.asset===videoAsset.id&&s.fixed);
 assert.ok(vslot,'fixed video slot placed');
 assert.equal(vslot.offset,0);
 assert.ok(vslot.end-vslot.start<=videoAsset.duration+1e-6);
 console.log(`Video slot ${vslot.start.toFixed(2)}–${vslot.end.toFixed(2)} offset ${vslot.offset}.`);
 // --- inspector: clip scrubber changes the offset + live preview ---
 await page.waitForTimeout(300); // drag suppression window
 await page.locator(`.media-axis button.fixed`).filter({has:page.locator(`img[src*="${videoAsset.proxy}"]`)}).first().click();
 await page.waitForSelector('.media-scrub',{timeout:10000});
 // The inspector is height-capped and scrollable; pointer coordinates must
 // target the visible scrubber rather than its offscreen layout box.
 await page.locator('.media-scrub').scrollIntoViewIfNeeded();
 const scrub=await page.locator('.media-scrub').boundingBox();
 const before=await canvasShot();
 await page.mouse.move(scrub.x+scrub.width*.25,scrub.y+scrub.height/2);
 await page.mouse.down();
 await page.mouse.move(scrub.x+scrub.width*.6,scrub.y+scrub.height/2,{steps:8});
 let during=await canvasShot();
 for(let n=0;n<40&&during.equals(before);n++){await page.waitForTimeout(100);during=await canvasShot();}
 if(during.equals(before)){console.log('Scrub diagnostic',await page.evaluate(()=>({time:document.querySelector('audio').currentTime,offset:document.querySelector('.media-scrub')?.getAttribute('aria-valuenow'),fallback:document.querySelector('iframe.mv-preview')?.contentDocument?.querySelector('#fallback-reason')?.textContent})));fs.writeFileSync(root+'/scrub-before.png',before);fs.writeFileSync(root+'/scrub-during.png',during);}
 assert.notDeepEqual(during,before,'preview shows the moved offset live');
 await page.mouse.up();
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 saved=await doc();
 vslot=saved.slots.find(s=>s.asset===videoAsset.id&&s.fixed);
 assert.ok(vslot.offset>0,'scrub committed a new offset');
 assert.ok(vslot.offset+(vslot.end-vslot.start)<=videoAsset.duration+1/30+1e-6);
 console.log(`Clip scrub → offset ${vslot.offset.toFixed(2)}.`);
 // --- preview motion + fps inside the video slot ---
 const iframe=page.frames().find(f=>f.url().includes('movie-preview'));
 await iframe.evaluate(()=>{window.__framesDrawn=0;});
 await page.evaluate(async t=>{const a=document.querySelector('audio');a.currentTime=t;await a.play();},vslot.start+.1);
 await page.waitForTimeout(200);
 const frames=[await canvasShot()];
 await page.waitForTimeout(400);frames.push(await canvasShot());
 await page.waitForTimeout(400);frames.push(await canvasShot());
 assert.notDeepEqual(frames[1],frames[0],'video slot shows motion in preview');
 assert.notDeepEqual(frames[2],frames[1],'video slot keeps animating');
 const t0=Date.now(),count0=await iframe.evaluate(()=>window.__framesDrawn);
 await page.waitForTimeout(Math.max(300,(vslot.end-vslot.start-.3)*1000));
 const drawn=(await iframe.evaluate(()=>window.__framesDrawn))-count0;
 const fps=drawn/((Date.now()-t0)/1000);
 await page.evaluate(()=>document.querySelector('audio')?.pause());
 console.log(`Preview drew ${drawn} frames in ${(Date.now()-t0).toFixed(0)}ms → ${fps.toFixed(1)} fps during the video slot.`);
 assert.ok(fps<=32,'count native rendered frames, not repeated preview callbacks');
 if(ci){assert.deepEqual(errors,[]);console.log('Video import, trim and moving preview passed (CI).');}
 else{
 // --- export determinism ---
 const inside=vslot.start+.4; // song time safely inside the slot
 const one=await render('a'),two=await render('b');
 for(const file of [one.file,two.file]){
  const probe=ffprobe('-show_entries','stream=width,height','-of','csv=p=0',file);
  assert.match(probe,/720,720/);
 }
 const shots=[];
 for(const [tag,file] of [['a1',one.file],['a2',one.file],['b1',two.file],['b2',two.file]]){
  const at=inside+(tag.endsWith('2')?.5:0),out=`${root}/frame-${tag}.jpg`;
  ffmpeg('-ss',String(at),'-i',file,'-frames:v','1','-q:v','3',out);
  shots.push(out);
 }
 assert.notDeepEqual(fs.readFileSync(shots[0]),fs.readFileSync(shots[1]),'two export frames 0.5s apart differ (motion made it out)');
 assert.deepEqual(fs.readFileSync(shots[0]),fs.readFileSync(shots[2]),'render A vs B frame 1 identical');
 assert.deepEqual(fs.readFileSync(shots[1]),fs.readFileSync(shots[3]),'render A vs B frame 2 identical');
 console.log(`Export deterministic: two renders byte-identical frames. Second render took ${two.seconds.toFixed(1)}s.`);
 assert.deepEqual(errors,[]);
 fs.writeFileSync(`${root}/verified.json`,JSON.stringify({offset:vslot.offset,fps:Number(fps.toFixed(1)),renderSeconds:[one.seconds,two.seconds]},null,2));
 console.log('Video import, lane slot, clip scrubbing, preview motion and deterministic export all passed.');
 }
}finally{
 await browser.close();assert.equal(path.dirname(fs.realpathSync(work)),fs.realpathSync(os.tmpdir()));assert.ok(path.basename(work).startsWith('beathi-vid-'));fs.rmSync(work,{recursive:true,force:true});
 // Leave the fixture clean for the other media tests.
 try{const g=await fetch(`${base}/api/projects/${project}/custom-media`);if(g.ok){const d=await g.json();if(d.assets.length||d.slots.length)await fetch(`${base}/api/projects/${project}/custom-media`,{method:'PUT',headers:{'Content-Type':'application/json','If-Match':g.headers.get('etag')},body:JSON.stringify({...d,assets:[],slots:[]})});}}catch{}
}
