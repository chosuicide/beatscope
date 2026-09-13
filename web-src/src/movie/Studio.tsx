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
import type { MovieRhythm } from './types';
import { createMusicGrid } from '../../../beatscope/web/music-grid.mjs';
import type { AgentActivity, ExportResult, MovieActionResult, ResponseRelevanceSidecar, StudioDirectorPort, StudioDirectorSnapshot, StudioStage } from '../webmcp/types.js';
import { installStudioWebMCP, type DirectorStatus } from '../webmcp/register.js';
import { LANGS, setLang, t, useCopy, useLang } from './copy';
import './studio.css';

type Job = { id: string; state: string; progress: number; message: string; project_id?: string; video_url?: string; error?: string; seed?: number };
type Session = { name: string; projectId?: string; analysisId?: string; movieId?: string; seed?: number };
const key = 'beathi.movie.session.1';
const wait = () => new Promise((resolve) => setTimeout(resolve, 1000));
const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
const TEMPLATE = { name: 'VOXEL INTERFERENCE', version: 'voxel-phrase-2' };

async function request(url: string, init?: RequestInit) {
  const response = await fetch(url, init);
  const text = await response.text();
  let data; try { data = JSON.parse(text); } catch { throw Error(t().errorService); }
  if (!response.ok) throw Error(data.message || data.error || t().errorRequest(response.status));
  return data;
}
function remember(session: Session) { try { localStorage.setItem(key, JSON.stringify(session)); } catch { /* session still works without persistence */ } }

