import {createEditScore} from '../runtime/edit-score.js';
export function makeMaterialScore(plan,library,setups,template){
 const modes=['full','liquidWindow','macro','mirrorSeam','full','kaleid','liquidSweep','inward','liquidRemnant','full','liquidTwin','centerFold','liquidNeedle'];
 const palettes={gray:{base:'#d7ddde',accent:'#e2e7e7',secondary:'#a7afb0'},blue:{base:'#061528',accent:'#167ce0',secondary:'#154975'},red:{base:'#23070c',accent:'#fa5327',secondary:'#882323'}};
 const counters={gray:0,blue:0,red:0},families=new Map(),motifs={},spans={},visitInfo=[];let lastBurst=-5;
 for(const visit of plan.shots){const family=visit.stageId??visit.family;if(!families.has(family))families.set(family,families.size);
  const group=template==='material-mix'?['gray','blue','red'][families.get(family)%3]:template.replace('material-',''),n=counters[group]++,motif=Math.floor(n/4),key=`${group}:${motif}`;
  spans[key]=(spans[key]??0)+visit.end-visit.start;visitInfo.push({group,n,motif});
 }
 const shots=plan.shots.map((visit,i)=>{
  const {group,n,motif}=visitInfo[i];
  const pool=library.assets.filter(a=>a.group===group),videos=pool.filter(a=>a.kind==='video'),photos=pool.filter(a=>a.kind!=='video');
  const photoMotif=motif%5===4&&photos.length,choices=photoMotif?photos:videos;
  const len=visit.end-visit.start;
  let asset=choices[((photoMotif?Math.floor(motif/5):motif-Math.floor(motif/5))+(plan.seed>>>0))%choices.length];
  // A photograph is a short insert, never the source of a long music passage.
  if(asset.kind!=='video'&&spans[`${group}:${motif}`]>.9)asset=videos[(motif+(plan.seed>>>0))%videos.length];
  if(asset.id==='birdA'&&spans[`${group}:${motif}`]>1.2)asset=videos.find(a=>a.id==='redFluid')??asset;
  if(asset.id==='fluidC'&&spans[`${group}:${motif}`]>2)asset=videos.find(a=>a.id==='inkD')??asset;
  if(group==='gray'&&len>2.5&&['water','birdB'].includes(asset.id)){
   const sustained=videos.filter(a=>!['water','birdB'].includes(a.id));asset=sustained[motif%sustained.length];
  }
  let mode=n%4===0?'full':modes[n%modes.length];
  if(mode.startsWith('liquid')&&!['water','rippleA','monoInk','ink','inkA','inkB','inkD','fluidC','smoke','foil','inkVeil','bubbleFilm','bubbleSwirl','oilBubbles'].includes(asset.id))mode=['macro','mirrorSeam','kaleid','inward'][n%4];
  if(asset.id==='birdB')mode=n%4===0?'subject':n%4===1?'macro':'mirrorSeam';
  const motifKey=`${group}:${motif}:${asset.id}`;
  if(!motifs[motifKey])motifs[motifKey]={cursor:0,reverse:motif%7===4,rate:motif%9===5?.35:motif%11===7?1.7:.9};
  const motion=motifs[motifKey],available=Math.max(.1,(asset.duration??8)-.15),range=asset.usableRanges?.[motif%asset.usableRanges.length]??[.15,available],lo=range[0],hi=range[1],span=spans[`${group}:${motif}`];
  const reverse=motion.reverse,rate=Math.min(motion.rate,(hi-lo)/Math.max(span,1/30)),sourceStart=lo+(motif*.61)%Math.max(.001,hi-lo-span*rate),elapsed=motion.cursor*rate;
  const from=Math.max(lo,Math.min(hi,reverse?sourceStart+span*rate-elapsed:sourceStart+elapsed));motion.cursor+=len;
  const to=Math.max(lo,Math.min(hi,from+(reverse?-1:1)*len*rate));
  const setup={...structuredClone(setups[mode]),mode,sourceId:asset.id,group,palette:palettes[group],variant:n%3,
   phrase:[visit.start,visit.end],phases:[0,1/30,4/30,8/30],stepPose:true,
   retime:[[0,from],[Math.max(len,1/30),to]],mediaHold:0,
   focal:asset.focal??[.5,.5],subjectZoom:asset.id==='birdB'?[1.65,1.7,1.8]:[1.05,1.14,1.18],effectLimit:mode==='liquidNeedle'?8/30:.4,
   attack:.1,settle:.23,sectors:8+2*(n%9),sectorSteps:[[0,8+2*(n%9)],[4/30,12+2*(n%8)],[8/30,8+2*(n%9)]],
   transition:n%6===0?'dissolve':n%8===3?'iris':'match',rgb:false,edgeAccent:mode==='liquidWindow'&&group!=='gray',
   edgeColors:group==='blue'?['#297ecd','#b8d8f4']:['#a83226','#e9a472'],
   trail:n%4!==0,trailAxis:n%2?'x':'y',trailDirection:n%2?1:-1,
   trailPolarity:['jellySilver','inkVeil','silverMesh','foil','smokeBubbles'].includes(asset.id)?'light':'dark',
   blankFrames:null,flashFrames:0,
   waterLandscape:['mountainA','desertB','lakeA','lakeB','oceanA','oceanB','snowB'].includes(asset.id)&&n%2===1,
   waterPose:i%3,surfacePose:i%8,negativeBurstFrames:len>=.65?(i%3===0?3:Math.min(i%2?22:16,Math.floor(len*30)-1)):3,negativeWindowCount:1+i%2,
   surfaceBurst:visit.start-lastBurst>=6&&len>=.1&&['full','macro','subject'].includes(mode)};
  if(setup.waterLandscape)setup.surfaceBurst=false;
  if(setup.surfaceBurst)lastBurst=visit.start;
  return {id:`material-${i}`,relation:'A shared source motif changes scale, density and reflection before returning to a readable subject.',duration:plan.duration,clock:{mode:'restart',offset:0,rate:1},setup,
   values:{'camera.scale':1,'camera.x':0,'camera.y':0},tracks:[]};
 });
 const boundaries=[0,...(plan.stages?.map(s=>s.start)??plan.shots.filter(s=>s.kind==='structure'||s.kind==='stage').map(s=>s.start)),plan.duration];
 const times=[...new Set(boundaries)].sort((a,b)=>a-b);
 const stages=times.slice(0,-1).map((start,i)=>{
  const end=times[i+1],visits=plan.shots.filter(s=>s.start>=start&&s.start<end);
  return {id:`stage-${i}`,start,end,focus:'material motif',change:'Color group and source relation follow the edited stage.',carry:true,
   rhythm:[{start,end,mode:visits.length>1?'switch':'hold',anchors:visits.map(s=>s.start),music:'Measured response cues and edited stage boundaries',reason:'Respond to selected cues while retaining the same source over a short motif.',action:'Hold the moving subject and return to its readable contour.'}]};
 });
 return {intent:'music-video',duration:plan.duration,notes:{template,version:'prismatic-echo-4',treatment:'prismatic-study',seed:plan.seed,output:{start:0,end:plan.duration,width:1080,height:1080},policy:'Sparse negative episodes mix brief flashes with 16–22-frame detail-window movement and exit. Photography motifs last at most .9 seconds. Approved water-derived contour/detail/echo/return treatment applies to scenery. No diagonal panels, RGB displacement or blank boards. Source clocks and edited cues remain authoritative.'},stages,shots,cuts:plan.shots.map((s,i)=>({at:s.start,shot:shots[i].id})),tracks:[]};
}
export function compileMaterialScore(score){return createEditScore(score,{RHYTHM_MAP:{duration:score.duration,beats:[],onsets:[]},getVisualState:time=>({time})});}
