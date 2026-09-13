/**
 * The single Pixi host: one WebGL renderer owns the composition viewport
 * (plan §3.2). All canvas content (boards, connectors, selection ring) lives
 * in this renderer; editor chrome stays in the React DOM layer.
 *
 * Round 3 Commit 1 adds live-board arbitration and the poster cache:
 * exactly one board renders live; every inactive board shows a cached
 * RenderTexture poster generated at its representative time. Posters are
 * invalidated only for affected scenes and evicted LRU before the GPU budget.
 */
import {
  Application,
  Container,
  Graphics,
  Rectangle,
  Sprite,
  Text,
  Texture,
} from 'pixi.js';
import type {
  DirectionDocument,
  WorkspaceLayout,
  BoardBox,
  CameraState,
} from '../direction/types';
import type { DemoTextures } from './textures.js';
import type { DemoRhythm } from '../demo/rhythm';
import {
  BOARD_HEAD,
  BOARD_FOOT,
  FIRST_RUN_ZOOM,
} from '../demo/document.js';
import {
  buildBoard,
  applyOutputs,
  resetOutputs,
  BOARD_SCALE,
} from './board-renderer.js';
import type { BoardVisual } from './board-renderer.js';
import { PosterCache } from './poster-cache.js';
import { NO_ASSETS, type AssetResolver } from '../systems/index.js';
import { getDirectionState, sceneAtTime } from '../motion/evaluate.js';
import { videoSourceTime } from '../motion/evaluate.js';
import type { CompiledDirection, DirectionState } from '../motion/evaluate.js';
import { clampZoom } from '../camera/camera.js';

const STROKE_W = 1 / FIRST_RUN_ZOOM; // 1 screen px of chrome at first-run zoom

export type LodMode = 'silhouette' | 'poster' | 'full';

export function lodForZoom(zoom: number): LodMode {
  if (zoom < 0.28) return 'silhouette';
  if (zoom <= 0.55) return 'poster';
  return 'full';
}

export function boardFullHeight(box: BoardBox): number {
  return BOARD_HEAD + box.bodyH + BOARD_FOOT;
}

/** True if a world point hits the (possibly rotated) board rect. */
export function boardHit(box: BoardBox, wx: number, wy: number): boolean {
  const fullH = boardFullHeight(box);
  const cx = box.x + box.w / 2;
  const cy = box.y + fullH / 2;
  const dx = wx - cx;
  const dy = wy - cy;
  const r = (-box.rotation * Math.PI) / 180;
  const lx = dx * Math.cos(r) - dy * Math.sin(r);
  const ly = dx * Math.sin(r) + dy * Math.cos(r);
  return Math.abs(lx) <= box.w / 2 && Math.abs(ly) <= fullH / 2;
}

export interface PixiHostEvents {
  onContextLost: () => void;
}

export interface CompositionSnapshot {
  camera: CameraState;
  firstRunMode: boolean;
  selectedSceneId: string | null;
  liveSceneId: string | null;
  boards: Array<{ id: string; visible: boolean; x: number; y: number; w: number; h: number }>;
}

/** One ghosted candidate region of the pending direction proposal (frame D). */
export interface ProposalGhost {
  sceneId: string;
  rect: { x: number; y: number; w: number; h: number }; // fractions of the board body
  label: string;
}

export interface HostDocumentOptions {
  rhythm?: DemoRhythm | null;
  assets?: AssetResolver;
  /** compiled evaluator; posters render its representative-time state */
  compiled?: CompiledDirection | null;
  reducedMotion?: boolean;
}

const ACCENT_HEX = 0x7567e8;

/** world offset for a reference-px length */
const wLen = (px: number) => px / FIRST_RUN_ZOOM;

/** normalize a 2D vector */
function norm2(x: number, y: number): { x: number; y: number } {
  const len = Math.hypot(x, y) || 1;
  return { x: x / len, y: y / len };
}

export class PixiHost {
  app: Application | null = null;
  private world = new Container();
  private wires = new Container();
  private boardsLayer = new Container();
  private posterLayer = new Container(); // cached posters for inactive boards
  private ghostLayer = new Container(); // world space: pending proposal ghosts
  private ringLayer = new Container(); // screen space, drawn above world
  private overlayLayer = new Container(); // screen space: guides, pills, brackets, annotation
  private snapLayer = new Container(); // screen space: live snap guides while dragging

