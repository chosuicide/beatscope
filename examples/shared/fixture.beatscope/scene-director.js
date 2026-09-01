/**
 * BeatScope Scene Director (v0.8 plan section 9): seek-safe structure
 * orchestration shared verbatim by the browser, the MCP worker, and the
 * exported runtime.
 *
 * The director answers one question — "what does the screen look like at
 * audio time t?" — purely from the compiled visual artifacts:
 *
 *   const director = createSceneDirector(recipe, timeline);
 *   const frame = director.at(audioTime);
 *
 * `at()` returns one frozen frame holding the owning scene, the active
 * transition envelope (stage approach/cross/settle/idle), the interpolated
 * composition vector, and bounded abstract treatment channels. Every query
 * is a closed-form function of (artifacts, time): no clocks, no randomness,
 * no springs, no audio/DOM access, no order-dependent caching. Seeking to
 * any time always reproduces the same frame, so pause/seek/replay and the
 * offline renderer agree by construction.
 *
 * Scene ownership matches `runtime.structuralSegmentAt`: interior scene
 * ends are exclusive, the next scene owns the exact boundary, the final
 * scene owns the exact duration, and times before 0 clamp to the first
 * scene at phase 0. Times after duration return null unless
 * `options.clamp` is set, in which case the final scene reports phase 1.
 *
 * Reduced motion (`options.reducedMotion`) scales spread/twist/flow
 * transitions and motion channels to 20% and the boundary impulse to 15%,
 * while palette/contrast crossfades and every timing fact stay identical;
 * no channel is ever removed from the returned frame.
 */

const RECIPE_SCHEMA = 'beatscope-visual-recipe-1';
const TIMELINE_SCHEMA = 'beatscope-visual-timeline-1';

const COMPOSITION_KEYS = ['spread', 'twist', 'flow', 'orbit', 'void', 'contrast'];
const TREATMENTS = new Set(['phase-turn', 'radial-part', 'aperture', 'flow-shear', 'cross-settle']);
const DRIVERS = new Set(['harmony', 'rhythm', 'energy', 'timbre', 'neutral']);

// Reduced-motion scales (plan section 9.6): transition motion at 20%,
// boundary impulse at 15%. Contrast and palette keep crossfading.
const REDUCED_TRANSITION_SCALE = 0.2;
const REDUCED_IMPUSE_SCALE = 0.15;
const REDUCED_TRANSITION_KEYS = { spread: true, twist: true, flow: true };

const DEFAULT_PALETTE_MIX_CAP = 0.42;

const clamp01 = (value) => Math.max(0, Math.min(1, Number(value) || 0));
const lerp = (from, to, amount) => from + (to - from) * amount;

function finiteNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function smoothstep01(p) {
  const clamped = clamp01(p);
  return clamped * clamped * (3 - 2 * clamped);
}

function smoothstepBetween(edge0, edge1, value) {
  const span = edge1 - edge0;
  if (!(span > 0)) return value >= edge1 ? 1 : 0;
  return smoothstep01((value - edge0) / span);
}

/** Last index with sortedTimes[index] <= time, or -1 (binary search). */
function previousIndex(sortedTimes, time) {
  let low = 0;
  let high = sortedTimes.length - 1;
  let answer = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (sortedTimes[middle] <= time) {
      answer = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return answer;
}

/** Deterministic ±1 flow-shear direction derived from the transition id. */
function signForText(text) {
  let hash = 0x811c9dc5;
  const source = String(text ?? '');
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0) % 2 === 0 ? 1 : -1;
}

function reject(message) {
  throw new TypeError(`scene director: ${message}`);
}

function coerceComposition(values, label) {
  const source = values && typeof values === 'object' && !Array.isArray(values) ? values : {};
  const composition = {};
  for (const key of COMPOSITION_KEYS) {
    composition[key] = clamp01(finiteNumber(source[key], 0));
  }
  return Object.freeze(composition);
}

