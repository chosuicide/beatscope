import { gridPosition, metrics } from './grid.js';
import { trackForProject } from '../runtime/runtime.js';
import { createVisualProfile } from '../runtime/visual-profile.js';
import { RING_DEFS, RING_SLOTS, findRingCrossings, ringPointLocal } from './particle-geometry.js';
import { CAMERA_Z } from './particle-field.js';

const ROWS = ['all', 'low', 'mid', 'high', 'accent'];
const LABELS = { all: 'IMPACT', low: 'LOW / SCALE', mid: 'MID / FLOW', high: 'HIGH / FLASH', accent: 'ACCENT / BLOOM' };
const ROW_HINTS = { all: 'transient', low: 'size + weight', mid: 'surface motion', high: 'light + detail', accent: 'hero event' };
const INK = '#171713';
const PAPER = '#f4f3ee';
const SURFACE = '#fbfaf6';
const MUTED = '#74736b';
const LINE = '#d6d4ca';
const ACCENT = '#c65032';

const clamp = (value, min = 0, max = 1) => Math.max(min, Math.min(max, Number(value) || 0));
const mix = (a, b, amount) => a + (b - a) * amount;
const fract = (value) => value - Math.floor(value);
const smoothstep = (value) => {
  const t = clamp(value);
  return t * t * (3 - 2 * t);
};
const hash01 = (index, salt = 0) => fract(Math.sin(index * 12.9898 + salt * 78.233) * 43758.5453123);

export function resizeCanvas(canvas, cssWidth, cssHeight, dprCapOverride = null) {
  // Non-stage canvases keep their historical 2x cap; the visual-stage stack
  // receives its tier's cap from the quality controller (plan section 7.3).
  const dprLimit = dprCapOverride ?? (canvas.id === 'visualStage' || canvas.id === 'particleStage' ? 1 : 2);
  const dpr = Math.min(window.devicePixelRatio || 1, dprLimit);
  const physicalWidth = Math.round(cssWidth * dpr);
  const physicalHeight = Math.round(cssHeight * dpr);
  if (canvas.width !== physicalWidth || canvas.height !== physicalHeight) {
    canvas.width = physicalWidth;
    canvas.height = physicalHeight;
  }
  const styleWidth = `${cssWidth}px`;
  const styleHeight = `${cssHeight}px`;
  if (canvas.style.width !== styleWidth) canvas.style.width = styleWidth;
  if (canvas.style.height !== styleHeight) canvas.style.height = styleHeight;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width: cssWidth, height: cssHeight };
}

function line(ctx, x1, y1, x2, y2, color = LINE, width = 1, alpha = 1) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.globalAlpha = alpha;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  ctx.restore();
}

function text(ctx, value, x, y, options = {}) {
  ctx.save();
  ctx.fillStyle = options.color || INK;
  ctx.font = options.font || '11px "SFMono-Regular", Consolas, monospace';
  ctx.textAlign = options.align || 'left';
  ctx.textBaseline = options.baseline || 'alphabetic';
  ctx.globalAlpha = options.alpha ?? 1;
  ctx.fillText(String(value), x, y);
  ctx.restore();
}

function energyAt(project, time, name = 'all') {
  return trackForProject(project).energyAt(time, name);
}

export function playbackState(project, time) {
  const signal = trackForProject(project).at(time);
  return {
    time,
    bar: signal.bar,
    beat: signal.beat,
    beatPhase: signal.beatPhase,
    barPhase: signal.barPhase,
    // Playback compression: the runtime reports raw energy; the visual
    // layer consumes perceptual (sqrt) levels.
    low: Math.sqrt(signal.low),
    mid: Math.sqrt(signal.mid),
    high: Math.sqrt(signal.high),
    all: Math.sqrt(signal.all),
    onset: signal.onset.value,
    accent: signal.accent ? signal.accent.value : 0,
    onsetAge: signal.onset.age,
    beatPulse: Math.exp(-signal.beatPhase * 7),
    section: signal.section,
  };
}

// Motion-tier budgets live in the shared visual profile; one profile per
// project object, built over the shared runtime track. Exported so the
// visual-stage controller — not the drawing layers — samples it once per
// frame (plan section 3.3: one already-computed frame object per layer).
const visualProfileCache = new WeakMap();

export function visualProfileFor(project) {
  if (!visualProfileCache.has(project)) {
    visualProfileCache.set(project, createVisualProfile(trackForProject(project)));
  }
  return visualProfileCache.get(project);
}

const sphereCache = new Map();

function spherePoints(count) {
  if (sphereCache.has(count)) return sphereCache.get(count);
  const points = [];
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  for (let index = 0; index < count; index += 1) {
    const y = 1 - 2 * (index + .5) / count;
    const radius = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = index * goldenAngle;
    const seedA = hash01(index, 1.17);
    const seedB = hash01(index, 4.63);
    const seedC = hash01(index, 8.91);
    const freeY = seedA * 2 - 1;
    const freeRadius = Math.sqrt(Math.max(0, 1 - freeY * freeY));
    const freeAngle = seedB * Math.PI * 2;
    const freeScale = 1.12 + seedC * .62;
    points.push({
      x: Math.cos(angle) * radius,
      y,
      z: Math.sin(angle) * radius,
      freeX: Math.cos(freeAngle) * freeRadius * freeScale,
      freeY: freeY * freeScale,
      freeZ: Math.sin(freeAngle) * freeRadius * freeScale,
      seedA,
      seedB,
      seedC,
      phase: seedB * Math.PI * 2,
      index,
    });
  }
  sphereCache.set(count, points);
  return points;
}

function rotatePoint(point, angleX, angleY) {
  const cosY = Math.cos(angleY);
  const sinY = Math.sin(angleY);
  const x1 = point.x * cosY + point.z * sinY;
  const z1 = -point.x * sinY + point.z * cosY;
  const cosX = Math.cos(angleX);
  const sinX = Math.sin(angleX);
  return { x: x1, y: point.y * cosX - z1 * sinX, z: point.y * sinX + z1 * cosX };
}

// --- Orbit rings (layer 3; definitions live in particle-geometry.js) --------
const RING_CSS_COLORS = RING_DEFS.map((def) => `rgb(${Math.round(def.color[0] * 255)}, ${Math.round(def.color[1] * 255)}, ${Math.round(def.color[2] * 255)})`);

/** Delayed beat ripple shared by WebGL parity markers and Canvas fallback. */
function ringRipple(frame, ringIndex) {
  const delay = .12 + .16 * ringIndex;
  return clamp((Number(frame.beatWave) || 0) * 1.8
    * Math.exp(-Math.pow(((Number(frame.waveProgress) || 0) - delay) * 8.5, 2)));
}

