import {createMaterialGpu} from './material-gpu.mjs';
import {createMediaColor} from './media-color.mjs';
// Score rectangles use normalized positions; angles, circles, text and stroke
// widths use the short edge. Project coordinates before the uniform transform
// so rotating a shape never stretches it into an ellipse.
function aspectContext(raw,sx,sy){
 if(sx===1&&sy===1)return raw;
 const methods={
  translate:(x,y)=>raw.translate(x*sx,y*sy),
  rect:(x,y,w,h)=>raw.rect(x*sx,y*sy,w*sx,h*sy),
  fillRect:(x,y,w,h)=>raw.fillRect(x*sx,y*sy,w*sx,h*sy),
  clearRect:(x,y,w,h)=>raw.clearRect(x*sx,y*sy,w*sx,h*sy),
  strokeRect:(x,y,w,h)=>raw.strokeRect(x*sx,y*sy,w*sx,h*sy),
  moveTo:(x,y)=>raw.moveTo(x*sx,y*sy),lineTo:(x,y)=>raw.lineTo(x*sx,y*sy),
  bezierCurveTo:(a,b,c,d,e,f)=>raw.bezierCurveTo(a*sx,b*sy,c*sx,d*sy,e*sx,f*sy),
  arc:(x,y,r,a,b)=>raw.arc(x*sx,y*sy,r,a,b),
  fillText:(text,x,y)=>raw.fillText(text,x*sx,y*sy),
  drawImage:(image,...args)=>{
   const a=[...args],i=a.length===8?4:0;a[i]*=sx;a[i+1]*=sy;
   if(a.length!==2){a[i+2]*=sx;a[i+3]*=sy;}raw.drawImage(image,...a);
  },
 };
 for(const name of ['save','restore','beginPath','closePath','clip','stroke','setTransform','scale','rotate'])methods[name]=raw[name].bind(raw);
 return new Proxy(raw,{get:(_,name)=>methods[name]??raw[name],set:(_,name,value)=>{raw[name]=value;return true;}});
}
// CPU/Canvas remains the fallback when hardware WebGL cannot initialize.
function createPixelGpu(enabled=true){
 if(!enabled)return null;
 const canvas=document.createElement('canvas');canvas.width=canvas.height=384;
 const gl=canvas.getContext('webgl2',{alpha:true,premultipliedAlpha:false,antialias:false,depth:false,stencil:false,preserveDrawingBuffer:true,failIfMajorPerformanceCaveat:true});
 if(!gl)return null;
 const debug=gl.getExtension('WEBGL_debug_renderer_info'),renderer=debug?gl.getParameter(debug.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);
 if(/swiftshader|llvmpipe|software/i.test(renderer)){gl.getExtension('WEBGL_lose_context')?.loseContext();return null;}
 const compile=(type,source)=>{const shader=gl.createShader(type);gl.shaderSource(shader,source);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){gl.deleteShader(shader);throw Error('Pixel shader compilation failed');}return shader;};
 let program,vs,fs;
 try{
  vs=compile(gl.VERTEX_SHADER,`#version 300 es
  out vec2 uv;void main(){vec2 p=vec2(float((gl_VertexID<<1)&2),float(gl_VertexID&2));uv=vec2(p.x,1.-p.y);gl_Position=vec4(p*2.-1.,0.,1.);}`);
  fs=compile(gl.FRAGMENT_SHADER,`#version 300 es
  precision highp float;uniform sampler2D picture;uniform int mode;uniform vec3 tint;uniform float light,ceiling;in vec2 uv;out vec4 result;
  void main(){vec3 c=texture(picture,uv).rgb;float y=dot(c,vec3(.2126,.7152,.0722))*255.;
   if(mode==0){float a=light>.5?(226.-y)/200.:(y-22.)/190.;result=vec4(tint,clamp(a,0.,1.));}
   else if(mode==1)result=vec4(1.-c,clamp((y-6.)/18.,0.,1.));
   else result=vec4(c,clamp((ceiling-y)/max(12.,ceiling*.24),0.,1.));}`);
  program=gl.createProgram();gl.attachShader(program,vs);gl.attachShader(program,fs);gl.linkProgram(program);
  if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('Pixel shader linking failed');
 }catch{if(program)gl.deleteProgram(program);if(vs)gl.deleteShader(vs);if(fs)gl.deleteShader(fs);gl.getExtension('WEBGL_lose_context')?.loseContext();return null;}
 gl.deleteShader(vs);gl.deleteShader(fs);gl.useProgram(program);
 const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
 const uniform=name=>gl.getUniformLocation(program,name),mode=uniform('mode'),tint=uniform('tint'),light=uniform('light'),ceiling=uniform('ceiling');
 gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL,gl.NONE);
 return {renderer,apply(source,type,color=[0,0,0],isLight=false,threshold=0){
  if(gl.isContextLost())return null;
  if(canvas.width!==source.width||canvas.height!==source.height){canvas.width=source.width;canvas.height=source.height;}
  gl.viewport(0,0,canvas.width,canvas.height);gl.useProgram(program);gl.bindTexture(gl.TEXTURE_2D,texture);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,source);gl.uniform1i(mode,type);gl.uniform3f(tint,color[0]/255,color[1]/255,color[2]/255);gl.uniform1f(light,isLight?1:0);gl.uniform1f(ceiling,threshold);gl.drawArrays(gl.TRIANGLES,0,3);return canvas;
 },dispose(){gl.deleteTexture(texture);gl.deleteProgram(program);gl.getExtension('WEBGL_lose_context')?.loseContext();}};
}

