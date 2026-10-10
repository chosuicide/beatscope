import {createMovie} from './mv-frame.mjs';
import {createMaterialMovie} from './material-frame.mjs';
import {materialTemplate,mediaTemplate} from './movie-templates.mjs';
import {createPaintMovie} from './paint-frame.mjs';
import {attachMedia,createMediaSource} from './custom-media.mjs';
export async function createTemplateMovie(canvas,map,track,plan,options){
 if(!mediaTemplate(plan.template))return createMovie(canvas,map,track,plan);
 let media=plan.media;
 if(!media&&plan.projectId&&options?.editableMedia){const response=await fetch(`/api/projects/${plan.projectId}/custom-media`);if(!response.ok)throw Error('Image arrangement unavailable');media=await response.json();}
 if(media?.assets.length||options?.editableMedia){
  const source=document.createElement('canvas');source.width=canvas.width;source.height=canvas.height;
  const urls=id=>plan.projectId?`/api/projects/${plan.projectId}/assets/${id}`:`./custom/${id}.${plan.mediaFiles[id]}`;
  const mediaSource=createMediaSource(media,urls,{preview:options?.editableMedia,width:canvas.width,height:canvas.height,aspect:plan.output?.aspect??'1:1',mediaFrames:plan.mediaFrames??null,frameUrl:(i,k)=>`./custom/v/${i}/${String(k).padStart(6,'0')}.jpg`});
  try{const base=await createBaseMovie(source,map,track,plan,{...options,mediaSource});return attachMedia(canvas,source,base,mediaSource);}catch(error){mediaSource.dispose();throw error;}
 }
 return createBaseMovie(canvas,map,track,plan,options);
}
async function createBaseMovie(canvas,map,track,plan,options){
 if(plan.template==='paint')return createPaintMovie(canvas,map,track,plan,options);
 if(!materialTemplate(plan.template))return createMovie(canvas,map,track,plan);
 let base='./';
 if(plan.projectId){
  for(;;){
   const response=await fetch(`/api/materials/prepare?project=${encodeURIComponent(plan.projectId)}&seed=${plan.seed}&template=${plan.template}`);
   const state=await response.json();
   if(!response.ok||state.state==='failed')throw Error(state.message||'Material preparation unavailable');
   if(state.state==='ready'){base=state.base;break;}
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
 }
 const response=await fetch(base+'material-timeline.json');if(!response.ok)throw Error('Material timeline missing');
 const timeline=await response.json();
 return createMaterialMovie(canvas,timeline,base,options);
}
