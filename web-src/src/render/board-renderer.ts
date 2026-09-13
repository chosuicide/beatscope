/**
 * Board renderer: draws one DirectionScene as a Pixi "desk board" that
 * reproduces the frozen frame-A board chrome and artwork.
 *
 * Coordinate model: all art/chrome values are authored in reference pixels
 * (the values from docs/design/beathi-canvas/frame-a.html); the whole board
 * container is scaled by BOARD_SCALE so that at the first-run camera zoom
 * (0.62) every reference pixel maps to exactly one screen pixel.
 *
 * The three layer systems (graphic-field, media-slice, editorial-typography)
 * are prop-driven renderers over DirectionLayer.props — the same contract the
 * Python renderer consumes.
 */
import {
  type TextStyleFontWeight,
  Container,
  Graphics,
  Sprite,
  Text,
  TextStyle,
  TilingSprite,
  Texture,
  FillGradient,
} from 'pixi.js';
import type {
  DirectionScene,
  BoardBox,
} from '../direction/types';
import { BOARD_HEAD_REF, BOARD_FOOT_REF, FIRST_RUN_ZOOM } from '../demo/document';
import type { DemoTextures, FilterSpec } from './textures';
import { makeColorFilter } from './textures';
import type { LayerOutput } from '../motion/evaluate';

/** World units per reference pixel. */
export const BOARD_SCALE = 1 / FIRST_RUN_ZOOM;

const INK0 = 0x171719;
const PAPER1 = 0xfbfaf7;
const ACCENT = 0x7567e8;
const STROKE1 = 1 / FIRST_RUN_ZOOM; // 1 screen px at first-run zoom

function lineStrong(alpha = 0.14) {
  return { width: STROKE1, color: 0x22281f, alpha };
}

/* Torn-edge clip polygons, verbatim from beathi.css (percent vertices). */
const TORN: Record<string, Array<[number, number]>> = {
  right: [
    [0, 0], [100, 0], [97.5, 4], [100, 11], [96.5, 19], [99.5, 27], [96, 36],
    [100, 45], [96.5, 54], [100, 62], [96, 71], [99.5, 79], [96.5, 87],
    [100, 94], [97.5, 100], [0, 100],
  ],
  left: [
    [2.5, 0], [100, 0], [100, 100], [1, 100], [2.5, 93], [0, 85], [3, 77],
    [0.5, 68], [3, 59], [0, 50], [2.5, 41], [0, 32], [3, 23], [0.5, 14],
    [2.5, 6],
  ],
};

const TRANSITION_LABEL: Record<string, string> = {
  dissolve: 'dissolve',
  cut: 'cut',
  'directional-wipe': 'wipe',
  'hold-through': 'hold',
};

function dispStyle(size: number, color: number | string, letterSpacing?: number): TextStyle {
  return new TextStyle({
    fontFamily: 'Geist',
    fontSize: size,
    fontWeight: '900',
    letterSpacing: letterSpacing !== undefined ? letterSpacing * size : -0.035 * size,
    lineHeight: size * 0.95,
    fill: color,
  });
}

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

/** Cover-crop a texture into (w, h) with a normalized focus point. */
function coverSprite(tex: Texture, w: number, h: number, focus: [number, number]): Sprite {
  const s = new Sprite(tex);
  const scale = Math.max(w / tex.width, h / tex.height);
  s.scale.set(scale);
  s.x = (w - tex.width * scale) * focus[0];
  s.y = (h - tex.height * scale) * focus[1];
  return s;
}

function tornMask(kind: string, w: number, h: number): Graphics {
  const g = new Graphics();
  const pts = TORN[kind] ?? TORN.left;
  pts.forEach(([px, py], i) => {
    const x = (px / 100) * w;
    const y = (py / 100) * h;
    if (i === 0) g.moveTo(x, y);
    else g.lineTo(x, y);
  });
  g.closePath();
  g.fill({ color: 0xffffff });
  return g;
}

/* ------------------------------------------------------------------ */
/* graphic-field system                                                */
/* ------------------------------------------------------------------ */

