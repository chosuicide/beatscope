/**
 * Canvas overview minimap (frozen frame B): board rects + viewport rect.
 * Shown only when the wall exceeds the canvas viewport. Click jumps there.
 */
import { useLayoutEffect, useRef, useState } from 'react';
import { useStore } from '../app/store';
import { translate } from '../app/i18n';
import { BOARD_HEAD, BOARD_FOOT } from '../demo/document';

const INNER_W = 204;
const INNER_H = 110;
const PAD = 4;

export function Minimap() {
  const { state, dispatch } = useStore();
  const t = (key: string) => translate(state.language, key);
  const stageRef = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(false);

  const boxes = state.layout.boards;
  const ids = Object.keys(boxes).sort(
    (a, b) =>
      (state.doc.scenes.find((s) => s.id === a)?.start_time ?? 0) -
      (state.doc.scenes.find((s) => s.id === b)?.start_time ?? 0),
  );

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const id of ids) {
    const b = boxes[id];
    const fullH = BOARD_HEAD + b.bodyH + BOARD_FOOT;
    minX = Math.min(minX, b.x);
    minY = Math.min(minY, b.y);
    maxX = Math.max(maxX, b.x + b.w);
    maxY = Math.max(maxY, b.y + fullH);
  }
  const wallW = maxX - minX || 1;
  const wallH = maxY - minY || 1;
  const scale = Math.min((INNER_W - PAD * 2) / wallW, (INNER_H - PAD * 2) / wallH);
  const ox = PAD + ((INNER_W - PAD * 2) - wallW * scale) / 2;
  const oy = PAD + ((INNER_H - PAD * 2) - wallH * scale) / 2;

  const liveId = state.doc.scenes.find(
    (s) => state.transport.time >= s.start_time && state.transport.time < s.end_time,
  )?.id;

  useLayoutEffect(() => {
    stageRef.current = document.querySelector('.stage');
    const stage = stageRef.current;
    if (!stage) return;
    const update = () => {
      // frame B context rule: overview-only chrome. Focused editing (C) and
      // package review (D) always hide it; the overview shows it when zoomed
      // out past the first-run scale.
      const reviewOpen = state.panels.packageOpen || state.panels.inspectorOpen;
      setShown(!reviewOpen && state.camera.zoom < 0.55);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(stage);
    return () => ro.disconnect();
  });

  if (!shown) return null;

  const jump = (e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const stage = stageRef.current;
    if (!stage) return;
    const wx = (px - ox) / scale + minX;
    const wy = (py - oy) / scale + minY;
    dispatch({
      type: 'camera',
      x: stage.clientWidth / 2 - wx * state.camera.zoom,
      y: stage.clientHeight / 2 - wy * state.camera.zoom,
      zoom: state.camera.zoom,
    });
  };

  // viewport rect in minimap coordinates
  const stage = stageRef.current;
  const vpW = stage ? stage.clientWidth / state.camera.zoom * scale : 0;
  const vpH = stage ? stage.clientHeight / state.camera.zoom * scale : 0;
  const vpX = ox + (0 - minX) * scale - (-state.camera.x) / state.camera.zoom * scale;
  const vpY = oy + (0 - minY) * scale - (-state.camera.y) / state.camera.zoom * scale;

  // hug the stage's right edge, whichever panel occupies it
  const panelW = state.panels.packageOpen ? 400 : state.panels.inspectorOpen ? 320 : 52;

  return (
    <div className="minimap" style={{ right: panelW + 12, bottom: 40 }} onClick={jump} role="button" aria-label={t('canvas.minimap.label')}>
      {ids.map((id) => {
        const b = boxes[id];
        const fullH = BOARD_HEAD + b.bodyH + BOARD_FOOT;
        return (
          <div
            key={id}
            className={`mm-b${state.selection.sceneId === id ? ' sel' : ''}${liveId === id ? ' liv' : ''}`}
            style={{
              left: ox + (b.x - minX) * scale,
              top: oy + (b.y - minY) * scale,
              width: b.w * scale,
              height: fullH * scale,
            }}
          />
        );
      })}
      <div className="mm-vp" style={{ left: vpX, top: vpY, width: vpW, height: vpH }} />
    </div>
  );
}
