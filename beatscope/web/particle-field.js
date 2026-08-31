/**
 * WebGL2 particle field (v0.6.1 plan sections 3.1, 4.3, 5.1, 8.4).
 *
 * One WebGL2 POINTS draw call renders the three-lobed body. Module import is
 * Node-safe — every DOM/WebGL touch lives inside createParticleField — so
 * tests exercise the pure uniform conversion directly.
 *
 * Failures never break playback: a missing context or a shader compile/link
 * error returns an `available: false` field and the stage routes the frame
 * to the Canvas fallback (plan section 9).
 */

import { PARTICLE_VERTEX_SOURCE, PARTICLE_FRAGMENT_SOURCE } from './particle-shaders.js';
import { RING_DEFS } from './particle-geometry.js';
import { combinedSpread, legacySpread } from '../runtime/visual-profile.js';

export const CAMERA_Z = 4.4;
export const FOV_Y = (35 * Math.PI) / 180;

const UNIFORM_NAMES = [
  'uTime', 'uViewport', 'uRadiusPx', 'uWorldScale', 'uCameraZ', 'uProjection',
  'uLow', 'uMid', 'uHigh', 'uAmbient',
  'uAnticipation', 'uHold', 'uImpact', 'uRecoil', 'uAftershock',
  'uTension', 'uHero', 'uLobeWeights', 'uDirection',
  'uShockProgress', 'uBeatWave', 'uWaveProgress', 'uCoreAperture', 'uDiffusion',
  'uBeatExpand', 'uLobeSplit', 'uReducedMotion', 'uQuality',
  // v0.8 scene uniforms (plan section 11).
  'uSceneSpread', 'uSceneTwist', 'uSceneFlow', 'uSceneOrbit', 'uSceneVoid',
  'uSceneContrast', 'uPaletteMix', 'uPhaseTurn', 'uRadialPart',
  'uApertureTransition', 'uFlowShear',
  'uRingA', 'uRingE', 'uRingSpeed', 'uRingColor', 'uRingMat',
];

const clamp = (value, low, high) => Math.min(high, Math.max(low, Number(value) || 0));

function finiteVec3(value, fallback) {
  if (!Array.isArray(value) || value.length < 3) return fallback.slice();
  const x = Number(value[0]);
  const y = Number(value[1]);
  const z = Number(value[2]);
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return fallback.slice();
  return [x, y, z];
}

function normalizeVec3(value, fallback) {
  const [x, y, z] = finiteVec3(value, fallback);
  const length = Math.sqrt(x * x + y * y + z * z);
  if (length < 1e-6) return fallback.slice();
  return [x / length, y / length, z / length];
}

/**
 * Column-major perspective projection written into ``out`` (Float32Array(16)).
 */
export function perspectiveMatrix(out, fovy = FOV_Y, aspect = 1, near = 0.1, far = 20) {
  const f = 1 / Math.tan(fovy / 2);
  out.fill(0);
  out[0] = f / Math.max(1e-6, aspect);
  out[5] = f;
  out[10] = (far + near) / (near - far);
  out[11] = -1;
  out[14] = (2 * far * near) / (near - far);
  return out;
}

/**
 * Pure combined-frame -> shader-uniform conversion (plan sections 10-11).
 * The frame may be the plain motion director frame (legacy callers and
 * tests) or the combined visual-stage frame `{..., motion, scene, ...}`;
 * beat channels are read from `frame.motion` when present, scene channels
 * from `frame.scene` (null = legacy neutral behavior). When ``target`` is
 * given the result is written into it so render loops allocate nothing.
 */
