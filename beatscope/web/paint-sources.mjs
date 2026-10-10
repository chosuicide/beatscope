import {createMediaColor} from './media-color.mjs';

// Only current/replay/effect frames are decoded. Originals never all live in RAM.
export function createPaintSources({base,mediaSource,shotAt,paletteFor,width,height,lowWidth,lowHeight,preview,gpu=true}){
 const images=new Map(),pending=new Map(),frames=new Map(),grade=createMediaColor(gpu);
 const abort=new AbortController();let disposed=false,bytes=0,loads=0;
 const frameLimit=Math.max(4,Math.min(8,Math.floor(32*1024*1024/(width*height*4))));
 const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
 const frameIndex=(t,shot)=>{const m=Math.max(0,Math.floor((t-shot[0]+shot[2])*30))%178;return(m<90?m:178-m)+1;};
 const keyFor=(t,res,shot)=>`${mediaSource?.revision??0}:${Math.round(t*30000)}:${res}:${shot[0]}:${shot[1]}:${shot[4].pk??''}`;
 async function load(key){
  if(images.has(key)){const entry=images.get(key);images.delete(key);images.set(key,entry);return entry.bitmap;}
  if(!pending.has(key))pending.set(key,(async()=>{
   const response=await fetch(base+key,{signal:abort.signal});if(!response.ok)throw Error('Pastel Bloom frame missing: '+key);
   const bitmap=await createImageBitmap(await response.blob());if(disposed){bitmap.close();throw Error('Paint renderer disposed');}
   const size=bitmap.width*bitmap.height*4;images.set(key,{bitmap,size});bytes+=size;loads++;
   while(images.size>12||bytes>32*1024*1024){const [old,entry]=images.entries().next().value;if(old===key)break;entry.bitmap.close();bytes-=entry.size;images.delete(old);}
   return bitmap;
  })().finally(()=>pending.delete(key)));
  return pending.get(key);
 }
 return {
  hasCustom:t=>!!mediaSource?.has(t),
  boundaryAt:t=>mediaSource?.boundaryAt(t)??0,
  async prepare(t,res='lo',shot=shotAt(t)){
   const key=keyFor(t,res,shot);if(frames.has(key)){const entry=frames.get(key);frames.delete(key);frames.set(key,entry);return;}
   let bitmap,fit='cover',progress=0;
   const palette=paletteFor(shot);
   if(mediaSource?.has(t)){
    await mediaSource.prepare([t]);const custom=mediaSource.at(t);if(disposed)return;
    bitmap=grade.at(custom.bitmap,palette,mediaSource.color);fit=custom.focus.fit;progress=custom.progress;
   }else bitmap=await load(`${shot[1]}/${preview||res==='lo'?'lo':'hi'}/${String(frameIndex(t,shot)).padStart(4,'0')}.jpg`);
   if(disposed)return;
   const canvas=document.createElement('canvas');canvas.width=res==='lo'?lowWidth:width;canvas.height=res==='lo'?lowHeight:height;
   // CPU brush analysis reads these surfaces repeatedly. Keep resampling on
   // the same raster path when a cached frame is evicted and replayed.
   const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.fillStyle=palette.base;ctx.fillRect(0,0,canvas.width,canvas.height);
   const zoom=1+(fit==='cover'?.035:.015)*progress;
   const scale=(fit==='contain'?Math.min:Math.max)(canvas.width/bitmap.width,canvas.height/bitmap.height)*zoom;
   ctx.drawImage(bitmap,(canvas.width-bitmap.width*scale)/2,(canvas.height-bitmap.height*scale)/2,bitmap.width*scale,bitmap.height*scale);
   frames.set(key,canvas);while(frames.size>frameLimit){const [old,c]=frames.entries().next().value;c.width=c.height=0;frames.delete(old);}
  },
  at(t,res='lo',shot=shotAt(t)){
   const key=keyFor(t,res,shot),canvas=frames.get(key);if(!canvas)throw Error('Paint source was not prepared: '+key);return canvas;
  },
  invalidate(){for(const c of frames.values())c.width=c.height=0;frames.clear();grade.clear();},
  get stats(){return {decodedFrames:images.size,decodedBytes:bytes,preparedFrames:frames.size,loads};},
  dispose(){disposed=true;abort.abort();this.invalidate();for(const entry of images.values())entry.bitmap.close();images.clear();bytes=0;grade.dispose();}
 };
}
