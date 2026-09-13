/**
 * App shell: boot state machine (§3.5), service detection, keyboard map,
 * transport clock, WebMCP bridge install, and the frozen chrome layout.
 */
import { useEffect, useRef, useState } from 'react';
import { useStore, moveBoardCommand } from './app/store';
import type { DirectionDocument, WorkspaceDocument } from './direction/types';
import type { BeatScopeServices } from './services/types';
import { DirectionConflictError } from './services/conflict';
import { StaticDemoServices } from './services/demo';
import { LocalStudioServices } from './services/localStudio';
import { installLegacyWebMCP } from './services/webmcpBridge';
import { TopBar } from './components/TopBar';
import { LeftDock } from './components/LeftDock';
import { Inspector } from './components/Inspector';
import { PackagePanel } from './components/PackagePanel';
import { Transport } from './components/Transport';
import { CoachMark } from './components/CoachMark';
import { Minimap } from './components/Minimap';
import { Toasts, NoGl } from './components/Toasts';
import { CanvasStage } from './canvas/CanvasStage';
import { translate } from './app/i18n';
import { demoProposal } from './demo/proposal';
import { fitAllCamera, focusCamera } from './demo/document';
import { clampZoom } from './camera/camera';

async function detectServices(): Promise<BeatScopeServices> {
  try {
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 1200);
    const res = await fetch('/api/projects', { signal: ctrl.signal });
    clearTimeout(timer);
    const ctype = res.headers.get('content-type') ?? '';
    if (res.ok && ctype.includes('json')) return new LocalStudioServices();
  } catch {
    /* static hosting falls through to the demo */
  }
  return new StaticDemoServices();
}

