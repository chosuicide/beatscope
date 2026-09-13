/**
 * The bundled first-run demo: "Beyond the Fog", the exact 10-scene project
 * shown in the four frozen reference frames (docs/design/beathi-canvas).
 *
 * Data consistency contract (design gate 2026-09-07):
 *   BPM 120 · 4/4 · bar 2.0 s · 121 bars · total 04:02 (242 s)
 *   01 Cold Open    00:00–00:24  bars 1–12    print        dissolve
 *   02 Pressure     00:24–00:52  bars 13–26   collage      dissolve
 *   03 Release Valve 00:52–01:16 bars 27–38   cut study    wipe
 *   04 Undertow     01:16–01:44  bars 39–52   signal       cut
 *   05 Sirens       01:44–02:06  bars 53–63   poster       dissolve
 *   06 Low Tide     02:06–02:30  bars 64–75   still        dissolve
 *   07 Harbor Lights 02:30–02:58 bars 76–89   halftone     dissolve
 *   08 Riptide      02:58–03:16  bars 90–98   collage A′   dissolve
 *   09 Fog Field    03:16–03:32  bars 99–106  signal live  cut
 *   10 Reprise      03:32–04:02  bars 107–121 print        dissolve
 *
 * Board boxes are stored in world units; the first-run camera (zoom 0.62)
 * maps them onto the frozen frame-A geometry exactly.
 */

import type {
  DirectionDocument,
  DirectionLayer,
  DirectionScene,
  ResponseChain,
  WorkspaceLayout,
  BoardBox,
  CameraState,
} from '../direction/types';
// .js extension keeps this module compilable to standalone ESM for the
// Node contract tests (tests/tsconfig.direction.json); bundler resolution
// maps it back to rhythm.ts.
import { DEMO_PROJECT_ID, DEMO_SOURCE_RHYTHM_SHA256 } from './rhythm.js';

export const FIRST_RUN_ZOOM = 0.62;
const w = (px: number) => px / FIRST_RUN_ZOOM;

const MEDIA = {
  fogRidge: 'demo-media/fog-ridge.png',
  fogBright: 'demo-media/fog-bright.png',
  paperFiber: 'demo-media/paper-fiber.png',
  halftone: 'demo-media/halftone.png',
};

let layerSeq = 0;
function layer(
  kind: DirectionLayer['kind'],
  label: string,
  props: DirectionLayer['props'],
  extra: Partial<DirectionLayer> = {},
): DirectionLayer {
  layerSeq += 1;
  return {
    id: `lay-${String(layerSeq).padStart(2, '0')}`,
    kind,
    label,
    visible: true,
    locked: false,
    opacity: 1,
    blend: 'normal',
    transform: { x: 0, y: 0, w: 1, h: 1, rotation: 0 },
    props,
    ...extra,
  };
}

let respSeq = 0;
function resp(c: Omit<ResponseChain, 'id'>): ResponseChain {
  respSeq += 1;
  return { id: `response-${String(respSeq).padStart(2, '0')}`, ...c };
}

const onsetsLow = (max: number): ResponseChain['driver'] => ({
  kind: 'ranked_onsets',
  band: 'low',
  tier: 'primary',
  max_events_per_bar: max,
  refractory_beats: 0.6,
});

