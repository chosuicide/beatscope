// End-to-end bounded export, reusing frozen facts, frames and authorized atlases.
import fs from 'node:fs';import path from 'node:path';import {spawn,spawnSync}from'node:child_process';import{createHash}from'node:crypto';import assert from'node:assert/strict';
const source=path.resolve('.beatscope-cache/movies/5adc351cd3474e8a48e41e76'),out=path.resolve('output/gpu-composite-sample'),start=12,duration=8;
fs.mkdirSync(out,{recursive:true});const full=JSON.parse(fs.readFileSync(source+'/material-timeline.json')),input=JSON.parse(fs.readFileSync(source+'/input.json')),plan=JSON.parse(fs.readFileSync(source+'/plan.json'));
const run=(cmd,args)=>{const r=spawnSync(cmd,args,{windowsHide:true,encoding:'utf8'});if(r.status!==0)throw Error(r.stderr||r.stdout);return r.stdout;};
const audio=out+'/excerpt.wav';run('ffmpeg',['-v','error','-ss',String(start),'-i',input.audio,'-t',String(duration),'-c:a','pcm_s16le','-y',audio]);
const frames=full.frames.slice(start*30,(start+duration)*30+1),assets=Object.fromEntries([...new Set(frames.map(f=>f.setup.sourceId))].map(id=>[id,full.assets[id]]));
input.audio=audio;input.rhythm.source.sha256=createHash('sha256').update(fs.readFileSync(audio)).digest('hex');input.rhythm.source.duration=duration;input.excerpt={start,duration,sourceFacts:'Frozen v4, no analysis or score changes'};
const env={...process.env,BEATSCOPE_PLAYWRIGHT_MODULE:path.resolve('tests/browser/node_modules/playwright/index.mjs')},reports=[];
for(const mode of ['legacy-hardware','gpu-hardware']){
 const dir=out+'/'+mode;fs.mkdirSync(dir+'/media',{recursive:true});
 for(const file of ['mv-render.html','mv-frame.mjs','mv-visual.js','mv-plan.mjs','mv-encode.mjs','movie-factory.mjs','movie-templates.mjs','material-frame.mjs','material-gpu.mjs'])fs.copyFileSync('beatscope/web/'+file,dir+'/'+file);
 for(const file of ['beatscope-runtime.js','edit-plan.js','package.json'])fs.copyFileSync(source+'/'+file,dir+'/'+file);
 for(const a of Object.values(assets))for(const file of a.files){if(!fs.existsSync(dir+'/'+file))fs.linkSync(source+'/'+file,dir+'/'+file);}
 fs.writeFileSync(dir+'/input.json',JSON.stringify(input));fs.writeFileSync(dir+'/plan.json',JSON.stringify({...plan,duration}));fs.writeFileSync(dir+'/material-timeline.json',JSON.stringify({duration,fps:30,frames,assets}));
 const t=performance.now(),samples=[],log=[];
 const p=spawn(process.execPath,['beatscope/web/mv-worker.mjs',dir],{env:{...env,BEATSCOPE_MV_HARDWARE:'prefer-hardware',BEATSCOPE_MV_GPU:'1',BEATSCOPE_MV_COMPOSITE:mode==='gpu-hardware'?'1':'0'},windowsHide:true});
 p.stdout.on('data',b=>log.push(String(b)));p.stderr.on('data',b=>log.push(String(b)));
 const timer=setInterval(()=>{const q=spawn('nvidia-smi',['--query-gpu=utilization.gpu,utilization.encoder','--format=csv,noheader,nounits'],{windowsHide:true});let s='';q.stdout.on('data',b=>s+=b);q.on('close',()=>{const [gpu,encoder]=s.trim().split(',').map(Number);if(Number.isFinite(gpu)&&Number.isFinite(encoder))samples.push({gpu,encoder});});},500);
 const code=await new Promise(r=>p.on('close',r));clearInterval(timer);fs.writeFileSync(dir+'/render.log',log.join(''));assert.equal(code,0,log.join(''));
 const info=JSON.parse(run('ffprobe',['-v','error','-show_streams','-show_format','-of','json',dir+'/movie.mp4']));const video=info.streams.find(s=>s.codec_type==='video');assert.equal(video.width,1080);assert.equal(video.height,1080);assert.equal(video.nb_frames,'240');assert.ok(Math.abs(Number(video.duration)-duration)<.04,'Video clock must span the excerpt');assert.equal(video.r_frame_rate,'30/1');assert.ok(info.streams.some(s=>s.codec_type==='audio'));
 reports.push({mode,wallSeconds:(performance.now()-t)/1000,acceleration:JSON.parse(fs.readFileSync(dir+'/acceleration.json')),samples,video:{width:video.width,height:video.height,frames:video.nb_frames,duration:info.format.duration}});
 console.log(reports.at(-1));
}
fs.writeFileSync(out+'/check.json',JSON.stringify(reports,null,2));assert.equal(reports[1].acceleration.effects.effects,'webgl2-composite');assert.equal(reports[1].acceleration.encodingPreference,'prefer-hardware');