  private boardVisuals = new Map<string, BoardVisual>();
  private posterSprites = new Map<string, Sprite>();
  private posterCache: PosterCache<Texture>;
  private sceneOrder: string[] = [];
  private layoutBoxes = new Map<string, BoardBox>();
  private doc: DirectionDocument | null = null;
  private textures: DemoTextures | null = null;
  private assets: AssetResolver = NO_ASSETS;
  private compiled: CompiledDirection | null = null;
  private reducedMotion = false;
  private liveSceneId: string | null = null;
  private selectedSceneId: string | null = null;
  private selectedLayerId: string | null = null;
  private proposalItems: ProposalGhost[] | null = null;
  private firstRunMode = false;
  private focusIsolation = false;
  private hoverSceneId: string | null = null;
  private camera: CameraState = { x: 0, y: 0, zoom: FIRST_RUN_ZOOM };
  private zoomBand = { connectors: 'solid', lod: 'full' as LodMode, shadows: true };
  private destroyed = false;
  private events: PixiHostEvents;
  private contextLostHandler = (e: Event) => {
    e.preventDefault();
    this.events.onContextLost();
  };

  constructor(events: PixiHostEvents) {
    this.events = events;
    this.posterCache = new PosterCache<Texture>({
      create: (sceneId) => this.renderPoster(sceneId, 'representative'),
      destroy: (texture) => texture.destroy(true),
    });
  }

  async init(canvas: HTMLCanvasElement, width: number, height: number): Promise<void> {
    const app = new Application();
    await app.init({
      canvas,
      width,
      height,
      preference: 'webgl',
      antialias: true,
      backgroundAlpha: 0,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
      autoDensity: true,
    });
    if (this.destroyed) {
      app.destroy(false);
      return;
    }
    app.ticker.stop();
    this.app = app;
    canvas.addEventListener('webglcontextlost', this.contextLostHandler);
    this.world.addChild(this.wires, this.posterLayer, this.boardsLayer, this.ghostLayer);
    app.stage.addChild(this.world, this.overlayLayer, this.ringLayer, this.snapLayer);
    this.applyCamera(this.camera);
  }

  resize(width: number, height: number): void {
    this.app?.renderer.resize(width, height);
  }

  setDocument(
    doc: DirectionDocument,
    layout: WorkspaceLayout,
    textures: DemoTextures,
    options: HostDocumentOptions = {},
  ): void {
    this.doc = doc;
    this.textures = textures;
    if (options.assets) this.assets = options.assets;
    if (options.compiled !== undefined) this.compiled = options.compiled;
    if (options.reducedMotion !== undefined) this.reducedMotion = options.reducedMotion;
    this.layoutBoxes.clear();
    for (const [id, box] of Object.entries(layout.boards)) {
      this.layoutBoxes.set(id, { ...box });
    }
    this.syncBoards();
  }

  /** Per-scene signature: content + box. Unchanged scenes keep their visual. */
  private sceneSignature(sceneId: string): string {
    const scene = this.doc?.scenes.find((s) => s.id === sceneId);
    const box = this.layoutBoxes.get(sceneId);
    if (!scene || !box) return '';
    return JSON.stringify([scene, box, this.doc?.theme ?? {}, this.assets.cacheKey?.() ?? '']);
  }

  private signatures = new Map<string, string>();

  /**
   * Rebuild only boards whose content or box changed; posters invalidate for
   * exactly those scenes (§3.2 "invalidate only posters affected by the
   * edited scene, theme or asset").
   */
  private syncBoards(): void {
    if (!this.doc || !this.textures || !this.app) return;
    const scenes = [...this.doc.scenes].sort((a, b) => a.start_time - b.start_time);
    this.sceneOrder = scenes.map((s) => s.id);
    const nextSignatures = new Map<string, string>();
    const invalidated: string[] = [];

    for (const scene of scenes) {
      const box = this.layoutBoxes.get(scene.id);
      if (!box) continue;
      const signature = this.sceneSignature(scene.id);
      nextSignatures.set(scene.id, signature);
      const live = scene.id === this.liveSceneId;
      const previous = this.signatures.get(scene.id);
      const existing = this.boardVisuals.get(scene.id);
      if (existing && previous === signature && existing.liveTag.visible === live) continue;

      if (existing) {
        this.borderOverlays.get(scene.id)?.destroy();
        this.borderOverlays.delete(scene.id);
        existing.container.destroy({ children: true });
        this.boardVisuals.delete(scene.id);
      }
      const sprite = this.posterSprites.get(scene.id);
      if (sprite) {
        sprite.destroy();
        this.posterSprites.delete(scene.id);
      }
      const visual = buildBoard(scene, box, this.textures, live, this.assets);
      if (live) this.overlayBorder(visual, true);
      this.boardsLayer.addChild(visual.container);
      this.boardVisuals.set(scene.id, visual);
      invalidated.push(scene.id);
    }

    // drop visuals for scenes that no longer exist
    for (const [id, visual] of [...this.boardVisuals]) {
      if (nextSignatures.has(id)) continue;
      this.borderOverlays.get(id)?.destroy();
      this.borderOverlays.delete(id);
      visual.container.destroy({ children: true });
      this.boardVisuals.delete(id);
      const sprite = this.posterSprites.get(id);
      if (sprite) {
        sprite.destroy();
        this.posterSprites.delete(id);
      }
      this.posterCache.invalidate([id]);
    }

    this.signatures = nextSignatures;
    this.posterCache.invalidate(invalidated);
    this.updateBoardVisibility();
    this.drawWires();
    this.drawRing();
    this.drawGhost();
    this.applyLod(lodForZoom(this.camera.zoom));
  }

