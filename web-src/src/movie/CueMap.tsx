/**
 * Cue map: the original BeatScope instrument (5-row subdivision grid plus a
 * motion-cue rail) and the whole-song overview, ported from the legacy
 * renderer. Same geometry (124/18/54 px margins, 59 px rows, 8-bar window,
 * 16/32 subdivisions), same data mapping, Beathi palette.
 *
 * Like the original it splits every view into a static canvas and an overlay
 * canvas, so following the playhead only repaints a few lines instead of the
 * whole instrument. Read-only: a click seeks, nothing edits the document.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useCopy } from './copy';
import type { MovieRhythm } from './types';
import { createMusicGrid, type MusicGrid } from '../../../beatscope/web/music-grid.mjs';

const COLLAPSE_KEY = 'beathi.cuemap.collapsed';

const ROWS = ['all', 'low', 'mid', 'high', 'accent'] as const;
const LABELS = ['IMPACT', 'LOW / SCALE', 'MID / FLOW', 'HIGH / FLASH', 'ACCENT / BLOOM'];
const HINTS = ['transient', 'size + weight', 'surface motion', 'light + detail', 'hero event'];
const LEFT = 124;
const RIGHT = 18;
const TOP = 30;
const ROW_H = 27;
const GRID_BOTTOM = TOP + ROWS.length * ROW_H;
/** Virtual instrument boxes: the canvases scale to fit, never clip. */
const MAP_W = 1400;
const MAP_H = 232;
const OVERVIEW_W = 1560;
const OVERVIEW_H = 104;

const INK = '#171719';
const MID = '#77737d';
const ACCENT = '#7567e8';
const LINE = 'rgba(34,31,40,0.14)';
const PAPER = '#f7f6f2';
const BAR_FILL = ['rgba(34,31,40,0.022)', 'rgba(34,31,40,0.045)'];
/** Structure families read as paper tints with a hairline, not as colour bars. */
const FAMILY_TINT = [
  'rgba(23,23,25,0.15)',
  'rgba(23,23,25,0.09)',
  'rgba(23,23,25,0.05)',
  'rgba(117,103,232,0.13)',
  'rgba(23,23,25,0.12)',
  'rgba(23,23,25,0.07)',
];

const clamp01 = (value: number) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0));

/** Strongest measured value per subdivision bucket, per row. */
function stepValues(rhythm: MovieRhythm, metrics: MusicGrid) {
  const { subdivision, bars } = metrics;
  const values: Record<string, Float64Array> = {};
  for (const row of ROWS) values[row] = new Float64Array(bars * subdivision);
  const rawByStep = new Map<number, number>();
  const accents = new Set((rhythm.cues?.accent ?? []).map(cue => cue.time));
  for (const onset of rhythm.onsets ?? []) {
    const step = Math.floor(metrics.stepAtTime(onset.time));
    if (step < 0 || step >= bars * subdivision) continue;
    const bands = onset.bands ?? {};
    const pick = (key: string) => clamp01(bands[key] ?? (key === 'all' ? onset.strength : 0));
    if (!rawByStep.has(step) || pick('all') > values.all[step]) rawByStep.set(step, onset.time);
    values.all[step] = Math.max(values.all[step], pick('all'));
    values.low[step] = Math.max(values.low[step], pick('low'));
    values.mid[step] = Math.max(values.mid[step], pick('mid'));
    values.high[step] = Math.max(values.high[step], pick('high'));
    if (onset.accent || accents.has(onset.time)) {
      values.accent[step] = Math.max(values.accent[step], clamp01(onset.strength));
    }
  }
  return { values, rawByStep };
}

function fitCanvas(canvas: HTMLCanvasElement, virtualWidth: number, virtualHeight: number) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const width = canvas.clientWidth || virtualWidth;
  const height = canvas.clientHeight || virtualHeight;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const context = canvas.getContext('2d');
  if (!context) return null;
  // uniform scale, centred: the instrument never distorts and never clips
  const scale = Math.min(width / virtualWidth, height / virtualHeight);
  const offsetX = (width - virtualWidth * scale) / 2;
  const offsetY = (height - virtualHeight * scale) / 2;
  context.setTransform(dpr * scale, 0, 0, dpr * scale, dpr * offsetX, dpr * offsetY);
  return context;
}