function coerceScene(scene, index) {
  if (!scene || typeof scene !== 'object' || Array.isArray(scene)) {
    reject(`scenes[${index}] must be an object`);
  }
  if (typeof scene.id !== 'string' || !scene.id) reject(`scenes[${index}].id must be a string`);
  if (typeof scene.family !== 'string' || !scene.family) {
    reject(`scenes[${index}].family must be a string`);
  }
  const startTime = finiteNumber(scene.start_time, NaN);
  const endTime = finiteNumber(scene.end_time, NaN);
  if (!Number.isFinite(startTime) || !Number.isFinite(endTime) || endTime < startTime) {
    reject(`scenes[${index}] must carry finite increasing start_time/end_time`);
  }
  const variant = Number(scene.variant);
  if (!Number.isInteger(variant) || variant < 0) {
    reject(`scenes[${index}].variant must be a non-negative integer`);
  }
  const deltaSource =
    scene.variant_delta && typeof scene.variant_delta === 'object' ? scene.variant_delta : {};
  const variantDelta = {};
  // Deltas are signed magnitudes: keep the sign, bound the magnitude.
  for (const key of COMPOSITION_KEYS) {
    const raw = finiteNumber(deltaSource[key], 0);
    variantDelta[key] = Math.sign(raw) * Math.min(Math.abs(raw), 1);
  }
  return Object.freeze({
    id: scene.id,
    segmentId: scene.segment_id ?? null,
    segmentIndex: Math.trunc(finiteNumber(scene.segment_index, index)),
    family: scene.family,
    variant,
    label: typeof scene.label === 'string' ? scene.label : scene.family,
    motif: typeof scene.motif === 'string' ? scene.motif : null,
    startTime,
    endTime,
    variantDelta: Object.freeze(variantDelta),
  });
}

function coerceTransition(transition, index) {
  if (!transition || typeof transition !== 'object' || Array.isArray(transition)) {
    reject(`transitions[${index}] must be an object`);
  }
  if (typeof transition.id !== 'string' || !transition.id) {
    reject(`transitions[${index}].id must be a string`);
  }
  const time = finiteNumber(transition.time, NaN);
  const lead = finiteNumber(transition.lead_seconds, NaN);
  const settle = finiteNumber(transition.settle_seconds, NaN);
  const strength = finiteNumber(transition.strength, NaN);
  if (!Number.isFinite(time)) reject(`transitions[${index}].time must be a finite number`);
  if (!Number.isFinite(lead) || lead <= 0) {
    reject(`transitions[${index}].lead_seconds must be a positive number`);
  }
  if (!Number.isFinite(settle) || settle <= 0) {
    reject(`transitions[${index}].settle_seconds must be a positive number`);
  }
  if (!Number.isFinite(strength) || strength < 0 || strength > 1) {
    reject(`transitions[${index}].strength must be a number in 0..1`);
  }
  const treatment = typeof transition.treatment === 'string' ? transition.treatment : '';
  if (!TREATMENTS.has(treatment)) {
    reject(`transitions[${index}].treatment ${JSON.stringify(treatment)} is not a known treatment`);
  }
  const driver = typeof transition.driver === 'string' ? transition.driver : '';
  if (!DRIVERS.has(driver)) {
    reject(`transitions[${index}].driver ${JSON.stringify(driver)} is not a known driver`);
  }
  return Object.freeze({
    id: transition.id,
    boundaryBar: Number.isInteger(transition.boundary_bar) ? transition.boundary_bar : null,
    time,
    fromScene: typeof transition.from_scene === 'string' ? transition.from_scene : null,
    toScene: typeof transition.to_scene === 'string' ? transition.to_scene : null,
    treatment,
    driver,
    strength,
    leadSeconds: lead,
    settleSeconds: settle,
  });
}

/**
 * Validate and freeze the artifact pair. Rejects malformed artifacts with
 * actionable TypeError messages; never mutates the inputs.
 */