  /** Poster key: scene content identity + poster kind. */
  private posterKey(sceneId: string, kind: 'representative' | 'hover'): string {
    const scene = this.doc?.scenes.find((s) => s.id === sceneId);
    if (!scene) return 'missing';
    const at = kind === 'hover' ? 'hover' : 'rep';
    return `${at}:${scene.start_time}:${scene.end_time}:${scene.layers.length}:${scene.responses.length}`;
  }

  /** Render one board to a RenderTexture at a representative or hover time. */
  private renderPoster(sceneId: string, kind: 'representative' | 'hover'): { texture: Texture; width: number; height: number } | null {
    const app = this.app;
    const visual = this.boardVisuals.get(sceneId);
    const box = this.layoutBoxes.get(sceneId);
    const scene = this.doc?.scenes.find((s) => s.id === sceneId);
    if (!app || !visual || !box || !scene) return null;

    const boardW = box.w / BOARD_SCALE;
    const bodyH = box.bodyH / BOARD_SCALE;
    const fullH = BOARD_HEAD + bodyH + BOARD_FOOT;
    const savedPosition = { x: visual.container.x, y: visual.container.y };
    const savedRotation = visual.container.rotation;
    const savedScale = { x: visual.container.scale.x, y: visual.container.scale.y };
    try {
      // A representative poster is deterministic: the scene midpoint with
      // the authored responses evaluated at that exact time.
      const at = kind === 'hover' && this.hoverAt !== null
        ? this.hoverAt
        : scene.start_time + (scene.end_time - scene.start_time) * 0.5;
      if (this.compiled) {
        const state = getDirectionState(this.compiled, at, { reducedMotion: this.reducedMotion });
        applyOutputs(visual, state.layers);
      }
      visual.container.position.set(0, 0);
      visual.container.rotation = 0;
      visual.container.scale.set(BOARD_SCALE);
      const texture = app.renderer.generateTexture({
        target: visual.container,
        frame: new Rectangle(0, 0, boardW, fullH),
        resolution: 2,
        antialias: true,
      });
      return { texture, width: boardW * 2, height: fullH * 2 };
    } catch {
      return null;
    } finally {
      resetOutputs(visual);
      visual.container.position.set(savedPosition.x, savedPosition.y);
      visual.container.rotation = savedRotation;
      visual.container.scale.set(savedScale.x, savedScale.y);
    }
  }

  private hoverAt: number | null = null;

  /** Display or clear the poster sprite for one board. */
  private syncPoster(sceneId: string): void {
    const visual = this.boardVisuals.get(sceneId);
    const box = this.layoutBoxes.get(sceneId);
    if (!visual || !box) return;
    let sprite = this.posterSprites.get(sceneId);
    if (!sprite) {
      sprite = new Sprite(Texture.EMPTY);
      sprite.eventMode = 'none';
      this.posterLayer.addChild(sprite);
      this.posterSprites.set(sceneId, sprite);
    }
    const key = this.posterKey(sceneId, this.hoverSceneId === sceneId ? 'hover' : 'representative');
    const texture = this.posterCache.ensure(sceneId, key);
    if (texture) sprite.texture = texture;
    sprite.position.set(box.x, box.y);
    sprite.rotation = (box.rotation * Math.PI) / 180;
    sprite.scale.set(BOARD_SCALE);
  }

  setLiveScene(sceneId: string | null): void {
    if (sceneId === this.liveSceneId) return;
    const prev = this.liveSceneId;
    this.liveSceneId = sceneId;
    if (prev && this.boardVisuals.has(prev)) {
      const v = this.boardVisuals.get(prev)!;
      v.liveTag.visible = false;
      this.overlayBorder(v, false);
      resetOutputs(v);
    }
    if (sceneId && this.boardVisuals.has(sceneId)) {
      const v = this.boardVisuals.get(sceneId)!;
      v.liveTag.visible = true;
      this.overlayBorder(v, true);
    }
    this.updateBoardVisibility();
    this.applyLod(lodForZoom(this.camera.zoom));
  }

  /** One poster checkpoint on hover; never a continuous loop (§3.2). */
  setHoverScene(sceneId: string | null, time: number | null = null): void {
    if (sceneId === this.hoverSceneId) {
      if (sceneId && time !== null && this.hoverAt !== time) {
        this.hoverAt = time;
        this.posterCache.invalidate([sceneId]);
        this.syncPoster(sceneId);
        this.updateBoardVisibility();
      }
      return;
    }
    const previous = this.hoverSceneId;
    this.hoverSceneId = sceneId;
    this.hoverAt = time;
    if (previous) {
      this.posterCache.invalidate([previous]);
      this.syncPoster(previous);
    }
    if (sceneId) {
      this.posterCache.invalidate([sceneId]);
      this.syncPoster(sceneId);
    }
    this.updateBoardVisibility();
  }

