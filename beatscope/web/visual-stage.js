/**
 * Visual stage controller (v0.6.1 plan sections 7.1, 8.2): owns the call
 * order so every layer of the signal player samples ONE shared frame per
 * animation tick — no layer calls the runtime track or the compat profile
 * itself.
 *
 * Layer order on the stack (section 3.2): the CSS paper background, the
 * WebGL2 particle field on #particleStage, then the Canvas 2D instrument
 * chrome on #visualStage. While the field is unavailable the retained
 * Canvas body routine paints beneath the chrome instead (section 9). The
 * controller never runs its own rAF loop; app.js keeps the single clock.
 */
import {
  playbackState,
  renderVisualBackdrop,
  renderVisualOverlay,
  resizeCanvas,
  visualProfileFor,
} from './renderer.js';
import { trackForProject } from '../runtime/runtime.js';
import { createMotionDirector } from '../runtime/visual-profile.js';
import { createParticleGeometry, RING_DEFS } from './particle-geometry.js';
import { createParticleField } from './particle-field.js';

// Tier presets (plan section 7.3): DPR cap and particle budget per tier.
export const QUALITY_TIERS = {
  high: { dprCap: 1.5, count: 18000 },
  medium: { dprCap: 1.25, count: 11000 },
  low: { dprCap: 1, count: 6000 },
};

const TIER_ORDER = ['low', 'medium', 'high'];
const QUALITY_WINDOW_FRAMES = 180;
const DOWNGRADE_P95_MS = 18;
const UPGRADE_P95_MS = 11;
const DOWNGRADE_WINDOWS = 3;
const UPGRADE_WINDOWS = 5;
const TIER_COOLDOWN_MS = 5000;

export function normalizeTier(value) {
  return Object.prototype.hasOwnProperty.call(QUALITY_TIERS, value) ? value : null;
}

/**
 * Pure hysteresis decision for one completed 180-frame window (section 8.2).
 * Streaks keep counting through the five-second cooldown; pausing or hiding
 * the stage resets them because those frames do not measure real cost.
 */
export function qualityTierDecision({
  tier,
  p95,
  overWindows,
  underWindows,
  playing,
  visible,
  msSinceChange,
}) {
  if (!playing || !visible) {
    return { tier, overWindows: 0, underWindows: 0, changed: false };
  }
  let nextOver = overWindows;
  let nextUnder = underWindows;
  if (p95 > DOWNGRADE_P95_MS) {
    nextOver += 1;
    nextUnder = 0;
  } else if (p95 < UPGRADE_P95_MS) {
    nextUnder += 1;
    nextOver = 0;
  } else {
    nextOver = 0;
    nextUnder = 0;
  }
  const index = TIER_ORDER.indexOf(tier);
  const cooledDown = msSinceChange >= TIER_COOLDOWN_MS;
  if (cooledDown && nextOver >= DOWNGRADE_WINDOWS && index > 0) {
    return { tier: TIER_ORDER[index - 1], overWindows: 0, underWindows: 0, changed: true };
  }
  if (cooledDown && nextUnder >= UPGRADE_WINDOWS && index < TIER_ORDER.length - 1) {
    return { tier: TIER_ORDER[index + 1], overWindows: 0, underWindows: 0, changed: true };
  }
  return { tier, overWindows: nextOver, underWindows: nextUnder, changed: false };
}

function prefersReducedMotion() {
  return Boolean(
    typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
  );
}