export function normalizeVisualArtifacts(recipe, timeline) {
  if (!recipe || typeof recipe !== 'object' || Array.isArray(recipe)) {
    reject('recipe must be an object');
  }
  if (!timeline || typeof timeline !== 'object' || Array.isArray(timeline)) {
    reject('timeline must be an object');
  }
  if (recipe.schema !== RECIPE_SCHEMA) {
    reject(`recipe schema must be "${RECIPE_SCHEMA}", got ${JSON.stringify(recipe.schema)}`);
  }
  if (timeline.schema !== TIMELINE_SCHEMA) {
    reject(`timeline schema must be "${TIMELINE_SCHEMA}", got ${JSON.stringify(timeline.schema)}`);
  }
  if (!recipe.families || typeof recipe.families !== 'object' || Array.isArray(recipe.families)) {
    reject('recipe must declare a families object');
  }
  if (!Array.isArray(timeline.scenes) || timeline.scenes.length === 0) {
    reject('timeline must hold at least one scene');
  }
  if (!Array.isArray(timeline.transitions)) {
    reject('timeline transitions must be a list');
  }

  const mode = timeline.mode === 'legacy' || recipe.mode === 'legacy' ? 'legacy' : 'structure';
  const duration = finiteNumber(timeline.duration, NaN);
  if (!Number.isFinite(duration) || duration < 0) {
    reject('timeline.duration must be a non-negative finite number');
  }

  const families = {};
  for (const [name, entry] of Object.entries(recipe.families)) {
    if (!entry || typeof entry !== 'object') reject(`families.${name} must be an object`);
    families[name] = Object.freeze({
      motif: typeof entry.motif === 'string' ? entry.motif : null,
      paletteSlot: Number.isInteger(entry.palette_slot) ? entry.palette_slot : 0,
      composition: coerceComposition(entry.composition, `families.${name}.composition`),
    });
  }
  for (const scene of timeline.scenes) {
    if (!families[scene?.family]) {
      reject(`timeline scene family ${JSON.stringify(scene?.family)} is not declared in the recipe`);
    }
  }

  const scenes = Object.freeze(timeline.scenes.map(coerceScene));
  const transitions = Object.freeze(timeline.transitions.map((entry, index) => coerceTransition(entry, index)));
  // Transitions must connect adjacent scenes so positional interpolation is
  // exact; the v0.8 compiler guarantees this and malformed exports fail here.
  transitions.forEach((transition, index) => {
    const from = scenes[index];
    const to = scenes[index + 1];
    if (!from || !to || transition.fromScene !== from.id || transition.toScene !== to.id) {
      reject(`transitions[${index}] must connect scenes[${index}] and scenes[${index + 1}] in order`);
    }
    if (transition.time < from.endTime - 1e-6 || transition.time > to.startTime + 1e-6) {
      reject(`transitions[${index}].time must sit on the scene boundary`);
    }
  });

  const tokens = recipe.tokens && typeof recipe.tokens === 'object' ? recipe.tokens : {};
  const motion = tokens.motion && typeof tokens.motion === 'object' ? tokens.motion : {};
  const paletteMixCap = clamp01(finiteNumber(motion.max_palette_mix, DEFAULT_PALETTE_MIX_CAP));

  return Object.freeze({
    mode,
    duration,
    paletteMixCap,
    families: Object.freeze(families),
    scenes,
    transitions,
  });
}

/**
 * One-time binary indexes (plan section 9.2): every per-frame query is
 * O(log S). `timeline` must be the normalized timeline (or the raw one —
 * the same numeric fields are read either way).
 */