/** Canvas-compat ring dots: same RING_DEFS, seeded dashes, slow revolution. */
function drawFallbackRings(ctx, frame, layout, baseRadius, angleX, angleY, reducedMotion) {
  const time = frame.signal.time;
  const revolution = reducedMotion ? 0 : 1;
  for (let r = 0; r < RING_DEFS.length; r += 1) {
    const def = RING_DEFS[r];
    const pulse = ringRipple(frame, r);
    const rippleScale = 1 + pulse * (.045 + .015 * r);
    for (let slot = 0; slot < RING_SLOTS; slot += 1) {
      if (hash01(slot * 7.31 + r * 131.7, 2.17) < .04) continue;
      const theta = ((slot + .5) / RING_SLOTS) * Math.PI * 2
        + (hash01(slot * 3.7 + r * 17.3, 5.19) - .5) * ((Math.PI * 2 / RING_SLOTS) * .55)
        + def.speed * time * revolution;
      const bandCoordinate = (hash01(slot * 4.91 + r * 83.2, 7.13) - .5) * 2;
      const bandCore = 1 - smoothstep(Math.max(0, (Math.abs(bandCoordinate) - .08) / .92));
      const bandOffset = bandCoordinate * (.060 + .035 * pulse);
      const local = ringPointLocal(def, theta)
        .map((value) => value * rippleScale * (1 + bandOffset / def.a));
      const rotated = rotatePoint({ x: local[0], y: local[1], z: local[2] }, angleX, angleY);
      const perspective = 3.15 / (3.15 - rotated.z);
      const depth = clamp((rotated.z + 2.3) / 4.6);
      ctx.beginPath();
      ctx.arc(
        layout.centreX + rotated.x * baseRadius * perspective,
        layout.centreY + rotated.y * baseRadius * perspective,
        (.75 + bandCore * 1.15 + depth * .55) * (1 + pulse * .42), 0, Math.PI * 2,
      );
      ctx.fillStyle = RING_CSS_COLORS[r];
      ctx.globalAlpha = clamp((.08 + bandCore * .40 + depth * .14) * (1 + pulse * .52));
      ctx.fill();
    }
  }
  ctx.globalAlpha = 1;
}

/** ◉ nodes where each ring's dashed path crosses the screen vertical. */
function drawOrbitRingNodes(ctx, frame, layout) {
  const time = Number(frame.time) || 0;
  const rotationScale = mix(1, .22, clamp(frame.hold));
  const yaw = (0.09 * time + 0.035 * Math.sin(0.17 * time)) * rotationScale;
  const pitch = -.2 + 0.045 * Math.sin(0.13 * time);
  const roll = 0.025 * Math.sin(0.11 * time) * rotationScale;
  for (let r = 0; r < RING_DEFS.length; r += 1) {
    const pulse = ringRipple(frame, r);
    const scale = 1 + pulse * (.045 + .015 * r);
    for (const world of findRingCrossings(RING_DEFS[r], yaw, pitch, roll, scale)) {
      const persp = CAMERA_Z / Math.max(0.1, CAMERA_Z - world[2]);
      const x = layout.centreX + world[0] * layout.baseRadius * persp;
      const y = layout.centreY - world[1] * layout.baseRadius * persp;
      const depth = clamp((world[2] + 2.3) / 4.6);
      const radius = 2.3 + depth * 2.3;
      ctx.save();
      ctx.strokeStyle = RING_CSS_COLORS[r];
      ctx.fillStyle = RING_CSS_COLORS[r];
      ctx.globalAlpha = .3 + depth * .45;
      ctx.lineWidth = depth > .55 ? 1.4 : 1;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x, y, Math.max(1, radius * .36), 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }
}

function drawFrequencyLine(ctx, project, signal, width, baseY, band, color, amplitude, lineWidth, alpha, bounds = null) {
  const margin = Math.max(24, width * .035);
  const left = bounds?.left ?? margin;
  const right = bounds?.right ?? width - margin;
  const innerWidth = right - left;
  const samples = width < 700 ? 48 : width < 1100 ? 64 : 80;
  const points = [];
  for (let index = 0; index <= samples; index += 1) {
    const ratio = index / samples;
    const sampleTime = signal.time + (ratio - .5) * 6;
    const value = Math.sqrt(energyAt(project, sampleTime, band));
    const harmonic = Math.sin(index * .42 + signal.time * (band === 'high' ? 4.2 : band === 'mid' ? 2.1 : .9));
    points.push({
      x: left + ratio * innerWidth,
      y: baseY - value * amplitude * (.76 + harmonic * .24),
    });
  }

  ctx.save();
  line(ctx, left, baseY, right, baseY, color, .65, .16);

  // A shallow wash makes each band read as a chart without turning it into a panel.
  const wash = ctx.createLinearGradient(0, baseY - amplitude, 0, baseY);
  wash.addColorStop(0, color === ACCENT ? 'rgba(198,80,50,.075)' : 'rgba(24,25,21,.045)');
  wash.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.beginPath();
  ctx.moveTo(points[0].x, baseY);
  for (const point of points) ctx.lineTo(point.x, point.y);
  ctx.lineTo(points[points.length - 1].x, baseY);
  ctx.closePath();
  ctx.fillStyle = wash;
  ctx.fill();

  ctx.beginPath();
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index];
    if (index === 0) ctx.moveTo(point.x, point.y); else ctx.lineTo(point.x, point.y);
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.globalAlpha = alpha;
  ctx.stroke();

  const current = points[Math.floor(points.length / 2)];
  ctx.globalAlpha = 1;
  ctx.fillStyle = PAPER;
  ctx.beginPath();
  ctx.arc(current.x, current.y, 4.1, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.25;
  ctx.beginPath();
  ctx.arc(current.x, current.y, 2.7, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();

  const value = Number(signal[band] || 0).toFixed(2);
  text(ctx, band.toUpperCase(), left, baseY + 14, { color, alpha: .72, font: '9px monospace' });
  text(ctx, value, right, baseY + 14, { color, alpha: .72, font: '9px monospace', align: 'right' });
}

function drawArcTicks(ctx, cx, cy, radius, signal) {
  ctx.save();
  for (let index = 0; index < 96; index += 1) {
    const angle = -Math.PI * .84 + index / 95 * Math.PI * 1.68;
    const major = index % 8 === 0;
    const active = Math.abs(index / 95 - signal.barPhase) < .025;
    const inner = radius + (major ? 13 : 18);
    const outer = radius + (major ? 28 : 23);
    line(
      ctx,
      cx + Math.cos(angle) * inner,
      cy + Math.sin(angle) * inner,
      cx + Math.cos(angle) * outer,
      cy + Math.sin(angle) * outer,
      active ? ACCENT : INK,
      active ? 2.2 : major ? 1 : .65,
      active ? .9 : major ? .32 : .16,
    );
  }

  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 1.4;
  ctx.globalAlpha = .22 + signal.beatPulse * .36;
  ctx.beginPath();
  ctx.arc(cx, cy, radius + 34, Math.PI * .12, Math.PI * .38);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(cx, cy, radius + 34, Math.PI * .62, Math.PI * .88);
  ctx.stroke();
  ctx.restore();
}

function drawMetricBox(ctx, x, y, width, height, label, value, detail, accent = false, meter = 0) {
  const bracket = 9;
  const color = accent ? ACCENT : INK;
  line(ctx, x, y, x + bracket, y, color, 1, .68);
  line(ctx, x, y, x, y + bracket, color, 1, .68);
  line(ctx, x + width - bracket, y, x + width, y, color, 1, .68);
  line(ctx, x + width, y, x + width, y + bracket, color, 1, .68);
  line(ctx, x, y + height - bracket, x, y + height, color, 1, .68);
  line(ctx, x, y + height, x + bracket, y + height, color, 1, .68);
  line(ctx, x + width, y + height - bracket, x + width, y + height, color, 1, .68);
  line(ctx, x + width - bracket, y + height, x + width, y + height, color, 1, .68);
  text(ctx, label, x + 12, y + 20, { color: accent ? ACCENT : MUTED, font: '700 8px monospace' });
  text(ctx, value, x + 12, y + 43, { color, font: '20px "Arial Narrow", sans-serif' });
  text(ctx, detail, x + 12, y + 59, { color: MUTED, font: '8px monospace' });
  const meterY = y + height - 15;
  line(ctx, x + 12, meterY, x + width - 12, meterY, LINE, 1, .9);
  line(ctx, x + 12, meterY, x + 12 + (width - 24) * clamp(meter), meterY, accent ? ACCENT : INK, 2, .85);
}

function drawSpectrumDeck(ctx, project, signal, width, top, bottom, margin) {
  const gap = 18;
  const panelWidth = (width - margin * 2 - gap * 2) / 3;
  const bands = [
    { key: 'low', title: 'SUB / BASS', range: '20Hz — 200Hz', color: ACCENT },
    { key: 'mid', title: 'BODY / MID', range: '200Hz — 2kHz', color: '#77756c' },
    { key: 'high', title: 'AIR / HIGH', range: '2kHz — 20kHz', color: '#e7903e' },
  ];
  ctx.save();
  ctx.strokeStyle = INK;
  ctx.globalAlpha = .42;
  ctx.strokeRect(margin, top, width - margin * 2, bottom - top);
  ctx.restore();

  for (let bandIndex = 0; bandIndex < bands.length; bandIndex += 1) {
    const band = bands[bandIndex];
    const x = margin + bandIndex * (panelWidth + gap);
    const value = clamp(signal[band.key]);
    if (bandIndex > 0) line(ctx, x - gap / 2, top + 14, x - gap / 2, bottom - 14, LINE, 1, .8);
    text(ctx, band.title, x + 14, top + 22, { color: INK, font: '700 9px monospace' });
    text(ctx, band.range, x + 14, top + 36, { color: MUTED, font: '8px monospace' });

    const chartTop = top + 46;
    const chartBottom = bottom - 18;
    const barCount = width < 700 ? 20 : 38;
    const available = panelWidth - 28;
    const barGap = 2;
    const barWidth = Math.max(1, (available - (barCount - 1) * barGap) / barCount);
    const curve = [];
    for (let index = 0; index < barCount; index += 1) {
      const ratio = index / Math.max(1, barCount - 1);
      const localTime = signal.time + (ratio - .5) * 1.6;
      const local = Math.sqrt(energyAt(project, localTime, band.key));
      const shape = .58 + .42 * Math.sin((ratio * 3.1 + bandIndex * .8) * Math.PI) ** 2;
      const shimmer = .82 + .18 * Math.sin(index * 1.73 + signal.time * (1.3 + bandIndex));
      const level = clamp((local * .72 + value * .28) * shape * shimmer);
      const barHeight = 5 + level * (chartBottom - chartTop - 5);
      const barX = x + 14 + index * (barWidth + barGap);
      const gradient = ctx.createLinearGradient(0, chartBottom, 0, chartBottom - barHeight);
      gradient.addColorStop(0, band.color === ACCENT ? 'rgba(198,80,50,.12)' : 'rgba(77,76,71,.12)');
      gradient.addColorStop(1, band.color);
      ctx.fillStyle = gradient;
      ctx.globalAlpha = .46 + level * .54;
      ctx.fillRect(barX, chartBottom - barHeight, barWidth, barHeight);
      curve.push({ x: barX + barWidth / 2, y: chartBottom - barHeight - 5 });
    }
    ctx.globalAlpha = .7;
    ctx.strokeStyle = band.color;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 5]);
    ctx.beginPath();
    curve.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }
}

