/**
 * `graphic-field` system (plan §4.3.2): grids, ruled lines, blocks, rings,
 * contours, noise fields and repeated geometric marks.
 */
import { Container, FillGradient, Graphics, Text, TilingSprite, TextStyle } from 'pixi.js';
import type { Texture } from 'pixi.js';
import { registerSystem, type SystemRenderContext } from './registry.js';
import { BOARD_SCALE } from '../render/scale.js';

const STROKE1 = 1 / 0.62;
const MONO = '"Geist Mono", ui-monospace, monospace';

function monoStyle(size: number, color: number | string, tracking = 0.02): TextStyle {
  return new TextStyle({
    fontFamily: MONO,
    fontSize: size,
    fontWeight: '500',
    letterSpacing: tracking * size,
    fill: color,
  });
}

function renderGraphicField(ctx: SystemRenderContext): Container {
  const { props, textures: tex, bodyW, bodyH, dark } = ctx;
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
  if (Array.isArray(props.rings)) {
    for (const ring of props.rings as Array<{ x: number; y: number; r: number; w?: number; color?: string }>) {
      c.addChild(
        new Graphics()
          .circle(ring.x, ring.y, ring.r)
          .stroke({ width: (ring.w ?? 1.5) * BOARD_SCALE, color: ring.color ?? 'rgba(196,232,203,.85)' }),
      );
    }
  }
  if (Array.isArray(props.blocks)) {
    for (const block of props.blocks as Array<{ x: number; y: number; w: number; h: number; fill?: string; alpha?: number }>) {
      c.addChild(
        new Graphics()
          .rect(block.x, block.y, block.w, block.h)
          .fill({ color: block.fill ?? '#c4e8cb', alpha: block.alpha ?? 1 }),
      );
    }
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
    const t = new Text({
      text: props.tag,
      style: monoStyle(10, 'rgba(240,238,230,.62)'),
      resolution: Math.max(2, Math.min(4, (window.devicePixelRatio || 1) * 2)),
    });
    t.x = 8;
    t.y = bodyH - 6 - t.height;
    c.addChild(t);
  }
  return c;
}

registerSystem({
  kind: 'graphic-field',
  label: 'Graphic field',
  summary: 'Tiled paper, grids, contours, rings, blocks and repeated marks.',
  defaults: { tilePx: 230, alpha: 1, width: 1.5 },
  fields: [
    { key: 'fill', type: 'color', label: 'Fill' },
    { key: 'tile', type: 'string', label: 'Tile source' },
    { key: 'tilePx', type: 'number', label: 'Tile size', min: 32, max: 512 },
    { key: 'fillOver', type: 'boolean', label: 'Fill over tile' },
    { key: 'blend', type: 'string', label: 'Tile blend' },
    { key: 'alpha', type: 'number', label: 'Tile alpha', min: 0, max: 1 },
    { key: 'scanlines', type: 'number', label: 'Scanline step', min: 2, max: 200 },
    { key: 'letterbox', type: 'number', label: 'Letterbox', min: 0, max: 200 },
    { key: 'polyline', type: 'array', label: 'Polyline' },
    { key: 'rings', type: 'array', label: 'Rings' },
    { key: 'blocks', type: 'array', label: 'Blocks' },
    { key: 'scan', type: 'number', label: 'Scan bar' },
    { key: 'cards', type: 'array', label: 'Cards' },
    { key: 'tag', type: 'string', label: 'Tag' },
  ],
  inspector: [
    { section: 'content', fields: ['fill', 'tile', 'tilePx', 'polyline', 'rings', 'blocks', 'cards'] },
    { section: 'layout', fields: ['scanlines', 'letterbox', 'scan', 'tag'] },
    { section: 'treatment', fields: ['fillOver', 'blend', 'alpha'] },
  ],
  validate(props) {
    if (props === null || typeof props !== 'object' || Array.isArray(props)) {
      return ['system/graphic-field/props: props must be an object'];
    }
    const record = props as Record<string, unknown>;
    const errors: string[] = [];
    if (record.fill !== undefined && typeof record.fill !== 'string') {
      errors.push('system/graphic-field/fill: must be a color string');
    }
    for (const key of ['tilePx', 'alpha', 'scanlines', 'letterbox', 'scan'] as const) {
      if (record[key] !== undefined && (typeof record[key] !== 'number' || !Number.isFinite(record[key]))) {
        errors.push(`system/graphic-field/${key}: must be a finite number`);
      }
    }
    if (record.polyline !== undefined && !Array.isArray(record.polyline)) {
      errors.push('system/graphic-field/polyline: must be an array of x,y pairs');
    }
    return errors;
  },
  render: renderGraphicField,
});

export { renderGraphicField };