  /** Invalidate posters for edited scenes only (§3.2). */
  invalidatePosters(sceneIds: Iterable<string>): void {
    const affected = [...sceneIds];
    this.posterCache.invalidate(affected);
    for (const sceneId of affected) this.syncPoster(sceneId);
  }

  posterStats(): { count: number; bytes: number; budgetBytes: number } {
    return this.posterCache.stats;
  }

  private borderOverlays = new Map<string, Graphics>();

  private overlayBorder(v: BoardVisual, live: boolean): void {
    const existing = this.borderOverlays.get(v.sceneId);
    if (existing) {
      existing.destroy();
      this.borderOverlays.delete(v.sceneId);
    }
    if (!live) return;
    const g = new Graphics();
    const box = v.box;
    const fullH = boardFullHeight(box);
    // container is scaled by BOARD_SCALE; draw in reference pixels
    g.rect(0, 0, box.w / BOARD_SCALE, fullH / BOARD_SCALE).stroke({
      width: STROKE_W,
      color: 0x22281f,
      alpha: 0.3,
    });
    v.container.addChild(g);
    this.borderOverlays.set(v.sceneId, g);
  }

  /** Push evaluated response outputs onto the live board. */
  updateLive(evaluation: DirectionState): void {
    const v = this.boardVisuals.get(evaluation.scene.id);
    if (!v || evaluation.scene.id !== this.liveSceneId) return;
    for (const layer of evaluation.scene.layers) {
      if (layer.kind !== 'media-slice') continue;
      const props = layer.props as Record<string, unknown>;
      const src = typeof props.src === 'string' ? props.src : '';
      const duration = this.assets.mediaDuration?.(src) ?? null;
      if (!(duration && duration > 0)) continue;
      const offset = Number.isFinite(Number(props.source_offset_seconds)) ? Number(props.source_offset_seconds) : 0;
      const authoredLoop = Number.isFinite(Number(props.loop_duration_seconds)) && Number(props.loop_duration_seconds) > 0
        ? Math.min(duration, Number(props.loop_duration_seconds))
        : duration;
      const looping = props.loop !== false;
      const sourceTime = videoSourceTime(evaluation.time, evaluation.scene.start_time, offset, authoredLoop, looping);
      this.assets.seekMedia?.(src, sourceTime);
    }
    const changed = [...evaluation.layers.values()].some(
      (o) => o.scale !== 1 || o.translate.x !== 0 || o.translate.y !== 0 || o.opacity !== 1 ||
        o.rotation !== 0 || o.crop !== 0 || o.strip !== 0 || o.blur !== 0 || o.invert !== 0,
    );
    if (!changed) {
      resetOutputs(v);
      return;
    }
    applyOutputs(v, evaluation.layers);
  }

  setSelection(sceneId: string | null, layerId: string | null = null): void {
    this.selectedSceneId = sceneId;
    this.selectedLayerId = layerId;
    this.updateBoardVisibility();
    this.drawRing();
    this.drawSelectionOverlay();
  }

  /**
   * Progressive first-run disclosure. The authored layout always contains
   * all ten boards; only the untouched coach view withholds the second row.
   * This keeps overview geometry truthful and makes the remaining scenes
   * appear as soon as the user starts working.
   */
  setFirstRunMode(active: boolean): void {
    if (active === this.firstRunMode) return;
    this.firstRunMode = active;
    this.updateBoardVisibility();
    this.drawWires();
  }

  /** Focused editing/review isolates the selected board from wall clutter. */
  setFocusIsolation(active: boolean): void {
    if (active === this.focusIsolation) return;
    this.focusIsolation = active;
    this.updateBoardVisibility();
    this.drawWires();
  }

  /** Base visibility before live/poster arbitration. */
  private boardVisible(sceneId: string, index: number): boolean {
    if (this.focusIsolation) return sceneId === this.selectedSceneId;
    return !this.firstRunMode || index < 5;
  }

  private updateBoardVisibility(): void {
    for (let i = 0; i < this.sceneOrder.length; i++) {
      const id = this.sceneOrder[i];
      const v = this.boardVisuals.get(id);
      if (!v) continue;
      const visible = this.boardVisible(id, i);
      const live = id === this.liveSceneId;
      const lod = lodForZoom(this.camera.zoom);
      const sprite = this.posterSprites.get(id);
      if (!visible) {
        v.container.visible = false;
        if (sprite) sprite.visible = false;
        continue;
      }
      if (live || lod === 'silhouette') {
        v.container.visible = true;
        if (sprite) sprite.visible = false;
      } else {
        this.syncPoster(id);
        v.container.visible = false;
        const poster = this.posterSprites.get(id);
        if (poster) poster.visible = true;
      }
    }
  }

  setCamera(cam: CameraState): void {
    this.applyCamera(cam);
  }