export function createVisualStage({ particleCanvas = null, overlayCanvas = null } = {}) {
  if (!overlayCanvas) throw new Error('createVisualStage requires an overlayCanvas');

  const stage = {
    project: null,
    director: null,
    compatProfile: null,
    field: null,
    visible: true,
    backend: 'canvas-compat',
    forcedBackend: null,
    framesRendered: 0,
    lastFrameCostMs: 0,
    lastState: null,
    sizedWidth: 0,
    sizedHeight: 0,
    sizedDpr: 0,
    tier: 'high',
    appliedTier: null,
    appliedDpr: 0,
    fixedTier: null,
    playing: false,
    windowCosts: [],
    windowP95Ms: null,
    overWindows: 0,
    underWindows: 0,
    lastTierChangeAt: typeof performance !== 'undefined' ? performance.now() : 0,
  };

  stage.field = createParticleField({
    canvas: particleCanvas,
    geometry: particleCanvas
      ? createParticleGeometry({ count: QUALITY_TIERS.high.count, rings: RING_DEFS.length })
      : null,
  });
  function overlayContext() {
    if (typeof overlayCanvas.getContext !== 'function') return null;
    try {
      return overlayCanvas.getContext('2d');
    } catch (_) {
      return null;
    }
  }

  function fieldReady() {
    return Boolean(stage.field?.available) && stage.forcedBackend !== 'canvas';
  }

  /** Adaptive monitoring only counts frames the tier actually influences. */
  function adaptiveAllowed() {
    return Boolean(stage.project && stage.director && fieldReady() && !stage.fixedTier);
  }

  function applyQualityTier(tier) {
    const resolved = normalizeTier(tier) || 'high';
    const preset = QUALITY_TIERS[resolved];
    stage.appliedTier = resolved;
    const deviceDpr = typeof window !== 'undefined' && Number(window.devicePixelRatio) > 0
      ? Number(window.devicePixelRatio)
      : 1;
    stage.appliedDpr = Math.min(deviceDpr, preset.dprCap);
    stage.sizedWidth = 0;
    stage.sizedHeight = 0;
    stage.sizedDpr = 0;
    // Buffer swap happens between frames, never inside a draw call (section 8.2).
    if (particleCanvas && stage.field?.available) {
      stage.field.updateGeometry(createParticleGeometry({ count: preset.count, rings: RING_DEFS.length }));
    }
  }

  /** One ResizeObserver-driven resize; skipped unless CSS pixels or DPR changed. */
  function ensureSized(width, height) {
    const dpr = stage.appliedDpr || 1;
    if (stage.sizedWidth === width && stage.sizedHeight === height && stage.sizedDpr === dpr) return;
    stage.sizedWidth = width;
    stage.sizedHeight = height;
    stage.sizedDpr = dpr;
    resizeCanvas(overlayCanvas, width, height, dpr);
    if (particleCanvas) {
      const physicalWidth = Math.max(1, Math.round(width * dpr));
      const physicalHeight = Math.max(1, Math.round(height * dpr));
      if (particleCanvas.width !== physicalWidth) particleCanvas.width = physicalWidth;
      if (particleCanvas.height !== physicalHeight) particleCanvas.height = physicalHeight;
      particleCanvas.style.width = `${width}px`;
      particleCanvas.style.height = `${height}px`;
      stage.field.resize(physicalWidth, physicalHeight);
    }
  }

  function computeLayout(width, height) {
    const margin = Math.max(24, width * .035);
    const spectrumTop = height * (width < 700 ? .72 : .73);
    const spectrumBottom = height - margin;
    const mainTop = margin + 24;
    const mainBottom = spectrumTop - 16;
    const mainHeight = mainBottom - mainTop;
    const hasSideMeters = width >= 900;
    const meterWidth = hasSideMeters ? Math.min(94, width * .082) : 0;
    const layout = {
      width,
      height,
      margin,
      innerWidth: width - margin * 2,
      spectrumTop,
      spectrumBottom,
      mainTop,
      mainBottom,
      mainHeight,
      hasSideMeters,
      meterWidth,
      traceBounds: {
        left: margin + (hasSideMeters ? meterWidth + 34 : 0),
        right: width - margin - (hasSideMeters ? meterWidth + 34 : 0),
      },
      centreX: width * .5,
      centreY: mainTop + mainHeight * .5,
      // The WebGL field now honours this radius directly. Keep enough scale
      // for the three petals to read as the hero, while the scissor rect
      // prevents even the close orbit layer from entering the spectrum deck.
      baseRadius: Math.min(width * .17, mainHeight * .42),
    };
    // Relaxed field rect (user-approved ring spec): the orbit rings may reach
    // past the band-chart lines and toward the top edge, but never into the
    // spectrum deck. Screen size derives from radiusPx alone, so widening the
    // viewport/scissor does not rescale the instrument.
    const ringSpan = 2.3 * layout.baseRadius;
    layout.fieldRect = {
      left: Math.min(layout.traceBounds.left, Math.max(0, layout.centreX - ringSpan)),
      right: Math.max(layout.traceBounds.right, Math.min(width, layout.centreX + ringSpan)),
      top: Math.max(0, layout.centreY - ringSpan),
      bottom: Math.min(spectrumTop - 8, layout.centreY + ringSpan),
    };
    return layout;
  }

  function clearOverlay() {
    const ctx = overlayContext();
    if (!ctx) return;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    ctx.restore();
  }

  function recordFrameCost(costMs) {
    if (!adaptiveAllowed()) return;
    stage.windowCosts.push(costMs);
    if (stage.windowCosts.length < QUALITY_WINDOW_FRAMES) return;
    const sorted = stage.windowCosts.slice().sort((a, b) => a - b);
    const p95 = sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1)];
    stage.windowP95Ms = p95;
    stage.windowCosts = [];
    const now = typeof performance !== 'undefined' ? performance.now() : 0;
    const decision = qualityTierDecision({
      tier: stage.tier,
      p95,
      overWindows: stage.overWindows,
      underWindows: stage.underWindows,
      playing: stage.playing,
      visible: stage.visible,
      msSinceChange: now - stage.lastTierChangeAt,
    });
    stage.overWindows = decision.overWindows;
    stage.underWindows = decision.underWindows;
    if (decision.changed) {
      stage.tier = decision.tier;
      stage.lastTierChangeAt = now;
    }
  }

  function renderFixedFrame(state) {
    const ctx = overlayContext();
    if (!ctx) return;
    const started = typeof performance !== 'undefined' ? performance.now() : 0;
    const width = overlayCanvas.clientWidth || 1200;
    const height = overlayCanvas.clientHeight || 520;
    const requestedTier = stage.fixedTier || stage.tier;
    if (requestedTier !== stage.appliedTier) applyQualityTier(requestedTier);
    ensureSized(width, height);
    clearOverlay();

    const project = stage.project;
    if (!project || !stage.director) {
      renderVisualOverlay(overlayCanvas, state, null);
      stage.framesRendered += 1;
      if (typeof performance !== 'undefined') stage.lastFrameCostMs = performance.now() - started;
      return;
    }

    // One sample per layer, all taken here (plan section 7.1).
    const time = Number(state.playbackTime) || 0;
    const signal = playbackState(project, time);
    const motion = stage.compatProfile.at(time);
    const reducedMotion = state.reducedMotion === undefined
      ? prefersReducedMotion()
      : Boolean(state.reducedMotion);
    const frame = stage.director.at(time, { reducedMotion });
    const layout = computeLayout(width, height);
    const shared = { ...frame, signal, motion, layout, reducedMotion };
    stage.playing = Boolean(state.isPlaying);

    if (fieldReady()) {
      const deviceScale = particleCanvas ? particleCanvas.width / Math.max(1, width) : 1;
      stage.field.render(frame, {
        quality: 1,
        reducedMotion,
        radiusPx: layout.baseRadius * deviceScale,
        viewportRect: {
          x: layout.fieldRect.left * deviceScale,
          y: (height - layout.fieldRect.bottom) * deviceScale,
          width: (layout.fieldRect.right - layout.fieldRect.left) * deviceScale,
          height: (layout.fieldRect.bottom - layout.fieldRect.top) * deviceScale,
        },
      });
      stage.backend = 'webgl2';
    } else {
      renderVisualBackdrop(overlayCanvas, state, shared);
      stage.backend = 'canvas-compat';
    }
    renderVisualOverlay(overlayCanvas, state, shared);

    stage.framesRendered += 1;
    if (typeof performance !== 'undefined') stage.lastFrameCostMs = performance.now() - started;
    recordFrameCost(stage.lastFrameCostMs);
  }

  function getDiagnostics() {
    return {
      backend: stage.forcedBackend || stage.backend,
      framesRendered: stage.framesRendered,
      lastFrameCostMs: Number(stage.lastFrameCostMs.toFixed(3)),
      visible: stage.visible,
      particleCount: stage.field?.count || 0,
      ringUniforms: stage.field?.diagnostics ? stage.field.diagnostics().ringUniforms : undefined,
      fieldReason: stage.field?.available ? null : stage.field?.reason || 'unavailable',
      tier: stage.fixedTier || stage.tier,
      appliedTier: stage.appliedTier,
      dpr: stage.appliedDpr || null,
      windowP95Ms: stage.windowP95Ms === null ? null : Number(stage.windowP95Ms.toFixed(3)),
      qualitySource: stage.fixedTier ? 'fixed' : 'adaptive',
      contextLost: Boolean(stage.field?.contextLost),
    };
  }

  // Reduced motion must respond live (section 10.1): repaint the paused or
  // running stage when the media query flips mid-session.
  let reduceQuery = null;
  let reduceChange = null;
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    reduceQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    reduceChange = () => {
      if (stage.visible && stage.lastState) renderFixedFrame(stage.lastState);
    };
    if (typeof reduceQuery.addEventListener === 'function') {
      reduceQuery.addEventListener('change', reduceChange);
    } else if (typeof reduceQuery.addListener === 'function') {
      reduceQuery.addListener(reduceChange);
    }
  }

  return {
    setProject(project) {
      stage.project = project || null;
      stage.director = null;
      stage.compatProfile = null;
      if (stage.project) {
        stage.director = createMotionDirector(trackForProject(stage.project));
        stage.compatProfile = visualProfileFor(stage.project);
      }
    },
    render(state) {
      if (!stage.visible) return;
      stage.lastState = state || null;
      renderFixedFrame(state || {});
    },
    resize() {
      stage.sizedWidth = 0;
      stage.sizedHeight = 0;
      stage.sizedDpr = 0;
      if (stage.lastState) renderFixedFrame(stage.lastState);
    },
    setVisible(visible) {
      stage.visible = Boolean(visible);
    },
    /** Debug/CI hook: pin one tier and disable adaptation (section 8.2). */
    setFixedTier(tier) {
      stage.fixedTier = normalizeTier(tier);
      return getDiagnostics();
    },
    /** Manual tier override; restarts the hysteresis streaks and cooldown. */
    setQualityTier(tier) {
      const resolved = normalizeTier(tier);
      if (resolved) {
        stage.tier = resolved;
        stage.overWindows = 0;
        stage.underWindows = 0;
        stage.windowCosts = [];
        stage.lastTierChangeAt = typeof performance !== 'undefined' ? performance.now() : 0;
      }
      return getDiagnostics();
    },
    dispose() {
      if (reduceQuery && reduceChange) {
        if (typeof reduceQuery.removeEventListener === 'function') {
          reduceQuery.removeEventListener('change', reduceChange);
        } else if (typeof reduceQuery.removeListener === 'function') {
          reduceQuery.removeListener(reduceChange);
        }
      }
      stage.field?.dispose();
      stage.field = null;
      stage.project = null;
      stage.director = null;
      stage.compatProfile = null;
      stage.lastState = null;
      stage.windowCosts = [];
    },
    forceBackend(backend) {
      stage.forcedBackend = backend === 'canvas' ? 'canvas' : backend === 'webgl2' ? 'webgl2' : null;
      return getDiagnostics();
    },
    getDiagnostics,
  };
}

/**
 * Development-only fixed-frame entry point (v0.6.1 plan section 12): render
 * one deterministic frame at an arbitrary time without playing audio. The
 * requested tier is fixed for the frame and adaptation is disabled (section
 * 8.2). Callers install the result on window.__BEATSCOPE_VISUAL_DEBUG__ from
 * localhost only.
 */
export function installVisualDebug(stage, { isLocal = () => true } = {}) {
  return {
    renderAt(time, { quality = 'high', reducedMotion = false } = {}) {
      stage.setFixedTier(quality);
      try {
        stage.render({ playbackTime: Number(time) || 0, reducedMotion });
      } finally {
        stage.setFixedTier(null);
      }
      return stage.getDiagnostics();
    },
    diagnostics: () => stage.getDiagnostics(),
    forceBackend(backend) {
      return stage.forceBackend(backend);
    },
    forceTier(tier) {
      return stage.setFixedTier(tier);
    },
    setTier(tier) {
      return stage.setQualityTier(tier);
    },
    isLocal,
  };
}