function renderGraphicField(
  props: Record<string, unknown>,
  tex: DemoTextures,
  bodyW: number,
  bodyH: number,
  dark: boolean,
): Container {
  const c = new Container();

  const fillG = () => new Graphics().rect(0, 0, bodyW, bodyH).fill(props.fill as string);
  if (typeof props.tile === 'string' && tex) {
    const texture = (tex as unknown as Record<string, Texture | null>)[
      props.tile === 'demo-media/halftone.png' ? 'halftone' : 'paperFiber'
    ];
    if (texture) {
      // CSS contract: a fill without fillOver paints UNDER a multiply tile
      // (scene 01/05/07 paper); fillOver paints OVER it (scene 02/08 backing).
      if (typeof props.fill === 'string' && props.fillOver !== true) c.addChild(fillG());
      const ts = new TilingSprite({ texture, width: bodyW, height: bodyH });
      const tilePx = typeof props.tilePx === 'number' ? props.tilePx : 230;
      ts.tileScale.set(tilePx / texture.width);
      if (props.blend === 'multiply') ts.blendMode = 'multiply';
      if (typeof props.alpha === 'number') ts.alpha = props.alpha;
      c.addChild(ts);
      if (typeof props.fill === 'string' && props.fillOver === true) c.addChild(fillG());
    }
  } else if (typeof props.fill === 'string') {
    c.addChild(fillG());
  }
  if (typeof props.scanlines === 'number') {
    const g = new Graphics();
    const step = props.scanlines;
    const line = dark ? { color: 0xf0eee6, alpha: 0.05 } : { color: 0x22281f, alpha: 0.05 };
    for (let y = 0; y < bodyH; y += step) g.rect(0, y, bodyW, 1).fill(line);
    for (let x = 0; x < bodyW; x += step) g.rect(x, 0, 1, bodyH).fill(line);
    c.addChild(g);
  }
  if (typeof props.letterbox === 'number') {
    const g = new Graphics()
      .rect(0, 0, bodyW, props.letterbox)
      .fill(0x0b0b0d)
      .rect(0, bodyH - props.letterbox, bodyW, props.letterbox)
      .fill(0x0b0b0d);
    c.addChild(g);
  }
  if (Array.isArray(props.polyline)) {
    const pts = props.polyline as number[];
    const y0 = typeof props.y === 'number' ? props.y : 0;
    const g = new Graphics();
    for (let i = 0; i + 1 < pts.length; i += 2) {
      const x = pts[i];
      const y = y0 + pts[i + 1];
      if (i === 0) g.moveTo(x, y);
      else g.lineTo(x, y);
    }
    g.stroke({
      width: (typeof props.width === 'number' ? props.width : 1.5) * BOARD_SCALE,
      color: typeof props.stroke === 'string' ? props.stroke : 'rgba(196,232,203,.85)',
      join: 'round',
      cap: 'round',
    });
    c.addChild(g);
  }
  if (typeof props.scan === 'number') {
    const barW = 26;
    const g = new Graphics();
    try {
      const grad = new FillGradient({
        type: 'linear',
        start: { x: 0, y: 0 },
        end: { x: barW, y: 0 },
        colorStops: [
          { offset: 0, color: 'rgba(240,238,230,0)' },
          { offset: 1, color: 'rgba(240,238,230,0.13)' },
        ],
      });
      g.rect(props.scan, 0, barW, bodyH).fill(grad);
    } catch {
      g.rect(props.scan, 0, barW, bodyH).fill({ color: 0xf0eee6, alpha: 0.09 });
    }
    g.rect(props.scan + barW, 0, STROKE1, bodyH).fill({ color: 0xf0eee6, alpha: 0.5 });
    c.addChild(g);
  }
  if (Array.isArray(props.cards)) {
    for (const card of props.cards as Array<Record<string, number>>) {
      const holder = new Container();
      const shadow1 = new Graphics()
        .roundRect(0, 1, card.w, card.h, 2)
        .fill({ color: 0x231e2d, alpha: 0.14 });
      const shadow2 = new Graphics()
        .roundRect(0, 4, card.w + 4, card.h + 6, 3)
        .fill({ color: 0x231e2d, alpha: 0.1 });
      const card2 = new Graphics().roundRect(0, 0, card.w, card.h, 2).fill(card.fill);
      shadow1.x = card.x;
      shadow1.y = card.y;
      shadow2.x = card.x - 2;
      shadow2.y = card.y - 2;
      card2.x = card.x;
      card2.y = card.y;
      holder.addChild(shadow2, shadow1, card2);
      holder.pivot.set(card.w / 2, card.h / 2);
      holder.position.set(card.x + card.w / 2, card.y + card.h / 2);
      holder.rotation = ((card.rot ?? 0) * Math.PI) / 180;
      c.addChild(holder);
    }
  }
  if (typeof props.tag === 'string') {
    const t = makeText(props.tag, monoStyle(10, 'rgba(240,238,230,.62)'));
    t.x = 8;
    t.y = bodyH - 6 - t.height;
    c.addChild(t);
  }
  return c;
}

