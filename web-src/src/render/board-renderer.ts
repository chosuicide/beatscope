/**
 * Board renderer: draws one DirectionScene as a Pixi "desk board" that
 * reproduces the frozen frame-A board chrome and artwork.
 *
 * Coordinate model: all art/chrome values are authored in reference pixels
 * (the values from docs/design/beathi-canvas/frame-a.html); the whole board
 * container is scaled by BOARD_SCALE so that at the first-run camera zoom
 * (0.62) every reference pixel maps to exactly one screen pixel.
 *
 * Layer content comes from the system registry (systems/index.ts). Each
 * layer wrapper applies the authored normalized transform, blend mode and
 * crop window; identity transforms reproduce the frozen frames exactly.
 */
import {
  type TextStyleFontWeight,
  BlurFilter,
  ColorMatrixFilter,
  Container,
  Graphics,
  Text,
  TextStyle,
} from 'pixi.js';
import type {
  DirectionScene,
  DirectionLayer,
  BoardBox,
} from '../direction/types';
import { BOARD_HEAD_REF, BOARD_FOOT_REF } from '../demo/document.js';
import type { DemoTextures } from './textures.js';
import { BOARD_SCALE } from './scale.js';
import { renderLayerSystem, NO_ASSETS, type AssetResolver } from '../systems/index.js';
import type { LayerOutput } from '../motion/evaluate.js';

const PAPER1 = 0xfbfaf7;
const ACCENT = 0x7567e8;
const STROKE1 = 1 / 0.62; // 1 screen px at first-run zoom

function lineStrong(alpha = 0.14) {
  return { width: STROKE1, color: 0x22281f, alpha };
}

const TRANSITION_LABEL: Record<string, string> = {
  dissolve: 'dissolve',
  cut: 'cut',
  'directional-wipe': 'wipe',
  'hold-through': 'hold',
};

function uiStyle(size: number, weight: TextStyleFontWeight, color: number | string, tracking = -0.008): TextStyle {
  return new TextStyle({
    fontFamily: 'Geist',
    fontSize: size,
    fontWeight: weight,
    letterSpacing: tracking * size,
    fill: color,
  });
}

function monoStyle(size: number, color: number | string, tracking = 0.02): TextStyle {
  return new TextStyle({
    fontFamily: '"Geist Mono", monospace',
    fontSize: size,
    fontWeight: '500',
    letterSpacing: tracking * size,
    fill: color,
  });
}

function makeText(text: string, style: TextStyle): Text {
  // Focus mode can enlarge a board beyond 1x. Rasterise type above device
  // resolution so the canvas does not turn editorial typography into a soft
  // screenshot when the camera settles around 160–180%.
  const t = new Text({ text, style, resolution: Math.max(2, Math.min(4, (window.devicePixelRatio || 1) * 2)) });
  return t;
}

/* ------------------------------------------------------------------ */
/* board assembly                                                      */
/* ------------------------------------------------------------------ */

export interface BoardVisual {
  sceneId: string;
  container: Container;
  layerWrappers: Map<string, Container>;
  layerCenters: Map<string, { x: number; y: number }>;
  /** authored wrapper scale before response output (transform.w/h) */
  baseScale: Map<string, { x: number; y: number }>;
  /** per-layer runtime used to apply and reset response channels */
  runtimes: Map<string, LayerRuntime>;
  /** media-slice print regions in container-local reference pixels (frame C guides) */
  layerRects: Map<string, { x: number; y: number; w: number; h: number }>;
  head: Container;
  foot: Container;
  artContainer: Container;
  liveTag: Container;
  shadow: Container;
  box: BoardBox;
  baseOpacity: Map<string, number>;
}

/** Authored base + lazily created filters/masks for one layer. */
export interface LayerRuntime {
  wrapper: Container;
  inner: Container;
  center: { x: number; y: number };
  baseScale: { x: number; y: number };
  baseRotation: number;
  baseOpacity: number;
  bodyW: number;
  bodyH: number;
  /** layer-centre in wrapper-local coordinates */
  cx: number;
  cy: number;
  staticCrop: { left: number; top: number; right: number; bottom: number } | null;
  staticMask: Graphics | null;
  dynamicMask: Graphics | null;
  blurFilter: BlurFilter | null;
  invertFilter: ColorMatrixFilter | null;
}

