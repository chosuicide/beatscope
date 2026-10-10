// Pointer-based media-panel interactions: lane drags, resizes, Esc cancel,
// Ctrl+Z, undo toast, upload progress tiles, live focus preview, touch long-press.
// Same fixture conventions as custom-media-smoke.mjs (synthetic project + mocked
// material feed). Starts by resetting the saved media doc via its ETag'd PUT.
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const base=process.argv[2]??'http://127.0.0.1:8772',project='0a1b2c3d4e5f';
const browser=await chromium.launch({channel:process.platform==='win32'?'msedge':undefined});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),errors=[];
await context.addInitScript(project=>{if(window===window.top)localStorage.setItem('beathi.movie.session.1',JSON.stringify({name:'synthetic.wav',projectId:project,seed:17,template:'material-mix'}));},project);
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
const rhythm=await(await context.request.get(`${base}/api/projects/${project}`)).json(),duration=rhythm.source.duration;
const timeline={duration,assets:{fixture:{kind:'image',files:['image.png']}},frames:Array.from({length:Math.ceil(duration*30)},(_,i)=>({sinceCut:i/30%2,setup:{sourceId:'fixture',mode:'subject',subjectZoom:[1],phases:[0],attack:.1,settle:.2,phrase:[0,duration],palette:{base:'#202124',accent:'#393a3d',secondary:'#666'},group:'gray'},values:{}}))};
await context.route('**/api/materials/prepare**',route=>route.fulfill({json:{state:'ready',base:'/test-material/'}}));
await context.route('**/test-material/material-timeline.json',route=>route.fulfill({json:timeline}));
const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=16;c.getContext('2d').fillRect(0,0,16,16);return c.toDataURL().split(',')[1];});
await context.route('**/test-material/image.png',route=>route.fulfill({contentType:'image/png',body:Buffer.from(png,'base64')}));
const ready=async()=>{try{await page.waitForFunction(()=>document.querySelector('iframe.mv-preview')?.contentWindow?.previewReady===true,{},{timeout:30000});}catch(e){console.log(await page.evaluate(()=>document.querySelector('iframe.mv-preview')?.contentDocument?.querySelector('#fallback-reason')?.textContent));throw e;}};
const doc=async()=>{const r=await context.request.get(`${base}/api/projects/${project}/custom-media`);assert.ok(r.ok());return r.json();};
const plan=await(await context.request.get(`${base}/api/projects/${project}/edit-plan`)).json().catch(()=>({boundaries:[]}));
const beats=(rhythm.beats??[]).map(b=>b.time).filter(Number.isFinite).sort((a,b)=>a-b);
const gaps=beats.slice(1).map((b,i)=>b-beats[i]).sort((a,b)=>a-b),beatLen=gaps.length?gaps[Math.floor(gaps.length/2)]:.5;
const points=[...new Set([0,duration,...beats,...(plan.boundaries??[]).map(b=>b.time)].filter(t=>Number.isFinite(t)&&t>=0&&t<=duration))].sort((a,b)=>a-b);
const snap=t=>points.reduce((b,p)=>Math.abs(p-t)<Math.abs(b-t)?p:b,points[0]);
try{
 // clean fixture: empty the saved doc through the same ETag'd PUT the app uses
 const get=await context.request.get(`${base}/api/projects/${project}/custom-media`);
 if(get.ok()){const etag=get.headers()['etag'],saved=await get.json();
  if(saved.assets?.length||saved.slots?.length){const put=await context.request.put(`${base}/api/projects/${project}/custom-media`,{headers:{'If-Match':etag},data:{...saved,assets:[],slots:[]}});assert.ok(put.ok(),await put.text());}}
 let resumeRhythm;
 const waiting=new Promise(resolve=>{resumeRhythm=resolve;});
 await page.route(`**/api/projects/${project}`,async route=>{await waiting;await route.continue();});
 await page.goto(base+'/app/');
 const images=await page.evaluate(()=>[0,1,2,3].map(n=>{
  const c=document.createElement('canvas');c.width=400;c.height=300;const q=c.getContext('2d');q.fillStyle=['#203a6a','#713431','#777777','#2a5a40'][n];q.fillRect(0,0,400,300);q.fillStyle='#ded6c8';q.beginPath();q.arc(310,110,40,0,Math.PI*2);q.fill();q.fillStyle='#111';q.font='24px sans-serif';q.fillText('FOCUS '+n,30,270);return c.toDataURL('image/png').split(',')[1];
 }));
 await page.locator('.media-panel input[type=file]').setInputFiles({name:'image-0.png',mimeType:'image/png',buffer:Buffer.from(images[0],'base64')});
 await page.waitForSelector('.media-upload.waiting');resumeRhythm();await ready();
 await page.waitForFunction(()=>document.querySelectorAll('.media-thumb').length===1);
 console.log('Queued image survived project/rhythm readiness.');
 await page.locator('.media-panel input[type=file]').setInputFiles(images.slice(1,3).map((b,n)=>({name:`image-${n+1}.png`,mimeType:'image/png',buffer:Buffer.from(b,'base64')})));
 await page.waitForFunction(()=>document.querySelectorAll('.media-thumb').length===3);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 const pxps=await page.evaluate(()=>{const r=document.querySelector('.media-axis').getBoundingClientRect();return {w:r.width,left:r.left};});
 const slotBox=async(sel='.media-axis > button')=>{const b=await page.locator(sel).first().boundingBox();const title=await page.locator(sel).first().getAttribute('title');return {x:b.x+b.width/2,y:b.y+b.height/2,title};};
 const titleTime=t=>{const m=t.match(/(\d+):(\d+\.\d)/);return m?+m[1]*60+ +m[2]:null;};

 /* ---- 1: slot click seeks to its start ---- */
 const first=await slotBox();
 const start=await page.evaluate(()=>{const b=document.querySelector('.media-axis > button');const ax=document.querySelector('.media-axis').getBoundingClientRect();return (b.getBoundingClientRect().left-ax.left)/ax.width;});
 await page.mouse.click(first.x,first.y);await page.waitForTimeout(250);
 const shown=await page.locator('.tp-time').textContent(),shownT=titleTime(shown);
 const slotStart=start*duration;
 assert.ok(Math.abs(shownT-slotStart)<.2,`slot click seek: transport ${shownT} vs slot start ${slotStart}`);
 console.log('slot click seeked to',shownT,'≈',slotStart.toFixed(2));

 /* ---- 2: drag slot body one beat → snapped fixed slot ---- */
 const target=await slotBox();
 await page.mouse.move(target.x,target.y);await page.mouse.down();
 await page.mouse.move(target.x+pxps.w*beatLen/duration, target.y,{steps:12});
 await page.mouse.up();await page.waitForTimeout(400);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 let saved=await doc();
 const pinned=saved.slots.filter(s=>s.fixed);
 assert.ok(pinned.length===1,`expected 1 fixed slot after drag, got ${pinned.length}`);
 assert.ok(points.some(p=>Math.abs(p-pinned[0].start)<.01),`dragged slot start ${pinned[0].start} is not a snap point`);
 console.log('drag committed fixed slot',pinned[0].start,'–',pinned[0].end);

 /* ---- 3: resize right edge → end on a snap point ---- */
 const hbox=await page.locator('.media-axis > button.fixed .media-handle.r').boundingBox();
 const before=saved.slots.find(s=>s.fixed);
 await page.mouse.move(hbox.x+hbox.width/2,hbox.y+hbox.height/2);await page.mouse.down();
 await page.mouse.move(hbox.x+hbox.width/2+pxps.w*beatLen/duration,hbox.y+hbox.height/2,{steps:10});
 await page.mouse.up();await page.waitForTimeout(400);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 saved=await doc();
 const resized=saved.slots.find(s=>s.fixed);
 assert.ok(resized.end>before.end+.05,`resize did not extend ${before.end} → ${resized.end}`);
 assert.ok(points.some(p=>Math.abs(p-resized.end)<.01),`resized end ${resized.end} is not a snap point`);
 console.log('resize committed end',resized.end);

 /* ---- 4: Esc mid-drag → doc unchanged ---- */
 const escBox=await page.locator('.media-axis > button.fixed').boundingBox();
 await page.mouse.move(escBox.x+escBox.width/2,escBox.y+escBox.height/2);await page.mouse.down();
 await page.mouse.move(escBox.x+escBox.width/2+pxps.w*beatLen,escBox.y+escBox.height/2,{steps:8});
 await page.keyboard.press('Escape');await page.mouse.up();await page.waitForTimeout(300);
 const afterEsc=await doc();
 assert.deepEqual(afterEsc.slots,saved.slots,'Esc mid-drag must not commit');
 console.log('Esc cancelled the drag');

 /* ---- 5: Ctrl+Z after a drag restores the previous doc ---- */
 const redoBox=await page.locator('.media-axis > button.fixed').boundingBox();
 await page.mouse.move(redoBox.x+redoBox.width/2,redoBox.y+redoBox.height/2);await page.mouse.down();
 await page.mouse.move(redoBox.x+redoBox.width/2-pxps.w*beatLen,redoBox.y+redoBox.height/2,{steps:10});
 await page.mouse.up();await page.waitForTimeout(400);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 const dragged=await doc();assert.notDeepEqual(dragged.slots,saved.slots,'drag should have committed');
 await page.locator('.media-thumb').first().locator('button').first().focus();
 await page.keyboard.press('Control+z');await page.waitForTimeout(400);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 const undone=await doc();assert.deepEqual(undone.slots,saved.slots,'Ctrl+Z should restore the pre-drag doc');
 console.log('Ctrl+Z restored the doc');
 saved=undone;

 /* ---- 6: remove image → toast → its Undo restores ---- */
 const beforeRemove=await page.locator('.media-thumb').count();
 await page.locator('.media-delete').first().click();
 await page.locator('.media-toast').waitFor();assert.ok(/Removed|已删除/.test(await page.locator('.media-toast').textContent()));
 await page.locator('.media-toast button').click();await page.waitForTimeout(400);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 assert.equal(await page.locator('.media-thumb').count(),beforeRemove,'toast undo should restore the image');
 console.log('toast undo restored the image');

 /* ---- 7: slow upload shows progress tile before the thumbnail ---- */
 await context.route(`**/api/projects/${project}/assets`,async route=>{
  if(route.request().method()!=='POST')return route.fallback();
  await new Promise(r=>setTimeout(r,900));return route.fallback();
 });
 await page.locator('.media-panel input[type=file]').setInputFiles([{name:'slow.png',mimeType:'image/png',buffer:Buffer.from(images[3],'base64')}]);
 await page.locator('.media-upload').waitFor();assert.ok(await page.locator('.media-upload .media-up-ring').count(),'progress ring missing');
 console.log('upload tile with ring visible while POSTs are delayed');
 try {
  await page.waitForFunction(()=>document.querySelectorAll('.media-thumb').length===4,{},{timeout:20000});
 } catch(e) {
  console.log('UPLOAD STUCK:',JSON.stringify(await page.evaluate(()=>({uploads:[...document.querySelectorAll('.media-upload')].map(u=>u.className+'|'+u.title+'|'+u.textContent.trim()),thumbs:document.querySelectorAll('.media-thumb').length,busy:document.querySelector('.media-toolbar button')?.disabled,err:document.querySelector('.media-error')?.textContent}))));
  throw e;
 }
 assert.equal(await page.locator('.media-upload').count(),0,'upload tile should clear after commit');
 await context.unroute(`**/api/projects/${project}/assets`);
 console.log('upload finished, tile replaced by thumbnail');

 /* ---- 8: marker drag → preview pixels change before release; commit on release ---- */
 const clickedAsset=(await doc()).slots.find(()=>true)?.asset;
 await page.locator('.media-axis > button').first().click();await page.waitForTimeout(400); // seek into a slot + open inspector
 await page.locator('.media-inspect-image').waitFor();
 const shotFrame=()=>page.locator('iframe.mv-preview').screenshot();
 const still1=await shotFrame();await page.waitForTimeout(300);const still2=await shotFrame();
 assert.ok(still1.equals(still2),'paused preview must be stable before the drag');
 const ibox=await page.locator('.media-inspect-image').boundingBox();
 const cx=ibox.x+ibox.width/2,cy=ibox.y+ibox.height/2;
 await page.mouse.move(cx,cy);await page.mouse.down();
 await page.mouse.move(cx-ibox.width*.3,cy+ibox.height*.2,{steps:8});
 await page.waitForTimeout(500);
 const during=await shotFrame();assert.ok(!during.equals(still1),'preview must change while dragging the marker');
 const persistedMid=await doc();const selAsset=persistedMid.assets.find(a=>a.id===clickedAsset);
 assert.deepEqual(selAsset.focus,{x:.5,y:.5,zoom:1,fit:'cover'},'nothing persisted before release');
 await page.mouse.up();await page.waitForTimeout(500);
 await page.waitForFunction(()=>!document.querySelector('.media-toolbar button').disabled);
 const persisted=await doc();
 const committed=persisted.assets.find(a=>Math.abs(a.focus.x-.5)>.01||Math.abs(a.focus.y-.5)>.01);
 assert.ok(committed,'marker drag did not commit a focus on release');
 console.log('marker drag previewed live and committed',committed.focus.x.toFixed(2),committed.focus.y.toFixed(2));

 /* ---- 9: touch long-press drags a thumbnail onto the lane ---- */
 const mobile=await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true});
 await mobile.addInitScript(project=>{if(window===window.top)localStorage.setItem('beathi.movie.session.1',JSON.stringify({name:'synthetic.wav',projectId:project,seed:17,template:'material-mix'}));},project);
 const mpage=await mobile.newPage();
 await mobile.route('**/api/materials/prepare**',route=>route.fulfill({json:{state:'ready',base:'/test-material/'}}));
 await mobile.route('**/test-material/material-timeline.json',route=>route.fulfill({json:timeline}));
 await mobile.route('**/test-material/image.png',route=>route.fulfill({contentType:'image/png',body:Buffer.from(png,'base64')}));
 await mpage.goto(base+'/app/');
 await mpage.waitForFunction(()=>document.querySelector('iframe.mv-preview')?.contentWindow?.previewReady===true,{},{timeout:30000});
 await mpage.locator('.media-thumb').first().waitFor();
 const fixedBefore=(await doc()).slots.filter(s=>s.fixed).length;
 await mpage.evaluate(async()=>{
  const tile=document.querySelector('.media-thumb'),r=tile.getBoundingClientRect(),lane=document.querySelector('.media-placement').getBoundingClientRect();
  const sx=r.left+r.width/2,sy=r.top+r.height/2,tx=lane.left+lane.width*.62,ty=lane.top+lane.height/2;
  const ev=(type,x,y)=>tile.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,pointerId:9,pointerType:'touch',clientX:x,clientY:y,button:0,buttons:1}));
  ev('pointerdown',sx,sy);
  await new Promise(r=>setTimeout(r,430));
  for(let i=1;i<=10;i++){ev('pointermove',sx+(tx-sx)*i/10,sy+(ty-sy)*i/10);await new Promise(r=>setTimeout(r,25));}
  ev('pointerup',tx,ty);
 });
 await mpage.waitForTimeout(600);
 await mpage.waitForFunction(()=>!document.querySelector('.media-toolbar button')?.disabled,{},{timeout:15000});
 const afterTouch=await doc();
 assert.ok(afterTouch.slots.filter(s=>s.fixed).length>fixedBefore,'touch drag did not pin a slot');
 const placed=afterTouch.slots.filter(s=>s.fixed).at(-1);
 assert.ok(points.some(p=>Math.abs(p-placed.start)<.01),`touch-dropped slot start ${placed.start} is not a snap point`);
 console.log('touch long-press pinned a slot at',placed.start);
 await mobile.close();

 assert.deepEqual(errors,[]);
 console.log('All pointer interactions verified: click-seek, drag-snap, resize, Esc cancel, Ctrl+Z, toast undo, upload progress, live focus preview and touch long-press.');
}finally{await browser.close();}
