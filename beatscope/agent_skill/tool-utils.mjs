// Shared CLI plumbing. Commands never install dependencies or invoke a shell.
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {createReadStream} from 'node:fs';
import {readFile,writeFile,rename} from 'node:fs/promises';

export function options(argv, flags=[], values=[], repeated=[]){
 const result={};
 for(let i=0;i<argv.length;i++){
  const key=argv[i];
  if(!key.startsWith('--')||Object.hasOwn(result,key.slice(2))&&!repeated.includes(key.slice(2)))throw Error(`Unknown or repeated argument: ${key}`);
  const name=key.slice(2);
  if(flags.includes(name)){result[name]=true;continue;}
  if(!values.includes(name)||argv[i+1]===undefined||argv[i+1].startsWith('--'))throw Error(`Invalid argument: ${key}`);
  const value=argv[++i];
  if(repeated.includes(name))(result[name]??=[]).push(value);else result[name]=value;
 }
 return result;
}
export function number(value,fallback,min,max,label){
 const n=value===undefined?fallback:Number(value);
 if(!Number.isFinite(n)||n<min||n>max)throw Error(`${label} must be between ${min} and ${max}`);
 return n;
}
export async function hashFile(path){const h=createHash('sha256');for await(const part of createReadStream(path))h.update(part);return h.digest('hex');}
export const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
export const jsonFile=async path=>JSON.parse(await readFile(path,'utf8'));
export async function saveJson(path,value){await writeFile(path+'.tmp',JSON.stringify(value,null,2)+'\n');await rename(path+'.tmp',path);}
export function processTool(program,args,{input=false,onData,timeout=120000}={}){
 const child=spawn(program,args,{shell:false,windowsHide:true,stdio:[input?'pipe':'ignore','pipe','pipe']});
 let stdout='',stderr='',timer;
 const done=new Promise((resolve,reject)=>{
  child.stdout.on('data',data=>{if(onData)onData(data);else stdout=(stdout+data.toString()).slice(-262144);});
  child.stderr.on('data',data=>{stderr=(stderr+data.toString()).slice(-65536);});
  child.stdin?.on('error',()=>{});
  child.once('error',error=>{clearTimeout(timer);reject(error);});
  child.once('close',(code,signal)=>{clearTimeout(timer);if(code===0)resolve(stdout);else reject(Error(`${program} failed (${signal??code}): ${stderr.trim()}`));});
  timer=setTimeout(()=>{child.kill();reject(Error(`${program} exceeded its time limit`));},timeout);
 });
 // Attach early: a missing executable may fail while the caller prepares input.
 done.catch(()=>{});
 return {child,done};
}
export const run=async(program,args,config)=>processTool(program,args,config).done;
export async function probe(video){
 return JSON.parse(await run(process.env.BEATSCOPE_FFPROBE||'ffprobe',['-v','error','-count_frames','-show_entries','stream=codec_type,width,height,avg_frame_rate,nb_read_frames:format=duration','-of','json',video]));
}
