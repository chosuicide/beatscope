// Real UI + HTTP roundtrip; no analysis, video encode or external service.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {chromium} from 'playwright';
import {createMusicGrid} from '../../beatscope/web/music-grid.mjs';
const base=process.argv[2], project='0a1b2c3d4e5f', out='build/edit-plan-check';
await mkdir(out,{recursive:true});
const browser=await chromium.launch({args:['--autoplay-policy=no-user-gesture-required']});
const context=await browser.newContext({viewport:{width:1440,height:1150}});
await context.addInitScript(()=>{
  localStorage.setItem('beathi.movie.session.1',JSON.stringify({name:'aba-fixture.wav',projectId:'0a1b2c3d4e5f',seed:7}));
  localStorage.setItem('beathi.cuemap.collapsed','false');
  const list=[];window.__editTools=list;
  document.modelContext={registerTool:async t=>list.push(t),getTools:async()=>list.map(t=>({name:t.name}))};
});
const page=await context.newPage(),errors=[];
page.on('pageerror',e=>errors.push(e.message));
const api=`${base}/api/projects/${project}`;
let original;
const read=async()=>{const r=await context.request.get(`${api}/edit-plan`);assert.equal(r.status(),200);return r.json();};
async function saved(check){await page.waitForFunction(()=>/Saved|已保存/.test(document.querySelector('.cm-save-dot')?.getAttribute('aria-label')??''));const p=await read();assert.ok(check(p),JSON.stringify(p));return p;}
async function tool(name,args){return page.evaluate(async({name,args})=>window.__editTools.find(t=>t.name===name).execute(args),{name,args});}
async function button(en,zh){return page.getByRole('button',{name:en,exact:true}).count()?page.getByRole('button',{name:en,exact:true}):page.getByRole('button',{name:zh,exact:true});}
try {
  await page.goto(`${base}/app/`,{waitUntil:'networkidle'});
  await page.locator('[data-testid="cue-map-editor"]').waitFor();
  assert.equal(await page.locator('.re-tracks,.re-stage,.re-cues').count(),0);
  assert.equal(await page.locator('.cm-stack').count(),2);
  assert.equal(await page.locator('.cm-stack canvas').count(),4);
  assert.equal(await page.locator('.cm-edit-time').count(),0);
  assert.equal(await page.locator('.cm-edit-tools').innerText(),'');
  const initialResponse=await context.request.get(`${api}/edit-plan`), initial=await initialResponse.json();
  const initialRhythm=await (await context.request.get(api)).json();
  const reset={...initial,cues:[],boundaries:[...new Set(initialRhythm.patterns.segments.map(s=>s.start_time).filter(t=>t>0&&t<initial.duration))].sort((a,b)=>a-b).map((time,i)=>({id:`s:${i}`,time}))};
  await context.request.put(`${api}/edit-plan`,{headers:{'If-Match':initialResponse.headers().etag},data:reset});
  await page.reload({waitUntil:'networkidle'});
  original=await saved(p=>p.cues.length===0);
  const originalRhythm=await (await context.request.get(api)).json();
  await (await button('Snap to nearest onset or beat','吸附到最近起音或拍点')).click();
  const first=page.locator('.cm-stack-overview [data-marker]').first();
  const id=await first.getAttribute('data-marker');
  const svg=await page.locator('.cm-stack-overview svg.cm-edit-layer').boundingBox();
  const scale=Math.min(svg.width/1560,svg.height/128),offset=(svg.width-1560*scale)/2;
  const target=original.boundaries[0].time+1.3;
  const box=await first.boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  await page.mouse.down();await page.mouse.move(svg.x+offset+(124+target/original.duration*(1560-124-18))*scale,box.y+box.height/2,{steps:5});await page.mouse.up();
  const dragged=await saved(p=>Math.abs(p.boundaries.find(b=>b.id===id).time-target)<.02);
  await (await button('Undo','撤销')).click();await saved(p=>p.boundaries[0].time===original.boundaries[0].time);
  await (await button('Redo','重做')).click();await saved(p=>p.boundaries[0].time===dragged.boundaries[0].time);
  const seek=await tool('beatscope_control_playback',{action:'seek',time:5.123});assert.equal(seek.ok,true);
  await page.waitForFunction(()=>Math.abs(document.querySelector('audio').currentTime-5.123)<.01);
  await (await button('Edit cues','编辑卡点')).click();
  await (await button('Add cue at playhead','在播放位置添加卡点')).click();
  const added=await saved(p=>p.cues.some(c=>c.id.startsWith('u:')&&Math.abs(c.time-5.123)<.02));
  await page.waitForFunction(()=>document.querySelectorAll('.cm-hit.manual[data-kind="cue"]').length>0);
  const explained=await tool('beatscope_explain_movie',{time:5.1231,context:0});assert.equal(explained.ok,true);assert.equal(explained.data.shot.entry.kind,'cue');
  const cue=page.locator('.cm-stack-map .cm-hit.manual[data-kind="cue"]');
  const map=await page.locator('.cm-stack-map svg.cm-edit-layer').boundingBox(),cueBox=await cue.boundingBox();
  const mapScale=Math.min(map.width/1400,map.height/232),mapOffset=(map.width-1400*mapScale)/2;
  const grid=createMusicGrid(originalRhythm),cueTarget=6.321;
  const cueX=124+grid.stepAtTime(cueTarget)*(1400-124-18)/(8*grid.subdivision);
  await page.mouse.move(cueBox.x+cueBox.width/2,cueBox.y+cueBox.height/2);
  await page.mouse.down();await page.mouse.move(map.x+mapOffset+cueX*mapScale,cueBox.y+cueBox.height/2,{steps:5});await page.mouse.up();
  await saved(p=>Math.abs(p.cues.find(c=>c.id===added.cues[0].id).time-cueTarget)<.005);
  const input=page.getByRole('spinbutton',{name:'Selected marker time (seconds)'});
  await input.fill('7.333');await input.press('Enter');await saved(p=>p.cues.find(c=>c.id===added.cues[0].id).time===7.333);
  const countBefore=await page.locator('.cm-stack-map [data-kind="cue"]').count();
  await (await button('Zoom rhythm map in','放大节奏图')).click();
  assert.ok(await page.locator('.cm-stack-map [data-kind="cue"]').count()<countBefore);
  await tool('beatscope_control_playback',{action:'seek',time:10.1});
  await page.waitForFunction(()=>/05.+08/.test(document.querySelector('.cm-tools > span').textContent));
  await tool('beatscope_control_playback',{action:'seek',time:5.123});
  await (await button('Zoom rhythm map out','缩小节奏图')).click();
  await page.waitForFunction(()=>/01.+08/.test(document.querySelector('.cm-tools > span').textContent));
  assert.equal(await page.locator('.cm-stack-map [data-kind="cue"]').count(),countBefore);
  await (await button('Edit stage boundaries','编辑阶段边界')).click();
  await (await button('Add stage at playhead','在播放位置添加阶段')).click();
  const stageAdded=await saved(p=>p.boundaries.some(b=>Math.abs(b.time-5.123)<.01));
  assert.match(await page.getByTestId('stage-count').innerText(),new RegExp(String(original.boundaries.length+2)));
  assert.match(await page.getByTestId('selected-stage').innerText(),/Stage 02.*00:05.12/s);
  await page.locator('section.cm').screenshot({path:`${out}/stage-selected.png`});
  await page.setViewportSize({width:319,height:618});
  await page.getByRole('button',{name:'中文',exact:true}).click();
  const stageId=stageAdded.boundaries.find(b=>Math.abs(b.time-5.123)<.01).id;
  await page.waitForFunction(id=>{
    const marker=document.querySelector(`.cm-stack-map [data-marker="${id}"]`).getBoundingClientRect();
    const graph=document.querySelector('.cm-stack-map').getBoundingClientRect();
    return marker.x>=graph.x&&marker.right<=graph.right&&graph.right<=window.innerWidth;
  },stageId);
  const stageHit=page.locator(`.cm-stack-map [data-marker="${stageId}"] rect`);
  const cueHit=page.locator('.cm-stack-map [data-kind="cue"] rect').first();
  assert.ok(Number(await stageHit.getAttribute('y'))>=Number(await cueHit.getAttribute('y'))+Number(await cueHit.getAttribute('height')));
  assert.equal(await page.locator('.cm-plot-scroll').count(),0);
  assert.ok(await page.locator('section.cm').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  assert.match(await page.getByTestId('selected-stage').innerText(),/阶段 02/);
  await page.locator('section.cm').screenshot({path:`${out}/stage-selected-mobile.png`});
  await page.setViewportSize({width:1440,height:1150});
  await page.getByRole('button',{name:'EN',exact:true}).click();
  await (await button('Delete selected marker','删除选中标记')).click();await saved(p=>p.boundaries.length===original.boundaries.length);
  await cue.focus();
  await (await button('Delete selected marker','删除选中标记')).click();await saved(p=>p.cues.length===0);
  await (await button('Undo','撤销')).click();await saved(p=>p.cues.some(c=>c.id===added.cues[0].id));
  const onset=page.locator('.cm-stack-map [data-marker="o:3"]');
  await onset.focus();await onset.press('Delete');
  const final=await saved(p=>p.cues.some(c=>c.id==='o:3'&&c.deleted));
  assert.equal(await page.locator('.cm-stack-map [data-marker="o:3"]').count(),0);
  const currentRhythm=await (await context.request.get(api)).json();assert.deepEqual(currentRhythm,originalRhythm);
  const zip=await context.request.get(`${api}/export/codex.zip`);assert.equal(zip.status(),200);await writeFile(`${out}/studio-edited.zip`,await zip.body());
  await page.reload({waitUntil:'networkidle'});await saved(p=>JSON.stringify(p)===JSON.stringify(final));
  assert.equal(await page.locator('.cm-stack-map [data-marker="o:3"]').count(),0);
  // Preview must load edited stages/cues without an iframe error.
  const frame=page.frames().find(f=>f.url().includes('movie-preview.html'));
  assert.ok(frame);assert.equal(await frame.locator('#fallback').evaluate(e=>e.classList.contains('on')),false);
  await page.getByRole('button',{name:'中文',exact:true}).click();
  await page.locator('.cm-hit.manual[data-kind="cue"]').focus();
  await page.locator('section.cm').screenshot({path:`${out}/editor.png`});
  const result={in_original_graph:true,stages_on_ruler:true,mobile_graph_fits:true,icon_toolbar:true,stage_drag:true,stage_add_delete:true,cue_drag:true,precise_time:true,zoom_original_graph:true,undo_redo:true,manual_cue:true,muted_onset:true,reload:true,preview:true,facts_unchanged:true,errors,plan:final};
  assert.deepEqual(errors,[]);await writeFile(`${out}/browser-report.json`,JSON.stringify(result,null,2));
  console.log('Studio editor: drag, add, delete, undo/redo, reload, preview, export and immutable facts passed');
} catch(error) {
  console.error({status:await page.locator('.cm-save-dot').getAttribute('aria-label'),errors});
  await page.screenshot({path:`${out}/editor-failure.png`});
  throw error;
} finally {
  if(original){const r=await context.request.get(`${api}/edit-plan`);await context.request.put(`${api}/edit-plan`,{headers:{'If-Match':r.headers().etag},data:original});}
  await browser.close();
}
