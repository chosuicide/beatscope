/**
 * The canvas stage: owns the Pixi host and translates pointer input into
 * camera / selection / board-drag actions. Board drags never enter audio
 * (plan §4): they only produce direction commands.
 */
import { useEffect, useRef, useState } from 'react';
import { useStore, moveBoardCommand } from '../app/store';
import type { BoardBox, DirectionDocument, WorkspaceLayout } from '../direction/types';

import { loadDemoTextures } from '../render/textures';
import { PixiHost } from '../render/pixi-host';
import type { ProposalGhost } from '../render/pixi-host';
import { zoomAtPointer, clampZoom } from '../camera/camera';
import { sceneAtTime, evaluateScene } from '../motion/evaluate';
import { focusCamera } from '../demo/document';
import { translate } from '../app/i18n';

interface DragState {
  sceneId: string;
  grabDX: number;
  grabDY: number;
  startBox: BoardBox;
  moved: boolean;
}


export function CanvasStage() {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hostRef = useRef<PixiHost | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const animRef = useRef<{ from: { x: number; y: number; zoom: number }; to: { x: number; y: number; zoom: number }; t: number } | null>(null);
  const { getState, dispatch, state } = useStore();
  // frame D candidate preview: "After" (ghost overlays) is the default view
  const [previewAfter, setPreviewAfter] = useState(true);
  const previewAfterRef = useRef(true);
  previewAfterRef.current = previewAfter;

  // The canvas keeps the majority of the width; edges follow panel state.
  const left = state.panels.dockOpen ? 280 : 52;
  const right = state.panels.packageOpen ? 400 : state.panels.inspectorOpen ? 320 : 52;

  useEffect(() => {
    const canvas = canvasRef.current;
    const stage = stageRef.current;
    if (!canvas || !stage) return;

    let disposed = false;
    let host: PixiHost | null = null;
    let raf = 0;

    const params = new URLSearchParams(window.location.search);
    // ?nogl=1 exercises the WebGL-unavailable shell state (and is the
    // DOM-screenshot path in headless capture environments).
    if (params.has('nogl')) {
      dispatch({ type: 'webgl', available: false });
      return;
    }
    // ?shot=1 renders N frames then stops the loop so headless capture can
    // read a deterministic, idle page.
    const shotMode = params.has('shot');
    let framesLeft = shotMode ? 24 : Infinity;

    const win = window as unknown as {
      __beathiStatus?: string;
      __beathiErr?: string;
      __beathiReady?: boolean;
      __beathiComposition?: ReturnType<PixiHost['compositionSnapshot']>;
    };
    const start = async () => {
      const rect = stage.getBoundingClientRect();
      win.__beathiStatus = 'init';
      host = new PixiHost({
        onContextLost: () => dispatch({ type: 'webgl', available: false }),
      });
      hostRef.current = host;
      try {
        await host.init(canvas, rect.width, rect.height);
      } catch (e) {
        win.__beathiErr = 'init: ' + String(e);
        dispatch({ type: 'webgl', available: false });
        return;
      }
      if (disposed) {
        host.destroy();
        return;
      }
      const state = getState();
      win.__beathiStatus = 'textures';
      const tex = await loadDemoTextures();
      win.__beathiStatus = 'setDocument';
      try {
        host.setDocument(state.doc, state.layout, tex);
      } catch (e) {
        win.__beathiErr = 'setDocument: ' + String(e);
        return;
      }
      win.__beathiStatus = 'render';
      host.resize(stage.clientWidth, stage.clientHeight);
      host.render();
      win.__beathiStatus = 'ticking';

      // command sync: whenever a committed command replaces the document or
      // layout (rename, split, merge, ratio, crop, undo/redo), the stage
      // rebuilds from the same state the store holds — one source of truth.
      // (Drag moves bypass this: the host is moved live and the command
      // commits the same box afterwards.)
      let lastDoc: DirectionDocument | null = null;
      let lastLayout: WorkspaceLayout | null = null;

      // per-frame sync: camera, live-board arbitration, evaluation, render
      let lastTs = performance.now();
      const tick = (ts: number) => {
        if (framesLeft-- <= 0) {
          (window as unknown as { __beathiReady?: boolean }).__beathiReady = true;
          return;
        }
        raf = requestAnimationFrame(tick);
        if (!hostRef.current) return;
        const h = hostRef.current;
        const s = getState();

        if (s.doc !== lastDoc || s.layout !== lastLayout) {
          lastDoc = s.doc;
          lastLayout = s.layout;
          h.setDocument(s.doc, s.layout, tex);
        }

        h.setFirstRunMode(s.coach.visible && s.selection.sceneId === null);
        h.setFocusIsolation(
          s.selection.sceneId !== null && (s.panels.inspectorOpen || s.panels.packageOpen),
        );

        const dt = Math.min(0.1, (ts - lastTs) / 1000);
        lastTs = ts;

        // camera tween (340 ms settle, interruptible); written back to the
        // store each frame so DOM chrome and restarts observe the same camera
        const anim = animRef.current;
        if (anim) {
          anim.t = Math.min(1, anim.t + dt / 0.34);
          const e = 1 - Math.pow(1 - anim.t, 3);
          const cam = {
            x: anim.from.x + (anim.to.x - anim.from.x) * e,
            y: anim.from.y + (anim.to.y - anim.from.y) * e,
            zoom: anim.from.zoom + (anim.to.zoom - anim.from.zoom) * e,
          };
          h.setCamera(cam);
          dispatch({ type: 'camera', x: cam.x, y: cam.y, zoom: cam.zoom });
          if (anim.t >= 1) animRef.current = null;
        } else {
          h.setCamera(s.camera);
        }

        h.setSelection(s.selection.sceneId, s.selection.layerId);
        // frame D: ghosted candidate regions while the proposal is under review
        if (s.panels.packageOpen && s.proposal && s.proposalState === 'pending' && s.proposal.preview) {
          const byTitle = new Map(s.doc.scenes.map((sc) => [sc.title, sc.id]));
          const items: ProposalGhost[] = [];
          for (const p of previewAfterRef.current ? s.proposal.preview : []) {
            const sceneId = byTitle.get(p.scene);
            if (sceneId) items.push({ sceneId, rect: p.rect, label: p.label });
          }
          h.setProposalPreview(items.length > 0 ? items : null);
        } else {
          h.setProposalPreview(null);
        }
        const liveScene = sceneAtTime(s.doc, s.transport.time);
        h.setLiveScene(liveScene ? liveScene.id : null);
        if (liveScene) {
          h.updateLive(evaluateScene(liveScene, s.transport.time, s.rhythm));
        }
        h.render();
        if (shotMode) win.__beathiComposition = h.compositionSnapshot();
      };
      raf = requestAnimationFrame(tick);
    };
    void start();

    const ro = new ResizeObserver(() => {
      const h = hostRef.current;
      if (!h || !stage) return;
      h.resize(stage.clientWidth, stage.clientHeight);
      h.render();
    });
    ro.observe(stage);

    const captureHandler = () => {
      const h = hostRef.current;
      if (h) {
        (window as unknown as { __beathiCapture: string | null }).__beathiCapture = h.captureDataURL();
      }
    };
    window.addEventListener('beathi:capture', captureHandler);

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener('beathi:capture', captureHandler);
      hostRef.current?.destroy();
      hostRef.current = null;
    };
  }, [dispatch, getState]);

  /* ---------------- pointer input ---------------- */

  const localPoint = (e: PointerEvent | WheelEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const host = hostRef.current;
    if (!host) return;
    const s = getState();
    const p = localPoint(e.nativeEvent);
    if (e.ctrlKey || e.metaKey) {
      const factor = Math.exp(-e.deltaY * 0.0016);
      const next = zoomAtPointer(s.camera, s.camera.zoom * factor, p.x, p.y);
      dispatch({ type: 'camera', x: next.x, y: next.y, zoom: next.zoom });
    } else {
      dispatch({
        type: 'camera',
        x: s.camera.x - e.deltaX,
        y: s.camera.y - e.deltaY,
        zoom: s.camera.zoom,
      });
    }
    animRef.current = null;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    const host = hostRef.current;
    if (!host || e.button !== 0) return;
    const p = localPoint(e.nativeEvent);
    const world = host.toWorld(p.x, p.y);
    const sceneId = host.sceneAtWorld(world.x, world.y);
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    if (sceneId) {
      const box = host.layoutBox(sceneId)!;
      dragRef.current = {
        sceneId,
        grabDX: world.x - box.x,
        grabDY: world.y - box.y,
        startBox: { ...box },
        moved: false,
      };
    } else {
      dragRef.current = null;
    }
    if (sceneId !== getState().selection.sceneId) {
      dispatch({ type: 'select', sceneId, layerId: null, responseId: null });
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const host = hostRef.current;
    const drag = dragRef.current;
    if (!host || !drag) return;
    const p = localPoint(e.nativeEvent);
    const world = host.toWorld(p.x, p.y);
    const box: BoardBox = {
      x: world.x - drag.grabDX,
      y: world.y - drag.grabDY,
      w: drag.startBox.w,
      bodyH: drag.startBox.bodyH,
      rotation: drag.startBox.rotation,
    };
    if (Math.hypot(box.x - drag.startBox.x, box.y - drag.startBox.y) > 2) drag.moved = true;
    const { box: snapped, gx, gy } = host.snapBoxWithGuides(drag.sceneId, box);
    host.moveBoard(drag.sceneId, snapped);
    host.showSnapGuides(gx, gy);
  };

  const onPointerUp = () => {
    const drag = dragRef.current;
    const host = hostRef.current;
    dragRef.current = null;
    host?.showSnapGuides(null);
    if (!drag || !host || !drag.moved) return;
    const box = host.layoutBox(drag.sceneId);
    if (!box) return;
    dispatch({
      type: 'command',
      command: moveBoardCommand(drag.sceneId, drag.startBox, box),
    });
  };

  /** Camera helper for keyboard/App: focus a scene board. */
  const focusScene = (sceneId: string) => {
    const s = getState();
    const stage = stageRef.current;
    const box = s.layout.boards[sceneId];
    if (!stage || !box) return;
    const right = s.panels.packageOpen ? 400 : s.panels.inspectorOpen ? 320 : 0;
    animRef.current = {
      from: { ...s.camera },
      to: focusCamera(box, stage.clientWidth - right, stage.clientHeight),
      t: 0,
    };
  };

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ sceneId: string }>).detail;
      if (detail?.sceneId) focusScene(detail.sceneId);
    };
    window.addEventListener('beathi:focus-scene', handler);
    return () => window.removeEventListener('beathi:focus-scene', handler);
  });

  const selBox = state.selection.sceneId ? state.layout.boards[state.selection.sceneId] : null;
  const showToggle =
    !!state.panels.packageOpen && !!state.proposal && state.proposalState === 'pending' && !!selBox;
  const cam = state.camera;

  return (
    <div
      ref={stageRef}
      className="stage"
      id="beathi-canvas"
      style={{ left, right }}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      <canvas ref={canvasRef} />
      <div className="grain" aria-hidden="true" />
      {showToggle && selBox && (
        <div
          className="mseg-toggle"
          style={{ left: selBox.x * cam.zoom + cam.x, top: selBox.y * cam.zoom + cam.y - 40 }}
        >
          <button className={!previewAfter ? 'on' : ''} onClick={() => setPreviewAfter(false)}>
            {translate(state.language, 'canvas.preview.before')}
          </button>
          <button className={previewAfter ? 'on' : ''} onClick={() => setPreviewAfter(true)}>
            {translate(state.language, 'canvas.preview.after')}
          </button>
        </div>
      )}
    </div>
  );
}

export { clampZoom };
