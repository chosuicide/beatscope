/**
 * Beathi movie studio.
 *
 * One song in, one film out: upload, BeatScope measures it, the built-in
 * template renders the whole track, then it plays here.
 *
 * Layout is editor-grade rather than a landing page: a facts rail for the
 * measured structure, the stage in the middle (the live template while the
 * analysis and render run, the film afterwards), an inspector rail for render
 * state, exports and the template, and the cue map docked underneath.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { MovieTransport } from './MovieTransport';
import { CueMap } from './CueMap';
import {useEditPlan} from './useEditPlan';
import type {EditPlan} from '../../../beatscope/runtime/edit-plan.js';
import type { MovieRhythm } from './types';
import { createMusicGrid } from '../../../beatscope/web/music-grid.mjs';
import {
  analyzeUrl,
  applyJobToSession,
  lastFilmUrl,
  trackJob,
} from '../../../beatscope/web/studio-session.mjs';
import type { AgentActivity, ExportResult, MovieActionResult, ResponseRelevanceSidecar, StudioDirectorPort, StudioDirectorSnapshot, StudioStage } from '../webmcp/types.js';
import { installStudioWebMCP, type DirectorStatus } from '../webmcp/register.js';
import { LANGS, setLang, t, useCopy, useLang } from './copy';
import { agentHandoffPrompt } from './agent-handoff';
import {MOVIE_TEMPLATES} from '../../../beatscope/web/movie-templates.mjs';
import './studio.css';

type Job = { id: string; state: string; progress: number; message: string; project_id?: string; video_url?: string; error?: string; seed?: number; edit_plan_digest?:string; template?:string; template_digest?:string; template_version?:string };
type Session = { name: string; projectId?: string; analysisId?: string; movieId?: string; seed?: number; videoUrl?: string; videoJobId?: string; videoPlanDigest?:string; job?: Job | null; template?:string; videoTemplate?:string; videoTemplateVersion?:string };
const key = 'beathi.movie.session.1';
const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;

async function request(url: string, init?: RequestInit) {
  const response = await fetch(url, init);
  const text = await response.text();
  let data; try { data = JSON.parse(text); }
  catch { throw Object.assign(Error(t().errorService), { status: response.status }); }
  if (!response.ok) throw Object.assign(Error(data.message || data.error || t().errorRequest(response.status)), { status: response.status });
  return data;
}
function remember(session: Session) { try { localStorage.setItem(key, JSON.stringify(session)); } catch { /* session still works without persistence */ } }

