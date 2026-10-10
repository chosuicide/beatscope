import {useEffect,useMemo,useRef,useState} from 'react';
import {arrangeMedia,normalizeMediaSlot,placeSlot,snapPoints,snapTime,freeRange,beatLength,type MediaDocument,type Focus} from '../../../beatscope/web/custom-media.mjs';
import type {MovieRhythm} from './types';
import type {EditPlan} from '../../../beatscope/runtime/edit-plan.js';
export type CatalogAsset={asset_id:string;display_name:string;width:number;height:number;kind:string};
export type MediaUpload={key:string;name:string;url:string;progress:number;state:'waiting'|'queued'|'uploading'|'processing'|'error';error?:string;video?:boolean};
export const isVideoFile=(file:File)=>/^video\/(mp4|quicktime|webm|x-m4v)$/i.test(file.type)||/\.(mp4|mov|m4v|webm)$/i.test(file.name);
function postJson(path:string,signal:AbortSignal):Promise<Record<string,any>>{
 return fetch(path,{method:'POST',signal}).then(async response=>{const data=await response.json().catch(()=>({}));if(!response.ok)throw Error(data.message||data.error||'Request failed');return data;});
}
function probeVideoDuration(url:string):Promise<number|null>{
 return new Promise(resolve=>{const el=document.createElement('video');el.preload='metadata';el.muted=true;let done=false;
  const fin=(d:number|null)=>{if(done)return;done=true;el.src='';resolve(d);};
  el.onloadedmetadata=()=>fin(Number.isFinite(el.duration)?el.duration:null);el.onerror=()=>fin(null);setTimeout(()=>fin(null),5000);el.src=url;});
}
// Progress needs XHR: fetch has no upload events. The proxy counts as the last
// 10% of a file's journey, so the ring only fills up once both posts land.
function postAsset(projectId:string,body:Blob,name:string,onProgress:(f:number)=>void,signal:AbortSignal):Promise<Record<string,any>>{
 return new Promise((resolve,reject)=>{
  const xhr=new XMLHttpRequest();
  const abort=()=>xhr.abort();signal.addEventListener('abort',abort,{once:true});
  xhr.onloadend=()=>signal.removeEventListener('abort',abort);
  xhr.onabort=()=>reject(new DOMException('Import cancelled','AbortError'));
  xhr.open('POST',`/api/projects/${projectId}/assets`);
  xhr.setRequestHeader('Content-Type','application/octet-stream');
  xhr.setRequestHeader('X-Filename',encodeURIComponent(name));
  xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(e.loaded/e.total);};
  xhr.onload=()=>{let data:Record<string,any>={};try{data=JSON.parse(xhr.responseText||'{}');}catch{/* empty */}
   if(xhr.status>=400)reject(Error(data.message||data.error||'Import failed'));else resolve(data);};
  xhr.onerror=()=>reject(Error('Import failed'));
  if(signal.aborted)reject(new DOMException('Import cancelled','AbortError'));else xhr.send(body);
 });
}
export function useCustomMedia(projectId:string|undefined,rhythm:MovieRhythm|null,editPlan:EditPlan|null,time:number,lang='en'){
 const [doc,setDoc]=useState<MediaDocument|null>(null),[catalog,setCatalog]=useState<CatalogAsset[]>([]);
 const [saving,setSaving]=useState(false),[error,setError]=useState('');
 const [uploads,setUploads]=useState<MediaUpload[]>([]),files=useRef(new Map<string,File>());
 const uploadRows=useRef(uploads);uploadRows.current=uploads;
 const [history,setHistory]=useState<{past:MediaDocument[];future:MediaDocument[]}>({past:[],future:[]});
 const current=useRef(doc);current.current=doc;
 const etag=useRef(''),active=useRef(0),locked=useRef(false);
 const previousProject=useRef<string|undefined>(undefined);
 const requests=useRef(new AbortController());
 const arrangedPlan=useRef<EditPlan|null>(null);
 const playhead=useRef(time);playhead.current=time;
 useEffect(()=>{
  const token=++active.current,abort=new AbortController();setDoc(null);setCatalog([]);setHistory({past:[],future:[]});etag.current='';locked.current=false;setSaving(false);setError('');arrangedPlan.current=null;
  requests.current=abort;
  // Pending originals survive analysis completion, failure/retry and song changes.
  setUploads(us=>us.map(u=>u.state==='uploading'||u.state==='processing'?{...u,state:'waiting',progress:0}:u));
  if(projectId&&rhythm)void(async()=>{try{
   const from=previousProject.current;previousProject.current=projectId;
   if(from&&from!==projectId){const copied=await fetch(`/api/projects/${projectId}/custom-media/copy`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from}),signal:abort.signal});if(!copied.ok)throw Error('Cannot carry images to the new song');}
   const [response,assets]=await Promise.all([fetch(`/api/projects/${projectId}/custom-media`,{signal:abort.signal}),fetch(`/api/projects/${projectId}/assets`,{signal:abort.signal})]);
   const data=await response.json(),library=await assets.json();if(!response.ok||!assets.ok)throw Error(data.error||'Cannot restore images');
   if(active.current!==token)return;etag.current=response.headers.get('ETag')??'';setDoc(data);setCatalog(library.assets);
  }catch(e){if(!abort.signal.aborted&&active.current===token)setError(String(e));}})();
  return()=>{abort.abort();active.current++;};
 },[projectId,rhythm]);
 useEffect(()=>{
  if(!editPlan||!rhythm||!current.current||locked.current||importing.current||arrangedPlan.current===editPlan)return;
  arrangedPlan.current=editPlan;
  const next=arrangeMedia(current.current,rhythm,editPlan);
  if(JSON.stringify(next)!==JSON.stringify(current.current))void commit(next);
 },[editPlan,doc?.source_sha256,saving]);
 async function commit(next:MediaDocument,mode:'edit'|'undo'|'redo'='edit'){
  const prior=current.current,token=active.current;if(!prior||!projectId||locked.current)return false;
  if(JSON.stringify(prior)===JSON.stringify(next))return true;
  locked.current=true;setSaving(true);setError('');
  try{
   const response=await fetch(`/api/projects/${projectId}/custom-media`,{method:'PUT',headers:{'Content-Type':'application/json','If-Match':etag.current},body:JSON.stringify(next)});
   const data=await response.json();if(!response.ok)throw Error(data.message||data.error||'Save failed');if(active.current!==token)return false;
   etag.current=response.headers.get('ETag')??'';current.current=data;setDoc(data);
   setHistory(h=>mode==='undo'?{past:h.past.slice(0,-1),future:[prior,...h.future]}:mode==='redo'?{past:[...h.past,prior].slice(-30),future:h.future.slice(1)}:{past:[...h.past,prior].slice(-30),future:[]});return true;
  }catch(e){if(active.current===token)setError(String(e));return false;}
  finally{if(active.current===token){locked.current=false;setSaving(false);}}
 }
 const importing=useRef(false);
 useEffect(()=>()=>{requests.current.abort();for(const up of uploadRows.current)URL.revokeObjectURL(up.url);files.current.clear();},[]);
 useEffect(()=>{
  if(!doc||!projectId||!rhythm||saving||importing.current)return;
  const todo=uploads.filter(u=>u.state==='waiting'||u.state==='queued');if(!todo.length)return;
  if(todo.some(u=>u.state==='waiting'))setUploads(us=>us.map(u=>u.state==='waiting'?{...u,state:'queued'}:u));
  importing.current=true;setSaving(true);const token=active.current;
  const patch=(key:string,next:Partial<MediaUpload>)=>{if(active.current===token)setUploads(us=>us.map(u=>u.key===key?{...u,...next}:u));};
  void(async()=>{try{
   let next=current.current!;const added:CatalogAsset[]=[],completed:MediaUpload[]=[];const signal=requests.current.signal;
   for(const up of todo){
    const file=files.current.get(up.key);if(!file)continue;
    try{
    patch(up.key,{state:'uploading'});
    if(next.assets.length>=100)throw Error('An arrangement supports up to 100 media items');
    if(isVideoFile(file)){
     if(file.size>100*1024*1024)throw Error(lang==='zh'?'视频限 60 秒以内、100 MB 以内':'Videos must be ≤60 s and ≤100 MB');
     const length=await probeVideoDuration(up.url);
     if(length!==null&&length>60)throw Error(lang==='zh'?'视频限 60 秒以内、100 MB 以内':'Videos must be ≤60 s and ≤100 MB');
     const data=await postAsset(projectId,file,file.name,f=>patch(up.key,{progress:f*.7}),signal);
     if(active.current!==token)return;
     const stored=data.asset??data;added.push(stored);
     patch(up.key,{state:'processing'});
     const existing=next.assets.find(a=>a.id===stored.asset_id);
     const derived=existing?.clip&&existing.proxy?{poster:existing.proxy,clip:existing.clip,duration:existing.duration}:await postJson(`/api/projects/${projectId}/assets/${stored.asset_id}/derive`,signal);
     if(active.current!==token)return;
     if(!derived.poster||!derived.clip)throw Error('Clip processing failed');
     const row={id:stored.asset_id,kind:'video' as const,proxy:derived.poster,clip:derived.clip,duration:derived.duration,focus:existing?.focus??{x:.5,y:.5,zoom:1,fit:'cover' as const},overrides:existing?.overrides??{}};
     next={...next,assets:existing?next.assets.map(a=>a.id===stored.asset_id?{...a,...row}:a):[...next.assets,row]};
     completed.push(up);
     continue;
    }
    if(!/\.(png|jpe?g|webp)$/i.test(file.name))throw Error('PNG / JPEG / WebP only. Convert HEIC photos before importing.');
    if(file.size>25*1024*1024)throw Error('Image exceeds 25 MiB');
    const bitmap=await createImageBitmap(file);const pixels=bitmap.width*bitmap.height;
    if(pixels>32*1024*1024){bitmap.close();throw Error('Image exceeds 32 megapixels');}
    const proxyCanvas=document.createElement('canvas'),scale=Math.min(1,960/Math.max(bitmap.width,bitmap.height));proxyCanvas.width=Math.max(1,Math.round(bitmap.width*scale));proxyCanvas.height=Math.max(1,Math.round(bitmap.height*scale));proxyCanvas.getContext('2d')!.drawImage(bitmap,0,0,proxyCanvas.width,proxyCanvas.height);bitmap.close();
    const proxy=await new Promise<Blob>((resolve,reject)=>proxyCanvas.toBlob(blob=>blob?resolve(blob):reject(Error('Cannot prepare image proxy')),'image/jpeg',.9));
    const data=await postAsset(projectId,file,file.name,f=>patch(up.key,{progress:f*.9}),signal);
    if(active.current!==token)return;
    const asset=data.asset??data;added.push(asset);
    const existing=next.assets.find(a=>a.id===asset.asset_id);
    if(!existing?.proxy){
     const proxyData=await postAsset(projectId,proxy,asset.asset_id+'.proxy.jpg',f=>patch(up.key,{progress:.9+f*.1}),signal);
     if(active.current!==token)return;
     next={...next,assets:existing?next.assets.map(a=>a.id===asset.asset_id?{...a,proxy:proxyData.asset.asset_id}:a):[...next.assets,{id:asset.asset_id,proxy:proxyData.asset.asset_id,focus:{x:.5,y:.5,zoom:1,fit:'cover'},overrides:{}}]};
    }
    if(active.current!==token)return;
    completed.push(up);
    }catch(e){patch(up.key,{state:'error',error:String(e).replace(/^Error: /,'')});}
   }
   if(active.current!==token)return;setCatalog(c=>[...c,...added.filter(a=>!c.some(b=>b.asset_id===a.asset_id))]);
   if(added.length){
    let arranged=arrangeMedia(next,rhythm,editPlan,false,playhead.current);
    const fresh=next.assets.find(a=>!current.current!.assets.some(old=>old.id===a.id));
    const activeSlot=arranged.slots.find(s=>!s.fixed&&s.start<=playhead.current&&s.end>playhead.current);
    if(fresh&&activeSlot)arranged={...arranged,slots:arranged.slots.map(s=>s===activeSlot?normalizeMediaSlot({...s,asset:fresh.id},fresh):s)};
    const saved=await commit(arranged);
    if(active.current!==token)return;
    if(saved){const keys=new Set(completed.map(u=>u.key));setUploads(us=>us.filter(u=>!keys.has(u.key)));for(const up of completed){URL.revokeObjectURL(up.url);files.current.delete(up.key);}}
    else for(const up of completed)patch(up.key,{state:'error',error:lang==='zh'?'保存失败，请重试':'Save failed; retry the import'});
   }
  }catch(e){if(active.current===token)setError(String(e));}
  finally{importing.current=false;if(active.current===token)setSaving(false);else setUploads(us=>[...us]);}})();
 },[doc,projectId,rhythm,uploads,saving,editPlan]);
 function change(next:MediaDocument,shuffle=false){if(rhythm)void commit(arrangeMedia(next,rhythm,editPlan,shuffle));}
 function remove(id:string){if(doc)change({...doc,assets:doc.assets.filter(a=>a.id!==id),slots:doc.slots.filter(s=>s.asset!==id)});}
 function focus(id:string,value:Focus,aspect?:string){if(doc)void commit({...doc,assets:doc.assets.map(a=>a.id!==id?a:aspect?{...a,overrides:{...a.overrides,[aspect]:value}}:{...a,focus:value})});}
 function pin(id:string,time:number){if(!doc||!rhythm)return;
  const duration=rhythm.source.duration,points=snapPoints(rhythm,editPlan);
  const start=snapTime(time,points);
  const beats=(rhythm.beats??[]).map(b=>b.time),future=beats.filter(t=>t>start);
  let end=future.length>=4?future[3]:Math.min(duration,start+3);
  const nextBoundary=editPlan?.boundaries.find(b=>b.time>start)?.time;if(nextBoundary)end=Math.min(end,nextBoundary);
  const range=freeRange(doc,start,duration),s=Math.max(start,range.min);end=Math.min(end,range.max);
  const entry=doc.assets.find(a=>a.id===id),video=entry?.kind==='video';
  if(video)end=Math.min(end,s+(entry.duration??0));
  if(end-s<.1)return;change(placeSlot(doc,{start:s,end,asset:id,...(video?{offset:0}:{})}));
 }
 const snaps=useMemo(()=>rhythm?snapPoints(rhythm,editPlan):[],[rhythm,editPlan]);
 const beatLen=useMemo(()=>rhythm?beatLength(rhythm):.5,[rhythm]);
 return {doc,catalog,error,saving:saving||importing.current,ready:!!doc,digest:etag.current.replaceAll('"',''),
  snaps,beatLen,uploads,pending:uploads.filter(u=>u.state!=='error'),
  add:(list:File[])=>setUploads(us=>[...us,...list.map(file=>{const key=crypto.randomUUID();files.current.set(key,file);return {key,name:file.name,url:URL.createObjectURL(file),progress:0,state:(current.current&&rhythm?'queued':'waiting') as MediaUpload['state'],video:isVideoFile(file)};})]),
  retry:(key:string)=>setUploads(us=>us.map(u=>u.key===key?{...u,state:(current.current&&rhythm?'queued':'waiting'),progress:0,error:undefined}:u)),
  dismiss:(key:string)=>{setUploads(us=>us.filter(u=>{if(u.key===key){URL.revokeObjectURL(u.url);files.current.delete(key);return false;}return true;}));},
  change,commit,remove,focus,pin,
  undo:()=>{const next=history.past.at(-1);if(next)void commit(next,'undo');},redo:()=>{const next=history.future[0];if(next)void commit(next,'redo');},canUndo:!!history.past.length,canRedo:!!history.future.length};
}
export type MediaEditor=ReturnType<typeof useCustomMedia>;