/* ------------------------------------------------------------------ */
/* media-slice system                                                  */
/* ------------------------------------------------------------------ */

function renderMediaSlice(
  props: Record<string, unknown>,
  tex: DemoTextures,
  bodyW: number,
  bodyH: number,
): Container {
  const c = new Container();
  const texture =
    props.src === 'demo-media/fog-ridge.png'
      ? tex.fogRidge
      : props.src === 'demo-media/fog-bright.png'
        ? tex.fogBright
        : null;
  if (!texture) return c;

  const filter = makeColorFilter((props.filter ?? {}) as FilterSpec);

  if (props.frame === 'print') {
    const rect = props.rect as { x: number; y: number; w: number; photoH: number; padBottom?: number };
    const padBottom = rect.padBottom ?? 20;
    const cardH = 7 + rect.photoH + padBottom;
    const holder = new Container();
    const s1 = new Graphics()
      .roundRect(0, 1, rect.w, cardH, 1.5)
      .fill({ color: 0x231e2d, alpha: 0.16 });
    const s2 = new Graphics()
      .roundRect(0, 6, rect.w + 6, cardH + 8, 3)
      .fill({ color: 0x231e2d, alpha: 0.12 });
    const card = new Graphics().roundRect(0, 0, rect.w, cardH, 1.5).fill(0xfdfcf8);
    const photo = coverSprite(texture, rect.w - 14, rect.photoH, (props.focus as [number, number]) ?? [0.5, 0.5]);
    photo.x = 7;
    photo.y = 7;
    if (filter) photo.filters = [filter];
    const photoClip = new Graphics().rect(7, 7, rect.w - 14, rect.photoH).fill(0xffffff);
    holder.addChild(s2, s1, card, photoClip, photo);
    photo.mask = photoClip;
    holder.x = rect.x;
    holder.y = rect.y;
    c.addChild(holder);
    return c;
  }

  let rx: number;
  let ry: number;
  let rw: number;
  let rh: number;
  if (props.full === true) {
    rx = 0;
    ry = 0;
    rw = bodyW;
    rh = bodyH;
  } else {
    const rect = props.rect as { x: number; y: number; w: number; h: number };
    rx = rect.x * bodyW;
    ry = rect.y * bodyH;
    rw = rect.w * bodyW;
    rh = rect.h * bodyH;
  }

  const photo = coverSprite(texture, rw, rh, (props.focus as [number, number]) ?? [0.5, 0.5]);
  photo.x = rx;
  photo.y = ry;
  if (filter) photo.filters = [filter];
  c.addChild(photo);

  if (typeof props.torn === 'string') {
    const mask = tornMask(props.torn, rw, rh);
    mask.x = rx;
    mask.y = ry;
    c.addChild(mask);
    photo.mask = mask;
  } else {
    const clip = new Graphics().rect(rx, ry, rw, rh).fill(0xffffff);
    c.addChild(clip);
    photo.mask = clip;
  }
  return c;
}

/* ------------------------------------------------------------------ */
/* editorial-typography system                                         */
/* ------------------------------------------------------------------ */

