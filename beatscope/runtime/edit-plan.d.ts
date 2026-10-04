export interface EditPlan { schema:'beatscope-edit-plan-1'; source_sha256:string; duration:number; boundaries:{id:string; time:number}[]; cues:({id:string; time:number}|{id:string; deleted:true})[] }
export interface EditCue { id:string; time:number; sourceTime:number|null; sourceId:string|number|null; manual:boolean; strength:number }
export interface EditStage { id:string; start:number; end:number; index:number }
export function resolveEditPlan(rhythm:unknown, plan:EditPlan):{stages:EditStage[]; cues:EditCue[]};