export function App() {
  const { state, dispatch, getState } = useStore();
  const [services, setServices] = useState<BeatScopeServices | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const bootedRef = useRef(false);

  /* boot: fonts → service probe → ready (§3.5) */
  useEffect(() => {
    if (bootedRef.current) return;
    bootedRef.current = true;
    let alive = true;
    void (async () => {
      try {
        await Promise.race([
          Promise.all([
            document.fonts.load('900 20px Geist'),
            document.fonts.load('520 13px Geist'),
            document.fonts.load('500 12px "Geist Mono"'),
          ]),
          new Promise((r) => window.setTimeout(r, 2000)),
        ]);
      } catch {
        /* fonts optional */
      }
      const svc = await detectServices();
      if (!alive) return;
      setServices(svc);
      dispatch({ type: 'boot', status: svc.mode === 'local-studio' ? 'loading-project' : 'recovering-draft' });
      let loaded: { doc: DirectionDocument; rhythm?: import('./demo/rhythm').DemoRhythm | null; workspace?: WorkspaceDocument | null; recoveredDraft?: boolean } | null = null;
      let conflict = false;
      try {
        const projects = await svc.listProjects();
        const projectId = projects.at(-1)?.project_id ?? 'beyond-the-fog-01';
        loaded = await svc.loadProject(projectId);
      } catch (err) {
        conflict = err instanceof DirectionConflictError;
      }
      if (!alive) return;
      if (loaded) {
        lastSavedDocRef.current = loaded.recoveredDraft ? null : loaded.doc;
        dispatch({ type: 'doc-loaded', doc: loaded.doc, rhythm: loaded.rhythm, workspace: loaded.workspace });
        dispatch({ type: 'boot', status: svc.mode === 'local-studio' ? 'ready' : 'read-only-demo' });
      } else {
        dispatch({ type: 'boot', status: conflict ? 'conflict' : 'fatal' });
      }
      dispatch({ type: 'proposal', proposal: demoProposal, state: 'pending' });
      void installLegacyWebMCP(svc, () => stateRef.current).then(() => {});
    })();
    return () => {
      alive = false;
    };
  }, [dispatch]);

  /* autosave (§4.7): debounced direction persistence with optimistic
   * concurrency. Edits mark the document dirty (commands set saveState
   * 'offline'); this effect drains it. Browser draft bytes are updated
   * immediately; the canonical server save follows after 750 ms. A stale
   * write remains blocked until an explicit reconciliation reload. */
  const saveSeqRef = useRef(0);
  const lastSavedDocRef = useRef<DirectionDocument | null>(null);
  const servicesRef = useRef<BeatScopeServices | null>(null);
  servicesRef.current = services;
  useEffect(() => {
    const svc = servicesRef.current;
    if (!svc) return;
    if (state.boot !== 'ready' && state.boot !== 'read-only-demo') return;
    if (state.doc === lastSavedDocRef.current) return;
    const doc = state.doc;
    svc.saveDraft(doc);
    const seq = ++saveSeqRef.current;
    dispatch({ type: 'save-state', state: 'saving' });
    const timer = window.setTimeout(() => {
      void svc
        .saveDirection(doc)
        .then(() => {
          if (seq !== saveSeqRef.current || lastSavedDocRef.current === doc) return;
          lastSavedDocRef.current = doc;
          dispatch({ type: 'save-state', state: 'saved' });
        })
        .catch((err) => {
          if (seq !== saveSeqRef.current) return;
          if (err instanceof DirectionConflictError) {
            dispatch({ type: 'save-state', state: 'conflict' });
            dispatch({ type: 'toast', text: err.message });
          } else {
            dispatch({ type: 'save-state', state: 'offline' });
            dispatch({ type: 'toast', text: 'Save failed — your edits stay as a local draft.' });
          }
        });
    }, 750);
    return () => window.clearTimeout(timer);
  }, [state.boot, state.doc, dispatch, getState]);

  /* Editor-only geometry/preferences persist separately from direction. */
  useEffect(() => {
    const svc = servicesRef.current;
    if (!svc || (state.boot !== 'ready' && state.boot !== 'read-only-demo')) return;
    const workspace: WorkspaceDocument = {
      schema: 'beathi-workspace-1', version: '0.12.0', project_id: state.doc.project_id,
      source_rhythm_sha256: state.doc.source_rhythm_sha256, layout: state.layout,
      camera: state.camera, selection: state.selection, panels: state.panels,
    };
    const timer = window.setTimeout(() => void svc.saveWorkspace(workspace), 750);
    return () => window.clearTimeout(timer);
  }, [state.boot, state.doc.project_id, state.doc.source_rhythm_sha256, state.layout, state.camera, state.selection, state.panels]);

  /* deterministic view preseed for tests/screenshots: ?sel=&lay=&seek=&fit=&dock=&package=&play=&loop= */
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current) return;
    if (state.boot !== 'ready' && state.boot !== 'read-only-demo') return;
    seededRef.current = true;
    const q = new URLSearchParams(window.location.search);
    const num = (k: string) => {
      const v = q.get(k);
      if (v === null || v === '') return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };
    const sel = q.get('sel');
    const lay = q.get('lay');
    if (sel) {
      // ?resp=1 pre-expands the selected layer's first response chain (frame C)
      let responseId: string | null = null;
      if (lay && q.get('resp') === '1') {
        const sc = state.doc.scenes.find((s) => s.id === sel);
        responseId =
          sc?.responses.find((r) => r.target_layer_id === lay)?.id ?? sc?.responses[0]?.id ?? null;
      }
      dispatch({ type: 'select', sceneId: sel, layerId: lay, responseId });
    }
    if (sel && lay && q.get('package') !== '1') {
      dispatch({ type: 'panels', inspectorOpen: true });
    }
    const seek = num('seek');
    if (seek !== null) dispatch({ type: 'transport-time', time: seek });
    if (q.get('dock') === '0') dispatch({ type: 'panels', dockOpen: false });
    if (q.get('package') === '1') dispatch({ type: 'panels', packageOpen: true, inspectorOpen: false });
    if (q.get('loop') === '1') {
      const sc = state.doc.scenes.find((x) => x.id === (sel ?? state.doc.scenes[0].id));
      if (sc) dispatch({ type: 'transport-loop', start: sc.start_time, end: sc.end_time });
    }
    if (q.get('play') === '1') dispatch({ type: 'transport-play', playing: true });
    if (q.get('focus') === '1' && sel) {
      const box = state.layout.boards[sel];
      const dockOpen = q.get('dock') !== '0';
      const packageOpen = q.get('package') === '1';
      const inspectorOpen = packageOpen ? false : !!q.get('lay');
      const left = dockOpen ? 280 : 52;
      const right = packageOpen ? 400 : inspectorOpen ? 320 : 52;
      if (box) {
        const cam = focusCamera(box, window.innerWidth - left - right, window.innerHeight - 48);
        dispatch({ type: 'camera', x: cam.x, y: cam.y, zoom: cam.zoom });
      }
    }
    if (q.get('fit') === '1') {
      const dockOpen = q.get('dock') !== '0';
      const packageOpen = q.get('package') === '1';
      const inspectorOpen = packageOpen ? false : !!q.get('lay');
      const left = dockOpen ? 280 : 52;
      const right = packageOpen ? 400 : inspectorOpen ? 320 : 52;
      const cam = fitAllCamera(window.innerWidth - left - right, window.innerHeight - 48, state.layout);
      dispatch({ type: 'camera', x: cam.x, y: cam.y, zoom: cam.zoom });
    }
  }, [state.boot, state.doc, dispatch]);

  /* transport clock: presentation time only; musical evaluation stays pure */
  useEffect(() => {
    if (!state.transport.playing) return;
    // screenshot mode keeps the seeded time frozen (deterministic capture)
    if (new URLSearchParams(window.location.search).has('shot')) return;
    let raf = 0;
    let last = performance.now();
    const tick = (ts: number) => {
      raf = requestAnimationFrame(tick);
      const dt = Math.min(0.1, (ts - last) / 1000);
      last = ts;
      const s = getState();
      if (!s.transport.playing) return;
      let t = s.transport.time + dt;
      const dur = s.doc.scenes[s.doc.scenes.length - 1]?.end_time ?? 242;
      const lo = s.transport.loopStart ?? 0;
      const hi = s.transport.loopEnd ?? dur;
      if (t >= hi) t = lo + ((t - lo) % Math.max(0.001, hi - lo));
      dispatch({ type: 'transport-time', time: t });
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [state.transport.playing, getState, dispatch]);

  /* keyboard map (capability-migration ledger rows) */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      const s = getState();
      const mod = e.metaKey || e.ctrlKey;

      if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        dispatch({ type: e.shiftKey ? 'redo' : 'undo' });
        return;
      }
      switch (e.key) {
        case ' ': {
          e.preventDefault();
          dispatch({ type: 'transport-play', playing: !s.transport.playing });
          break;
        }
        case '0': {
          const stage = document.querySelector('.stage');
          if (stage) {
            const cam = fitAllCamera(stage.clientWidth, stage.clientHeight, getState().layout);
            dispatch({ type: 'camera', x: cam.x, y: cam.y, zoom: cam.zoom });
          }
          break;
        }
        case 'f':
        case 'F': {
          if (s.selection.sceneId) {
            window.dispatchEvent(
              new CustomEvent('beathi:focus-scene', { detail: { sceneId: s.selection.sceneId } }),
            );
          }
          break;
        }
        case '+':
        case '=': {
          const stage = document.querySelector('.stage');
          if (stage) {
            const z = clampZoom(s.camera.zoom * 1.2);
            const cx = stage.clientWidth / 2;
            const cy = stage.clientHeight / 2;
            const wx = (cx - s.camera.x) / s.camera.zoom;
            const wy = (cy - s.camera.y) / s.camera.zoom;
            dispatch({ type: 'camera', x: cx - wx * z, y: cy - wy * z, zoom: z });
          }
          break;
        }
        case '-': {
          const stage = document.querySelector('.stage');
          if (stage) {
            const z = clampZoom(s.camera.zoom / 1.2);
            const cx = stage.clientWidth / 2;
            const cy = stage.clientHeight / 2;
            const wx = (cx - s.camera.x) / s.camera.zoom;
            const wy = (cy - s.camera.y) / s.camera.zoom;
            dispatch({ type: 'camera', x: cx - wx * z, y: cy - wy * z, zoom: z });
          }
          break;
        }
        case 'Escape':
          dispatch({ type: 'select', sceneId: null, layerId: null, responseId: null });
          break;
        default:
          break;
      }

      if (e.shiftKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
        e.preventDefault();
        const scenes = [...s.doc.scenes].sort((a, b) => a.start_time - b.start_time);
        const cur = scenes.findIndex((sc) => s.transport.time >= sc.start_time && s.transport.time < sc.end_time);
        const next = Math.max(0, Math.min(scenes.length - 1, cur + (e.key === 'ArrowRight' ? 1 : -1)));
        const scene = scenes[next];
        if (scene) {
          dispatch({ type: 'select', sceneId: scene.id, layerId: null, responseId: null });
          dispatch({ type: 'transport-time', time: scene.start_time + 0.4 });
          window.dispatchEvent(new CustomEvent('beathi:focus-scene', { detail: { sceneId: scene.id } }));
        }
        return;
      }

      // arrow nudges move the selected board (mergeKey merges into one undo)
      if (
        s.selection.sceneId &&
        ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key) &&
        !e.shiftKey
      ) {
        e.preventDefault();
        const box = s.layout.boards[s.selection.sceneId];
        if (!box) return;
        const step = 1;
        const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0;
        const dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
        dispatch({
          type: 'command',
          command: moveBoardCommand(s.selection.sceneId, { x: box.x, y: box.y }, { x: box.x + dx, y: box.y + dy }),
        });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [getState, dispatch]);

  const t = (key: string) => translate(state.language, key);
  const booted = state.boot === 'ready' || state.boot === 'read-only-demo';
  const veilVisible = !booted && state.boot !== 'fatal';
  const railRight = !state.panels.inspectorOpen && !state.panels.packageOpen;

  const focusSelected = () => {
    const s = stateRef.current;
    if (s.selection.sceneId) {
      const box = s.layout.boards[s.selection.sceneId];
      const stage = document.querySelector('.stage');
      if (box && stage) {
        const cam = focusCamera(box, stage.clientWidth, stage.clientHeight);
        dispatch({ type: 'camera', x: cam.x, y: cam.y, zoom: cam.zoom });
      }
    }
    dispatch({ type: 'panels', inspectorOpen: true, packageOpen: false });
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#beathi-canvas">
        {state.language === 'en' ? 'Skip to canvas' : '跳转到画布'}
      </a>
      <TopBar mode={services?.mode ?? 'static-demo'} />
      <LeftDock />
      <CanvasStage />
      <Inspector />
      <PackagePanel />
      {railRight && (
        <aside className="rail right" onClick={focusSelected}>
          <button className="ibtn" aria-label="inspector">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
              <rect x="2.5" y="2.5" width="11" height="11" rx="2" />
              <path d="M6 2.5v11" />
            </svg>
          </button>
          <button className="ibtn" aria-label="inspector wide">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
              <rect x="2.5" y="2.5" width="11" height="11" rx="2" />
              <path d="M2.5 6h11" />
            </svg>
          </button>
          <div className="rlab">Inspector</div>
        </aside>
      )}
      <Transport />
      <CoachMark />
      <Minimap />
      <Toasts />
      <NoGl />
      <div className="boot-veil" hidden={!veilVisible}>
        <span>{t(`boot.state.${veilVisible ? state.boot : 'ready'}`)}</span>
      </div>
    </div>
  );
}

export default App;