function buildShadow(w: number, fullH: number): Container {
  const c = new Container();
  const layers: Array<[number, number, number, number, number]> = [
    // dx, dy, expandX, expandY, alpha — three shadow-board components
    [0, 1, 1, 1, 0.05],
    [0, 12, 7, 8, 0.05],
    [0, 36, 16, 18, 0.028],
  ];
  for (const [, dy, ex, ey, alpha] of layers) {
    c.addChild(
      new Graphics()
        .roundRect(-ex, -ex + dy, w + ex * 2, fullH + ey * 2 - dy, 10 + ex)
        .fill({ color: 0x231e2d, alpha }),
    );
  }
  c.eventMode = 'none';
  return c;
}

function buildHead(
  scene: DirectionScene,
  boardW: number,
  live: boolean,
): { head: Container; liveTag: Container } {
  const head = new Container();
  head.addChild(new Graphics().rect(0, 0, boardW, BOARD_HEAD_REF).fill(PAPER1));

  const idx = makeText(sceneNum(scene.id), monoStyle(10, '#77737d'));
  idx.x = 10;
  idx.y = (BOARD_HEAD_REF - idx.height) / 2;
  head.addChild(idx);

  const ttl = makeText(scene.title, uiStyle(13, '500', '#171719'));
  ttl.x = idx.x + idx.width + 7;
  ttl.y = (BOARD_HEAD_REF - ttl.height) / 2;
  head.addChild(ttl);

  const time = makeText(fmtRange(scene.start_time, scene.end_time), monoStyle(10, '#77737d'));
  time.x = boardW - 10 - time.width;
  time.y = (BOARD_HEAD_REF - time.height) / 2;
  head.addChild(time);

  // the live tag is always built so setLiveScene can toggle it later
  const liveTag = new Container();
  {
    const dot = new Graphics().circle(3, 3, 3).fill(ACCENT);
    dot.y = (BOARD_HEAD_REF - 6) / 2;
    const label = makeText('LIVE', monoStyle(10, '#7567e8'));
    label.x = 10;
    label.y = (BOARD_HEAD_REF - label.height) / 2;
    liveTag.addChild(dot, label);
    liveTag.x = time.x - 7 - (label.width + 10);
    liveTag.visible = live;
    head.addChild(liveTag);
  }

  head.addChild(
    new Graphics()
      .rect(0, BOARD_HEAD_REF - STROKE1, boardW, STROKE1)
      .fill({ color: 0x22281f, alpha: 0.075 }),
  );
  head.eventMode = 'none';
  return { head, liveTag };
}

function buildFoot(scene: DirectionScene, boardW: number, bodyH: number): Container {
  const foot = new Container();
  const y0 = BOARD_HEAD_REF + bodyH;
  foot.addChild(new Graphics().rect(0, y0, boardW, BOARD_FOOT_REF).fill(PAPER1));
  foot.addChild(
    new Graphics()
      .rect(0, y0, boardW, STROKE1)
      .fill({ color: 0x22281f, alpha: 0.075 }),
  );
  const label = makeText(
    `${scene.family} · ${scene.layers.length} layers`,
    uiStyle(11, '500', '#77737d', 0.012),
  );
  label.x = 10;
  label.y = y0 + (BOARD_FOOT_REF - label.height) / 2;
  foot.addChild(label);
  const tr = makeText(
    TRANSITION_LABEL[scene.transition_out] ?? scene.transition_out,
    monoStyle(10, '#77737d'),
  );
  tr.x = boardW - 10 - tr.width;
  tr.y = y0 + (BOARD_FOOT_REF - tr.height) / 2;
  foot.addChild(tr);
  foot.eventMode = 'none';
  return foot;
}

function sceneNum(sceneId: string): string {
  const n = parseInt(sceneId.replace('scene-', ''), 10);
  return String(n).padStart(2, '0');
}