  /** Test-only geometry readout used with the deterministic ?shot channel. */
  compositionSnapshot(): CompositionSnapshot {
    return {
      camera: { ...this.camera },
      firstRunMode: this.firstRunMode,
      selectedSceneId: this.selectedSceneId,
      liveSceneId: this.liveSceneId,
      boards: this.sceneOrder.map((id) => {
        const box = this.layoutBoxes.get(id)!;
        const v = this.boardVisuals.get(id);
        const poster = this.posterSprites.get(id);
        const visible = (v?.container.visible ?? false) || (poster?.visible ?? false);
        return {
          id,
          visible,
          x: box.x * this.camera.zoom + this.camera.x,
          y: box.y * this.camera.zoom + this.camera.y,
          w: box.w * this.camera.zoom,
          h: boardFullHeight(box) * this.camera.zoom,
        };
      }),
    };
  }

  private applyCamera(cam: CameraState): void {
    this.camera = cam;
    this.world.scale.set(cam.zoom);
    this.world.position.set(cam.x, cam.y);
    this.updateZoomBands();
    this.drawRing();
    this.drawSelectionOverlay();
    this.drawGhost();
  }

  private updateZoomBands(): void {
    const zoom = this.camera.zoom;
    const lod = lodForZoom(zoom);
    const connectors = zoom < 0.55 ? 'dashed' : 'solid';
    // frame B's fit-all lands near 0.30; keep the soft board shadows there
    // like the frozen reference overview.
    const shadows = zoom > 0.28;
    if (
      lod !== this.zoomBand.lod ||
      connectors !== this.zoomBand.connectors ||
      shadows !== this.zoomBand.shadows
    ) {
      this.zoomBand = { connectors, lod, shadows };
      this.applyLod(lod);
      for (const v of this.boardVisuals.values()) v.shadow.visible = shadows;
      this.drawWires();
    }
    this.updateBoardVisibility();
  }

  private applyLod(mode: LodMode): void {
    for (const [id, v] of this.boardVisuals) {
      const silhouette = mode === 'silhouette';
      v.artContainer.visible = !silhouette;
      v.foot.visible = !silhouette;
      const sprite = this.posterSprites.get(id);
      if (sprite) sprite.visible = sprite.visible && !silhouette;
    }
  }

  /** Live move of a board during drag (world units). */
  moveBoard(sceneId: string, box: BoardBox): void {
    const v = this.boardVisuals.get(sceneId);
    if (!v) return;
    this.layoutBoxes.set(sceneId, { ...box });
    v.box = { ...box };
    v.container.position.set(box.x, box.y);
    v.container.rotation = (box.rotation * Math.PI) / 180;
    const sprite = this.posterSprites.get(sceneId);
    if (sprite) {
      sprite.position.set(box.x, box.y);
      sprite.rotation = (box.rotation * Math.PI) / 180;
    }
    const overlay = this.borderOverlays.get(sceneId);
    if (overlay) {
      overlay.destroy();
      this.borderOverlays.delete(sceneId);
      if (sceneId === this.liveSceneId) this.overlayBorder(v, true);
    }
    this.drawWires();
    this.drawRing();
    this.drawSelectionOverlay();
  }

  /** Snap a dragged box against canvas siblings + world origin edges. */
  private snapTargets(excludeId: string): { x: number[]; y: number[] } {
    const xs = [0];
    const ys = [0];
    for (const [id, box] of this.layoutBoxes) {
      if (id === excludeId) continue;
      xs.push(box.x, box.x + box.w, box.x + box.w / 2);
      ys.push(box.y, box.y + boardFullHeight(box), box.y + boardFullHeight(box) / 2);
    }
    return { x: xs, y: ys };
  }

  snapBox(sceneId: string, box: BoardBox, thresholdPx = 7): BoardBox {
    return this.snapBoxWithGuides(sceneId, box, thresholdPx).box;
  }

  /**
   * Snap a dragged box against canvas siblings + world origin edges and
   * report which guide lines fired (world coords) so the drag can visualize
   * them (plan: snap acquire/release — guides fade in, position follows).
   */
  snapBoxWithGuides(
    sceneId: string,
    box: BoardBox,
    thresholdPx = 7,
  ): { box: BoardBox; gx: number[]; gy: number[] } {
    const t = this.snapTargets(sceneId);
    const zoom = this.camera.zoom;
    const snapped = { ...box };
    const gx: number[] = [];
    const gy: number[] = [];
    for (const cand of t.x) {
      for (const edge of [box.x, box.x + box.w / 2, box.x + box.w]) {
        if (Math.abs(edge - cand) <= thresholdPx / zoom) {
          snapped.x = box.x + (cand - edge);
          if (!gx.includes(cand)) gx.push(cand);
          break;
        }
      }
    }
    for (const cand of t.y) {
      for (const edge of [box.y, box.y + boardFullHeight(box) / 2, box.y + boardFullHeight(box)]) {
        if (Math.abs(edge - cand) <= thresholdPx / zoom) {
          snapped.y = box.y + (cand - edge);
          if (!gy.includes(cand)) gy.push(cand);
          break;
        }
      }
    }
    return { box: snapped, gx, gy };
  }