export function frameToUniforms(frame, layout, { quality = 1, reducedMotion = false } = {}, target = null) {
  const width = Math.max(1, Number(layout?.width) || 1);
  const height = Math.max(1, Number(layout?.height) || 1);
  const radiusPx = Number(layout?.radiusPx) > 0
    ? Number(layout.radiusPx)
    : (height * 0.5 / Math.tan(FOV_Y / 2)) / CAMERA_Z;
  const beat = frame?.motion ?? frame ?? {};
  const scene = frame?.scene ?? null;
  const composition = scene?.composition ?? null;
  const channels = scene?.transition?.channels ?? null;
  const weights = finiteVec3(beat?.lobeWeights, [0.34, 0.33, 0.33]).map((value) => clamp(value, 0, 1));
  const direction = normalizeVec3(beat?.direction, [0, 1, 0]);

  const uniforms = target || {};
  uniforms.uTime = Number(beat?.time) || 0;
  uniforms.uViewportX = width;
  uniforms.uViewportY = height;
  uniforms.uRadiusPx = radiusPx;
  uniforms.uWorldScale = radiusPx * CAMERA_Z * 2 * Math.tan(FOV_Y / 2) / height;
  uniforms.uCameraZ = CAMERA_Z;
  uniforms.uLow = clamp(beat?.low, 0, 1);
  uniforms.uMid = clamp(beat?.mid, 0, 1);
  uniforms.uHigh = clamp(beat?.high, 0, 1);
  uniforms.uAmbient = clamp(beat?.ambient, 0, 1);
  uniforms.uAnticipation = clamp(beat?.anticipation, 0, 1);
  uniforms.uHold = clamp(beat?.hold, 0, 1);
  uniforms.uImpact = clamp(beat?.impact, 0, 1);
  uniforms.uRecoil = clamp(beat?.recoil, 0, 1);
  uniforms.uAftershock = clamp(beat?.aftershock, -1, 1);
  uniforms.uTension = clamp(beat?.tension, 0, 1);
  uniforms.uHero = clamp(beat?.hero, 0, 1);
  uniforms.uLobeWeights0 = weights[0];
  uniforms.uLobeWeights1 = weights[1];
  uniforms.uLobeWeights2 = weights[2];
  uniforms.uDirection0 = direction[0];
  uniforms.uDirection1 = direction[1];
  uniforms.uDirection2 = direction[2];
  uniforms.uShockProgress = clamp(beat?.shockProgress, 0, 1);
  uniforms.uBeatWave = clamp(beat?.beatWave, 0, 1);
  uniforms.uWaveProgress = clamp(beat?.waveProgress, 0, 1);
  uniforms.uCoreAperture = clamp(beat?.coreAperture, 0, 1);
  uniforms.uDiffusion = clamp(beat?.diffusion, 0, 1);
  uniforms.uBeatExpand = clamp(beat?.beatExpand, 0, 1);
  uniforms.uLobeSplit = clamp(beat?.lobeSplit, 0, 1);
  uniforms.uReducedMotion = reducedMotion ? 1 : 0;
  uniforms.uQuality = clamp(quality, 0.5, 1);

  // Scene block (plan section 10): the combined spread folds the scene
  // baseline, the scene-aware heavy-beat additive, and the radial parting
  // into one capped translation; without a scene frame the v0.7 heavy-beat
  // split is reproduced exactly so legacy projects keep their visuals.
  const spread = scene
    ? combinedSpread(scene, beat)
    : { sceneSpread: legacySpread(beat), radialPart: 0 };
  uniforms.uSceneSpread = spread.sceneSpread;
  uniforms.uRadialPart = spread.radialPart;
  uniforms.uSceneTwist = clamp(composition?.twist, 0, 1);
  uniforms.uSceneFlow = clamp(composition?.flow, 0, 1);
  uniforms.uSceneOrbit = clamp(composition?.orbit, 0, 1);
  uniforms.uSceneVoid = clamp(composition?.void, 0, 1);
  uniforms.uSceneContrast = clamp(composition?.contrast, 0, 1);
  uniforms.uPaletteMix = clamp(composition?.paletteMix, 0, 1);
  uniforms.uPhaseTurn = clamp(channels?.phaseTurn, 0, 1);
  uniforms.uApertureTransition = clamp(channels?.aperture, 0, 1);
  uniforms.uFlowShear = clamp(channels?.flowShear, -1, 1);

  // Aspect feeds the projection; recomputed with the caller's scratch matrix.
  uniforms.aspect = width / height;
  return uniforms;
}

