import {useMemo, useRef, useState} from 'react';
import {resolveEditPlan, type EditPlan} from '../../../beatscope/runtime/edit-plan.js';
import type {MovieRhythm} from './types';
import type {PlanEditor} from './useEditPlan';
import {useLang} from './copy';

export type CueSelection={kind:'stage'|'cue';id:string};
const paths={stage:'M3 5h18v14H3zM10 5v14M16 5v14',cue:'m12 3 6 9-6 9-6-9Z',plus:'M12 5v14M5 12h14',minus:'M5 12h14',undo:'M8 4 3 9l5 5M3 9h10a7 7 0 0 1 0 14',redo:'m16 4 5 5-5 5M21 9h-10a7 7 0 0 0 0 14',reset:'M4 8V3m0 5h5M4 8a9 9 0 1 1-1 8',magnet:'M5 5v8a7 7 0 0 0 14 0V5h-5v8a2 2 0 0 1-4 0V5ZM5 9h5m4 0h5',zoomIn:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 6 6M7 10h6m-3-3v6',zoomOut:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 6 6M7 10h6',prev:'m15 5-7 7 7 7',next:'m9 5 7 7-7 7',follow:'M12 2v4m0 12v4M2 12h4m12 0h4M12 6a6 6 0 1 0 0 12 6 6 0 0 0 0-12ZM12 10v4m-2-2h4'};
export function CueIcon({name}:{name:keyof typeof paths}) {return <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>;}
export const editorCopy={zh:{stage:'编辑阶段边界',cue:'编辑卡点',addStage:'在播放位置添加阶段',addCue:'在播放位置添加卡点',remove:'删除选中标记',undo:'撤销',redo:'重做',reset:'恢复自动建议',snap:'吸附到最近起音或拍点',saved:'已保存',saving:'保存中',loading:'加载中',time:'选中标记时间（秒）',zoomIn:'放大节奏图',zoomOut:'缩小节奏图',prev:'上一个窗口',next:'下一个窗口',follow:'跟随播放'},en:{stage:'Edit stage boundaries',cue:'Edit cues',addStage:'Add stage at playhead',addCue:'Add cue at playhead',remove:'Delete selected marker',undo:'Undo',redo:'Redo',reset:'Restore automatic suggestions',snap:'Snap to nearest onset or beat',saved:'Saved',saving:'Saving',loading:'Loading',time:'Selected marker time (seconds)',zoomIn:'Zoom rhythm map in',zoomOut:'Zoom rhythm map out',prev:'Previous window',next:'Next window',follow:'Follow playback'}};