  /** Show (or clear) the live snap guides, in screen space. */
  showSnapGuides(gx: number[] | null, gy: number[] = []): void {
    this.snapLayer.removeChildren().forEach((c) => c.destroy({ children: true }));
    if (!gx || (gx.length === 0 && gy.length === 0)) return;
    const zoom = this.camera.zoom;
    const stageW = this.app?.screen.width ?? 0;
    const stageH = this.app?.screen.height ?? 0;
    const g = new Graphics();
    for (const wx of gx) {
      const x = Math.round(wx * zoom + this.camera.x) + 0.5;
      g.moveTo(x, 0).lineTo(x, stageH);
    }
    for (const wy of gy) {
      const y = Math.round(wy * zoom + this.camera.y) + 0.5;
      g.moveTo(0, y).lineTo(stageW, y);
    }
    g.stroke({ width: 1, color: ACCENT_HEX, alpha: 0.85, ...({ dash: [6, 5] }) });
    g.eventMode = 'none';
    this.snapLayer.addChild(g);
  }

  private drawWires(): void {
    this.wires.removeChildren().forEach((c) => c.destroy({ children: true }));
    if (!this.doc || this.focusIsolation) return;
    const zoom = this.camera.zoom;
    const dashed = this.zoomBand.connectors === 'dashed';
    const arrows = zoom > 0.45;
    for (let i = 0; i + 1 < this.sceneOrder.length; i++) {
      if (this.firstRunMode && i >= 4) continue;
      const a = this.layoutBoxes.get(this.sceneOrder[i]);
      const b = this.layoutBoxes.get(this.sceneOrder[i + 1]);
      if (!a || !b) continue;
      const active = this.liveSceneId !== null && this.sceneOrder[i] === this.liveSceneId;
      const x1 = a.x + a.w;
      const y1 = a.y + BOARD_HEAD + a.bodyH / 2;
      const x2 = b.x;
      const y2 = b.y + BOARD_HEAD + b.bodyH / 2;
      const ym = (y1 + y2) / 2;
      const g = new Graphics();
      g.moveTo(x1, y1);
      g.bezierCurveTo(x1, ym, x2, ym, x2, y2);
      g.stroke({
        width: active ? 1.3 / FIRST_RUN_ZOOM : STROKE_W,
        color: 0x171719,
        // dashed overview wires read slightly stronger: the row-to-row
        // hop (05→06) sweeps the inter-row gap and keeps the wall one piece
        alpha: active ? 0.8 : dashed ? 0.3 : 0.2,
        ...(dashed && !active ? { dash: [6 / zoom, 5 / zoom] } : {}),
      });
      if (arrows) {
        const dx = x2 - x1;
        const dy = y2 - y1;
        const len = Math.hypot(dx, dy) || 1;
        const ux = dx / len;
        const uy = dy / len;
        const size = 5 / FIRST_RUN_ZOOM;
        const tipX = x2 - ux * 2;
        const tipY = y2 - uy * 2;
        g.moveTo(tipX, tipY);
        g.lineTo(tipX - ux * size - uy * size * 0.42, tipY - uy * size + ux * size * 0.42);
        g.lineTo(tipX - ux * size + uy * size * 0.42, tipY - uy * size - ux * size * 0.42);
        g.closePath();
        g.fill({ color: 0x171719, alpha: active ? 0.9 : 0.35 });
      }
      this.wires.addChild(g);
    }
  }

  private drawRing(): void {
    this.ringLayer.removeChildren().forEach((c) => c.destroy({ children: true }));
    if (!this.selectedSceneId) return;
    const box = this.layoutBoxes.get(this.selectedSceneId);
    if (!box) return;
    const zoom = this.camera.zoom;
    const moat = 6; // screen px
    const fullH = boardFullHeight(box);
    const sx = box.x * zoom + this.camera.x - moat;
    const sy = box.y * zoom + this.camera.y - moat;
    const sw = box.w * zoom + moat * 2;
    const sh = fullH * zoom + moat * 2;
    const g = new Graphics()
      .roundRect(sx, sy, sw, sh, 10 * zoom + moat)
      .stroke({ width: 2, color: 0x7567e8 });
    // corner handles (frames B/C/D)
    for (const [hx, hy] of [[sx, sy], [sx + sw, sy], [sx + sw, sy + sh], [sx, sy + sh]]) {
      g.rect(hx - 3.5, hy - 3.5, 7, 7).fill(0xffffff).stroke({ width: 1.5, color: 0x7567e8 });
    }
    g.eventMode = 'none';
    this.ringLayer.addChild(g);
  }

