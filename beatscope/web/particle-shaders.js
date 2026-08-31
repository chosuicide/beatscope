/**
 * GLSL ES 3.00 sources for the WebGL2 particle field (v0.6.1 plan section 5).
 * Static strings only — no runtime substitution, so the shader that ships is
 * the shader that compiles. One draw call renders every particle; all motion
 * is derived from the per-frame uniforms (section 5.1) and the stable
 * per-particle attributes uploaded once from particle-geometry.js.
 */

export const PARTICLE_VERTEX_SOURCE = `#version 300 es
precision highp float;

layout(location = 0) in vec3 aPosition;
layout(location = 1) in vec4 aSeed;
// layer (0 body / 1 core / 2 orbit / 3 ring dot), lobe or ring id,
// shellRadius or ellipse theta, pointSizeBias
layout(location = 2) in vec4 aMeta;

uniform float uTime;
uniform vec2 uViewport;
uniform float uRadiusPx;      // pixel radius of a 1.0-world-unit body
uniform float uWorldScale;    // makes geometry obey uRadiusPx, not canvas height
uniform float uCameraZ;
uniform mat4 uProjection;
uniform float uLow;
uniform float uMid;
uniform float uHigh;
uniform float uAmbient;
uniform float uAnticipation;
uniform float uHold;
uniform float uImpact;
uniform float uRecoil;
uniform float uAftershock;
uniform float uTension;
uniform float uHero;
uniform vec3 uLobeWeights;
uniform vec3 uDirection;
uniform float uShockProgress;
uniform float uBeatWave;
uniform float uWaveProgress;
uniform float uCoreAperture;
uniform float uDiffusion;
uniform float uBeatExpand;
uniform float uLobeSplit;
uniform float uReducedMotion;
uniform float uQuality;
// v0.8 scene uniforms (plan section 11): structure owns the baseline
// composition, transitions enter through bounded abstract channels. The
// shader never branches on driver strings — only on these channels.
uniform float uSceneSpread;        // combined lobe translation, world units
uniform float uSceneTwist;         // scene baseline twist, 0..1 -> 0.28 rad
uniform float uSceneFlow;          // scene baseline macro-flow scale, 0..1
uniform float uSceneOrbit;         // orbit belt width amplitude, 0..1
uniform float uSceneVoid;          // central negative space, 0..1
uniform float uSceneContrast;      // opacity/size contrast, 0..1
uniform float uPaletteMix;         // reviewed palette crossfade, 0..1
uniform float uPhaseTurn;          // transition phase turn, 0..1 -> 0.12 rad
uniform float uRadialPart;         // transition lobe parting, 0..1
uniform float uApertureTransition; // transition core aperture, 0..1
uniform float uFlowShear;          // signed transition flow shear, -1..1
uniform vec3 uRingA;          // ring semi-major axes (world units)
uniform vec3 uRingE;          // ring Y-squash factors
uniform vec3 uRingSpeed;      // signed revolution speed, rad/s
uniform vec3 uRingColor[3];   // stable tint per ring
uniform mat3 uRingMat[3];     // ring basis: Rx(incl) * Rz(phi)

out vec3 vColor;
out float vAlpha;

const float TAU = 6.283185307179586;

mat3 rotationXYZ(float yaw, float pitch, float roll) {
  float cy = cos(yaw), sy = sin(yaw);
  float cp = cos(pitch), sp = sin(pitch);
  float cr = cos(roll), sr = sin(roll);
  mat3 yawM = mat3(cy, 0.0, -sy, 0.0, 1.0, 0.0, sy, 0.0, cy);
  mat3 pitchM = mat3(1.0, 0.0, 0.0, 0.0, cp, sp, 0.0, -sp, cp);
  mat3 rollM = mat3(cr, sr, 0.0, -sr, cr, 0.0, 0.0, 0.0, 1.0);
  return yawM * pitchM * rollM;
}

void main() {
  vec3 base = aPosition;
  vec3 normal = length(base) > 0.0001 ? normalize(base) : vec3(0.0, 1.0, 0.0);
  float layer = aMeta.x;

  vec3 lobeMask = vec3(equal(vec3(aMeta.y), vec3(0.0, 1.0, 2.0)));
  float selected = dot(lobeMask, uLobeWeights);

  // Per-ring constants, resolved once; unused by the three body layers.
  vec3 ringTint = vec3(1.0);
  mat3 ringBasis = mat3(1.0);
  float ringSpeed = 0.0;
  float ringA = 0.0;
  float ringSquash = 1.0;
  float ringPulse = 0.0;
  float ringBandCore = 0.0;
  if (layer > 2.5) {
    if (aMeta.y < 0.5) {
      ringSpeed = uRingSpeed.x; ringA = uRingA.x; ringSquash = uRingE.x;
      ringBasis = uRingMat[0]; ringTint = uRingColor[0];
    } else if (aMeta.y < 1.5) {
      ringSpeed = uRingSpeed.y; ringA = uRingA.y; ringSquash = uRingE.y;
      ringBasis = uRingMat[1]; ringTint = uRingColor[1];
    } else {
      ringSpeed = uRingSpeed.z; ringA = uRingA.z; ringSquash = uRingE.z;
      ringBasis = uRingMat[2]; ringTint = uRingColor[2];
    }
  }

  // --- Analytic rotation (plan section 5.2); hold nearly freezes it. -------
  float rotationScale = mix(1.0, 0.22, uHold);

  // Deformation channels read back by the colour/size sections; ring dots
  // keep them at zero, so every shared term below degenerates to a no-op.
  float waveBand = 0.0;
  float edgeSpark = 0.0;
  float escape = 0.0;
  float streamer = 0.0;
  vec3 position;
  if (layer > 2.5) {
    // --- Orbit-ring revolution (user-approved motion level b): dots ride
    // their own dashed ellipse. The path is static; revolution plus the
    // shared breath/rotation below are its only motion.
    float theta = aMeta.z + ringSpeed * uTime * (1.0 - uReducedMotion);
    // Seed X is a stable cross-track coordinate. Dense samples near zero form
    // the belt's darker spine; samples toward either edge fade into dust.
    float bandCoordinate = (aSeed.x - 0.5) * 2.0;
    ringBandCore = 1.0 - smoothstep(0.08, 1.0, abs(bandCoordinate));
    // uSceneOrbit widens the belt's cross-track scatter without touching the
    // ellipse identity: same path, same speed, same tint (plan section 11).
    float bandOffset = bandCoordinate * (0.060 + 0.035 * ringPulse + uSceneOrbit * 0.045);
    position = ringBasis * vec3(
      (ringA + bandOffset) * cos(theta),
      (ringA * ringSquash + bandOffset) * sin(theta),
      0.0
    );
    // The body owns the strike. Rings receive the same beat later as a
    // three-stage ripple (inner -> middle -> outer), never on the impact frame.
    float ringDelay = 0.12 + 0.16 * aMeta.y;
    ringPulse = clamp(uBeatWave * 1.8
      * exp(-pow((uWaveProgress - ringDelay) * 8.5, 2.0)), 0.0, 1.0);
    position *= 1.0 + ringPulse * (0.045 + 0.015 * aMeta.y);
  } else {
    // --- Ambient circulation (plan section 5.2): continuous in audio time. --
    // Slow motion is shared per lobe, not randomized per particle. The form
    // stays alive at rest without dissolving into independent jitter.
    float lobePhase = aMeta.y * TAU / 3.0;
    float drift = sin(uTime * 0.31 + lobePhase)
                + 0.42 * sin(uTime * 0.13 + lobePhase * 0.73);
    float circulation = 0.008 + 0.012 * uAmbient + 0.008 * uLow;
    position = base + normal * drift * circulation;

    // A beat travels through the body as a density wave. Unlike a scale pulse,
    // this changes local spacing while preserving the overall silhouette.
    float waveFront = mix(-0.72, 0.72, uWaveProgress);
    float waveCoordinate = dot(base, normalize(uDirection));
    waveBand = exp(-pow((waveCoordinate - waveFront) * 8.0, 2.0)) * uBeatWave;
    // Keep the travelling wave as surface detail only. The beat itself is
    // carried by the coherent transforms below, so the body never appears to
    // fire particle-by-particle out of time.
    position -= normal * waveBand * (0.005 + 0.006 * selected);

    // Coherent petal choreography. Every particle in a lobe receives the
    // same shear/open transform on the same frame; three different axes make
    // the silhouette flex and twist instead of behaving like one rigid stamp.
    vec2 lobeAxis = vec2(cos(-TAU * 0.25 + lobePhase), sin(-TAU * 0.25 + lobePhase));
    vec2 lobeTangent = vec2(-lobeAxis.y, lobeAxis.x);
    float alongLobe = dot(position.xy, lobeAxis);
    float idleTurn = sin(uTime * 0.52 + lobePhase) * (0.012 + 0.018 * uMid)
      * (1.0 - uReducedMotion);
    float impactTurn = (aMeta.y - 1.0) * uImpact * 0.060
      + sin(lobePhase + uWaveProgress * TAU) * uAftershock * 0.030;
    float lobeOpen = uImpact * (0.10 + 0.10 * selected)
      + uBeatExpand * 0.055 + abs(uAftershock) * 0.025;
    position.xy += lobeTangent * alongLobe * (idleTurn + impactTurn);
    position.xy += lobeAxis * alongLobe * lobeOpen;
    position.xy += lobeAxis * uImpact * (0.025 + 0.040 * selected);
    // One coherent translation per petal. v0.8 (plan section 10): the scene
    // owns the baseline spread, the heavy beat adds a scene-aware capped
    // amount, and the CPU folds both into uSceneSpread via the combination
    // rule; uRadialPart repeats the same parting language at the slower
    // transition scale. No per-particle temporal offsets are introduced.
    position.xy += lobeAxis * uSceneSpread;
    position.xy += lobeAxis * uRadialPart * 0.10;

    // Scene void (plan section 11): coherent negative space — the core layer
    // retreats outward while the whole body contracts slightly. Every
    // particle of a layer receives the same transform on the same frame.
    if (layer > 0.5 && layer < 1.5) {
      position += normal * uSceneVoid * 0.05;
    }
    position *= 1.0 - uSceneVoid * 0.022;

    // Continuous macro flow: neighbouring particles sample the same smooth
    // spatial field, so the centre rolls and folds as one material instead of
    // three rigid petals or thousands of unrelated points. Audio envelopes
    // only change the field strength; they never change particle timing.
    vec3 flowAxisA = normalize(vec3(
      0.38 + 0.16 * sin(uTime * 0.21),
      0.72,
      0.44 + 0.14 * cos(uTime * 0.17)
    ));
    vec3 flowAxisB = normalize(vec3(-0.56, 0.30 + 0.12 * sin(uTime * 0.19), 0.77));
    float flowBandA = sin(dot(position, vec3(2.15, -1.65, 2.35)) + uTime * 0.74);
    float flowBandB = cos(dot(position, vec3(-1.45, 2.55, 1.25)) - uTime * 0.51);
    vec3 macroFlow = cross(flowAxisA, position) * flowBandA
      + cross(flowAxisB, position) * flowBandB * 0.58;
    float flowAmount = (0.018 + 0.036 * uMid + 0.075 * uBeatWave
      + 0.060 * abs(uAftershock) + uSceneFlow * 0.05) * mix(1.0, 0.24, uReducedMotion);
    position += macroFlow * flowAmount;
    // Signed transition shear rides the same smooth field: the sign flips
    // the fold direction, the magnitude only deepens it (plan section 11).
    position += macroFlow * uFlowShear * 0.045;
    position.z += sin(position.x * 2.8 - position.y * 2.15 + uTime * 0.63)
      * flowAmount * (0.32 + 0.28 * uHigh);

    // Stable edge grains stretch into coherent streamers. They all respond to
    // the same envelope; seed values vary only their length and thickness, not
    // their timing. The macro field bends the tails so they read as flow rather
    // than a radial particle explosion.
    streamer = step(0.82, aSeed.w) * step(layer, 0.5) * (0.38 + 0.62 * selected);
    float streamEnergy = clamp(0.10 + 0.34 * uMid + 0.72 * uBeatWave
      + 0.46 * abs(uAftershock) + 0.16 * uHigh, 0.0, 1.0)
      * mix(1.0, 0.18, uReducedMotion);
    vec3 streamDirection = normalize(
      macroFlow
      + vec3(lobeTangent * (0.55 + 0.30 * selected), (aSeed.z - 0.5) * 0.30)
      + flowAxisA * 0.22
    );
    float streamLength = (0.050 + 0.42 * streamEnergy)
      * (0.48 + 0.52 * aSeed.x) * streamer;
    position += streamDirection * streamLength;

    // --- Band separation (plan section 5.3). --------------------------------
    float facing = max(0.0, dot(normal, uDirection));
    float pressure = uLow * (0.025 + 0.055 * uTension);
    position -= uDirection * pressure * selected * facing;

    float twist = (0.018 + 0.070 * uMid) * selected;
    float twistAngle = twist * position.y;
    float ct = cos(twistAngle), st = sin(twistAngle);
    position.xz = mat2(ct, -st, st, ct) * position.xz;

    // Scene twist (plan section 11): each lobe rotates coherently with an
    // alternating sign; the whole-body transition turn rides uPhaseTurn in
    // the camera yaw below. Both stay inside the plan's radian limits.
    float sceneTwistAngle = uSceneTwist * (aMeta.y - 1.0) * 0.28;
    float cs = cos(sceneTwistAngle), ss = sin(sceneTwistAngle);
    position.xz = mat2(cs, -ss, ss, cs) * position.xz;

    float fold = sin(lobePhase + atan(base.z, base.x) * 1.4 + uTime * 0.9);
    position += normal * fold * uMid * (0.012 + 0.035 * uAftershock);

    // --- Anticipation and hold (plan section 5.4). ---------------------------
    position *= 1.0 - uAnticipation * (0.045 + 0.020 * uHero);
    float inward = uAnticipation * selected * (0.045 + 0.045 * uHero);
    position -= normal * inward * facing;

    // --- Impact, recoil, aftershock (plan section 5.5). ----------------------
    vec3 tangent = cross(uDirection, normal);
    float tangentLength = length(tangent);
    tangent = tangentLength > 0.001 ? tangent / tangentLength
                                    : normalize(cross(uDirection, vec3(0.0, 0.0, 1.0)) + vec3(0.001));
    // The chosen lobe folds and releases for one beat; only a tiny seeded edge
    // population escapes farther, producing fast detail without global chaos.
    position += tangent * selected * uBeatWave * 0.018;
    edgeSpark = step(0.975, aSeed.w) * step(layer, 0.5) * uBeatWave;
    position += (normal * (0.045 + 0.035 * aSeed.x)
      + tangent * (aSeed.z - 0.5) * 0.065) * edgeSpark;
    if (layer > 0.5 && layer < 1.5) {
      position += normal * uCoreAperture * (0.055 + 0.035 * uHero);
      // The aperture transition reuses the core-opening language during the
      // boundary window (plan section 11), bounded like the beat channel.
      position += normal * uApertureTransition * 0.06;
    }

    // Controlled diffusion: at most 4–8% of body particles leave the form,
    // only from the active lobe and always along a reproducible curved path.
    float escapeThreshold = 1.0 - (0.04 + 0.04 * uDiffusion);
    escape = step(escapeThreshold, aSeed.w) * step(layer, 0.5)
      * selected * uDiffusion;
    vec3 escapeDirection = normalize(normal * 0.72 + uDirection * 0.28 + tangent * (aSeed.z - 0.5) * 0.42);
    float escapeDistance = (0.080 + 0.22 * aSeed.x) * escape;
    position += escapeDirection * escapeDistance;
    position += tangent * sin(uWaveProgress * 3.14159265 + aSeed.y * 2.2)
      * escape * 0.045;
    // The strike must visibly break the resting silhouette: the active lobe
    // opens radially first, then travels and shears along the musical axis.
    // Pulse/turbulence events inherit their smaller uImpact amplitude, while
    // burst/hero events receive the full displacement without a global blast.
    // Every body particle receives the same radial strike on the same frame.
    // Lobe weighting adds direction without introducing seeded timing drift.
    float coherentStrike = uImpact * (0.080 + 0.060 * uHero);
    float strikeOpen = uImpact * selected * (0.105 + 0.055 * uHero);
    position += normal * coherentStrike;
    position += normal * strikeOpen;
    position += uDirection * selected * uImpact * (0.11 + 0.14 * uHero);
    position += tangent * selected * uImpact * (0.055 + 0.075 * uHero);

    // Recoil crosses the resting position once, at <= 25% of the impact.
    position *= 1.0 - uRecoil * 0.055;
    position -= uDirection * uRecoil * selected * facing * 0.45;

    // Shock ring: a shader band, not a 2D overlay (plan section 5.5).
    float shock = exp(-pow((length(base) - uShockProgress) * 24.0, 2.0));
    position += normal * shock * uImpact * 0.045;
  }

  // Per-beat breath: after the strike the whole three-lobe form diffuses
  // outward and then contracts back before the next beat. The seeded spread
  // loosens the silhouette without breaking it; scaling after every other
  // deformation keeps lobes, wave and shock coherent.
  // One uniform expand-contract for the complete body. Ring dots breathe less
  // so the visual hierarchy remains centred on the particle instrument.
  float coherentBreath = layer > 2.5 ? 0.0 : 0.20;
  position *= 1.0 + uBeatExpand * coherentBreath;

  // uPhaseTurn (plan section 11): one bounded whole-body turn during the
  // transition window — the "maximum transition twist: 0.12 radians" limit.
  float yaw = (0.09 * uTime + 0.035 * sin(0.17 * uTime)) * rotationScale + uPhaseTurn * 0.12;
  float pitch = -0.20 + 0.045 * sin(0.13 * uTime);
  float roll = 0.025 * sin(0.11 * uTime) * rotationScale;
  vec3 rotated = rotationXYZ(yaw, pitch, roll) * position * uWorldScale;

  vec4 clip = uProjection * vec4(rotated + vec3(0.0, 0.0, -uCameraZ), 1.0);
  gl_Position = clip;

  // --- Point size ----------------------------------------------------------
  float depth = max(0.1, uCameraZ - rotated.z);
  float worldSize;
  float coreGlow = 1.0 + 0.35 * uAnticipation;
  if (layer < 0.5) {
    worldSize = (0.006 + 0.006 * aSeed.y)
      * (1.0 + 0.30 * waveBand + 0.34 * edgeSpark + 0.22 * escape)
      * (1.0 - 0.18 * streamer)
      * (1.0 + 0.16 * uBeatExpand);
  } else if (layer < 1.5) {
    worldSize = (0.012 + 0.018 * aSeed.y) * coreGlow * (1.0 - 0.10 * uAnticipation);
  } else if (layer < 2.5) {
    worldSize = 0.004 + 0.006 * aSeed.y;
  } else {
    // Ring dots must remain legible against both the particle body and the
    // quiet outer field. Keep them visibly heavier than detached particles.
    worldSize = (0.010 + 0.008 * ringBandCore + 0.005 * aSeed.y)
      * (1.0 + 0.42 * ringPulse);
  }
  float pointSize = worldSize * uRadiusPx * uCameraZ / depth * aMeta.w * uQuality;
  // uSceneContrast (plan section 11): seeded point-size contrast inside
  // bounded limits; the seed keeps membership stable across frames.
  pointSize *= 1.0 + uSceneContrast * 0.18 * (aSeed.y * 2.0 - 1.0);
  gl_PointSize = clamp(pointSize, 0.8, 12.0);

  // --- Colour (plan section 5.6): stable seeded membership. ----------------
  vec3 ink = vec3(0.0902, 0.0902, 0.0745);        // #171713
  vec3 accent = vec3(0.7765, 0.3137, 0.1961);     // #c65032
  vec3 warmWhite = vec3(1.0, 0.9569, 0.8118);     // #fff4cf
  vec3 grey = vec3(0.4667, 0.4588, 0.4235);       // #77756c

  vec3 color;
  if (layer > 2.5) {
    // Ring dots carry their ring's stable tint; a sparse seeded population
    // brightens toward warm white so the dashes never read as flat.
    color = mix(ringTint, warmWhite,
      clamp((1.0 - ringBandCore) * 0.12
        + step(0.975, aSeed.z) * 0.35 + ringPulse * 0.34, 0.0, 0.68));
  } else {
    color = mix(ink, grey * 0.85, step(0.90, aSeed.z));
    color = mix(color, accent, step(0.955, aSeed.w));
    color = mix(color, warmWhite, step(0.985, aSeed.z));
    color = mix(color, accent, waveBand * (0.12 + 0.18 * selected));
    color = mix(color, warmWhite, edgeSpark * 0.58);
    color = mix(color, ink, escape * 0.72);
    color = mix(color, accent, streamer * (0.10 + 0.16 * uHigh));
  }
  // A moving negative-space incision travels through the active lobe. White
  // particles disappear into the paper, while escaped particles stay dark.
  float negativeSeed = step(0.44, aSeed.x) * step(layer, 0.5);
  float negativeCut = clamp(waveBand * selected * negativeSeed
    * (0.72 + 0.28 * uImpact), 0.0, 1.0);
  color = mix(color, vec3(1.0), negativeCut * 0.92);

  // uPaletteMix (plan section 11): the only palette crossfade — body colors
  // warm toward the reviewed accent/warm pair, ring dots shift a little.
  // Bounded so family identity stays recognizable at every mix level.
  color = mix(color, mix(accent, warmWhite, 0.35),
    uPaletteMix * (layer > 2.5 ? 0.10 : 0.30));

  float depthShade = 0.78 + 0.22 * clamp((rotated.z + 1.0) * 0.5, 0.0, 1.0);
  float alpha;
  if (layer < 0.5) {
    alpha = (0.28 + 0.42 * aSeed.x) * depthShade;
  } else if (layer < 1.5) {
    // Internal warm light; capped at 0.26, or 0.48 in a hero impact.
    float luminance = (0.45 + 0.55 * clamp(uLow * 1.4, 0.0, 1.0)) * coreGlow;
    alpha = min((0.055 + 0.045 * aSeed.x) * luminance, mix(0.16, 0.30, uHero));
    color = mix(accent, warmWhite, 0.42 + 0.18 * (1.0 - uHero));
  } else if (layer < 2.5) {
    float sparkle = 0.75 + 0.25 * sin(uTime * (3.0 + 2.0 * aSeed.y) + aSeed.z * TAU);
    alpha = (0.07 + 0.11 * aSeed.x) * mix(1.0, 0.25, uReducedMotion) * sparkle;
  } else {
    // Rings reach outside the body's depth range; fade the far half so the
    // back of each orbit reads behind the sphere (the mockup's depth cue).
    float ringDepth = 0.38 + 0.62 * clamp((rotated.z + 2.3) / 4.6, 0.0, 1.0);
    alpha = (0.16 + 0.46 * ringBandCore + 0.12 * aSeed.y)
      * ringDepth * (1.0 + 0.52 * ringPulse);
  }
  float bodyResponse = 1.0 - step(2.5, layer);
  alpha *= 1.0 + 0.30 * uImpact * step(0.955, aSeed.w) * bodyResponse;
  alpha *= 1.0 + (0.34 * waveBand + 0.48 * edgeSpark + 0.28 * escape) * bodyResponse;
  alpha *= 1.0 - 0.14 * streamer;
  alpha *= 1.0 + 0.18 * uBeatExpand * bodyResponse;
  alpha *= 1.0 - negativeCut * 0.36;
  // uSceneContrast (plan section 11): seeded alpha contrast for body layers,
  // clamped with vAlpha below so the accent never blows out.
  alpha *= 1.0 + uSceneContrast * 0.26 * (aSeed.x * 2.0 - 1.0) * bodyResponse;

  vColor = color;
  vAlpha = clamp(alpha, 0.0, 1.0);
}
`;

export const PARTICLE_FRAGMENT_SOURCE = `#version 300 es
precision highp float;

in vec3 vColor;
in float vAlpha;
out vec4 outColor;

void main() {
  vec2 q = gl_PointCoord * 2.0 - 1.0;
  float d = dot(q, q);
  if (d > 1.0) discard;
  float alpha = smoothstep(1.0, 0.45, d) * vAlpha;
  outColor = vec4(vColor, alpha);
}
`;
