// Glitch/voxel beat-synced visual for 10.mp3, driven by the BeatScope handoff package.
//
// The clock contract and the mapping discipline are the same as engine/visual-engine.js:
//   - getBeatScopeFrame(time) is the only animation input; the audio is never re-analysed
//   - renderAt(seconds) is pure — pause, seek, replay and single-frame render agree
//   - family identity is stable: family A/B/C each own a set of background worlds, so a
//     repeated family returns to the same visual material
//   - at a structural boundary at most two channels move (a hard world cut + one burst)
//
// Mapping used here (authored, not from the package's own scene orchestration):
//   bar/beat      -> hard background cut every 2 beats (the 卡点 grid)
//   family        -> which set of background worlds the cut cycles through
//   onset/accent  -> glitch burst: slice displacement, RGB split, invert flash
//   low/mid/high  -> background field intensity, dither density, HUD meter
//   beatPhase     -> 2% pump on the voxel diorama
//   structure     -> boundary = forced world change + full-frame burst


// family -> ordered background worlds (identity stays stable across repetitions)
import { WORLD_SETS } from './mv-plan.mjs';

// Only used when a caller renders without a plan (the plan owns the real cut
// list): every world some family can show, in family order.
const FALLBACK_SET = [...new Set(Object.values(WORLD_SETS).flat())];

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

// ---- voxel diorama (same floating archipelago as the reference piece) ----------------
const BOXES = [
  [-3.2, 0.6, 2.6, 1.8, 1.1, 1.8],
  [-1.8, 0.5, 3.6, 0.9, 0.7, 0.9],
  [-2.6, 2.4, 1.4, 1.1, 0.9, 1.1],
  [-0.4, 0.6, 2.0, 1.2, 1.8, 1.2],
  [1.2, 0.6, 2.9, 0.9, 0.9, 0.9],
  [0.4, 3.4, 0.2, 0.8, 0.6, 0.8],
  [2.6, 3.5, -1.2, 3.0, 0.55, 2.0],
  [1.7, 1.5, -1.9, 1.2, 1.2, 1.2],
  [3.6, 1.6, 1.0, 0.8, 0.8, 0.8],
  [2.8, 0.6, 3.0, 1.9, 1.4, 1.9],
  [1.7, 0.6, 1.2, 0.8, 1.2, 0.8],
  [-2.8, 3.0, -1.6, 1.0, 0.8, 1.0],
  [-3.4, 4.2, -2.0, 0.5, 0.5, 0.5],
  [-1.7, 3.8, -0.9, 0.42, 0.42, 0.42],
  [-0.7, 1.8, -2.4, 0.22, 3.2, 0.22],
  [0.1, 2.4, -2.0, 0.22, 2.4, 0.22],
  [-0.4, 4.9, 0.4, 0.7, 0.45, 0.7],
  [0.8, 5.3, 0.0, 0.36, 0.36, 0.36],
  [-1.5, 5.4, 0.2, 0.4, 0.4, 0.4],
];

const FACES = [
  { n: [1, 0, 0], u: [0, 0, -1], v: [0, 1, 0] },
  { n: [-1, 0, 0], u: [0, 0, 1], v: [0, 1, 0] },
  { n: [0, 1, 0], u: [1, 0, 0], v: [0, 0, -1] },
  { n: [0, -1, 0], u: [1, 0, 0], v: [0, 0, 1] },
  { n: [0, 0, 1], u: [1, 0, 0], v: [0, 1, 0] },
  { n: [0, 0, -1], u: [-1, 0, 0], v: [0, 1, 0] },
];
const MASKS = [
  [1, 0, 1], [1, 0, 1], [1, 0, 1],
  [1, 1, 0], [1, 1, 0], [1, 1, 0],
];

function buildGeometry() {
  const verts = [];
  let minY = Infinity, maxY = -Infinity;
  for (let b = 0; b < BOXES.length; b++) {
    const [cx, base, cz, sx, sy, sz] = BOXES[b];
    const cy = base + sy / 2;
    minY = Math.min(minY, base);
    maxY = Math.max(maxY, base + sy);
    const hx = sx / 2, hy = sy / 2, hz = sz / 2;
    for (let f = 0; f < 6; f++) {
      const fc = FACES[f];
      const pick = (c) => (fc.u[0] !== 0 ? hx : fc.u[1] !== 0 ? hy : hz);
      const pickV = (c) => (fc.v[0] !== 0 ? hx : fc.v[1] !== 0 ? hy : hz);
      const pickN = (c) => (fc.n[0] !== 0 ? hx : fc.n[1] !== 0 ? hy : hz);
      const ux = fc.u[0] * pick(), uy = fc.u[1] * pick(), uz = fc.u[2] * pick();
      const vx = fc.v[0] * pickV(), vy = fc.v[1] * pickV(), vz = fc.v[2] * pickV();
      const ox = fc.n[0] * pickN(), oy = fc.n[1] * pickN(), oz = fc.n[2] * pickN();
      const c = [cx + ox, cy + oy, cz + oz];
      const corners = [
        [c[0] - ux - vx, c[1] - uy - vy, c[2] - uz - vz],
        [c[0] + ux - vx, c[1] + uy - vy, c[2] + uz - vz],
        [c[0] + ux + vx, c[1] + uy + vy, c[2] + uz + vz],
        [c[0] - ux + vx, c[1] - uy + vy, c[2] - uz + vz],
      ];
      const tri = [0, 1, 2, 0, 2, 3];
      const bary = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
      for (let k = 0; k < 6; k++) {
        const p = corners[tri[k]];
        const ba = bary[k % 3];
        const m = MASKS[k];
        verts.push(
          p[0], p[1], p[2],
          fc.n[0], fc.n[1], fc.n[2],
          ba[0], ba[1], ba[2],
          m[0], m[1], m[2]
        );
      }
    }
  }
  return { verts, centerY: (minY + maxY) / 2 };
}

