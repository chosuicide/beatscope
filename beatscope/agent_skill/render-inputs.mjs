// Bounded input checks, explicit exclusions and conservative disk estimates.
import {readdir,stat,lstat,open,realpath,statfs} from 'node:fs/promises';
import {resolve,relative,isAbsolute,join} from 'node:path';
import {hashFile,processTool,run} from './tool-utils.mjs';

export const inside=(root,path)=>{const r=relative(root,path);return !isAbsolute(r)&&r!=='..'&&!r.startsWith('..'+(process.platform==='win32'?'\\':'/'));};
export function exclusions(root,paths=[]){
 return [...new Set(paths.map(p=>{
  if(!p||isAbsolute(p)||/[?*]/.test(p))throw Error('--exclude needs a root-relative file/directory path, not a glob');
  const file=resolve(root,p);if(file===root||!inside(root,file))throw Error('--exclude must stay inside root and cannot exclude root');return file;
 }))].sort();
}
export const excluded=(file,paths)=>paths.some(p=>file===p||inside(p,file));
export async function sourceHashes(root,omitted,paths){
 const files=[];let bytes=0;
 async function walk(dir){
  for(const entry of (await readdir(dir,{withFileTypes:true})).sort((a,b)=>a.name.localeCompare(b.name))){
   const file=join(dir,entry.name);
   if(omitted.has(file)||excluded(file,paths)||entry.name.startsWith('.render-')||['node_modules','.git','.beatscope-cache','output'].includes(entry.name))continue;
   if(entry.isSymbolicLink())throw Error(`Symlink in render sources: ${relative(root,file)}`);
   if(entry.isDirectory())await walk(file);
   else if(entry.isFile()){files.push(file);bytes+=(await stat(file)).size;}
  }
 }
 await walk(root);
 if(bytes>50*1024*1024)process.stderr.write(`Warning: source snapshot is ${(bytes/1024/1024).toFixed(1)} MiB; hashing all included files. Use --exclude for generated output directories.\n`);
 const rows=[];for(const file of files)rows.push([relative(root,file).replaceAll('\\','/'),await hashFile(file)]);
 return {rows,bytes};
}
export async function frameSources(dir,pattern,start,count,width,height){
 if(/[\\/]/.test(pattern)||!pattern.endsWith('.png'))throw Error('--frame-pattern must be a PNG filename with one %d or %0Nd placeholder');
 const match=/^([^%]*)%0?(\d*)d([^%]*)$/.exec(pattern);
 if(!match||Number(match[2])>12)throw Error('Invalid --frame-pattern; use frame-%06d.png');
 const files=[];let bytes=0;
 for(let i=0;i<count;i++){
  const name=match[1]+String(start+i).padStart(Number(match[2])||0,'0')+match[3],file=join(dir,name);
  const info=await lstat(file).catch(()=>{throw Error(`Missing input frame ${start+i}: ${name}`);});
  if(!info.isFile()||info.isSymbolicLink()||!inside(dir,await realpath(file)))throw Error(`Input frame is not a regular local file: ${name}`);
  const handle=await open(file,'r');const header=Buffer.alloc(24);let size;
  try{size=(await handle.read(header,0,24,0)).bytesRead;}finally{await handle.close();}
  if(size<24||header.subarray(0,8).toString('hex')!=='89504e470d0a1a0a'||header.toString('ascii',12,16)!=='IHDR')throw Error(`Invalid PNG input frame: ${name}`);
  const w=header.readUInt32BE(16),h=header.readUInt32BE(20);
  if(w!==width||h!==height)throw Error(`Input frame ${name} is ${w}×${h}; requested ${width}×${height}`);
  files.push([name,await hashFile(file)]);bytes+=info.size;
 }
 return {files,bytes};
}
export async function diskSpace(directory,{width,height,frameCount,retainedBytes=0}){
 // CRF output size depends on content. Estimate 0.5 bytes/pixel/frame plus margin;
 // this is an early warning/refusal, not an exact upper bound on encoder output.
 const encodedEstimate=Math.ceil(width*height*frameCount*.5);
 const required=Math.max(32*1024*1024,encodedEstimate*2-retainedBytes+16*1024*1024);
 try{
  const fs=await statfs(directory,{bigint:true}),available=Number(fs.bavail*fs.bsize);
  if(available<required)throw Error(`Insufficient estimated disk space: ${(available/1024/1024).toFixed(1)} MiB available; about ${(required/1024/1024).toFixed(1)} MiB additional estimated. Change --out or free space.`);
  return {availableBytes:available,estimatedAdditionalBytes:required,estimatedEncodedBytes:encodedEstimate,method:'content-dependent estimate: 0.5 bytes/pixel/frame, segments plus final, with margin; not a guarantee'};
 }catch(error){if(error.code){process.stderr.write(`Warning: disk free-space check unavailable (${error.code})\n`);return {availableBytes:null,estimatedAdditionalBytes:required,method:'free-space API unavailable; estimate only'};}throw error;}
}
async function audioInfo(path){
 const info=JSON.parse(await run(process.env.BEATSCOPE_FFPROBE||'ffprobe',['-v','error','-show_entries','stream=codec_type:format=duration','-of','json',path]));
 const duration=Number(info.format?.duration);
 if(!info.streams?.some(s=>s.codec_type==='audio')||!Number.isFinite(duration)||duration<=0)throw Error('Audio reference/input has no valid audio duration');
 return duration;
}
async function pcm(path,start,seconds){
 const chunks=[];
 await processTool(process.env.BEATSCOPE_FFMPEG||'ffmpeg',['-v','error','-ss',String(start),'-i',path,'-t',String(seconds),'-vn','-ac','1','-ar','8000','-f','f32le','pipe:1'],{onData:b=>chunks.push(b)}).done;
 const bytes=Buffer.concat(chunks),values=new Float32Array(bytes.length/4);
 for(let i=0;i<values.length;i++)values[i]=bytes.readFloatLE(i*4);
 return values;
}
function similarity(a,b){
 let best={correlation:-1,lagSamples:0},power=0;for(const x of a)power+=x*x;
 if(a.length<800||power/a.length<1e-8)return {informative:false};
 // +/-40ms checks codec padding only. A shifted edit is never silently retimed.
 for(let lag=-320;lag<=320;lag+=4){let ab=0,aa=0,bb=0;
  for(let i=320;i<Math.min(a.length,b.length)-320;i+=2){const x=a[i],y=b[i+lag];ab+=x*y;aa+=x*x;bb+=y*y;}
  const correlation=aa&&bb?ab/Math.sqrt(aa*bb):0;
  if(correlation>best.correlation+1e-5||correlation>=best.correlation-1e-5&&Math.abs(lag)<Math.abs(best.lagSamples))best={correlation,lagSamples:lag};
 }
 let ea=0,eb=0,difference=0;
 for(let i=320;i+80<Math.min(a.length,b.length)-320;i+=80){let x=0,y=0;for(let n=0;n<80;n++){x+=a[i+n]**2;y+=b[i+n+best.lagSamples]**2;}x=Math.sqrt(x/80);y=Math.sqrt(y/80);ea+=x*x;eb+=y*y;}
 const gain=eb?Math.sqrt(ea/eb):0;
 for(let i=320;i+80<Math.min(a.length,b.length)-320;i+=80){let x=0,y=0;for(let n=0;n<80;n++){x+=a[i+n]**2;y+=b[i+n+best.lagSamples]**2;}difference+=(Math.sqrt(x/80)-gain*Math.sqrt(y/80))**2;}
 return {informative:true,correlation:best.correlation,alignmentMs:best.lagSamples/8,envelopeRelativeError:ea?Math.sqrt(difference/ea):1};
}
export async function audioIdentity(audio,hash,expected,reference){
 if(!expected||!/^[a-f0-9]{64}$/.test(expected))return {audioIdentity:'unverified',sourceAudioSha256:expected??null};
 if(hash===expected)return {audioIdentity:'sha256-match',sourceAudioSha256:expected};
 if(!reference)throw Error('Original audio does not match the timing package source SHA-256. For a transcoded copy provide --reference-audio ORIGINAL (matching source hash); duration alone cannot establish identity.');
 const referenceSha256=await hashFile(reference);
 if(referenceSha256!==expected)throw Error('--reference-audio does not match the timing package source SHA-256');
 const originalDuration=await audioInfo(reference),inputDuration=await audioInfo(audio),tolerance=Math.min(.25,Math.max(.08,originalDuration*.001));
 if(Math.abs(originalDuration-inputDuration)>tolerance)throw Error('Transcoded audio duration differs from original');
 const length=Math.min(5,originalDuration-.1),starts=[...new Set([0,Math.max(0,(originalDuration-length)/2),Math.max(0,originalDuration-length-.05)])];
 if(length<.25)throw Error('Audio too short for a reliable transcoded comparison');
 const comparisons=[];
 for(const start of starts){const a=await pcm(reference,start,length),b=await pcm(audio,start,length);comparisons.push({start,seconds:length,...similarity(a,b)});}
 const useful=comparisons.filter(c=>c.informative);
 if(!useful.length||useful.some(c=>c.correlation<.98||c.envelopeRelativeError>.08||Math.abs(c.alignmentMs)>10))throw Error('Transcoded audio did not pass decoded waveform/envelope alignment checks; retain the original audio or inspect the different edit.');
 return {audioIdentity:'transcoded-match',sourceAudioSha256:expected,referenceSha256,originalDuration,inputDuration,comparisons,method:'duration plus distributed decoded mono waveform/envelope checks; inference, not byte identity; no timeline offset applied'};
}
