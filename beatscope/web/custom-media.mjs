const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
export function normalizeMediaSlot(slot,asset){
 const {offset,...plain}=slot;
 if(asset?.kind!=='video')return plain;
 const length=Math.min(slot.end-slot.start,asset.duration??0);
 return {...plain,end:slot.start+length,offset:clamp(offset??0,0,Math.max(0,(asset.duration??0)-length))};
}
export function arrangeMedia(doc,rhythm,editPlan,reshuffle=false,preferredTime=null){
 const duration=rhythm.source.duration,ids=doc.assets.map(a=>a.id);
 const byId=new Map(doc.assets.map(a=>[a.id,a]));
 // A video slot's offset window must stay inside the clip; clips too short for
 // a kept slot shrink the slot rather than the doc failing validation.
 const heal=s=>normalizeMediaSlot(s,byId.get(s.asset));
 const fixed=doc.slots.filter(s=>s.fixed&&ids.includes(s.asset)&&s.end<=duration).map(heal);
 const beats=(rhythm.beats??[]).map(b=>b.time).filter(Number.isFinite);
 const edges=[0,...(editPlan?.boundaries??[]).map(b=>b.time),duration];
 // Four-beat windows, bounded by authored stages; no invented musical facts.
 for(let i=0;i<beats.length;i+=4)if(beats[i]>0&&beats[i]<duration)edges.push(beats[i]);
 for(const cue of editPlan?.cues??[])if(!cue.deleted&&cue.time>0&&cue.time<duration)edges.push(cue.time);
 edges.sort((a,b)=>a-b);
 const unique=[...new Set(edges)],cells=[];
 for(let i=0;i<unique.length-1;i++)if(unique[i+1]-unique[i]>=1)cells.push({start:unique[i],end:unique[i+1]});
 if(!beats.length&&cells.length===1){cells.length=0;for(let t=0;t<duration;t+=3)if(duration-t>=1)cells.push({start:t,end:Math.min(duration,t+3)});}
 const overlaps=(a,b)=>a.start<b.end&&b.start<a.end;
 let budget=Math.max(0,duration*doc.target-fixed.reduce((n,s)=>n+s.end-s.start,0));
 const slots=[...fixed];
 if(!reshuffle)for(const s of doc.slots){if(!s.fixed&&ids.includes(s.asset)&&cells.some(c=>c.start===s.start&&c.end===s.end)&&!slots.some(p=>overlaps(p,s)||(p.asset===s.asset&&(p.end===s.start||s.end===p.start)))&&s.end-s.start<=budget+1e-6){const h=heal(s);slots.push(h);budget-=h.end-h.start;}}
 const free=cells.filter(c=>!slots.some(s=>overlaps(c,s)));
 let state=doc.seed>>>0;const random=()=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state/2**32;};
 const candidates=free.map(c=>({c,key:random()})).sort((a,b)=>{
  const current=c=>preferredTime!==null&&c.start<=preferredTime&&c.end>preferredTime;
  return Number(current(b.c))-Number(current(a.c))||a.key-b.key;
 });
 for(const {c} of candidates){
  if(c.end-c.start>budget+1e-6)continue;
  const neighbors=slots.filter(s=>Math.abs(s.end-c.start)<1e-6||Math.abs(c.end-s.start)<1e-6).map(s=>s.asset);
  const len=c.end-c.start;
  const choices=ids.filter(id=>!neighbors.includes(id)&&(byId.get(id)?.kind!=='video'||(byId.get(id).duration??0)>=len));if(!choices.length)continue;
  const asset=choices[Math.floor(random()*choices.length)],entry=byId.get(asset);
  const slot={...c,asset,fixed:false};
  if(entry?.kind==='video')slot.offset=Math.round(random()*((entry.duration??len)-len)*30)/30;
  slots.push(slot);budget-=len;
 }
 slots.sort((a,b)=>a.start-b.start);
 return {...doc,slots};
}
export function focusRect(iw,ih,width,height,focus,progress=0){
 const fit=focus?.fit??'cover',zoom=fit==='contain'?1:(focus?.zoom??1)*(1+.035*clamp(progress,0,1));
 const scale=(fit==='contain'?Math.min(width/iw,height/ih)*(.97+.025*clamp(progress,0,1)):Math.max(width/iw,height/ih))*zoom;
 const w=iw*scale,h=ih*scale;
 const x=fit==='contain'?(width-w)/2:clamp(width/2-(focus?.x??.5)*w,width-w,0);
 const y=fit==='contain'?(height-h)/2:clamp(height/2-(focus?.y??.5)*h,height-h,0);
 return {x,y,width:w,height:h};
}
export function mediaRatio(doc,duration){return duration?doc.slots.reduce((n,s)=>n+s.end-s.start,0)/duration:0;}
/* Placement helpers shared by the lane drags and pin(). Snap points are the
   authored structure of the song — beats and edit-plan boundaries — plus its
   edges; the lane never invents musical facts of its own. */