export function buildSceneIndexes(timeline) {
  const source = timeline && typeof timeline === 'object' ? timeline : {};
  const scenes = Array.isArray(source.scenes) ? source.scenes : [];
  const transitions = Array.isArray(source.transitions) ? source.transitions : [];
  const familyByName = {};
  for (const scene of scenes) {
    if (scene && typeof scene.family === 'string' && !(scene.family in familyByName)) {
      familyByName[scene.family] = typeof scene.motif === 'string' ? scene.motif : null;
    }
  }
  return Object.freeze({
    sceneStartTimes: Object.freeze(
      scenes.map((scene) => finiteNumber(scene?.startTime ?? scene?.start_time, 0)),
    ),
    sceneEndTimes: Object.freeze(
      scenes.map((scene) => finiteNumber(scene?.endTime ?? scene?.end_time, 0)),
    ),
    transitionTimes: Object.freeze(transitions.map((transition) => finiteNumber(transition?.time, 0))),
    transitionStartTimes: Object.freeze(
      transitions.map((transition) => {
        const time = finiteNumber(transition?.time, 0);
        return time - Math.max(
          0,
          finiteNumber(transition?.leadSeconds ?? transition?.lead_seconds, 0),
        );
      }),
    ),
    transitionEndTimes: Object.freeze(
      transitions.map((transition) => {
        const time = finiteNumber(transition?.time, 0);
        return time + Math.max(
          0,
          finiteNumber(transition?.settleSeconds ?? transition?.settle_seconds, 0),
        );
      }),
    ),
    familyByName: Object.freeze(familyByName),
  });
}

/** Resolved composition of one scene: family base plus its variant delta. */
function sceneComposition(artifacts, scene) {
  const entry = artifacts.families[scene.family];
  const base = entry ? entry.composition : coerceComposition(null);
  const composition = {};
  for (const key of COMPOSITION_KEYS) {
    composition[key] = clamp01(base[key] + scene.variantDelta[key]);
  }
  return composition;
}

const ZERO_CHANNELS = Object.freeze({
  phaseTurn: 0,
  radialPart: 0,
  aperture: 0,
  flowShear: 0,
  contrastHit: 0,
});

function zeroChannels() {
  return { phaseTurn: 0, radialPart: 0, aperture: 0, flowShear: 0, contrastHit: 0 };
}

/**
 * The transition state at `time`, or the idle block. Windows are half-open
 * around the boundary: [boundary - lead, boundary), the exact boundary
 * itself, then (boundary, boundary + settle]. When both neighbors could
 * claim the time (never true for compiler artifacts, which clamp against
 * the half gap), the later boundary wins.
 */
function transitionStateAt(artifacts, indexes, time) {
  const transitions = artifacts.transitions;
  if (!transitions.length) {
    return { stage: 'idle', transition: null, approach: 0, cross: 0, settle: 0, impulse: 0, settleProgress: 0, index: -1 };
  }
  const boundaryIndex = previousIndex(indexes.transitionTimes, time);
  const nextIndex = boundaryIndex + 1;
  if (nextIndex < transitions.length) {
    const transition = transitions[nextIndex];
    if (time >= transition.time - transition.leadSeconds && time < transition.time) {
      return {
        stage: 'approach',
        transition,
        approach: smoothstepBetween(transition.time - transition.leadSeconds, transition.time, time),
        cross: 0,
        settle: 0,
        impulse: 0,
        settleProgress: 0,
        index: nextIndex,
      };
    }
  }
  if (boundaryIndex >= 0) {
    const transition = transitions[boundaryIndex];
    if (time === transition.time) {
      return {
        stage: 'cross',
        transition,
        approach: 1,
        cross: transition.strength,
        settle: 0,
        impulse: transition.strength,
        settleProgress: 0,
        index: boundaryIndex,
      };
    }
    if (time > transition.time && time <= transition.time + transition.settleSeconds) {
      const settleProgress = clamp01((time - transition.time) / transition.settleSeconds);
      return {
        stage: 'settle',
        transition,
        approach: 1,
        cross: 0,
        settle: 1 - smoothstep01(settleProgress),
        impulse: 0,
        settleProgress,
        index: boundaryIndex,
      };
    }
  }
  return { stage: 'idle', transition: null, approach: 0, cross: 0, settle: 0, impulse: 0, settleProgress: 0, index: -1 };
}

