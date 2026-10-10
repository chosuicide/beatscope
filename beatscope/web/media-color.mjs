// Palette chroma follows source luminance, preserving light/dark detail.
// One GPU surface is reused; at most four immutable outputs stay cached.
const luma=c=>c[0]*.2126+c[1]*.7152+c[2]*.0722;
const rgb=hex=>{if(/^#[\da-f]{3}$/i.test(hex))hex='#'+hex.slice(1).split('').map(c=>c+c).join('');return [1,3,5].map(i=>parseInt((hex??'').slice(i,i+2),16)/255);};
export function createMediaColor(gpu=true){
 const cache=[];let gl=null,surface=null,program=null,texture=null,locations=null,initialized=false;
 function init(){if(!gpu||initialized)return;initialized=true;try{
  surface=document.createElement('canvas');gl=surface.getContext('webgl2',{alpha:true,premultipliedAlpha:false,antialias:false,preserveDrawingBuffer:true});
  if(gl){
   const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
   const v=shader(gl.VERTEX_SHADER,`#version 300 es
   out vec2 uv;void main(){vec2 p=vec2(float((gl_VertexID<<1)&2),float(gl_VertexID&2));uv=p;gl_Position=vec4(p*2.-1.,0.,1.);}`);
   const f=shader(gl.FRAGMENT_SHADER,`#version 300 es
   precision highp float;uniform sampler2D image;uniform vec3 low,mid,high;uniform float amount;in vec2 uv;out vec4 result;
   void main(){vec4 c=texture(image,vec2(uv.x,1.-uv.y));vec3 weights=vec3(.2126,.7152,.0722);float y=dot(c.rgb,weights);vec3 tint=y<.5?mix(low,mid,y*2.):mix(mid,high,(y-.5)*2.);vec3 target=clamp(vec3(y)+tint-dot(tint,weights),0.,1.);result=vec4(mix(c.rgb,target,amount),c.a);}`);
   program=gl.createProgram();gl.attachShader(program,v);gl.attachShader(program,f);gl.linkProgram(program);gl.deleteShader(v);gl.deleteShader(f);
   if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
   locations=Object.fromEntries(['image','low','mid','high','amount'].map(k=>[k,gl.getUniformLocation(program,k)]));
   texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
  }
 }catch{gl?.getExtension('WEBGL_lose_context')?.loseContext();gl=null;surface=null;}}
 return {
  at(bitmap,palette,settings){
   const strength=settings?.enabled?settings.strength:0;
   if(!(strength>0))return bitmap;
   init();
   const colors=[palette.base,palette.accent,palette.secondary].map(rgb).sort((a,b)=>luma(a)-luma(b));
   if(colors.some(c=>c.some(v=>!Number.isFinite(v))))return bitmap;
   const key=colors.flat().join(',')+':'+strength;
   const index=cache.findIndex(c=>c.bitmap===bitmap&&c.key===key);
   if(index>=0){const [entry]=cache.splice(index,1);cache.push(entry);return entry.canvas;}
   const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;const ctx=canvas.getContext('2d',{willReadFrequently:!gl});
   if(gl&&!gl.isContextLost()){
    surface.width=bitmap.width;surface.height=bitmap.height;gl.viewport(0,0,surface.width,surface.height);gl.useProgram(program);gl.bindTexture(gl.TEXTURE_2D,texture);gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,bitmap);
    gl.uniform1i(locations.image,0);gl.uniform3fv(locations.low,colors[0]);gl.uniform3fv(locations.mid,colors[1]);gl.uniform3fv(locations.high,colors[2]);gl.uniform1f(locations.amount,strength);gl.drawArrays(gl.TRIANGLES,0,3);ctx.drawImage(surface,0,0);
   }else{
    ctx.drawImage(bitmap,0,0);const pixels=ctx.getImageData(0,0,canvas.width,canvas.height),d=pixels.data;
    for(let i=0;i<d.length;i+=4){const y=(d[i]*.2126+d[i+1]*.7152+d[i+2]*.0722)/255,k=y<.5?0:1,p=y<.5?y*2:(y-.5)*2;const tint=colors[k].map((v,j)=>v+(colors[k+1][j]-v)*p),lum=luma(tint);
     for(let j=0;j<3;j++){const target=Math.max(0,Math.min(1,y+tint[j]-lum))*255;d[i+j]+=strength*(target-d[i+j]);}
    }ctx.putImageData(pixels,0,0);
   }
   cache.push({bitmap,key,canvas});while(cache.length>4){const old=cache.shift();old.canvas.width=old.canvas.height=0;}
   return canvas;
  },
  clear(){for(const c of cache)c.canvas.width=c.canvas.height=0;cache.length=0;},
  dispose(){this.clear();gl?.getExtension('WEBGL_lose_context')?.loseContext();gl=null;surface=null;}
 };
}