export function fmtTime(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function fmtRange(a: number, b: number): string {
  return `${fmtTime(a)}–${fmtTime(b)}`;
}

/** Pixi blend modes accepted by the layer contract. */
const BLEND_MODES = new Set(['normal', 'multiply', 'screen', 'difference', 'overlay']);

function cropMask(layer: DirectionLayer, bodyW: number, bodyH: number, cx: number, cy: number): Graphics | null {
  const crop = layer.transform.crop;
  if (!crop) return null;
  const left = Math.max(0, Math.min(1, crop.left));
  const top = Math.max(0, Math.min(1, crop.top));
  const right = Math.max(0, Math.min(1, crop.right));
  const bottom = Math.max(0, Math.min(1, crop.bottom));
  const w = Math.max(0.001, 1 - left - right) * bodyW;
  const h = Math.max(0.001, 1 - top - bottom) * bodyH;
  // wrapper-local coordinates have their origin at the layer centre
  return new Graphics()
    .rect(-cx + left * bodyW, -cy + top * bodyH, w, h)
    .fill({ color: 0xffffff });
}

/**
 * Build the full board container for a scene. All coordinates inside are
 * reference pixels; the container itself is scaled by BOARD_SCALE and placed
 * at the board's world position.
 */
export function buildBoard(
  scene: DirectionScene,
  box: BoardBox,
  tex: DemoTextures,
  live: boolean,
  assets: AssetResolver = NO_ASSETS,
): BoardVisual {
  const boardW = box.w / BOARD_SCALE;
  const bodyH = box.bodyH / BOARD_SCALE;
  const fullH = BOARD_HEAD_REF + bodyH + BOARD_FOOT_REF;

  const container = new Container();
  container.position.set(box.x, box.y);
  container.scale.set(BOARD_SCALE);
  if (box.rotation) container.rotation = (box.rotation * Math.PI) / 180;

  const shadow = buildShadow(boardW, fullH);
  container.addChild(shadow);

  const plate = new Graphics()
    .roundRect(0, 0, boardW, fullH, 10)
    .fill(PAPER1)
    .stroke(lineStrong());
  container.addChild(plate);

  const { head, liveTag } = buildHead(scene, boardW, live);
  const foot = buildFoot(scene, boardW, bodyH);
  container.addChild(head, foot);

  // art area, clipped to the body with rounded bottom corners
  const art = new Container();
  const artMask = new Graphics();
  const r = 9;
  artMask.moveTo(1, BOARD_HEAD_REF + 1);
  artMask.lineTo(boardW - 1, BOARD_HEAD_REF + 1);
  artMask.lineTo(boardW - 1, BOARD_HEAD_REF + bodyH - r);
  artMask.arcTo(boardW - 1, BOARD_HEAD_REF + bodyH, boardW - 1 - r, BOARD_HEAD_REF + bodyH, r);
  artMask.lineTo(1 + r, BOARD_HEAD_REF + bodyH);
  artMask.arcTo(1, BOARD_HEAD_REF + bodyH, 1, BOARD_HEAD_REF + bodyH - r, r);
  artMask.closePath();
  artMask.fill({ color: 0xffffff });
  art.mask = artMask;
  container.addChild(artMask, art);

  const dark = ['collage', 'signal', 'cut study', 'still'].includes(scene.family);
  if (dark) {
    art.addChild(
      new Graphics()
        .rect(0, BOARD_HEAD_REF, boardW, bodyH)
        .fill(scene.family === 'cut study' ? 0x0e0e11 : scene.family === 'still' ? 0x0b0b0d : 0x101014),
    );
  }

  const layerWrappers = new Map<string, Container>();
  const layerCenters = new Map<string, { x: number; y: number }>();
  const baseScale = new Map<string, { x: number; y: number }>();
  const baseOpacity = new Map<string, number>();
  const layerRects = new Map<string, { x: number; y: number; w: number; h: number }>();
  const runtimes = new Map<string, LayerRuntime>();

  for (const layerObj of scene.layers) {
    const wrapper = new Container();
    const inner = new Container();
    const content = renderLayerSystem({
      kind: layerObj.kind,
      props: layerObj.props as Record<string, unknown>,
      textures: tex,
      assets,
      bodyW: boardW,
      bodyH,
      dark,
    });
    content.position.set(0, BOARD_HEAD_REF);
    // mask coordinates are art-relative; wrap content so masks stay aligned
    inner.position.set(0, -BOARD_HEAD_REF);
    inner.addChild(content);

    const transform = layerObj.transform;
    const tw = Number.isFinite(transform.w) && transform.w > 0 ? transform.w : 1;
    const th = Number.isFinite(transform.h) && transform.h > 0 ? transform.h : 1;
    const cx = (boardW * tw) / 2;
    const cy = (bodyH * th) / 2;
    wrapper.addChild(inner);
    wrapper.pivot.set(cx, cy);
    wrapper.position.set(
      transform.x * boardW + cx,
      BOARD_HEAD_REF + transform.y * bodyH + cy,
    );
    wrapper.scale.set(tw, th);
    if (transform.rotation) wrapper.rotation = (transform.rotation * Math.PI) / 180;
    if (layerObj.blend && BLEND_MODES.has(layerObj.blend)) wrapper.blendMode = layerObj.blend;

    const mask = cropMask(layerObj, boardW, bodyH, cx, cy);
    if (mask) {
      wrapper.addChild(mask);
      inner.mask = mask;
    }

    art.addChild(wrapper);

    if (!layerObj.visible || layerObj.opacity === 0) wrapper.visible = false;
    wrapper.alpha = layerObj.opacity;
    layerWrappers.set(layerObj.id, wrapper);
    layerCenters.set(layerObj.id, { x: transform.x * boardW + cx, y: BOARD_HEAD_REF + transform.y * bodyH + cy });
    baseScale.set(layerObj.id, { x: tw, y: th });
    baseOpacity.set(layerObj.id, layerObj.opacity);
    runtimes.set(layerObj.id, {
      wrapper,
      inner,
      center: { x: transform.x * boardW + cx, y: BOARD_HEAD_REF + transform.y * bodyH + cy },
      baseScale: { x: tw, y: th },
      baseRotation: transform.rotation ?? 0,
      baseOpacity: layerObj.opacity,
      bodyW: boardW,
      bodyH,
      cx,
      cy,
      staticCrop: transform.crop ? { ...transform.crop } : null,
      staticMask: mask,
      dynamicMask: null,
      blurFilter: null,
      invertFilter: null,
    });

    // record printed media regions for the selection overlay (frame C)
    if (layerObj.kind === 'media-slice') {
      const props = layerObj.props as Record<string, unknown>;
      let rect: { x: number; y: number; w: number; h: number } | null = null;
      if (props.frame === 'print') {
        const pr = props.rect as { x: number; y: number; w: number; photoH: number } | undefined;
        if (pr) rect = { x: pr.x + 7, y: BOARD_HEAD_REF + pr.y + 7, w: pr.w - 14, h: pr.photoH };
      } else if (props.full === true) {
        rect = { x: 0, y: BOARD_HEAD_REF, w: boardW, h: bodyH };
      } else {
        const pr = props.rect as { x: number; y: number; w: number; h: number } | undefined;
        if (pr) {
          rect = {
            x: pr.x * boardW,
            y: BOARD_HEAD_REF + pr.y * bodyH,
            w: pr.w * boardW,
            h: pr.h * bodyH,
          };
        }
      }
      if (rect) {
        // the recorded region follows the authored layer transform so the
        // frame-C overlay stays on the printed slice
        layerRects.set(layerObj.id, {
          x: transform.x * boardW + rect.x * tw,
          y: BOARD_HEAD_REF + transform.y * bodyH + (rect.y - BOARD_HEAD_REF) * th,
          w: rect.w * tw,
          h: rect.h * th,
        });
      }
    }
  }

  return {
    sceneId: scene.id,
    container,
    layerWrappers,
    layerCenters,
    layerRects,
    runtimes,
    head,
    foot,
    artContainer: art,
    liveTag,
    shadow,
    box,
    baseOpacity,
    baseScale,
  };
}

/** Lazily create/reuse the blur filter for a response output. */
function blurFor(runtime: LayerRuntime, radius: number): BlurFilter | null {
  if (radius <= 0.01) {
    if (runtime.blurFilter) runtime.blurFilter.strength = 0;
    return runtime.blurFilter;
  }
  if (!runtime.blurFilter) {
    runtime.blurFilter = new BlurFilter({ strength: radius, quality: 3 });
    runtime.wrapper.filters = [...(runtime.wrapper.filters ?? []), runtime.blurFilter];
  } else {
    runtime.blurFilter.strength = radius;
  }
  return runtime.blurFilter;
}

/** Palette inversion: lerp the colour matrix from identity by influence. */
function invertFor(runtime: LayerRuntime, influence: number): ColorMatrixFilter | null {
  if (influence <= 0) {
    if (runtime.invertFilter) runtime.invertFilter.matrix = IDENTITY_MATRIX;
    return runtime.invertFilter;
  }
  if (!runtime.invertFilter) {
    runtime.invertFilter = new ColorMatrixFilter();
    runtime.wrapper.filters = [...(runtime.wrapper.filters ?? []), runtime.invertFilter];
  }
  runtime.invertFilter.matrix = [
    1 - 2 * influence, 0, 0, 0, influence,
    0, 1 - 2 * influence, 0, 0, influence,
    0, 0, 1 - 2 * influence, 0, influence,
    0, 0, 0, 1, 0,
  ] as ColorMatrixFilter['matrix'];
  return runtime.invertFilter;
}

const IDENTITY_MATRIX = [
  1, 0, 0, 0, 0,
  0, 1, 0, 0, 0,
  0, 0, 1, 0, 0,
  0, 0, 0, 1, 0,
] as ColorMatrixFilter['matrix'];

/** Dynamic crop-reveal mask intersected with the authored crop window. */
function updateCropMask(runtime: LayerRuntime, progress: number): void {
  if (progress <= 0.001) {
    if (runtime.dynamicMask) {
      runtime.dynamicMask.visible = false;
    }
    runtime.inner.mask = runtime.staticMask;
    return;
  }
  const base = runtime.staticCrop ?? { left: 0, top: 0, right: 0, bottom: 0 };
  const inset = Math.min(0.45, progress * 0.5);
  const left = base.left + inset;
  const top = base.top + inset;
  const right = base.right + inset;
  const bottom = base.bottom + inset;
  const w = Math.max(1, (1 - left - right) * runtime.bodyW);
  const h = Math.max(1, (1 - top - bottom) * runtime.bodyH);
  if (!runtime.dynamicMask) {
    runtime.dynamicMask = new Graphics();
    runtime.wrapper.addChild(runtime.dynamicMask);
  }
  runtime.dynamicMask.visible = true;
  runtime.dynamicMask
    .clear()
    .rect(-runtime.cx + left * runtime.bodyW, -runtime.cy + top * runtime.bodyH, w, h)
    .fill({ color: 0xffffff });
  runtime.inner.mask = runtime.dynamicMask;
}

/** Apply evaluated response outputs to a live board. */
export function applyOutputs(visual: BoardVisual, outputs: Map<string, LayerOutput>): void {
  for (const [layerId, out] of outputs) {
    const runtime = visual.runtimes.get(layerId);
    if (!runtime) continue;
    const { wrapper, center, baseScale, baseRotation } = runtime;
    wrapper.scale.set(baseScale.x * out.scale, baseScale.y * out.scale);
    const stripShift = out.strip * runtime.bodyW * baseScale.x * 0.15;
    wrapper.x = center.x + out.translate.x + stripShift;
    wrapper.y = center.y + out.translate.y;
    wrapper.rotation = ((baseRotation + out.rotation) * Math.PI) / 180;
    wrapper.alpha = runtime.baseOpacity * out.opacity;
    blurFor(runtime, out.blur);
    invertFor(runtime, out.invert);
    updateCropMask(runtime, out.crop);
  }
}

/** Reset a live board to its authored (time-invariant) pose. */
export function resetOutputs(visual: BoardVisual): void {
  for (const runtime of visual.runtimes.values()) {
    const { wrapper, center, baseScale, baseRotation } = runtime;
    wrapper.scale.set(baseScale.x, baseScale.y);
    wrapper.x = center.x;
    wrapper.y = center.y;
    wrapper.rotation = (baseRotation * Math.PI) / 180;
    wrapper.alpha = runtime.baseOpacity;
    blurFor(runtime, 0);
    invertFor(runtime, 0);
    updateCropMask(runtime, 0);
  }
}

export { BOARD_SCALE };
