import {useEffect,useId,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {mediaRatio,placeSlot,freeRange,snapTime,clipWindow,type Focus,type MediaAsset,type MediaDocument,type MediaSlot} from '../../../beatscope/web/custom-media.mjs';
import type {MediaEditor} from './useCustomMedia';
import {overviewAxis} from './CueMap';
import './media-panel.css';

const paths={undo:'M9 14 4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11',redo:'m15 14 5-5-5-5M20 9H9.5a5.5 5.5 0 0 0 0 11H13',shuffle:'M16 3h5v5M21 3 4 20M21 16v5h-5M15 15l6 6M4 4l5 5',close:'M6 6l12 12M18 6 6 18',plus:'M12 6v12M6 12h12',left:'m14 6-6 6 6 6',right:'m10 6 6 6-6 6',check:'m4.5 12.5 5 5L19.5 7'};
const pinPath='M8 1.5A3.5 3.5 0 0 0 4.5 5C4.5 7.8 8 12.4 8 12.4S11.5 7.8 11.5 5A3.5 3.5 0 0 0 8 1.5zm0 4.7a1.2 1.2 0 1 1 0-2.4 1.2 1.2 0 0 1 0 2.4z';
function Icon({d,size=14}:{d:string;size?:number}){return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d}/></svg>;}
const IMAGE=/^image\/(png|jpeg|webp)$/,VIDEO=/^video\/(mp4|quicktime|webm|x-m4v)$/,VIDEO_EXT=/\.(mp4|mov|m4v|webm)$/i;
const takes=(file:File)=>IMAGE.test(file.type)||VIDEO.test(file.type)||VIDEO_EXT.test(file.name);
const FALLBACK_AXIS={l:`${124/1560*100}%`,r:`${18/1560*100}%`};
const clamp=(x:number,a:number,b:number)=>Math.max(a,Math.min(b,x));
const clamp01=(x:number)=>clamp(x,0,1);
const mmss=(t:number)=>`${Math.floor(t/60)}:${(t%60).toFixed(1).padStart(4,'0')}`;
const mmss0=(t:number)=>`${Math.floor(t/60)}:${Math.round(t%60).toString().padStart(2,'0')}`;
const MAC=typeof navigator!=='undefined'&&/mac/i.test((navigator as {userAgentData?:{platform?:string}}).userAgentData?.platform??navigator.platform??'');
const capture=(el:HTMLElement,e:React.PointerEvent)=>{try{el.setPointerCapture(e.pointerId);}catch{/* synthetic pointer ids have no capture */}};
const COLLAPSE_KEY='beathi.media.collapsed';
type SlotKey={start:number;asset:string};
type Ghost={id:string;url:string;x:number;y:number;ret?:{x:number;y:number}};
type SlotDrag={s:MediaSlot;mode:'move'|'l'|'r';x0:number;rect:DOMRect;moved:boolean;cur:{start:number;end:number;offset?:number}};
type ThumbDrag={a:MediaAsset;pid:number;x0:number;y0:number;started:boolean;timer?:ReturnType<typeof setTimeout>};

