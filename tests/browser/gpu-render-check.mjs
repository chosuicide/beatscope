import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import assert from 'node:assert/strict';import{chromium}from'playwright';
const root=path.resolve('.beatscope-cache/movies/5adc351cd3474e8a48e41e76'),data=JSON.parse(fs.readFileSync(root+'/material-timeline.json'));
const server=http.createServer((req,res)=>{const n=new URL(req.url,'http://local').pathname.slice(1);if(!n){res.end('<!doctype html><title>GPU render check</title>');return;}if(['material-frame.mjs','material-gpu.mjs','mv-encode.mjs'].includes(n)){res.setHeader('Content-Type','text/javascript');res.end(fs.readFileSync('beatscope/web/'+n));return;}if(!/^media\/[A-Za-z0-9_-]+\.jpg$/.test(n)){res.writeHead(404).end();return;}res.setHeader('Content-Type','image/jpeg');res.end(fs.readFileSync(path.join(root,n)));});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',args:['--enable-gpu','--enable-webgl']});
try{
 const cdp=await browser.newBrowserCDPSession(),system=await cdp.send('SystemInfo.getInfo'),p=await browser.newPage();await p.goto(`http://127.0.0.1:${server.address().port}`);
 const report=await p.evaluate(async data=>{
  const {createMaterialMovie}=await import('/material-frame.mjs'),canvas=()=>{const c=document.createElement('canvas');c.width=c.height=1080;return c;},a=canvas(),b=canvas(),r=await createMaterialMovie(a,data),cpu=await createMaterialMovie(b,data,'',{composite:false}),checks=[];
  const times=[.033,1.1,13.6,14.8666667,19.7,36.5333333,58.3,68.9666667,91.45,94.3,101.7,192.5,198,211.2,214.5];
  const seen=new Set();let bursts=0,landscapes=0;
  for(const [i,f]of data.frames.entries())if(!seen.has(f.shot)){
   seen.add(f.shot);
   if(f.setup.surfaceBurst&&f.setup.negativeBurstFrames>6&&bursts++<4)for(const offset of [2,8,14])times.push((i+offset)/30);
   if(f.setup.waterLandscape&&landscapes++<3)for(const offset of [4,9,17])times.push((i+offset)/30);
  }
  // Cover each authored layout/transition without replaying the whole song.
  const modes=new Set(),transitions=new Set();for(const [i,f]of data.frames.entries()){
   if(!modes.has(f.setup.mode)){modes.add(f.setup.mode);times.push(Math.min(data.duration,(i+2)/30));}
   if(f.previous&&!transitions.has(f.setup.transition)){transitions.add(f.setup.transition);times.push(i/30);}
  }
  // Read comparison pixels through separate canvases so timed drawing stays accelerated.
  const ca=canvas(),cb=canvas(),qa=ca.getContext('2d',{willReadFrequently:true}),qb=cb.getContext('2d',{willReadFrequently:true});
  for(const time of times){await r(time);await cpu(time);qa.drawImage(a,0,0);qb.drawImage(b,0,0);const x=qa.getImageData(0,0,1080,1080).data,y=qb.getImageData(0,0,1080,1080).data;let error=0,big=0;for(let i=0;i<x.length;i+=4)for(let c=0;c<3;c++){const d=Math.abs(x[i+c]-y[i+c]);error+=d;if(d>12)big++;}checks.push({time,meanChannelError:error/(1080*1080*3),largeDifferenceFraction:big/(1080*1080*3)});}
  const first=a.toDataURL();await r(0);await r(times.at(-1));const seekIdentical=first===a.toDataURL();
  const indices=data.frames.flatMap((f,i)=>f.setup.trail&&f.sinceCut>.02&&f.sinceCut<.19?[i]:[]).slice(0,30);for(const i of indices){await r(i/30);await cpu(i/30);}
  const measure=async render=>{const values=[];for(let round=0;round<3;round++)for(const i of indices){const t=performance.now();await render(i/30);values.push(performance.now()-t);}values.sort((a,b)=>a-b);return values[Math.floor(values.length/2)];};
  const cpuMs=await measure(cpu),gpuMs=await measure(r),acceleration=r.acceleration;r.dispose();cpu.dispose();
  const configs=[];for(const preference of ['prefer-hardware','prefer-software','no-preference']){const config={codec:'avc1.640028',width:1080,height:1080,framerate:30,bitrate:8000000,hardwareAcceleration:preference,avc:{format:'annexb'}};configs.push({preference,supported:(await VideoEncoder.isConfigSupported(config)).supported});}
  return{checks,seekIdentical,acceleration,configs,performance:{frames:90,cpuMedianMs:cpuMs,gpuMedianMs:gpuMs}};
 },data);
 report.system={devices:system.gpu.devices,features:system.gpu.featureStatus,aux:system.gpu.auxAttributes};
 fs.writeFileSync('output/gpu-composite-check.json',JSON.stringify(report,null,2));console.log(JSON.stringify({checks:report.checks.length,worstError:Math.max(...report.checks.map(c=>c.meanChannelError)),worstLargeFraction:Math.max(...report.checks.map(c=>c.largeDifferenceFraction)),seekIdentical:report.seekIdentical,acceleration:report.acceleration,performance:report.performance},null,2));
 assert.equal(report.acceleration.effects,'webgl2-composite');assert.ok(report.seekIdentical);assert.ok(report.checks.every(c=>c.meanChannelError<2&&c.largeDifferenceFraction<.01),'GPU effect parity');
}finally{await browser.close();await new Promise(r=>server.close(r));}
