// Shared native browser contract: selectable templates, real cache and seek parity.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {chromium} from 'playwright';
const base=process.argv[2]??'http://127.0.0.1:8871',project='bb4987145c2d',seed=17;
const browser=await chromium.launch({channel:'msedge'}),context=await browser.newContext({viewport:{width:1440,height:1000}}),errors=[];
await context.addInitScript(()=>{if(window===window.top)localStorage.setItem('beathi.movie.session.1',JSON.stringify({name:'mafia',projectId:'bb4987145c2d',seed:17,template:'material-mix'}));});
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
fs.mkdirSync('output/playwright/material-template',{recursive:true});
try{
 await page.goto(base+'/app/');
 await page.locator('.template-select').waitFor();
 assert.equal(await page.locator('.template-select option').count(),2);
 assert.equal(await page.locator('.template-select').inputValue(),'material-mix');
 assert.equal(await page.locator('.material-library').count(),0);
 assert.equal((await(await context.request.get(base+'/api/materials/library')).json()).assets.length,51);
 const iframe=page.frameLocator('iframe.mv-preview');
 await iframe.locator('canvas').waitFor();
 await page.waitForFunction(()=>document.querySelector('iframe.mv-preview')?.contentWindow?.previewReady===true,{},{timeout:120000});
 assert.deepEqual(await iframe.locator('canvas').evaluate(c=>[c.width,c.height]),[540,540]);
 const cache=await(await context.request.get(`${base}/api/materials/prepare?project=${project}&seed=${seed}&template=material-mix`)).json();
 assert.equal(cache.state,'ready');
 const data=await(await context.request.get(base+cache.base+'material-timeline.json')).json();
 assert.equal(data.duration,218.6842);
 const testPage=await context.newPage();
 await testPage.goto(base+'/movie-preview.html?project='+project+'&seed=17&template=voxel');
 const result=await testPage.evaluate(async({data,base})=>{
  const {createMaterialMovie}=await import('/material-frame.mjs');
  const a=document.createElement('canvas'),b=document.createElement('canvas');a.width=a.height=b.width=b.height=1080;
  const render=await createMaterialMovie(a,data,base),other=await createMaterialMovie(b,data,base);
  const capture=document.createElement('canvas');capture.width=capture.height=1080;const q=capture.getContext('2d',{willReadFrequently:true});const pixels=c=>{q.clearRect(0,0,1080,1080);q.drawImage(c,0,0);return capture.toDataURL();};const checks=[];
  for(const time of [1.1,9.12,14.8,27.3,7.13,192.5,198,211.2]){
   await render(time);const initial=pixels(a);await render(0);await render(time);await other(time);
   const later=pixels(a);checks.push({time,backward:initial===later,shared:initial===pixels(b),...(initial===later?{}:{first:initial,next:later})});
  }
    render.dispose();other.dispose();
  const c=document.createElement('canvas'),d=document.createElement('canvas');c.width=c.height=d.width=d.height=1080;
  const original=HTMLCanvasElement.prototype.getContext;let fallback;
  try{HTMLCanvasElement.prototype.getContext=function(type,...args){return type.startsWith('webgl')?null:original.call(this,type,...args);};fallback=await createMaterialMovie(c,data,base);}
  finally{HTMLCanvasElement.prototype.getContext=original;}
  const cpu=await createMaterialMovie(d,data,base,{gpu:false});
  if(fallback.acceleration.effects!=='cpu')throw Error('Unsupported GPU did not select Canvas fallback');
  for(const time of [1.1,14.8,192.5]){await fallback(time);await cpu(time);if(pixels(c)!==pixels(d))throw Error('Canvas fallback changed the picture at '+time);}
  fallback.dispose();cpu.dispose();return checks;
 },{data,base:cache.base});
 for(const row of result){if(row.first){for(const key of ['first','next'])fs.writeFileSync('output/playwright/material-template/seek-'+row.time+'-'+key+'.png',Buffer.from(row[key].split(',')[1],'base64'));delete row.first;delete row.next;}}
 fs.writeFileSync('output/playwright/material-template/seek-check.json',JSON.stringify(result,null,2));
 assert.ok(result.every(r=>r.backward&&r.shared),JSON.stringify(result));
 for(const time of [3.1,192.5,198,211.2]){
  const png=await testPage.evaluate(async({data,base,time})=>{
   const {createMaterialMovie}=await import('/material-frame.mjs');const c=document.createElement('canvas');c.width=c.height=1080;
   const render=await createMaterialMovie(c,data,base);await render(time);const png=c.toDataURL();render.dispose();return png;
  },{data,base:cache.base,time});
  fs.writeFileSync(`output/playwright/material-template/v2-${time}.png`,Buffer.from(png.split(',')[1],'base64'));
 }
 await testPage.close();
 await page.locator('.template-select').selectOption('voxel');
 assert.match(await page.locator('iframe.mv-preview').getAttribute('src'),/template=voxel/);
 assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('beathi.movie.session.1')).template),'voxel');
 await page.waitForFunction(()=>document.querySelector('iframe.mv-preview')?.contentWindow?.previewReady===true,{},{timeout:120000});
 assert.deepEqual(await iframe.locator('canvas').evaluate(c=>[c.width,c.height]),[540,540]);
 await page.locator('.template-select').selectOption('material-mix');
 await page.screenshot({path:'output/playwright/material-template/studio.png'});
 assert.deepEqual(errors,[]);
 fs.writeFileSync('output/playwright/material-template/verified.json',JSON.stringify({templates:2,assets:51,fullDuration:data.duration,checks:result,errors},null,2));
 console.log('Studio: selection, persistence, full score coverage and shared deterministic seek passed.');
}finally{await browser.close();}



