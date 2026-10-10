#!/usr/bin/env node
// One frame in flight, one encoder; browser reuse with periodic recycling.
import {createServer} from 'node:http';
import {createReadStream,existsSync} from 'node:fs';
import {mkdir,open,readdir,realpath,stat,lstat,unlink,writeFile,rename,rmdir} from 'node:fs/promises';
import {dirname,basename,extname,join,relative,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
import {options,number,hashFile,digest,jsonFile,saveJson,processTool,run,probe} from './tool-utils.mjs';
import {inside,exclusions,excluded,sourceHashes,frameSources,diskSpace,audioIdentity} from './render-inputs.mjs';

const MIME={'.html':'text/html','.js':'text/javascript','.mjs':'text/javascript','.json':'application/json','.css':'text/css','.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp','.mp4':'video/mp4','.webm':'video/webm','.woff2':'font/woff2'};
const toolRoot=dirname(fileURLToPath(import.meta.url));
async function serve(root,excludedPaths,onExcluded){
 const server=createServer(async(req,res)=>{
  try{
   const pathname=decodeURIComponent(new URL(req.url,'http://local').pathname);
   const target=await realpath(resolve(root,'.'+pathname));
   if(!inside(root,target)){res.writeHead(403).end();return;}
   if(excluded(target,excludedPaths)){onExcluded(relative(root,target));res.writeHead(403).end();return;}
   const info=await stat(target);if(!info.isFile()){res.writeHead(404).end();return;}
   const headers={'Content-Type':MIME[extname(target)]||'application/octet-stream','Cache-Control':'no-store','Accept-Ranges':'bytes'};
   let start=0,end=info.size-1,status=200;
   if(req.headers.range){const match=/^bytes=(\d+)-(\d*)$/.exec(req.headers.range);if(!match){res.writeHead(416).end();return;}
    start=Number(match[1]);end=match[2]?Math.min(end,Number(match[2])):end;
    if(start>end||start>=info.size){res.writeHead(416,{'Content-Range':`bytes */${info.size}`}).end();return;}
    status=206;headers['Content-Range']=`bytes ${start}-${end}/${info.size}`;
   }
   res.writeHead(status,{...headers,'Content-Length':Math.max(0,end-start+1)});
   if(req.method==='HEAD'||!info.size){res.end();return;}
   const stream=createReadStream(target,{start,end});stream.on('error',()=>res.destroy());res.on('close',()=>stream.destroy());stream.pipe(res);
  }catch{if(!res.headersSent)res.writeHead(404);res.end();}
 });
 await new Promise(done=>server.listen(0,'127.0.0.1',done));
 return {server,base:`http://127.0.0.1:${server.address().port}`};
}
async function loadPlaywright(modulePath){
 if(modulePath)return import(pathToFileURL(resolve(modulePath)).href);
 for(const base of [join(process.cwd(),'package.json'),join(toolRoot,'package.json')]){
  try{return await import(pathToFileURL(createRequire(base).resolve('playwright')).href);}catch{/* try the next explicit location */}
 }
 throw Error('Playwright unavailable. Use --playwright /path/to/playwright/index.mjs; no installation was attempted.');
}
async function demoAudio(path,seconds,example){
 const score=await jsonFile(join(toolRoot,'examples/directing',example+'.json'));
 const rate=44100,count=Math.ceil(seconds*rate),buffer=Buffer.alloc(44+count*2);
 buffer.write('RIFF');buffer.writeUInt32LE(36+count*2,4);buffer.write('WAVEfmt ',8);buffer.writeUInt32LE(16,16);buffer.writeUInt16LE(1,20);buffer.writeUInt16LE(1,22);buffer.writeUInt32LE(rate,24);buffer.writeUInt32LE(rate*2,28);buffer.writeUInt16LE(2,32);buffer.writeUInt16LE(16,34);buffer.write('data',36);buffer.writeUInt32LE(count*2,40);
 for(let i=0;i<count;i++){const t=i/rate;let v=0;
  for(const event of score.demo.audioEvents){const d=t-event.time;if(d>=0&&d<.11)v+=Math.sin(2*Math.PI*event.frequency*d)*Math.exp(-d*55)*(event.gain??.3);}
  buffer.writeInt16LE(Math.round(Math.max(-.9,Math.min(.9,v))*32767),44+i*2);
 }await writeFile(path,buffer);
}
export async function renderMain(argv){
 const a=options(argv,['resume','clean','demo-audio','help'],['entry','root','audio','reference-audio','out','start','seconds','fps','width','height','chunk-frames','memory-mb','playwright','browser','executable','browser-restart-every','example','exclude','frames-dir','frame-pattern','frame-start'],['exclude']);
 if(a.help){console.log('node render.mjs --entry ../scene.html --root .. --audio ../song.mp3 --out ../sample.mp4 [--executable /path/to/chromium --browser-restart-every 10 --exclude generated --clean --resume]\nFrames: --frames-dir ../frames --frame-pattern frame-%06d.png --frame-start 0\nTranscoded song: --audio ../song.mp3 --reference-audio ../original.wav\nTutorial: --example accent --demo-audio --out ../accent.mp4');return;}
 if(a.example&&!['accent','transition','transition-late','buildup','dense','pause','return'].includes(a.example))throw Error('Unknown tutorial example');
 const framesMode=Boolean(a['frames-dir']);
 if(a['demo-audio']&&!a.example)throw Error('Synthetic sound is only available for named tutorials');
 if(framesMode&&(a.entry||a.example||a.playwright||a.browser||a.executable||a['browser-restart-every']))throw Error('--frames-dir is separate from browser/entry/example options');
 if(framesMode&&(a.root||a.exclude))throw Error('--root/--exclude apply to browser sources; frames-dir hashes only the selected PNGs');
 if(!framesMode&&(a['frame-pattern']||a['frame-start']))throw Error('--frame-pattern/--frame-start require --frames-dir');
 if(a.executable&&a.browser)throw Error('Choose --executable or --browser, not both');
 if(!a.out||(!a.entry&&!a.example&&!framesMode)||(!a.audio&&!a['demo-audio']))throw Error('entry/frames-dir, audio and out are required; use --help');
 const framesDir=framesMode?await realpath(resolve(a['frames-dir'])):null;
 const root=framesMode?framesDir:await realpath(resolve(a.root??(a.example?toolRoot:process.cwd())));
 const entry=framesMode?null:await realpath(resolve(a.entry??join(toolRoot,'examples/directing/player.html')));
 if(entry&&!inside(root,entry))throw Error('Entry must be inside --root');
 const excludePaths=exclusions(root,a.exclude);
 if(entry&&excluded(entry,excludePaths))throw Error('Entry is excluded from the source snapshot');
 const start=number(a.start,0,0,86400,'start'),seconds=number(a.seconds,a.example?2:3,1/120,86400,'seconds'),fps=number(a.fps,30,1,120,'fps');
 const width=number(a.width,640,64,4096,'width'),height=number(a.height,640,64,4096,'height'),memory=number(a['memory-mb'],512,128,8192,'memory-mb'),chunkFrames=number(a['chunk-frames'],60,1,300,'chunk-frames');
 const restartEvery=number(a['browser-restart-every'],10,1,1000,'browser-restart-every'),frameStart=number(a['frame-start'],0,0,100000000,'frame-start');
 if(![width,height,memory,chunkFrames,restartEvery,frameStart].every(Number.isInteger)||width%2||height%2)throw Error('Dimensions must be even integers; budgets, frame start and restart interval must be integers');
 if(width*height*16>memory*1024*1024*.4)throw Error('Frame buffers exceed the selected working budget; lower dimensions or raise --memory-mb');
 const frameCount=Math.ceil(seconds*fps),duration=frameCount/fps,ffmpeg=process.env.BEATSCOPE_FFMPEG||'ffmpeg';
 const map=await jsonFile(join(toolRoot,'rhythm-map.json'));
 if(a.example&&start+duration>2+1e-6)throw Error('Requested interval exceeds two-second tutorial duration');
 if(!a.example&&start+duration>map.duration+1e-6)throw Error('Requested interval exceeds timing package duration');
 const executable=a.executable?await realpath(resolve(a.executable)):null;
 if(executable&&!(await stat(executable)).isFile())throw Error('--executable must identify a browser executable file');
 const playwright=framesMode?null:await loadPlaywright(a.playwright);
 await run(ffmpeg,['-version']);await run(process.env.BEATSCOPE_FFPROBE||'ffprobe',['-version']);
 await mkdir(dirname(resolve(a.out)),{recursive:true});
 const out=join(await realpath(dirname(resolve(a.out))),basename(resolve(a.out)));
 const work=join(dirname(out),'.render-'+digest(out).slice(0,12));await mkdir(work,{recursive:true});
 if((await lstat(work)).isSymbolicLink())throw Error('Render checkpoint directory cannot be a symlink');
 const lockPath=join(work,'lock.json');let lock;
 try{lock=await open(lockPath,'wx');}catch(error){
  if(error.code!=='EEXIST')throw error;
  const prior=await jsonFile(lockPath);let alive=true;try{process.kill(prior.pid,0);}catch(e){if(e.code==='ESRCH')alive=false;}
  if(alive)throw Error('A renderer owns this output lock');await unlink(lockPath);lock=await open(lockPath,'wx');
 }
 await lock.writeFile(JSON.stringify({pid:process.pid}));await lock.close();
 let server,browser,page,encoder,aborted=false,browserStarts=0,sessionParts=0;
 const abort=()=>{aborted=true;encoder?.kill();void browser?.close().catch(()=>{});};
 process.once('SIGINT',abort);process.once('SIGTERM',abort);
 const joined=join(work,'joined.mp4'),muxed=join(work,'final.mp4');
 async function recycle(){if(page)await page.evaluate(()=>window.beatscopeRender?.dispose?.()).catch(()=>{});await browser?.close();browser=null;page=null;sessionParts=0;}
 try{
  // An obsolete joined file is never needed by checkpoint reuse.
  await unlink(joined).catch(error=>{if(error.code!=='ENOENT')throw error;});
  const audio=a['demo-audio']?join(work,'tutorial.wav'):await realpath(resolve(a.audio));
  if(a['demo-audio'])await demoAudio(audio,duration,a.example);
  const audioHash=await hashFile(audio),reference=a['reference-audio']?await realpath(resolve(a['reference-audio'])):null;
  const identity=a.example?{audioIdentity:'synthetic-tutorial',sourceAudioSha256:null}:await audioIdentity(audio,audioHash,map.source?.sha256,reference);
  const selectedFrames=framesMode?await frameSources(framesDir,a['frame-pattern']??'frame-%06d.png',frameStart,frameCount,width,height):null;
  const snapshot=framesMode?{rows:[],bytes:0}:await sourceHashes(root,new Set([out,out+'.render.json',out+'.sync.json',work,audio,...(reference?[reference]:[])]),excludePaths);
  const sources=snapshot.rows;
  const settings={entry:entry?relative(root,entry).replaceAll('\\','/'):null,example:a.example??null,start,duration,fps,width,height,chunkFrames,memory,
   inputMode:framesMode?'frames':'browser',framesDir,framePattern:framesMode?a['frame-pattern']??'frame-%06d.png':null,frameStart,
   browser:framesMode?null:a.browser??null,executable,browserRestartEvery:framesMode?null:restartEvery,
   exclude:excludePaths.map(p=>relative(root,p).replaceAll('\\','/'))};
  const key=digest({settings,sources,frames:selectedFrames?.files,audio:audioHash,identity,driver:await hashFile(fileURLToPath(import.meta.url)),utils:await hashFile(join(toolRoot,'tool-utils.mjs')),inputs:await hashFile(join(toolRoot,'render-inputs.mjs'))});
  const statePath=join(work,'state.json');let state={schema:'beatscope-render-checkpoint-1',key,settings,parts:[]};
  if(existsSync(statePath)){
   const saved=await jsonFile(statePath);
   if(a.resume&&saved.key!==key)throw Error('Resume inputs changed; rerun without --resume to render the changed sources');
   if(a.resume&&saved.key===key)state=saved;
  }
  const totalParts=Math.ceil(frameCount/chunkFrames),reusable=new Set();let retainedBytes=0,reused=0;
  for(let part=0;part<totalParts;part++){
   const name=`part-${String(part).padStart(6,'0')}.mp4`,file=join(work,name),record=state.parts.find(p=>p.part===part);
   const count=Math.min(chunkFrames,frameCount-part*chunkFrames);
   if(a.resume&&record&&existsSync(file)&&await hashFile(file)===record.sha256){
    const info=await probe(file),video=info.streams.find(s=>s.codec_type==='video');
    if(video?.width===width&&video.height===height&&Number(video.nb_read_frames)===count){reusable.add(part);retainedBytes+=(await stat(file)).size;}
   }
  }
  const space=await diskSpace(dirname(out),{width,height,frameCount,retainedBytes});
  await saveJson(statePath,state);
  const failures=[];
  let url;
  if(!framesMode){const serving=await serve(root,excludePaths,p=>failures.push(`Renderer requested excluded dependency: ${p}; remove its --exclude`));server=serving.server;url=serving.base+'/'+settings.entry.split('/').map(encodeURIComponent).join('/')+(a.example?'?example='+encodeURIComponent(a.example):'');}
  for(let part=0;part<totalParts;part++){
   if(aborted)throw Error('Render interrupted; complete segments can be resumed');
   const first=part*chunkFrames,count=Math.min(chunkFrames,frameCount-first),name=`part-${String(part).padStart(6,'0')}.mp4`,file=join(work,name);
   if(reusable.has(part)){reused++;process.stderr.write(`Reusing segment ${part+1}/${totalParts}\n`);continue;}
   let target;
   if(!framesMode){
    if(browser&&sessionParts>=restartEvery)await recycle();
    if(!browser){
     browser=await playwright.chromium.launch({...(executable?{executablePath:executable}:a.browser?{channel:a.browser}:{}),args:[`--js-flags=--max-old-space-size=${Math.max(64,Math.floor(memory*.5))}`]});browserStarts++;
     page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});page.on('pageerror',e=>failures.push(e.message));
     await page.goto(url);
     await page.waitForFunction(()=>window.beatscopeRender&&typeof window.beatscopeRender.renderAt==='function').catch(error=>{throw Error(failures[0]??error.message);});
     await page.evaluate(async({width,height})=>{await document.fonts.ready;await window.beatscopeRender.ready;await window.beatscopeRender.resize?.(width,height);},{width,height}).catch(error=>{throw Error(failures[0]??error.message);});
    }
    const contract=await page.evaluate(()=>({duration:window.beatscopeRender.duration,selector:window.beatscopeRender.selector??'canvas'}));
    if(!Number.isFinite(contract.duration)||contract.duration<=0)throw Error('Renderer must declare a finite positive duration');
    if(start+duration>contract.duration+1e-6)throw Error('Requested interval exceeds renderer duration');
    target=page.locator(contract.selector);if(await target.count()!==1)throw Error('Renderer selector must identify exactly one canvas/element');
    const size=await target.boundingBox();
    if(!size||Math.abs(size.width-width)>.01||Math.abs(size.height-height)>.01)throw Error(`Renderer element is ${size?size.width+'×'+size.height:'not visible'}; requested ${width}×${height}. Implement resize() or choose the element size.`);
   }
   const input=framesMode?['-framerate',String(fps),'-start_number',String(frameStart+first),'-i',join(framesDir,settings.framePattern)]:['-f','image2pipe','-framerate',String(fps),'-vcodec','png','-i','pipe:0'];
   const job=processTool(ffmpeg,['-hide_banner','-loglevel','error','-y','-threads','1','-filter_threads','1',...input,'-an','-c:v','libx264','-threads','1','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-frames:v',String(count),file],{input:!framesMode,timeout:600000});encoder=job.child;
   if(!framesMode){
    for(let n=0;n<count;n++){
     if(aborted)throw Error('Render interrupted');
     await page.evaluate(t=>window.beatscopeRender.renderAt(t),start+(first+n)/fps);
     if(failures.length)throw Error(failures[0]);
     const buffer=await target.screenshot({type:'png',animations:'allow',timeout:30000});
     const w=buffer.readUInt32BE(16),h=buffer.readUInt32BE(20);
     if(w!==width||h!==height)throw Error(`Frame ${first+n} element is ${w}×${h}; requested ${width}×${height}`);
     await new Promise((done,fail)=>encoder.stdin.write(buffer,error=>error?fail(error):done()));
    }
    encoder.stdin.end();sessionParts++;
   }
   await job.done;encoder=null;
   const info=await probe(file),video=info.streams.find(s=>s.codec_type==='video');
   if(video?.width!==width||video.height!==height||Number(video.nb_read_frames)!==count)throw Error(`Encoded segment ${part+1} has ${video?.width}×${video?.height}, ${video?.nb_read_frames} frames; requested ${width}×${height}, ${count} frames`);
   state.parts=state.parts.filter(p=>p.part!==part);state.parts.push({part,name,first,count,sha256:await hashFile(file)});await saveJson(statePath,state);
   process.stderr.write(`Rendered segment ${part+1}/${totalParts}\n`);
  }
  await recycle();
  const list=join(work,'concat.txt');await writeFile(list,Array.from({length:totalParts},(_,i)=>`file 'part-${String(i).padStart(6,'0')}.mp4'`).join('\n')+'\n');
  if(aborted)throw Error('Render interrupted');
  // Mux from the segment list directly: no second, full-size joined video.
  const job=processTool(ffmpeg,['-hide_banner','-loglevel','error','-y','-f','concat','-safe','1','-i',list,'-ss',String(a['demo-audio']?0:start),'-i',audio,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','128k','-t',String(duration),'-af',`apad=whole_dur=${duration}`,'-movflags','+faststart',muxed],{timeout:600000});encoder=job.child;await job.done;encoder=null;
  if(aborted)throw Error('Render interrupted');
  const info=await probe(muxed),video=info.streams.find(s=>s.codec_type==='video');
  if(Number(video?.nb_read_frames)!==frameCount||!info.streams.some(s=>s.codec_type==='audio'))throw Error('Final video/audio verification failed');
  await rename(muxed,out);
  if(a.clean){for(const name of await readdir(work))if(/^part-\d{6}\.mp4$/.test(name)||['state.json','state.json.tmp','concat.txt','tutorial.wav'].includes(name))await unlink(join(work,name));}
  const report={schema:'beatscope-render-report-1',output:out,sha256:await hashFile(out),key,settings,frameCount,reusedSegments:reused,segments:totalParts,browserStarts,
   memoryPolicy:'soft working budget: one PNG in flight, one encoder thread, V8 heap cap, browser recycled periodically; not an OS/GPU memory limit',
   cachePolicy:a.clean?'removed-after-success':'segments-retained-for-resume',diskSpace:space,sourceBytes:snapshot.bytes,frameSourceBytes:selectedFrames?.bytes??0,
   ...identity,sources,frames:selectedFrames?.files??null,audio_sha256:audioHash};
  await saveJson(out+'.render.json',report);console.log(JSON.stringify({...report,sources:undefined,frames:undefined},null,2));
 }catch(error){
  if(aborted)throw Error('Render interrupted; complete segments can be resumed');throw error;
 }finally{
  encoder?.kill();await browser?.close().catch(()=>{});server?.closeAllConnections();if(server)await new Promise(done=>server.close(done));
  await unlink(muxed).catch(()=>{});await unlink(joined).catch(()=>{});await unlink(lockPath).catch(()=>{});
  if(a.clean)await rmdir(work).catch(()=>{});
  process.removeListener('SIGINT',abort);process.removeListener('SIGTERM',abort);
 }
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))renderMain(process.argv.slice(2)).catch(error=>{console.error(error.message);process.exitCode=2;});