// A landscape counterpart to the reference's full subject/detail/echo/return relation.
function createLandscapeRelay(ctx,canvas,gpu,compositor){
 const size=384,ink=document.createElement('canvas');ink.width=ink.height=size;const q=ink.getContext('2d',{willReadFrequently:true}),luma=new Float32Array(size*size);
 const clamp=x=>Math.max(0,Math.min(1,x));
 return s=>{const t=s.sinceCut;if(!s.setup.waterLandscape||t<1/30||t>.73)return;
  let image=ink;
  if(compositor){const original=compositor.snapshot(size,size),stats=compositor.landscape(original);image=compositor.effect(original,4,[0,0,0],false,0,stats.summary);ctx.save();compositor.condition(stats.occupied,1);}
  else{
  q.clearRect(0,0,size,size);q.drawImage(canvas,0,0,size,size);const pixels=q.getImageData(0,0,size,size),a=pixels.data;let mean=0;
  for(let i=0,k=0;i<a.length;i+=4,k++){const y=.2126*a[i]+.7152*a[i+1]+.0722*a[i+2];luma[k]=y;mean+=y;}mean/=size*size;
  const ceiling=mean*.99;let occupied=0;
  const denominator=Math.max(12,ceiling*.24);
  for(let i=0,k=0;i<a.length;i+=4,k++){const alpha=clamp((ceiling-luma[k])/denominator);if(!gpu)a[i+3]=255*alpha;if(alpha>.25)occupied++;}
  // A flat or unsuitable source keeps the readable full frame instead of exposing empty paper.
  if(occupied/(size*size)<.12)return;
  const processed=gpu?.apply(ink,2,[0,0,0],false,ceiling);
  if(processed){q.clearRect(0,0,size,size);q.drawImage(processed,0,0);}else{for(let i=0,k=0;i<a.length;i+=4,k++)a[i+3]=255*clamp((ceiling-luma[k])/denominator);q.putImageData(pixels,0,0);}
  }
  ctx.save();ctx.globalAlpha=1;ctx.fillStyle='#e9e8e1';ctx.fillRect(0,0,1080,1080);
  const pose=s.setup.waterPose??0;
  // A related contour remains in the space while the detail aperture changes.
  for(const [x,y,alpha]of [[-36,-12,.13],[32,16,.21]]){ctx.globalAlpha=alpha;ctx.drawImage(image,x,y,1080,1080);}
  ctx.globalAlpha=1;
  if(t<.23){const stretch=t<.1?1:.82;ctx.drawImage(image,0,0,size,size,540-540*stretch,0,1080*stretch,1080);}
  else if(t<.40){
   const sx=pose===1?80:32,sy=pose===2?125:65;ctx.drawImage(image,sx,sy,240,230,350,220,430,560);
   ctx.strokeStyle='rgba(144,63,43,.65)';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(349,220);ctx.lineTo(349,780);ctx.stroke();
  }else if(t<.54){
   ctx.drawImage(image,35,65,280,270,0,0,1080,1080);
  }else if(t<.64){
   for(const [y,shift]of [[0,-34],[390,36],[700,-16]]){ctx.save();ctx.beginPath();ctx.rect(0,y,1080,y===0?390:y===390?310:380);ctx.clip();ctx.drawImage(image,shift,0,1080,1080);ctx.restore();}
  }else{ctx.globalAlpha=.4+.6*clamp((t-.64)/.09);ctx.drawImage(image,0,0,1080,1080);}
  ctx.restore();if(compositor)ctx.restore();
 };
}

// Onset-owned, short-lived negatives sampled from the current composed picture.
function createBurstLayer(ctx,canvas,gpu,compositor){
 const N=320,scale=N/384,small=document.createElement('canvas');small.width=small.height=N;const q=small.getContext('2d',{willReadFrequently:true}),luma=new Float32Array(N*N);
 const limit=x=>Math.max(0,Math.min(1,x)),mix=(a,b,p)=>a+(b-a)*p;
 const boxes=[{x:325,y:230,w:175,h:190},{x:620,y:365,w:210,h:150},{x:310,y:620,w:190,h:165},{x:605,y:670,w:165,h:180}];
 return s=>{
  const z=s.setup;if(!z.surfaceBurst||s.sinceCut>=(z.negativeBurstFrames??4)/30)return;
  const length=(z.negativeBurstFrames??4)/30,phase=Math.floor(s.sinceCut/.18),key=(z.surfacePose??0)+phase,old=s.previous?key-1:key,p=1-(1-limit((s.sinceCut-phase*.18)/(2/30)))**3;
  const wave=(freq,n)=>mix(Math.sin(old*freq+n),Math.sin(key*freq+n),p);
  let image=small,regions,selection;
  if(compositor){const original=compositor.snapshot(N,N);selection=compositor.regions(original);regions=selection.regions;image=compositor.effect(original,3);ctx.save();compositor.condition(selection.texture,2);}
  else{
  q.clearRect(0,0,N,N);q.drawImage(canvas,0,0,N,N);const data=q.getImageData(0,0,N,N),a=data.data;
  // Select real textured regions before inversion; flat sky/background never becomes a solid board.
  for(let i=0,k=0;i<a.length;i+=4,k++)luma[k]=.2126*a[i]+.7152*a[i+1]+.0722*a[i+2];
  const candidates=[],side=Math.round(80*scale),margin=Math.round(16*scale),step=Math.round(32*scale);
  for(let y=margin;y<=N-side-margin;y+=step)for(let x=margin;x<=N-side-margin;x+=step){let sum=0,sq=0,count=0;
   for(let yy=y;yy<y+side;yy+=7)for(let xx=x;xx<x+side;xx+=7){const v=luma[yy*N+xx];sum+=v;sq+=v*v;count++;}
   candidates.push({x,y,side,variance:sq/count-(sum/count)**2});
  }
  candidates.sort((a,b)=>b.variance-a.variance);if(candidates[0].variance<60)return;
  regions=[];for(const r of candidates){if(regions.every(v=>Math.hypot(v.x-r.x,v.y-r.y)>70*scale))regions.push(r);if(regions.length===2)break;}
  const processed=gpu?.apply(small,1);
  if(processed){q.clearRect(0,0,N,N);q.drawImage(processed,0,0);}else{for(let i=0,k=0;i<a.length;i+=4,k++){const y=luma[k];
   a[i]=255-a[i];a[i+1]=255-a[i+1];a[i+2]=255-a[i+2];a[i+3]=255*limit((y-6)/18);
  }q.putImageData(data,0,0);}
  }
  const live=Array.from({length:z.negativeWindowCount??2},(_,n)=>{const b=boxes[(n+key)%4];return{...b,x:b.x+75*wave(1.3,n*1.7),y:b.y+55*wave(.95,n*2.1)};});
  ctx.save();ctx.globalAlpha=z.negativeBurstFrames>6?limit((length-s.sinceCut)/(2/30)):1;ctx.font='10px Arial';
  for(const [n,b]of live.entries()){
   const region=regions[n%regions.length],sw=region.side,sh=region.side*b.h/b.w,sx=Math.max(0,Math.min(N-sw,region.x+6*wave(1.7,n))),sy=Math.max(0,Math.min(N-sh,region.y+6*wave(1.4,n)));
   ctx.drawImage(compositor?compositor.regionImage(image,selection,n%2):image,sx,sy,sw,sh,b.x,b.y,b.w,b.h);
   ctx.strokeStyle=z.group==='gray'?'rgba(52,64,76,.75)':'rgba(223,228,233,.70)';ctx.lineWidth=.85;ctx.strokeRect(b.x,b.y,b.w,b.h);ctx.fillStyle=ctx.strokeStyle;
   for(const x of [b.x,b.x+b.w])for(const y of [b.y,b.y+b.h])ctx.fillRect(x-2,y-2,4,4);
   ctx.fillText(`Surface / 0${n+1}`,b.x,b.y-8);
  }
  for(let n=0;n<live.length-1;n++){const a=live[n],b=live[n+1];ctx.beginPath();ctx.moveTo(a.x+a.w,a.y+a.h/2);ctx.bezierCurveTo(a.x+a.w+90,a.y+a.h/2+55*wave(.8,n),b.x-75,b.y+b.h/2+65*wave(1.2,n),b.x,b.y+b.h/2);ctx.stroke();}
  // Drafting marks follow the same two-frame cue response; they disappear with the aperture.
  ctx.globalAlpha*=.34;ctx.beginPath();ctx.arc(540,540,290,key*.32,key*.32+Math.PI*.8);ctx.stroke();
  for(let n=0;n<6;n++){const x=270+n*95+18*wave(.9,n),y=520+95*wave(1.3,n);ctx.strokeRect(x-7,y-5,14,10);}
  ctx.restore();if(compositor)ctx.restore();
 };
}