const useClipSrc=(clip:string|undefined,projectId:string|undefined)=>{
 // Native video seeks use byte ranges; no full-file blob or global cache.
 return clip&&projectId?`/api/projects/${projectId}/assets/${clip}`:'';
};
const HoverVideo=({clip,projectId}:{clip:string;projectId?:string})=>{
 const u=useClipSrc(clip,projectId);
 return u?<video className="media-hover-vid" src={u} autoPlay muted loop playsInline/>:null;
};
export function MediaPanel({media,projectId,lang,duration,time,aspect,disabled,beatPulse,seek,onPreview}:{media:MediaEditor;projectId?:string;lang:string;duration:number;time:number;aspect:string;disabled:boolean;beatPulse:boolean;seek:(t:number)=>void;onPreview:(doc:MediaDocument|null)=>void}){
 const picker=useRef<HTMLInputElement>(null),lane=useRef<HTMLDivElement>(null),axis=useRef<HTMLDivElement>(null);
 const [selected,setSelected]=useState(''),[selectedSlot,setSelectedSlot]=useState<SlotKey|null>(null),[message,setMessage]=useState('');
 const zh=lang==='zh',doc=media.doc,asset=doc?.assets.find(a=>a.id===selected);
 const [draft,setDraft]=useState<Focus|null>(null),[scope,setScope]=useState<'all'|'aspect'>('all'),[savedFlash,setSavedFlash]=useState(false);
 const [coverDraft,setCoverDraft]=useState<number|null>(null);
 const [colorDraft,setColorDraft]=useState<number|null>(null);
 const [pressId,setPressId]=useState('');
 const [ghost,setGhost]=useState<Ghost|null>(null);
 const [preview,setPreview]=useState<{start:number;end:number;asset:string}|null>(null);
 const [slotCur,setSlotCur]=useState<{key:SlotKey;start:number;end:number;offset?:number}|null>(null);
 const [laneDrop,setLaneDrop]=useState(false),[zoneDrag,setZoneDrag]=useState(false);
 const [hoverVid,setHoverVid]=useState(''),[scrubOff,setScrubOff]=useState<number|null>(null);
 const [toast,setToast]=useState<{text:string;at:number;key:number}|null>(null);
 const [inspectorMax,setInspectorMax]=useState(320);
 const bodyId=useId();
 const [collapsed,setCollapsed]=useState(()=>{try{return localStorage.getItem(COLLAPSE_KEY)==='1';}catch{return false;}});
 const panelRef=useRef<HTMLElement>(null);
 const inspectorOpen=!!(doc&&asset);
 const selSlot=selectedSlot&&doc?doc.slots.find(x=>x.start===selectedSlot.start&&x.asset===selectedSlot.asset):undefined;
 const scrub=selSlot&&asset?.kind==='video'&&selSlot.asset===asset.id?selSlot:null;
 const clipDur=asset?.duration??0;
 const focus=asset?(scope==='aspect'?(asset.overrides[aspect]??asset.focus):asset.focus):undefined;
 const value=draft??focus;
 const points=media.snaps,beatLen=media.beatLen;
 // Drag bookkeeping lives in refs; state mirrors only what the render needs.
 const slotRef=useRef<SlotDrag|null>(null);
 const thumbRef=useRef<ThumbDrag|null>(null);
 const markerRef=useRef<DOMRect|null>(null);
 const suppressUntil=useRef(0),pendingDoc=useRef<MediaDocument|null>(null),rafRef=useRef(0);
 const zoomTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),saveTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
 const toastTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),toastLeft=useRef(5000),toastEnd=useRef(0);
 // The lane's time axis must coincide with the CueMap overview's grid, whose
 // canvases fit-centre (fitCanvas) rather than stretch. Measure the overview
 // canvas directly; until it mounts, fall back to the ideal 124/1560·18/1560.
 const [insets,setInsets]=useState(FALLBACK_AXIS);
 useLayoutEffect(()=>{
  const el=lane.current;if(!el)return;
  let canvas:HTMLCanvasElement|null=null;
  const set=(l:string,r:string)=>setInsets(prev=>prev.l===l&&prev.r===r?prev:{l,r});
  const measure=()=>{
   if(!canvas||!canvas.isConnected)canvas=document.querySelector<HTMLCanvasElement>('.cm-stack-overview canvas');
   if(canvas&&canvas.clientWidth>0&&canvas.clientHeight>0){
    const laneRect=el.getBoundingClientRect(),cv=canvas.getBoundingClientRect(),a=overviewAxis(canvas.clientWidth,canvas.clientHeight),pl=laneRect.left+el.clientLeft;
    set(`${cv.left+a.left-pl}px`,`${pl+el.clientWidth-(cv.right-a.right)}px`);
   }else set(FALLBACK_AXIS.l,FALLBACK_AXIS.r);
  };
  const ro=new ResizeObserver(measure);
  ro.observe(el);
  const attach=()=>{const c=document.querySelector<HTMLCanvasElement>('.cm-stack-overview canvas');if(c&&c!==canvas){canvas=c;ro.observe(c);}};
  const mo=new MutationObserver(()=>{attach();measure();});
  mo.observe(document.body,{childList:true,subtree:true});
  window.addEventListener('resize',measure);
  attach();measure();
  return()=>{ro.disconnect();mo.disconnect();window.removeEventListener('resize',measure);};
 },[!!doc?.assets.length]);
 const actual=doc?mediaRatio(doc,duration):0;
 const target=coverDraft??(doc?doc.target*100:0);
 const over=!!doc&&actual>doc.target+.001;
 useEffect(()=>{if(!message)return;const t=setTimeout(()=>setMessage(''),2400);return()=>clearTimeout(t);},[message]);
 useEffect(()=>setCoverDraft(null),[doc?.target]);
 useEffect(()=>setColorDraft(null),[doc?.color?.strength,doc?.color?.enabled]);
 // A commit while a toast is open belongs to that toast; the next one hides it.
 const lastDoc=useRef(doc),countRef=useRef(0),toastRef=useRef(toast);toastRef.current=toast;
 useEffect(()=>{if(doc===lastDoc.current)return;lastDoc.current=doc;countRef.current++;if(toastRef.current&&countRef.current-toastRef.current.at>=2)setToast(null);},[doc]);
 useEffect(()=>{if(!toast)return;toastLeft.current=5000;toastEnd.current=Date.now()+5000;toastTimer.current=setTimeout(()=>setToast(null),5000);return()=>clearTimeout(toastTimer.current);},[toast?.key]);
 useEffect(()=>{if(!ghost?.ret)return;const t=setTimeout(()=>setGhost(null),190);return()=>clearTimeout(t);},[ghost?.ret]);
 // Inspector state resets whenever another image opens.
 useEffect(()=>{setScope(asset?.overrides[aspect]?'aspect':'all');setDraft(null);onPreview(null);},[selected,aspect]);
 // A selected slot that a commit reshaped away stops being selected.
 useEffect(()=>{if(selectedSlot&&doc&&!doc.slots.some(x=>x.start===selectedSlot.start&&x.asset===selectedSlot.asset))setSelectedSlot(null);},[doc]);
 // The inspector is bottom-anchored; cap its height by the space that actually
 // remains above the panel (minus the topbar), re-measured on resize/scroll.
 useLayoutEffect(()=>{
  if(!inspectorOpen)return;
  const measure=()=>{const panel=panelRef.current,bar=document.querySelector('.topbar');if(!panel)return;setInspectorMax(Math.max(96,panel.getBoundingClientRect().top-16-Math.max(0,bar?.getBoundingClientRect().bottom??0)));};
  measure();window.addEventListener('resize',measure);
  const shell=panelRef.current?.closest('.mv-shell');shell?.addEventListener('scroll',measure,{passive:true});
  return()=>{window.removeEventListener('resize',measure);shell?.removeEventListener('scroll',measure);};
 },[inspectorOpen]);
 // The inspector video shows the frame at the slot's offset (draft while
 // scrubbing); poster-fallback happens visually via the paused first frame.
 const clipTime=(scrubOff??selSlot?.offset)??0;
 useEffect(()=>{
  const el=clipRef.current;if(!el||asset?.kind!=='video')return;
  const set=()=>{el.currentTime=Math.min(Math.max(0,clipTime),Math.max(0,clipDur-.05));};
  if(el.readyState>=1)set();else el.addEventListener('loadedmetadata',set,{once:true});
 },[clipTime,asset?.clip,clipDur]);
 useEffect(()=>{setScrubOff(null);},[selectedSlot?.start,selectedSlot?.asset]);
 const toastIt=(text:string)=>setToast({text,at:countRef.current,key:Date.now()});
 const busy=disabled||media.saving;
 const url=(id:string)=>`/api/projects/${projectId}/assets/${doc?.assets.find(a=>a.id===id)?.proxy??id}`;
 const assetOf=(id:string)=>doc?.assets.find(a=>a.id===id);
 const durOf=(id:string)=>assetOf(id)?.duration??0;
 const clipRef=useRef<HTMLVideoElement>(null),scrubRef=useRef<HTMLDivElement>(null),scrubDrag=useRef<{x0:number;anchor:number;rect:DOMRect}|null>(null);
 const canHover=useMemo(()=>typeof matchMedia==='function'&&matchMedia('(hover:hover)').matches&&!matchMedia('(prefers-reduced-motion: reduce)').matches,[]);
 const clipSrc=useClipSrc(asset?.kind==='video'?asset.clip:undefined,projectId);
 const choose=(id:string)=>{setSelected(id);setDraft(null);};
 const pick=(a:MediaAsset)=>{
  choose(a.id);if(!doc)return;
  const own=doc.slots.filter(s=>s.asset===a.id).sort((x,y)=>x.start-y.start),next=own.find(s=>s.start>=time-.001)??own[0];
  if(next)seek(next.start+.001);
 };
 const reorder=(delta:number)=>{if(!doc||!asset)return;const i=doc.assets.indexOf(asset),j=i+delta;if(j<0||j>=doc.assets.length)return;const assets=[...doc.assets];[assets[j],assets[i]]=[assets[i],assets[j]];let n=0;const slots=doc.slots.map(s=>s.fixed?s:{...s,asset:assets[n++%assets.length].id});media.change({...doc,assets,slots});};
 const addFiles=(files:FileList)=>{const list=Array.from(files).filter(takes);if(list.length)media.add(list);};
 const zoneDrop=(event:React.DragEvent<HTMLElement>)=>{event.preventDefault();setZoneDrag(false);setLaneDrop(false);if(!disabled)addFiles(event.dataTransfer.files);};
 const zoneOver=(event:React.DragEvent<HTMLElement>)=>{event.preventDefault();setZoneDrag(!disabled);};
 const laneFileOver=(event:React.DragEvent<HTMLDivElement>)=>{if(!event.dataTransfer.types.includes('Files'))return;event.preventDefault();setLaneDrop(!disabled);};
 const removeSlot=(s:MediaSlot)=>{if(!doc)return;media.change({...doc,slots:doc.slots.filter(x=>x!==s)});toastIt(zh?'已删除槽位':'Removed the slot');};
 const unpinSlot=(s:MediaSlot)=>{if(!doc)return;media.change({...doc,slots:doc.slots.map(x=>x===s?{...x,fixed:false}:x)});toastIt(zh?'已取消固定':'Unpinned');};
 const removeImage=(id:string)=>{media.remove(id);toastIt(zh?'已删除 1 个素材':'Removed 1 media item');if(selected===id)setSelected('');setSelectedSlot(k=>k?.asset===id?null:k);};
 const cancelDrags=()=>{
  const d=thumbRef.current;if(d?.timer)clearTimeout(d.timer);
  slotRef.current=null;setSlotCur(null);thumbRef.current=null;setPressId('');setPreview(null);setLaneDrop(false);
  setGhost(g=>g&&!g.ret?{...g,ret:{x:d?d.x0:g.x,y:d?d.y0:g.y}}:g);
  if(markerRef.current){markerRef.current=null;setDraft(null);onPreview(null);}
  if(scrubDrag.current){scrubDrag.current=null;pendingDoc.current=null;setScrubOff(null);onPreview(null);}
 };
 useEffect(()=>{const h=(e:KeyboardEvent)=>{if(e.key==='Escape'&&(slotRef.current||thumbRef.current||markerRef.current||scrubDrag.current))cancelDrags();};window.addEventListener('keydown',h);return()=>window.removeEventListener('keydown',h);});
 /* ---------- lane slots: pointer drag to move/resize ---------- */
 const slotDown=(e:React.PointerEvent<HTMLButtonElement>,s:MediaSlot)=>{
  if(busy||e.button!==0||!axis.current)return;
  const handle=(e.target as HTMLElement).closest('.media-handle');
  capture(e.currentTarget as HTMLElement,e);
  slotRef.current={s,mode:handle?.classList.contains('l')?'l':handle?'r':'move',x0:e.clientX,rect:axis.current.getBoundingClientRect(),moved:false,cur:{start:s.start,end:s.end}};
 };
 const slotMove=(e:React.PointerEvent<HTMLButtonElement>)=>{
  const d=slotRef.current;if(!d||!doc)return;
  if(!d.moved){if(Math.abs(e.clientX-d.x0)<3)return;d.moved=true;}
  const dx=(e.clientX-d.x0)/d.rect.width*duration,to=e.altKey?(v:number)=>Math.round(v*30)/30:(v:number)=>snapTime(v,points);
  const len=d.s.end-d.s.start,r=freeRange(doc,d.s.start,duration,{start:d.s.start,asset:d.s.asset});
  const clip=durOf(d.s.asset);
  let start=d.s.start,end=d.s.end,offset=d.s.offset;
  if(d.mode==='move'){start=clamp(to(d.s.start+dx),r.min,Math.max(r.min,r.max-len));end=start+len;}
  else if(d.mode==='l'){
   // NLE trim: the left edge slides the clip window, not just the slot.
   const next=clamp(to(d.s.start+dx),r.min,d.s.end-beatLen);
   if(clip){const w=clipWindow(clip,d.s,'l',next,beatLen);start=w.start;offset=w.offset;}
   else start=next;
  }
  else{const next=clamp(to(d.s.end+dx),d.s.start+beatLen,r.max);if(clip)end=clipWindow(clip,d.s,'r',next,beatLen).end;else end=next;}
  d.cur={start,end,offset};setSlotCur({key:{start:d.s.start,asset:d.s.asset},start,end,offset});
 };
 const slotUp=()=>{
  const d=slotRef.current;slotRef.current=null;
  if(d?.moved&&doc)media.change(placeSlot(doc,{start:d.cur.start,end:d.cur.end,asset:d.s.asset,...(d.cur.offset!=null?{offset:d.cur.offset}:{})},{start:d.s.start,asset:d.s.asset}));
  if(d?.moved)suppressUntil.current=performance.now()+150;
  setSlotCur(null);
 };
 const slotCancel=()=>{slotRef.current=null;setSlotCur(null);};
 const slotKey=(e:React.KeyboardEvent<HTMLElement>,s:MediaSlot)=>{
  if(!doc)return;
  const key={start:s.start,asset:s.asset},r=freeRange(doc,s.start,duration,key);
  if(e.key==='ArrowLeft'||e.key==='ArrowRight'){
   e.preventDefault();e.stopPropagation();
   const dir=e.key==='ArrowLeft'?-1:1;
   if(e.shiftKey){
    const cands=points.filter(p=>dir>0?p>s.end+.001:p<s.end-.001),end=dir>0?cands[0]:cands.at(-1),clip=durOf(s.asset);
    if(end!=null){const cap=clip?s.start+clip-(s.offset??0):r.max;media.change(placeSlot(doc,{start:s.start,end:clamp(end,s.start+beatLen,Math.min(cap,r.max)),asset:s.asset,...(s.offset!=null?{offset:s.offset}:{})},key));}
   }else{
    const cands=points.filter(p=>dir>0?p>s.start+.001:p<s.start-.001),len=s.end-s.start,raw=dir>0?cands[0]:cands.at(-1);
    if(raw!=null){const start=clamp(raw,r.min,Math.max(r.min,r.max-len));media.change(placeSlot(doc,{start,end:start+len,asset:s.asset,...(s.offset!=null?{offset:s.offset}:{})},key));}
   }
  }else if(e.key==='Delete'||e.key==='Backspace'){
   if(s.fixed){e.preventDefault();e.stopPropagation();removeSlot(s);}
  }
 };
 /* ---------- thumbnails: pointer drag onto the lane ---------- */
 const startThumbDrag=(x:number,y:number)=>{
  const d=thumbRef.current;if(!d||d.started)return;d.started=true;setPressId('');setHoverVid('');
  setGhost({id:d.a.id,url:url(d.a.id),x,y});
 };
 const thumbDown=(e:React.PointerEvent<HTMLElement>,a:MediaAsset)=>{
  if(busy||e.button!==0||(e.target as HTMLElement).closest('.media-delete'))return;
  capture(e.currentTarget as HTMLElement,e);
  const d:ThumbDrag={a,pid:e.pointerId,x0:e.clientX,y0:e.clientY,started:false};
  thumbRef.current=d;
  if(e.pointerType!=='mouse'){setPressId(a.id);d.timer=setTimeout(()=>startThumbDrag(d.x0,d.y0),350);}
 };
 const thumbMove=(e:React.PointerEvent<HTMLElement>)=>{
  const d=thumbRef.current;if(!d||d.pid!==e.pointerId)return;
  if(!d.started){
   const dist=Math.hypot(e.clientX-d.x0,e.clientY-d.y0);
   if(e.pointerType==='mouse'){if(dist>4)startThumbDrag(e.clientX,e.clientY);}
   else if(dist>8){clearTimeout(d.timer);setPressId('');thumbRef.current=null;}
   return;
  }
  e.preventDefault();
  setGhost(g=>g?{...g,x:e.clientX,y:e.clientY}:g);
  const hit=lane.current?.getBoundingClientRect(),box=axis.current?.getBoundingClientRect();
  if(hit&&box&&e.clientX>=hit.left-16&&e.clientX<=hit.right+16&&e.clientY>=hit.top-24&&e.clientY<=hit.bottom+24&&doc){
   const t=clamp01((e.clientX-box.left)/box.width)*duration,start0=snapTime(t,points),clip=d.a.kind==='video'?(d.a.duration??0):0,len=clip?Math.min(4*beatLen,clip):4*beatLen,r=freeRange(doc,start0,duration);
   if(r.max-r.min>=.05){const start=clamp(start0,r.min,Math.max(r.min,r.max-len));setPreview({start,end:Math.min(start+len,r.max),asset:d.a.id});}
   else setPreview(null);
  }else setPreview(null);
 };
 const thumbDone=(commit:boolean)=>{
  const d=thumbRef.current;thumbRef.current=null;setPressId('');
  if(!d?.started)return;
  suppressUntil.current=performance.now()+150;
  if(commit&&preview&&doc){media.change(placeSlot(doc,{start:preview.start,end:preview.end,asset:d.a.id,...(d.a.kind==='video'?{offset:0}:{})}));setMessage(zh?'已吸附到拍点 / 段落边界':'Snapped to beat / stage boundary');}
  setPreview(null);setLaneDrop(false);
  setGhost(g=>g&&!g.ret?{...g,ret:{x:d.x0,y:d.y0}}:g);
 };
 /* ---------- live preview drafts (focus marker, zoom, clip offset) ---------- */
 const queueDoc=(d:MediaDocument|null)=>{pendingDoc.current=d;if(rafRef.current)return;rafRef.current=requestAnimationFrame(()=>{rafRef.current=0;const p=pendingDoc.current;pendingDoc.current=null;onPreview(p);});};
 const withFocus=(v:Focus):MediaDocument|null=>doc&&asset?{...doc,assets:doc.assets.map(a=>a.id!==asset.id?a:scope==='aspect'?{...a,overrides:{...a.overrides,[aspect]:v}}:{...a,focus:v})}:null;
 const withOffset=(slot:MediaSlot,off:number):MediaDocument|null=>doc?{...doc,slots:doc.slots.map(s=>s===slot?{...s,offset:off}:s)}:null;
 const commitFocus=(v:Focus)=>{if(!asset)return;clearTimeout(zoomTimer.current);pendingDoc.current=null;media.focus(asset.id,v,scope==='aspect'?aspect:undefined);setDraft(null);onPreview(null);setSavedFlash(true);clearTimeout(saveTimer.current);saveTimer.current=setTimeout(()=>setSavedFlash(false),1200);};
 const markerSet=(e:React.PointerEvent<HTMLElement>)=>{
  const box=markerRef.current;if(!box||!value)return;
  const v={...value,x:clamp01((e.clientX-box.left)/box.width),y:clamp01((e.clientY-box.top)/box.height)};
  setDraft(v);queueDoc(withFocus(v));
 };
 const markerDown=(e:React.PointerEvent<HTMLElement>)=>{if(busy||e.button!==0||!value||value.fit==='contain')return;markerRef.current=e.currentTarget.getBoundingClientRect();capture(e.currentTarget as HTMLElement,e);markerSet(e);};
 const markerMove=(e:React.PointerEvent<HTMLElement>)=>{if(markerRef.current)markerSet(e);};
 const markerUp=()=>{if(!markerRef.current)return;markerRef.current=null;if(draft)commitFocus(draft);};
 const markerCancel=()=>{if(!markerRef.current)return;markerRef.current=null;pendingDoc.current=null;setDraft(null);onPreview(null);};
 /* ---------- clip offset scrubber ---------- */
 const scrubDown=(e:React.PointerEvent<HTMLElement>)=>{
  if(busy||e.button!==0||!scrub||!scrubRef.current)return;
  const rect=scrubRef.current.getBoundingClientRect(),pos=clamp01((e.clientX-rect.left)/rect.width)*clipDur,len=scrub.end-scrub.start,off=scrubOff??(scrub.offset??0);
  capture(e.currentTarget as HTMLElement,e);
  scrubDrag.current={x0:e.clientX,anchor:pos>=off&&pos<=off+len?pos-off:len/2,rect};
 };
 const scrubMove=(e:React.PointerEvent<HTMLElement>)=>{
  const d=scrubDrag.current;if(!d||!scrub)return;
  e.preventDefault();
  const pos=clamp01((e.clientX-d.rect.left)/d.rect.width)*clipDur,len=scrub.end-scrub.start;
  const off=clamp(Math.round((pos-d.anchor)*30)/30,0,Math.max(0,clipDur-len));
  setScrubOff(off);queueDoc(withOffset(scrub,off));
 };
 const scrubUp=()=>{
  const d=scrubDrag.current;scrubDrag.current=null;if(!d||!scrub||!doc||scrubOff==null)return;
  const off=scrubOff;setScrubOff(null);pendingDoc.current=null;onPreview(null);
  media.change(placeSlot(doc,{start:scrub.start,end:scrub.end,asset:scrub.asset,offset:off},{start:scrub.start,asset:scrub.asset}));
 };
 const scrubCancel=()=>{if(!scrubDrag.current)return;scrubDrag.current=null;pendingDoc.current=null;setScrubOff(null);onPreview(null);};
 const useDefault=()=>{if(!doc||!asset)return;
  media.change({...doc,assets:doc.assets.map(a=>a.id!==asset.id?a:{...a,overrides:Object.fromEntries(Object.entries(a.overrides).filter(([k])=>k!==aspect))})});
  setScope('all');setDraft(null);onPreview(null);
 };
 /* ---------- shortcuts, all inside the panel ---------- */
 const closeInspector=()=>{setSelected('');setDraft(null);onPreview(null);};
 const setPanelCollapsed=(next:boolean)=>{setCollapsed(next);try{localStorage.setItem(COLLAPSE_KEY,next?'1':'0');}catch{/* preference only */}};
 const toggleCollapsed=()=>{if(!collapsed){cancelDrags();closeInspector();setHoverVid('');}setPanelCollapsed(!collapsed);};
 const openPicker=()=>{setPanelCollapsed(false);picker.current?.click();};
 const sectionKey=(e:React.KeyboardEvent<HTMLElement>)=>{
  const tag=e.target as HTMLElement;
  if(tag.matches('input:not([type="range"]),select,textarea'))return;
  const mod=e.ctrlKey||e.metaKey;
  if(mod&&e.key.toLowerCase()==='z'){e.preventDefault();if(e.shiftKey)media.redo();else media.undo();return;}
  if(mod&&e.key.toLowerCase()==='y'){e.preventDefault();media.redo();return;}
  if(e.key==='Escape'){e.preventDefault();
   if(slotRef.current||thumbRef.current||markerRef.current||scrubDrag.current)cancelDrags();
   else if(inspectorOpen)closeInspector();
   else setSelectedSlot(null);
   return;}
  if(tag.matches('input[type="range"]')||tag.closest('.media-axis > button'))return;
  if((e.key==='Delete'||e.key==='Backspace')&&doc){
   if(selectedSlot){const s=doc.slots.find(x=>x.start===selectedSlot.start&&x.asset===selectedSlot.asset);if(s?.fixed){e.preventDefault();removeSlot(s);}return;}
   const tile=tag.closest('.media-thumb');const id=tile?.getAttribute('data-asset');
   if(id){e.preventDefault();removeImage(id);}
  }
 };
 const dragLabel=()=>{
  const d=slotRef.current,c=slotCur??preview;
  if(!c)return null;
  const rect=d?d.rect:axis.current?.getBoundingClientRect();if(!rect)return null;
  const mid=(c.start+c.end)/2,x=rect.left+mid/duration*rect.width;
  return <b className="media-float-label" style={{left:x,top:rect.top-8}}>{mmss(c.start)} – {mmss(c.end)} · {Math.max(1,Math.round((c.end-c.start)/beatLen))}{zh?' 拍':' beats'}</b>;
 };
 return <section className={`media-panel${collapsed?' collapsed':''}`} aria-label={zh?'自定义素材':'Custom media'} onKeyDown={sectionKey} ref={panelRef}>
  <header className="media-head">
   <div className="media-title">
    <h2>{zh?'素材':'Media'}</h2>
    <span className="media-count">{doc?.assets.length??0}</span>
    {doc&&<span className="media-meta">{zh?`占比 ≤ ${Math.round(target)}% · 实际 ${Math.round(actual*100)}%`:`≤ ${Math.round(target)}% · actual ${Math.round(actual*100)}%`}{over&&<b className="over">{zh?' 超出目标':' over target'}</b>}</span>}
    {doc&&<label className="media-coverage"><span>{zh?'占比上限':'Coverage'}</span><input className="media-range" aria-label={zh?'素材占比上限':'Image coverage target'} type="range" min="0" max="100" value={Math.round(target)} style={{'--fill':`${target}%`} as React.CSSProperties} disabled={busy} onChange={e=>setCoverDraft(Number(e.currentTarget.value))} onPointerUp={e=>{media.change({...doc,target:Number(e.currentTarget.value)/100});setCoverDraft(null);}} onKeyUp={e=>{media.change({...doc,target:Number(e.currentTarget.value)/100});setCoverDraft(null);}}/></label>}
   </div>
   <div className="media-toolbar">
    <button className="btn-ink" disabled={busy} onClick={openPicker}>{zh?'+ 添加素材':'+ Media'}</button>
    <input hidden ref={picker} type="file" multiple accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm,.mov,.m4v" onChange={e=>{media.add(Array.from(e.target.files??[]));e.target.value='';}}/>
    <i className="media-divider"/>
    <button className="media-icon" title={zh?'撤销 (Ctrl+Z)':`Undo (${MAC?'⌘Z':'Ctrl+Z'})`} aria-label={zh?'撤销':'Undo'} disabled={busy||!media.canUndo} onClick={media.undo}><Icon d={paths.undo}/></button>
    <button className="media-icon" title={zh?'重做 (Ctrl+Shift+Z)':`Redo (${MAC?'⌘⇧Z':'Ctrl+Shift+Z'})`} aria-label={zh?'重做':'Redo'} disabled={busy||!media.canRedo} onClick={media.redo}><Icon d={paths.redo}/></button>
    <button className="media-icon" title={zh?'随机未固定素材':'Shuffle unpinned'} aria-label={zh?'随机未固定素材':'Shuffle unpinned'} disabled={busy||!doc} onClick={()=>{if(!doc)return;media.change({...doc,seed:(doc.seed+1)%2**24},true);toastIt(zh?'已随机重排':'Shuffled');}}><Icon d={paths.shuffle}/></button>
    <span className="media-status" role="status"><i className={`media-save-dot${media.saving?' saving':''}`}/>{media.saving?(zh?'正在保存…':'Saving…'):message}</span>
    <button className="media-icon media-toggle" aria-expanded={!collapsed} aria-controls={bodyId} aria-label={collapsed?(zh?'展开素材面板':'Expand media panel'):(zh?'收起素材面板':'Collapse media panel')} title={collapsed?(zh?'展开素材面板':'Expand media panel'):(zh?'收起素材面板':'Collapse media panel')} onClick={toggleCollapsed}><Icon d={collapsed?'m6 9 6 6 6-6':'m6 15 6-6 6 6'} size={13}/></button>
   </div>
   {toast&&<div className="media-toast" role="status" onMouseEnter={()=>{clearTimeout(toastTimer.current);toastLeft.current=Math.max(0,toastEnd.current-Date.now());}} onMouseLeave={()=>{toastEnd.current=Date.now()+toastLeft.current;toastTimer.current=setTimeout(()=>setToast(null),toastLeft.current);}}>
    <span>{toast.text}</span>
    <button aria-label={`${zh?'撤销':'Undo'}: ${toast.text}`} onClick={()=>{media.undo();}}>{zh?'撤销':'Undo'}</button>
   </div>}
  </header>
  <div className="cm-body media-body" id={bodyId} inert={collapsed}>
   <div className="cm-body-inner media-body-inner">
  {doc&&<div className="media-color-controls">
   <label><input type="checkbox" checked={doc.color?.enabled??false} disabled={busy} onChange={e=>void media.commit({...doc,color:{enabled:e.currentTarget.checked,strength:doc.color?.strength??.5}})}/><span>{zh?'跟随场景配色':'Follow scene palette'}</span></label>
   {doc.color?.enabled&&<label className="media-coverage"><span>{zh?'调色强度':'Color strength'}</span><input className="media-range" aria-label={zh?'调色强度':'Color strength'} type="range" min="0" max="100" value={colorDraft??Math.round(doc.color.strength*100)} disabled={busy} onChange={e=>{const strength=Number(e.currentTarget.value);setColorDraft(strength);onPreview({...doc,color:{enabled:true,strength:strength/100}});}} onPointerUp={e=>{void media.commit({...doc,color:{enabled:true,strength:Number(e.currentTarget.value)/100}});setColorDraft(null);onPreview(null);}} onPointerCancel={()=>{setColorDraft(null);onPreview(null);}} onKeyUp={e=>{void media.commit({...doc,color:{enabled:true,strength:Number(e.currentTarget.value)/100}});setColorDraft(null);onPreview(null);}}/><span>{colorDraft??Math.round(doc.color.strength*100)}%</span></label>}
  </div>}
  {(!doc||!doc.assets.length)&&!media.uploads.length?
   <div className={`media-empty${zoneDrag?' dragging':''}${disabled?' disabled':''}`} role="button" tabIndex={disabled?-1:0} aria-label={zh?'添加图片':'Add images'}
    onClick={()=>{if(!disabled)openPicker();}} onKeyDown={e=>{if(!disabled&&(e.key==='Enter'||e.key===' ')){e.preventDefault();openPicker();}}}
    onDragOver={zoneOver} onDragLeave={()=>setZoneDrag(false)} onDrop={zoneDrop}>
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m5 17 5-5 3.5 3.5L17 12l4 4"/></svg>
    <span>{zh?'拖入图片或视频，或点击添加 · 图片 ≤25 MiB · 视频 ≤60 秒':'Drop images or videos here or click to add · images ≤25 MiB · videos ≤60 s'}</span>
   </div>
  :<>
   <div className="media-thumbnails">
    {doc?.assets.map(a=>{
     const meta=media.catalog.find(c=>c.asset_id===a.id),active=doc.slots.some(s=>s.asset===a.id&&time>=s.start&&time<s.end);
     return <div key={a.id} data-asset={a.id} className={`media-thumb${a.kind==='video'?' video':''}${active?' active':''}${active&&beatPulse?' pulse':''}${selected===a.id?' selected':''}${pressId===a.id?' pressing':''}${ghost?.id===a.id?' dragging':''}`}
      onPointerDown={e=>thumbDown(e,a)} onPointerMove={thumbMove} onPointerUp={()=>thumbDone(true)} onPointerCancel={()=>thumbDone(false)}
      onPointerEnter={e=>{if(e.pointerType==='mouse'&&a.kind==='video'&&canHover&&a.clip)setHoverVid(a.id);}} onPointerLeave={()=>setHoverVid(v=>v===a.id?'':v)}
      onClick={e=>{if(performance.now()<suppressUntil.current||(e.target as HTMLElement).closest('.media-delete'))return;pick(a);}}>
      <button title={meta?.display_name}><img loading="lazy" decoding="async" draggable={false} src={url(a.id)} alt={meta?.display_name??(a.kind==='video'?'Clip':'Image')}/></button>
      {a.kind==='video'&&<i className="media-dur">{mmss0(a.duration??0)}</i>}
      {a.kind==='video'&&<i className="media-play-glyph" aria-hidden="true"><svg viewBox="0 0 10 10" width="8" height="8" fill="#fff"><path d="M2 1.2v7.6L8.8 5z"/></svg></i>}
      {hoverVid===a.id&&a.clip&&<HoverVideo clip={a.clip} projectId={projectId}/>}
      <button className="media-delete" aria-label={zh?'删除素材':'Remove media'} disabled={busy} onClick={()=>removeImage(a.id)}><svg viewBox="0 0 16 16" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/></svg></button>
     </div>;
    })}
    {media.uploads.map(u=><div key={u.key} className={`media-upload ${u.state}`} title={u.state==='error'?(u.error??u.name):u.name}>
     {u.video?<video muted playsInline preload="metadata" src={u.url} onError={e=>e.currentTarget.classList.add('bad')}/>:<img src={u.url} alt=""/>}
     {u.video&&<i className="media-up-film" aria-hidden="true"><svg viewBox="0 0 10 10" width="8" height="8" fill="#fff"><path d="M2 1.2v7.6L8.8 5z"/></svg></i>}
     {u.state==='error'?<>
      <b className="media-up-err">!</b>
      <button className="media-up-btn retry" aria-label={zh?'重试':'Retry'} onClick={()=>media.retry(u.key)}><Icon d={paths.redo} size={11}/></button>
      <button className="media-up-btn" aria-label={zh?'放弃':'Dismiss'} onClick={()=>media.dismiss(u.key)}><Icon d={paths.close} size={10}/></button>
     </>:<>
      <svg className={`media-up-ring${u.state==='processing'?' spin':''}`} viewBox="0 0 22 22" width="22" height="22" aria-hidden="true">
       <circle cx="11" cy="11" r="9"/>
       <circle className="on" cx="11" cy="11" r="9" strokeDasharray="56.55" strokeDashoffset={u.state==='processing'?42:56.55*(1-u.progress)}/>
      </svg>
      <span>{u.state==='processing'?(zh?'处理视频…':'Processing…'):u.state==='waiting'?(zh?'等待分析':'Waiting'):u.state==='queued'?(zh?'排队':'Queued'):`${Math.round(u.progress*100)}%`}</span>
     </>}
    </div>)}
    <button className={`media-add${zoneDrag?' dragging':''}`} aria-label={zh?'添加素材':'Add media'} title={zh?'添加素材':'Add media'} disabled={busy} onClick={openPicker} onDragOver={zoneOver} onDragLeave={()=>setZoneDrag(false)} onDrop={zoneDrop}><Icon d={paths.plus} size={18}/></button>
   </div>
   {doc&&doc.assets.length>0&&duration>0&&<div className={`media-placement${preview||laneDrop?' dropping':''}${selected?' has-selection':''}`} ref={lane} style={{'--axis-l':insets.l,'--axis-r':insets.r} as React.CSSProperties} onDragOver={laneFileOver} onDragLeave={()=>setLaneDrop(false)} onDrop={zoneDrop} aria-label={zh?'图片时间轴':'Image timeline'}>
    <span className="media-axis-label">{zh?'素材':'MEDIA'}</span>
    <div className="media-axis" ref={axis}>
     {doc.slots.map(s=>{
      const isDrag=!!slotCur&&slotCur.key.start===s.start&&slotCur.key.asset===s.asset,cur=isDrag?slotCur!:s;
      const sel=!!selectedSlot&&selectedSlot.start===s.start&&selectedSlot.asset===s.asset;
      const replacing=!!slotCur&&!isDrag&&!s.fixed&&s.start<slotCur.end&&s.end>slotCur.start;
      const vid=assetOf(s.asset)?.kind==='video',off=cur.offset??s.offset??0;
      const clipInfo=vid?` · ${zh?'片段':'clip'} ${mmss(off)}–${mmss(off+(cur.end-cur.start))}`:'';
      return <button key={`${s.start}-${s.asset}`} style={{left:`${cur.start/duration*100}%`,width:`calc(${(cur.end-cur.start)/duration*100}% - 2px)`}}
       className={[s.fixed?'fixed':'',vid?'video':'',s.asset===selected?'selected':'',sel?'sel':'',isDrag?'dragging':'',replacing?'replacing':''].filter(Boolean).join(' ')}
       title={`${s.fixed?`${mmss(s.start)}–${mmss(s.end)} · ${zh?'已固定':'pinned'}`:`${mmss(s.start)}–${mmss(s.end)} · ${zh?'拖动以固定':'drag to pin'}`}${clipInfo}`}
       onPointerDown={e=>slotDown(e,s)} onPointerMove={slotMove} onPointerUp={slotUp} onPointerCancel={slotCancel} onKeyDown={e=>slotKey(e,s)}
       onClick={()=>{if(performance.now()<suppressUntil.current)return;setSelectedSlot({start:s.start,asset:s.asset});choose(s.asset);seek(s.start+.001);}}>
       <img src={url(s.asset)} alt="" draggable={false}/>
       {s.fixed&&<span className="media-pin"><svg viewBox="0 0 16 16" width="8" height="8" fill="#fff" aria-hidden="true"><path d={pinPath}/></svg></span>}
       <b className="media-handle l"/><b className="media-handle r"/>
      </button>;
     })}
     {preview&&<div className={`media-preview-slot${assetOf(preview.asset)?.kind==='video'?' video':''}`} style={{left:`${preview.start/duration*100}%`,width:`calc(${(preview.end-preview.start)/duration*100}% - 2px)`}}><img src={url(preview.asset)} alt=""/></div>}
     {!doc.slots.length&&<span className="media-lane-hint">{zh?'拖动缩略图到这里固定位置':'Drag a thumbnail here to pin it'}</span>}
     <i style={{left:`${time/duration*100}%`}}/>
    </div>
   </div>}
  </>}
   </div>
  </div>
  {doc&&asset&&<div className="media-inspector" style={{maxHeight:inspectorMax}}>
   <header className="media-inspector-head">
    <b>{zh?'素材编辑':'Media editor'}</b>
    <button className="media-icon media-inspector-close" aria-label={zh?'关闭图片编辑':'Close image editor'} title={zh?'关闭图片编辑':'Close image editor'} onClick={closeInspector}><Icon d={paths.close} size={14}/></button>
   </header>
   <div className="media-inspector-body">
   {value&&<div className={`media-inspect-image${value.fit==='contain'?' contain':''}`} style={value.fit==='contain'?{aspectRatio:aspect.replace(':','/'),width:180*(Number(aspect.split(':')[0])/Number(aspect.split(':')[1])||1)}:undefined}
    onPointerDown={markerDown} onPointerMove={markerMove} onPointerUp={markerUp} onPointerCancel={markerCancel}>
    {asset.kind==='video'&&scrub&&clipSrc?<video ref={clipRef} src={clipSrc} muted playsInline preload="auto" draggable={false}/>:<img src={url(asset.id)} alt={zh?'拖动设置焦点':'Drag to set focal point'} draggable={false}/>}
    {value.fit!=='contain'&&<i className="media-marker" style={{left:`${value.x*100}%`,top:`${value.y*100}%`}}/>}
   </div>}
   {value&&<>
    <div className="media-fit" role="radiogroup" aria-label={zh?'图片填充':'Image fit'}>
     <button role="radio" aria-checked={value.fit==='cover'} disabled={busy} onClick={()=>commitFocus({...value,fit:'cover'})}>{zh?'填满':'Fill'}</button>
     <button role="radio" aria-checked={value.fit==='contain'} disabled={busy} onClick={()=>commitFocus({...value,fit:'contain'})}>{zh?'完整显示':'Fit'}</button>
    </div>
    <label className="media-zoom"><span>{zh?'缩放':'Zoom'}</span><input className="media-range" type="range" min="1" max="3" step=".01" value={value.zoom} style={{'--fill':`${(value.zoom-1)/2*100}%`} as React.CSSProperties} disabled={busy}
     onChange={e=>{const v={...value,zoom:Number(e.target.value)};setDraft(v);queueDoc(withFocus(v));}}
     onPointerUp={()=>{if(draft)commitFocus(draft);}}
     onKeyUp={()=>{clearTimeout(zoomTimer.current);zoomTimer.current=setTimeout(()=>{if(draft)commitFocus(draft);},300);}}/><b>{value.zoom.toFixed(2)}×</b></label>
    <div className="media-fit" role="radiogroup" aria-label={zh?'焦点范围':'Focus scope'}>
     <button role="radio" aria-checked={scope==='all'} disabled={busy} onClick={()=>{setScope('all');setDraft(null);}}>{zh?'所有画幅':'All aspects'}</button>
     <button role="radio" aria-checked={scope==='aspect'} disabled={busy} onClick={()=>{setScope('aspect');setDraft(null);}}>{zh?`仅 ${aspect}`:`${aspect} only`}</button>
    </div>
    {scope==='aspect'&&asset.overrides[aspect]&&<button className="link-btn media-use-default" disabled={busy} onClick={useDefault}>{zh?'恢复通用':'Use default'}</button>}
   </>}
   {selSlot?<div className="media-slot-info">
    <b>{mmss(selSlot.start)} – {mmss(selSlot.end)} · {Math.max(1,Math.round((selSlot.end-selSlot.start)/beatLen))}{zh?' 拍':' beats'}</b>
    <div className="media-row">
     <button className="btn-line" disabled={busy} onClick={()=>selSlot.fixed?unpinSlot(selSlot):doc&&media.change({...doc,slots:doc.slots.map(x=>x===selSlot?{...x,fixed:true}:x)})}>{selSlot.fixed?(zh?'取消固定':'Unpin'):(zh?'固定':'Pin')}</button>
     <button className="btn-line danger" disabled={busy||!selSlot.fixed} onClick={()=>removeSlot(selSlot)}>{zh?'删除槽位':'Delete slot'}</button>
    </div>
   </div>:!doc.slots.some(s=>s.asset===asset.id)&&<p className="media-note">{zh?'此素材未在时间轴上 — 拖到时间轴即可使用':'Not on the timeline — drag it onto the timeline to use it'}</p>}
   {scrub&&(()=>{const off=scrubOff??(scrub.offset??0),len=scrub.end-scrub.start;
    return <div className="media-clip">
     <span className="media-caption">{zh?'片段':'Clip'}</span>
     <div className="media-scrub" ref={scrubRef} role="slider" aria-label={zh?'片段起点':'Clip offset'} aria-valuenow={off} aria-valuemin={0} aria-valuemax={Math.max(0,clipDur-len)} tabIndex={0}
      onPointerDown={scrubDown} onPointerMove={scrubMove} onPointerUp={scrubUp} onPointerCancel={scrubCancel}
      onKeyDown={e=>{if(e.key!=='ArrowLeft'&&e.key!=='ArrowRight')return;e.preventDefault();e.stopPropagation();const next=clamp(off+(e.key==='ArrowRight'?1:-1)/30,0,Math.max(0,clipDur-len));setScrubOff(null);media.change(placeSlot(doc,{start:scrub.start,end:scrub.end,asset:scrub.asset,offset:next},{start:scrub.start,asset:scrub.asset}));}}>
      <b className="media-scrub-window" style={{left:`${clipDur?off/clipDur*100:0}%`,width:`${clipDur?len/clipDur*100:0}%`}}/>
     </div>
     <b className="media-clip-meta">{zh?`起点 ${mmss(off)} · 长度 ${len.toFixed(1)} 秒`:`In ${mmss(off)} · ${len.toFixed(1)} s`} · {mmss0(clipDur)}</b>
    </div>;})()}
   <div className="media-row media-actions">
    <button className="media-icon" aria-label={zh?'前移':'Move earlier'} title={zh?'前移':'Move earlier'} disabled={busy||doc.assets.indexOf(asset)===0} onClick={()=>reorder(-1)}><Icon d={paths.left}/></button>
    <button className="media-icon" aria-label={zh?'后移':'Move later'} title={zh?'后移':'Move later'} disabled={busy||doc.assets.indexOf(asset)===doc.assets.length-1} onClick={()=>reorder(1)}><Icon d={paths.right}/></button>
    <button className="btn-line" disabled={busy} onClick={()=>{media.pin(asset.id,time);setMessage(zh?'已吸附到拍点 / 段落边界':'Snapped to beat / stage boundary');}}>{zh?'固定到当前位置':'Pin at playhead'}</button>
    <button className="btn-line danger" disabled={busy} onClick={()=>removeImage(asset.id)}>{zh?'删除素材':'Remove media'}</button>
   </div>
   <span className="media-inspector-status"><i className={`media-save-dot${media.saving?' saving':''}`}/>{savedFlash&&!media.saving&&<b className="media-saved"><Icon d={paths.check} size={11}/>{zh?'已保存':'Saved'}</b>}</span>
   {value&&<p className="media-note">{zh?'拖动或点击原图设置焦点，缩放和裁切按画幅计算。':'Drag or click the image to set its focal point.'}</p>}
   </div>
  </div>}
  {ghost&&<img className={`media-ghost-thumb${ghost.ret?' ret':''}`} src={ghost.url} alt="" draggable={false} style={ghost.ret?{left:ghost.ret.x,top:ghost.ret.y}:{left:ghost.x,top:ghost.y}}/>}
  {dragLabel()}
  {media.error&&<p className="media-error" role="alert">{media.error}</p>}
 </section>;
}