export function snapPoints(rhythm,editPlan){
 const duration=rhythm.source.duration;
 const points=[0,duration,...(rhythm.beats??[]).map(b=>b.time),...(editPlan?.boundaries??[]).map(b=>b.time)];
 return [...new Set(points.filter(t=>Number.isFinite(t)&&t>=0&&t<=duration))].sort((a,b)=>a-b);
}
export function snapTime(t,points){return points.reduce((best,p)=>Math.abs(p-t)<Math.abs(best-t)?p:best,points[0]??t);}
export function beatLength(rhythm){
 const beats=(rhythm.beats??[]).map(b=>b.time).filter(Number.isFinite).sort((a,b)=>a-b),gaps=[];
 for(let i=1;i<beats.length;i++)gaps.push(beats[i]-beats[i-1]);
 if(!gaps.length)return .5;gaps.sort((a,b)=>a-b);return gaps[Math.floor(gaps.length/2)];
}
// Insert a user-pinned slot: the replaced slot and every NON-fixed slot it
// overlaps leave; other pins stay (callers clamp them out via freeRange).
export function placeSlot(doc,slot,replaceKey){
 const {start,end,asset}=slot;
 if(end-start<0.05)return doc;
 const slots=doc.slots.filter(s=>{
  if(replaceKey&&s.start===replaceKey.start&&s.asset===replaceKey.asset)return false;
  if(!s.fixed&&s.start<end&&s.end>start)return false;
  return true;
 });
 const placed={start,end,asset,fixed:true};
 if(slot.offset!=null)placed.offset=slot.offset;
 slots.push(placed);
 slots.sort((a,b)=>a.start-b.start);
 return {...doc,slots};
}
// NLE-style edge resize on a video slot: the right edge is capped by the clip
// tail, the left edge slides the clip window (offset) with the same delta.
export function clipWindow(clip,slot,edge,target,minLen){
 const off=slot.offset??0;
 if(edge==='r')return{start:slot.start,end:clamp(target,slot.start+minLen,slot.start+clip-off),offset:off};
 const o=clamp(off+(target-slot.start),0,Math.max(0,off+(slot.end-slot.start)-minLen));
 return{start:slot.start+(o-off),end:slot.end,offset:o};
}
// Free span around a time, bounded by the neighbouring pins. A pin containing
// `at` counts as occupied, so the free range resumes right after it.
export function freeRange(doc,at,duration,ignoreKey){
 const same=s=>ignoreKey&&s.start===ignoreKey.start&&s.asset===ignoreKey.asset;
 let min=0,max=duration;
 for(const s of doc.slots){
  if(!s.fixed||same(s))continue;
  if(s.start<at&&s.end>at){min=Math.max(min,s.end);continue;}
  if(s.end<=at&&s.end>min)min=s.end;
  if(s.start>=at&&s.start<max)max=s.start;
 }
 return {min,max};
}
// Supply pictures (and video frames) before template composition, so all
// template effects see them. Video slots: export renders pre-extracted JPEG
// frames (deterministic, codec-free); preview keeps a live HTMLVideoElement
// per clip whose current frame is snapshotted into the same bitmap contract.
export function createMediaSource(initial,urls,{preview=false,width=1080,height=1080,aspect='1:1',mediaFrames=null,frameUrl=null}={}){
 const images=new Map(),loading=new Map(),videos=new Map();let document=initial,disposed=false,revision=0;
 const imageLimit=Math.max(6,Math.min(12,Math.floor(64*1024*1024/(width*height*4))));
 const keyFor=asset=>JSON.stringify([asset.id,asset.overrides?.[aspect]??asset.focus]);
 const frameKey=(index,k)=>`v:${index}:${k}`;
 const hitAt=t=>{if(!document)return null;const i=document.slots.findIndex(s=>t>=s.start&&t<s.end);return i<0?null:{slot:document.slots[i],index:i};};
 const slotAt=t=>hitAt(t)?.slot??null;
 const assetAt=t=>{const hit=hitAt(t);return hit&&document.assets.find(a=>a.id===hit.slot.asset);};
 const frameNumber=(hit,t)=>clamp(Math.floor((t-hit.slot.start)*30+1e-6),0,Math.max(0,(mediaFrames?.[hit.index]??0)-1));
 const loadImage=async(asset,key,src)=>{
  const focus=asset.overrides?.[aspect]??asset.focus;
  if(images.has(key)){const im=images.get(key);images.delete(key);images.set(key,im);return im;}
  const response=await fetch(src);if(!response.ok)throw Error('Image missing: '+src);
  const blob=await response.blob(),original=await createImageBitmap(blob);
  let im;
  try{if(focus.fit==='cover'){
   const rect=focusRect(original.width,original.height,width,height,focus,0),scale=rect.width/original.width;
   const sx=Math.floor(-rect.x/scale),sy=Math.floor(-rect.y/scale),sw=Math.min(original.width-sx,Math.ceil(width/scale)),sh=Math.min(original.height-sy,Math.ceil(height/scale));
   im=await createImageBitmap(original,sx,sy,sw,sh,{resizeWidth:width,resizeHeight:height,resizeQuality:'high'});
  }else{
   const limit=Math.max(width,height),scale=Math.min(1,limit/Math.max(original.width,original.height));
   im=scale<1?await createImageBitmap(original,{resizeWidth:Math.max(1,Math.round(original.width*scale)),resizeHeight:Math.max(1,Math.round(original.height*scale)),resizeQuality:'high'}):original;
  }
  }catch(error){original.close();throw error;}
  if(im!==original)original.close();if(disposed){im.close();return null;}
  const result={bitmap:im,focus:{x:.5,y:.5,zoom:1,fit:focus.fit}};
  images.set(key,result);return result;
 };
 const image=(asset,key,src)=>{
  if(loading.has(key))return loading.get(key);
  const promise=loadImage(asset,key,src).finally(()=>loading.delete(key));
  loading.set(key,promise);return promise;
 };
 /* ------- preview: one live element per clip, shared frame contract ------- */
 const nowMs=()=>globalThis.performance?.now()??Date.now();
 const videoFor=asset=>{
  let v=videos.get(asset.id);
  if(v)return v;
  const el=globalThis.document.createElement('video');
  el.muted=true;el.playsInline=true;el.preload='auto';
  v={el,bitmap:null,ready:false,readyP:null,srcP:null,lastT:null,lastAt:0,pauseTimer:0};
  el.addEventListener('loadeddata',()=>{v.ready=true;});
  el.src=urls(asset.clip);
  videos.set(asset.id,v);return v;
 };
 const loadVideo=v=>(v.srcP??Promise.resolve()).then(()=>v.ready?true:v.readyP??=new Promise(resolve=>{let done=false;const fin=ok=>{if(done)return;done=true;resolve(ok);};v.el.addEventListener('loadeddata',()=>fin(true),{once:true});v.el.addEventListener('error',()=>fin(false),{once:true});setTimeout(()=>fin(v.el.readyState>=2),8000);})).catch(()=>false);
 const seekTo=(v,ct)=>new Promise(resolve=>{if(Math.abs(v.el.currentTime-ct)<.02)return resolve();let done=false;const fin=()=>{if(done)return;done=true;v.el.removeEventListener('seeked',fin);resolve();};v.el.addEventListener('seeked',fin);v.el.currentTime=ct;setTimeout(fin,1000);});
 const grab=async(v,asset)=>{
  const el=v.el,vw=el.videoWidth,vh=el.videoHeight;if(!vw||!vh)return;
  const focus=asset.overrides?.[aspect]??asset.focus;
  let bitmap;
  if(focus.fit==='cover'){
   const rect=focusRect(vw,vh,width,height,focus,0),scale=rect.width/vw;
   const sx=Math.max(0,Math.floor(-rect.x/scale)),sy=Math.max(0,Math.floor(-rect.y/scale)),sw=Math.min(vw-sx,Math.ceil(width/scale)),sh=Math.min(vh-sy,Math.ceil(height/scale));
   bitmap=await createImageBitmap(el,sx,sy,sw,sh,{resizeWidth:width,resizeHeight:height});
  }else{
   const limit=Math.max(width,height),scale=Math.min(1,limit/Math.max(vw,vh));
   bitmap=await createImageBitmap(el,{resizeWidth:Math.max(1,Math.round(vw*scale)),resizeHeight:Math.max(1,Math.round(vh*scale))});
  }
  if(disposed){bitmap.close();return;}
  v.bitmap?.close();v.bitmap=bitmap;
 };
 const primeVideo=async(asset,t,primary)=>{
  const v=videoFor(asset);if(!(await loadVideo(v)))throw Error('Preview clip unavailable');
  const hit=primary??hitAt(t);if(!hit||hit.slot.asset!==asset.id)return;
  const ct=Math.max(0,(hit.slot.offset??0)+(t-hit.slot.start)),now=nowMs();
  const continuous=v.lastT!==null&&t-v.lastT>0&&t-v.lastT<.4&&now-v.lastAt<600;
  if(continuous){
   if(v.el.paused){await seekTo(v,ct);await v.el.play().catch(()=>{});}
   else if(Math.abs(v.el.currentTime-ct)>.12)v.el.currentTime=ct;
  }else{
   if(!v.el.paused)v.el.pause();
   await seekTo(v,ct);
  }
  v.lastT=t;v.lastAt=now;
  clearTimeout(v.pauseTimer);v.pauseTimer=setTimeout(()=>v.el.pause(),250);
  await grab(v,asset);
 };
 return {
  get revision(){return revision;},get color(){return document?.color;},has:t=>!!assetAt(t),
  boundaryAt(t){let boundary=0;for(const slot of document?.slots??[]){if(slot.start<=t)boundary=Math.max(boundary,slot.start);if(slot.end<=t)boundary=Math.max(boundary,slot.end);}return boundary;},
  async prepare(times){
   if(!document)return;
   const assets=[...new Map(times.map(assetAt).filter(Boolean).map(a=>[keyFor(a),a])).values()];
   const jobs=[],keepFrames=new Set();
   const primary=hitAt(times[0]),primaryAsset=primary&&document.assets.find(a=>a.id===primary.slot.asset);
   for(const asset of assets){
    if(asset.kind==='video'){
     if(preview){
      const hits=times.map(t=>hitAt(t)).filter(h=>h&&h.slot.asset===asset.id);
      if(primaryAsset===asset)jobs.push(primeVideo(asset,times[0],primary).catch(()=>image(asset,keyFor(asset),urls(asset.proxy??asset.id))));
      else if(hits.length)jobs.push(primeVideo(asset,times.find(t=>hitAt(t)?.slot.asset===asset.id),hits[0]).catch(()=>image(asset,keyFor(asset),urls(asset.proxy??asset.id))));
     }else{
      // Fetch only requested frames; in-flight decodes are shared and retained
      // frames obey the same memory budget as pictures.
      for(const t of times){
       const hit=hitAt(t);if(!hit||hit.slot.asset!==asset.id)continue;
       const k=frameNumber(hit,t),count=mediaFrames?.[hit.index]??0;
       jobs.push(image(asset,frameKey(hit.index,k),frameUrl(hit.index,k)));
       if(count)keepFrames.add(frameKey(hit.index,k));
      }
     }
    }else jobs.push(image(asset,keyFor(asset),urls(preview?(asset.proxy??asset.id):asset.id)));
   }
   await Promise.all(jobs);
   const keep=new Set(assets.map(keyFor));
   for(const [id,v]of videos)if(!assets.some(a=>a.id===id)){
    clearTimeout(v.pauseTimer);v.el.pause();v.bitmap?.close();v.el.removeAttribute('src');v.el.load();videos.delete(id);
   }
   for(const [key,im]of images){
    if(images.size<=imageLimit)break;
    const protectedKey=key.startsWith('v:')?keepFrames.has(key):keep.has(key);
    if(!protectedKey){im.bitmap.close();images.delete(key);}
   }
  },
  at(t){const hit=hitAt(t);if(!hit)return null;const asset=document.assets.find(a=>a.id===hit.slot.asset);if(!asset)return null;
   const focus=asset.overrides?.[aspect]??asset.focus;
   if(asset.kind==='video'){
    if(preview){
     const v=videos.get(asset.id);
     if(v?.bitmap)return {bitmap:v.bitmap,focus:{x:.5,y:.5,zoom:1,fit:focus.fit},progress:0};
     const poster=images.get(keyFor(asset));
     if(poster)return {...poster,progress:0};
     throw Error('Template frame was not prepared');
    }
    const prepared=images.get(frameKey(hit.index,frameNumber(hit,t)));
    if(!prepared)throw Error('Template frame was not prepared');
    return {...prepared,progress:0};
   }
   const prepared=images.get(keyFor(asset));if(!prepared)throw Error('Template image was not prepared');
   return {...prepared,progress:clamp((t-hit.slot.start)/(hit.slot.end-hit.slot.start),0,1)};
  },
  set(doc){document=doc;revision++;},
  dispose(){disposed=true;for(const im of images.values())im.bitmap.close();images.clear();for(const v of videos.values()){clearTimeout(v.pauseTimer);v.el.pause();if(v.el.src.startsWith('blob:'))URL.revokeObjectURL(v.el.src);v.el.src='';v.bitmap?.close();}videos.clear();}
 };
}
export async function attachMedia(canvas,baseCanvas,baseRender,mediaSource){
 const ctx=canvas.getContext('2d');let pending=null,disposed=false,queue=Promise.resolve(),lastTime=null,transition=null;
 const draw=async time=>{
  const t=Math.round(time*30)/30;
  if(disposed)return;if(pending&&t>=pending.at){
   transition=null;
   if(pending.animate&&t-pending.at<.12){const snapshot=globalThis.document.createElement('canvas');snapshot.width=canvas.width;snapshot.height=canvas.height;snapshot.getContext('2d').drawImage(canvas,0,0);transition={snapshot,at:pending.at};}
   mediaSource.set(pending.document);baseRender.invalidate?.();pending=null;lastTime=null;
  }
  if(lastTime===t)return;
  await baseRender(t);if(disposed)return;
  globalThis.__framesDrawn=(globalThis.__framesDrawn||0)+1;
  ctx.setTransform(1,0,0,1,0,0);ctx.globalAlpha=1;
  ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(baseCanvas,0,0);
  if(transition){const age=t-transition.at;if(age<0||age>=.12)transition=null;else{ctx.save();ctx.globalAlpha=1-age/.12;ctx.drawImage(transition.snapshot,0,0);ctx.restore();}}
  lastTime=t;
 };
 const render=t=>{queue=queue.catch(()=>{}).then(()=>draw(t));return queue;};
 let wanted=null,pump=null;
 render.preview=t=>{wanted=t;if(!pump)pump=(async()=>{while(wanted!==null&&!disposed){const at=wanted;wanted=null;await render(at);}})().finally(()=>{pump=null;});return pump;};
 render.setMedia=(doc,at,animate=false)=>{pending={document:doc,at:Math.round(at*30)/30,animate};};
 render.acceleration=baseRender.acceleration;
 render.dispose=()=>{disposed=true;baseRender.dispose?.();mediaSource.dispose();};
 return render;
}