function unavailable(reason) {
  return {
    available: false,
    backend: 'canvas',
    reason,
    contextLost: false,
    count: 0,
    resize() {},
    render() {},
    updateGeometry() {},
    onFallback(callback) {
      if (typeof callback === 'function') callback(reason);
    },
    diagnostics() {
      return { backend: 'canvas', available: false, reason, contextLost: false, count: 0 };
    },
    dispose() {},
  };
}

/**
 * Create the field. Returns an `available: false` stub on any failure so the
 * stage never branches on WebGL details.
 */
export function createParticleField({ canvas, geometry = null } = {}) {
  if (!canvas || typeof canvas.getContext !== 'function') {
    return unavailable('no-canvas');
  }
  let gl;
  try {
    gl = canvas.getContext('webgl2', {
      alpha: true,
      antialias: false,
      depth: false,
      stencil: false,
      premultipliedAlpha: false,
      preserveDrawingBuffer: false,
      powerPreference: 'high-performance',
    });
  } catch (error) {
    return unavailable(`context-error: ${error?.message || error}`);
  }
  if (!gl) return unavailable('webgl2-unavailable');

  const state = {
    program: null,
    vao: null,
    buffers: [],
    locations: null,
    count: 0,
    contextLost: false,
    fallbackCallbacks: [],
    projection: new Float32Array(16),
    uniformsScratch: {},
  };

  function fail(reason) {
    state.fallbackCallbacks.forEach((callback) => callback(reason));
  }

  function compileShader(type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error(`particle shader compile failed: ${log || 'no log'}`);
    }
    return shader;
  }

  function uploadGeometry(geometry) {
    state.buffers.forEach((buffer) => gl.deleteBuffer(buffer));
    state.buffers = [];
    if (!geometry || !geometry.count) {
      state.count = 0;
      return;
    }
    const vao = state.vao || gl.createVertexArray();
    state.vao = vao;
    gl.bindVertexArray(vao);
    const feeds = [
      { data: geometry.positions, size: 3, location: 0 },
      { data: geometry.seeds, size: 4, location: 1 },
      { data: geometry.meta, size: 4, location: 2 },
    ];
    for (const feed of feeds) {
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, feed.data, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(feed.location);
      gl.vertexAttribPointer(feed.location, feed.size, gl.FLOAT, false, 0, 0);
      state.buffers.push(buffer);
    }
    gl.bindVertexArray(null);
    state.count = geometry.count;
  }

  /**
   * Ring constants never change per frame: upload them once per program
   * (and again on context restore, which re-runs initGL). The ring basis is
   * the column-major mat3 of Rx(incl) * Rz(phi) matching ringPointLocal().
   */
  function uploadRingUniforms() {
    if (!state.locations.uRingMat) {
      state.ringUniforms = { uploaded: false, reason: 'no-location', basis00: null };
      return;
    }
    const count = RING_DEFS.length;
    const ringA = new Float32Array(count);
    const ringE = new Float32Array(count);
    const ringSpeed = new Float32Array(count);
    const colors = new Float32Array(count * 3);
    const bases = new Float32Array(count * 9);
    RING_DEFS.forEach((def, index) => {
      ringA[index] = def.a;
      ringE[index] = def.squash;
      ringSpeed[index] = def.speed;
      colors.set(def.color, index * 3);
      const cosPhi = Math.cos(def.phi);
      const sinPhi = Math.sin(def.phi);
      const cosI = Math.cos(def.incl);
      const sinI = Math.sin(def.incl);
      bases.set([
        cosPhi, cosI * sinPhi, sinI * sinPhi,
        -sinPhi, cosI * cosPhi, sinI * cosPhi,
        0, -sinI, cosI,
      ], index * 9);
    });
    gl.uniform3fv(state.locations.uRingA, ringA);
    gl.uniform3fv(state.locations.uRingE, ringE);
    gl.uniform3fv(state.locations.uRingSpeed, ringSpeed);
    gl.uniform3fv(state.locations.uRingColor, colors);
    gl.uniformMatrix3fv(state.locations.uRingMat, false, bases);
    // Read one value back so diagnostics can prove the upload landed on the
    // live program (cos(phi) of ring 0 when healthy).
    const probe = gl.getUniform(state.program, state.locations.uRingMat);
    state.ringUniforms = {
      uploaded: true,
      reason: null,
      basis00: probe ? Number(probe[0]?.toFixed?.(4) ?? probe[0]) : null,
    };
  }

  function initGL() {
    const vertexShader = compileShader(gl.VERTEX_SHADER, PARTICLE_VERTEX_SOURCE);
    const fragmentShader = compileShader(gl.FRAGMENT_SHADER, PARTICLE_FRAGMENT_SOURCE);
    const program = gl.createProgram();
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    gl.deleteShader(vertexShader);
    gl.deleteShader(fragmentShader);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      const log = gl.getProgramInfoLog(program);
      gl.deleteProgram(program);
      throw new Error(`particle program link failed: ${log || 'no log'}`);
    }
    state.program = program;
    gl.useProgram(program);
    // Resolved once (plan section 5.1); render() never queries locations.
    state.locations = {};
    for (const name of UNIFORM_NAMES) {
      state.locations[name] = gl.getUniformLocation(program, name);
    }
    uploadRingUniforms();
    gl.enable(gl.BLEND);
    gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.disable(gl.DEPTH_TEST);
    // Frames are exact redraws, not trails: the buffer clears every render
    // (plan section 5.1 deterministic frame rule).
    gl.clearColor(0.0, 0.0, 0.0, 0.0);
    if (geometry) uploadGeometry(geometry);
  }

  try {
    initGL();
  } catch (error) {
    return unavailable(`shader: ${error?.message || error}`);
  }

  canvas.addEventListener('webglcontextlost', (event) => {
    event.preventDefault();
    state.contextLost = true;
    state.count = 0;
    fail('context-lost');
  });
  canvas.addEventListener('webglcontextrestored', () => {
    state.contextLost = false;
    try {
      initGL();
    } catch (error) {
      fail(`shader: ${error?.message || error}`);
    }
  });

  return {
    available: true,
    backend: 'webgl2',
    reason: null,
    get contextLost() {
      return state.contextLost;
    },
    get count() {
      return state.count;
    },
    resize(width, height) {
      const w = Math.max(1, Math.floor(Number(width) || 1));
      const h = Math.max(1, Math.floor(Number(height) || 1));
      gl.viewport(0, 0, w, h);
      perspectiveMatrix(state.projection, FOV_Y, w / h);
    },
    render(frame, { quality = 1, reducedMotion = false, radiusPx = 0, viewportRect = null } = {}) {
      if (state.contextLost || !state.count) return;
      gl.disable(gl.SCISSOR_TEST);
      gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
      gl.clear(gl.COLOR_BUFFER_BIT);
      const rect = viewportRect || {
        x: 0,
        y: 0,
        width: gl.drawingBufferWidth,
        height: gl.drawingBufferHeight,
      };
      const viewX = Math.max(0, Math.floor(Number(rect.x) || 0));
      const viewY = Math.max(0, Math.floor(Number(rect.y) || 0));
      const viewWidth = Math.max(1, Math.min(gl.drawingBufferWidth - viewX, Math.floor(Number(rect.width) || 1)));
      const viewHeight = Math.max(1, Math.min(gl.drawingBufferHeight - viewY, Math.floor(Number(rect.height) || 1)));
      gl.enable(gl.SCISSOR_TEST);
      gl.scissor(viewX, viewY, viewWidth, viewHeight);
      gl.viewport(viewX, viewY, viewWidth, viewHeight);
      const uniforms = frameToUniforms(
        frame,
        {
          width: viewWidth,
          height: viewHeight,
          ...(radiusPx > 0 ? { radiusPx } : {}),
        },
        { quality, reducedMotion },
        state.uniformsScratch,
      );
      perspectiveMatrix(state.projection, FOV_Y, uniforms.aspect);
      const loc = state.locations;
      gl.useProgram(state.program);
      // uploadGeometry leaves the default VAO bound; the draw must run on ours.
      gl.bindVertexArray(state.vao);
      gl.uniform1f(loc.uTime, uniforms.uTime);
      gl.uniform2f(loc.uViewport, uniforms.uViewportX, uniforms.uViewportY);
      gl.uniform1f(loc.uRadiusPx, uniforms.uRadiusPx);
      gl.uniform1f(loc.uWorldScale, uniforms.uWorldScale);
      gl.uniform1f(loc.uCameraZ, uniforms.uCameraZ);
      gl.uniformMatrix4fv(loc.uProjection, false, state.projection);
      gl.uniform1f(loc.uLow, uniforms.uLow);
      gl.uniform1f(loc.uMid, uniforms.uMid);
      gl.uniform1f(loc.uHigh, uniforms.uHigh);
      gl.uniform1f(loc.uAmbient, uniforms.uAmbient);
      gl.uniform1f(loc.uAnticipation, uniforms.uAnticipation);
      gl.uniform1f(loc.uHold, uniforms.uHold);
      gl.uniform1f(loc.uImpact, uniforms.uImpact);
      gl.uniform1f(loc.uRecoil, uniforms.uRecoil);
      gl.uniform1f(loc.uAftershock, uniforms.uAftershock);
      gl.uniform1f(loc.uTension, uniforms.uTension);
      gl.uniform1f(loc.uHero, uniforms.uHero);
      gl.uniform3f(loc.uLobeWeights, uniforms.uLobeWeights0, uniforms.uLobeWeights1, uniforms.uLobeWeights2);
      gl.uniform3f(loc.uDirection, uniforms.uDirection0, uniforms.uDirection1, uniforms.uDirection2);
      gl.uniform1f(loc.uShockProgress, uniforms.uShockProgress);
      gl.uniform1f(loc.uBeatWave, uniforms.uBeatWave);
      gl.uniform1f(loc.uWaveProgress, uniforms.uWaveProgress);
      gl.uniform1f(loc.uCoreAperture, uniforms.uCoreAperture);
      gl.uniform1f(loc.uDiffusion, uniforms.uDiffusion);
      gl.uniform1f(loc.uBeatExpand, uniforms.uBeatExpand);
      gl.uniform1f(loc.uLobeSplit, uniforms.uLobeSplit);
      gl.uniform1f(loc.uReducedMotion, uniforms.uReducedMotion);
      gl.uniform1f(loc.uQuality, uniforms.uQuality);
      gl.uniform1f(loc.uSceneSpread, uniforms.uSceneSpread);
      gl.uniform1f(loc.uSceneTwist, uniforms.uSceneTwist);
      gl.uniform1f(loc.uSceneFlow, uniforms.uSceneFlow);
      gl.uniform1f(loc.uSceneOrbit, uniforms.uSceneOrbit);
      gl.uniform1f(loc.uSceneVoid, uniforms.uSceneVoid);
      gl.uniform1f(loc.uSceneContrast, uniforms.uSceneContrast);
      gl.uniform1f(loc.uPaletteMix, uniforms.uPaletteMix);
      gl.uniform1f(loc.uPhaseTurn, uniforms.uPhaseTurn);
      gl.uniform1f(loc.uRadialPart, uniforms.uRadialPart);
      gl.uniform1f(loc.uApertureTransition, uniforms.uApertureTransition);
      gl.uniform1f(loc.uFlowShear, uniforms.uFlowShear);
      gl.drawArrays(gl.POINTS, 0, state.count);
      gl.disable(gl.SCISSOR_TEST);
    },
    updateGeometry(nextGeometry) {
      geometry = nextGeometry;
      if (!state.contextLost) uploadGeometry(nextGeometry);
    },
    onFallback(callback) {
      if (typeof callback === 'function') state.fallbackCallbacks.push(callback);
    },
    diagnostics() {
      return {
        backend: 'webgl2',
        available: !state.contextLost && Boolean(state.program),
        reason: null,
        contextLost: state.contextLost,
        count: state.count,
        ringUniforms: state.ringUniforms || null,
      };
    },
    dispose() {
      state.buffers.forEach((buffer) => gl.deleteBuffer(buffer));
      state.buffers = [];
      if (state.vao) gl.deleteVertexArray(state.vao);
      state.vao = null;
      if (state.program) gl.deleteProgram(state.program);
      state.program = null;
      state.count = 0;
    },
  };
}
