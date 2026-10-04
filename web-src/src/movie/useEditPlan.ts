import {useEffect, useRef, useState} from 'react';
import {resolveEditPlan, type EditPlan} from '../../../beatscope/runtime/edit-plan.js';
import type {MovieRhythm} from './types';

export function useEditPlan(projectId:string|undefined, rhythm:MovieRhythm|null) {
  const [plan,setPlan] = useState<EditPlan|null>(null);
  const [saving,setSaving] = useState(false), [error,setError] = useState('');
  const [history,setHistory] = useState<{past:EditPlan[]; future:EditPlan[]}>({past:[],future:[]});
  const active = useRef(0), etag = useRef(''), locked = useRef(false);
  const current = useRef(plan); current.current = plan;
  useEffect(()=>{
    const token = ++active.current, controller = new AbortController();
    setPlan(null); setError(''); setSaving(false); locked.current=false;
    setHistory({past:[],future:[]}); etag.current='';
    if (projectId && rhythm) void (async()=>{
      try {
        const response = await fetch(`/api/projects/${projectId}/edit-plan`, {signal:controller.signal});
        const data = await response.json();
        if (!response.ok) throw Error(data.error ?? `HTTP ${response.status}`);
        resolveEditPlan(rhythm,data);
        if (active.current!==token) return;
        etag.current=response.headers.get('ETag')??''; setPlan(data);
      } catch(e) {if(active.current===token&&!controller.signal.aborted) setError(String(e));}
    })();
    return ()=>{controller.abort(); active.current++;};
  },[projectId,rhythm]);

  async function commit(next:EditPlan, mode:'edit'|'undo'|'redo'='edit') {
    const prior = current.current, token = active.current;
    if (!prior || !projectId || !rhythm || locked.current || JSON.stringify(prior)===JSON.stringify(next)) return;
    resolveEditPlan(rhythm,next);
    locked.current=true; setSaving(true); setError('');
    try {
      const response = await fetch(`/api/projects/${projectId}/edit-plan`, {method:'PUT',headers:{'Content-Type':'application/json','If-Match':etag.current},body:JSON.stringify(next)});
      const data = await response.json();
      if(!response.ok) throw Error(data.error??`HTTP ${response.status}`);
      if(active.current!==token) return;
      etag.current=response.headers.get('ETag')??''; setPlan(data);
      setHistory(h=> mode==='undo' ? {past:h.past.slice(0,-1),future:[prior,...h.future]} : mode==='redo' ? {past:[...h.past,prior].slice(-30),future:h.future.slice(1)} : {past:[...h.past,prior].slice(-30),future:[]});
    } catch(e) {if(active.current===token) setError(String(e));}
    finally {if(active.current===token) {locked.current=false;setSaving(false);}}
  }
  return {plan,saving,error,ready:!!plan,digest:etag.current.replaceAll('"',''),commit,
    canUndo:history.past.length>0,canRedo:history.future.length>0,
    undo:()=>{const next=history.past.at(-1);if(next) void commit(next,'undo');},
    redo:()=>{const next=history.future[0];if(next) void commit(next,'redo');}};
}
export type PlanEditor = ReturnType<typeof useEditPlan>;