// ---- matrices -------------------------------------------------------------------------
function ortho(half, near, far) {
  return new Float32Array([
    1 / half, 0, 0, 0,
    0, 1 / half, 0, 0,
    0, 0, -2 / (far - near), 0,
    0, 0, -(far + near) / (far - near), 1,
  ]);
}
function lookAt(eye, target, up) {
  let zx = eye[0] - target[0], zy = eye[1] - target[1], zz = eye[2] - target[2];
  const zl = Math.hypot(zx, zy, zz);
  zx /= zl; zy /= zl; zz /= zl;
  let xx = up[1] * zz - up[2] * zy;
  let xy = up[2] * zx - up[0] * zz;
  let xz = up[0] * zy - up[1] * zx;
  const xl = Math.hypot(xx, xy, xz) || 1;
  xx /= xl; xy /= xl; xz /= xl;
  const yx = zy * xz - zz * xy;
  const yy = zz * xx - zx * xz;
  const yz = zx * xy - zy * xx;
  return new Float32Array([
    xx, yx, zx, 0,
    xy, yy, zy, 0,
    xz, yz, zz, 0,
    -(xx * eye[0] + xy * eye[1] + xz * eye[2]),
    -(yx * eye[0] + yy * eye[1] + yz * eye[2]),
    -(zx * eye[0] + zy * eye[1] + zz * eye[2]),
    1,
  ]);
}

// ---- shaders --------------------------------------------------------------------------
const SCENE_VS =
  "#version 300 es\n" +
  "in vec3 aPos; in vec3 aNormal; in vec3 aBary; in vec3 aMask;\n" +
  "uniform mat4 uProj; uniform mat4 uView; uniform float uPump; uniform vec3 uCenter;\n" +
  "out vec3 vNormal; out vec3 vBary; out vec3 vMask;\n" +
  "void main(){\n" +
  "  vec3 p = uCenter + (aPos - uCenter) * uPump;\n" +
  "  gl_Position = uProj * (uView * vec4(p, 1.0));\n" +
  "  vNormal = aNormal; vBary = aBary; vMask = aMask;\n" +
  "}\n";

const SCENE_FS =
  "#version 300 es\n" +
  "precision highp float;\n" +
  "in vec3 vNormal; in vec3 vBary; in vec3 vMask;\n" +
  "uniform float uDither;\n" +
  "out vec4 outColor;\n" +
  "void main(){\n" +
  "  float shade = 0.88;\n" +
  "  if (vNormal.y > 0.5) shade = 0.88;\n" +
  "  else if (vNormal.x > 0.5) shade = 0.66;\n" +
  "  else if (vNormal.z > 0.5) shade = 0.48;\n" +
  "  shade = clamp(shade - uDither * 0.12, 0.05, 0.99);\n" +
  "  vec3 d = max(fwidth(vBary), vec3(0.0001));\n" +
  "  vec3 w = vBary / d;\n" +
  "  vec3 m = mix(vec3(64.0), w, vMask);\n" +
  "  float edge = 1.0 - clamp(min(min(m.x, m.y), m.z), 0.0, 1.0);\n" +
  "  outColor = vec4(shade, edge, 0.0, 1.0);\n" +
  "}\n";

const COMP_VS =
  "#version 300 es\n" +
  "in vec2 aP;\n" +
  "void main(){ gl_Position = vec4(aP, 0.0, 1.0); }\n";