  /** Show/hide the pending proposal ghost overlays (frame D). */
  setProposalPreview(items: ProposalGhost[] | null): void {
    this.proposalItems = items;
    this.drawGhost();
  }

  private drawGhost(): void {
    this.ghostLayer.removeChildren().forEach((c) => c.destroy({ children: true }));
    if (!this.proposalItems) return;
    const zoom = this.camera.zoom;
    for (const item of this.proposalItems) {
      const box = this.layoutBoxes.get(item.sceneId);
      if (!box) continue;
      const gx = box.x + item.rect.x * box.w;
      const gy = box.y + BOARD_HEAD + item.rect.y * box.bodyH;
      const gw = item.rect.w * box.w;
      const gh = item.rect.h * box.bodyH;
      // frame D: accent-wash region with a dashed border and a floating label
      const g = new Graphics()
        .roundRect(gx, gy, gw, gh, 3 / FIRST_RUN_ZOOM)
        .fill({ color: 0xece9ff, alpha: 0.6 })
        .stroke({
          width: 1.5 / FIRST_RUN_ZOOM,
          color: ACCENT_HEX,
          alpha: 0.85,
          ...({ dash: [6 / zoom, 5 / zoom] }),
        });
      g.eventMode = 'none';
      const label = this.monoText(item.label, 9.5, '#7567e8');
      label.x = gx + 2 / zoom;
      label.y = gy - 16 / zoom;
      this.ghostLayer.addChild(g, label);
    }
  }

  private monoText(text: string, size: number, fill: string): Text {
    const t = new Text({
      text,
      style: { fontFamily: '"Geist Mono", ui-monospace, monospace', fontSize: size, fill },
      resolution: Math.max(2, Math.min(4, (window.devicePixelRatio || 1) * 2)),
    });
    t.eventMode = 'none';
    return t;
  }

  /**
   * Screen-space selection chrome (frame C): dashed guides through the
   * selected media slice's edges, corner crop brackets, dimension pills and a
   * slice caption. Also draws the printed scene-index annotation card when
   * zoomed to poster/silhouette LOD (frame B).
   */
  private drawSelectionOverlay(): void {
    this.overlayLayer.removeChildren().forEach((c) => c.destroy({ children: true }));
    const zoom = this.camera.zoom;
    const stageW = this.app?.screen.width ?? 0;
    const stageH = this.app?.screen.height ?? 0;

    // frame B: printed scene-index card in the gap between the wall rows,
    // poster/silhouette only — bridges the two rows instead of trailing the
    // proof strip (reference overview keeps the rows reading as one wall).
    if (lodForZoom(zoom) !== 'full') {
      const anchor = this.layoutBoxes.get('scene-07'); // demo doc: row-2 board
      if (anchor) {
        const ax = (anchor.x - wLen(40)) * zoom + this.camera.x;
        const ay = (anchor.y - wLen(82)) * zoom + this.camera.y;
        const t1 = this.monoText('Scene index — reel 02 / 06–10', 10, '#171719');
        const t2 = this.monoText('06–10 · printed 4-up', 9.5, '#77737d');
        const cw = Math.max(t1.width, t2.width) + 26;
        const card = new Graphics()
          .roundRect(ax, ay, cw, 42, 4)
          .fill(0xf7f5ee)
          .stroke({ width: 1, color: 0x171719, alpha: 0.25 })
          .rect(ax, ay + 4, 3, 34)
          .fill(ACCENT_HEX);
        card.eventMode = 'none';
        t1.x = ax + 13;
        t1.y = ay + 8;
        t2.x = ax + 13;
        t2.y = ay + 24;
        this.overlayLayer.addChild(card, t1, t2);
      }

    }

    // frame C: layer slice chrome
    const sceneId = this.selectedSceneId;
    const layerId = this.selectedLayerId;
    if (!sceneId || !layerId) return;
    const v = this.boardVisuals.get(sceneId);
    const box = this.layoutBoxes.get(sceneId);
    if (!v || !box) return;
    const rect = v.layerRects.get(layerId);
    if (!rect) return;

    // container-local ref px -> world (boards may be rotated)
    const r = (box.rotation * Math.PI) / 180;
    const cos = Math.cos(r);
    const sin = Math.sin(r);
    const toWorld = (lx: number, ly: number) => ({
      x: box.x + (lx * cos - ly * sin) * BOARD_SCALE,
      y: box.y + (lx * sin + ly * cos) * BOARD_SCALE,
    });
    const toScreen = (p: { x: number; y: number }) => ({
      x: p.x * zoom + this.camera.x,
      y: p.y * zoom + this.camera.y,
    });
    const c00 = toScreen(toWorld(rect.x, rect.y));
    const c10 = toScreen(toWorld(rect.x + rect.w, rect.y));
    const c11 = toScreen(toWorld(rect.x + rect.w, rect.y + rect.h));
    const c01 = toScreen(toWorld(rect.x, rect.y + rect.h));
    // unit edge vectors (screen space)
    const ex = norm2(c10.x - c00.x, c10.y - c00.y);
    const ey = norm2(c01.x - c00.x, c01.y - c00.y);

    // dashed alignment guides through each slice edge, spanning the stage
    const guides = new Graphics();
    for (const p of [c00, c10, c11, c01]) {
      guides.moveTo(0, p.y).lineTo(stageW, p.y);
      guides.moveTo(p.x, 0).lineTo(p.x, stageH);
    }
    guides.stroke({ width: 1, color: ACCENT_HEX, alpha: 0.45, ...({ dash: [6, 5] }) });
    guides.eventMode = 'none';
    this.overlayLayer.addChild(guides);

    // corner crop brackets
    const arm = 12;
    const brackets = new Graphics();
    const corner = (c: { x: number; y: number }, sx: number, sy: number) => {
      brackets
        .moveTo(c.x - ex.x * arm * sx, c.y - ex.y * arm * sx)
        .lineTo(c.x, c.y)
        .lineTo(c.x - ey.x * arm * sy, c.y - ey.y * arm * sy);
    };
    corner(c00, 1, 1);
    corner(c10, -1, 1);
    corner(c11, -1, -1);
    corner(c01, 1, -1);
    brackets.stroke({ width: 2, color: ACCENT_HEX, alpha: 0.95 });
    brackets.eventMode = 'none';
    this.overlayLayer.addChild(brackets);

    // dimension pills: printed reference-px sizes, consistent with the inspector
    const pill = (cx: number, cy: number, label: string) => {
      const t = this.monoText(label, 10, '#ffffff');
      const pw = t.width + 14;
      const ph = 18;
      const g = new Graphics().roundRect(cx - pw / 2, cy - ph / 2, pw, ph, 9).fill(ACCENT_HEX);
      g.eventMode = 'none';
      t.x = cx - t.width / 2;
      t.y = cy - t.height / 2 + 1;
      this.overlayLayer.addChild(g, t);
    };
    pill(
      (c01.x + c11.x) / 2 + ey.x * 40,
      (c01.y + c11.y) / 2 + ey.y * 40,
      String(Math.round(rect.w)),
    );
    pill(
      (c10.x + c11.x) / 2 + ex.x * 26,
      (c10.y + c11.y) / 2 + ex.y * 26,
      String(Math.round(rect.h)),
    );

    // slice caption chip above the top-left corner
    const layer = this.doc?.scenes.flatMap((s) => s.layers).find((l) => l.id === layerId);
    const src = (layer?.props as { src?: string } | undefined)?.src;
    const caption = this.monoText(`media-slice · ${src ?? 'slice'}`, 9.5, '#d9d5ff');
    const chipW = caption.width + 16;
    const chipX = c00.x;
    // clear the board head band (34 ref px) plus the selection ring moat
    const chipY = c00.y - 72;
    const chip = new Graphics()
      .roundRect(chipX, chipY, chipW, 18, 4)
      .fill({ color: 0x171719, alpha: 0.85 });
    chip.eventMode = 'none';
    caption.x = chipX + 8;
    caption.y = chipY + 4;
    this.overlayLayer.addChild(chip, caption);
  }

