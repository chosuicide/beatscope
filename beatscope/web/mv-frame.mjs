import {createGlitchVisual} from './mv-visual.js';
export function createMovie(canvas, map, track, plan) {
  const source=document.createElement('canvas');source.width=source.height=1080;
  const visual=createGlitchVisual(source,map,t=>({timing:track.at(t)})), ctx=canvas.getContext('2d');
  const render=t=>{
    const shot=plan.shots.find(s=>t>=s.start&&t<s.end)??plan.shots.at(-1);
    const e=plan.details.findLast(e=>e.time<=t),age=e?t-e.time:99;
    const hit=Math.max(0,1-age/.16)*(e?.response_relevance??0);
    visual.renderAt(t,{world:shot.world,worldStart:shot.start,pump:1,invert:0,glitch:.12+hit*.72});
    ctx.clearRect(0,0,1080,1080);ctx.drawImage(source,0,0);
    if(e&&e.id%5===0&&age<.24){const x=e.id%2?720:0;ctx.save();ctx.beginPath();ctx.rect(x,0,360,1080);ctx.clip();ctx.translate(x+360,0);ctx.scale(-1,1);ctx.drawImage(source,360,0,360,1080,0,0,360,1080);ctx.restore();}
  };
  render.dispose=()=>{try{visual.dispose&&visual.dispose();}catch(error){/* already gone */}};
  return render;
}