function drawReactiveLight(ctx, cx, cy, radius, signal, motion, reducedMotion) {
  const flash = reducedMotion ? 0 : clamp(motion.burst * .34 + motion.hero);
  const breath = .1 + signal.low * .38 + motion.pulse * .1 + motion.turbulence * .08;
  const bloomRadius = radius * (1.05 + breath * .45 + flash * .38);
  const bloom = ctx.createRadialGradient(cx - radius * .18, cy - radius * .2, 0, cx, cy, bloomRadius);
  bloom.addColorStop(0, `rgba(255,255,244,${.74 + flash * .24})`);
  bloom.addColorStop(.18, `rgba(255,218,136,${.18 + breath * .3 + flash * .28})`);
  bloom.addColorStop(.52, `rgba(220,92,44,${.035 + flash * .16})`);
  bloom.addColorStop(1, 'rgba(198,80,50,0)');
  ctx.fillStyle = bloom;
  ctx.fillRect(cx - bloomRadius, cy - bloomRadius, bloomRadius * 2, bloomRadius * 2);

  if (flash > .025) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-.18 + Math.sin(signal.time * .7) * .08);
    const streak = ctx.createLinearGradient(-radius * 1.8, 0, radius * 1.8, 0);
    streak.addColorStop(0, 'rgba(198,80,50,0)');
    streak.addColorStop(.42, `rgba(255,157,85,${flash * .12})`);
    streak.addColorStop(.5, `rgba(255,247,210,${flash * .72})`);
    streak.addColorStop(.58, `rgba(255,157,85,${flash * .12})`);
    streak.addColorStop(1, 'rgba(198,80,50,0)');
    ctx.fillStyle = streak;
    ctx.fillRect(-radius * 1.8, -1.5 - flash * 3, radius * 3.6, 3 + flash * 6);
    ctx.rotate(Math.PI / 2);
    ctx.globalAlpha = .62;
    ctx.fillRect(-radius * 1.45, -1 - flash * 2, radius * 2.9, 2 + flash * 4);
    ctx.restore();
  }
}

function drawEmptyCanvas(ctx, width, height, label) {
  ctx.fillStyle = PAPER;
  ctx.fillRect(0, 0, width, height);
  line(ctx, 24, height / 2, width - 24, height / 2, LINE);
  text(ctx, label, 24, height / 2 - 14, { color: MUTED });
}

// --- Layered signal player (v0.6.1 plan section 3.3). -----------------------
//
// visual-stage.js samples the runtime and the compat profile ONCE per tick
// and hands every layer the same shared frame. renderVisualBackdrop paints
// the retained Canvas body beneath the chrome (only while the WebGL2 field
// is unavailable); renderVisualOverlay paints the instrument chrome above
// the particle layer. Neither layer resizes or clears the canvas — the
// stage controller owns sizing and the per-frame clear.

export function renderVisualBackdrop(canvas, state, frame) {
  const ctx = canvas.getContext ? canvas.getContext('2d') : null;
  if (!ctx || !state.project || !frame?.layout) return;
  const { layout, signal, motion } = frame;
  const reducedMotion = Boolean(frame.reducedMotion);
  ctx.save();
  // The relaxed field rect lets the orbit rings leave the main chart area;
  // without one (older layouts) the historical main-area clip applies.
  const fieldBox = layout.fieldRect || {
    left: layout.traceBounds.left,
    top: layout.mainTop,
    right: layout.traceBounds.right,
    bottom: layout.mainBottom,
  };
  ctx.beginPath();
  ctx.rect(fieldBox.left, fieldBox.top, fieldBox.right - fieldBox.left, fieldBox.bottom - fieldBox.top);
  ctx.clip();
  drawReactiveLight(ctx, layout.centreX, layout.centreY, layout.baseRadius, signal, motion, reducedMotion);
  drawArcTicks(ctx, layout.centreX, layout.centreY, layout.baseRadius, signal);
  renderCanvasParticleFallback(ctx, frame, layout);
  ctx.restore();
}