  /** World-space point from a screen (canvas-local) point. */
  toWorld(sx: number, sy: number): { x: number; y: number } {    return {
      x: (sx - this.camera.x) / this.camera.zoom,
      y: (sy - this.camera.y) / this.camera.zoom,
    };
  }

  sceneAtWorld(wx: number, wy: number): string | null {
    for (let i = this.sceneOrder.length - 1; i >= 0; i--) {
      const box = this.layoutBoxes.get(this.sceneOrder[i]);
      if (box && boardHit(box, wx, wy)) return this.sceneOrder[i];
    }
    return null;
  }

  get currentLayout(): WorkspaceLayout {
    const boards: Record<string, BoardBox> = {};
    for (const [id, box] of this.layoutBoxes) boards[id] = { ...box };
    return { boards };
  }

  layoutBox(sceneId: string): BoardBox | null {
    return this.layoutBoxes.get(sceneId) ?? null;
  }

  render(): void {
    this.app?.render();
  }

  /** Deterministic canvas readback (bypasses the compositor for tests). */
  captureDataURL(): string | null {
    if (!this.app) return null;
    this.app.render();
    try {
      const canvas = this.app.renderer.extract.canvas(this.app.stage) as HTMLCanvasElement;
      return canvas.toDataURL('image/png');
    } catch {
      return null;
    }
  }

  destroy(): void {
    this.destroyed = true;
    const canvas = this.app?.canvas;
    if (canvas) canvas.removeEventListener('webglcontextlost', this.contextLostHandler);
    this.posterCache.clear();
    this.posterSprites.clear();
    // keep the view element: React owns the canvas (StrictMode remounts reuse it)
    this.app?.destroy(false, { children: true });
    this.app = null;
  }
}

export { clampZoom, BOARD_SCALE, sceneAtTime };
