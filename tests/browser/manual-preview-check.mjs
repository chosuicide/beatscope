// UI edits use an isolated HTTP plan double; no changes to the user's project.
import fs from 'node:fs';import assert from 'node:assert/strict';import{createHash}from'node:crypto';import{chromium}from'playwright';
const base='http://127.0.0.1:8871',project='bb4987145c2d',endpoint=`${base}/api/projects/${project}/edit-plan`,out='output/playwright/manual-preview';fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',args:['--enable-gpu']}),context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.addInitScript(()=>{if(window===window.top&&!localStorage.getItem('manual-preview-test-initialized')){localStorage.setItem('beathi.movie.session.1',JSON.stringify({name:'mafia',projectId:'bb4987145c2d',seed:17,template:'material-mix'}));localStorage.setItem('manual-preview-test-initialized','true');}window.__planMessages=[];window.addEventListener('message',e=>{if(e.origin===location.origin&&e.data?.type==='edit-plan')window.__planMessages.push(e.data.value);});});
const initialResponse=await context.request.get(endpoint),initial=await initialResponse.json(),initialDigest=initialResponse.headers().etag.replaceAll('"','');let plan=structuredClone(initial),writes=0,prepares=0;
const tag=()=>JSON.stringify(plan)===JSON.stringify(initial)?initialDigest:createHash('sha256').update(JSON.stringify(plan)).digest('hex');
await context.route(endpoint,async route=>{if(route.request().method()==='PUT'){plan=route.request().postDataJSON();writes++;}await route.fulfill({json:plan,headers:{ETag:`"${tag()}"`}});});
const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/api/materials/prepare?'))prepares++;});
try{
 await page.goto(base+'/app/');await page.getByRole('button',{name:'中文',exact:true}).click();await page.waitForFunction(()=>document.querySelector('iframe.mv-preview')?.contentWindow?.previewReady===true,{},{timeout:120000});
 const frame=page.frames().find(f=>f.url().includes('movie-preview.html'));assert.ok(frame);
 assert.equal(await page.locator('.material-library').count(),0);
 assert.match(await page.locator('.mv-body > .mv-rail').first().innerText(),/自动分段 · 9/);
 assert.match(await page.getByTestId('stage-count').innerText(),/编辑阶段 22/);
 assert.equal(await page.locator('.export-tools').getAttribute('open'),null);
 assert.equal(await page.getByRole('link',{name:'数据包 · codex.zip',exact:true}).isVisible(),false);
 const caps=await page.locator('.mv-body > .mv-rail').last().locator(':scope > .card > .rail-cap').allTextContents();assert.deepEqual(caps,['模板','视频','更多导出']);
 assert.ok(await page.locator('.seg-meta').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize)>=12));
 await page.locator('.export-tools > summary').click();assert.equal(await page.getByRole('link',{name:'数据包 · codex.zip',exact:true}).getAttribute('href'),`/api/projects/${project}/export/codex.zip`);await page.locator('.export-tools > summary').click();
 await page.screenshot({path:out+'/studio-before.png'});
 const readCount=()=>frame.evaluate(()=>window.__planMessages.length),before=await readCount(),beforePrepares=prepares;
 await page.getByRole('button',{name:'编辑卡点',exact:true}).click();
 await page.getByRole('button',{name:'在播放位置添加卡点',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.cm-save-dot')?.getAttribute('aria-label')==='已保存');
 await page.getByRole('button',{name:'在播放位置添加卡点',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.cm-save-dot')?.getAttribute('aria-label')==='已保存');
 assert.equal(writes,2);assert.equal(plan.cues.length,initial.cues.length+2);assert.equal(await readCount(),before);assert.equal(prepares,beforePrepares);assert.match(await page.getByTestId('preview-edit-state').innerText(),/预览待更新/);assert.equal(await frame.evaluate(()=>window.previewReady),true);
 await page.screenshot({path:out+'/studio-pending.png'});
 await page.getByRole('button',{name:'更新预览',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[data-testid="preview-edit-state"]')?.textContent?.includes('预览已同步'),{},{timeout:120000});
 assert.equal(await readCount(),before+1);assert.deepEqual(await frame.evaluate(()=>window.__planMessages.at(-1)),plan);
 await page.getByRole('button',{name:'撤销',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.cm-save-dot')?.getAttribute('aria-label')==='已保存');assert.match(await page.getByTestId('preview-edit-state').innerText(),/预览待更新/);assert.equal(await readCount(),before+1);
 const preparesBeforeLanguage=prepares;
 await page.getByRole('button',{name:'EN',exact:true}).click();assert.match(await page.getByTestId('preview-edit-state').innerText(),/preview needs updating/);assert.equal(await readCount(),before+1);assert.equal(prepares,preparesBeforeLanguage);
 await page.setViewportSize({width:1100,height:800});await page.screenshot({path:out+'/studio-1100.png'});assert.ok(await page.locator('.mv-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
 // Editing a completed film must not replace it with a newly built iframe.
 plan=structuredClone(initial);
 await page.evaluate(digest=>localStorage.setItem('beathi.movie.session.1',JSON.stringify({name:'mafia',projectId:'bb4987145c2d',seed:17,template:'material-mix',videoUrl:'/api/movies/5adc351cd3474e8a48e41e76/video',videoPlanDigest:digest,videoTemplate:'material-mix',videoTemplateVersion:'prismatic-echo-4'})),initialDigest);
 await page.reload();await page.locator('.mv-frame video').waitFor();await page.getByRole('button',{name:'Edit cues',exact:true}).click();await page.getByRole('button',{name:'Add cue at playhead',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.cm-save-dot')?.getAttribute('aria-label')==='Saved');assert.equal(await page.locator('.mv-frame video').count(),1);assert.equal(await page.locator('iframe.mv-preview').count(),0);assert.match(await page.getByTestId('preview-edit-state').innerText(),/preview needs updating/);
 assert.deepEqual(errors,[]);fs.writeFileSync(out+'/check.json',JSON.stringify({writes,insertionsWithoutPreviewMessages:true,insertionsWithoutPreparation:true,manualBatchUpdate:true,undoPending:true,localized:true,completedFilmPreserved:true,errors},null,2));console.log('Manual preview batching, saved edits, undo state, completed film and localization passed.');
}finally{await browser.close();}