/** Scene ownership identical to `runtime.structuralSegmentAt` (section 9.3). */
function sceneStateAt(artifacts, indexes, time, clampAfterEnd) {
  const scenes = artifacts.scenes;
  if (!scenes.length) return null;
  if (time < 0) {
    const first = scenes[0];
    return { scene: first, index: 0, phase: 0 };
  }
  let index = previousIndex(indexes.sceneStartTimes, time);
  if (index < 0) index = 0;
  const scene = scenes[index];
  const isFinal = index === scenes.length - 1;
  if (!isFinal && time >= scene.endTime) return null;
  if (isFinal && time > scene.endTime) {
    if (!clampAfterEnd) return null;
    return { scene, index, phase: 1 };
  }
  const length = Math.max(1e-9, scene.endTime - scene.startTime);
  return { scene, index, phase: clamp01((time - scene.startTime) / length) };
}

/**
 * The owning scene block, or null. `options.clamp` also reports the final
 * scene at phase 1 after the duration; `options.reducedMotion` is accepted
 * for signature parity and does not change scene identity or timing facts.
 */
export function sceneAt(recipe, timeline, indexes, time, options = {}) {
  const artifacts = normalizeVisualArtifacts(recipe, timeline);
  const resolvedIndexes = indexes || buildSceneIndexes(timeline);
  const state = sceneStateAt(artifacts, resolvedIndexes, Number(time) || 0, options.clamp === true);
  if (!state) return null;
  return Object.freeze({
    id: state.scene.id,
    segmentId: state.scene.segmentId,
    family: state.scene.family,
    variant: state.scene.variant,
    label: state.scene.label,
    motif: state.scene.motif,
    phase: state.phase,
  });
}

/**
 * The active transition block (with treatment channels), or null when the
 * time sits outside every transition window.
 */
export function transitionAt(recipe, timeline, indexes, time, options = {}) {
  const artifacts = normalizeVisualArtifacts(recipe, timeline);
  const resolvedIndexes = indexes || buildSceneIndexes(timeline);
  const reducedMotion = options.reducedMotion === true;
  const state = transitionStateAt(artifacts, resolvedIndexes, Number(time) || 0);
  if (state.stage === 'idle') return null;
  const channels = treatmentChannels(state, reducedMotion);
  return Object.freeze({
    id: state.transition.id,
    treatment: state.transition.treatment,
    driver: state.transition.driver,
    strength: state.transition.strength,
    stage: state.stage,
    approach: state.approach,
    cross: state.cross,
    settle: state.settle,
    impulse: state.impulse * (reducedMotion ? REDUCED_IMPUSE_SCALE : 1),
    channels: Object.freeze(channels),
  });
}

/** Bounded abstract channels (plan section 9.5); renderers never branch on
 * driver strings. Motion channels scale to 20% under reduced motion; the
 * contrast accent keeps crossfading. */
function treatmentChannels(state, reducedMotion) {
  const channels = zeroChannels();
  const { transition, stage } = state;
  if (!transition || stage === 'idle') return channels;
  const motionScale = reducedMotion ? REDUCED_TRANSITION_SCALE : 1;
  const envelope = stage === 'approach' ? state.approach : stage === 'cross' ? 1 : state.settle;
  if (transition.treatment === 'phase-turn') channels.phaseTurn = envelope * motionScale;
  if (transition.treatment === 'radial-part') channels.radialPart = envelope * motionScale;
  if (transition.treatment === 'aperture') channels.aperture = envelope * motionScale;
  if (transition.treatment === 'flow-shear') {
    channels.flowShear = envelope * signForText(transition.id) * motionScale;
  }
  if (stage === 'cross') channels.contrastHit = transition.strength;
  else if (stage === 'settle') channels.contrastHit = transition.strength * state.settle;
  return channels;
}