const scenes: DirectionScene[] = [
  {
    id: 'scene-01',
    title: 'Cold Open',
    family: 'print',
    anchor: { kind: 'bars', start_bar: 1, end_bar: 13 },
    start_time: 0,
    end_time: 24,
    transition_out: 'dissolve',
    layers: [
      layer('graphic-field', 'Paper texture', { tile: MEDIA.paperFiber, tilePx: 230, blend: 'multiply', alpha: 0.55 }),
      layer('media-slice', 'Print — fog ridge', {
        frame: 'print',
        src: MEDIA.fogRidge,
        rect: { x: 9, y: 9, w: 196, photoH: 88, padBottom: 14 },
        focus: [0.5, 0.38],
      }),
      layer('editorial-typography', 'Caption card', {
        card: { x: 28, y: 98, pad: [3, 9, 5] },
        display: 'COLD OPEN',
        displaySize: 19,
        mono: 'BEYOND THE FOG · REEL 01',
      }),
      layer('editorial-typography', 'Timecode + reg mark', { timecode: '00:00–00:24', regmark: true }),
    ],
    responses: [
      resp({
        target_layer_id: 'lay-03',
        label: 'Downbeat pulse → caption scale',
        driver: onsetsLow(4),
        motion: { kind: 'scale_pulse', amount: 0.035, attack_seconds: 0.025, release_seconds: 0.22 },
      }),
    ],
  },
  {
    id: 'scene-02',
    title: 'Pressure',
    family: 'collage',
    anchor: { kind: 'bars', start_bar: 13, end_bar: 27 },
    start_time: 24,
    end_time: 52,
    transition_out: 'dissolve',
    layers: [
      layer('graphic-field', 'Fiber backing', { fill: 'rgba(19,19,21,.88)', tile: MEDIA.paperFiber, tilePx: 220, fillOver: true }),
      layer('media-slice', 'Torn photo — right', {
        torn: 'left',
        rect: { x: 0.54, y: 0, w: 0.46, h: 1 },
        src: MEDIA.fogRidge,
        focus: [0.72, 0.55],
        filter: { saturate: 0.72, contrast: 1.06, brightness: 0.95 },
      }),
      layer('editorial-typography', 'Masthead', {
        display: 'PRESSURE',
        displaySize: 21,
        pos: [9, 42],
        rotation: -2,
        color: '#f0eee6',
      }),
      layer('editorial-typography', 'Rule', { rule: { x: 9, y: 76, w: 64, h: 2, color: '#f0eee6' } }),
      layer('editorial-typography', 'Bar tag', { mono: 'BAR 13–26', corner: 'bottom-left' }),
      layer('editorial-typography', 'Reg mark', { regmark: true, corner: 'top-right', size: 11 }),
    ],
    responses: [
      resp({
        target_layer_id: 'lay-07',
        label: 'Low onsets → masthead recoil',
        driver: onsetsLow(4),
        motion: { kind: 'translate_recoil', axis: [1, 0], amount: 0.045, attack_seconds: 0.025, release_seconds: 0.22 },
      }),
      resp({
        target_layer_id: 'lay-06',
        label: 'Mid onsets → photo opacity lift',
        driver: { kind: 'ranked_onsets', band: 'mid', tier: 'secondary', max_events_per_bar: 2, refractory_beats: 1 },
        motion: { kind: 'opacity_lift', amount: 0.08, attack_seconds: 0.05, release_seconds: 0.4 },
      }),
    ],
  },
  {
    id: 'scene-03',
    title: 'Release Valve',
    family: 'cut study',
    anchor: { kind: 'bars', start_bar: 27, end_bar: 39 },
    start_time: 52,
    end_time: 76,
    transition_out: 'directional-wipe',
    layers: [
      layer('media-slice', 'Shot A', { rect: { x: 0, y: 0, w: 0.38, h: 1 }, src: MEDIA.fogBright, focus: [0.22, 0.42] }),
      layer('media-slice', 'Shot B', { rect: { x: 0.38, y: 0, w: 0.62, h: 1 }, src: MEDIA.fogRidge, focus: [0.82, 0.62] }),
      layer('editorial-typography', 'Shot tags', { tags: [['SHOT A', 8, 6], ['SHOT B', 84, 6]] }),
      layer('editorial-typography', 'Title', {
        display: 'RELEASE VALVE',
        displaySize: 11,
        pos: [8, -22],
        from: 'bottom',
        letterSpacing: 0.08,
        color: '#f0eee6',
      }),
      layer('editorial-typography', 'Cut tag', { mono: 'CUT 03 · 2 SLICES', corner: 'bottom-left' }),
    ],
    responses: [
      resp({
        target_layer_id: 'lay-11',
        label: 'Mid onsets → Shot A drift',
        driver: { kind: 'ranked_onsets', band: 'mid', tier: 'secondary', max_events_per_bar: 2, refractory_beats: 1 },
        motion: { kind: 'translate_recoil', axis: [1, 0], amount: 0.03, attack_seconds: 0.03, release_seconds: 0.3 },
      }),
    ],
  },
  {
    id: 'scene-04',
    title: 'Undertow',
    family: 'signal',
    anchor: { kind: 'bars', start_bar: 39, end_bar: 53 },
    start_time: 76,
    end_time: 104,
    transition_out: 'cut',
    layers: [
      layer('graphic-field', 'Scanline grid', { fill: '#101014', scanlines: 30 }),
      layer('graphic-field', 'Contour wave', {
        polyline: [0, 34, 22, 30, 40, 35, 58, 22, 76, 31, 94, 12, 112, 28, 130, 18, 148, 33, 166, 24, 190, 29],
        stroke: 'rgba(196,232,203,.85)',
        width: 1.5,
        y: 34,
      }),
      layer('graphic-field', 'Scan bar + tag', { scan: 118, tag: 'T3 · CONTOURS' }),
    ],
    responses: [
      resp({
        target_layer_id: 'lay-17',
        label: 'Beat phase → wave pulse',
        driver: { kind: 'beat_phase', subdivision: 4 },
        motion: { kind: 'scale_pulse', amount: 0.05, attack_seconds: 0.02, release_seconds: 0.2 },
      }),
    ],
  },
  {
    id: 'scene-05',
    title: 'Sirens',
    family: 'poster',
    anchor: { kind: 'bars', start_bar: 53, end_bar: 64 },
    start_time: 104,
    end_time: 126,
    transition_out: 'dissolve',
    layers: [
      layer('graphic-field', 'Paper texture', { tile: MEDIA.paperFiber, tilePx: 230, blend: 'multiply', alpha: 0.4 }),
      layer('graphic-field', 'Poster cards', {
        cards: [
          { x: 12, y: 12, w: 88, h: 70, rot: -3.5, fill: '#fbfaf7' },
          { x: 56, y: 20, w: 100, h: 72, rot: 2, fill: '#fdfcf8' },
        ],
      }),
      layer('editorial-typography', 'Poster type', {
        cardType: { x: 64, y: 28, display: 'SIRENS', displaySize: 15, mono: ['SIDE B', '02:06'], ruleW: 34 },
      }),
      layer('editorial-typography', 'Tape + timecode', { tape: { x: 86, y: 14, w: 40, rot: 38 }, timecode: '01:44–02:06' }),
    ],
    responses: [
      resp({
        target_layer_id: 'lay-20',
        label: 'High onsets → poster lift',
        driver: { kind: 'ranked_onsets', band: 'high', tier: 'primary', max_events_per_bar: 6, refractory_beats: 0.7 },
        motion: { kind: 'opacity_lift', amount: 0.1, attack_seconds: 0.02, release_seconds: 0.24 },
      }),
    ],
  },
  {
    id: 'scene-06',
    title: 'Low Tide',
    family: 'still',
    anchor: { kind: 'bars', start_bar: 64, end_bar: 76 },
    start_time: 126,
    end_time: 150,
    transition_out: 'dissolve',
    layers: [
      layer('media-slice', 'Still — harbor', { full: true, src: MEDIA.fogBright, focus: [0.3, 0.6], filter: { saturate: 0.7, brightness: 0.9 } }),
      layer('graphic-field', 'Letterbox bars', { letterbox: 18, fill: '#0b0b0d' }),
      layer('editorial-typography', 'Still tag', { mono: 'LOW TIDE · STILL 02', corner: 'bottom-left', color: 'rgba(240,238,230,.75)' }),
    ],
    responses: [
      resp({
        target_layer_id: 'lay-23',
        label: 'Low onsets → still push',
        driver: onsetsLow(2),
        motion: { kind: 'scale_pulse', amount: 0.025, attack_seconds: 0.04, release_seconds: 0.5 },
      }),
    ],
  },
  {
    id: 'scene-07',
    title: 'Harbor Lights',
    family: 'halftone',
    anchor: { kind: 'bars', start_bar: 76, end_bar: 90 },
    start_time: 150,
    end_time: 178,
    transition_out: 'dissolve',
    layers: [
      layer('graphic-field', 'Paper base', { fill: '#f2f0e9' }),
      layer('graphic-field', 'Halftone field', { tile: MEDIA.halftone, tilePx: 190, blend: 'multiply', alpha: 0.9 }),
      layer('editorial-typography', 'Masthead', { display: 'HARBOR LIGHTS', displaySize: 18, pos: [10, 40], color: '#171719' }),
      layer('editorial-typography', 'Tag', { mono: 'HT · 45 LPI', corner: 'bottom-left' }),
    ],
    responses: [
      resp({
        target_layer_id: 'lay-27',
        label: 'Mid onsets → halftone shimmer',
        driver: { kind: 'ranked_onsets', band: 'mid', tier: 'secondary', max_events_per_bar: 3, refractory_beats: 0.8 },
        motion: { kind: 'opacity_lift', amount: 0.06, attack_seconds: 0.03, release_seconds: 0.28 },
      }),
    ],
  },
  {
    id: 'scene-08',
    title: 'Riptide',
    family: 'collage',
    anchor: { kind: 'bars', start_bar: 90, end_bar: 99 },
    start_time: 178,
    end_time: 196,
    transition_out: 'dissolve',
    layers: [
      layer('graphic-field', 'Fiber backing', { fill: 'rgba(19,19,21,.88)', tile: MEDIA.paperFiber, tilePx: 220, fillOver: true }),
      layer('media-slice', 'Torn photo — left', {
        torn: 'right',
        rect: { x: 0, y: 0, w: 0.46, h: 1 },
        src: MEDIA.fogRidge,
        focus: [0.3, 0.5],
        filter: { saturate: 0.72, contrast: 1.06, brightness: 0.95 },
      }),
      layer('editorial-typography', 'Masthead', {
        display: 'RIPTIDE',
        displaySize: 21,
        pos: [-9, 42],
        from: 'right',
        rotation: 2,
        color: '#f0eee6',
      }),
      layer('editorial-typography', 'Rule', { rule: { x: -9, y: 76, w: 64, h: 2, color: '#f0eee6' } }),
      layer('editorial-typography', 'Bar tag', { mono: 'BAR 90–98', corner: 'bottom-right', color: 'rgba(240,238,230,.62)' }),
      layer('editorial-typography', 'Reg mark', { regmark: true, corner: 'top-left', size: 11 }),
    ],
    responses: [
      resp({
        target_layer_id: 'lay-32',
        label: 'Low onsets → masthead recoil',
        driver: onsetsLow(4),
        motion: { kind: 'translate_recoil', axis: [-1, 0], amount: 0.045, attack_seconds: 0.025, release_seconds: 0.22 },
      }),
    ],
  },
  {
    id: 'scene-09',
    title: 'Fog Field',
    family: 'signal',
    anchor: { kind: 'bars', start_bar: 99, end_bar: 107 },
    start_time: 196,
    end_time: 212,
    transition_out: 'cut',
    layers: [
      layer('graphic-field', 'Scanline grid', { fill: '#101014', scanlines: 30 }),
      layer('graphic-field', 'Contour wave', {
        polyline: [0, 26, 24, 32, 46, 18, 70, 30, 94, 14, 118, 28, 142, 20, 166, 32, 190, 24],
        stroke: 'rgba(196,232,203,.85)',
        width: 1.5,
        y: 22,
      }),
      layer('graphic-field', 'Scan bar + tag', { scan: 64, tag: 'LIVE · T3' }),
    ],
    responses: [
      resp({
        target_layer_id: 'lay-37',
        label: 'Beat phase → wave pulse',
        driver: { kind: 'beat_phase', subdivision: 2 },
        motion: { kind: 'scale_pulse', amount: 0.04, attack_seconds: 0.02, release_seconds: 0.2 },
      }),
    ],
  },
  {
    id: 'scene-10',
    title: 'Reprise',
    family: 'print',
    anchor: { kind: 'bars', start_bar: 107, end_bar: 122 },
    start_time: 212,
    end_time: 242,
    transition_out: 'hold-through',
    layers: [
      layer('graphic-field', 'Paper texture', { tile: MEDIA.paperFiber, tilePx: 230, blend: 'multiply', alpha: 0.55 }),
      layer('media-slice', 'Print — fog bright', {
        frame: 'print',
        src: MEDIA.fogBright,
        rect: { x: 22, y: 10, w: 170, photoH: 82, padBottom: 12 },
        focus: [0.62, 0.3],
      }),
      layer('editorial-typography', 'Caption card', {
        card: { x: 40, y: 96, pad: [3, 9, 5] },
        display: 'REPRISE',
        displaySize: 19,
        mono: 'BEYOND THE FOG · REEL 02',
      }),
      layer('editorial-typography', 'Timecode + reg mark', { timecode: '03:32–04:02', regmark: true }),
    ],
    responses: [
      resp({
        target_layer_id: 'lay-41',
        label: 'Downbeat impulse → caption scale',
        driver: { kind: 'beat_phase', subdivision: 1 },
        motion: { kind: 'scale_pulse', amount: 0.03, attack_seconds: 0.03, release_seconds: 0.3 },
      }),
    ],
  },
];