/**
 * Three-lobe light spill composited above the WebGL field. This deliberately
 * avoids a single circular halo: each soft ellipse belongs to one particle
 * lobe, while the active lobe receives the transient energy. The glow is
 * short-lived and spatially biased, so it reads as emitted light rather than
 * a decorative ring around the instrument.
 */
function drawParticleHalo(ctx, frame, layout) {
  const reduced = frame.reducedMotion ? 0.25 : 1;
  const impact = clamp(frame.impact) * reduced;
  const wave = clamp(frame.beatWave) * reduced;
  const expand = clamp(frame.beatExpand) * reduced;
  const split = clamp(frame.lobeSplit) * reduced;
  const anticipation = clamp(frame.anticipation) * reduced;
  const low = clamp(frame.low);
  const weights = Array.isArray(frame.lobeWeights) ? frame.lobeWeights : [1 / 3, 1 / 3, 1 / 3];
  const { centreX, centreY, baseRadius } = layout;
  const fieldBox = layout.fieldRect || {
    left: layout.traceBounds.left,
    top: layout.mainTop,
    right: layout.traceBounds.right,
    bottom: layout.mainBottom,
  };

  ctx.save();
  ctx.beginPath();
  ctx.rect(fieldBox.left, fieldBox.top, fieldBox.right - fieldBox.left, fieldBox.bottom - fieldBox.top);
  ctx.clip();

  for (let index = 0; index < 3; index += 1) {
    const angle = -Math.PI / 2 + index * Math.PI * 2 / 3;
    const selected = clamp(weights[index]);
    const energy = clamp(.045 + low * .075 + expand * .16 + split * .28 + wave * (.09 + selected * .16)
      + impact * (.16 + selected * .54));
    const pullIn = 1 - anticipation * (.10 + selected * .10);
    const offset = baseRadius * (.14 + split * .34 + impact * selected * .10) * pullIn;
    const radius = baseRadius * (.66 + expand * .28 + impact * selected * .38) * pullIn;
    const x = centreX + Math.cos(angle) * offset;
    const y = centreY + Math.sin(angle) * offset;

    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle + .22);
    ctx.scale(1, .62 + selected * .08);
    const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
    glow.addColorStop(0, `rgba(255,247,218,${energy * .72})`);
    glow.addColorStop(.26, `rgba(240,154,94,${energy * .38})`);
    glow.addColorStop(.62, `rgba(198,80,50,${energy * .13})`);
    glow.addColorStop(1, 'rgba(198,80,50,0)');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(0, 0, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  // A compact hot core appears on the transient, then disappears before the
  // lobe spill finishes. It supplies a clear strike without becoming a ring.
  const coreEnergy = clamp(low * .12 + wave * .22 + impact * .88);
  if (coreEnergy > .01) {
    const coreRadius = baseRadius * (.20 + impact * .20 + wave * .08);
    const core = ctx.createRadialGradient(centreX, centreY, 0, centreX, centreY, coreRadius);
    core.addColorStop(0, `rgba(255,255,240,${coreEnergy * .78})`);
    core.addColorStop(.22, `rgba(255,214,158,${coreEnergy * .44})`);
    core.addColorStop(.58, `rgba(198,80,50,${coreEnergy * .16})`);
    core.addColorStop(1, 'rgba(198,80,50,0)');
    ctx.fillStyle = core;
    ctx.beginPath();
    ctx.arc(centreX, centreY, coreRadius, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

/** Persistent black/white composition beneath the particle field. */
export function renderCanvasParticleFallback(ctx, frame, layout) {
  const signal = frame.signal;
  const motion = frame.motion;
  const reducedMotion = Boolean(frame.reducedMotion);
  const centreX = layout.centreX;
  const centreY = layout.centreY;
  const width = layout.width;
  // The per-beat breath matches the WebGL field: expand after the strike,
  // contract before the next beat (shared director frame field).
  const beatExpand = clamp(frame.beatExpand);
  const baseRadius = layout.baseRadius
    * (1 + signal.low * .07 + motion.pulse * .018 + motion.turbulence * .012 + beatExpand * .09);

  const angleY = signal.time * (.12 + signal.mid * .09);
  const angleX = -.22 + Math.sin(signal.time * .16) * .055;
  // Fixed fallback budget (plan section 9): at most 680 points, no shadow
  // blur in the loop; only the WebGL2 tiers adapt.
  const particleCount = width < 650 ? 480 : 680;
  const projected = [];
  for (const point of spherePoints(particleCount)) {
    const surfaceWave = Math.sin(point.y * 8 + point.x * 3.5 + signal.time * (1.35 + motion.turbulence * 1.4))
      * (signal.mid * .065 + motion.turbulence * .055);
    const highRipple = Math.sin(point.index * .31 + signal.time * 5.8) * signal.high * .022;
    const radialScale = 1 + surfaceWave + highRipple;
    const ambientDetach = clamp((point.seedA - .56) / .44) * (.42 + signal.mid * .28);
    const transientDetach = (motion.burst * .22 + motion.hero * .78) * (.12 + point.seedC * .88);
    const morph = smoothstep(clamp(ambientDetach + transientDetach));
    const orbitTime = signal.time * (.12 + point.seedB * .2);
    const freeTarget = rotatePoint(
      { x: point.freeX, y: point.freeY, z: point.freeZ },
      Math.sin(orbitTime + point.phase) * .16,
      orbitTime * .42 + Math.sin(point.phase) * .2,
    );
    const wander = .018 + point.seedC * .034 + morph * .055 + signal.high * .02 + motion.turbulence * .035;
    const driftX = (Math.sin(signal.time * (.31 + point.seedA * .24) + point.phase)
      + Math.sin(signal.time * .11 + point.seedC * 9.7) * .42) * wander;
    const driftY = (Math.cos(signal.time * (.27 + point.seedB * .21) + point.phase * 1.31)
      + Math.sin(signal.time * .14 + point.seedA * 7.1) * .38) * wander;
    const driftZ = (Math.sin(signal.time * (.22 + point.seedC * .19) + point.phase * .73)
      + Math.cos(signal.time * .09 + point.seedB * 11.2) * .36) * wander;
    const local = {
      x: mix(point.x * radialScale, freeTarget.x, morph) + driftX,
      y: mix(point.y * radialScale, freeTarget.y, morph) + driftY,
      z: mix(point.z * radialScale, freeTarget.z, morph) + driftZ,
    };
    const rotated = rotatePoint(local, angleX, angleY);
    const perspective = 3.15 / (3.15 - rotated.z);
    const shimmer = .78 + Math.sin(point.index * 1.73 + signal.time * 8.2) * signal.high * .28;
    projected.push({
      x: centreX + rotated.x * baseRadius * perspective,
      y: centreY + rotated.y * baseRadius * perspective,
      z: rotated.z,
      size: Math.max(.45, (1.05 + (rotated.z + 1) * 1.15) * shimmer),
      sourceY: point.y,
      morph,
      trailX: driftX * baseRadius * (4 + morph * 5),
      trailY: driftY * baseRadius * (4 + morph * 5),
      index: point.index,
    });
  }
  projected.sort((a, b) => a.z - b.z);

  // Sparse radial connections give high-frequency transients a brief electrical flare.
  ctx.save();
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = .55;
  ctx.globalAlpha = reducedMotion ? 0 : .012 + signal.high * .028 + motion.burst * .055 + motion.hero * .14;
  for (let index = 0; index < projected.length; index += 13) {
    const particle = projected[index];
    ctx.beginPath();
    ctx.moveTo(centreX, centreY);
    ctx.lineTo(particle.x, particle.y);
    ctx.stroke();
  }
  ctx.restore();

  const impact = Math.max(motion.burst * .48, motion.hero);
  const shockPosition = motion.impactAge < .32 ? 1 - motion.impactAge / .32 * 2 : 4;
  ctx.shadowBlur = 0;
  for (const particle of projected) {
    const depth = clamp((particle.z + 1) / 2);
    const inShock = Math.abs(particle.sourceY - shockPosition) < .045 + impact * .04;
    const frontLight = Math.pow(depth, 1.8);
    if (particle.morph > .14 && particle.index % 19 === 0) {
      line(
        ctx,
        particle.x - particle.trailX,
        particle.y - particle.trailY,
        particle.x,
        particle.y,
        particle.index % 3 === 0 ? ACCENT : INK,
        .7,
        (.08 + particle.morph * .24) * (reducedMotion ? .2 : 1),
      );
    }
    ctx.beginPath();
    ctx.arc(particle.x, particle.y, particle.size * (1 + signal.high * .38) * (1 - particle.morph * .18), 0, Math.PI * 2);
    if (inShock && impact > .025) {
      ctx.fillStyle = ACCENT;
      ctx.globalAlpha = .45 + impact * .48;
    } else if (particle.morph > .2 && particle.index % 11 === 0) {
      ctx.fillStyle = ACCENT;
      ctx.globalAlpha = .16 + depth * .32 + particle.morph * .18;
    } else if (frontLight > .58 && particle.index % 7 === 0) {
      ctx.fillStyle = '#fff9df';
      ctx.globalAlpha = .35 + frontLight * .6;
    } else {
      ctx.fillStyle = INK;
      ctx.globalAlpha = (.1 + depth * .72) * (1 - particle.morph * .22);
    }
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  ctx.shadowBlur = 0;

  // Orbit rings under the same breath scale as the WebGL field.
  drawFallbackRings(ctx, frame, layout, layout.baseRadius, angleX, angleY, reducedMotion);

  // A small inner core gives low frequencies a visible centre of gravity.
  const coreRadius = baseRadius * (.055 + signal.low * .08 + signal.beatPulse * .025);
  const core = ctx.createRadialGradient(centreX, centreY, 0, centreX, centreY, coreRadius * 2.6);
  core.addColorStop(0, `rgba(198,80,50,${.48 + motion.pulse * .22 + impact * .22})`);
  core.addColorStop(.28, `rgba(255,244,207,${.42 + signal.low * .3})`);
  core.addColorStop(1, 'rgba(255,244,207,0)');
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(centreX, centreY, coreRadius * 2.6, 0, Math.PI * 2);
  ctx.fill();
}

export function renderVisualOverlay(canvas, state, frame) {
  const ctx = canvas.getContext ? canvas.getContext('2d') : null;
  if (!ctx) return;
  const project = state.project;
  if (!project || !frame?.layout) {
    drawEmptyCanvas(ctx, canvas.clientWidth || 1200, canvas.clientHeight || 520, 'LOAD AUDIO');
    return;
  }
  ctx.save();
  const { layout, signal, motion } = frame;
  const width = layout.width;
  const margin = layout.margin;
  const innerWidth = layout.innerWidth;
  const spectrumTop = layout.spectrumTop;
  const spectrumBottom = layout.spectrumBottom;
  const mainTop = layout.mainTop;
  const mainBottom = layout.mainBottom;
  const mainHeight = layout.mainHeight;
  const hasSideMeters = layout.hasSideMeters;
  const meterWidth = layout.meterWidth;
  const traceBounds = layout.traceBounds;
  const centreX = layout.centreX;
  const centreY = layout.centreY;
  const baseRadius = layout.baseRadius;

  drawParticleHalo(ctx, frame, layout);

  // Instrument grid and the local eight-bar ruler.
  for (let index = 0; index <= 8; index += 1) {
    const x = traceBounds.left + (traceBounds.right - traceBounds.left) * index / 8;
    line(ctx, x, mainTop + 16, x, mainBottom, INK, .5, .052);
    const bar = Math.max(1, signal.bar - 4 + index);
    text(ctx, String(bar).padStart(2, '0'), x, mainTop + 7, {
      color: index === 4 ? ACCENT : MUTED,
      align: 'center',
      font: index === 4 ? '700 9px monospace' : '9px monospace',
    });
    line(ctx, x, mainTop + 14, x, mainTop + (index === 4 ? 23 : 19), index === 4 ? ACCENT : LINE, index === 4 ? 1.5 : 1, .8);
  }

  // The original three-band chart stays in the foreground of the instrument.
  drawFrequencyLine(ctx, project, signal, width, mainTop + mainHeight * .34, 'low', INK, mainHeight * .12, 1.35, .62, traceBounds);
  drawFrequencyLine(ctx, project, signal, width, mainTop + mainHeight * .57, 'mid', '#77756c', mainHeight * .11, 1.15, .62, traceBounds);
  drawFrequencyLine(ctx, project, signal, width, mainTop + mainHeight * .8, 'high', ACCENT, mainHeight * .095, 1.1, .78, traceBounds);

  // ◉ node markers: where each orbit ring's dashed path crosses the screen
  // vertical through the instrument centre (mockup detail).
  drawOrbitRingNodes(ctx, frame, layout);

  if (hasSideMeters) {
    const boxHeight = Math.min(76, mainHeight * .205);
    const gap = 7;
    const stackY = mainTop + Math.max(38, (mainHeight - boxHeight * 3 - gap * 2) / 2);
    const leftX = margin;
    const rightX = width - margin - meterWidth;
    drawMetricBox(ctx, leftX, stackY, meterWidth, boxHeight, 'BASS', `${Math.round(36 + signal.low * 54)}Hz`, `${(signal.low * 8 - 4).toFixed(1)} dB`, true, signal.low);
    drawMetricBox(ctx, leftX, stackY + boxHeight + gap, meterWidth, boxHeight, 'DYNAMIC', `${Math.round(signal.all * 100)}%`, 'FULL RANGE', false, signal.all);
    drawMetricBox(ctx, leftX, stackY + (boxHeight + gap) * 2, meterWidth, boxHeight, 'PUNCH', signal.onset.toFixed(2), 'TRANSIENT', true, signal.onset);
    drawMetricBox(ctx, rightX, stackY, meterWidth, boxHeight, 'ENERGY', `${Math.round(signal.all * 100)}%`, 'LIVE', true, signal.all);
    drawMetricBox(ctx, rightX, stackY + boxHeight + gap, meterWidth, boxHeight, 'SECTION', String(signal.section?.group || signal.section?.label || '—').slice(0, 9), `BAR ${String(signal.bar).padStart(2, '0')}`, false, signal.barPhase);
    drawMetricBox(ctx, rightX, stackY + (boxHeight + gap) * 2, meterWidth, boxHeight, 'TEMPO', `${Math.round(Number(project?.tempo?.bpm || project?.bpm || metrics(project, 16, null).bpm))}`, 'BPM', true, signal.beatPulse);
  }

  drawSpectrumDeck(ctx, project, signal, width, spectrumTop, spectrumBottom, margin);

  // Playhead and metadata stay secondary to the sphere.
  const playheadX = margin + innerWidth * .5;
  line(ctx, playheadX, mainTop, playheadX, mainBottom, ACCENT, 1, .62);
  ctx.fillStyle = ACCENT;
  ctx.fillRect(playheadX - 2, mainTop, 4, 6);
  text(ctx, `BAR ${String(signal.bar).padStart(2, '0')} / BEAT ${signal.beat}`, margin, margin + 10, { color: MUTED });
  text(ctx, `${signal.section?.group || signal.section?.label || '—'} / 08 BARS`, width - margin, margin + 10, { color: MUTED, align: 'right' });
  ctx.restore();
}

function aggregateSteps(project, subdivision, adjustments) {
  const cells = new Map();
  for (const onset of (project?.onsets || [])) {
    const position = gridPosition(onset.time ?? onset.raw_time, project, subdivision, adjustments);
    if (!cells.has(position.step)) cells.set(position.step, { all: 0, low: 0, mid: 0, high: 0, accent: 0, onsets: [] });
    const cell = cells.get(position.step);
    cell.all = Math.max(cell.all, clamp(onset.strength));
    cell.low = Math.max(cell.low, clamp(onset.bands?.low));
    cell.mid = Math.max(cell.mid, clamp(onset.bands?.mid));
    cell.high = Math.max(cell.high, clamp(onset.bands?.high));
    if (onset.accent) cell.accent = Math.max(cell.accent, clamp(onset.strength));
    cell.onsets.push({ onset, position });
  }
  return cells;
}

export function renderStaticMap(canvas, state) {
  const width = canvas.clientWidth || 1248;
  const height = canvas.clientHeight || 500;
  const { ctx } = resizeCanvas(canvas, width, height);
  ctx.fillStyle = PAPER;
  ctx.fillRect(0, 0, width, height);
  const project = state.project;
  if (!project) return;

  const left = 124;
  const right = 18;
  const top = 54;
  const rowHeight = 59;
  const subdivision = Number(state.subdivision) || 16;
  const viewBars = Number(state.viewBars) || 8;
  const startBar = Number(state.startBar) || 0;
  const columns = viewBars * subdivision;
  const cellWidth = (width - left - right) / columns;
  const gridBottom = top + ROWS.length * rowHeight;
  const stepCells = aggregateSteps(project, subdivision, state.adjustments);

  // Eight large bars create a readable phrase before the step resolution appears.
  for (let barIndex = 0; barIndex < viewBars; barIndex += 1) {
    const barX = left + barIndex * subdivision * cellWidth;
    const barWidth = subdivision * cellWidth;
    ctx.fillStyle = barIndex % 2 === 0 ? '#efede5' : '#f8f6f0';
    ctx.fillRect(barX, top, barWidth, gridBottom - top);
    text(ctx, `BAR ${String(startBar + barIndex + 1).padStart(2, '0')}`, barX + 7, 29, {
      color: barIndex === 0 ? ACCENT : INK,
      font: '700 10px monospace',
    });
    for (let beat = 0; beat < 4; beat += 1) {
      const beatX = barX + beat * barWidth / 4;
      text(ctx, beat + 1, beatX + 4, 45, { color: MUTED, font: '8px monospace' });
    }
  }

  for (let column = 0; column <= columns; column += 1) {
    const x = left + column * cellWidth;
    const isBar = column % subdivision === 0;
    const isBeat = column % (subdivision / 4) === 0;
    if (isBar || isBeat) line(ctx, x, top, x, gridBottom, isBar ? INK : '#aaa89f', isBar ? 1.15 : .7, isBar ? .5 : .26);
  }

  for (let rowIndex = 0; rowIndex < ROWS.length; rowIndex += 1) {
    const row = ROWS[rowIndex];
    const y = top + rowIndex * rowHeight;
    const baseline = y + rowHeight - 10;
    const color = row === 'accent' || row === 'high' ? ACCENT : row === 'mid' ? '#77756c' : INK;
    line(ctx, 0, y, width, y, rowIndex === 0 ? INK : LINE, rowIndex === 0 ? 1 : .75);
    text(ctx, LABELS[row], 16, y + 24, { color: row === 'accent' || row === 'high' ? ACCENT : INK, font: '700 9px monospace' });
    text(ctx, ROW_HINTS[row], 16, y + 40, { color: MUTED, font: '8px monospace' });
    line(ctx, left, baseline, width - right, baseline, color, .65, .18);

    const values = [];
    for (let column = 0; column < columns; column += 1) {
      const absoluteStep = startBar * subdivision + column;
      values.push(clamp(stepCells.get(absoluteStep)?.[row]));
    }

    if (row === 'accent') {
      for (let column = 0; column < columns; column += 1) {
        const value = values[column];
        if (value <= 0) continue;
        const x = left + (column + .5) * cellWidth;
        const size = 2 + value * 5;
        ctx.save();
        ctx.translate(x, baseline - 15 - value * 16);
        ctx.rotate(Math.PI / 4);
        ctx.fillStyle = ACCENT;
        ctx.globalAlpha = .35 + value * .65;
        ctx.fillRect(-size / 2, -size / 2, size, size);
        ctx.restore();
        line(ctx, x, baseline, x, baseline - 12 - value * 17, ACCENT, 1, .35 + value * .55);
      }
    } else {
      ctx.save();
      const wash = ctx.createLinearGradient(0, y + 8, 0, baseline);
      wash.addColorStop(0, row === 'high' ? 'rgba(198,80,50,.13)' : 'rgba(23,23,19,.09)');
      wash.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.beginPath();
      ctx.moveTo(left, baseline);
      for (let column = 0; column < columns; column += 1) {
        const x = left + (column + .5) * cellWidth;
        const value = values[column];
        const curveY = baseline - (4 + value * (rowHeight - 22));
        ctx.lineTo(x, curveY);
      }
      ctx.lineTo(width - right, baseline);
      ctx.closePath();
      ctx.fillStyle = wash;
      ctx.fill();
      ctx.beginPath();
      values.forEach((value, column) => {
        const x = left + (column + .5) * cellWidth;
        const curveY = baseline - (4 + value * (rowHeight - 22));
        if (column === 0) ctx.moveTo(x, curveY); else ctx.lineTo(x, curveY);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = row === 'all' ? 1.35 : 1;
      ctx.globalAlpha = row === 'high' ? .78 : .62;
      ctx.stroke();
      ctx.restore();
    }
  }
  line(ctx, 0, gridBottom, width, gridBottom, INK, 1, .72);

  // Raw timing pins show the groove without pretending it is quantized.
  for (const [absoluteStep, cell] of stepCells.entries()) {
    const relativeStep = absoluteStep - startBar * subdivision;
    if (relativeStep < 0 || relativeStep >= columns) continue;
    const strongest = cell.onsets.slice().sort((a, b) => b.onset.strength - a.onset.strength)[0];
    if (!strongest) continue;
    const timing = metrics(project, subdivision, state.adjustments);
    const rawRelative = (Number(strongest.onset.time ?? strongest.onset.raw_time) - timing.origin) / timing.step - startBar * subdivision;
    const rawX = left + rawRelative * cellWidth;
    const snappedX = left + (relativeStep + .5) * cellWidth;
    line(ctx, rawX, top - 9, snappedX, top - 9, ACCENT, 1, .6);
    ctx.fillStyle = ACCENT;
    ctx.fillRect(rawX - 1, top - 13, 2, 8);
  }

  // Motion cues translate the strongest event into a usable visual instruction.
  const graphTop = gridBottom + 25;
  const graphHeight = height - graphTop - 18;
  const centreY = graphTop + graphHeight * .54;
  text(ctx, 'MOTION CUES', 16, graphTop + 8, { color: INK, font: '700 9px monospace' });
  text(ctx, 'pulse · flow · flash', 16, graphTop + 25, { color: MUTED, font: '8px monospace' });
  line(ctx, left, centreY, width - right, centreY, LINE);
  for (let barIndex = 0; barIndex <= viewBars; barIndex += 1) {
    const x = left + barIndex * subdivision * cellWidth;
    line(ctx, x, graphTop, x, height - 12, INK, 1, .35);
  }
  for (const [absoluteStep, cell] of stepCells.entries()) {
    const relativeStep = absoluteStep - startBar * subdivision;
    if (relativeStep < 0 || relativeStep >= columns) continue;
    const strongest = cell.onsets.slice().sort((a, b) => b.onset.strength - a.onset.strength)[0];
    if (!strongest) continue;
    const x = left + (relativeStep + .5) * cellWidth;
    const velocity = clamp(strongest.onset.strength);
    const offset = clamp(strongest.position.offsetMs / 80, -1, 1);
    const bands = strongest.onset.bands || {};
    const driver = Number(bands.low) >= Number(bands.mid) && Number(bands.low) >= Number(bands.high)
      ? 'low' : Number(bands.high) >= Number(bands.mid) ? 'high' : 'mid';
    const cueColor = driver === 'high' || strongest.onset.accent ? ACCENT : driver === 'mid' ? '#77756c' : INK;
    const cueTop = centreY - 8 - velocity * graphHeight * .32;
    line(ctx, x, centreY, x, cueTop, cueColor, driver === 'low' ? 2.2 : 1.2, .3 + velocity * .7);
    if (driver === 'low') {
      ctx.strokeStyle = cueColor;
      ctx.globalAlpha = .35 + velocity * .55;
      ctx.beginPath();
      ctx.arc(x, cueTop, 2 + velocity * 4, 0, Math.PI * 2);
      ctx.stroke();
    } else if (driver === 'high') {
      line(ctx, x - 4, cueTop, x + 4, cueTop, cueColor, 1, .8);
      line(ctx, x, cueTop - 4, x, cueTop + 4, cueColor, 1, .8);
    } else {
      ctx.fillStyle = cueColor;
      ctx.globalAlpha = .4 + velocity * .6;
      ctx.fillRect(x - 1.5, cueTop - 3, 3, 6);
    }
    ctx.globalAlpha = 1;
    line(ctx, x, centreY, x, centreY + offset * graphHeight * .3, ACCENT, Math.max(1, cellWidth * .12), .72);
  }
}

export function renderOverlay(canvas, state) {
  const width = canvas.clientWidth || 1248;
  const height = canvas.clientHeight || 500;
  const { ctx } = resizeCanvas(canvas, width, height);
  ctx.clearRect(0, 0, width, height);
  const project = state.project;
  if (!project) return;
  const left = 124;
  const right = 18;
  const top = 54;
  const rowHeight = 59;
  const gridBottom = top + ROWS.length * rowHeight;
  const subdivision = Number(state.subdivision) || 16;
  const columns = (Number(state.viewBars) || 8) * subdivision;
  const cellWidth = (width - left - right) / columns;
  const startStep = (Number(state.startBar) || 0) * subdivision;

  if (state.loopSelection) {
    const from = Math.max(0, state.loopSelection.start - startStep);
    const to = Math.min(columns, state.loopSelection.end - startStep + 1);
    if (to > from) {
      ctx.fillStyle = ACCENT;
      ctx.globalAlpha = .1;
      ctx.fillRect(left + from * cellWidth, top, (to - from) * cellWidth, gridBottom - top);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = ACCENT;
      ctx.strokeRect(left + from * cellWidth + .5, top + .5, (to - from) * cellWidth - 1, gridBottom - top - 1);
    }
  }

  if (state.hoverStep !== null) {
    const relative = state.hoverStep - startStep;
    if (relative >= 0 && relative < columns) {
      ctx.strokeStyle = INK;
      ctx.strokeRect(left + relative * cellWidth + .5, top + .5, Math.max(1, cellWidth - 1), gridBottom - top - 1);
    }
  }

  const timing = metrics(project, subdivision, state.adjustments);
  if (timing.step > 0) {
    const relative = (state.playbackTime - timing.origin) / timing.step - startStep;
    if (relative >= 0 && relative <= columns) {
      const x = left + relative * cellWidth;
      line(ctx, x, 19, x, height - 12, ACCENT, 2, 1);
      ctx.fillStyle = ACCENT;
      ctx.beginPath();
      ctx.moveTo(x - 5, 19);
      ctx.lineTo(x + 5, 19);
      ctx.lineTo(x, 27);
      ctx.closePath();
      ctx.fill();
    }
  }
}

// v0.7 whole-song structure helpers (plan 15): pure functions of the project
// JSON so the overview strip, the keyboard jumps, and the readout agree on
// the same segment facts.
export function structuralSegments(project) {
  const segments = project?.patterns?.segments;
  return Array.isArray(segments) && segments.length ? segments : null;
}

export function structuralSegmentAt(project, time) {
  const segments = structuralSegments(project);
  if (!segments) return null;
  let active = null;
  for (const segment of segments) {
    if (time >= (Number(segment.start_time) || 0)) active = segment;
    else break;
  }
  return active;
}

export function structureSummary(project) {
  const segments = structuralSegments(project);
  if (!segments) return null;
  const named = (segment) => {
    const family = segment.family || '?';
    if (family === 'BREAK') return 'break';
    const primed = (Number(segment.variant) || 0) > 0
      || (segment.display_label && segment.display_label !== family);
    return primed ? `${family}-prime` : family;
  };
  const span = (segment) => {
    const start = Number(segment.start_bar) || 0;
    const end = Number(segment.end_bar) || start;
    return end > start ? `bars ${start} to ${end}` : `bar ${start}`;
  };
  return `Song structure: ${segments.map((segment) => `${named(segment)} ${span(segment)}`).join(', ')}`;
}

export function renderOverview(canvas, state) {
  const width = canvas.clientWidth || 1200;
  const height = canvas.clientHeight || 192;
  const { ctx } = resizeCanvas(canvas, width, height);
  ctx.fillStyle = PAPER;
  ctx.fillRect(0, 0, width, height);
  const project = state.project;
  if (!project) return;

  const duration = Number(project.source?.duration) || 1;
  const overview = project.patterns?.bars || project.overview || [];
  const bars = Number(project.grid?.bars) || Math.max(1, overview.length);
  const left = 18;
  const right = 18;
  const innerWidth = width - left - right;
  const barWidth = innerWidth / bars;
  const structureTop = 18;
  const structureHeight = 28;

  // Song sections are treated as navigation chapters, never as a confidence score.
  const structureSegments = structuralSegments(project);
  if (structureSegments) {
    // v0.7 whole-song navigator (plan 15.1): one contiguous block per
    // structural segment. Shades are indexed by family, so every repeat of a
    // family wears the same neutral shade and variants differ only by their
    // prime label. Boundary tick weight follows the boundary's novelty.
    const familyShades = ['#171713', '#77756c', '#a9a69b', '#4a4840', '#8c897d', '#6b6960'];
    const familyIndex = new Map();
    const activeSegment = structuralSegmentAt(project, state.playbackTime);
    for (const segment of structureSegments) {
      if (!familyIndex.has(segment.family)) familyIndex.set(segment.family, familyIndex.size);
      const startX = clamp(Number(segment.start_time) / duration);
      const endX = clamp(Number(segment.end_time) / duration);
      const segmentX = left + startX * innerWidth;
      const segmentWidth = Math.max(1, (endX - startX) * innerWidth);
      ctx.fillStyle = familyShades[familyIndex.get(segment.family) % familyShades.length];
      ctx.globalAlpha = segment === activeSegment ? .92 : .68;
      ctx.fillRect(segmentX, structureTop, segmentWidth, structureHeight);
      ctx.globalAlpha = 1;
      if (segmentWidth > 34) {
        text(ctx, segment.display_label || segment.family || '—', segmentX + 6, structureTop + 12, { color: SURFACE, font: '700 8px monospace' });
        text(ctx, `${String(segment.start_bar).padStart(2, '0')}—${String(segment.end_bar).padStart(2, '0')}`, segmentX + 6, structureTop + 23, { color: SURFACE, alpha: .72, font: '7px monospace' });
      }
    }
    for (const boundary of project.patterns?.boundaries || []) {
      const novelty = clamp(Number(boundary.novelty));
      const x = left + clamp(Number(boundary.time) / duration) * innerWidth;
      line(ctx, x, structureTop - 2 - novelty * 5, x, structureTop + structureHeight, INK, 1 + novelty, .28 + novelty * .5);
    }
  } else {
    let lastGroup = null;
    let groupStart = 0;
    const groupPalette = ['#171713', '#77756c', '#c65032', '#a9a69b'];
    let groupIndex = -1;
    for (let index = 0; index <= overview.length; index += 1) {
      const group = index < overview.length ? (overview[index]?.group || overview[index]?.label || '—') : null;
      if (group !== lastGroup) {
        if (lastGroup !== null) {
          const segmentX = left + groupStart * barWidth;
          const segmentWidth = Math.max(1, (index - groupStart) * barWidth);
          ctx.fillStyle = groupPalette[Math.abs(groupIndex) % groupPalette.length];
          ctx.globalAlpha = lastGroup === (overview[Math.max(0, Math.floor(clamp(state.playbackTime / duration) * bars))]?.group || overview[Math.max(0, Math.floor(clamp(state.playbackTime / duration) * bars))]?.label) ? .92 : .68;
          ctx.fillRect(segmentX, structureTop, segmentWidth, structureHeight);
          ctx.globalAlpha = 1;
          if (segmentWidth > 34) {
            text(ctx, lastGroup, segmentX + 6, structureTop + 12, { color: SURFACE, font: '700 8px monospace' });
            text(ctx, `${String(groupStart + 1).padStart(2, '0')}—${String(index).padStart(2, '0')}`, segmentX + 6, structureTop + 23, { color: SURFACE, alpha: .72, font: '7px monospace' });
          }
        }
        lastGroup = group;
        groupStart = index;
        groupIndex += 1;
      }
    }
  }

  const lanes = [
    { key: 'low', y: 78, color: INK, label: 'LOW' },
    { key: 'mid', y: 112, color: '#77756c', label: 'MID' },
    { key: 'high', y: 146, color: ACCENT, label: 'HIGH' },
  ];
  const samples = Math.max(100, Math.floor(width / 2));

  for (const lane of lanes) {
    line(ctx, left, lane.y, width - right, lane.y, lane.color, .6, .17);
    text(ctx, lane.label, left + 2, lane.y - 13, { color: lane.color, alpha: .72, font: '8px monospace' });
    ctx.beginPath();
    for (let index = 0; index <= samples; index += 1) {
      const time = duration * index / samples;
      const value = Math.sqrt(energyAt(project, time, lane.key));
      const x = left + innerWidth * index / samples;
      const y = lane.y - value * 22;
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = lane.color;
    ctx.lineWidth = lane.key === 'low' ? 1.3 : 1;
    ctx.globalAlpha = lane.key === 'high' ? .74 : .58;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // Accented events appear as a sparse visual cue rail beneath the band envelopes.
  const cueY = 164;
  line(ctx, left, cueY, width - right, cueY, LINE, 1, .85);
  const accentIds = new Set((project.cues?.accent || []).map((c) => c.onset));
  for (const onset of (project.onsets || [])) {
    const isAccent = onset.accent || accentIds.has(onset.id);
    if (!isAccent && Number(onset.strength) < .72) continue;
    const x = left + clamp(Number(onset.time ?? onset.raw_time) / duration) * innerWidth;
    const strength = clamp(onset.strength);
    line(ctx, x, cueY - 3, x, cueY - 3 - strength * 8, isAccent ? ACCENT : INK, isAccent ? 1.5 : 1, .35 + strength * .55);
  }

  for (let index = 0; index <= bars; index += 8) {
    const x = left + index * barWidth;
    line(ctx, x, structureTop + structureHeight, x, height - 10, LINE, 1, .55);
    text(ctx, index + 1, x + 3, height - 4, { color: MUTED, font: '8px monospace' });
  }

  const windowX = left + (Number(state.startBar) || 0) * barWidth;
  const windowWidth = (Number(state.viewBars) || 8) * barWidth;
  ctx.fillStyle = ACCENT;
  ctx.globalAlpha = .055;
  ctx.fillRect(windowX, structureTop + structureHeight, windowWidth, height - structureTop - structureHeight - 9);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 1.5;
  ctx.strokeRect(windowX + .5, structureTop + structureHeight + .5, Math.max(2, windowWidth - 1), height - structureTop - structureHeight - 10);

  const playheadX = left + clamp(state.playbackTime / duration) * innerWidth;
  line(ctx, playheadX, structureTop - 5, playheadX, height - 9, ACCENT, 1.7);
  ctx.fillStyle = ACCENT;
  ctx.beginPath();
  ctx.moveTo(playheadX - 4, structureTop - 5);
  ctx.lineTo(playheadX + 4, structureTop - 5);
  ctx.lineTo(playheadX, structureTop + 1);
  ctx.closePath();
  ctx.fill();
}

export function exportStaticPng(state) {
  const canvas = document.createElement('canvas');
  canvas.style.width = '1400px';
  canvas.style.height = '500px';
  renderStaticMap(canvas, state);
  return canvas.toDataURL('image/png');
}