export default function MovieStudio() {
  const copy = useCopy();
  const lang = useLang();
  const [session, setSession] = useState<Session>({ name: '' });
  const TEMPLATE=MOVIE_TEMPLATES.find(t=>t.id===session.template)??MOVIE_TEMPLATES[0];
  const [stage, setStage] = useState('idle'), [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState(''), [capability, setCapability] = useState<{ available: boolean; message: string } | null>(null);
  const [rhythm, setRhythm] = useState<MovieRhythm | null>(null);
  const editor=useEditPlan(session.projectId,rhythm);
  const [previewPlan,setPreviewPlan]=useState<{projectId:string;rhythm:MovieRhythm;value:EditPlan;digest:string}|null>(null);
  const [previewUpdating,setPreviewUpdating]=useState(false);
  const renderSnapshot=useRef<typeof previewPlan>(null);
  useEffect(()=>{
    if(editor.plan&&session.projectId&&rhythm)setPreviewPlan(prior=>prior&&prior.projectId===session.projectId&&prior.rhythm===rhythm?prior:{projectId:session.projectId!,rhythm,value:editor.plan!,digest:editor.digest});
  },[editor.plan,editor.digest,session.projectId,rhythm]);
  const shownPlan=previewPlan&&previewPlan.projectId===session.projectId&&previewPlan.rhythm===rhythm?previewPlan:null;
  const previewPending=!!shownPlan&&editor.ready&&shownPlan.digest!==editor.digest;
  /* The v0.11 ordering sidecar, loaded best-effort beside the rhythm. The
     WebMCP port reads it through this ref; a missing or invalid sidecar stays
     an honest null and never blocks preview or playback. */
  const [relevance, setRelevance] = useState<ResponseRelevanceSidecar | null>(null);
  const relevanceRef = useRef<ResponseRelevanceSidecar | null>(null);
  relevanceRef.current = relevance;
  /* Page-changing Agent actions, newest last; rendered by the action strip. */
  const [activity, setActivity] = useState<AgentActivity[]>([]);
  const activityRef = useRef<AgentActivity[]>([]);
  activityRef.current = activity;
  /* One audition restoration snapshot, replaced only by a validated audition. */
  const auditionRef = useRef<{ time: number; playing: boolean } | null>(null);
  const auditionCleanup = useRef<(() => void) | null>(null);
  const dataExport = useRef<HTMLAnchorElement>(null);
  /* WebMCP presence: 'unsupported' renders nothing at all. */
  const [agent, setAgent] = useState<{ status: DirectorStatus; count: number; detail?: string }>({ status: 'unsupported', count: 0 });
  const [stripHidden, setStripHidden] = useState(false);
  const [handoffCopied, setHandoffCopied] = useState(false);
  const [handoffFallback, setHandoffFallback] = useState(false);
  const [time, setTime] = useState(0), [playing, setPlaying] = useState(false);
  const [startBar, setStartBar] = useState(1), [follow, setFollow] = useState(true);
  const [mapViewBars,setMapViewBars]=useState(8);
  const [elapsed, setElapsed] = useState(0);
  const input = useRef<HTMLInputElement>(null), video = useRef<HTMLVideoElement>(null), audio = useRef<HTMLAudioElement>(null);
  const preview = useRef<HTMLIFrameElement>(null);
  const generation = useRef(0), sessionRef = useRef<Session>({ name: '' });
  const startedRef = useRef<number | null>(null);
  const busy = ['uploading', 'analyzing', 'rendering'].includes(stage);
  const canRender = Boolean(rhythm && session.projectId && capability?.available) && !busy && editor.ready && !editor.saving;
  const grid = useMemo(() => createMusicGrid(rhythm), [rhythm]);
  const duration = Number(rhythm?.source?.duration ?? 0);
  /* The film slot comes from the session kernel: it survives regeneration
     failures and cancellations, and only a newer completed job replaces it.
     While a job runs the stage shows the live preview again; the finished
     film stays in the rail and returns to the stage once tracking ends. */
  const filmUrl = lastFilmUrl(session);
  const automaticBoundaries=JSON.stringify((rhythm?.patterns?.segments??[]).map(s=>s.start_time).filter(t=>t>0&&t<duration).sort((a,b)=>a-b));
  const legacyPlanUnchanged=editor.plan?.cues.length===0&&JSON.stringify(editor.plan.boundaries.map(b=>b.time))===automaticBoundaries;
  const filmCurrent=editor.ready&&(session.videoPlanDigest?session.videoPlanDigest===editor.digest:legacyPlanUnchanged)&&(session.videoTemplate??'voxel')===TEMPLATE.id&&(TEMPLATE.id==='voxel'||session.videoTemplateVersion===TEMPLATE.version);
  const shownAutomatic=shownPlan?.value.cues.length===0&&JSON.stringify(shownPlan.value.boundaries.map(b=>b.time))===automaticBoundaries;
  const shownFilmCurrent=!!shownPlan&&(session.videoPlanDigest?session.videoPlanDigest===shownPlan.digest:shownAutomatic)&&(session.videoTemplate??'voxel')===TEMPLATE.id&&(TEMPLATE.id==='voxel'||session.videoTemplateVersion===TEMPLATE.version);
  const hasFilm = filmUrl != null && !busy && shownFilmCurrent;
  const segments = rhythm?.patterns?.segments ?? [];
  const bpm = Number(rhythm?.tempo?.global_bpm ?? 0);
  const save = (next: Session) => { sessionRef.current = next; setSession(next); remember(next); };
  const player = () => (hasFilm ? video.current : audio.current);

  const sendPreview = (payload: Record<string, unknown>) => {
    preview.current?.contentWindow?.postMessage(payload, window.location.origin);
  };
  useEffect(()=>{if(shownPlan)sendPreview({type:'edit-plan',value:shownPlan.value});},[shownPlan,hasFilm]);
  useEffect(()=>{sendPreview({type:'lang',value:lang});},[lang,hasFilm]);
  const updatePreview=()=>{
    if(!editor.plan||!session.projectId||!rhythm||editor.saving||busy)return;
    audio.current?.pause();video.current?.pause();setPlaying(false);setPreviewUpdating(true);
    setPreviewPlan({projectId:session.projectId,rhythm,value:editor.plan,digest:editor.digest});
  };
  // The render poll repeats the same seed; the preview rebuilds on every seed
  // message, so only a real change is forwarded.
  const sentSeed = useRef<number | null>(null);
  const sendSeed = (seed?: number | null) => {
    if (seed == null || seed === sentSeed.current) return;
    sentSeed.current = seed;
    sendPreview({ type: 'seed', value: seed });
  };
  const seek = (target: number) => {
    const clamped = Math.max(0, Math.min(duration || target, target));
    const element = player();
    if (element) element.currentTime = clamped;
    setTime(clamped);
    sendPreview({ type: 't', value: clamped });
  };
  const playMedia = async (): Promise<{ playing: boolean; requiresUserGesture: boolean }> => {
    const element = player();
    if (!element) return { playing: false, requiresUserGesture: false };
    try { await element.play(); return { playing: true, requiresUserGesture: false }; }
    catch { return { playing: false, requiresUserGesture: true }; }
  };
  const pauseMedia = (): void => { player()?.pause(); };
  const toggle = () => {
    const element = player();
    if (!element) return;
    if (element.paused) void playMedia(); else pauseMedia();
  };

  /* Audition drives the same media element: seek to the start, play only when
     asked, stop at the end through the element's own timeupdate, and keep one
     restoration snapshot for the last validated audition. */
  const auditionRange = async (start: number, end: number, autoplay: boolean, signal: AbortSignal) => {
    const element = player();
    if (!element) return { started: false, start, end, requires_user_gesture: false };
    auditionCleanup.current?.();
    auditionRef.current = { time: element.currentTime, playing: !element.paused };
    seek(start);
    const stop = () => {
      if (element.currentTime >= end - 0.02) {
        element.pause();
        // `timeupdate` is intentionally coarse and can arrive after the media
        // clock has crossed the requested boundary.  Land on the exact end so
        // the visible player, Agent result and subsequent restore are stable.
        seek(end);
        cleanup();
      }
    };
    const cleanup = () => {
      element.removeEventListener('timeupdate', stop);
      signal.removeEventListener('abort', cleanup);
      if (auditionCleanup.current === cleanup) auditionCleanup.current = null;
    };
    auditionCleanup.current = cleanup;
    element.addEventListener('timeupdate', stop);
    signal.addEventListener('abort', cleanup, { once: true });
    if (!autoplay) return { started: false, start, end, requires_user_gesture: false };
    const outcome = await playMedia();
    return { started: outcome.playing, start, end, requires_user_gesture: outcome.requiresUserGesture };
  };
  const restoreAudition = async () => {
    const saved = auditionRef.current;
    if (!saved) return { restored: false, time: 0, playing: false };
    auditionCleanup.current?.();
    auditionRef.current = null;
    seek(saved.time);
    if (saved.playing) await playMedia(); else pauseMedia();
    return { restored: true, time: saved.time, playing: saved.playing };
  };

  /* The media element is the only clock: rAF keeps the transport, the live
     preview and the cue map smooth while the tab is visible, and the interval
     keeps them honest when it is hidden (rAF never fires there). */
  useEffect(() => {
    let raf = 0;
    let lastSent = -1;
    let lastRaf = 0;
    const push = () => {
      const element = player();
      if (!element) return;
      const now = element.currentTime;
      if (Math.abs(now - lastSent) <= 0.001) return;
      lastSent = now;
      setTime(now);
      sendPreview({ type: 't', value: now });
      if (follow && duration > 0) {
        const bar = grid.barAtTime(now) ?? 1;
        setStartBar(Math.max(1, Math.floor((bar - 1) / mapViewBars) * mapViewBars + 1));
      }
    };
    const tick = () => { lastRaf = performance.now(); push(); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    const fallback = window.setInterval(() => { if (performance.now() - lastRaf > 250) push(); }, 200);
    return () => { cancelAnimationFrame(raf); window.clearInterval(fallback); };
  }, [follow, duration, grid, hasFilm, mapViewBars]);

  // Re-sync after async preview initialization (including a paused seek), and
  // surface preview build errors in the main error banner instead of losing
  // them inside the iframe.
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== location.origin || event.source !== preview.current?.contentWindow) return;
      if (event.data?.type === 'ready') {setPreviewUpdating(false);sendPreview({ type: 't', value: player()?.currentTime ?? 0 });}
      if (event.data?.type === 'error') {setPreviewUpdating(false);setError(copy.previewFailed);}
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, [hasFilm]);

  /* elapsed time while a render runs (local to this page, honest about it) */
  useEffect(() => {
    if (stage !== 'rendering') { setElapsed(0); return; }
    const timer = window.setInterval(() => {
      if (startedRef.current) setElapsed((Date.now() - startedRef.current) / 1000);
    }, 500);
    return () => window.clearInterval(timer);
  }, [stage]);

  /* space toggles playback, like every media tool */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT|BUTTON|A)$/.test(target.tagName)) return;
      event.preventDefault();
      toggle();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  async function loadRhythm(id: string, token: number) {
    const next: MovieRhythm = await request(`/api/projects/${id}`);
    if (token === generation.current) setRhythm(next);
    try {
      const sidecar: ResponseRelevanceSidecar = await request(`/api/projects/${id}/response-relevance`);
      if (token === generation.current) setRelevance(sidecar);
    } catch {
      // No ranking sidecar: raw timing stays available, ranked queries say so.
      if (token === generation.current) setRelevance(null);
    }
  }
  async function movieLoop(id: string, token: number) {
    setStage('rendering');
    await trackJob({
      read: () => request(`/api/movies/${id}`),
      isCurrent: () => token === generation.current,
      accept: async (next: Job) => {
        setJob(next);
        save({...applyJobToSession(sessionRef.current, next),...(next.state==='complete'?{videoPlanDigest:next.edit_plan_digest,videoTemplate:next.template??'voxel',videoTemplateVersion:next.template_version}:{})});
        sendSeed(next.seed);
        if (next.state === 'complete') {
          if(renderSnapshot.current?.digest===next.edit_plan_digest)setPreviewPlan(renderSnapshot.current);
          // hand the clock over to the film: one player at a time
          audio.current?.pause();
          setTime(0); setPlaying(false);
          setStage('complete'); setError('');
          return true;
        }
        if (next.state === 'cancelled') { save({ ...sessionRef.current, movieId: undefined }); setStage('preview'); return true; }
        if (next.state === 'failed') { setStage('failed'); setError(next.message); return true; }
        return false;
      },
    });
  }
  async function submitMovie(id: string, token: number, seed?: number): Promise<Job> {
    renderSnapshot.current=editor.plan&&rhythm?{projectId:id,rhythm,value:editor.plan,digest:editor.digest}:null;
    const next: Job = await request('/api/movies', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: id, seed: seed ?? sessionRef.current.seed ?? 1, template:sessionRef.current.template??'voxel' }) });
    if (token !== generation.current) return next;
    sendSeed(next.seed);
    save({ ...sessionRef.current, projectId: id, analysisId: undefined, movieId: next.id, seed: next.seed });
    return next;
  }
  async function createMovie(id: string, token: number) {
    setStage('rendering'); setJob(null);
    startedRef.current = Date.now();
    const next = await submitMovie(id, token);
    if (token !== generation.current) return;
    await movieLoop(next.id, token);
  }
  /* The Agent path returns as soon as the job exists; progress is read back
     through the state tool while the poll keeps running. */
  async function startRenderForAgent(seed?: number): Promise<MovieActionResult> {
    if(!editor.ready||editor.saving) throw Error(lang==='zh'?'请等待编辑方案保存完成。':'Wait until the edit plan is saved.');
    const id = sessionRef.current.projectId;
    if (!id) throw new Error('no project');
    const token = ++generation.current;
    setStage('rendering'); setJob(null); setError('');
    startedRef.current = Date.now();
    let next: Job;
    try { next = await submitMovie(id, token, seed); }
    catch (e) {
      if (token === generation.current) { setStage('failed'); setError(String(e)); }
      throw e;
    }
    if (token === generation.current) {
      void movieLoop(next.id, token).catch((e) => {
        if (token === generation.current) { setStage('failed'); setError(String(e)); }
      });
    }
    return { action: 'start', job: { id: next.id, state: next.state, progress: Number(next.progress ?? 0), video_ready: Boolean(next.video_url) }, seed: sessionRef.current.seed ?? null };
  }
  async function cancelMovieRender(): Promise<void> {
    if (sessionRef.current.movieId) await request(`/api/movies/${sessionRef.current.movieId}/cancel`, { method: 'POST' });
  }
  async function analysisLoop(id: string, token: number) {
    setStage('analyzing');
    await trackJob({
      read: () => request(`/api/jobs/${id}`),
      isCurrent: () => token === generation.current,
      accept: async (next: Job) => {
        setJob(next);
        if (next.state === 'complete' && next.project_id) {
          // rendering is on demand: analysis only unlocks the live preview
          save({ ...sessionRef.current, projectId: next.project_id, analysisId: undefined, movieId: undefined });
          await loadRhythm(next.project_id, token); if (token !== generation.current) return true;
          setStage('preview');
          return true;
        }
        if (['failed', 'cancelled'].includes(next.state)) { setStage(next.state); if (next.state === 'failed') setError(next.error || next.message); return true; }
        return false;
      },
    });
  }
  useEffect(() => {
    document.title = t().docTitle;
    const token = ++generation.current;
    void request('/api/movies/capabilities').then(setCapability).catch((e) => setCapability({ available: false, message: String(e) }));
    let saved: Session | null = null;
    try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch { /* no saved session */ }
    const link=new URLSearchParams(location.search),linkedProject=link.get('project'),linkedTemplate=link.get('template');
    if(linkedProject&&/^[0-9a-f]{12}$/.test(linkedProject)){
      saved={...(saved?.projectId===linkedProject?saved:{name:link.get('name')||linkedProject}),projectId:linkedProject};
      if(MOVIE_TEMPLATES.some(t=>t.id===linkedTemplate))saved.template=linkedTemplate!;
      const linkedSeed=Number(link.get('seed'));if(link.has('seed')&&Number.isInteger(linkedSeed)&&linkedSeed>=0&&linkedSeed<2**24)saved.seed=linkedSeed;
    }
    if (saved && typeof saved.name === 'string') {
      if(saved.template?.startsWith('material-')&&saved.template!=='material-mix')saved.template='material-mix';
      save(saved);
      void (async () => {
        if (saved!.projectId) {
          try { await loadRhythm(saved!.projectId, token); }
          catch (e) { if (token === generation.current) setError(String(e)); }
        }
        if (token !== generation.current) return;
        if (saved!.movieId) { startedRef.current = Date.now(); await movieLoop(saved!.movieId, token); }
        else if (saved!.analysisId) await analysisLoop(saved!.analysisId, token);
        else if (saved!.projectId) setStage('preview');
      })().catch((e) => { if (token === generation.current) { setStage('failed'); setError(String(e)); } });
    }
    return () => { generation.current++; };
  }, []);
  async function upload(file?: File) {
    if (!file || busy) return;
    if (!/\.(wav|mp3|flac|ogg|m4a|aac|aiff|aif|opus)$/i.test(file.name)) { setError(t().errorFileType); return; }
    if (!file.size || file.size > 500 * 1024 * 1024) { setError(t().errorFileSize); return; }
    const token = ++generation.current;
    audio.current?.pause(); video.current?.pause();
    setError(''); setRhythm(null); setTime(0); setPlaying(false); setStartBar(1); setFollow(true);
    const seed = crypto.getRandomValues(new Uint32Array(1))[0] & 0xffffff;
    setJob(null); setStage('uploading'); setRelevance(null); auditionCleanup.current?.(); auditionRef.current = null; save({ name: file.name, seed,template:sessionRef.current.template });
    startedRef.current = null;
    try {
      const next = await request(analyzeUrl(), {
        method: 'POST',
        body: file,
        headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) },
      });
      if (token !== generation.current) return;
      save({ name: file.name, analysisId: next.job_id, seed,template:sessionRef.current.template });
      await analysisLoop(next.job_id, token);
    } catch (e) { if (token === generation.current) { setError(String(e)); setStage('failed'); } }
  }
  async function cancel() {
    try {
      if (stage === 'analyzing' && session.analysisId) await request(`/api/jobs/${session.analysisId}`, { method: 'DELETE' });
      if (stage === 'rendering' && session.movieId) await request(`/api/movies/${session.movieId}/cancel`, { method: 'POST' });
    } catch (e) { setError(String(e)); }
  }
  async function retry() {
    const token = ++generation.current;
    setError('');
    try { if (session.projectId) await createMovie(session.projectId, token); else input.current?.click(); }
    catch (e) { setError(String(e)); setStage(previewReady ? 'preview' : 'failed'); }
  }

  const percent = Math.round((job?.progress ?? 0) * 100);
  const previewReady = Boolean(rhythm && session.projectId && shownPlan);
  const status = stage === 'uploading' ? copy.status.uploading
    : stage === 'analyzing' ? copy.status.analyzing
    : stage === 'rendering' ? copy.status.rendering
    : stage === 'complete' ? copy.status.complete
    : stage === 'failed' ? copy.status.failed
    : stage === 'preview' ? copy.status.preview
    : session.name ? copy.status.ready : copy.status.idle;
  const statusTone = stage === 'complete' ? 'ok' : stage === 'failed' ? 'bad' : busy ? 'run' : '';
  const eta = stage === 'rendering' && job && job.progress > 0.04 && job.progress < 0.99
    ? Math.max(0, elapsed / job.progress - elapsed)
    : null;
  const exportBase = session.projectId ? `/api/projects/${encodeURIComponent(session.projectId)}/export` : null;
  const timingPackageUrl = exportBase && editor.ready && !editor.saving ? `${exportBase}/codex.zip` : null;
  const timingPackageName = session.projectId ? `${session.projectId}.beatscope-codex.zip` : 'timing-package.zip';
  async function copyAgentInstructions() {
    if (!session.projectId) return;
    try {
      await navigator.clipboard.writeText(agentHandoffPrompt(lang));
      setHandoffCopied(true);
      setHandoffFallback(false);
    } catch {
      setHandoffCopied(false);
      setHandoffFallback(true);
    }
  }
  /* Same URL as the visible Data export button: the button keeps its native
     anchor (the most reliable path), the tool path clicks the same href and
     falls back to the button when a programmatic download is refused. */
  async function downloadTimingPackage(): Promise<ExportResult> {
    if (!timingPackageUrl) throw new Error('no project');
    if (!('download' in HTMLAnchorElement.prototype)) {
      dataExport.current?.closest('details')?.setAttribute('open','');
      dataExport.current?.focus();
      return { filename: timingPackageName, started: false, requires_user_action: true };
    }
    const anchor = document.createElement('a');
    anchor.href = timingPackageUrl;
    anchor.download = timingPackageName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    return { filename: timingPackageName, started: true, requires_user_action: false };
  }

  /* One stable port object, refreshed every render: tool callbacks read it
     through this ref, so an older call can never mutate a new session. */
  const port: StudioDirectorPort = {
    snapshot: (): StudioDirectorSnapshot => {
      const element = player();
      return {
        stage: stage as StudioStage,
        projectId: sessionRef.current.projectId ?? null,
        name: sessionRef.current.name,
        rhythm,
        responseRelevance: relevanceRef.current,
        editPlan:editor.plan,
        movieTemplate:TEMPLATE,
        seed: sessionRef.current.seed ?? null,
        movieJob: job ? { id: job.id, state: job.state, progress: Number(job.progress ?? 0), video_ready: Boolean(job.video_url) } : null,
        movieFailureText: job?.error || job?.message || null,
        currentTime: element ? element.currentTime : time,
        duration,
        playing: element ? !element.paused : playing,
        rendererAvailable: Boolean(capability?.available),
      };
    },
    seek: (target: number) => seek(target),
    play: () => playMedia(),
    pause: () => pauseMedia(),
    audition: (start, end, autoplay, signal) => auditionRange(start, end, autoplay, signal),
    restoreAudition: () => restoreAudition(),
    render: async (action, seed) => {
      if (action === 'start') return startRenderForAgent(seed);
      await cancelMovieRender();
      const current = port.snapshot();
      return { action: 'cancel', job: current.movieJob, seed: current.seed };
    },
    exportTimingPackage: () => downloadTimingPackage(),
    recordAgentAction: (entry: AgentActivity) => { setStripHidden(false); setActivity((list) => [...list.slice(-4), entry]); },
  };
  const portRef = useRef<StudioDirectorPort>(port);
  portRef.current = port;

  /* Register once per mounted document; every callback reads portRef, so a
     song change never needs a re-registration. */
  useEffect(() => {
    const session = installStudioWebMCP(
      () => portRef.current,
      (status, count, detail) => setAgent({ status, count, detail }),
    );
    return () => session.dispose();
  }, []);
  const latest = activity[activity.length - 1];
  const currentBar = grid.barAtTime(time) ?? 1;

  return (
    <div
      className="mv-shell"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); void upload(e.dataTransfer.files[0]); }}
    >
      <header className="topbar">
        <span className="mark" aria-hidden="true">b.</span>
        <span className="tb-name">{session.name || 'Beathi'}</span>
        {rhythm && (
          <span className="mv-facts">
            {bpm > 0 && <><b>{bpm.toFixed(1)}</b> BPM</>}
            <i />
            <>{copy.sections(segments.length || '—')}</>
            <i />
            <>{duration ? mmss(duration) : '—'}</>
          </span>
        )}
        <span className="tb-sp" />
        <span className={`mv-chip ${statusTone}`}>{status}{busy && stage !== 'uploading' ? ` ${percent}%` : ''}</span>
        {agent.status !== 'unsupported' && (
          <span className={`mv-agent${agent.status === 'error' ? ' error' : ''}`} title={agent.detail}>
            {agent.status === 'registering' ? copy.agent.connecting
              : agent.status === 'error' ? copy.agent.error
                : copy.agent.tools(agent.count)}
          </span>
        )}
        <span className="mv-agent-sr" role="status" aria-live="polite">
          {agent.status === 'unsupported' ? '' : `${copy.agent.label}: ${agent.status}`}
        </span>
        <span className="mv-lang" role="group" aria-label="Language">
          {LANGS.map((entry) => (
            <button
              key={entry.id}
              className={`tbtn${lang === entry.id ? ' on' : ''}`}
              aria-pressed={lang === entry.id}
              onClick={() => setLang(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </span>
        {session.name && (
          <button className="tbtn" disabled={busy} onClick={() => input.current?.click()}>{copy.changeSong}</button>
        )}
      </header>
      <input ref={input} type="file" hidden accept="audio/*,.flac,.m4a" onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ''; }} />
      {capability && !capability.available && <div className="mv-notice" role="alert">{capability.message}</div>}
      {error && (
        <div className="mv-error" role="alert">
          <span>{error}</span>
          <button onClick={() => setError('')} aria-label={copy.dismissError}>×</button>
        </div>
      )}

      <div className="mv-body">
        <aside className="mv-rail" aria-label={copy.structure}>
          <div className="rail-cap">{copy.structure}{segments.length ? ` · ${lang==='zh'?copy.sections(segments.length):segments.length}` : ''}</div>
          <ol className="seg-list">
            {segments.map((segment, index) => {
              const active = time >= segment.start_time && time < segment.end_time;
              const energy = Number((segment as { mean_energy?: number }).mean_energy ?? 0);
              return (
                <li key={`${segment.family}-${index}`}>
                  <button
                    className={`seg-row${active ? ' on' : ''}`}
                    onClick={() => {
                      seek(segment.start_time);
                      setFollow(false);
                      setStartBar(Math.max(1, Math.floor(((segment.start_bar ?? 1) - 1) / 8) * 8 + 1));
                    }}
                    title={`${segment.display_label ?? segment.family} · ${mmss(segment.start_time)}–${mmss(segment.end_time)}`}
                  >
                    <span className="seg-fam">{segment.display_label ?? segment.family}</span>
                    <span className="seg-meta">
                      {segment.start_bar != null && segment.end_bar != null
                        ? `${String(segment.start_bar).padStart(2, '0')}–${String(segment.end_bar).padStart(2, '0')}`
                        : mmss(segment.start_time)}
                    </span>
                    <span className="seg-time">{mmss(segment.start_time)}</span>
                    <span className="seg-energy" aria-hidden="true"><i style={{ width: `${Math.round(Math.min(1, energy * 3) * 100)}%` }} /></span>
                  </button>
                </li>
              );
            })}
          </ol>
          {segments.length > 0 && grid.available && (
            <div className="rail-foot">{copy.barOf(Math.max(1, currentBar), rhythm?.grid?.bars ?? '—')}</div>
          )}
        </aside>

        <main className="mv-stage">
          <div className="stage-head">
            <span className="stage-name">{lang==='zh'?TEMPLATE.nameZh:TEMPLATE.name}</span>
            <span className="stage-sep" />
            <span className="stage-meta">{hasFilm?'1080 × 1080':'540 × 540'} · 30 FPS</span>
            {session.seed != null && <><span className="stage-sep" /><span className="stage-meta">seed {session.seed}</span></>}
            <span className="tb-sp" />
            <span className="stage-meta">{hasFilm ? copy.filmReady : previewReady ? copy.transport.preview : ''}</span>
          </div>
          <div className="mv-frame">
            {hasFilm ? (
              <video
                ref={video}
                src={filmUrl}
                playsInline
                preload="metadata"
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onEnded={() => setPlaying(false)}
                onError={() => setError(copy.previewFailed)}
              />
            ) : previewReady ? (
              <iframe
                ref={preview}
                className="mv-preview"
                title={copy.livePreviewTitle}
                key={`${session.projectId}-${TEMPLATE.id}`}
                src={`/movie-preview.html?project=${encodeURIComponent(session.projectId!)}&seed=${session.seed ?? 1}&template=${TEMPLATE.id}`}
                onLoad={() => { sendPreview({type:'lang',value:lang});sendPreview({ type: 't', value: time }); sendSeed(session.seed); if(shownPlan)sendPreview({type:'edit-plan',value:shownPlan.value}); }}
              />
            ) : (
              <div className="mv-placeholder">
                <img src="./movie-poster.webp" alt={copy.posterAlt} />
                <div className="mv-empty">
                  <button className="btn-ink" disabled={busy} onClick={() => input.current?.click()}>
                    {copy.uploadSong}
                  </button>
                  <span className="note">{copy.uploadHint}</span>
                </div>
              </div>
            )}
            {busy && stage !== 'uploading' && <span className="mv-bar" style={{ width: `${percent}%` }} aria-hidden="true" />}
          </div>
          {latest && !stripHidden && (
            <div className="mv-strip" role="status">
              <span>{latest.label}</span>
              <span className="sp" />
              {latest.restorable && (
                <button type="button" onClick={() => { void restoreAudition(); }}>{copy.agent.restore}</button>
              )}
              <button type="button" aria-label={copy.agent.dismiss} onClick={() => setStripHidden(true)}>×</button>
            </div>
          )}
          {previewReady&&<div className={`preview-edit-state${previewPending?' pending':''}`} data-testid="preview-edit-state">
            <span role="status">{previewUpdating?(lang==='zh'?'正在更新预览…':'Updating preview…'):previewPending?(lang==='zh'?'编辑已保存，预览待更新':'Edits saved · preview needs updating'):(lang==='zh'?'预览已同步':'Preview is up to date')}</span>
            <button type="button" className="btn-line" onClick={updatePreview} disabled={!previewPending||editor.saving||previewUpdating||busy}>{lang==='zh'?'更新预览':'Update preview'}</button>
          </div>}
          <MovieTransport
            time={time}
            duration={duration}
            playing={playing}
            disabled={!previewReady && !hasFilm}
            label={hasFilm ? copy.transport.film : stage === 'rendering' ? copy.transport.rendering : copy.transport.preview}
            onToggle={toggle}
            onSeek={seek}
          />
          <p className="mv-warning">{copy.warning}</p>
        </main>

        <aside className="mv-rail" aria-label={copy.filmExport}>
          <section className="card template-card">
            <div className="rail-cap">{copy.template}</div>
            <select className="template-select" aria-label={copy.template} value={TEMPLATE.id} disabled={busy} onChange={event=>{audio.current?.pause();video.current?.pause();setPlaying(false);if(editor.plan&&rhythm&&session.projectId)setPreviewPlan({projectId:session.projectId,rhythm,value:editor.plan,digest:editor.digest});save({...sessionRef.current,template:event.target.value});}}>
              {MOVIE_TEMPLATES.map(template=><option key={template.id} value={template.id}>{lang==='zh'?template.nameZh:template.name}</option>)}
            </select>
            <details className="template-details">
              <summary>{lang==='zh'?'模板说明':'Template details'}</summary>
              {TEMPLATE.id==='paint'&&<p className="material-note">{lang==='zh'?'实拍花卉在节拍上被一笔笔重画：厚涂油彩、色粉、墨，重拍处刮画、丝网错版、对折墨印。':'Real flower footage repainted stroke by stroke on the beat: impasto oil, pastel on toned paper and ink, with sgraffito, misregistered prints and folded ink on the accents.'}</p>}
              {TEMPLATE.id.startsWith('material-')&&<p className="material-note">{lang==='zh'?'裁切、镜像、万花筒、同色拖影与负片，按色组编排。':'Crops, mirrors, kaleidoscopes, tonal trails and negatives, arranged by color.'}</p>}
              <div className="kv"><span>{copy.kv.version}</span><b>{TEMPLATE.version}</b></div>
            </details>
          </section>
          <section className="card">
            <div className="rail-cap">{copy.video}</div>
            <div className="kv"><span>{copy.kv.status}</span><b className={`tone-${statusTone || 'idle'}`}>{status}</b></div>
            {stage === 'rendering' && <div className="kv"><span>{copy.kv.progress}</span><b>{percent}%</b></div>}
            {stage === 'rendering' && <div className="kv"><span>{copy.kv.elapsed}</span><b>{mmss(elapsed)}</b></div>}
            {eta !== null && <div className="kv"><span>{copy.kv.eta}</span><b>{mmss(eta)}</b></div>}
            <div className="kv"><span>{copy.kv.output}</span><b>{duration ? mmss(duration) : '—'} · 1080×1080 · 30fps</b></div>
            {canRender && (
              <button className="btn-ink wide" onClick={() => void retry()}>
                {hasFilm ? copy.regenerate : copy.generate}
              </button>
            )}
            {(stage === 'rendering' || stage === 'analyzing') && (session.analysisId || session.movieId) && (
              <button className="btn-line wide" onClick={() => void cancel()}>{copy.cancel}</button>
            )}
            {stage === 'failed' && !canRender && !session.projectId && (
              <button className="btn-line wide" onClick={() => void retry()}>{copy.retry}</button>
            )}
            <a
              className={`btn-line wide${filmUrl ? '' : ' off'}`}
              href={filmUrl ? `${filmUrl}?download=1` : undefined}
              download
              aria-disabled={!filmUrl}
            >
              {filmUrl ? (!filmCurrent ? (lang==='zh'?'下载上次视频 · 方案已修改':'Previous video · plan changed') : (lang==='zh'?'下载视频 · MP4':'Download video · MP4')) : copy.filmMissing}
            </a>
          </section>

          <details className="card export-tools">
            <summary className="rail-cap">{copy.moreExport}</summary>
            <div className="export-tools-body">
            <a
              className={`btn-line wide${timingPackageUrl ? '' : ' off'}`}
              ref={dataExport}
              href={timingPackageUrl ?? undefined}
              download
              aria-disabled={!timingPackageUrl}
            >
              {copy.dataPackage}
            </a>
            <button className="btn-line wide" type="button" disabled={!exportBase} onClick={() => void copyAgentInstructions()}>
              {copy.copyAgentInstructions}
            </button>
            {handoffCopied && <p className="handoff-note" role="status">{copy.agentInstructionsCopied}</p>}
            {handoffFallback && (
              <div className="handoff-fallback" role="status">
                <p>{copy.agentInstructionsFallback}</p>
                <textarea aria-label={copy.copyAgentInstructions} readOnly value={agentHandoffPrompt(lang)} onFocus={(event) => event.currentTarget.select()} />
              </div>
            )}
            <div className="row2">
              <a className={`btn-line${exportBase ? '' : ' off'}`} href={exportBase ? `${exportBase}/rhythm.mid` : undefined} download aria-disabled={!exportBase}>
                {copy.rhythmMidi}
              </a>
              <a className={`btn-line${exportBase ? '' : ' off'}`} href={exportBase ? `${exportBase}/rhythm.csv` : undefined} download aria-disabled={!exportBase}>
                {copy.rhythmCsv}
              </a>
            </div>
            </div>
          </details>
        </aside>
      </div>

      {previewReady && rhythm && (
        <CueMap
          key={session.projectId}
          editor={editor}
          editingDisabled={busy}
          rhythm={rhythm}
          time={time}
          seek={seek}
          startBar={startBar}
          viewBars={mapViewBars}
          onViewBars={setMapViewBars}
          onStartBar={(bar) => { setFollow(false); setStartBar(bar); }}
          onFollowChange={(next) => setFollow(next)}
        />
      )}

      <audio
        ref={audio}
        src={session.projectId ? `/api/projects/${session.projectId}/audio` : undefined}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => { if (session.projectId) setError(copy.previewFailed); }}
      />
    </div>
  );
}
