/**
 * `editorial-typography` system (plan §4.3.1): display text, counters,
 * time/bar text, outlined/fill text, masks and line-by-line reveal.
 *
 * The renderer is prop-driven over `DirectionLayer.props`; every visual
 * constant is authored in reference pixels, matching the frozen frames.
 */
import { Container, Graphics, Text, TextStyle } from 'pixi.js';
import { registerSystem, type SystemRenderContext } from './registry.js';
import { BOARD_SCALE } from '../render/scale.js';

const INK0 = 0x171719;
const PAPER1 = 0xfbfaf7;
const ACCENT = 0x7567e8;
const STROKE1 = 1 / 0.62; // 1 screen px at first-run zoom

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
  return new Text({ text, style, resolution: Math.max(2, Math.min(4, (window.devicePixelRatio || 1) * 2)) });
}

function renderEditorialTypography(ctx: SystemRenderContext): Container {
  const { props, bodyW, bodyH, dark } = ctx;
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

registerSystem({
  kind: 'editorial-typography',
  label: 'Editorial typography',
  summary: 'Display type, mono readouts, rules, registration marks and print cards.',
  defaults: { displaySize: 21, rotation: 0 },
  fields: [
    { key: 'display', type: 'string', label: 'Display text' },
    { key: 'displaySize', type: 'number', label: 'Display size', min: 8, max: 96 },
    { key: 'mono', type: 'string', label: 'Mono readout' },
    { key: 'timecode', type: 'string', label: 'Timecode' },
    { key: 'corner', type: 'string', label: 'Corner' },
    { key: 'color', type: 'color', label: 'Color' },
    { key: 'rotation', type: 'number', label: 'Rotation', min: -90, max: 90 },
    { key: 'regmark', type: 'boolean', label: 'Registration mark' },
    { key: 'rule', type: 'object', label: 'Rule' },
    { key: 'card', type: 'object', label: 'Print card' },
    { key: 'cardType', type: 'object', label: 'Type card' },
    { key: 'tape', type: 'object', label: 'Tape' },
    { key: 'tags', type: 'array', label: 'Tags' },
  ],
  inspector: [
    { section: 'content', fields: ['display', 'displaySize', 'mono', 'timecode', 'tags'] },
    { section: 'layout', fields: ['corner', 'rotation', 'rule', 'card', 'cardType', 'tape'] },
    { section: 'treatment', fields: ['color', 'regmark'] },
  ],
  validate(props) {
    if (props === null || typeof props !== 'object' || Array.isArray(props)) {
      return ['system/editorial-typography/props: props must be an object'];
    }
    const record = props as Record<string, unknown>;
    const errors: string[] = [];
    for (const key of ['display', 'mono', 'timecode', 'color'] as const) {
      if (record[key] !== undefined && typeof record[key] !== 'string') {
        errors.push(`system/editorial-typography/${key}: must be a string`);
      }
    }
    if (record.displaySize !== undefined && (typeof record.displaySize !== 'number' || !Number.isFinite(record.displaySize))) {
      errors.push('system/editorial-typography/displaySize: must be a finite number');
    }
    if (record.rotation !== undefined && (typeof record.rotation !== 'number' || !Number.isFinite(record.rotation))) {
      errors.push('system/editorial-typography/rotation: must be a finite number');
    }
    return errors;
  },
  render: renderEditorialTypography,
});

export { renderEditorialTypography };