function renderEditorialTypography(
  props: Record<string, unknown>,
  bodyW: number,
  bodyH: number,
  dark: boolean,
): Container {
  const c = new Container();

  if (Array.isArray(props.tags)) {
    for (const [text, x, y] of props.tags as Array<[string, number, number]>) {
      const t = makeText(text, monoStyle(10, 'rgba(240,238,230,.75)'));
      t.x = x;
      t.y = y;
      c.addChild(t);
    }
  }

  if (typeof props.display === 'string' && !props.card && !props.cardType) {
    const size = typeof props.displaySize === 'number' ? props.displaySize : 21;
    const color = (props.color as string) ?? (dark ? '#f0eee6' : '#171719');
    const t = makeText(props.display, dispStyle(size, color));
    const rot = typeof props.rotation === 'number' ? props.rotation : 0;
    if (Array.isArray(props.pos)) {
      const [px, py] = props.pos as [number, number];
      t.x = px < 0 ? bodyW + px - t.width : px;
      t.y = typeof props.from === 'string' && props.from === 'bottom'
        ? bodyH + py - t.height
        : py;
    }
    if (rot !== 0) {
      t.rotation = (rot * Math.PI) / 180;
      t.pivot.set(t.width / 2, t.height / 2);
      t.x += t.width / 2;
      t.y += t.height / 2;
    }
    c.addChild(t);
  }

  if (props.rule && typeof props.rule === 'object') {
    const r = props.rule as { x: number; y: number; w: number; h: number; color?: string };
    const x = r.x < 0 ? bodyW + r.x - r.w : r.x;
    const g = new Graphics()
      .rect(x, r.y, r.w, r.h)
      .fill((r.color as string) ?? (dark ? '#f0eee6' : '#171719'));
    c.addChild(g);
  }

  if (typeof props.mono === 'string' && props.corner) {
    const color = (props.color as string) ?? (dark ? 'rgba(240,238,230,.62)' : '#77737d');
    const t = makeText(props.mono, monoStyle(10, color));
    if (props.corner === 'bottom-left') {
      t.x = 8;
      t.y = bodyH - 6 - t.height;
    } else if (props.corner === 'bottom-right') {
      t.x = bodyW - 8 - t.width;
      t.y = bodyH - 6 - t.height;
    } else if (props.corner === 'top-left') {
      t.x = 8;
      t.y = 8;
    }
    c.addChild(t);
  }

  if (typeof props.timecode === 'string') {
    const t = makeText(props.timecode, monoStyle(10, '#55534b'));
    t.x = bodyW - 10 - t.width;
    t.y = bodyH - 6 - t.height;
    c.addChild(t);
  }

  if (props.regmark === true) {
    const size = typeof props.size === 'number' ? props.size : 13;
    const inset = size === 11 ? 8 : 9;
    const topInset = size === 11 ? 8 : 10;
    const r = size * 0.354;
    const cx = props.corner === 'top-left' ? inset + r : bodyW - inset - r;
    const cy = topInset + r;
    const sw = (size === 11 ? 1.2 : 1.1) * BOARD_SCALE;
    const g = new Graphics()
      .circle(cx, cy, r)
      .stroke({ width: sw, color: ACCENT })
      .moveTo(cx, cy - size / 2)
      .lineTo(cx, cy + size / 2)
      .moveTo(cx - size / 2, cy)
      .lineTo(cx + size / 2, cy)
      .stroke({ width: sw, color: ACCENT });
    c.addChild(g);
  }

  if (props.tape && typeof props.tape === 'object') {
    const tp = props.tape as { x: number; y: number; w?: number; rot: number };
    const tw = tp.w ?? 52;
    const g = new Graphics()
      .rect(0, 0, tw, 15)
      .fill({ color: 0xe2ddce, alpha: 0.78 })
      .rect(0, 0, STROKE1, 15)
      .fill({ color: 0x22281f, alpha: 0.06 })
      .rect(tw - STROKE1, 0, STROKE1, 15)
      .fill({ color: 0x22281f, alpha: 0.06 });
    const sh = new Graphics().roundRect(0, 1, tw, 15, 1).fill({ color: 0x231e2d, alpha: 0.14 });
    const holder = new Container();
    holder.addChild(sh, g);
    holder.pivot.set(tw / 2, 7.5);
    holder.position.set(tp.x + tw / 2, tp.y + 7.5);
    holder.rotation = (tp.rot * Math.PI) / 180;
    c.addChild(holder);
  }

  if (props.card && typeof props.card === 'object') {
    const card = props.card as { x: number; y: number; pad: [number, number, number] };
    const size = typeof props.displaySize === 'number' ? props.displaySize : 19;
    const display = makeText((props.display as string) ?? '', dispStyle(size, '#171719'));
    const mono = makeText((props.mono as string) ?? '', monoStyle(10, '#6a675e'));
    const cw = display.width + card.pad[1] * 2;
    const ch = card.pad[0] + display.height + 2 + mono.height + card.pad[2];
    const sh = new Graphics()
      .roundRect(0, 2, cw, ch, 1.5)
      .fill({ color: 0x231e2d, alpha: 0.15 });
    const cardG = new Graphics()
      .roundRect(0, 0, cw, ch, 1.5)
      .fill(PAPER1)
      .stroke({ width: STROKE1, color: 0x22281f, alpha: 0.13 });
    cardG.x = card.x;
    cardG.y = card.y;
    sh.x = card.x;
    sh.y = card.y;
    display.x = card.x + card.pad[1];
    display.y = card.y + card.pad[0];
    mono.x = card.x + card.pad[1];
    mono.y = display.y + display.height + 2;
    c.addChild(sh, cardG, display, mono);
  }

  if (props.cardType && typeof props.cardType === 'object') {
    const ct = props.cardType as {
      x: number;
      y: number;
      display: string;
      displaySize: number;
      mono: string[];
      ruleW: number;
    };
    const display = makeText(ct.display, dispStyle(ct.displaySize, '#171719'));
    display.x = ct.x;
    display.y = ct.y;
    c.addChild(display);
    const ruleY = ct.y + display.height + 4;
    c.addChild(new Graphics().rect(ct.x, ruleY, ct.ruleW, 2).fill(INK0));
    let my = ruleY + 2 + 6;
    for (const line of ct.mono) {
      const t = makeText(line, monoStyle(10, '#6a675e'));
      t.x = ct.x;
      t.y = my;
      c.addChild(t);
      my += t.height + 1;
    }
  }

  return c;
}