export default function MovieStudio() {
  const copy = useCopy();
  const lang = useLang();
  const [session, setSession] = useState<Session>({ name: '' });
  const [stage, setStage] = useState('idle'), [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState(''), [capability, setCapability] = useState<{ available: boolean; message: string } | null>(null);
  const [rhythm, setRhythm] = useState<MovieRhythm | null>(null);
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
  const [time, setTime] = useState(0), [playing, setPlaying] = useState(false);
  const [startBar, setStartBar] = useState(1), [follow, setFollow] = useState(true);
  const [elapsed, setElapsed] = useState(0);
  const input = useRef<HTMLInputElement>(null), video = useRef<HTMLVideoElement>(null), audio = useRef<HTMLAudioElement>(null);
  const preview = useRef<HTMLIFrameElement>(null);
  const generation = useRef(0), sessionRef = useRef<Session>({ name: '' });
  const startedRef = useRef<number | null>(null);
  const busy = ['uploading', 'analyzing', 'rendering'].includes(stage);
  const canRender = Boolean(rhythm && session.projectId && capability?.available) && !busy;
  const grid = useMemo(() => createMusicGrid(rhythm), [rhythm]);
  const duration = Number(rhythm?.source?.duration ?? 0);
  const hasFilm = stage === 'complete' && Boolean(job?.video_url);
  const segments = rhythm?.patterns?.segments ?? [];
  const bpm = Number(rhythm?.tempo?.global_bpm ?? 0);
  const save = (next: Session) => { sessionRef.current = next; setSession(next); remember(next); };
  const player = () => (hasFilm ? video.current : audio.current);

  const sendPreview = (payload: Record<string, unknown>) => {
    preview.current?.contentWindow?.postMessage(payload, window.location.origin);
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
    const stop = () => { if (element.currentTime >= end - 0.02) { element.pause(); cleanup(); } };
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
        setStartBar(Math.max(1, Math.floor((bar - 1) / 8) * 8 + 1));
      }
    };
    const tick = () => { lastRaf = performance.now(); push(); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    const fallback = window.setInterval(() => { if (performance.now() - lastRaf > 250) push(); }, 200);
    return () => { cancelAnimationFrame(raf); window.clearInterval(fallback); };
  }, [follow, duration, grid, hasFilm]);

  // Re-sync after async preview initialization (including a paused seek).
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== location.origin || event.source !== preview.current?.contentWindow) return;
      if (event.data?.type === 'ready') sendPreview({ type: 't', value: player()?.currentTime ?? 0 });
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
      if (event.code !== 'Space') return;
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
    for (;;) {
      const next: Job = await request(`/api/movies/${id}`); if (token !== generation.current) return;
      setJob(next);
      sendSeed(next.seed);
      if (next.state === 'complete') {
        // hand the clock over to the film: one player at a time
        audio.current?.pause();
        setTime(0); setPlaying(false);
        setStage('complete');
        return;
      }
      if (next.state === 'cancelled') { save({ ...sessionRef.current, movieId: undefined }); setStage('preview'); return; }
      if (next.state === 'failed') { setStage('failed'); setError(next.message); return; }
      await wait(); if (token !== generation.current) return;
    }
  }
  async function submitMovie(id: string, token: number, seed?: number): Promise<Job> {
    const next: Job = await request('/api/movies', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: id, seed: seed ?? sessionRef.current.seed ?? 1 }) });
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
    const id = sessionRef.current.projectId;
    if (!id) throw new Error('no project');
    const token = ++generation.current;
    setStage('rendering'); setJob(null);
    startedRef.current = Date.now();
    const next = await submitMovie(id, token, seed);
    void movieLoop(next.id, token);
    return { action: 'start', job: { id: next.id, state: next.state, progress: Number(next.progress ?? 0), video_ready: Boolean(next.video_url) }, seed: sessionRef.current.seed ?? null };
  }
  async function cancelMovieRender(): Promise<void> {
    if (sessionRef.current.movieId) await request(`/api/movies/${sessionRef.current.movieId}/cancel`, { method: 'POST' });
  }
  async function analysisLoop(id: string, token: number) {
    setStage('analyzing');
    for (;;) {
      const next: Job = await request(`/api/jobs/${id}`); if (token !== generation.current) return;
      setJob(next);
      if (next.state === 'complete' && next.project_id) {
        // rendering is on demand: analysis only unlocks the live preview
        save({ ...sessionRef.current, projectId: next.project_id, analysisId: undefined, movieId: undefined });
        await loadRhythm(next.project_id, token); if (token !== generation.current) return;
        setStage('preview');
        return;
      }
      if (['failed', 'cancelled'].includes(next.state)) { setStage(next.state); if (next.state === 'failed') setError(next.error || next.message); return; }
      await wait(); if (token !== generation.current) return;
    }
  }
  useEffect(() => {
    document.title = t().docTitle;
    const token = ++generation.current;
    void request('/api/movies/capabilities').then(setCapability).catch((e) => setCapability({ available: false, message: String(e) }));
    let saved: Session | null = null;
    try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch { /* no saved session */ }
    if (saved && typeof saved.name === 'string') {
      save(saved);
      void (async () => {
        if (saved!.projectId) await loadRhythm(saved!.projectId, token);
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
    setJob(null); setStage('uploading'); setRelevance(null); auditionCleanup.current?.(); auditionRef.current = null; save({ name: file.name, seed });
    startedRef.current = null;
    try {
      const next = await request('/api/jobs/analyze', {
        method: 'POST',
        body: file,
        headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) },
      });
      if (token !== generation.current) return;
      save({ name: file.name, analysisId: next.job_id, seed });
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
  const previewReady = Boolean(rhythm && session.projectId);
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
  const timingPackageUrl = exportBase ? `${exportBase}/codex.zip` : null;
  const timingPackageName = session.projectId ? `${session.projectId}.beatscope-codex.zip` : 'timing-package.zip';
  /* Same URL as the visible Data export button: the button keeps its native
     anchor (the most reliable path), the tool path clicks the same href and
     falls back to the button when a programmatic download is refused. */
  async function downloadTimingPackage(): Promise<ExportResult> {
    if (!timingPackageUrl) throw new Error('no project');
    if (!('download' in HTMLAnchorElement.prototype)) {
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
        seed: sessionRef.current.seed ?? null,
        movieJob: job ? { id: job.id, state: job.state, progress: Number(job.progress ?? 0), video_ready: Boolean(job.video_url) } : null,
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
          <div className="rail-cap">{copy.structure}{segments.length ? ` · ${copy.sections(segments.length)}` : ''}</div>
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
            <span className="stage-name">{TEMPLATE.name}</span>
            <span className="stage-sep" />
            <span className="stage-meta">1080 × 1080 · 30 FPS</span>
            {session.seed != null && <><span className="stage-sep" /><span className="stage-meta">seed {session.seed}</span></>}
            <span className="tb-sp" />
            <span className="stage-meta">{hasFilm ? copy.filmReady : previewReady ? copy.transport.preview : ''}</span>
          </div>
          <div className="mv-frame">
            {hasFilm ? (
              <video
                ref={video}
                src={job?.video_url}
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
                key={`${session.projectId}-${lang}`}
                src={`/movie-preview.html?project=${encodeURIComponent(session.projectId!)}&seed=${session.seed ?? 1}&lang=${lang}`}
                onLoad={() => { sendPreview({ type: 't', value: time }); sendSeed(session.seed); }}
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
          </section>

          <section className="card">
            <div className="rail-cap">{copy.dataExport}</div>
            <a
              className={`btn-line wide${exportBase ? '' : ' off'}`}
              ref={dataExport}
              href={timingPackageUrl ?? undefined}
              download
              aria-disabled={!exportBase}
            >
              {copy.dataPackage}
            </a>
            <div className="row2">
              <a className={`btn-line${exportBase ? '' : ' off'}`} href={exportBase ? `${exportBase}/rhythm.mid` : undefined} download aria-disabled={!exportBase}>
                {copy.rhythmMidi}
              </a>
              <a className={`btn-line${exportBase ? '' : ' off'}`} href={exportBase ? `${exportBase}/rhythm.csv` : undefined} download aria-disabled={!exportBase}>
                {copy.rhythmCsv}
              </a>
            </div>
            <div className="rail-cap" style={{ marginTop: 6 }}>{copy.filmExport}</div>
            <a
              className={`btn-line wide${hasFilm ? '' : ' off'}`}
              href={hasFilm ? `${job?.video_url}?download=1` : undefined}
              download
              aria-disabled={!hasFilm}
            >
              {hasFilm ? copy.filmReady : copy.filmMissing}
            </a>
          </section>

          <section className="card">
            <div className="rail-cap">{copy.template}</div>
            <div className="kv"><span>{copy.kv.name}</span><b>{TEMPLATE.name}</b></div>
            <div className="kv"><span>{copy.kv.version}</span><b>{TEMPLATE.version}</b></div>
          </section>
        </aside>
      </div>

      {previewReady && rhythm && (
        <CueMap
          rhythm={rhythm}
          time={time}
          seek={seek}
          startBar={startBar}
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
      />
    </div>
  );
}
