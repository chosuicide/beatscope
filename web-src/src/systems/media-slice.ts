/**
 * `media-slice` system (plan §4.3.3): image or muted-video texture, crop,
 * split strips, offset repetition, mask and blend.
 *
 * Source resolution goes through the AssetResolver: bundled demo media
 * (`demo-media/...`) and project assets (`asset:<id>`) share one path.
 * A reference that no longer resolves renders the missing-asset placeholder
 * instead of vanishing — the layer and its authored props are preserved.
 */
import { Container, Graphics, Sprite } from 'pixi.js';
import type { Texture } from 'pixi.js';
import { registerSystem, missingAssetPlaceholder, type SystemRenderContext } from './registry.js';
import { makeColorFilter, type FilterSpec } from '../render/textures.js';

/** Cover-crop a texture into (w, h) with a normalized focus point. */
function coverSprite(tex: Texture, w: number, h: number, focus: [number, number]): Sprite {
  const s = new Sprite(tex);
  const scale = Math.max(w / tex.width, h / tex.height);
  s.scale.set(scale);
  s.x = (w - tex.width * scale) * focus[0];
  s.y = (h - tex.height * scale) * focus[1];
  return s;
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

function srcOf(props: Record<string, unknown>): string {
  return typeof props.src === 'string' ? props.src : '';
}

function renderMediaSlice(ctx: SystemRenderContext): Container {
  const { props, assets, textures, bodyW, bodyH } = ctx;
  const c = new Container();
  const src = srcOf(props);

  if (!src) {
    return missingAssetPlaceholder(bodyW, bodyH, 'no source');
  }
  // Bundled demo media resolves from the shared texture set; project assets
  // go through the resolver. Both paths share the same layer contract.
  const demoTexture =
    src === 'demo-media/fog-ridge.png'
      ? textures.fogRidge
      : src === 'demo-media/fog-bright.png'
        ? textures.fogBright
        : null;
  const texture = demoTexture ?? assets.textureFor(src);
  if (!texture) {
    return assets.missingAsset(src) || src.startsWith('asset:') || src.startsWith('missing-asset:')
      ? missingAssetPlaceholder(bodyW, bodyH, src)
      : new Container(); // demo media still loading: keep the board quiet
  }

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

  const strips = typeof props.strips === 'number' ? Math.max(1, Math.min(12, Math.round(props.strips))) : 1;
  if (strips > 1) {
    // Split strips with deterministic offset repetition (§4.3.3). Each strip
    // shows the same source window shifted by a fixed fraction of its width.
    const gap = typeof props.stripGap === 'number' ? props.stripGap : 2;
    const step = rw / strips;
    const offset = typeof props.stripOffset === 'number' ? props.stripOffset : 0.12;
    for (let i = 0; i < strips; i++) {
      const sw = step - gap;
      const photo = coverSprite(texture, sw, rh, (props.focus as [number, number]) ?? [0.5, 0.5]);
      const shift = ((i % 2 === 0 ? 1 : -1) * offset * sw) / 2;
      photo.x = rx + i * step + shift;
      photo.y = ry;
      if (filter) photo.filters = [filter];
      const clip = new Graphics().rect(rx + i * step, ry, sw, rh).fill(0xffffff);
      c.addChild(clip, photo);
      photo.mask = clip;
    }
    return c;
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

  if (props.offsetRepeat === true) {
    // A second, smaller pass of the same frame: offset repetition that reads
    // as a cut study without introducing another asset.
    const ow = rw * 0.32;
    const oh = rh * 0.32;
    const dup = coverSprite(texture, ow, oh, (props.focus as [number, number]) ?? [0.5, 0.5]);
    dup.x = rx + rw - ow - 8;
    dup.y = ry + rh - oh - 8;
    if (filter) dup.filters = [filter];
    const dupClip = new Graphics().rect(rx + rw - ow - 8, ry + rh - oh - 8, ow, oh).fill(0xffffff);
    const frame = new Graphics()
      .rect(rx + rw - ow - 8, ry + rh - oh - 8, ow, oh)
      .stroke({ width: 1, color: 0xfdfcf8, alpha: 0.9 });
    c.addChild(dupClip, dup, frame);
    dup.mask = dupClip;
  }

  return c;
}

registerSystem({
  kind: 'media-slice',
  label: 'Media slice',
  summary: 'Project image or muted video, cropped, torn, stripped and repeated.',
  defaults: { focus: [0.5, 0.5], strips: 1, stripGap: 2, stripOffset: 0.12, source_offset_seconds: 0, loop: true },
  fields: [
    { key: 'src', type: 'string', label: 'Source', required: true },
    { key: 'frame', type: 'string', label: 'Frame' },
    { key: 'full', type: 'boolean', label: 'Full bleed' },
    { key: 'rect', type: 'object', label: 'Rect' },
    { key: 'focus', type: 'number-pair', label: 'Focus' },
    { key: 'torn', type: 'string', label: 'Torn edge' },
    { key: 'strips', type: 'number', label: 'Strips', min: 1, max: 12 },
    { key: 'stripGap', type: 'number', label: 'Strip gap', min: 0, max: 40 },
    { key: 'stripOffset', type: 'number', label: 'Strip offset', min: -1, max: 1 },
    { key: 'offsetRepeat', type: 'boolean', label: 'Offset repeat' },
    { key: 'source_offset_seconds', type: 'number', label: 'Source offset', min: 0 },
    { key: 'loop_duration_seconds', type: 'number', label: 'Loop duration', min: 0 },
    { key: 'loop', type: 'boolean', label: 'Loop' },
    { key: 'filter', type: 'object', label: 'Filter' },
  ],
  inspector: [
    { section: 'content', fields: ['src', 'frame', 'full', 'rect', 'focus', 'source_offset_seconds', 'loop_duration_seconds', 'loop'] },
    { section: 'layout', fields: ['torn', 'strips', 'stripGap', 'stripOffset', 'offsetRepeat'] },
    { section: 'treatment', fields: ['filter'] },
  ],
  validate(props) {
    if (props === null || typeof props !== 'object' || Array.isArray(props)) {
      return ['system/media-slice/props: props must be an object'];
    }
    const record = props as Record<string, unknown>;
    const errors: string[] = [];
    if (typeof record.src !== 'string' || record.src.length === 0) {
      errors.push('system/media-slice/src: a source reference is required');
    }
    if (record.focus !== undefined) {
      const focus = record.focus;
      if (
        !Array.isArray(focus) ||
        focus.length !== 2 ||
        !focus.every((v) => typeof v === 'number' && Number.isFinite(v))
      ) {
        errors.push('system/media-slice/focus: must be a pair of finite numbers');
      }
    }
    if (record.strips !== undefined) {
      if (typeof record.strips !== 'number' || !Number.isFinite(record.strips) || record.strips < 1) {
        errors.push('system/media-slice/strips: must be a number >= 1');
      }
    }
    if (
      record.source_offset_seconds !== undefined &&
      (typeof record.source_offset_seconds !== 'number' ||
        !Number.isFinite(record.source_offset_seconds) ||
        record.source_offset_seconds < 0)
    ) {
      errors.push('system/media-slice/source-offset: must be a finite number >= 0');
    }
    if (
      record.loop_duration_seconds !== undefined &&
      (typeof record.loop_duration_seconds !== 'number' ||
        !Number.isFinite(record.loop_duration_seconds) ||
        record.loop_duration_seconds <= 0)
    ) {
      errors.push('system/media-slice/loop-duration: must be a finite number > 0');
    }
    if (record.loop !== undefined && typeof record.loop !== 'boolean') {
      errors.push('system/media-slice/loop: must be a boolean');
    }
    if (record.filter !== undefined && (typeof record.filter !== 'object' || record.filter === null)) {
      errors.push('system/media-slice/filter: must be an object');
    }
    return errors;
  },
  render: renderMediaSlice,
});

export { renderMediaSlice };
