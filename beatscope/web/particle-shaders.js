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
// layer (0 body / 1 core / 2 orbit), lobe (0..2), shellRadius, pointSizeBias
layout(location = 2) in vec4 aMeta;

uniform float uTime;
uniform vec2 uViewport;
uniform float uRadiusPx;      // pixel radius of a 1.0-world-unit body
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
uniform float uReducedMotion;
uniform float uQuality;

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

  // --- Ambient circulation (plan section 5.2): continuous in audio time. --
  float drift = sin(uTime * 0.31 + aSeed.x * TAU)
              + 0.42 * sin(uTime * 0.13 + aSeed.y * 11.7);
  float circulation = 0.008 + 0.012 * uAmbient + 0.008 * uLow;
  vec3 position = base + normal * drift * circulation;

  // --- Band separation (plan section 5.3). --------------------------------
  float facing = max(0.0, dot(normal, uDirection));
  float pressure = uLow * (0.025 + 0.055 * uTension);
  position -= uDirection * pressure * selected * facing;

  float twist = (0.018 + 0.070 * uMid) * selected;
  float twistAngle = twist * position.y;
  float ct = cos(twistAngle), st = sin(twistAngle);
  position.xz = mat2(ct, -st, st, ct) * position.xz;

  float fold = sin(aMeta.y * 2.1 + atan(base.z, base.x) * 3.0 + uTime * 0.9 + aSeed.z * 2.0);
  position += normal * fold * uMid * (0.012 + 0.035 * uAftershock);

  // --- Anticipation and hold (plan section 5.4). ---------------------------
  float inward = uAnticipation * selected * (0.035 + 0.035 * uHero);
  position -= normal * inward * facing;

  // --- Impact, recoil, aftershock (plan section 5.5). ----------------------
  vec3 tangent = cross(uDirection, normal);
  float tangentLength = length(tangent);
  tangent = tangentLength > 0.001 ? tangent / tangentLength
                                  : normalize(cross(uDirection, vec3(0.0, 0.0, 1.0)) + vec3(0.001));
  position += uDirection * selected * uImpact * (0.07 + 0.10 * uHero);
  position += tangent * selected * uImpact * (0.04 + 0.06 * uHero);

  // Recoil crosses the resting position once, at <= 25% of the impact.
  position -= uDirection * uRecoil * selected * facing * 0.45;

  // Shock ring: a shader band, not a 2D overlay (plan section 5.5).
  float shock = exp(-pow((length(base) - uShockProgress) * 24.0, 2.0));
  position += normal * shock * uImpact * 0.045;

  // --- Analytic rotation (plan section 5.2); hold nearly freezes it. -------
  float rotationScale = mix(1.0, 0.22, uHold);
  float yaw = (0.09 * uTime + 0.035 * sin(0.17 * uTime)) * rotationScale;
  float pitch = -0.20 + 0.045 * sin(0.13 * uTime);
  float roll = 0.025 * sin(0.11 * uTime) * rotationScale;
  vec3 rotated = rotationXYZ(yaw, pitch, roll) * position;

  vec4 clip = uProjection * vec4(rotated + vec3(0.0, 0.0, -uCameraZ), 1.0);
  gl_Position = clip;

  // --- Point size ----------------------------------------------------------
  float depth = max(0.1, uCameraZ - rotated.z);
  float worldSize;
  float coreGlow = 1.0 + 0.35 * uAnticipation;
  if (layer < 0.5) {
    worldSize = 0.014 + 0.014 * aSeed.y;
  } else if (layer < 1.5) {
    // Core glow stays inside 0.34 * body radius of projected spread.
    worldSize = (0.10 + 0.12 * aSeed.y) * coreGlow * (1.0 - 0.10 * uAnticipation);
  } else {
    worldSize = 0.016 + 0.020 * aSeed.y;
  }
  float pointSize = worldSize * uRadiusPx * uCameraZ / depth * aMeta.w * uQuality;
  gl_PointSize = clamp(pointSize, 1.0, 64.0);

  // --- Colour (plan section 5.6): stable seeded membership. ----------------
  vec3 ink = vec3(0.0902, 0.0902, 0.0745);        // #171713
  vec3 accent = vec3(0.7765, 0.3137, 0.1961);     // #c65032
  vec3 warmWhite = vec3(1.0, 0.9569, 0.8118);     // #fff4cf
  vec3 grey = vec3(0.4667, 0.4588, 0.4235);       // #77756c

  vec3 color = mix(ink, grey * 0.85, step(0.90, aSeed.z));
  color = mix(color, accent, step(0.955, aSeed.w));
  color = mix(color, warmWhite, step(0.985, aSeed.z));

  float depthShade = 0.78 + 0.22 * clamp((rotated.z + 1.0) * 0.5, 0.0, 1.0);
  float alpha;
  if (layer < 0.5) {
    alpha = (0.42 + 0.38 * aSeed.x) * depthShade;
  } else if (layer < 1.5) {
    // Internal warm light; capped at 0.26, or 0.48 in a hero impact.
    float luminance = (0.45 + 0.55 * clamp(uLow * 1.4, 0.0, 1.0)) * coreGlow;
    alpha = min((0.10 + 0.06 * aSeed.x) * luminance, mix(0.26, 0.48, uHero));
    color = mix(warmWhite, accent, 0.22 * uHero + 0.08 * uTension);
  } else {
    float sparkle = 0.75 + 0.25 * sin(uTime * (3.0 + 2.0 * aSeed.y) + aSeed.z * TAU);
    alpha = (0.22 + 0.20 * aSeed.x) * mix(1.0, 0.25, uReducedMotion) * sparkle;
  }
  alpha *= 1.0 + 0.30 * uImpact * step(0.955, aSeed.w);

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
