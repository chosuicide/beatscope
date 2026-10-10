import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {pathToFileURL} from 'node:url';
import {createHash,randomBytes} from 'node:crypto';
import {acceptsChunk,writeChunk} from './mv-io.mjs';
const root=path.resolve(process.argv[2]);
const {chromium}=await import(pathToFileURL(process.env.BEATSCOPE_PLAYWRIGHT_MODULE).href);
const {makePlan}=await import(pathToFileURL(path.join(root,'mv-plan.mjs')).href);
const {createTrack}=await import(pathToFileURL(path.join(root,'beatscope-runtime.js')).href);
const input=JSON.parse(fs.readFileSync(path.join(root,'input.json')));
const hash=createHash('sha256');for await(const chunk of fs.createReadStream(input.audio))hash.update(chunk);
if(hash.digest('hex')!==input.rhythm.source.sha256)throw Error('Audio hash mismatch');
const track=createTrack(input.rhythm,{responseRelevance:input.ranking});
const plan=input.template&&input.template!=='voxel'&&input.template!=='paint'?JSON.parse(fs.readFileSync(path.join(root,'plan.json'))):makePlan(input.rhythm,track.responseBetween(0,input.rhythm.source.duration),input.seed,input.editPlan);
if(input.template==='paint')plan.template='paint';
fs.writeFileSync(path.join(root,'plan.json'),JSON.stringify(plan));
// Capture is the bottleneck (frame rendering itself costs <1 ms), so several
// pages render and grab frames in parallel, chunk by chunk, and the frames are
// piped to the encoder in exact time order. Frame content is a pure function
// of its media time, so the output is identical to the single-page path.
// Screenshots can be grabbed from several pages in parallel because the
// frames are reassembled in order. In-page encoding cannot: each page owns an
// independent H.264 stream, so the encoder path is deliberately single-page.
const PAGES=Math.max(1,Math.min(6,Math.floor(Number(process.env.BEATSCOPE_MV_PAGES)||3)));
// Pastel Bloom carries stroke state from frame to frame, so it renders on one page in order.
const PAGES_FOR=(mode)=>mode==='webcodecs'||input.template==='paint'?1:PAGES;
const PRESET=process.env.BEATSCOPE_MV_PRESET||'slower';
const CRF=process.env.BEATSCOPE_MV_CRF||'20';
// Capping encoder threads keeps the capture pages fed: with all cores on x264
// the capture side starves and the loop runs slower overall.
const THREADS=Math.max(0,Math.min(64,Math.floor(Number(process.env.BEATSCOPE_MV_THREADS)||0)));
// In-page WebCodecs encoding is the fast path; BEATSCOPE_MV_ENCODER=png forces
// the screenshot+FFmpeg path, and an unsupported browser falls back to it too.
const ENCODER=String(process.env.BEATSCOPE_MV_ENCODER||'webcodecs').toLowerCase();
const HARDWARE=['prefer-hardware','prefer-software','no-preference'].includes(process.env.BEATSCOPE_MV_HARDWARE)?process.env.BEATSCOPE_MV_HARDWARE:'prefer-hardware';
const GPU=process.env.BEATSCOPE_MV_GPU==='0'?'0':'1';
const COMPOSITE=process.env.BEATSCOPE_MV_COMPOSITE==='0'?'0':'1';
const BITRATE=Math.max(100000,Math.min(50000000,Math.floor(Number(process.env.BEATSCOPE_MV_BITRATE)||8000000)));
const token=randomBytes(24).toString('hex');
let videoMode=ENCODER==='png'?'png':'webcodecs';
const allowed=new Set(['mv-render.html','mv-frame.mjs','mv-visual.js','mv-plan.mjs','mv-encode.mjs','beatscope-runtime.js','edit-plan.js','input.json','plan.json','movie-factory.mjs','movie-templates.mjs','material-frame.mjs','material-gpu.mjs','material-timeline.json','paint-frame.mjs']);
let encoderStream=null; // ffmpeg stdin, fed by POST /chunk from the page
const publicInput=JSON.stringify({rhythm:input.rhythm,ranking:input.ranking});
const server=http.createServer(async (req,res)=>{
 const name=new URL(req.url,'http://local').pathname.slice(1)||'mv-render.html';
 if(req.method==='POST'&&name==='chunk'){
  if(!acceptsChunk(req.headers,`127.0.0.1:${server.address().port}`,token)){res.writeHead(403).end();return;}
  if(!encoderStream){res.writeHead(409).end();return;}
  try{
   let size=0;
   for await(const piece of req){size+=piece.length;if(size>64*1024*1024)throw Error('Chunk too large');await writeChunk(encoderStream,piece);}
   res.writeHead(200).end('ok');
  }catch(error){res.writeHead(500).end(String(error));}
  return;
 }
 if(req.method!=='GET'){res.writeHead(405).end();return;}
 if(!allowed.has(name)&&!(input.template?.startsWith('material-')&&/^media\/[A-Za-z0-9_-]+\.jpg$/.test(name))&&!(input.template==='paint'&&/^paint-assets\/[a-z]+\/(lo|hi)\/[0-9]{4}\.jpg$/.test(name))){res.writeHead(404).end();return;}
 if(!fs.existsSync(path.join(root,name))){res.writeHead(404).end();return;}
 res.setHeader('Content-Type',name.endsWith('.html')?'text/html':name.endsWith('.json')?'application/json':name.endsWith('.jpg')?'image/jpeg':'text/javascript');
 res.end(name==='input.json'?publicInput:fs.readFileSync(path.join(root,name)));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser,encoder,encoderClosed;let cancelled=false;
let lastProgress=Date.now(), aborted=false;
// Cancellation and encoder failure must also interrupt an in-flight page.evaluate.
const watchdog=setInterval(()=>{
 let parentGone=false;
 const parent=Number(process.env.BEATSCOPE_RENDER_PARENT_PID);
 if(parent>0){try{process.kill(parent,0);}catch{parentGone=true;}}
 const requested=fs.existsSync(path.join(root,'cancel'));
 if(!aborted&&(requested||parentGone||Date.now()-lastProgress>(input.template==='paint'?300000:90000))){
  aborted=true;cancelled=requested;
  console.error(requested?'Cancelled':parentGone?'Render host stopped':'Render stalled for 90 seconds');
  encoderStream?.destroy();encoder?.kill();void browser?.close();
 }
},500);
const check=()=>{if(fs.existsSync(path.join(root,'cancel'))){cancelled=true;throw Error('Cancelled');}};
const temp=path.join(root,'movie.partial.mp4'), output=path.join(root,'movie.mp4');
try {
 check();browser=await chromium.launch({headless:true,channel:process.env.BEATSCOPE_BROWSER_CHANNEL||(process.platform==='win32'?'msedge':'chromium'),args:['--enable-gpu','--enable-webgl']});
 const errors=[];
 const makeWorker=async()=>{
  const page=await browser.newPage({viewport:{width:1080,height:1080},deviceScaleFactor:1});
  page.on('pageerror',e=>errors.push(String(e)));
  // Lossless but much faster than page.screenshot(): the CDP screenshot with
  // optimizeForSpeed uses a faster zlib setting, so pixels are identical.
  const cdp=await page.context().newCDPSession(page);
 const query=videoMode==='webcodecs'?`?encode=webcodecs&bitrate=${BITRATE}&hardware=${HARDWARE}&gpu=${GPU}&composite=${COMPOSITE}&token=${token}`:`?gpu=${GPU}&composite=${COMPOSITE}`;
  await page.goto(`http://127.0.0.1:${server.address().port}/${query}`);
  await page.waitForFunction(()=>window.ready,{},{timeout:input.template==='paint'?180000:45000});
  if(videoMode==='webcodecs'){
   const codec=await page.evaluate(()=>window.encoderCodec||null);
   if(!codec){await page.close();throw Error('webcodecs-unavailable');}
  }
  return {page,render:async t=>{await page.evaluate(x=>window.renderAt(x),t);return Buffer.from((await cdp.send('Page.captureScreenshot',{format:'png',optimizeForSpeed:true,captureBeyondViewport:false})).data,'base64');}};
 };
 const workers=[];
 for(let i=0;i<PAGES_FOR(videoMode);i++){
  let worker;
  try{
   worker=await makeWorker();
  }catch(error){
   if(String(error).includes('webcodecs-unavailable')){videoMode='png';console.log(JSON.stringify({progress:0,message:'浏览器不支持页面内编码，改用截图路径'}));}
   else throw error;
   worker=await makeWorker();
  }
  if(videoMode==='webcodecs')worker.encode=async t=>{await worker.page.evaluate(x=>window.encodeAt(x),t);};
  workers.push(worker);
 }
 const lead=workers[0];
 const acceleration=await lead.page.evaluate(()=>({encodingPreference:window.encoderAcceleration||null,effects:window.renderAt.acceleration||null}));
 fs.writeFileSync(path.join(root,'acceleration.json'),JSON.stringify(acceleration,null,2));
 const checkpoint=Math.min(8,plan.duration/2);
 await lead.page.evaluate(t=>window.renderAt(t),checkpoint);const before=await lead.page.screenshot();
 await lead.page.evaluate(()=>window.renderAt(0));await lead.page.evaluate(t=>window.renderAt(t),checkpoint);
 if(!before.equals(await lead.page.screenshot()))throw Error('Seek reproducibility check failed');
 const frames=Math.ceil(plan.duration*plan.fps);let stderr='';
 const diagnostics=await browser.newBrowserCDPSession();
 const cpuBefore=await diagnostics.send('SystemInfo.getProcessInfo').catch(()=>null),renderStarted=Date.now();
 // webcodecs: the page encodes, FFmpeg only muxes the elementary stream
 // png: FFmpeg decodes the screenshots and encodes the video itself
 const videoArgs=videoMode==='webcodecs'
  // Annex B discards WebCodecs timestamps. Force a constant input clock:
  // some software encoders rewrite their VUI timing at a later keyframe.
  ?['-f','h264','-r',String(plan.fps),'-i','pipe:0']
  :['-f','image2pipe','-framerate',String(plan.fps),'-vcodec','png','-i','pipe:0'];
 // Both paths must describe the same RGB->YUV mapping: Chromium converts a
 // canvas with BT.709, while ffmpeg defaults to BT.601 for RGB sources. Pin
 // both to BT.709 and tag the output so players agree with us.
 const BT709=['-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-color_range','tv'];
 const videoCodecArgs=videoMode==='webcodecs'
  ?['-c:v','copy','-bsf:v','h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1',...BT709]
  :['-c:v','libx264','-preset',PRESET,'-crf',String(CRF),'-tune','film',...(THREADS?['-threads',String(THREADS)]:[]),'-pix_fmt','yuv420p','-vf','scale=out_color_matrix=bt709:out_range=tv',...BT709];
 encoder=spawn(process.env.BEATSCOPE_FFMPEG||'ffmpeg',['-y','-v','error',...videoArgs,'-i',input.audio,'-map','0:v:0','-map','1:a:0','-af',`atrim=duration=${plan.duration},asetpts=PTS-STARTPTS`,...videoCodecArgs,'-c:a','aac','-b:a','192k','-t',String(plan.duration),'-movflags','+faststart',temp],{windowsHide:true,stdio:['pipe','ignore','pipe']});
 encoderStream=videoMode==='webcodecs'?encoder.stdin:null;
 encoder.stderr.on('data',b=>stderr=(stderr+b).slice(-4000));
 let pipeError;encoder.stdin.on('error',e=>pipeError=e);
 const closed=encoderClosed=once(encoder,'close');
 closed.catch(()=>{});
 const write=async png=>{
  await writeChunk(encoder.stdin,png);
 };
 const step=PAGES_FOR(videoMode);
 for(let start=0;start<frames;start+=step){
  check();if(aborted)throw Error('Render interrupted');if(errors.length)throw Error(errors.join(' | '));if(pipeError)throw pipeError;if(encoder.exitCode!==null)throw Error(stderr||'Encoder stopped');
  if(videoMode==='webcodecs'){
   // the pages render and encode; only compressed chunks travel to FFmpeg
   await Promise.all(workers.map((worker,slot)=>{
    const index=start+slot;
    return index<frames?worker.encode(index/plan.fps):Promise.resolve();
   }));
  }else{
   const shots=await Promise.all(workers.map((worker,slot)=>{
    const index=start+slot;
    return index<frames?worker.render(index/plan.fps):Promise.resolve(null);
   }));
   for(const png of shots)if(png)await write(png);
  }
  lastProgress=Date.now();
  if(start%120===0)console.log(JSON.stringify({progress:Math.min(1,(start+step)/frames),frame:start,frames,pages:workers.length,encoder:videoMode}));
 }
 if(videoMode==='webcodecs')await workers[0].page.evaluate(()=>window.finishEncode());
 encoderStream=null;encoder.stdin.end();const [code]=await closed;if(code!==0)throw Error(stderr);
 check();if(TMPD){fs.copyFileSync(temp,output);fs.rmSync(temp,{force:true});}else fs.renameSync(temp,output);
 const cpuAfter=await diagnostics.send('SystemInfo.getProcessInfo').catch(()=>null);
 if(cpuBefore&&cpuAfter){const initial=new Map(cpuBefore.processInfo.map(p=>[p.id,p.cpuTime]));acceleration.browserCpuSeconds=cpuAfter.processInfo.reduce((sum,p)=>sum+Math.max(0,p.cpuTime-(initial.get(p.id)??0)),0);}
 acceleration.renderSeconds=(Date.now()-renderStarted)/1000;
 fs.writeFileSync(path.join(root,'acceleration.json'),JSON.stringify(acceleration,null,2));
 console.log(JSON.stringify({progress:1,complete:true,frames,duration:plan.duration,shots:plan.shots.length,pages:workers.length,encoder:videoMode,acceleration,preset:videoMode==='png'?PRESET:null,crf:videoMode==='png'?Number(CRF):null,bitrate:videoMode==='webcodecs'?BITRATE:null}));
} finally {
 clearInterval(watchdog);
 if(encoder&&encoder.exitCode===null){encoder.stdin.destroy();encoder.kill();await encoderClosed?.catch(()=>{});}
 await browser?.close();server.closeAllConnections();server.close();
 if(fs.existsSync(temp))fs.unlinkSync(temp);
 if(cancelled&&fs.existsSync(output))fs.unlinkSync(output);
}
