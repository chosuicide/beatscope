/**
 * Layer-system registry (plan §4.3). Three art-directed systems are shipped:
 * `editorial-typography`, `graphic-field` and `media-slice`. Each definition
 * exposes schema, defaults, renderer factory, inspector definition and a
 * serialization validator; the board renderer dispatches through this
 * registry instead of switch statements spread through the UI.
 *
 * Unknown kinds stay preserved in the document and render as unsupported
 * placeholders — a newer document is never destructively rewritten (§4.3).
 */
import { Container, Graphics, Text } from 'pixi.js';
import type { Texture } from 'pixi.js';
import type { LayerSystemKind } from '../direction/types';
import type { DemoTextures } from '../render/textures';

/** Resolves layer `props.src` references to decoded project assets. */
export interface AssetResolver {
  /** Demo media path (`demo-media/...`) or `asset:<id>` -> texture. */
  textureFor(src: string): Texture | null;
  /** True when an `asset:<id>` reference no longer resolves. */
  missingAsset(src: string): boolean;
  /** Stable revision for poster invalidation after manifest/texture changes. */
  cacheKey?(): string;
  /** Duration and deterministic seek surface for muted video assets. */
  mediaDuration?(src: string): number | null;
  seekMedia?(src: string, time: number): void;
}

export const NO_ASSETS: AssetResolver = {
  textureFor: () => null,
  missingAsset: () => false,
};

export interface PropFieldSpec {
  key: string;
  type: 'string' | 'number' | 'boolean' | 'color' | 'number-pair' | 'array' | 'object';
  label: string;
  required?: boolean;
  min?: number;
  max?: number;
}

export interface SystemRenderContext {
  props: Record<string, unknown>;
  textures: DemoTextures;
  assets: AssetResolver;
  /** body size in reference pixels */
  bodyW: number;
  bodyH: number;
  /** true when the board family paints a dark art ground */
  dark: boolean;
}

export interface SystemDefinition {
  kind: LayerSystemKind;
  label: string;
  summary: string;
  defaults: Record<string, unknown>;
  fields: PropFieldSpec[];
  /** inspector grouping: section id -> prop keys, in display order */
  inspector: Array<{ section: string; fields: string[] }>;
  /** stable codes `system/<kind>/...`; empty means valid */
  validate(props: unknown): string[];
  render(ctx: SystemRenderContext): Container;
}

const registry = new Map<string, SystemDefinition>();

export function registerSystem(definition: SystemDefinition): void {
  registry.set(definition.kind, definition);
}

export function systemFor(kind: string): SystemDefinition | null {
  return registry.get(kind) ?? null;
}

export function registeredKinds(): string[] {
  return [...registry.keys()].sort();
}

/** Unknown kinds validate clean (preserved as authored, §4.3). */
export function validateLayerProps(kind: string, props: unknown): string[] {
  const definition = registry.get(kind);
  if (!definition) return [];
  return definition.validate(props);
}

/** Merge authored props over the system defaults (authored values win). */
export function withDefaults(kind: string, props: Record<string, unknown>): Record<string, unknown> {
  const definition = registry.get(kind);
  if (!definition) return { ...props };
  return { ...definition.defaults, ...props };
}

const MONO = '"Geist Mono", ui-monospace, monospace';

function notice(text: string, detail: string): Container {
  const c = new Container();
  const g = new Graphics().rect(0, 0, 100, 40).stroke({ width: 1, color: 0xb94a57, alpha: 0.8 });
  const t = new Text({
    text,
    style: { fontFamily: MONO, fontSize: 10, fill: '#b94a57' },
    resolution: 2,
  });
  t.x = 6;
  t.y = 5;
  const d = new Text({
    text: detail,
    style: { fontFamily: MONO, fontSize: 8, fill: '#8a7a7d' },
    resolution: 2,
  });
  d.x = 6;
  d.y = 20;
  c.addChild(g, t, d);
  return c;
}

/**
 * Renderer dispatch. Registered systems get their factory; anything else
 * renders an unsupported placeholder that names the kind and keeps the
 * authored props untouched in the document.
 */
export function renderLayerSystem(ctx: SystemRenderContext & { kind: string }): Container {
  const definition = registry.get(ctx.kind);
  if (!definition) {
    return notice(`unsupported layer kind`, ctx.kind);
  }
  try {
    return definition.render(ctx);
  } catch (error) {
    return notice('layer render failed', String(error).slice(0, 48));
  }
}

/** Missing-asset placeholder for media-slice layers (§6.2). */
export function missingAssetPlaceholder(bodyW: number, bodyH: number, src: string): Container {
  const c = new Container();
  const w = Math.min(bodyW, 260);
  const h = Math.min(bodyH, 120);
  const g = new Graphics()
    .rect(0, 0, w, h)
    .fill({ color: 0xf2f0e9, alpha: 0.9 })
    .stroke({ width: 1, color: 0xb94a57, alpha: 0.7 });
  // hatch
  for (let x = -h; x < w; x += 10) {
    g.moveTo(x, h).lineTo(x + h, 0);
  }
  g.stroke({ width: 1, color: 0xb94a57, alpha: 0.14 });
  const label = new Text({
    text: 'MISSING ASSET',
    style: { fontFamily: MONO, fontSize: 10, fill: '#b94a57', letterSpacing: 1 },
    resolution: 2,
  });
  label.x = 8;
  label.y = 8;
  const id = new Text({
    text: src.length > 34 ? `${src.slice(0, 31)}…` : src,
    style: { fontFamily: MONO, fontSize: 8, fill: '#8a7a7d' },
    resolution: 2,
  });
  id.x = 8;
  id.y = 24;
  c.addChild(g, label, id);
  return c;
}
