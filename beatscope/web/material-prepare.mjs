import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {makeMaterialScore,compileMaterialScore} from './material-plan.mjs';
import {makePlan} from './mv-plan.mjs';
import {createTrack} from '../runtime/runtime.js';
const root=path.resolve(process.argv[2]),input=JSON.parse(fs.readFileSync(path.join(root,'input.json')));
const library=JSON.parse(fs.readFileSync(new URL('./material-library.json',import.meta.url))),setups=JSON.parse(fs.readFileSync(new URL('./material-setups.json',import.meta.url)));
const track=createTrack(input.rhythm,{responseRelevance:input.ranking});
const plan=makePlan(input.rhythm,track.responseBetween(0,input.rhythm.source.duration),input.seed,input.editPlan);
const score=input.scoreFile?JSON.parse(fs.readFileSync(input.scoreFile)):makeMaterialScore(plan,library,setups,input.template);
if(score.duration!==plan.duration||score.intent!=='music-video')throw Error('Score must describe this song as a music-video');
const edit=compileMaterialScore(score);
fs.writeFileSync(path.join(root,'score.json'),JSON.stringify(score,null,2));
const outputEnd=Math.min(plan.duration,input.renderEnd??plan.duration);
const frames=Array.from({length:Math.ceil(outputEnd*30)+1},(_,i)=>{const s=edit.at(Math.min(outputEnd,i/30));return {shot:s.view.id,clock:s.view.sampleTime,sinceCut:s.view.sinceCut,setup:s.view.setup,values:s.values,previous:s.view.previous};});
const run=args=>{const p=spawnSync(process.env.BEATSCOPE_FFMPEG||'ffmpeg',['-hide_banner','-loglevel','error',...args],{stdio:'inherit',windowsHide:true});if(p.status!==0)throw Error('Material preparation failed');};
const assets={};fs.mkdirSync(path.join(root,'media'),{recursive:true});
for(const id of new Set(frames.map(f=>f.setup.sourceId))){
 if(fs.existsSync(path.join(root,'cancel')))throw Error('Cancelled');
 const asset=library.assets.find(a=>a.id===id),source=path.resolve(input.materialRoot,asset.file);
 if(!source.startsWith(path.resolve(input.materialRoot)+path.sep))throw Error('Invalid material path');
 const hash=createHash('sha256');for await(const chunk of fs.createReadStream(source))hash.update(chunk);
 if(hash.digest('hex')!==asset.sha256)throw Error(`Material hash mismatch: ${id}`);
 const visits=frames.filter(f=>f.setup.sourceId===id);
 const gray=asset.group==='gray';
 const curve=score.notes?.treatment==='prismatic-study'
  ? (asset.group==='red'?'colorchannelmixer=.65:.25:.1:.65:.25:.1:.65:.25:.1':asset.group==='blue'?'colorchannelmixer=.3:.4:.3:.3:.4:.3:.3:.4:.3':'hue=s=0')+",curves=all='0/.015 .18/.14 .4/.4 .65/.72 .85/.9 1/.96'"
  : ['jellySilver','inkVeil','smokeBubbles'].includes(asset.id)
  ? "hue=s=0,curves=all='0/0 .18/.16 .4/.38 .65/.66 .85/.86 1/.94'"
  : "hue=s=0,curves=all='0/0 .18/.015 .4/.1 .65/.3 .85/.82 .95/1 1/1'";
 const grade=gray?curve+(asset.id==='smoke'?',negate':'')+",lutrgb=r='12+val*.933':g='16+val*.91':b='26+val*.847'":asset.group==='blue'?curve+",lutrgb=r='10+val*.28':g='15+val*.66':b='24+val*.90'":curve+",lutrgb=r='12+val*.94':g='6+val*.31':b='10+val*.18'";
 const birdGrade="hue=s=0,curves=all='0/0 .2/.08 .5/.35 .8/.66 1/.79',lutrgb=r='12+val*.92':g='18+val*.94':b='24+val*.94',unsharp=5:5:.75:5:5:0";
 const filter=asset.id==='birdB'?'crop=1080:570:420:0,scale=1080:570,'+birdGrade+',pad=1080:1080:0:(oh-ih)/2:color=0xd7ddde':'scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,'+grade+',unsharp=5:5:.65:5:5:0';
 if(asset.kind!=='video'){
  const file=`media/${id}.jpg`;run(['-i',source,'-vf',filter,'-frames:v','1','-q:v','2','-y',path.join(root,file)]);
  assets[id]={files:[file],frames:1,kind:'photo'};continue;
 }
 const [num,den]=asset.avg_frame_rate.split('/').map(Number),fps=num/den;
 for(const f of visits){const [[a,x],[b,y]]=f.setup.retime,at=f.setup.mediaHold&&f.sinceCut<f.setup.mediaHold?0:f.clock;f.nativeFrame=Math.floor(Math.max(0,Math.min(asset.duration-.15,x+(y-x)*Math.min(1,at/(b-a))))*fps);}
 const indices=[...new Set(visits.map(f=>f.nativeFrame))].sort((a,b)=>a-b),mapping=new Map(indices.map((f,i)=>[f,i]));
 for(const f of visits)f.mediaCell=mapping.get(f.nativeFrame);
 const ranges=[];let first=indices[0],last=first;for(const n of indices.slice(1)){if(n===last+1)last=n;else{ranges.push([first,last]);first=last=n;}}ranges.push([first,last]);
 // Balance additions so sparse native-frame runs do not exceed FFmpeg's parser depth.
 const terms=ranges.map(([a,b])=>a===b?`eq(n,${a})`:`between(n,${a},${b})`);
 const sum=items=>items.length===1?items[0]:`(${sum(items.slice(0,Math.floor(items.length/2)))}+${sum(items.slice(Math.floor(items.length/2)))})`;
 const selection=sum(terms);
 const pages=Math.ceil(indices.length/4),files=Array.from({length:pages},(_,i)=>`media/${id}-${String(i+1).padStart(4,'0')}.jpg`);
 run(['-i',source,'-an','-vf',`select='${selection}',${filter},tile=2x2`,'-fps_mode','passthrough','-frames:v',String(pages),'-q:v','2','-y',path.join(root,`media/${id}-%04d.jpg`)]);
 assets[id]={files,frames:indices.length,width:1080,height:1080,fps,kind:'video'};
 console.log(JSON.stringify({asset:id,frames:indices.length}));
}
fs.writeFileSync(path.join(root,'material-timeline.json'),JSON.stringify({duration:outputEnd,fps:30,assets,frames}));
fs.writeFileSync(path.join(root,'material-library.json'),JSON.stringify(library,null,2));
fs.writeFileSync(path.join(root,'plan.json'),JSON.stringify({...plan,duration:outputEnd,template:input.template,version:score.notes.version}));