/** Client x -> virtual x under the same fit the canvas was drawn with. */
function virtualX(clientX: number, rect: { left: number; width: number; height: number }, virtualWidth: number, virtualHeight: number) {
  const scale = Math.min(rect.width / virtualWidth, rect.height / virtualHeight);
  const offsetX = (rect.width - virtualWidth * scale) / 2;
  return (clientX - rect.left - offsetX) / scale;
}

interface CueMapProps {
  rhythm: MovieRhythm;
  time: number;
  seek: (time: number) => void;
  startBar: number;
  onStartBar: (bar: number) => void;
  onFollowChange: (follow: boolean) => void;
}

export function CueMap({ rhythm, time, seek, startBar, onStartBar, onFollowChange }: CueMapProps) {
  const copy = useCopy();
  const overviewStatic = useRef<HTMLCanvasElement | null>(null);
  const overviewOverlay = useRef<HTMLCanvasElement | null>(null);
  const mapStatic = useRef<HTMLCanvasElement | null>(null);
  const mapOverlay = useRef<HTMLCanvasElement | null>(null);
  const [hoverStep, setHoverStep] = useState<number | null>(null);
  // the panel is tall by nature; collapsing it hands the space back to the stage
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) === '1'; } catch { return false; }
  });
  const toggleCollapsed = () => {
    setCollapsed((value) => {
      const next = !value;
      try { localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0'); } catch { /* preference only */ }
      return next;
    });
  };
  const viewBars = 8;

  const metrics = useMemo(() => createMusicGrid(rhythm), [rhythm]);
  const [sizeVersion, resize] = useState(0);
  useEffect(() => {
    const observer = new ResizeObserver(() => resize(value => value + 1));
    for (const ref of [overviewStatic, mapStatic]) if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [metrics.available]);
  const { values, rawByStep } = useMemo(() => stepValues(rhythm, metrics), [rhythm, metrics]);
  const duration = Number(rhythm.source?.duration ?? 0) || 1;

  /* ---------------- overview: static ---------------- */

  useEffect(() => {
    const canvas = overviewStatic.current;
    if (!canvas) return;
    const context = fitCanvas(canvas, OVERVIEW_W, OVERVIEW_H);
    if (!context) return;
    const width = OVERVIEW_W;
    const height = OVERVIEW_H;
    context.fillStyle = PAPER;
    context.fillRect(0, 0, width, height);

    const inner = width - LEFT - RIGHT;
    const at = (t: number) => LEFT + Math.min(1, Math.max(0, t / duration)) * inner;
    const windowStart = metrics.timeAtStep((startBar - 1) * metrics.subdivision);
    const windowEnd = metrics.timeAtStep((startBar - 1 + viewBars) * metrics.subdivision);

    const segments = rhythm.patterns?.segments ?? [];
    const families = [...new Set(segments.map((segment) => segment.family))];
    segments.forEach((segment) => {
      const left = at(segment.start_time);
      const right = at(segment.end_time);
      if (right - left < 1) return;
      context.fillStyle = FAMILY_TINT[Math.max(0, families.indexOf(segment.family)) % FAMILY_TINT.length];
      context.fillRect(left, 6, right - left, 22);
      context.strokeStyle = LINE;
      context.lineWidth = 1;
      context.strokeRect(left + 0.5, 6.5, Math.max(1, right - left - 1), 21);
      if (right - left > 30) {
        context.fillStyle = INK;
        context.font = '600 8px "Geist Mono", ui-monospace, monospace';
        context.fillText((segment.display_label ?? segment.family).toUpperCase().slice(0, 10), left + 4, 17);
        if (segment.start_bar != null && segment.end_bar != null && right - left > 46) {
          context.fillStyle = MID;
          context.fillText(`${String(segment.start_bar).padStart(2, '0')}—${String(segment.end_bar).padStart(2, '0')}`, left + 4, 26);
        }
      }
    });
    for (const boundary of rhythm.patterns?.boundaries ?? []) {
      const novelty = clamp01(boundary.novelty ?? 0.5);
      const x = at(boundary.time);
      context.strokeStyle = INK;
      context.globalAlpha = 0.28 + novelty * 0.5;
      context.lineWidth = 1 + novelty;
      context.beginPath();
      context.moveTo(x, 6 - 2 - novelty * 4);
      context.lineTo(x, 28);
      context.stroke();
      context.globalAlpha = 1;
    }

    const energy = rhythm.energy;
    if (energy?.bands) {
      const samples = Math.max(100, Math.floor(width / 2));
      const lanes: [string, number, string][] = [['low', 40, INK], ['mid', 58, MID], ['high', 76, ACCENT]];
      for (const [band, laneY, color] of lanes) {
        const series = energy.bands[band];
        if (!series?.length) continue;
        context.strokeStyle = color;
        context.globalAlpha = 0.17;
        context.lineWidth = 0.6;
        context.beginPath();
        context.moveTo(LEFT, laneY);
        context.lineTo(width - RIGHT, laneY);
        context.stroke();
        context.globalAlpha = 0.72;
        context.font = '600 8px "Geist Mono", ui-monospace, monospace';
        context.fillText(band.toUpperCase(), 8, laneY - 4);
        context.globalAlpha = band === 'high' ? 0.74 : 0.58;
        context.lineWidth = band === 'low' ? 1.3 : 1;
        context.beginPath();
        for (let i = 0; i < samples; i++) {
          const t = (i / (samples - 1)) * duration;
          const index = Math.min(series.length - 1, Math.max(0, Math.round((t - (energy.start ?? 0)) * energy.fps)));
          const x = LEFT + (i / (samples - 1)) * inner;
          const y = laneY - Math.sqrt(clamp01(series[index])) * 10;
          if (i === 0) context.moveTo(x, y); else context.lineTo(x, y);
        }
        context.stroke();
        context.globalAlpha = 1;
      }
    }

    context.strokeStyle = LINE;
    context.globalAlpha = 0.85;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(LEFT, 88);
    context.lineTo(width - RIGHT, 88);
    context.stroke();
    context.globalAlpha = 1;
    for (const onset of rhythm.onsets ?? []) {
      if (!(onset.accent || onset.strength >= 0.72)) continue;
      const x = at(onset.time);
      context.strokeStyle = onset.accent ? ACCENT : INK;
      context.globalAlpha = 0.35 + clamp01(onset.strength) * 0.55;
      context.lineWidth = onset.accent ? 1.5 : 1;
      context.beginPath();
      context.moveTo(x, 86);
      context.lineTo(x, 86 - clamp01(onset.strength) * 5);
      context.stroke();
      context.globalAlpha = 1;
    }

    for (let bar = 1; bar <= metrics.bars; bar += 8) {
      const x = at(metrics.timeAtStep((bar - 1) * metrics.subdivision));
      context.strokeStyle = LINE;
      context.globalAlpha = 0.55;
      context.beginPath();
      context.moveTo(x, 26);
      context.lineTo(x, height - 12);
      context.stroke();
      context.globalAlpha = 1;
      context.fillStyle = MID;
      context.font = '8px "Geist Mono", ui-monospace, monospace';
      context.fillText(String(bar), x + 3, height - 4);
    }

    context.fillStyle = ACCENT;
    context.globalAlpha = 0.055;
    context.fillRect(at(windowStart), 26, Math.max(2, at(windowEnd) - at(windowStart)), height - 34);
    context.globalAlpha = 0.9;
    context.strokeStyle = ACCENT;
    context.lineWidth = 1.5;
    context.strokeRect(at(windowStart), 26, Math.max(2, at(windowEnd) - at(windowStart)), height - 34);
    context.globalAlpha = 1;
  }, [rhythm, startBar, metrics, duration, viewBars, sizeVersion]);

  /* ---------------- overview: overlay (playhead only) ---------------- */

  useEffect(() => {
    const canvas = overviewOverlay.current;
    if (!canvas) return;
    const context = fitCanvas(canvas, OVERVIEW_W, OVERVIEW_H);
    if (!context) return;
    context.clearRect(0, 0, OVERVIEW_W, OVERVIEW_H);
    const inner = OVERVIEW_W - LEFT - RIGHT;
    const x = LEFT + Math.min(1, Math.max(0, time / duration)) * inner;
    context.strokeStyle = ACCENT;
    context.lineWidth = 1.7;
    context.beginPath();
    context.moveTo(x, 1);
    context.lineTo(x, OVERVIEW_H - 3);
    context.stroke();
    context.beginPath();
    context.moveTo(x - 4, 1);
    context.lineTo(x + 4, 1);
    context.lineTo(x, 6);
    context.closePath();
    context.fillStyle = ACCENT;
    context.fill();
  }, [time, duration]);

  /* ---------------- 8-bar map: static ---------------- */

  useEffect(() => {
    const canvas = mapStatic.current;
    if (!canvas) return;
    const context = fitCanvas(canvas, MAP_W, MAP_H);
    if (!context) return;
    const width = MAP_W;
    const height = MAP_H;
    context.fillStyle = PAPER;
    context.fillRect(0, 0, width, height);

    const columns = viewBars * metrics.subdivision;
    const cellWidth = (width - LEFT - RIGHT) / columns;
    const startStep = (startBar - 1) * metrics.subdivision;
    const stepAt = (column: number) => startStep + column;

    for (let bar = 0; bar < viewBars; bar++) {
      const barX = LEFT + bar * metrics.subdivision * cellWidth;
      context.fillStyle = BAR_FILL[bar % 2];
      context.fillRect(barX, TOP, metrics.subdivision * cellWidth, GRID_BOTTOM - TOP);
      context.fillStyle = bar === 0 ? ACCENT : INK;
      context.font = '700 10px "Geist Mono", ui-monospace, monospace';
      context.fillText(`BAR ${String(startBar + bar).padStart(2, '0')}`, barX + 7, 10);
      context.fillStyle = MID;
      context.font = '8px "Geist Mono", ui-monospace, monospace';
      for (let beat = 1; beat <= 4; beat++) {
        context.fillText(String(beat), barX + (beat * metrics.subdivision * cellWidth) / 4 + 3, 22);
      }
    }
    for (let column = 0; column <= columns; column++) {
      const isBar = column % metrics.subdivision === 0;
      const isBeat = column % (metrics.subdivision / 4) === 0;
      if (!isBar && !isBeat) continue;
      const x = LEFT + column * cellWidth;
      context.strokeStyle = isBar ? INK : '#aaa89f';
      context.globalAlpha = isBar ? 0.5 : 0.26;
      context.lineWidth = isBar ? 1.15 : 0.7;
      context.beginPath();
      context.moveTo(x, TOP);
      context.lineTo(x, GRID_BOTTOM);
      context.stroke();
      context.globalAlpha = 1;
    }

    ROWS.forEach((row, index) => {
      const y = TOP + ROW_H * index;
      const baseline = y + 22;
      context.strokeStyle = index === 0 ? INK : LINE;
      context.globalAlpha = index === 0 ? 1 : 0.75;
      context.lineWidth = index === 0 ? 1 : 0.75;
      context.beginPath();
      context.moveTo(LEFT, y);
      context.lineTo(width - RIGHT, y);
      context.stroke();
      context.globalAlpha = 1;

      const highlight = row === 'high' || row === 'accent';
      context.fillStyle = highlight ? ACCENT : INK;
      context.font = '700 9px "Geist Mono", ui-monospace, monospace';
      context.fillText(LABELS[index], 16, y + 11);
      context.fillStyle = MID;
      context.font = '7.5px "Geist Mono", ui-monospace, monospace';
      context.fillText(HINTS[index], 16, y + 21);

      context.strokeStyle = row === 'mid' ? MID : highlight ? ACCENT : INK;
      context.globalAlpha = 0.18;
      context.lineWidth = 0.65;
      context.beginPath();
      context.moveTo(LEFT, baseline);
      context.lineTo(width - RIGHT, baseline);
      context.stroke();
      context.globalAlpha = 1;

      const series = values[row];
      const valueAt = (column: number) => series[Math.min(series.length - 1, Math.max(0, stepAt(column)))] ?? 0;
      const curveY = (column: number) => baseline - (3 + valueAt(column) * (ROW_H - 10));

      if (row === 'accent') {
        for (let column = 0; column < columns; column++) {
          const value = valueAt(column);
          if (value <= 0) continue;
          const x = LEFT + (column + 0.5) * cellWidth;
          const cy = baseline - 8 - value * 7;
          const size = 2 + value * 5;
          context.globalAlpha = 0.35 + value * 0.65;
          context.fillStyle = ACCENT;
          context.beginPath();
          context.moveTo(x, cy - size);
          context.lineTo(x + size, cy);
          context.lineTo(x, cy + size);
          context.lineTo(x - size, cy);
          context.closePath();
          context.fill();
          context.globalAlpha = 0.35 + value * 0.55;
          context.strokeStyle = ACCENT;
          context.lineWidth = 1;
          context.beginPath();
          context.moveTo(x, baseline);
          context.lineTo(x, baseline - 6 - value * 8);
          context.stroke();
          context.globalAlpha = 1;
        }
        return;
      }

      const gradient = context.createLinearGradient(0, y + 8, 0, baseline);
      gradient.addColorStop(0, row === 'high' ? 'rgba(117,103,232,0.14)' : 'rgba(23,23,25,0.09)');
      gradient.addColorStop(1, 'rgba(255,255,255,0)');
      context.fillStyle = gradient;
      context.beginPath();
      context.moveTo(LEFT, baseline);
      for (let column = 0; column < columns; column++) context.lineTo(LEFT + (column + 0.5) * cellWidth, curveY(column));
      context.lineTo(width - RIGHT, baseline);
      context.closePath();
      context.fill();

      context.strokeStyle = row === 'high' ? ACCENT : row === 'mid' ? MID : INK;
      context.lineWidth = row === 'all' ? 1.35 : 1;
      context.globalAlpha = row === 'high' ? 0.8 : 0.62;
      context.beginPath();
      for (let column = 0; column < columns; column++) {
        const x = LEFT + (column + 0.5) * cellWidth;
        if (column === 0) context.moveTo(x, curveY(column));
        else context.lineTo(x, curveY(column));
      }
      context.stroke();
      context.globalAlpha = 1;
    });

    for (let column = 0; column < columns; column++) {
      const step = stepAt(column);
      if (!rawByStep.has(step)) continue;
      const epsilon = metrics.stepAtTime(rawByStep.get(step)!) - (step + 0.5);
      if (Math.abs(epsilon) < 0.02) continue;
      const rawX = LEFT + (column + 0.5 + epsilon) * cellWidth;
      const snappedX = LEFT + (column + 0.5) * cellWidth;
      context.strokeStyle = ACCENT;
      context.globalAlpha = 0.6;
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(rawX, 24);
      context.lineTo(snappedX, 24);
      context.stroke();
      context.globalAlpha = 0.9;
      context.fillStyle = ACCENT;
      context.fillRect(rawX - 1, 18, 2, 6);
      context.globalAlpha = 1;
    }

    const graphTop = GRID_BOTTOM + 12;
    const graphHeight = Math.max(22, height - graphTop - 10);
    const centreY = graphTop + graphHeight * 0.56;
    context.fillStyle = INK;
    context.font = '700 9px "Geist Mono", ui-monospace, monospace';
    context.fillText('MOTION CUES', 16, graphTop + 9);
    context.fillStyle = MID;
    context.font = '8px "Geist Mono", ui-monospace, monospace';
    context.fillText('pulse · flow · flash', 16, graphTop + 21);
    context.strokeStyle = LINE;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(LEFT, centreY);
    context.lineTo(width - RIGHT, centreY);
    context.stroke();
    for (let bar = 0; bar <= viewBars; bar++) {
      const x = LEFT + bar * metrics.subdivision * cellWidth;
      context.strokeStyle = INK;
      context.globalAlpha = 0.35;
      context.beginPath();
      context.moveTo(x, graphTop);
      context.lineTo(x, height - 12);
      context.stroke();
      context.globalAlpha = 1;
    }
    for (let column = 0; column < columns; column++) {
      const step = stepAt(column);
      const all = values.all[step] ?? 0;
      if (all <= 0.02) continue;
      const x = LEFT + (column + 0.5) * cellWidth;
      const low = values.low[step] ?? 0;
      const mid = values.mid[step] ?? 0;
      const high = values.high[step] ?? 0;
      const driver = low >= mid && low >= high ? 'low' : high >= mid ? 'high' : 'mid';
      const color = driver === 'high' ? ACCENT : driver === 'mid' ? MID : INK;
      const cueTop = centreY - 6 - all * graphHeight * 0.3;
      context.strokeStyle = color;
      context.globalAlpha = 0.3 + all * 0.7;
      context.lineWidth = driver === 'low' ? 2.2 : 1.2;
      context.beginPath();
      context.moveTo(x, centreY);
      context.lineTo(x, cueTop);
      context.stroke();
      if (driver === 'low') {
        context.beginPath();
        context.arc(x, cueTop, 2 + all * 4, 0, Math.PI * 2);
        context.stroke();
      } else if (driver === 'high') {
        context.beginPath();
        context.moveTo(x - 4, cueTop);
        context.lineTo(x + 4, cueTop);
        context.moveTo(x, cueTop - 4);
        context.lineTo(x, cueTop + 4);
        context.stroke();
      } else {
        context.fillStyle = color;
        context.fillRect(x - 1.5, cueTop - 3, 3, 6);
      }
      context.globalAlpha = 1;
    }
    context.strokeStyle = INK;
    context.globalAlpha = 0.72;
    context.beginPath();
    context.moveTo(LEFT, GRID_BOTTOM);
    context.lineTo(width - RIGHT, GRID_BOTTOM);
    context.stroke();
    context.globalAlpha = 1;
  }, [rhythm, startBar, metrics, values, rawByStep, viewBars, sizeVersion]);

  /* ---------------- 8-bar map: overlay (hover + playhead) ---------------- */

  useEffect(() => {
    const canvas = mapOverlay.current;
    if (!canvas) return;
    const context = fitCanvas(canvas, MAP_W, MAP_H);
    if (!context) return;
    context.clearRect(0, 0, MAP_W, MAP_H);
    const columns = viewBars * metrics.subdivision;
    const cellWidth = (MAP_W - LEFT - RIGHT) / columns;
    const startStep = (startBar - 1) * metrics.subdivision;
    if (hoverStep !== null) {
      const column = hoverStep - startStep;
      if (column >= 0 && column < columns) {
        context.strokeStyle = INK;
        context.globalAlpha = 0.5;
        context.lineWidth = 1;
        context.strokeRect(LEFT + column * cellWidth + 0.5, TOP + 0.5, cellWidth - 1, GRID_BOTTOM - TOP - 1);
        context.globalAlpha = 1;
      }
    }
    const playColumn = metrics.stepAtTime(time) - startStep;
    if (playColumn >= 0 && playColumn <= columns) {
      const x = LEFT + playColumn * cellWidth;
      context.strokeStyle = ACCENT;
      context.lineWidth = 2;
      context.beginPath();
      context.moveTo(x, 2);
      context.lineTo(x, MAP_H - 5);
      context.stroke();
      context.beginPath();
      context.moveTo(x - 5, 2);
      context.lineTo(x + 5, 2);
      context.lineTo(x, 8);
      context.closePath();
      context.fillStyle = ACCENT;
      context.fill();
    }
  }, [time, hoverStep, startBar, metrics, viewBars, sizeVersion]);

  const stepFromEvent = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const columns = viewBars * metrics.subdivision;
    const cellWidth = (MAP_W - LEFT - RIGHT) / columns;
    const column = Math.floor((virtualX(event.clientX, rect, MAP_W, MAP_H) - LEFT) / cellWidth);
    if (column < 0 || column >= columns) return null;
    return { step: (startBar - 1) * metrics.subdivision + column };
  };

  const currentBar = metrics.barAtTime(time) ?? 0;

  return (
    <section className={`cm${collapsed ? ' collapsed' : ''}`} aria-label={copy.cue.label}>
      <header className="cm-head">
        <div>
          <span className="cm-eyebrow">BEATSCOPE / ANALYSIS</span>
          <h2>{copy.cue.overview}</h2>
        </div>
        {metrics.available && <span className="cm-meta">
          {copy.cue.meta(Number(rhythm.tempo?.global_bpm ?? 0).toFixed(1), metrics.bars, Math.max(1, Math.min(metrics.bars, currentBar)))}
        </span>}
        <button
          className="tbtn cm-toggle"
          aria-expanded={!collapsed}
          onClick={toggleCollapsed}
        >
          {collapsed ? copy.cue.expand : copy.cue.collapse}
        </button>
      </header>
      {/* the collapsible half: the wrapper animates its height, the inner
          layer carries the mask so the plots slide out from under the header
          instead of being cut off */}
      <div className="cm-body">
        <div className="cm-body-inner">
          <div className="cm-stack cm-stack-overview">
            <canvas
              ref={overviewStatic}
              aria-label={copy.cue.overviewLabel}
              onClick={(event) => {
                const rect = event.currentTarget.getBoundingClientRect();
                const fraction = (virtualX(event.clientX, rect, OVERVIEW_W, OVERVIEW_H) - LEFT) / (OVERVIEW_W - LEFT - RIGHT);
                seek(Math.max(0, Math.min(1, fraction)) * duration);
                onFollowChange(true);
              }}
            />
            <canvas ref={overviewOverlay} aria-hidden="true" />
          </div>
          {metrics.available && <><div className="cm-tools">
            <span>
              {copy.cue.barsRange(String(startBar).padStart(2, '0'), String(Math.min(startBar + viewBars - 1, metrics.bars)).padStart(2, '0'), metrics.bars)}
            </span>
            <div>
              <button className="tbtn" disabled={startBar <= 1} onClick={() => onStartBar(Math.max(1, startBar - viewBars))}>
                {copy.cue.prev}
              </button>
              <button className="tbtn" onClick={() => onFollowChange(true)}>{copy.cue.follow}</button>
              <button
                className="tbtn"
                disabled={startBar + viewBars > metrics.bars}
                onClick={() => onStartBar(startBar + viewBars)}
              >
                {copy.cue.next}
              </button>
            </div>
          </div>
          <div className="cm-stack cm-stack-map">
            <canvas
              ref={mapStatic}
              aria-label={copy.cue.mapLabel}
              onMouseMove={(event) => {
                const hit = stepFromEvent(event);
                setHoverStep(hit ? hit.step : null);
              }}
              onMouseLeave={() => setHoverStep(null)}
              onClick={(event) => {
                const hit = stepFromEvent(event);
                if (!hit) return;
                seek(rawByStep.get(hit.step) ?? metrics.timeAtStep(hit.step));
              }}
            />
            <canvas ref={mapOverlay} aria-hidden="true" />
          </div></>}
        </div>
      </div>
    </section>
  );
}
