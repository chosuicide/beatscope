// Geometry is teaching material only; production renderers provide their own world.
export function demoTiming(score){
 const onsets=score.demo.audioEvents.map((e,id)=>({id,time:e.time,strength:e.gain??.3}));
 const map={duration:2,source:{duration:2,sha256:'tutorial-synthetic'},beats:[0,.5,1,1.5].map((time,index)=>({time,index})),onsets};
 return {RHYTHM_MAP:map,getVisualState:time=>({time})};
}
export function draw(canvas,state,time){
 const q=canvas.getContext('2d'),w=canvas.width,h=canvas.height,v=state.values,mode=state.view.setup.mode;
 q.setTransform(1,0,0,1,0,0);q.fillStyle='#ebe9e3';q.fillRect(0,0,w,h);
 const scale=Math.min(w,h)/640;
 q.save();q.translate(w/2,h/2);q.scale(scale,scale);
 const circle=(x,y,r,color='#25262a')=>{q.fillStyle=color;q.beginPath();q.arc(x,y,r,0,Math.PI*2);q.fill();};
 const line=(x1,y1,x2,y2,alpha=1)=>{q.save();q.globalAlpha=alpha;q.strokeStyle='#25262a';q.lineWidth=2;q.beginPath();q.moveTo(x1,y1);q.lineTo(x2,y2);q.stroke();q.restore();};
 if(mode==='transition'){
  circle(-65,0,94);line(-190,160,190,160);
  q.save();q.beginPath();q.rect(-w/(2*scale),-h/(2*scale),w/scale*(v['world.cover']??0),h/scale);q.clip();
  q.fillStyle='#25262a';q.fillRect(-w/scale,-h/scale,w*2/scale,h*2/scale);q.fillStyle='#ebe9e3';q.fillRect(0,-88,145,176);line(-190,160,190,-160);q.restore();
 }else{
  const size=v['actor.scale']??1;
  circle(0,0,88*size);
  q.fillStyle='#ebe9e3';q.fillRect((mode==='return'?(v['detail.direction']??0)*30:0)-32,-12,64,24);
  if(mode==='accent'||mode==='buildup'){const impact=Math.max(0,size-1);q.strokeStyle='#25262a';q.lineWidth=2;for(let i=0;i<8;i++){const a=i*Math.PI/4;line(Math.cos(a)*(120+impact*20),Math.sin(a)*(120+impact*20),Math.cos(a)*(120+impact*110),Math.sin(a)*(120+impact*110),Math.min(1,impact*3));}}
  if(mode==='dense'){const tick=v['detail.tick']??0;for(let i=0;i<8;i++){const a=i*Math.PI/4;circle(Math.cos(a)*(150+tick*12),Math.sin(a)*(150+tick*12),3+tick*4);}}
  if(mode==='pause')line(-160,150,160,150+Math.sin(time*7)*3);
  if(mode==='return'){line(-180,150,180,150);line(-180,-150,180,-150,v['thread.alpha']??1);}
  if(mode==='buildup'){const order=v['world.order']??0;for(let i=0;i<4;i++)circle(-190+i*128,190,4+order*2);}
 }
 q.restore();
}