export function useCueMapEditor(editor:PlanEditor|undefined,rhythm:MovieRhythm,time:number,disabled:boolean) {
  const [mode,setMode]=useState<'stage'|'cue'>('stage'),[selection,setSelection]=useState<CueSelection|null>(null);
  const [snap,setSnap]=useState(true),[draft,setDraft]=useState<EditPlan|null>(null);
  const drag=useRef<{original:EditPlan;latest:EditPlan;selection:CueSelection;clientX:number;toTime:(x:number)=>number;moved:boolean}|null>(null);
  const plan=draft??editor?.plan??null,duration=rhythm.source.duration;
  const resolved=useMemo(()=>plan?resolveEditPlan(rhythm,plan):null,[rhythm,plan]);
  const blocked=disabled||!editor?.ready||editor.saving;
  const selectedTime=selection?.kind==='stage'?plan?.boundaries.find(b=>b.id===selection.id)?.time:resolved?.cues.find(c=>c.id===selection?.id)?.time;
  const magnets=useMemo(()=>[0,...(rhythm.onsets??[]).map(o=>o.time),...(rhythm.beats??[]).map(b=>b.time)], [rhythm]);
  function near(t:number) {return snap?magnets.reduce((best,x)=>Math.abs(x-t)<Math.abs(best-t)?x:best,magnets[0]??t):t;}
  const addTime=near(time);
  const canAdd=mode==='cue'?addTime<duration:addTime>0&&addTime<duration&&!plan?.boundaries.some(b=>Math.abs(b.time-addTime)<.001);
  function modified(original:EditPlan,selected:CueSelection,target:number) {
    const next=structuredClone(original);
    if(selected.kind==='stage') {
      const i=next.boundaries.findIndex(b=>b.id===selected.id); if(i<0)return next;
      const lo=next.boundaries[i-1]?.time??0,hi=next.boundaries[i+1]?.time??duration,pad=Math.min(.001,(hi-lo)/3);
      next.boundaries[i].time=Math.max(lo+pad,Math.min(hi-pad,target));
    } else {
      next.cues=next.cues.filter(c=>c.id!==selected.id);
      next.cues.push({id:selected.id,time:Math.max(0,Math.min(duration-.001,target))});
    }
    return next;
  }
  function select(s:CueSelection) {setSelection(s);setMode(s.kind);}
  function begin(s:CueSelection,clientX:number,toTime:(x:number)=>number) {
    if(blocked||!plan)return;
    select(s);drag.current={original:plan,latest:plan,selection:s,clientX,toTime,moved:false};
  }
  function move(clientX:number) {
    const d=drag.current;if(!d||Math.abs(clientX-d.clientX)<2)return;
    d.moved=true;d.latest=modified(d.original,d.selection,near(d.toTime(clientX)));setDraft(d.latest);
  }
  function finish(cancel=false) {
    const d=drag.current;drag.current=null;setDraft(null);
    if(d&&!cancel&&d.moved)void editor?.commit(d.latest);
    return d&&!cancel&&!d.moved;
  }
  function changeTime(target:number) {if(plan&&selection&&!blocked&&Number.isFinite(target)&&target!==selectedTime)void editor?.commit(modified(plan,selection,target));}
  function add() {
    if(!plan||blocked)return;
    const next=structuredClone(plan),t=near(time),id=`${mode==='stage'?'s':'u'}:${crypto.randomUUID()}`;
    if(mode==='stage') {
      if(t<=0||t>=duration||next.boundaries.some(b=>Math.abs(b.time-t)<.001))return;
      next.boundaries.push({id,time:t});next.boundaries.sort((a,b)=>a.time-b.time);
    } else {if(t>=duration)return;next.cues.push({id,time:t});}
    select({kind:mode,id});void editor?.commit(next);
  }
  function remove() {
    if(!plan||!selection||blocked)return;
    const next=structuredClone(plan);
    if(selection.kind==='stage')next.boundaries=next.boundaries.filter(b=>b.id!==selection.id);
    else {next.cues=next.cues.filter(c=>c.id!==selection.id);if(selection.id.startsWith('o:'))next.cues.push({id:selection.id,deleted:true});}
    setSelection(null);void editor?.commit(next);
  }
  function reset() {
    if(!plan||blocked)return;
    const times=[...new Set((rhythm.patterns?.segments??[]).map(s=>s.start_time).filter(t=>t>0&&t<duration))].sort((a,b)=>a-b);
    void editor?.commit({...plan,boundaries:times.map((time,i)=>({id:`s:${i}`,time})),cues:[]});setSelection(null);
  }
  return {editor,plan,resolved,blocked,selection,selectedTime,mode,setMode,snap,setSnap,canAdd,select,begin,move,finish,changeTime,add,remove,reset};
}
export type CueEditor = ReturnType<typeof useCueMapEditor>;

export function CueMapToolbar({edit}:{edit:CueEditor}) {
  const copy=editorCopy[useLang()],status=edit.editor?.error||(edit.editor?.saving?copy.saving:edit.editor?.ready?copy.saved:copy.loading);
  const button=(name:keyof typeof paths,label:string,action:()=>void,off=false,pressed?:boolean)=><button type="button" title={label} aria-label={label} aria-pressed={pressed} disabled={edit.blocked||off} onClick={action}><CueIcon name={name}/></button>;
  return <div className="cm-edit-tools" data-testid="cue-map-editor">
    <div className="cm-edit-modes">{button('stage',copy.stage,()=>edit.setMode('stage'),false,edit.mode==='stage')}{button('cue',copy.cue,()=>edit.setMode('cue'),false,edit.mode==='cue')}</div>
    {button('plus',edit.mode==='stage'?copy.addStage:copy.addCue,edit.add,!edit.canAdd)}{button('minus',copy.remove,edit.remove,edit.selectedTime===undefined)}
    <i className="cm-edit-divider"/>
    {button('undo',copy.undo,()=>edit.editor?.undo(),!edit.editor?.canUndo)}{button('redo',copy.redo,()=>edit.editor?.redo(),!edit.editor?.canRedo)}
    {button('magnet',copy.snap,()=>edit.setSnap(!edit.snap),false,edit.snap)}{button('reset',copy.reset,edit.reset)}
    {edit.selectedTime!==undefined&&<label className="cm-edit-time"><input aria-label={copy.time} type="number" min="0" max={edit.plan?.duration} step="0.001" key={`${edit.selection?.id}-${edit.selectedTime}`} defaultValue={edit.selectedTime.toFixed(3)} disabled={edit.blocked} onBlur={e=>{if(e.target.value&&e.target.value!==e.target.defaultValue)edit.changeTime(Number(e.target.value));}} onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur();}}/><span>s</span></label>}
    <span className={`cm-save-dot${edit.editor?.saving?' saving':''}${edit.editor?.error?' failed':''}`} title={status} aria-label={status} role="status"/>
  </div>;
}