function frozenFrame(artifacts, time, sceneState, transitionState, composition, channels, reducedMotion) {
  const transition = transitionState.transition;
  return Object.freeze({
    time,
    mode: artifacts.mode,
    scene: Object.freeze({
      id: sceneState.scene.id,
      segmentId: sceneState.scene.segmentId,
      family: sceneState.scene.family,
      variant: sceneState.scene.variant,
      label: sceneState.scene.label,
      motif: sceneState.scene.motif,
      phase: sceneState.phase,
    }),
    transition: Object.freeze({
      id: transition ? transition.id : null,
      treatment: transition ? transition.treatment : null,
      driver: transition ? transition.driver : null,
      strength: transition ? transition.strength : 0,
      stage: transitionState.stage,
      approach: transitionState.approach,
      cross: transitionState.cross,
      settle: transitionState.settle,
      impulse: transitionState.impulse * (reducedMotion ? REDUCED_IMPUSE_SCALE : 1),
      channels: Object.freeze(channels),
    }),
    composition: Object.freeze(composition),
  });
}

function buildFrame(artifacts, indexes, time, reducedMotion, clampAfterEnd) {
  const sceneState = sceneStateAt(artifacts, indexes, time, clampAfterEnd);
  const transitionState = transitionStateAt(artifacts, indexes, time);
  if (!sceneState) return null;

  const sceneCompositionValues = sceneComposition(artifacts, sceneState.scene);

  // Composition interpolation (plan section 9.4): before the boundary the
  // current scene stays visually dominant (mix 0); across the settle window
  // values lerp toward the next scene with a smoothstep mix. Composition
  // itself is continuous — the boundary impulse is the only jump.
  const composition = { ...sceneCompositionValues };
  if (transitionState.stage === 'settle' || transitionState.stage === 'cross') {
    const from = artifacts.scenes[transitionState.index];
    const to = artifacts.scenes[transitionState.index + 1];
    if (from && to) {
      const fromComposition = sceneComposition(artifacts, from);
      const toComposition = sceneComposition(artifacts, to);
      const mix = smoothstep01(transitionState.settleProgress);
      for (const key of COMPOSITION_KEYS) {
        const scale =
          reducedMotion && REDUCED_TRANSITION_KEYS[key] ? REDUCED_TRANSITION_SCALE : 1;
        composition[key] = clamp01(lerp(fromComposition[key], toComposition[key], mix * scale));
      }
    }
  }
  composition.paletteMix = transitionState.stage === 'settle' || transitionState.stage === 'cross'
    ? smoothstep01(transitionState.settleProgress) * artifacts.paletteMixCap
    : 0;

  const channels = treatmentChannels(transitionState, reducedMotion);
  return frozenFrame(artifacts, time, sceneState, transitionState, composition, channels, reducedMotion);
}

/**
 * Create the per-playback director: artifacts and indexes are built once,
 * `at(time)` stays O(log S) per query and returns one frozen frame.
 */
export function createSceneDirector(recipe, timeline, options = {}) {
  const artifacts = normalizeVisualArtifacts(recipe, timeline);
  const indexes = buildSceneIndexes(timeline);
  const settings = Object.freeze({
    reducedMotion: options.reducedMotion === true,
    clamp: options.clamp === true,
  });
  return Object.freeze({
    at: (time, queryOptions = null) => {
      const reducedMotion = queryOptions?.reducedMotion === undefined
        ? settings.reducedMotion
        : queryOptions.reducedMotion === true;
      const clampAfterEnd = queryOptions?.clamp === undefined
        ? settings.clamp
        : queryOptions.clamp === true;
      return buildFrame(
        artifacts,
        indexes,
        Number(time) || 0,
        reducedMotion,
        clampAfterEnd,
      );
    },
    options: settings,
    recipe,
    timeline,
    indexes,
  });
}