const COMP_FS =
  "#version 300 es\n" +
  "precision highp float;\n" +
  "uniform sampler2D uScene; uniform sampler2D uHud;\n" +
  "uniform vec2 uRes; uniform vec4 uHudRect;\n" +
  "uniform float uTime; uniform float uWorldT; uniform float uGlitch; uniform float uInvert;\n" +
  "uniform vec3 uBands; uniform int uWorld;\n" +
  "uniform float uBeat; uniform float uBeatPhase;\n" +
  "out vec4 outColor;\n" +
  "\n" +
  "float hash11(float p){ p = fract(p * 0.1031); p *= p + 33.33; p *= p + p; return fract(p); }\n" +
  "float hash21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }\n" +
  "const float BAYER[64] = float[64](\n" +
  "   0.0, 32.0,  8.0, 40.0,  2.0, 34.0, 10.0, 42.0,\n" +
  "  48.0, 16.0, 56.0, 24.0, 50.0, 18.0, 58.0, 26.0,\n" +
  "  12.0, 44.0,  4.0, 36.0, 14.0, 46.0,  6.0, 38.0,\n" +
  "  60.0, 28.0, 52.0, 20.0, 62.0, 30.0, 54.0, 22.0,\n" +
  "   3.0, 35.0, 11.0, 43.0,  1.0, 33.0,  9.0, 41.0,\n" +
  "  51.0, 19.0, 59.0, 27.0, 49.0, 17.0, 57.0, 25.0,\n" +
  "  15.0, 47.0,  7.0, 39.0, 13.0, 45.0,  5.0, 37.0,\n" +
  "  63.0, 31.0, 55.0, 23.0, 61.0, 29.0, 53.0, 21.0);\n" +
  "float bayer(vec2 c){ int x = int(mod(c.x, 8.0)); int y = int(mod(c.y, 8.0)); return (BAYER[y * 8 + x] + 0.5) / 64.0; }\n" +
  "float luma(vec3 c){ return dot(c, vec3(0.299, 0.587, 0.114)); }\n" +
  "vec3 inkFor(vec3 c){ return luma(c) > 0.5 ? vec3(0.05) : vec3(0.95); }\n" +
  "\n" +
  "float curves(vec2 px, float t){\n" +
  "  float ink = 0.0;\n" +
  "  for (int i = 0; i < 5; i++){\n" +
  "    float fi = float(i);\n" +
  "    float amp  = 20.0 + 60.0 * hash11(fi * 4.13 + 21.0);\n" +
  "    float freq = 0.003 + 0.006 * hash11(fi * 6.71 + 22.0);\n" +
  "    float ph   = 6.283 * hash11(fi * 9.17 + 23.0);\n" +
  "    float spd  = 0.2 + 0.7 * hash11(fi * 2.33 + 24.0);\n" +
  "    float yc = uRes.y * (0.15 + 0.7 * hash11(fi * 5.11 + 25.0)) + amp * sin(px.x * freq + ph + t * spd);\n" +
  "    ink = max(ink, 1.0 - smoothstep(0.0, 1.0, abs(px.y - yc)));\n" +
  "  }\n" +
  "  return ink;\n" +
  "}\n" +
  "float hangLines(vec2 px, float t){\n" +
  "  float m = 0.0;\n" +
  "  for (int i = 0; i < 7; i++){\n" +
  "    float fi = float(i);\n" +
  "    float x = (0.06 + 0.88 * hash11(fi * 3.77 + 31.0)) * uRes.x;\n" +
  "    float y0 = (0.15 + 0.6 * hash11(fi * 5.31 + 32.0)) * uRes.y;\n" +
  "    float len = (0.12 + 0.5 * hash11(fi * 7.93 + 33.0)) * uRes.y;\n" +
  "    float drift = mod(t * (8.0 + 22.0 * hash11(fi * 2.11 + 34.0)), uRes.y * 1.4) - uRes.y * 0.2;\n" +
  "    float yy = mod(px.y - y0 - drift, uRes.y);\n" +
  "    float inY = step(0.0, yy) * step(yy, len);\n" +
  "    float onX = 1.0 - smoothstep(0.0, 1.0, abs(px.x - x));\n" +
  "    m = max(m, inY * onX);\n" +
  "  }\n" +
  "  return m;\n" +
  "}\n" +
  "\n" +
  "float gridMask(vec2 p, float cell, float w){\n" +
  "  float dx = min(mod(p.x, cell), cell - mod(p.x, cell));\n" +
  "  float dy = min(mod(p.y, cell), cell - mod(p.y, cell));\n" +
  "  return 1.0 - smoothstep(0.0, w, min(dx, dy));\n" +
  "}\n" +
  "vec3 bg(int s, vec2 px, float st, float t){\n" +
  "  if (s == 0){\n" +
  "    vec3 c = vec3(0.945, 0.937, 0.921);\n" +
  "    float ink = curves(px, st);\n" +
  "    for (int i = 0; i < 4; i++){\n" +
  "      float fi = float(i);\n" +
  "      vec2 cc = vec2(uRes.x * (0.15 + 0.7 * hash11(fi * 11.3 + 6.0)), uRes.y * (0.15 + 0.7 * hash11(fi * 17.9 + 7.0)));\n" +
  "      float r = uRes.y * (0.07 + 0.16 * hash11(fi * 23.1 + 8.0)) + 10.0 * sin(st * 0.6 + fi * 2.0);\n" +
  "      ink = max(ink, 1.0 - smoothstep(0.0, 1.0, abs(length(px - cc) - r)));\n" +
  "    }\n" +
  "    return mix(c, vec3(0.05), ink * 0.8);\n" +
  "  }\n" +
  "  if (s == 1){\n" +
  "    vec3 c = vec3(0.015);\n" +
  "    vec2 cc = uRes * 0.5;\n" +
  "    float d = max(abs(px.x - cc.x), abs(px.y - cc.y));\n" +
  "    d += 6.0 * (hash11(floor(d / 34.0) * 1.7 + floor(st * 7.0)) - 0.5);\n" +
  "    float m = mod(d, 34.0);\n" +
  "    float ring = (1.0 - smoothstep(1.0, 2.6, m)) * step(d, uRes.x * 0.46);\n" +
  "    float d2 = max(abs(px.x - cc.x - 8.0), abs(px.y - cc.y - 8.0));\n" +
  "    float ring2 = (1.0 - smoothstep(1.0, 2.6, mod(d2, 34.0))) * step(d2, uRes.x * 0.46);\n" +
  "    vec3 blue = vec3(0.24, 0.30, 1.0);\n" +
  "    return mix(mix(c, blue, ring), blue * 0.35, ring2 * 0.7);\n" +
  "  }\n" +
  "  if (s == 2){\n" +
  "    vec2 g = floor(px / 14.0);\n" +
  "    float h = hash21(g);\n" +
  "    float trace = 0.0;\n" +
  "    if (h < 0.42) trace = 1.0 - smoothstep(1.0, 2.2, abs(px.y - (g.y * 14.0 + 7.0)));\n" +
  "    else if (h < 0.78) trace = 1.0 - smoothstep(1.0, 2.2, abs(px.x - (g.x * 14.0 + 7.0)));\n" +
  "    vec2 cell = (g + 0.5) * 14.0;\n" +
  "    float via = 1.0 - smoothstep(2.0, 3.2, length(px - cell));\n" +
  "    vec3 c = vec3(0.34, 0.02, 0.04) * (0.8 + 0.4 * hash21(g * 3.7));\n" +
  "    c = mix(c, vec3(0.74, 0.07, 0.09), trace * 0.9);\n" +
  "    return mix(c, vec3(0.86, 0.10, 0.12), via * step(0.86, h));\n" +
  "  }\n" +
  "  if (s == 3){\n" +
  "    float horizon = uRes.y * 0.52 + 8.0 * sin(st * 0.7);\n" +
  "    vec3 sky = vec3(0.52, 0.72, 0.92);\n" +
  "    vec3 grass = vec3(0.22, 0.55, 0.24);\n" +
  "    vec3 c = px.y < horizon ? sky : grass;\n" +
  "    float hx = floor(px.x / 40.0);\n" +
  "    float hh = horizon - 20.0 - 26.0 * hash11(hx * 3.1 + 1.0);\n" +
  "    if (px.y > hh && px.y < horizon) c = mix(sky, grass, 0.75);\n" +
  "    vec2 cg = floor(px / vec2(46.0, 16.0));\n" +
  "    if (hash21(cg * 1.7) < 0.12 && px.y < horizon - 60.0) c = vec3(0.98);\n" +
  "    return c;\n" +
  "  }\n" +
  "  if (s == 4){\n" +
  "    vec3 c = vec3(0.02);\n" +
  "    float fr = floor(t * 12.0);\n" +
  "    for (int i = 0; i < 7; i++){\n" +
  "      float fi = float(i);\n" +
  "      float hx = hash21(vec2(fi * 3.1, fr));\n" +
  "      float hy = hash21(vec2(fi * 5.7, fr + 11.0));\n" +
  "      float hw = 0.10 + 0.50 * hash21(vec2(fi * 7.3, fr + 23.0));\n" +
  "      float hh = 0.02 + 0.18 * hash21(vec2(fi * 9.9, fr + 37.0));\n" +
  "      vec2 p0 = vec2(hx * (1.0 - hw), hy * (1.0 - hh)) * uRes;\n" +
  "      vec2 p1 = p0 + vec2(hw, hh) * uRes;\n" +
  "      float inside = step(p0.x, px.x) * step(px.x, p1.x) * step(p0.y, px.y) * step(px.y, p1.y);\n" +
  "      c = mix(c, vec3(0.95), inside);\n" +
  "    }\n" +
  "    return c;\n" +
  "  }\n" +
  "  if (s == 5){\n" +
  "    vec3 c = vec3(0.75, 0.0, 0.75);\n" +
  "    vec2 cc = vec2(uRes.x * 0.62, uRes.y * 0.44);\n" +
  "    float d = length(px - cc) - uRes.x * 0.17;\n" +
  "    c = mix(c, vec3(0.97), 1.0 - smoothstep(0.0, 2.0, abs(d)));\n" +
  "    float w = (px.x - uRes.x * 0.18) * 1.1;\n" +
  "    return mix(c, vec3(0.97), step(px.y, w) * step(px.x, uRes.x * 0.55) * 0.9);\n" +
  "  }\n" +
  "  if (s == 6){\n" +
  "    vec3 c = vec3(0.04);\n" +
  "    for (int i = 0; i < 5; i++){\n" +
  "      float fi = float(i);\n" +
  "      vec2 p0 = vec2(hash11(fi * 3.3 + 41.0) * 0.8, hash11(fi * 7.7 + 42.0) * 0.8) * uRes;\n" +
  "      vec2 sz = vec2(0.06 + 0.22 * hash11(fi * 11.1 + 43.0), 0.06 + 0.22 * hash11(fi * 13.3 + 44.0)) * uRes;\n" +
  "      float inside = step(p0.x, px.x) * step(px.x, p0.x + sz.x) * step(p0.y, px.y) * step(px.y, p0.y + sz.y);\n" +
  "      c = mix(c, vec3(0.93), inside);\n" +
  "    }\n" +
  "    return c;\n" +
  "  }\n" +
  "  if (s == 7){\n" +
  "    float s2 = mod(px.x + st * 30.0, 6.0);\n" +
  "    vec3 c = mix(vec3(0.36, 0.44, 0.44), vec3(0.46, 0.55, 0.54), step(3.0, s2));\n" +
  "    if (px.x > uRes.x * 0.7) c = mix(c, vec3(0.72, 0.78, 0.76), 0.5);\n" +
  "    return c;\n" +
  "  }\n" +
  "  if (s == 8){\n" +
  "    vec3 c = vec3(0.0, 0.62, 0.16);\n" +
  "    c *= 1.0 - 0.55 * step(1.0, mod(px.y + st * 40.0, 3.0));\n" +
  "    float barY = uRes.y * (0.3 + 0.4 * hash11(floor(t * 2.0) * 1.7));\n" +
  "    return mix(c, vec3(0.9, 0.05, 0.05), step(abs(px.y - barY), 9.0));\n" +
  "  }\n" +
  "  if (s == 9){\n" +
  "    vec3 c = vec3(0.16, 0.56, 0.22);\n" +
  "    float inside = step(uRes.x * 0.55, px.x) * step(px.x, uRes.x * 0.82)\n" +
  "                 * step(uRes.y * 0.18, px.y) * step(px.y, uRes.y * 0.34);\n" +
  "    return mix(c, vec3(0.85, 0.12, 0.12), inside);\n" +
  "  }\n" +
  "  if (s == 10){\n" +
  "    float row = floor(px.y / 6.0);\n" +
  "    float fr = floor(st * 6.0);\n" +
  "    float h = hash11(row * 3.77 + fr * 1.13);\n" +
  "    vec3 c = 0.5 + 0.5 * cos(6.283 * (h + vec3(0.0, 0.33, 0.67)));\n" +
  "    c = mix(c, vec3(0.98), step(0.55, hash11(row * 1.31 + fr + 7.0)));\n" +
  "    c = mix(c, vec3(0.02), step(0.34, fract(px.y * 0.5)));\n" +
  "    float n = hash21(floor(px / 2.0) + fr * 9.0);\n" +
  "    return mix(c, vec3(0.98), step(0.93, n));\n" +
  "  }\n" +
  "  if (s == 11){\n" +
  "    vec3 paper = vec3(0.906, 0.888, 0.850);\n" +
  "    vec2 q = px / uRes;\n" +
  "    float f1 = sin((q.x * 3.1 + q.y * 2.3) * 6.283 + st * 0.8);\n" +
  "    float f2 = sin((q.x * 1.7 - q.y * 3.9) * 6.283 - st * 0.5);\n" +
  "    float d = clamp((0.06 + 0.44 * smoothstep(-0.35, 1.15, f1 + 0.55 * f2)) * (1.0 + 0.22 * (1.0 - uBeatPhase)), 0.0, 1.0);\n" +
  "    float band = floor(px.y / 26.0);\n" +
  "    float phase = floor(uBeat * 0.5);\n" +
  "    float slip = hash21(vec2(band * 3.1, phase));\n" +
  "    float shift = (slip - 0.5) * 34.0 * step(0.70, slip);\n" +
  "    vec2 sp = vec2(px.x + shift, px.y);\n" +
  "    float inkA = step(bayer(sp / 6.0), d * 0.95);\n" +
  "    vec2 rp = vec2(sp.x * 0.866 - sp.y * 0.5, sp.x * 0.5 + sp.y * 0.866);\n" +
  "    float inkB = step(bayer(rp / 5.0), clamp(d * 1.15 - 0.12, 0.0, 1.0) * 0.72);\n" +
  "    float ink = max(inkA, inkB * 0.8) * (1.0 - step(slip, 0.10));\n" +
  "    vec3 c = mix(paper, vec3(0.06), ink);\n" +
  "    for (int i = 0; i < 3; i++){\n" +
  "      float fi = float(i);\n" +
  "      vec2 cc = vec2(hash11(fi * 7.1 + 11.0), hash11(fi * 5.3 + 12.0)) * uRes;\n" +
  "      float r = uRes.y * (0.09 + 0.20 * hash11(fi * 9.7 + 13.0));\n" +
  "      c = mix(c, vec3(0.10), (1.0 - smoothstep(r * 0.55, r, length(px - cc))) * 0.32);\n" +
  "    }\n" +
  "    float moire = 1.0 - smoothstep(0.0, 1.6, abs(mod(px.x * 0.7 + px.y * 0.7, 5.0) - 2.5));\n" +
  "    c = mix(c, vec3(0.08), moire * 0.12);\n" +
  "    vec2 mk = floor(px / 260.0);\n" +
  "    vec2 mc = (mk + vec2(0.5)) * 260.0;\n" +
  "    float ax = abs(px.x - mc.x);\n" +
  "    float ay = abs(px.y - mc.y);\n" +
  "    float reg = (1.0 - smoothstep(0.0, 1.3, min(ax, ay))) * step(12.0, ax + ay) * step(ax + ay, 30.0);\n" +
  "    return mix(c, vec3(0.14), reg * 0.6) * (1.0 - 0.16 * (1.0 - uBeatPhase));\n" +
  "  }\n" +
  "  if (s == 12){\n" +
  "    vec3 c = vec3(0.018, 0.022, 0.030);\n" +
  "    float ph = mod(px.x, 3.0);\n" +
  "    vec3 stripe = ph < 1.0 ? vec3(1.0, 0.30, 0.30) : (ph < 2.0 ? vec3(0.30, 1.0, 0.40) : vec3(0.35, 0.50, 1.0));\n" +
  "    float scan = 1.0 - 0.5 * step(1.0, mod(px.y, 3.0));\n" +
  "    c += stripe * 0.15 * scan;\n" +
  "    float roll = fract((px.y + st * 120.0) / uRes.y);\n" +
  "    float band = smoothstep(0.95, 1.0, roll) + smoothstep(0.05, 0.0, roll);\n" +
  "    c += vec3(0.85, 0.92, 1.0) * band * 0.22;\n" +
  "    float vig = 1.0 - 0.55 * length((px / uRes - vec2(0.5)) * vec2(1.05, 1.35));\n" +
  "    return c * clamp(vig, 0.15, 1.0);\n" +
  "  }\n" +
  "  if (s == 13){\n" +
  "    vec3 c = vec3(0.035, 0.072, 0.170);\n" +
  "    vec3 line = vec3(0.36, 0.78, 0.96);\n" +
  "    float g1 = gridMask(px, 40.0, 1.1) * 0.30;\n" +
  "    float g2 = gridMask(px, 200.0, 1.7) * 0.70;\n" +
  "    float g3 = gridMask(px + vec2(1.8, 1.2), 40.0, 1.0) * 0.22;\n" +
  "    float inset = step(uRes.x * 0.06, px.x) * step(px.x, uRes.x * 0.40) * step(uRes.y * 0.58, px.y) * step(px.y, uRes.y * 0.92);\n" +
  "    float g4 = gridMask(px, 8.0, 0.9) * 0.30 * inset;\n" +
  "    float sweepX = uRes.x * fract(st * 0.07);\n" +
  "    float sweep = (1.0 - smoothstep(0.0, 1.8, abs(px.x - sweepX))) * 0.85;\n" +
  "    float dimY = uRes.y * (0.16 + 0.05 * floor(uBeat * 0.25));\n" +
  "    float dim = (1.0 - smoothstep(0.0, 1.4, abs(px.y - dimY))) * step(0.04, fract(px.x / 24.0)) * 0.55;\n" +
  "    float ticks = (1.0 - smoothstep(0.0, 1.2, abs(px.y - uRes.y * 0.08))) * step(0.5, fract(px.x / 12.0)) * 0.5;\n" +
  "    vec2 cc = vec2(uRes.x * 0.68, uRes.y * 0.33);\n" +
  "    float rings = 0.0;\n" +
  "    for (int i = 1; i <= 3; i++){\n" +
  "      float r = float(i) * uRes.y * 0.105;\n" +
  "      rings = max(rings, 1.0 - smoothstep(0.0, 1.3, abs(length(px - cc) - r)));\n" +
  "    }\n" +
  "    vec2 g = floor(px / 200.0);\n" +
  "    float cross = 0.0;\n" +
  "    if (hash21(g * 2.3) < 0.45) {\n" +
  "      vec2 mc = (g + vec2(0.5)) * 200.0;\n" +
  "      cross = max((1.0 - smoothstep(0.0, 1.4, abs(px.x - mc.x))) * step(abs(px.y - mc.y), 11.0),\n" +
  "                  (1.0 - smoothstep(0.0, 1.4, abs(px.y - mc.y))) * step(abs(px.x - mc.x), 11.0));\n" +
  "    }\n" +
  "    vec2 t0 = vec2(uRes.x * 0.72, uRes.y * 0.76);\n" +
  "    vec2 t1 = vec2(uRes.x * 0.95, uRes.y * 0.93);\n" +
  "    float inside = step(t0.x, px.x) * step(px.x, t1.x) * step(t0.y, px.y) * step(px.y, t1.y);\n" +
  "    float border = inside * clamp(step(px.x, t0.x + 3.0) + step(t1.x - 3.0, px.x) + step(px.y, t0.y + 3.0) + step(t1.y - 3.0, px.y), 0.0, 1.0);\n" +
  "    float bars = inside * step(0.55, fract(px.y / 21.0)) * step(8.0, px.x - t0.x) * step(px.x - t0.x, 40.0 + 50.0 * hash11(floor(px.y / 21.0) * 3.7));\n" +
  "    float band = floor(px.y / 34.0);\n" +
  "    float torn = step(0.78, hash21(vec2(band * 2.7, floor(uBeat * 0.5))));\n" +
  "    float gate = 1.0 - torn * 0.85;\n" +
  "    float pump = 1.0 + 0.35 * (1.0 - uBeatPhase);\n" +
  "    return c + line * (g1 + g2 + g3 + g4 + sweep + dim + ticks + rings * 0.55 + cross * 0.6 + border * 0.7 + bars * 0.4) * gate * pump + vec3(0.05, 0.09, 0.17) * (1.0 - uBeatPhase);\n" +
  "  }\n" +
  "  if (s == 14){\n" +
  "    vec2 q = px / uRes.y;\n" +
  "    float v = 0.0;\n" +
  "    for (int i = 0; i < 4; i++){\n" +
  "      float fi = float(i);\n" +
  "      float fq = 1.1 + 2.2 * hash11(fi * 3.1 + 61.0);\n" +
  "      float a = 6.283 * hash11(fi * 5.7 + 62.0);\n" +
  "      v += sin(q.x * fq + a + st * (0.15 + 0.25 * fi)) * cos(q.y * fq * 0.75 - a * 0.6 - st * 0.12);\n" +
  "    }\n" +
  "    v = clamp(0.5 + 0.28 * v, 0.0, 1.0);\n" +
  "    vec3 c = mix(vec3(0.09, 0.09, 0.10), vec3(0.88, 0.87, 0.85), floor(v * 6.0) / 6.0);\n" +
  "    c = mix(c, inkFor(c), step(bayer(px / 3.0), 0.22) * 0.35);\n" +
  "    float vig = 1.0 - 0.45 * length((px / uRes - vec2(0.5)) * vec2(1.0, 1.2));\n" +
  "    return c * clamp(vig, 0.2, 1.0);\n" +
  "  }\n" +
  "  if (s == 15){\n" +
  "    vec3 c = vec3(0.012, 0.020, 0.014);\n" +
  "    vec3 rain = vec3(0.16, 0.92, 0.34);\n" +
  "    vec3 head = vec3(0.80, 1.0, 0.85);\n" +
  "    float v = 0.0;\n" +
  "    float bright = 0.0;\n" +
  "    for (int L = 0; L < 2; L++){\n" +
  "      float fl = float(L);\n" +
  "      float cwl = (uRes.x / 44.0) * (1.0 + fl * 0.9);\n" +
  "      float cil = floor(px.x / cwl);\n" +
  "      float loc = fract(px.x / cwl);\n" +
  "      float inl = step(0.16, loc) * step(loc, 0.88);\n" +
  "      float speed = (70.0 + 300.0 * hash11(cil * 1.7 + 71.0 + fl * 17.0)) * (1.0 - fl * 0.45);\n" +
  "      float len = uRes.y * (0.10 + 0.42 * hash11(cil * 3.3 + 72.0 + fl * 19.0));\n" +
  "      float y = mod(px.y + st * speed + hash11(cil * 5.1 + 73.0 + fl * 23.0) * (uRes.y + len), uRes.y + len) - len;\n" +
  "      float cell = floor(y / 9.0);\n" +
  "      float glyph = step(0.20, hash21(vec2(cil * 7.0 + fl * 31.0, cell)));\n" +
  "      float inCol = step(0.0, y) * step(y, len) * inl * glyph;\n" +
  "      float hd = (1.0 - smoothstep(0.0, 8.0, abs(y - 3.0))) * inl;\n" +
  "      float att = fl > 0.5 ? 0.45 : 1.0;\n" +
  "      v = max(v, inCol * att);\n" +
  "      bright = max(bright, hd * att);\n" +
  "    }\n" +
  "    c = mix(c, rain, v * 0.55);\n" +
  "    c = mix(c, head, bright);\n" +
  "    float row = floor(px.y / 5.0);\n" +
  "    float fr = floor(uBeat * 2.0);\n" +
  "    c += rain * step(0.955, hash11(row * 1.3 + fr * 7.7)) * 0.30;\n" +
  "    float col = uRes.x / 44.0;\n" +
  "    float local = fract(px.x / col);\n" +
  "    float flash = step(0.90, hash11(floor(px.x / col) * 9.1 + floor(uBeat)));\n" +
  "    return mix(c, head, flash * step(0.16, local) * step(local, 0.88) * 0.22) + rain * 0.12 * (1.0 - uBeatPhase);\n" +
  "  }\n" +
  "  return vec3(0.0);\n" +
  "}\n" +
  "\n" +
  "float ditherMask(vec2 px, float density){\n" +
  "  float d1 = bayer(px);\n" +
  "  float ph = hash11(floor(px.y * 0.5) + 1.0) * 4.0;\n" +
  "  float d2 = fract((px.x + ph) * 0.25);\n" +
  "  float lineAmt = smoothstep(0.12, 0.30, min(density, 1.0 - density));\n" +
  "  return step(mix(d1, d2, lineAmt * 0.85), density);\n" +
  "}\n" +
  "float sceneAlpha(vec2 uv){ return step(0.5, texture(uScene, uv).a); }\n" +
  "float sceneShade(vec2 uv){ return texture(uScene, uv).r; }\n" +
  "float sceneEdge(vec2 uv){ return texture(uScene, uv).g; }\n" +
  "\n" +
  "void main(){\n" +
  "  vec2 px = gl_FragCoord.xy;\n" +
  "  vec2 bpx = vec2(px.x, uRes.y - px.y);\n" +
  "  float t = uTime;\n" +
  "  float frame = floor(t * 30.0);\n" +
  "\n" +
  "  float bandH = 18.0 + 30.0 * hash11(frame * 1.7);\n" +
  "  float band = floor(px.y / bandH);\n" +
  "  float bh = hash21(vec2(band, frame * 3.0));\n" +
  "  float amp = 0.05 * (0.35 + 0.65 * uGlitch);\n" +
  "  float shift = (bh < 0.10 + 0.35 * uGlitch) ? (hash21(vec2(band * 7.0 + 3.0, frame)) * 2.0 - 1.0) * amp : 0.0;\n" +
  "  vec2 spx = vec2(px.x + shift * uRes.x, px.y);\n" +
  "  vec2 suv = spx / uRes;\n" +
  "  vec2 bshift = vec2(bpx.x + shift * uRes.x, bpx.y);\n" +
  "\n" +
  "  vec3 col = bg(uWorld, bshift, uWorldT, t);\n" +
  "  col = mix(col, inkFor(col), curves(px, t) * 0.30);\n" +
  "\n" +
  "  float sp = (2.5 + 6.0 * uGlitch) / uRes.x;\n" +
  "  float aR = sceneAlpha(suv + vec2(sp, 0.0));\n" +
  "  float aG = sceneAlpha(suv);\n" +
  "  float aB = sceneAlpha(suv - vec2(sp, 0.0));\n" +
  "  vec3 gmask = vec3(aR, aG, aB);\n" +
  "  vec3 ink = vec3(\n" +
  "    ditherMask(px, 1.0 - sceneShade(suv + vec2(sp, 0.0))),\n" +
  "    ditherMask(px, 1.0 - sceneShade(suv)),\n" +
  "    ditherMask(px, 1.0 - sceneShade(suv - vec2(sp, 0.0))));\n" +
  "  vec3 geom = mix(vec3(0.965), vec3(0.07), ink);\n" +
  "  col = mix(col, geom, gmask);\n" +
  "  col = mix(col, vec3(0.985), sceneEdge(suv) * aG);\n" +
  "\n" +
  "  col = mix(col, inkFor(col), hangLines(px, t) * (1.0 - aG) * 0.5);\n" +
  "  col = mix(col, inkFor(col), curves(px, t) * 0.12);\n" +
  "\n" +
  "  float bandY = floor(px.y / 40.0);\n" +
  "  float gh = hash21(vec2(bandY, floor(t * 8.0)));\n" +
  "  if (gh < 0.03 + 0.12 * uGlitch) col = mix(col, vec3(1.0) - col, 0.85);\n" +
  "  float ty = hash11(floor(t * 6.0) * 3.3 + 5.0) * uRes.y;\n" +
  "  col = mix(col, vec3(0.9), (1.0 - smoothstep(0.0, 3.0, abs(px.y - ty))) * (0.25 + 0.4 * uGlitch));\n" +
  "\n" +
  "  col *= 1.0 - 0.06 * step(1.0, mod(px.y, 2.0));\n" +
  "  if (uInvert > 0.001) col = mix(col, 1.0 - col, uInvert);\n" +
  "\n" +
  "  vec2 h = (px - uHudRect.xy) / uHudRect.zw;\n" +
  "  if (h.x > 0.0 && h.x < 1.0 && h.y > 0.0 && h.y < 1.0) {\n" +
  "    vec4 hu = texture(uHud, vec2(h.x, 1.0 - h.y));\n" +
  "    col = mix(col, hu.rgb, hu.a);\n" +
  "  }\n" +
  "  outColor = vec4(col, 1.0);\n" +
  "}\n";