const HEAD = 34;
const FOOT = 26;
function board(refX: number, refY: number, refW: number, refBodyH: number, rotDeg = 0): BoardBox {
  return { x: w(refX), y: w(refY), w: w(refW), bodyH: w(refBodyH), rotation: rotDeg };
}

// Row 1 mirrors frame A: five working boards spread between the dock and
// the right rail at first-run zoom (world ref px map 1:1 to stage px).
// Bodies reach the reference band bottom (~430) without touching the coach
// mark (top 520) or transport. Scene 02 keeps the frozen C/D focus size.
// Row 2 (06–10) completes the chronological wall. It stays close enough to
// row 1 that Fit all reads as one composition instead of two distant islands.
// The first-run host progressively withholds this row while the coach is
// visible, so frame A can introduce five boards without corrupting the real
// overview geometry.
const layout: WorkspaceLayout = {
  boards: {
    'scene-01': board(14, 190, 240, 180),
    'scene-02': board(266, 84, 250, 120),
    'scene-03': board(500, 232, 205, 145),
    'scene-04': board(715, 96, 190, 135),
    'scene-05': board(915, 218, 175, 125),
    'scene-06': board(6, 580, 240, 180, -0.6),
    'scene-07': board(270, 555, 235, 175, 0.5),
    'scene-08': board(528, 575, 245, 180, 0.9),
    'scene-09': board(792, 560, 225, 170, -0.4),
    'scene-10': board(1034, 585, 240, 185, 0.7),
  },
};