// Stateless picture adapter: score visits, source clocks, focal crops and phase maps.
export async function createMaterialMovie(canvas,D,base="",{gpu:useGpu=true,composite:trueGpu=true,mediaSource=null}={}){
 const start=0,duration=D.duration;let disposed=false;
 const W=1080,short=Math.min(canvas.width,canvas.height),aspectX=canvas.width/short,aspectY=canvas.height/short;
 const compositor=createMaterialGpu(canvas,useGpu&&trueGpu),rawCtx=compositor?.ctx||canvas.getContext('2d'),ctx=aspectContext(rawCtx,aspectX,aspectY),images={},gpu=compositor?null:createPixelGpu(useGpu);
 const center=[540*aspectX,540*aspectY],radius=820*Math.hypot(aspectX,aspectY)/Math.SQRT2;
 const burst=createBurstLayer(ctx,canvas,gpu,compositor),contour=createLandscapeRelay(ctx,canvas,gpu,compositor);
 const pending={},touch=new Map(),mediaColor=createMediaColor(useGpu&&!!mediaSource);
 const customFor=s=>{const custom=mediaSource?.at(frameTimes.get(s));return custom?{...custom,bitmap:mediaColor.at(custom.bitmap,s.setup.palette||{base:'#f7f7f3',accent:'#f7f7f3',secondary:'#dedfd9'},mediaSource.color)}:null;};
 const frameTimes=new WeakMap(D.frames.map((s,i)=>[s,i/30]));
 const pageFor=s=>{if(mediaSource?.has(frameTimes.get(s)))return null;const a=D.assets[s.setup.sourceId];return a.kind==='video'?a.files[Math.floor(s.mediaCell/4)]:a.files[0];};
 const frameAt=time=>Math.max(0,Math.min(D.frames.length-1,Math.round((start+time)*30)));
 const statesFor=time=>{const f=frameAt(time),s=D.frames[f],states=[s],t=s.sinceCut;
  if(s.previous&&t<.2&&['iris','dissolve','push','occlude'].includes(s.setup.transition))states.push(D.frames[Math.max(0,f-Math.ceil(t*30)-1)]);
  if(s.setup.trail&&t>0&&t<.2)for(const j of [1,3,5])states.push(D.frames[Math.max(0,f-j)]);
  return states;};
 const needed=time=>[...new Set(statesFor(time).map(pageFor).filter(Boolean))];
 async function load(file){if(images[file])return; if(!pending[file])pending[file]=(async()=>{if(compositor&&typeof createImageBitmap==='function'){const response=await fetch(base+file);if(!response.ok)throw Error('Material image missing');const bitmap=await createImageBitmap(await response.blob(),{premultiplyAlpha:'none'});if(disposed){bitmap.close();return;}images[file]=bitmap;}else{const im=new Image();im.src=base+file;await im.decode();images[file]=im;}})().catch(error=>{delete pending[file];throw error;});await pending[file];}
 async function prepare(time){if(mediaSource)await mediaSource.prepare([...statesFor(time).map(s=>frameTimes.get(s)),Math.min(duration-1/30,time+.25)]);const files=[...new Set([...needed(time),...needed(Math.min(duration,time+.25))])];await Promise.all(files.map(load));for(const f of files)touch.set(f,time);{for(const [f]of [...touch].sort((a,b)=>a[1]-b[1])){if(Object.keys(images).length<=10)break;if(!files.includes(f)){images[f]?.close?.();delete images[f];delete pending[f];touch.delete(f);}}}}
 const files=needed(0);let next=0;
 await Promise.all(Array.from({length:4},async()=>{while(next<files.length)await load(files[next++]);}));
 const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x)),out=x=>1-(1-clamp(x))**3,expo=x=>x<=0?0:1-2**(-10*clamp(x));
 const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
 // Hold authored poses, then move over two native frames into the next one.
 const pose=(s,values)=>{const times=s.setup.phases,t=s.sinceCut;let i=times.length-1;while(i>0&&t<times[i])i--;const a=values[Math.min(i,values.length-1)];if(s.setup.stepPose)return a;if(i===times.length-1)return a;const next=times[i+1],p=clamp((t-next+.045)/.045);return a+(values[Math.min(i+1,values.length-1)]-a)*out(p);};
 function picture(s,w=W,h=W,z=1,ox=0,oy=0){
  const a=D.assets[s.setup.sourceId],custom=customFor(s);let im,sx=0,sy=0,sw,sh;
  if(custom){im=custom.bitmap;sw=im.width;sh=im.height;}
  else if(a.kind==='video'){const f=s.mediaCell;im=images[a.files[Math.floor(f/4)]];sx=f%2*a.width;sy=Math.floor(f%4/2)*a.height;sw=a.width;sh=a.height;}
  else{im=images[a.files[0]];sw=im.width;sh=im.height;}
  let focal=custom?[.5,.5]:s.focus||s.setup.focal||[.5,.5];
  // The birdB atlas intentionally pads a 1080x570 shot for its square score.
  // Rectangular cover uses its content, while keeping the cached square score intact.
  if(!custom&&aspectX!==aspectY&&s.setup.sourceId==='birdB'){
   const contentHeight=sh*570/1080,padding=(sh-contentHeight)/2;
   focal=[focal[0],clamp((focal[1]*sh-padding)/contentHeight)];sy+=padding;sh=contentHeight;
  }
  const zoom=z*(s.values['camera.scale']||1)*(custom?1+.035*custom.progress:1),side=Math.min(sw,sh)/zoom;
  const stretch=s.setup.mode==='squeeze'||s.setup.mode==='spine'||s.setup.mode==='liquidNeedle',ratio=w*aspectX/(h*aspectY);
  const cropW=stretch?side:aspectX===aspectY?side*Math.min(1,ratio):Math.min(sw,sh*ratio)/zoom,cropH=stretch?side:cropW/ratio;
  const fx=clamp(focal[0]+(s.values['camera.x']||0)+ox),fy=clamp(focal[1]+(s.values['camera.y']||0)+oy);
  sx+=clamp(sw*fx-cropW/2,0,sw-cropW);sy+=clamp(sh*fy-cropH/2,0,sh-cropH);
  return{im,sx,sy,sw:cropW,sh:cropH};
 }
 function source(s,x=0,y=0,w=W,h=W,z=1,ox=0,oy=0,alpha=1){
  const custom=customFor(s);
  if(custom?.focus.fit==='contain'){
   const im=custom.bitmap,scale=Math.min(w*aspectX/im.width,h*aspectY/im.height)*(1+.025*custom.progress),iw=im.width*scale/aspectX,ih=im.height*scale/aspectY;
   ctx.save();ctx.globalAlpha*=alpha;ctx.beginPath();ctx.rect(x,y,w,h);ctx.clip();ctx.drawImage(im,x+(w-iw)/2,y+(h-ih)/2,iw,ih);ctx.restore();return;
  }
  const p=picture(s,w,h,z,ox,oy);ctx.save();ctx.globalAlpha*=alpha;ctx.beginPath();ctx.rect(x,y,w,h);ctx.clip();ctx.drawImage(p.im,p.sx,p.sy,p.sw,p.sh,x,y,w,h);ctx.restore();
 }
 let palette={base:'#f7f7f3',accent:'#f7f7f3',secondary:'#dedfd9'};
 const rect=(x,y,w,h,c='#f7f7f3')=>{ctx.fillStyle=c==='#f7f7f3'?palette.base:c==='#dedfd9'||c==='#d9dbd8'?palette.secondary:c==='#e8e9e3'||c==='#ebede7'||c==='#f5f5f1'?palette.accent:c;ctx.fillRect(x,y,w,h);};
 function response(s){let at=0,weight=1;for(const [t,w]of s.setup.surfaceSteps||[])if(s.sinceCut>=t){at=t;weight=w;}return weight*(1-out((s.sinceCut-at)/.17));}
 function edge(s,x1,y1,x2,y2,strength=1){
  if(!s.setup.edgeAccent)return;const dx=x2-x1,dy=y2-y1,length=Math.hypot(dx,dy)||1,nx=-dy/length,ny=dx/length,p=response(s);
  ctx.save();ctx.globalAlpha*=strength*(.35+.65*p);ctx.lineWidth=s.setup.edgeWidth||1.6;
  for(let i=0;i<2;i++){const offset=(i?1:-1)*(1.3+1.3*p);ctx.strokeStyle=s.setup.edgeColors?.[i]||['#ff3150','#21f2e8'][i];ctx.beginPath();ctx.moveTo(x1+nx*offset,y1+ny*offset);ctx.lineTo(x2+nx*offset,y2+ny*offset);ctx.stroke();}ctx.restore();
 }
 function masked(s,box,z=1,ox=0,oy=0){ctx.save();ctx.beginPath();ctx.rect(...box);ctx.clip();source(s,0,0,W,W,z,ox,oy);ctx.restore();}
 // Reflect the video itself. Adjacent sectors share the same source clock and
 // focal edge, so flowing ink and ridgelines continue across the seams.
 function radial(s,n,angle,zoom,drift){
  const R=radius,p=picture(s,2*R/aspectX,2*R/aspectY,zoom,drift,.035);
  if(compositor){compositor.radial(p,n,angle,center,R);return;}
  const step=Math.PI*2/n;
  for(let i=0;i<n;i++){
   rawCtx.save();rawCtx.translate(...center);rawCtx.rotate(angle+i*step);
   rawCtx.beginPath();rawCtx.moveTo(0,0);rawCtx.lineTo(R*Math.cos(-step/2-.002),R*Math.sin(-step/2-.002));
   rawCtx.arc(0,0,R,-step/2-.002,step/2+.002);rawCtx.closePath();rawCtx.clip();
   if(i%2)rawCtx.scale(1,-1);
   rawCtx.drawImage(p.im,p.sx,p.sy,p.sw,p.sh,-R,-R,2*R,2*R);rawCtx.restore();
  }
 }
 function fourfold(s,zoom,drift,angle=0){
  const R=radius,p=picture(s,R/aspectX,R/aspectY,zoom,drift,.10-drift*.4);
  if(compositor){compositor.fourfold(p,angle,center,R);return;}
  rawCtx.save();rawCtx.translate(...center);rawCtx.rotate(angle);
  for(const x of [-1,1])for(const y of [-1,1]){
   rawCtx.save();rawCtx.scale(x,y);rawCtx.drawImage(p.im,p.sx,p.sy,p.sw,p.sh,0,0,R,R);rawCtx.restore();
  }rawCtx.restore();
 }
 function layout(s,tx=0){
  const t=s.sinceCut;let mode=s.setup.mode;if(s.setup.effectLimit&&t>=s.setup.effectLimit&&['liquidNeedle','liquidRemnant','liquidWindow','liquidSweep'].includes(mode))mode='subject';const {variant:v,attack,settle}=s.setup,e=out(t/settle),fast=expo(t/attack);
  palette=s.setup.palette||{base:'#f7f7f3',accent:'#f7f7f3',secondary:'#dedfd9'};
  ctx.save();ctx.translate(tx,0);rect(0,0,W,W);
  const phrase=s.setup.phrase||[0,.75],p=clamp(t/(phrase[1]-phrase[0]));
  
 if(mode==='liquidWindow'){
  // One upright crop follows the droplet head, never a slanted photo panel.
  const width=pose(s,[W,285,390,390]),height=pose(s,[W,940,800,800]);
  source(s,540-width/2,540-height/2,width,height,1);edge(s,540-width/2,540-height/2,540-width/2,540+height/2,.6);edge(s,540+width/2,540-height/2,540+width/2,540+height/2,.6);
 }else if(mode==='liquidNeedle'){
  const width=pose(s,[W,20,12,12]),height=pose(s,[W,1470,1540,1540]);
  source(s,540-width/2,540-height/2,width,height,1);
 }else if(mode==='liquidSweep'){
  const height=pose(s,[W,230,330,330]),y=height===W?0:600-height*.32;
  source(s,0,y,W,height,1,0,.06);
 }else if(mode==='liquidRemnant'){
   // A single active ripple patch with offset pale exposure remnants.
   // No three-column layout and no angled borders.
   const shift=pose(s,[0,42,18,18]);
   for(const [x,y,w,h,alpha]of [[345-shift,165,340,725,.18],[375+shift,205,355,725,.28]]){
    ctx.save();ctx.globalAlpha=alpha;masked(s,[x,y,w,h],1.3,0,.02);ctx.restore();
    ctx.save();ctx.globalAlpha=.55;rect(x,y,w,h,'#d1d2cf');ctx.restore();
   }
   source(s,345+shift,450,365,245,1.42,0,.10);
  }else if(mode==='liquidTwin'){

  const width=pose(s,[165,260,340,520]),gap=pose(s,[240,180,60,0]);
  source(s,540-gap/2-width,0,width,W,1);
  ctx.save();ctx.translate(1080,0);ctx.scale(-1,1);source(s,540-gap/2-width,0,width,W,1);ctx.restore();
 }else if(mode==='subject'){
source(s,0,0,W,W,pose(s,s.setup.subjectZoom||[1,1,1]));}else if(mode==='rupture'){
   // Adjacent cuts retain a continuous occupied image. No floating photo scraps.
   source(s,0,0,W,W,1.08);
   const bounds=[-140,330,775,1220],shear=pose(s,[90,-28,18,0])+response(s)*36;
   for(let i=0;i<3;i++){
    const a=bounds[i],b=bounds[i+1],d=(i%2?1:-1)*shear;
    ctx.save();ctx.beginPath();ctx.moveTo(a+55,0);ctx.lineTo(b+55,0);ctx.lineTo(b-55,W);ctx.lineTo(a-55,W);ctx.closePath();ctx.clip();source(s,d,-d*.18,W,W,1.08+i*.06,(i-1)*.028,0);ctx.restore();
    if(i<2)edge(s,b+55,0,b-55,W,.95);
   }
  }else if(mode==='drive'){
   const direction=s.setup.ridgeDirection||1;
   source(s,0,0,W,W,1.04+.25*p,-direction*.075+direction*.13*p,.025-.05*p);
  }else if(mode==='density'){
   const states=s.setup.densitySteps;let n=states[0][1];for(const [at,count]of states)if(t>=at)n=count;
   const rows=n>8?3:n>4?2:1,columns=Math.ceil(n/rows),heights=rows===3?[0,.27,.71,1]:rows===2?[0,.62,1]:[0,1];
   for(let r=0;r<rows;r++)for(let c=0;c<columns;c++){
    const edge=k=>(k/columns+.055*Math.sin(k*2.1+r)*Math.sin(k*Math.PI/columns))*W;
    const x=edge(c),w=edge(c+1)-x,y=heights[r]*W,h=(heights[r+1]-heights[r])*W,shift=(r%2?1:-1)*26*(1-out(t/.12));
    ctx.save();ctx.beginPath();ctx.rect(x,y,w+.5,h+.5);ctx.clip();
    if((c+r)%2){ctx.translate(2*x+w,0);ctx.scale(-1,1);}
    source(s,x+shift,y,w,h,1.08+(c%3)*.22,(c%3-1)*.07,(r-1)*.08);ctx.restore();
    if(c>0&&(c+r)%3===0)edge(s,x,y,x,y+h,.75);
   }
  }else if(mode==='mirrorSeam'){
   const axis=540+(1-out(t/.18))*(v===1?-155:110),drift=.04+.09*p;
   source(s,0,0,axis,W,1.12,drift,.025);
   ctx.save();ctx.translate(2*axis,0);ctx.scale(-1,1);
   source(s,2*axis-W,0,W-axis,W,1.12,drift,.025);ctx.restore();
   edge(s,axis,0,axis,W,.9);
  }else if(mode==='kaleid'){
   // The angle belongs to the whole musical phrase, including the source handoff.
   let n=s.setup.sectors;for(const [at,count]of s.setup.sectorSteps||[])if(t>=at)n=count;
   const bluePlume=s.setup.sourceId==='ink';
   radial(s,n,-Math.PI/2+.09*p,(bluePlume?1.45:1.18)+.12*p,bluePlume?-.10+.03*p:.12-.07*p);
   if(response(s)>.1){const a=-Math.PI/2+.09*p,b=a+Math.PI*2/n;edge(s,540,540,540+radius*Math.cos(a)/aspectX,540+radius*Math.sin(a)/aspectY,.7);edge(s,540,540,540+radius*Math.cos(b)/aspectX,540+radius*Math.sin(b)/aspectY,.5);}
  }else if(mode==='centerFold'){
   const pull=out(t/.34),dunes=s.setup.sourceId==='desertB';
   fourfold(s,(dunes?1.6:1.16)+.26*pull,(dunes?.08:.20)-.15*pull,-.025*(1-pull));
   // On the final accent, the central detail expands out of the mirrored diamond.
   if(t>.23){ctx.save();ctx.beginPath();ctx.arc(540,540,radius*out((t-.23)/.28),0,Math.PI*2);ctx.clip();source(s,0,0,W,W,1.7);ctx.restore();}
  }else if(mode==='inward'){
   const pull=smooth(clamp(t/.42));
   // Texture moves radially along mirrored sectors; no ornamental frame overlay.
   radial(s,s.setup.sectors||8,-Math.PI/4,1.12+.82*pull,.24-.31*pull);
   if(t>.30){ctx.save();ctx.beginPath();ctx.arc(540,540,radius*out((t-.30)/.25),0,Math.PI*2);ctx.clip();source(s,0,0,W,W,1.92);ctx.restore();}
  }else if(mode==='travel'||mode==='detailFlow'){
   const progress=clamp((s.mediaTime-D.assets[s.setup.sourceId].sourceStart)/6);
   const z=mode==='detailFlow'?1.35:1.04;
   source(s,0,0,W,W,z+progress*.055,-.045+progress*.09,.025-progress*.035);
  }else if(mode==='ridgeSlice'){
   source(s,0,0,W,W,1.08);
   const bounds=[0,245,690,1080];
   for(let i=0;i<3;i++){
    const motion=1-out(t/(.17+i*.055)),d=(i-1)*(38*motion+45*response(s));
    ctx.save();ctx.beginPath();ctx.moveTo(bounds[i],0);ctx.lineTo(bounds[i+1]+65,0);ctx.lineTo(bounds[i+1]-65,W);ctx.lineTo(bounds[i]-80,W);ctx.closePath();ctx.clip();
    source(s,d,-d*.38,W,W,1.08);ctx.restore();
    if(i<2)edge(s,bounds[i+1]+65,0,bounds[i+1]-65,W,.9);
   }
  }else if(mode==='full')source(s,0,0,W,W,1+.045*(1-out(t/.22)));
  else if(mode==='punch'){
   const zoom=pose(s,[.87,1.13,1.02]);source(s,0,0,W,W,zoom,(1-fast)*.11*(v%2?1:-1),.015*Math.sin(t*4));
  }else if(mode==='macro'){
   source(s,0,0,W,W,pose(s,[1,1.16,1.04]),s.focus?pose(s,[-.012,.008,0]):pose(s,[-.16,.11,.045]),s.focus?0:pose(s,[.07,-.08,0]));
  }else if(mode==='slab'){
   const w=pose(s,[420,350,350]);rect(540-w/2-24,95,w+48,890,'#d9dbd8');
   // The crop shown inside the tall slab is a different detail from the full shot.
   source(s,540-w/2,155,w,610,1.95,.03,.14);rect(540-w/2,765,w,150);
  }else if(mode==='squeeze'){
   const w=pose(s,[W,20,76,310,W]),h=pose(s,[W,1830,1690,1340,W]);source(s,540-w/2,540-h/2,w,h,1.03);
   if(w<W-10){edge(s,540-w/2,0,540-w/2,W,.95);edge(s,540+w/2,0,540+w/2,W,.95);}
  }else if(mode==='spine'){
   const widths=[66,112,230],w=pose(s,widths),n=v===1?3:2;
   for(let i=0;i<n;i++)source(s,540+(i-(n-1)/2)*(w+75)-w/2,-160,w,1400,1.15,(i-1)*.06);
  }else if(mode==='repeat'){
   const n=t<.067?3:t<.167?7:t<.267?5:4,w=W/n;
   for(let i=0;i<n;i++){const z=i%2?1.32:.92;source(s,i*w+(i%2?1:-1)*13*(1-e),-65,w-3,1210,z,(i%3-1)*.08);}
   if(v===2){rect(0,0,W,90);rect(0,W-90,W,90);}
  }else if(mode==='paper'){
   const spread=pose(s,[135,95,145,105]);
   for(let i=0;i<4;i++){
    const cx=540+(i-1.5)*spread,cy=540+(i-1.5)*52;
    rect(cx-205,cy-385,410,770,i%2?'#dedfd9':'#e8e9e3');
    if(i===0||i===3)source(s,cx-188,cy-90,376,210,2.0,(i-1.5)*.07,.10);
   }
   rect(327,179,426,722,'#f7f7f3');source(s,348,362,384,410,1.7,0,.09);
   // Foreground white folds briefly cover the active image without stopping it.
   const fold=1-out(clamp((t-.08)/.12));rect(348,362,384,410*fold);
  }else if(mode==='whitefold'||mode==='unfurl'){
   source(s,0,0,W,W,mode==='whitefold'?1.1:1);
   const cover=mode==='whitefold'?pose(s,[0,.78,.48,0]):1-out(clamp((t-.067)/.23));
   const boxes=[[0,0,300,W],[300,0,260,620],[560,410,260,670],[820,0,260,W]];
   boxes.forEach(([x,y,w,h],i)=>{const k=clamp(cover*(1+i*.12));rect(x,y,w,h*k,i%2?'#f5f5f1':'#ebede7');});
   if(mode==='unfurl'&&t<.12)source(s,430,335,220,410,1.1);
  }else if(mode==='bands'){
   const n=v===0?3:5,h=W/n;
   for(let i=0;i<n;i++){
    const slide=(i%2?1:-1)*pose(s,[130,30,0]);
    ctx.save();ctx.beginPath();ctx.rect(0,i*h,W,h);ctx.clip();
    source(s,slide,i*h-h*.22,W,h*1.4,1.25,(i%3-1)*.065,(i%2?-.12:.12));ctx.restore();
    if(i>0)edge(s,0,i*h,W,i*h,.9);
   }
  }else if(mode==='mosaic'){
   const cols=3+(v===1?1:0),z=W/cols;
   for(let r=0;r<cols;r++)for(let c=0;c<cols;c++){
    const delay=(r+c)*.027,k=out(clamp((t-delay)/.10)),gap=(1-k)*22;
    if((r*cols+c+v)%7===0&&t>.1)continue;
    source(s,c*z+gap,r*z-gap,z-2,z-2,1.05+(r%2)*.32,(c%2?-.1:.1),r%2?-.09:.07);
   }
  }else if(mode==='holes'){
   source(s,0,0,W,W,1.1);
   const z=216,shift=pose(s,[0,1,2]);
   for(let r=0;r<5;r++)for(let c=0;c<5;c++)if((c+r*2+Math.round(shift)+v)%4===0)rect(c*z,r*z,z+1,z+1);
  }else if(mode==='card'){
   const size=t<.067?350:t<.2?285:330,angle=(-25+v*12)+(1-e)*34;
   ctx.translate(540,540);ctx.rotate(angle*Math.PI/180);
   source(s,-size/2,-size/2,size,size,1.15,0,0);
   // A faint second exposure lasts two frames, before the pose becomes readable.
   if(t<.067)source(s,-size/2+9,-size/2-7,size,size,1.15,0,0,.15);
  }else if(mode==='scan'){
   source(s,0,0,W,W,1.45,pose(s,[-.07,.05,0]));
   const spacing=t<.1?4:7;for(let y=0;y<W;y+=spacing)rect(0,y,W,1,'rgba(247,247,243,.44)');
  }else if(mode==='columns'){
   const cuts=[0,180,415,565,840,1080];
   for(let i=0;i<5;i++){
    const p=out(clamp((t-i*.026)/.13)),offset=(i%2?1:-1)*W*(1-p);
    masked(s,[cuts[i],offset,cuts[i+1]-cuts[i]-4,W],1.07,(i-2)*.045,0);
   }
  }
  ctx.restore();
 }

 const trailBase=document.createElement('canvas'),trailImage=document.createElement('canvas');
 trailBase.width=canvas.width;trailBase.height=canvas.height;trailImage.width=trailImage.height=384;
 const baseCtx=trailBase.getContext('2d'),trailCtx=trailImage.getContext('2d',{willReadFrequently:!gpu});

 function applyTrail(s,f){
  if(!s.setup.trail)return;
  const t=s.sinceCut;if(t<=0||t>=.20)return;
  const energy=Math.sin(Math.PI*clamp(t/.20))*(1-clamp(t/.20));
  if(compositor){
   let base=compositor.snapshot();
   for(let n=0;n<3;n++){
    const oldIndex=Math.max(0,f-[1,3,5][n]),old=D.frames[oldIndex];ctx.globalAlpha=1;const previous=compositor.layoutFrame(`${mediaSource?.revision??0}:${oldIndex}`,()=>layout(old));
    const light=s.setup.group==='gray'&&s.setup.trailPolarity!=='light',color=s.setup.group==='gray'?[[96,101,102],[140,144,145],[177,180,180]][n]:s.setup.group==='blue'?[[30,95,160],[56,139,204],[128,184,235]][n]:[[144,32,30],[199,70,43],[239,130,74]][n];
    const image=compositor.effect(previous,2,color,light);
    ctx.clearRect(0,0,W,W);ctx.drawImage(base,0,0,W,W);ctx.save();ctx.globalAlpha=energy*[.65,.38,.21][n];
    const shift=s.setup.trailDirection*(n+1)*energy*155;
    if(s.setup.trailAxis==='y'){ctx.translate(540,540+shift);ctx.scale(1,1+energy*(n+1)*.12);ctx.drawImage(image,-540,-540,W,W);}
    else{ctx.translate(540+shift,540);ctx.scale(1+energy*(n+1)*.18,1);ctx.drawImage(image,-540,-540,W,W);}
    ctx.restore();if(n<2)base=compositor.snapshot();
   }
   ctx.globalAlpha=1;return;
  }
  baseCtx.clearRect(0,0,canvas.width,canvas.height);baseCtx.drawImage(canvas,0,0);
  for(let n=0;n<3;n++){
   const old=D.frames[Math.max(0,f-[1,3,5][n])];ctx.globalAlpha=1;layout(old);
   trailCtx.clearRect(0,0,384,384);trailCtx.drawImage(canvas,0,0,384,384);
   // Extract only the real dark subject. Light fields become transparent,
   // so an old crop rectangle cannot appear as a ghost panel.
   const light=s.setup.group==='gray'&&s.setup.trailPolarity!=='light',color=s.setup.group==='gray'?[[96,101,102],[140,144,145],[177,180,180]][n]:s.setup.group==='blue'?[[30,95,160],[56,139,204],[128,184,235]][n]:[[144,32,30],[199,70,43],[239,130,74]][n];
   const processed=gpu?.apply(trailImage,0,color,light);
   if(processed){trailCtx.clearRect(0,0,384,384);trailCtx.drawImage(processed,0,0);}else{const mask=trailCtx.getImageData(0,0,384,384),a=mask.data;for(let i=0;i<a.length;i+=4){const y=(a[i]*.2126+a[i+1]*.7152+a[i+2]*.0722);a[i+3]=255*clamp(light?(226-y)/200:(y-22)/190);a[i]=color[0];a[i+1]=color[1];a[i+2]=color[2];}trailCtx.clearRect(0,0,W,W);trailCtx.putImageData(mask,0,0);}
   ctx.clearRect(0,0,W,W);ctx.drawImage(trailBase,0,0,W,W);
   ctx.save();ctx.globalAlpha=energy*[.65,.38,.21][n];
   const shift=s.setup.trailDirection*(n+1)*energy*155;
   if(s.setup.trailAxis==='y'){ctx.translate(540,540+shift);ctx.scale(1,1+energy*(n+1)*.12);ctx.drawImage(trailImage,-540,-540,W,W);}
   else{ctx.translate(540+shift,540);ctx.scale(1+energy*(n+1)*.18,1);ctx.drawImage(trailImage,-540,-540,W,W);}
   ctx.restore();baseCtx.clearRect(0,0,canvas.width,canvas.height);baseCtx.drawImage(canvas,0,0);
  }
  ctx.globalAlpha=1;
 }
 function draw(time){
  compositor?.begin();
  const at=start+time,f=frameAt(time),s=D.frames[f],t=s.sinceCut;
  rawCtx.setTransform(1,0,0,1,0,0);rawCtx.clearRect(0,0,canvas.width,canvas.height);
  ctx.setTransform(short/W,0,0,short/W,0,0);
  ctx.globalAlpha=1;palette=s.setup.palette||palette;rect(0,0,W,W);
  const old=s.previous?D.frames[Math.max(0,f-Math.ceil(t*30)-1)]:null;
  if(old&&s.setup.transition==='iris'&&t<.14){
   const r=radius*expo(t/.14);layout(old);ctx.save();ctx.beginPath();ctx.arc(540,540,r,0,Math.PI*2);ctx.clip();layout(s);ctx.restore();
   if(s.setup.edgeAccent){ctx.save();ctx.strokeStyle=s.setup.edgeColors?.[1]||'#aaaaaa';ctx.lineWidth=1.6;ctx.beginPath();ctx.arc(540,540,r,0,Math.PI*.9);ctx.stroke();ctx.restore();}
  }else if(old&&s.setup.transition==='dissolve'&&t<.13){layout(old);ctx.globalAlpha=smooth(t/.13);layout(s);ctx.globalAlpha=1;}
  else if(old&&s.setup.transition==='push'&&t<.1){
   const p=expo(t/.1);layout(old,-W*p);ctx.save();ctx.beginPath();ctx.rect(W*(1-p),0,W,W);ctx.clip();layout(s,W*(1-p));ctx.restore();
   edge(s,W*(1-p),0,W*(1-p),W,.9);
  }else if(old&&s.setup.transition==='occlude'&&t<.16){
   layout(s);const p=out(t/.16),cuts=[0,270,510,810,1080];
   for(let i=0;i<4;i++){const h=W*(1-out(clamp(p-i*.085))),y=i%2?W-h:h;ctx.save();ctx.beginPath();ctx.rect(cuts[i],i%2?W-h:0,cuts[i+1]-cuts[i],h);ctx.clip();layout(old);ctx.restore();edge(s,cuts[i],y,cuts[i+1],y,.9);}
  }else layout(s);
  applyTrail(s,f);palette=s.setup.palette||palette;contour(s);burst(s);
  if(s.setup.blankFrames){const [a,b]=s.setup.blankFrames;if(t>=a/30&&t<b/30){rect(0,0,W,W);ctx.save();ctx.globalAlpha=.025;source(s,0,0,W,W,1);ctx.restore();}}
  if(s.setup.flashFrames&&t<s.setup.flashFrames/30){ctx.save();ctx.globalAlpha=.34;rect(0,0,W,W,'#d6d7d2');ctx.restore();}

  if(s.setup.finalRelease){const [a,b]=s.setup.finalRelease;if(at>a){ctx.globalAlpha=smooth((at-a)/(b-a));rect(0,0,W,W,s.setup.finalColor||'#faf8f2');ctx.globalAlpha=1;}}
  compositor?.present();
 }
 let queue=Promise.resolve(),lastDrawn=-1;
 const render=time=>{queue=queue.catch(()=>{}).then(async()=>{if(disposed)return;const f=frameAt(time);if(f===lastDrawn)return;await prepare(time);if(!disposed){draw(time);lastDrawn=f;}});return queue;};
 render.invalidate=()=>{lastDrawn=-1;};
 let wanted=null,pump=null;
 render.preview=time=>{wanted=time;if(!pump)pump=(async()=>{while(wanted!==null&&!disposed){const at=wanted;wanted=null;await render(at);}})().finally(()=>{pump=null;});return pump;};
 render.acceleration={effects:compositor?'webgl2-composite':gpu?'webgl2':'cpu',renderer:compositor?.renderer??gpu?.renderer??null};
 render.dispose=()=>{disposed=true;mediaColor.dispose();compositor?.dispose();gpu?.dispose();for(const f of Object.keys(images)){images[f]?.close?.();delete images[f];}};
 await render(0);return render;
}