export function createGlitchVisual(canvas, RHYTHM_MAP, getBeatScopeFrame) {
  const BPM = RHYTHM_MAP.tempo?.global_bpm ?? RHYTHM_MAP.bpm;
  const BEAT = 60 / BPM;
  const ORIGIN = RHYTHM_MAP.grid?.origin ?? RHYTHM_MAP.origin ?? 0;
  const W = canvas.width;
  const H = canvas.height;
  const gl = canvas.getContext("webgl2", {
    alpha: false,
    antialias: false,
    depth: true,
    preserveDrawingBuffer: true,
    premultipliedAlpha: false,
  });
  if (!gl) throw new Error("WebGL2 unavailable");

  function compile(type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      throw new Error("shader: " + gl.getShaderInfoLog(s));
    }
    return s;
  }
  function program(vs, fs) {
    const p = gl.createProgram();
    gl.attachShader(p, compile(gl.VERTEX_SHADER, vs));
    gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      throw new Error("link: " + gl.getProgramInfoLog(p));
    }
    return p;
  }

  const geo = buildGeometry();
  const vbo = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(geo.verts), gl.STATIC_DRAW);

  const sceneProg = program(SCENE_VS, SCENE_FS);
  const aPos = gl.getAttribLocation(sceneProg, "aPos");
  const aNormal = gl.getAttribLocation(sceneProg, "aNormal");
  const aBary = gl.getAttribLocation(sceneProg, "aBary");
  const aMask = gl.getAttribLocation(sceneProg, "aMask");
  const uProj = gl.getUniformLocation(sceneProg, "uProj");
  const uView = gl.getUniformLocation(sceneProg, "uView");
  const uPump = gl.getUniformLocation(sceneProg, "uPump");
  const uCenter = gl.getUniformLocation(sceneProg, "uCenter");
  const uDither = gl.getUniformLocation(sceneProg, "uDither");

  const proj = ortho(5.8, -60, 60);
  const view = lookAt([8.0, 6.8, 8.0], [0.4, 2.9, 0.6], [0, 1, 0]);
  const center = [0, geo.centerY, 0];

  const sceneTex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, sceneTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, W, H, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const sceneFBO = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, sceneFBO);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, sceneTex, 0);
  const depthRB = gl.createRenderbuffer();
  gl.bindRenderbuffer(gl.RENDERBUFFER, depthRB);
  gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, W, H);
  gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, depthRB);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);

  const compProg = program(COMP_VS, COMP_FS);
  const aP = gl.getAttribLocation(compProg, "aP");
  const loc = {};
  for (const n of ["uScene", "uHud", "uRes", "uHudRect", "uTime", "uWorldT", "uGlitch", "uInvert", "uBands", "uWorld", "uBeat", "uBeatPhase"]) {
    loc[n] = gl.getUniformLocation(compProg, n);
  }

  const quadVBO = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quadVBO);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);

  // HUD: 2D canvas -> texture
  const hudW = Math.round(W * 0.34);
  const hudH = Math.round(H * 0.058);
  const hudCanvas = document.createElement("canvas");
  hudCanvas.width = hudW;
  hudCanvas.height = hudH;
  const hudCtx = hudCanvas.getContext("2d");
  const hudTex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, hudTex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

  const hudRect = [W - hudW - Math.round(W * 0.018), H - hudH - Math.round(H * 0.018), hudW, hudH];

  function drawHUD(tm) {
    const pad = Math.round(hudH * 0.14);
    hudCtx.clearRect(0, 0, hudW, hudH);
    hudCtx.font = "500 " + Math.round(hudH * 0.34) + 'px "JetBrains Mono", ui-monospace, monospace';
    hudCtx.textBaseline = "top";
    hudCtx.fillStyle = "rgba(10,10,10,0.85)";
    hudCtx.fillText("BAR " + tm.bar + "  BEAT " + tm.beat, pad + 1, pad + 1);
    hudCtx.fillStyle = "rgba(245,245,240,0.95)";
    hudCtx.fillText("BAR " + tm.bar + "  BEAT " + tm.beat, pad, pad);
    const line2 = BPM.toFixed(1) + " BPM";
    hudCtx.fillStyle = "rgba(10,10,10,0.85)";
    hudCtx.fillText(line2, pad + 1, hudH * 0.52 + 1);
    hudCtx.fillStyle = "rgba(245,245,240,0.95)";
    hudCtx.fillText(line2, pad, hudH * 0.52);
    // band meter
    const mw = hudW * 0.36;
    const mx = hudW - pad - mw;
    const my = hudH * 0.58;
    const mh = hudH * 0.26;
    const vals = [tm.low, tm.mid, tm.high];
    for (let i = 0; i < 3; i++) {
      const bw = mw / 3 - 4;
      const x = mx + i * (mw / 3);
      hudCtx.fillStyle = "rgba(245,245,240,0.25)";
      hudCtx.fillRect(x, my, bw, mh);
      hudCtx.fillStyle = i === 0 ? "#39ff6a" : i === 1 ? "#ffd23f" : "#ff3b3b";
      hudCtx.fillRect(x, my + mh * (1 - clamp01(vals[i])), bw, mh * clamp01(vals[i]));
    }
    gl.bindTexture(gl.TEXTURE_2D, hudTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, hudCanvas);
  }

  function worldFor(family, bar, beat) {
    const set = WORLD_SETS[family] || FALLBACK_SET;
    const step = (bar - 1) * 2 + Math.floor((beat - 1) / 2);
    return { world: set[step % set.length], step };
  }

  function renderAt(timeSeconds, options) {
    const opts = options || {};
    const reduced = !!opts.reducedMotion;
    const t = Math.max(0, Math.min(RHYTHM_MAP.source?.duration ?? RHYTHM_MAP.duration, Number(timeSeconds) || 0));
    const f = getBeatScopeFrame(t, { reducedMotion: reduced });
    const tm = f.timing;

    const beatsPerBar = Number(RHYTHM_MAP.meter?.beats_per_bar ?? RHYTHM_MAP.meter?.beats ?? 4) || 4;
    const beatIndex = (Math.max(1, tm.bar) - 1) * beatsPerBar + (Math.max(1, tm.beat) - 1);
    const inferred = worldFor(tm.structure ? tm.structure.family : "A", tm.bar, tm.beat);
    const world = opts.world ?? inferred.world;
    const step = inferred.step;
    const worldStart = opts.worldStart ?? (ORIGIN + step * 2 * BEAT);
    const worldT = Math.max(0, t - worldStart);

    const on = tm.onset;
    const hit = on && isFinite(on.age) ? on.value * clamp01(1 - on.age / 0.5) : 0;
    let glitch = clamp01(hit * 1.3 + tm.high * 0.3);
    let invert = 0;
    if (tm.accent && isFinite(tm.accent.age)) {
      glitch = clamp01(glitch + tm.accent.value * 0.5);
      invert = reduced ? 0 : clamp01(1 - tm.accent.age / 0.14) * tm.accent.value * 0.8;
    }
    if (reduced) glitch = clamp01(glitch * 0.35);
    if (opts.glitch !== undefined) glitch = opts.glitch;
    if (opts.invert !== undefined) invert = opts.invert;
    const pump = opts.pump ?? (reduced ? 1 : 1 + 0.022 * Math.pow(1 - tm.beatPhase, 4));

    // ---- scene pass
    gl.bindFramebuffer(gl.FRAMEBUFFER, sceneFBO);
    gl.viewport(0, 0, W, H);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);
    gl.cullFace(gl.BACK);
    gl.disable(gl.BLEND);
    gl.useProgram(sceneProg);
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    const stride = 12 * 4;
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(aNormal);
    gl.vertexAttribPointer(aNormal, 3, gl.FLOAT, false, stride, 12);
    gl.enableVertexAttribArray(aBary);
    gl.vertexAttribPointer(aBary, 3, gl.FLOAT, false, stride, 24);
    gl.enableVertexAttribArray(aMask);
    gl.vertexAttribPointer(aMask, 3, gl.FLOAT, false, stride, 36);
    gl.uniformMatrix4fv(uProj, false, proj);
    gl.uniformMatrix4fv(uView, false, view);
    gl.uniform1f(uPump, pump);
    gl.uniform3f(uCenter, center[0], center[1], center[2]);
    gl.uniform1f(uDither, tm.mid);
    gl.drawArrays(gl.TRIANGLES, 0, geo.verts.length / 12);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);

    // ---- composite
    drawHUD(tm);
    gl.viewport(0, 0, W, H);
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);
    gl.disable(gl.BLEND);
    gl.useProgram(compProg);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, sceneTex);
    gl.uniform1i(loc.uScene, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, hudTex);
    gl.uniform1i(loc.uHud, 1);
    gl.uniform2f(loc.uRes, W, H);
    gl.uniform4f(loc.uHudRect, hudRect[0], hudRect[1], hudRect[2], hudRect[3]);
    gl.uniform1f(loc.uTime, t);
    gl.uniform1f(loc.uWorldT, worldT);
    gl.uniform1f(loc.uGlitch, glitch);
    gl.uniform1f(loc.uInvert, invert);
    gl.uniform3f(loc.uBands, tm.low, tm.mid, tm.high);
    gl.uniform1i(loc.uWorld, world);
    gl.uniform1f(loc.uBeat, beatIndex);
    gl.uniform1f(loc.uBeatPhase, Number.isFinite(tm.beatPhase) ? tm.beatPhase : 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, quadVBO);
    gl.enableVertexAttribArray(aP);
    gl.vertexAttribPointer(aP, 2, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function dispose() {
    // Release the WebGL context explicitly: rebuilding a preview (a seed change,
    // a new song) would otherwise pile up GL resources until the browser refuses
    // to hand out another context.
    const lose = gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
  }

  return { renderAt, dispose, width: W, height: H, duration: RHYTHM_MAP.duration };
}