export const BOARD_HEAD = w(HEAD);
export const BOARD_FOOT = w(FOOT);
/** Reference-px header/footer band heights used inside the board container. */
export const BOARD_HEAD_REF = HEAD;
export const BOARD_FOOT_REF = FOOT;

/** Full board height for a layout box, in world units. */
export function boardFullHeight(box: BoardBox): number {
  return BOARD_HEAD + box.bodyH + BOARD_FOOT;
}

/** Wall bounding box (world units) derived from the actual layout. */
function wallBounds(layout: WorkspaceLayout): { minX: number; minY: number; wallW: number; wallH: number } {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const box of Object.values(layout.boards)) {
    minX = Math.min(minX, box.x);
    minY = Math.min(minY, box.y);
    maxX = Math.max(maxX, box.x + box.w);
    maxY = Math.max(maxY, box.y + boardFullHeight(box));
  }
  const margin = w(40);
  return { minX: minX - margin, minY: minY - margin, wallW: maxX - minX + margin * 2, wallH: maxY - minY + margin * 2 };
}

/**
 * Fit-all camera (frame B). The frozen reference covers 87% of the frame
 * width at ~64% of its height, so the zoom targets 88% of the usable width
 * capped at 73% of the usable height — whichever side binds wins. The
 * compact two-row wall keeps the boards legible at overview LOD.
 */