/* ------------------------------------------------------------------ */
/* board assembly                                                      */
/* ------------------------------------------------------------------ */

export interface BoardVisual {
  sceneId: string;
  container: Container;
  layerWrappers: Map<string, Container>;
  layerCenters: Map<string, { x: number; y: number }>;
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
  const baseOpacity = new Map<string, number>();
  const layerRects = new Map<string, { x: number; y: number; w: number; h: number }>();

  for (const layerObj of scene.layers) {
    const wrapper = new Container();
    const inner = new Container();
    let content: Container;
    const props = layerObj.props as Record<string, unknown>;
    if (layerObj.kind === 'graphic-field') {
      content = renderGraphicField(props, tex, boardW, bodyH, dark);
    } else if (layerObj.kind === 'media-slice') {
      content = renderMediaSlice(props, tex, boardW, bodyH);
      // record the printed media region for the selection overlay (frame C)
      if (props.frame === 'print') {
        const rect = props.rect as { x: number; y: number; w: number; photoH: number } | undefined;
        if (rect) {
          layerRects.set(layerObj.id, {
            x: rect.x + 7,
            y: BOARD_HEAD_REF + rect.y + 7,
            w: rect.w - 14,
            h: rect.photoH,
          });
        }
      } else if (props.full === true) {
        layerRects.set(layerObj.id, { x: 0, y: BOARD_HEAD_REF, w: boardW, h: bodyH });
      } else {
        const rect = props.rect as { x: number; y: number; w: number; h: number } | undefined;
        if (rect) {
          layerRects.set(layerObj.id, {
            x: rect.x * boardW,
            y: BOARD_HEAD_REF + rect.y * bodyH,
            w: rect.w * boardW,
            h: rect.h * bodyH,
          });
        }
      }
    } else {
      content = renderEditorialTypography(props, boardW, bodyH, dark);
    }
    content.position.set(0, BOARD_HEAD_REF);
    // mask coordinates are art-relative; wrap content so masks stay aligned
    inner.position.set(0, -BOARD_HEAD_REF);
    inner.addChild(content);
    wrapper.addChild(inner);
    wrapper.position.set(0, BOARD_HEAD_REF);

    const cx = boardW / 2;
    const cy = bodyH / 2;
    wrapper.pivot.set(cx, cy);
    wrapper.x += cx;
    wrapper.y += cy;
    art.addChild(wrapper);

    if (!layerObj.visible || layerObj.opacity === 0) wrapper.visible = false;
    wrapper.alpha = layerObj.opacity;
    layerWrappers.set(layerObj.id, wrapper);
    layerCenters.set(layerObj.id, { x: cx, y: cy + BOARD_HEAD_REF });
    baseOpacity.set(layerObj.id, layerObj.opacity);
  }

  return {
    sceneId: scene.id,
    container,
    layerWrappers,
    layerCenters,
    layerRects,
    head,
    foot,
    artContainer: art,
    liveTag,
    shadow,
    box,
    baseOpacity,
  };
}

/** Apply evaluated response outputs to a live board. */
export function applyOutputs(visual: BoardVisual, outputs: Map<string, LayerOutput>): void {
  for (const [layerId, out] of outputs) {
    const wrapper = visual.layerWrappers.get(layerId);
    if (!wrapper) continue;
    const center = visual.layerCenters.get(layerId)!;
    wrapper.scale.set(out.scale);
    wrapper.x = center.x + out.translate.x;
    wrapper.y = center.y + out.translate.y;
    wrapper.alpha = (visual.baseOpacity.get(layerId) ?? 1) * out.opacity;
  }
}

/** Reset a live board to its authored (time-invariant) pose. */
export function resetOutputs(visual: BoardVisual): void {
  for (const [layerId, wrapper] of visual.layerWrappers) {
    const center = visual.layerCenters.get(layerId)!;
    wrapper.scale.set(1);
    wrapper.x = center.x;
    wrapper.y = center.y;
    wrapper.alpha = visual.baseOpacity.get(layerId) ?? 1;
  }
}
