// GPU implementation of the small Canvas2D subset used by the material score.
// The score remains the owner of paths, timing and composition.
export function createMaterialGpu(output, enabled=true, direct) {
 if(direct===undefined){let probe;try{probe=createMaterialGpu(output,enabled,false);}catch{return null;}if(!probe)return null;probe.dispose();return createMaterialGpu(output,enabled,true);}
 if(!enabled)return null;
 const surface=direct?output:document.createElement('canvas');surface.width=output.width;surface.height=output.height;
 const gl=surface.getContext('webgl2',{alpha:true,antialias:false,premultipliedAlpha:true,preserveDrawingBuffer:true,failIfMajorPerformanceCaveat:true});
 if(!gl)return null;
 gl.disable(gl.DITHER);
 const debug=gl.getExtension('WEBGL_debug_renderer_info'),renderer=debug?gl.getParameter(debug.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);
 if(/swiftshader|llvmpipe|software/i.test(renderer)||gl.getParameter(gl.MAX_TEXTURE_SIZE)<2160||!gl.getExtension('EXT_color_buffer_float')){gl.getExtension('WEBGL_lose_context')?.loseContext();return null;}
 const shader=(type,text)=>{const s=gl.createShader(type);gl.shaderSource(s,text);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
 const program=(v,f)=>{const p=gl.createProgram(),vs=shader(gl.VERTEX_SHADER,v),fs=shader(gl.FRAGMENT_SHADER,f);gl.attachShader(p,vs);gl.attachShader(p,fs);gl.linkProgram(p);gl.deleteShader(vs);gl.deleteShader(fs);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));return p;};
 let paint,stats;
 try{
 paint=program(`#version 300 es
 in vec2 position;in vec2 coordinate;uniform vec2 resolution;out vec2 uv;
 void main(){uv=coordinate;gl_Position=vec4(position.x/resolution.x*2.-1.,1.-position.y/resolution.y*2.,0.,1.);}`,
 `#version 300 es
 precision highp float;uniform sampler2D picture,summary,conditionPicture,regionPicture;uniform int mode,conditional,regionIndex;uniform vec4 regionCrop;uniform vec2 regionOrigin,regionLimit;uniform vec4 color;uniform float opacity,light,ceiling;in vec2 uv;out vec4 result;
 void main(){if(conditional>0){vec4 z=texture(conditionPicture,vec2(.5,.25));if(conditional==1&&z.r/max(1.,z.g)<.12||conditional==2&&z.a<60.)discard;}vec2 at=uv;if(regionIndex>=0){vec4 r=texture(regionPicture,vec2(.5,(float(regionIndex)+.5)/2.));vec2 corrected=clamp(r.xy+regionCrop.xy-regionOrigin,vec2(0.),regionLimit);at+=vec2((corrected.x-regionCrop.x)/regionCrop.z,-(corrected.y-regionCrop.y)/regionCrop.w);}vec4 c=texture(picture,at);float y=dot(c.rgb,vec3(.2126,.7152,.0722))*255.;
 if(mode==1)c=color;
 else if(mode==2){float a=clamp(light>.5?(226.-y)/200.:(y-22.)/190.,0.,1.);c=vec4(color.rgb*a,a);}
 else if(mode==3){float a=clamp((y-6.)/18.,0.,1.);c=vec4((1.-c.rgb)*a,a);}
 else if(mode==4){vec2 z=texture(summary,vec2(.5)).rg;float threshold=z.x/max(1.,z.y)*.99;float a=clamp((threshold-y)/max(12.,threshold*.24),0.,1.);c=vec4(c.rgb*a,a);}
 result=c*opacity;}`);
 stats=program(`#version 300 es
 void main(){vec2 p=vec2(float((gl_VertexID<<1)&2),float(gl_VertexID&2));gl_Position=vec4(p*2.-1.,0.,1.);}`,
 `#version 300 es
 precision highp float;uniform sampler2D picture,summary;uniform ivec2 sourceSize;uniform int mode,side,margin,stepSize;uniform float ceiling;out vec4 result;
 float luma(ivec2 p){return dot(texelFetch(picture,ivec2(p.x,sourceSize.y-1-p.y),0).rgb,vec3(.2126,.7152,.0722))*255.;}
 void main(){ivec2 p=ivec2(gl_FragCoord.xy);result=vec4(0.);
 if(mode==4){float best=-1.;ivec2 origin=ivec2(0);vec4 previous=texture(summary,vec2(.5));for(int y=0;y<12;y++)for(int x=0;x<12;x++){if(x>=sourceSize.x||y>=sourceSize.y)continue;vec2 candidate=vec2(margin)+vec2(x,y)*float(stepSize);float v=texelFetch(picture,ivec2(x,y),0).r;if(p.y==1&&distance(candidate,previous.xy)<=float(side)/80.*70.)continue;if(v>best){best=v;origin=ivec2(candidate);}}result=vec4(origin,float(side),best);return;}
if(mode==3){ivec2 origin=ivec2(margin)+p*stepSize;float sum=0.,sq=0.,count=0.;for(int y=0;y<80;y+=7)for(int x=0;x<80;x+=7){if(x>=side||y>=side)continue;float v=luma(origin+ivec2(x,y));sum+=v;sq+=v*v;count++;}result=vec4(sq/count-pow(sum/count,2.),0.,0.,1.);return;}
 for(int y=0;y<2;y++)for(int x=0;x<2;x++){ivec2 q=p*2+ivec2(x,y);if(any(greaterThanEqual(q,sourceSize)))continue;
 if(mode==0)result.rg+=vec2(luma(q),1.);
 else if(mode==2){vec2 z=texture(summary,vec2(.5)).rg;float threshold=z.x/max(1.,z.y)*.99;result.rg+=vec2(clamp((threshold-luma(q))/max(12.,threshold*.24),0.,1.)>.25?1.:0.,1.);}
 else result.rg+=texelFetch(picture,q,0).rg;}}
 `);
 }catch{gl.getExtension('WEBGL_lose_context')?.loseContext();return null;}
 const locs=p=>Object.fromEntries(['resolution','picture','summary','conditionPicture','regionPicture','conditional','regionIndex','regionCrop','regionOrigin','regionLimit','mode','color','opacity','light','ceiling','sourceSize','side','margin','stepSize'].map(n=>[n,gl.getUniformLocation(p,n)]));
 const u=locs(paint),su=locs(stats),buffer=gl.createBuffer(),vao=gl.createVertexArray();gl.bindVertexArray(vao);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
 for(const [name,offset]of [['position',0],['coordinate',8]]){const a=gl.getAttribLocation(paint,name);gl.enableVertexAttribArray(a);gl.vertexAttribPointer(a,2,gl.FLOAT,false,16,offset);}
 gl.useProgram(paint);for(const [name,unit]of [['picture',0],['summary',1],['conditionPicture',2],['regionPicture',3]])gl.uniform1i(u[name],unit);
 const uniformCache=new Map();
 const scalar=(name,value)=>{if(uniformCache.get(name)!==value){uniformCache.set(name,value);gl.uniform1i(u[name],value);}};
 const number=(name,value)=>{if(uniformCache.get(name)!==value){uniformCache.set(name,value);gl.uniform1f(u[name],value);}};
 const vector=(name,values)=>{const key=values.join(',');if(uniformCache.get(name)!==key){uniformCache.set(name,key);if(values.length===4)gl.uniform4fv(u[name],values);else gl.uniform2fv(u[name],values);}};
 const resources=[],imageTextures=new Map(),temps=new Map(),tempUsed=new Map(),reductions=new Map();
 const texture=(width,height,float=false,allocate=true)=>{const tex=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,tex);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,float?gl.NEAREST:gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,float?gl.NEAREST:gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);if(allocate)gl.texImage2D(gl.TEXTURE_2D,0,float?gl.RGBA32F:gl.RGBA8,width,height,0,gl.RGBA,float?gl.FLOAT:gl.UNSIGNED_BYTE,null);return tex;};
 const target=(width,height,float=false)=>{const t={width,height,tex:texture(width,height,float),fbo:gl.createFramebuffer()};gl.bindFramebuffer(gl.FRAMEBUFFER,t.fbo);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,t.tex,0);if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('GPU material framebuffer unavailable');resources.push(t);return t;};
 const resolved=target(output.width,output.height),main=gl.createFramebuffer(),samples=Math.min(4,gl.getParameter(gl.MAX_SAMPLES));
 const colorBuffer=gl.createRenderbuffer(),stencilBuffer=gl.createRenderbuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,main);gl.bindRenderbuffer(gl.RENDERBUFFER,colorBuffer);gl.renderbufferStorageMultisample(gl.RENDERBUFFER,samples,gl.RGBA8,output.width,output.height);gl.framebufferRenderbuffer(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.RENDERBUFFER,colorBuffer);gl.bindRenderbuffer(gl.RENDERBUFFER,stencilBuffer);gl.renderbufferStorageMultisample(gl.RENDERBUFFER,samples,gl.DEPTH24_STENCIL8,output.width,output.height);gl.framebufferRenderbuffer(gl.FRAMEBUFFER,gl.DEPTH_STENCIL_ATTACHMENT,gl.RENDERBUFFER,stencilBuffer);
 if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE){gl.getExtension('WEBGL_lose_context')?.loseContext();return null;}
 const temporary=(w,h)=>{const key=w+'x'+h,index=tempUsed.get(key)||0;tempUsed.set(key,index+1);let pool=temps.get(key);if(!pool){pool=[];temps.set(key,pool);}return pool[index]||(pool[index]=target(w,h));};
 const bind=t=>{gl.bindFramebuffer(gl.FRAMEBUFFER,t===null?null:t==='main'?main:t.fbo);gl.viewport(0,0,t==='main'||t===null?output.width:t.width,t==='main'||t===null?output.height:t.height);};
 const resolve=()=>{gl.bindFramebuffer(gl.READ_FRAMEBUFFER,main);gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER,resolved.fbo);gl.blitFramebuffer(0,0,output.width,output.height,0,0,output.width,output.height,gl.COLOR_BUFFER_BIT,gl.NEAREST);return resolved;};
 const parseColor=value=>{if(Array.isArray(value))return value;const text=String(value);if(text[0]==='#'){const h=text.slice(1),n=h.length===3?h.split('').map(x=>x+x).join(''):h;return [parseInt(n.slice(0,2),16)/255,parseInt(n.slice(2,4),16)/255,parseInt(n.slice(4,6),16)/255,1];}const a=text.match(/[\d.]+/g)?.map(Number)||[0,0,0];return[a[0]/255,a[1]/255,a[2]/255,a[3]??1];};
 let state={matrix:[1,0,0,1,0,0],alpha:1,fill:'#000000',stroke:'#000000',width:1,condition:null,font:'10px sans-serif',clips:[]},stack=[],path=[],dirtyClip=true,appliedClips=null;
 const point=(x,y)=>{const [a,b,c,d,e,f]=state.matrix;return[a*x+c*y+e,b*x+d*y+f];};
 const multiply=([a,b,c,d,e,f])=>{const [A,B,C,D,E,F]=state.matrix;state.matrix=[A*a+C*b,B*a+D*b,A*c+C*d,B*c+D*d,A*e+C*f+E,B*e+D*f+F];};
 const vertices=(points,coordinates)=>points.flatMap((p,i)=>[p[0],p[1],...(coordinates?.[i]||[0,0])]);
 const primitive=(points,coordinates,tex,mode,color,alpha,targetName='main',extra={})=>{if(points.length===4&&!extra.triangles&&points[0][0]===0&&points[0][1]===0&&points[1][1]===0&&points[3][0]===0&&points[2][0]===(targetName==='main'||targetName===null?output.width:targetName.width)&&points[2][1]===(targetName==='main'||targetName===null?output.height:targetName.height)){points=[points[0],points[1].map((v,i)=>2*v-points[0][i]),points[3].map((v,i)=>2*v-points[0][i])];if(coordinates)coordinates=[coordinates[0],coordinates[1].map((v,i)=>2*v-coordinates[0][i]),coordinates[3].map((v,i)=>2*v-coordinates[0][i])];extra={...extra,triangles:true};}if(points.length===4&&!extra.triangles){const order=[0,1,2,0,2,3];points=order.map(i=>points[i]);if(coordinates)coordinates=order.map(i=>coordinates[i]);extra={...extra,triangles:true};}bind(targetName);gl.useProgram(paint);gl.bindVertexArray(vao);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(vertices(points,coordinates)),gl.STREAM_DRAW);vector('resolution',[targetName==='main'||targetName===null?output.width:targetName.width,targetName==='main'||targetName===null?output.height:targetName.height]);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,tex||resolved.tex);gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,extra.summary?.tex||resolved.tex);const condition=targetName==='main'?state.condition:null;gl.activeTexture(gl.TEXTURE2);gl.bindTexture(gl.TEXTURE_2D,condition?.texture.tex||resolved.tex);scalar('conditional',condition?.kind||0);gl.activeTexture(gl.TEXTURE3);gl.bindTexture(gl.TEXTURE_2D,extra.region?.texture.tex||resolved.tex);scalar('regionIndex',extra.region?.index??-1);if(extra.region){gl.uniform4fv(u.regionCrop,extra.region.crop);gl.uniform2fv(u.regionOrigin,extra.region.origin);gl.uniform2fv(u.regionLimit,extra.region.limit);}scalar('mode',mode);vector('color',color);number('opacity',alpha);number('light',extra.light?1:0);number('ceiling',extra.ceiling||0);gl.drawArrays(extra.triangles?gl.TRIANGLES:gl.TRIANGLE_FAN,0,points.length);};
 const clipState=()=>{if(!dirtyClip)return;bind('main');if(!state.clips.length){gl.disable(gl.STENCIL_TEST);gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);appliedClips=[];dirtyClip=false;return;}if(appliedClips&&appliedClips.length===state.clips.length&&state.clips.every((p,i)=>p===appliedClips[i])){gl.enable(gl.STENCIL_TEST);gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);dirtyClip=false;return;}appliedClips=state.clips.slice();gl.disable(gl.BLEND);gl.enable(gl.STENCIL_TEST);gl.stencilMask(255);gl.clearStencil(0);gl.clear(gl.STENCIL_BUFFER_BIT);gl.colorMask(false,false,false,false);for(let i=0;i<state.clips.length;i++){gl.stencilFunc(gl.EQUAL,i,255);gl.stencilOp(gl.KEEP,gl.KEEP,gl.INCR);primitive(state.clips[i],null,null,1,[0,0,0,0],1);}gl.colorMask(true,true,true,true);gl.stencilMask(0);gl.stencilFunc(gl.EQUAL,state.clips.length,255);gl.stencilOp(gl.KEEP,gl.KEEP,gl.KEEP);gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);dirtyClip=false;};
 const quad=(x,y,w,h)=>[[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
 const copy=(source,t,mode=0,color=[0,0,0,1],extra={})=>{gl.disable(gl.STENCIL_TEST);gl.disable(gl.BLEND);primitive(quad(0,0,t.width,t.height),[[0,1],[1,1],[1,0],[0,0]],source.tex,mode,color,1,t,extra);dirtyClip=true;return t;};
 const snapshot=(width=output.width,height=output.height)=>copy(resolve(),temporary(width,height));
 const obtain=source=>{if(source?.tex)return source;if(source===output||source===surface)return resolve();let t=imageTextures.get(source);if(t){imageTextures.delete(source);imageTextures.set(source,t);return t;}t={tex:texture(source.width,source.height,false,false),width:source.width,height:source.height,flipped:false};gl.bindTexture(gl.TEXTURE_2D,t.tex);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,source instanceof HTMLCanvasElement);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,source);imageTextures.set(source,t);while(imageTextures.size>16){const [key,value]=imageTextures.entries().next().value;gl.deleteTexture(value.tex);imageTextures.delete(key);}return t;};
 const fonts=new Map();
 const ctx={
  save(){stack.push({...state,matrix:state.matrix.slice(),clips:state.clips.slice()});},restore(){if(stack.length){const previous=state.clips;state=stack.pop();if(previous.length!==state.clips.length||previous.some((p,i)=>p!==state.clips[i]))dirtyClip=true;}},
  setTransform(a,b,c,d,e,f){state.matrix=[a,b,c,d,e,f];},translate(x,y){multiply([1,0,0,1,x,y]);},scale(x,y){multiply([x,0,0,y,0,0]);},rotate(a){multiply([Math.cos(a),Math.sin(a),-Math.sin(a),Math.cos(a),0,0]);},
  beginPath(){path=[];},moveTo(x,y){path.push([point(x,y)]);},lineTo(x,y){if(!path.length)path.push([]);path.at(-1).push(point(x,y));},closePath(){if(path.at(-1)?.length)path.at(-1).push(path.at(-1)[0]);},
  rect(x,y,w,h){path.push(quad(x,y,w,h).map(p=>point(...p)));},
  arc(x,y,r,a,b){const count=Math.max(8,Math.ceil(Math.abs(b-a)*r/12));if(!path.length)path.push([]);for(let i=0;i<=count;i++)path.at(-1).push(point(x+r*Math.cos(a+(b-a)*i/count),y+r*Math.sin(a+(b-a)*i/count)));},
  bezierCurveTo(x1,y1,x2,y2,x3,y3){const p=path.at(-1),a=p.at(-1),b=point(x1,y1),c=point(x2,y2),d=point(x3,y3);for(let i=1;i<=24;i++){const t=i/24,k=1-t;p.push([k*k*k*a[0]+3*k*k*t*b[0]+3*k*t*t*c[0]+t*t*t*d[0],k*k*k*a[1]+3*k*k*t*b[1]+3*k*t*t*c[1]+t*t*t*d[1]]);}},
  clip(){for(const p of path)if(p.length>2)state.clips.push(p.slice());dirtyClip=true;},
  fillRect(x,y,w,h){clipState();const c=parseColor(state.fill);primitive(quad(x,y,w,h).map(p=>point(...p)),null,null,1,[c[0]*c[3],c[1]*c[3],c[2]*c[3],c[3]],state.alpha);},
  clearRect(x,y,w,h){clipState();gl.disable(gl.BLEND);primitive(quad(x,y,w,h).map(p=>point(...p)),null,null,1,[0,0,0,0],1);gl.enable(gl.BLEND);},
  drawImage(source,...a){const t=obtain(source);let sx=0,sy=0,sw=t.width,sh=t.height,x,y,w,h;if(a.length===2){[x,y]=a;w=sw;h=sh;}else if(a.length===4)[x,y,w,h]=a;else [sx,sy,sw,sh,x,y,w,h]=a;const corners=quad(x,y,w,h).map(p=>point(...p)),last=state.clips.at(-1);if(last?.length===4&&last.every((p,i)=>p[0]===corners[i][0]&&p[1]===corners[i][1])){state.clips.pop();dirtyClip=true;}clipState();primitive(corners,[[sx/t.width,t.flipped===false?sy/t.height:1-sy/t.height],[(sx+sw)/t.width,t.flipped===false?sy/t.height:1-sy/t.height],[(sx+sw)/t.width,t.flipped===false?(sy+sh)/t.height:1-(sy+sh)/t.height],[sx/t.width,t.flipped===false?(sy+sh)/t.height:1-(sy+sh)/t.height]],t.tex,0,[0,0,0,1],state.alpha,'main',source.region?{region:{...source.region,crop:[sx,sy,t.width,t.height],limit:[t.width-sw,t.height-sh]}}:{});},
  stroke(){clipState();const c=parseColor(state.stroke),m=state.matrix,width=state.width*Math.sqrt(Math.abs(m[0]*m[3]-m[1]*m[2])),points=[];for(const p of path)for(let i=1;i<p.length;i++){const a=p[i-1],b=p[i],dx=b[0]-a[0],dy=b[1]-a[1],len=Math.hypot(dx,dy)||1,nx=-dy/len*width/2,ny=dx/len*width/2,A=[a[0]+nx,a[1]+ny],B=[b[0]+nx,b[1]+ny],C=[b[0]-nx,b[1]-ny],D=[a[0]-nx,a[1]-ny];points.push(A,B,C,A,C,D);}if(points.length)primitive(points,null,null,1,[c[0]*c[3],c[1]*c[3],c[2]*c[3],c[3]],state.alpha,'main',{triangles:true});},
  strokeRect(x,y,w,h){const previous=path;path=[quad(x,y,w,h).map(p=>point(...p))];path[0].push(path[0][0]);ctx.stroke();path=previous;},
  fillText(text,x,y){const key=state.font+'|'+state.fill+'|'+text;let image=fonts.get(key);if(!image){image=document.createElement('canvas');const q=image.getContext('2d');q.font=state.font;image.width=Math.ceil(q.measureText(text).width)+4;image.height=24;q.font=state.font;q.fillStyle=state.fill;q.fillText(text,2,18);fonts.set(key,image);}ctx.drawImage(image,x-2,y-18);},
 };
 for(const [name,key]of [['globalAlpha','alpha'],['fillStyle','fill'],['strokeStyle','stroke'],['lineWidth','width'],['font','font']])Object.defineProperty(ctx,name,{get:()=>state[key],set:value=>{state[key]=value;}});
 const statDraw=(source,t,mode,summary)=>{bind(t);gl.disable(gl.STENCIL_TEST);gl.disable(gl.BLEND);gl.useProgram(stats);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,source.tex);gl.uniform1i(su.picture,0);gl.uniform2i(su.sourceSize,source.width,source.height);gl.uniform1i(su.mode,mode);gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,summary?.tex||resolved.tex);gl.uniform1i(su.summary,1);gl.drawArrays(gl.TRIANGLES,0,3);dirtyClip=true;};
 const reductionTarget=(key,w,h)=>{let t=reductions.get(key);if(!t){t=target(w,h,true);reductions.set(key,t);}return t;};
 const reduce=(source,mode,summary)=>{let s=source,first=true;do{const w=Math.ceil(s.width/2),h=Math.ceil(s.height/2),t=reductionTarget(mode+':'+w+'x'+h,w,h);statDraw(s,t,first?mode:1,summary);s=t;first=false;}while(s.width>1||s.height>1);return s;};
 const regions=source=>{const scale=source.width/384,side=Math.round(80*scale),margin=Math.round(16*scale),step=Math.round(32*scale),n=Math.floor((source.width-side-2*margin)/step)+1,t=reductionTarget('regions'+n,n,n);gl.useProgram(stats);gl.uniform1i(su.side,side);gl.uniform1i(su.margin,margin);gl.uniform1i(su.stepSize,step);statDraw(source,t,3);const first=reductionTarget('regionFirst',1,1),both=reductionTarget('regionBoth',1,2);statDraw(t,first,4);statDraw(t,both,4,first);return{texture:both,origin:[margin,margin],regions:[{x:margin,y:margin,side},{x:margin,y:margin,side}],variance:Infinity};};
 const layoutFrames=new Map();

 let display=null;
 const batch=(p,vertices,coordinates)=>{const t=obtain(p.im);clipState();primitive(vertices,coordinates.map(([x,y])=>[(p.sx+x*p.sw)/t.width,t.flipped===false?(p.sy+y*p.sh)/t.height:1-(p.sy+y*p.sh)/t.height]),t.tex,0,[0,0,0,1],state.alpha,'main',{triangles:true});};
 return {ctx,renderer,
  radial(p,n,angle,center=[540,540],R=820){const vertices=[],uv=[],step=Math.PI*2/n;for(let i=0;i<n;i++){const a=angle+i*step,cos=Math.cos(a),sin=Math.sin(a),transform=([x,y])=>point(center[0]+x*cos-y*sin,center[1]+x*sin+y*cos),coordinate=([x,y])=>[(x+R)/(2*R),((i%2?-y:y)+R)/(2*R)],count=Math.max(2,Math.ceil(step*R/48));for(let j=0;j<count;j++){const start=-step/2-.002+(step+.004)*j/count,end=-step/2-.002+(step+.004)*(j+1)/count,points=[[0,0],[R*Math.cos(start),R*Math.sin(start)],[R*Math.cos(end),R*Math.sin(end)]];vertices.push(...points.map(transform));uv.push(...points.map(coordinate));}}batch(p,vertices,uv);},
  fourfold(p,angle,center=[540,540],R=820){const vertices=[],uv=[],cos=Math.cos(angle),sin=Math.sin(angle);for(const x of [-1,1])for(const y of [-1,1]){const transform=([a,b])=>point(center[0]+x*a*cos-y*b*sin,center[1]+x*a*sin+y*b*cos),points=[[0,0],[R,0],[R,R],[0,0],[R,R],[0,R]];vertices.push(...points.map(transform));uv.push(...points.map(([a,b])=>[a/R,b/R]));}batch(p,vertices,uv);},
  begin(){tempUsed.clear();uniformCache.clear();bind('main');gl.invalidateFramebuffer(gl.FRAMEBUFFER,[gl.COLOR_ATTACHMENT0,gl.DEPTH_STENCIL_ATTACHMENT]);gl.colorMask(true,true,true,true);gl.stencilMask(255);gl.clearColor(0,0,0,0);gl.clearStencil(0);gl.clear(gl.COLOR_BUFFER_BIT|gl.STENCIL_BUFFER_BIT);appliedClips=null;dirtyClip=true;},snapshot,
  effect(source,mode,color=[0,0,0],light=false,ceiling=0,summary=null){return copy(source,temporary(source.width,source.height),mode,[...color.map(v=>v/255),1],{light,ceiling,summary});},
  landscape(source){const summary=reduce(source,0);return{summary,occupied:reduce(source,2,summary)};},regions,
  condition(texture,kind){state.condition={texture,kind};},
  regionImage(image,selection,index){return{...image,region:{texture:selection.texture,index,origin:selection.origin}};},
  layoutFrame(id,draw){let t=layoutFrames.get(id);if(t){layoutFrames.delete(id);layoutFrames.set(id,t);return t;}draw();if(layoutFrames.size>=8){const key=layoutFrames.keys().next().value;t=layoutFrames.get(key);layoutFrames.delete(key);}else t=target(384,384);copy(resolve(),t);layoutFrames.set(id,t);return t;},
  present(){if(gl.isContextLost())throw Error('Material GPU context lost');if(direct){gl.bindFramebuffer(gl.READ_FRAMEBUFFER,main);gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER,null);gl.blitFramebuffer(0,0,output.width,output.height,0,0,output.width,output.height,gl.COLOR_BUFFER_BIT,gl.NEAREST);}else{copy(resolve(),{width:output.width,height:output.height,fbo:null});display ||= output.getContext('2d');display.setTransform(1,0,0,1,0,0);display.globalAlpha=1;display.clearRect(0,0,output.width,output.height);display.drawImage(surface,0,0);}},
  dispose(){for(const t of resources){gl.deleteTexture(t.tex);gl.deleteFramebuffer(t.fbo);}for(const t of imageTextures.values())gl.deleteTexture(t.tex);gl.deleteRenderbuffer(colorBuffer);gl.deleteRenderbuffer(stencilBuffer);gl.deleteFramebuffer(main);gl.deleteProgram(paint);gl.deleteProgram(stats);gl.deleteBuffer(buffer);gl.deleteVertexArray(vao);if(!direct)gl.getExtension('WEBGL_lose_context')?.loseContext();},
 };
}