export function fitAllCamera(viewW: number, viewH: number, layout: WorkspaceLayout): CameraState {
  const { minX, minY, wallW, wallH } = wallBounds(layout);
  const zoom = Math.max(0.12, Math.min(3, Math.min((viewW * 0.88) / wallW, (viewH * 0.73) / wallH)));
  const contentW = wallW * zoom;
  const contentH = wallH * zoom;
  return {
    x: (viewW - contentW) / 2 - minX * zoom,
    // Optical rather than mathematical centering: the floating transport
    // already occupies the lower field, so the wall sits slightly high.
    y: (viewH - contentH) / 2 - minY * zoom - viewH * 0.055,
    zoom,
  };
}

/** First-run camera (frame A): the wall origin sits at the stage origin. */
export function firstRunCamera(): CameraState {
  return { x: 0, y: 0, zoom: FIRST_RUN_ZOOM };
}

/**
 * Focus camera for a selected board (frames C/D). The frozen references
 * show the board spanning ~86% of the width between the dock and the right
 * panel, capped at 62% of the stage height; callers pass that usable rect.
 */
export function focusCamera(box: BoardBox, viewW: number, viewH: number): CameraState {
  const fullH = boardFullHeight(box);
  const zoom = Math.min(3, (0.86 * viewW) / box.w, (0.62 * viewH) / fullH);
  const cx = box.x + box.w / 2;
  const cy = box.y + fullH / 2;
  return { x: viewW / 2 - cx * zoom, y: viewH / 2 - cy * zoom, zoom };
}

export const demoDocument: DirectionDocument = {
  schema: 'beatscope-direction-1',
  version: '0.12.0',
  project_id: DEMO_PROJECT_ID,
  project_title: 'Beyond the Fog',
  source_rhythm_sha256: DEMO_SOURCE_RHYTHM_SHA256,
  composition: { primary_ratio: '16:9', width: 1920, height: 1080, background: '#F5F1E8' },
  theme: {},
  assets: [],
  scenes,
  transitions: [],
  diagnostics: {},
};

export const demoLayout: WorkspaceLayout = layout;
