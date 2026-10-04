import {createMovie} from './mv-frame.mjs';
import {createMaterialMovie} from './material-frame.mjs';
import {materialTemplate} from './movie-templates.mjs';
export async function createTemplateMovie(canvas,map,track,plan,options){
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
 return createMaterialMovie(canvas,await response.json(),base,options);
}
