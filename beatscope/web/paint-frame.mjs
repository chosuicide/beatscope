// PASTEL BLOOM (粉彩花信): real flower footage repainted stroke by stroke on the beat.
// Seek-safe: render(t) replays the current shot from its first frame when time jumps.
export async function createPaintMovie(outCanvas, map, track, plan, options = {}) {
const W = 1920, H = 1080, AW = 640, AH = 360, S = W / AW;
const CTXO = {willReadFrequently: true};
const mk = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
const cx2 = c => c.getContext('2d', CTXO);
const cv = mk(W, H); const out = cx2(cv); const octx = outCanvas.getContext('2d');
const ASSET = options.assetBase || new URL('./paint-assets/', import.meta.url).href;
const RM = map; const BEATS = (RM.beats || []).map(b => b.time); const NB = BEATS.length; if (NB < 8) throw Error('Pastel Bloom needs a beat grid of at least 8 beats');
const B = i => i >= NB ? BEATS[NB - 1] + (i - NB + 1) * (BEATS[NB - 1] - BEATS[NB - 2]) : BEATS[Math.max(0, i)];
const cl = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
function lastIdx(arr, t) { let lo = 0, hi = arr.length - 1, r = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m] <= t) { r = m; lo = m + 1; } else hi = m - 1; } return r; }
let SEED = 1; const R = () => { SEED = (SEED * 16807) % 2147483647; return SEED / 2147483647; };
const rnd = i => { const x = Math.sin(i * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
const SE = (() => { const a = RM.energy.bands.low; const o = new Float32Array(a.length); let s = 0; const k = 20; for (let i = 0; i < a.length; i++) { s += a[i]; if (i >= k) s -= a[i - k]; o[i] = s / Math.min(i + 1, k); } let mx = 0; for (const v of o) mx = Math.max(mx, v); for (let i = 0; i < o.length; i++) o[i] /= mx; return o; })();
const bass = t => SE[cl(Math.floor(t * RM.energy.fps), 0, SE.length - 1)];
const loadImg = src => new Promise(r => { const i = new Image(); i.onload = () => r(i); i.onerror = () => r(null); i.src = src; });
function noiseCanvas(w, h, sw, sh, seed) { const s = mk(sw, sh), x = cx2(s), id = x.createImageData(sw, sh); SEED = seed; for (let i = 0; i < id.data.length; i += 4) { const v = R() * 255; id.data[i] = id.data[i + 1] = id.data[i + 2] = v; id.data[i + 3] = 255; } x.putImageData(id, 0, 0); const c = mk(w, h), y = cx2(c); y.imageSmoothingEnabled = true; y.drawImage(s, 0, 0, w, h); return c; }
const grain = noiseCanvas(512, 512, 512, 512, 3);
const blotch = noiseCanvas(W, H, 30, 17, 11);
const weave = mk(256, 256); { const x = cx2(weave), id = x.createImageData(256, 256); SEED = 7; for (let y = 0; y < 256; y++) for (let X = 0; X < 256; X++) { const v = 200 + 40 * Math.sin(X * 1.6) * Math.sin(y * 1.6) + R() * 30; const i = (y * 256 + X) * 4; id.data[i] = id.data[i + 1] = id.data[i + 2] = cl(v, 0, 255); id.data[i + 3] = 255; } x.putImageData(id, 0, 0); }
function makePaper(base, a1, a2, s) { const c = mk(W, H), x = cx2(c); x.fillStyle = base; x.fillRect(0, 0, W, H); x.globalCompositeOperation = 'multiply'; x.globalAlpha = a1; x.drawImage(noiseCanvas(W, H, 900, 506, s), 0, 0); x.globalAlpha = a2; x.drawImage(noiseCanvas(W, H, 60, 34, s + 1), 0, 0); SEED = s; x.globalAlpha = 0.18; x.strokeStyle = '#8a7a5a'; x.lineWidth = 0.7; for (let i = 0; i < 500; i++) { const px = R() * W, py = R() * H, a = R() * 6.28, l = 6 + R() * 26; x.beginPath(); x.moveTo(px, py); x.quadraticCurveTo(px + Math.cos(a) * l, py + Math.sin(a) * l + 4, px + Math.cos(a + 0.5) * l * 1.6, py + Math.sin(a + 0.5) * l * 1.6); x.stroke(); } return c; }
const washi = makePaper('#efe5cc', 0.12, 0.10, 31);
const rice = makePaper('#f1ece0', 0.10, 0.08, 41);
const charPaper = makePaper('#e6dfcf', 0.22, 0.16, 51);
const woodgrain = (() => { const c = mk(W, H), x = cx2(c); x.drawImage(noiseCanvas(W, H, 5, 200, 21), 0, 0); x.globalCompositeOperation = 'overlay'; x.drawImage(noiseCanvas(W, H, 40, 800, 22), 0, 0); return c; })();

// ---------- sources ----------
const CLIPS = {dandelion: 90, whiteflower: 90, daffodil: 90, amaryllis: 90, tulips: 90, passion: 90, orchid: 90, hibiscus: 90, rose: 90, alstro: 90};
const FR = {};
await Promise.all(Object.entries(CLIPS).map(async ([k, n]) => { const ps = []; for (let i = 1; i <= n; i++) ps.push(loadImg(`${ASSET}${k}/lo/${String(i).padStart(4, '0')}.jpg`)); FR[k] = (await Promise.all(ps)).filter(Boolean); }));
const FRH = {}; await Promise.all(Object.entries(CLIPS).map(async ([k, n]) => { const ps = []; for (let i = 1; i <= n; i++) ps.push(loadImg(`${ASSET}${k}/hi/${String(i).padStart(4, '0')}.jpg`)); FRH[k] = (await Promise.all(ps)).filter(Boolean); }));
const fiOf = (n, ts) => { const k = Math.max(0, Math.floor(ts * 30)); const per = 2 * n - 2; const m = k % per; return m < n ? m : per - m; };

// ---------- score: generated from the song's own beats and sections ----------
const T0 = 0;
const SHOTS = []; const LASTOFF = {};
const D = {dark: true, pal: true};
function SH(bi, clip, med, o = {}) { const t = Number.isInteger(bi) ? B(bi) : bi; let off = o.off;
  if (off === undefined) { const L = LASTOFF[clip]; off = L ? L[1] + (t - L[0]) : 0.2; } LASTOFF[clip] = [t, off];
  const opt = Object.assign({}, med === 'oil' ? D : {}, o); delete opt.off; SHOTS.push([t, clip, off, med, opt]); }
const CALM = ['dandelion', 'whiteflower', 'daffodil', 'alstro'], HOT = ['amaryllis', 'tulips', 'passion', 'orchid', 'hibiscus', 'rose'];
const SILKC = [[47, 163, 200], [242, 194, 48], [226, 92, 30]];
const ZOOMS = [], REDF = [], TRIPS = [], SKETCH = [], SGRAF = [], SILK = [], FOLD = [], ROLL_ON = [], RED = [];
let JOIN = [-1, -1];
const biAt = t => Math.max(0, lastIdx(BEATS, t + 1e-3));
const SEGS = (() => { const s = (RM.patterns?.segments ?? []).filter(x => Number.isFinite(x.start_time)).sort((a, b) => a.start_time - b.start_time);
  if (!s.length) return [{a: 0, b: NB, kind: 'hot'}];
  const mx = Math.max(...s.map(x => x.mean_rms ?? x.mean_energy ?? 1));
  return s.map((x, k) => { const lvl = (x.mean_rms ?? x.mean_energy ?? mx) / mx; const ending = (x.descriptors || []).includes('ending') && k === s.length - 1 && k > 0;
    return {a: k ? biAt(x.start_time) : 0, b: k < s.length - 1 ? biAt(s[k + 1].start_time) : NB, kind: ending ? 'outro' : lvl < 0.62 ? 'calm' : 'hot', lvl}; }).filter(x => x.b > x.a)
    .flatMap(x => { if (x.kind !== 'outro' || x.b - x.a <= 8) return [x]; const cut = x.b - 8;
      return [{a: x.a, b: cut, kind: x.lvl < 0.62 ? 'calm' : 'hot', lvl: x.lvl}, {a: cut, b: x.b, kind: 'outro', lvl: x.lvl}]; }); })();
if (plan?.paintScore) { // authored score (beat units, fractions allowed), written per song by a director/agent
  const P = plan.paintScore, Bf = x => { const i = Math.floor(x), f = x - i; return f ? B(i) + f * (B(i + 1) - B(i)) : B(i); };
  for (const [b, c, m, o] of P.shots) SH(Bf(b), c, m, o || {});
  for (const [b, c, m] of P.rolls || []) { ROLL_ON.push(Bf(b)); SHOTS.push([Bf(b), c, 0.5 + ROLL_ON.length * 0.09, m, {roll: true}]); }
  for (const b of P.rolls?.filter((r, k) => k % 3 === 2).map(r => r[0]) || []) RED.push(Bf(b));
  for (const [a, b, z, x, y] of P.zooms || []) ZOOMS.push([Bf(a), Bf(b), z, x, y]);
  for (const b of P.red || []) REDF.push(Bf(b));
  for (const [a, b] of P.trips || []) TRIPS.push([Bf(a), Bf(b)]);
  for (const [a, b] of P.sketch || []) SKETCH.push([Bf(a), Bf(b)]);
  for (const [a, b] of P.sgraf || []) SGRAF.push([Bf(a), Bf(b)]);
  for (const [a, b, k] of P.silk || []) SILK.push([Bf(a), Bf(b), SILKC[k || 0]]);
  for (const [a, b, m] of P.fold || []) FOLD.push([Bf(a), Bf(b), m || 'light']);
  if (P.join) { JOIN = [Bf(P.join[0]), Bf(P.join[1])]; SHOTS.push([JOIN[0], P.join[2] || 'hibiscus', 0.3, 'raw', {}]); }
}
else if (!(plan?.shots?.length > 8)) { let hc = 0, cc = 0, fx = 0, hw = 0, lastHot = HOT[0];
  const peak = SEGS.filter((s, k) => k > 0 && s.kind === 'hot').sort((p, q) => q.lvl - p.lvl)[0];
  if (peak && peak.a >= 8) JOIN = [B(peak.a - 4), B(peak.a)];
  SEGS.forEach((s, k) => {
    if (s.kind === 'hot' && k > 0 && SEGS[k - 1].kind !== 'hot' && s.a >= 2 && !(JOIN[1] === B(s.a))) { for (let i = s.a - 2; i < s.a; i++) for (const h of [0, 0.5]) ROLL_ON.push(B(i) + h * (B(i + 1) - B(i))); }
    if (s.kind === 'outro') { SH(s.a, lastHot, 'oil', {tiers: [0, 0, 1, 1, 2, 2, 2, 2]}); return; }
    for (let w = s.a; w < s.b; w += 8) { const len = Math.min(8, s.b - w);
      if (s.kind === 'calm') { const c = CALM[cc++ % CALM.length]; SH(w, c, 'raw'); if (len >= 4) SH(w + 2, c, cc % 2 ? 'charcoal' : 'ink', {quiet: true});
        if (len >= 8 && cc % 2 === 0) FOLD.push([B(w + 5), B(w + 7), 'light']); continue; }
      const c = HOT[hc++ % HOT.length]; lastHot = c; SH(w, c, 'raw'); if (len >= 3) SH(w + 1, c, 'oil', {red: true, tiers: [0, 1, 2], pk: ['ember', 'cobalt', 'violet', 'sulfur', 'verdigris', 'ember', 'nocturne'][hw % 7]});
      REDF.push(B(w)); if (len < 8) continue;
      ZOOMS.push([B(w + 4), B(w + 5), 2.2, 0.4 + 0.1 * (hw % 2), 0.4]);
      if (hw % 3 === 2) SKETCH.push([B(w + 3) + 0.2, B(w + 4)]);
      const e = ['trip', 'sgraf', 'silk', 'fold'][fx++ % 4];
      if (e === 'trip') TRIPS.push([B(w + 7), B(w + 8)]); else if (e === 'sgraf') SGRAF.push([B(w + 6), B(w + 8)]);
      else if (e === 'silk') SILK.push([B(w + 6), B(w + 8), SILKC[hw % 3]]); else FOLD.push([B(w + 6), B(w + 8), 'light']); hw++; } });
  ROLL_ON.forEach((t, i) => { SHOTS.push([t, HOT[i % HOT.length], 0.5 + i * 0.07, i % 2 ? 'raw' : 'ink', {roll: true}]); if (i % 3 === 2) RED.push(t); });
  if (JOIN[0] >= 0) SHOTS.push([JOIN[0], 'hibiscus', 0.3, 'raw', {}]); }
else {
  // Response director (v2): cuts come from Beathi's ranked response events (the same plan.shots the
  // Prismatic Echo template cuts on). Events are grouped into motifs: one clip held for about one bar
  // while its medium is repainted; every response event inside a motif lands an effect. Each section
  // (family) opens on the other colour world, so cold and hot footage alternate through the song.
  const PS = plan.shots.filter(x => x.end > x.start), DUR = plan.duration || BEATS[NB - 1] + 1;
  const bar = Math.max(1.2, 4 * (BEATS[Math.min(NB - 1, 8)] - BEATS[0]) / Math.min(NB - 1, 8));
  const lvlAt = t => (SEGS.find(g => B(g.a) <= t && t < B(g.b)) ?? SEGS[SEGS.length - 1]).lvl ?? 1;
  const fams = new Map(); const motifs = []; let cur = null;
  for (const x of PS) { if (!fams.has(x.family)) fams.set(x.family, fams.size); const newSec = x.kind === 'structure' || x.kind === 'start';
    if (!cur || newSec || x.start - cur.a >= bar * (cur.long ? 2 : 1) - 0.05) { cur = {a: x.start, fam: fams.get(x.family), ev: [], sec: newSec, long: motifs.length % 5 === 3}; motifs.push(cur); }
    cur.ev.push(x); }
  motifs.forEach((m, i) => m.b = motifs[i + 1]?.a ?? DUR);
  const COOL = ['dandelion', 'whiteflower', 'daffodil'], FIRE = ['amaryllis', 'tulips', 'passion', 'orchid', 'hibiscus'];
  const PK = ['ember', 'cobalt', 'violet', 'verdigris', 'sulfur', 'nocturne'];
  const MED = ['oil', 'charcoal', 'oil', 'ink', 'oil', 'oil', 'charcoal', 'oil'];
  const FX = ['zoom', 'red', 'sketch', 'zoom', 'silk', 'red', 'sgraf', 'zoom', 'fold', 'red', 'trip'];
  let nc = 0, nf = 0, fx = 0, busyTo = -1, lastSec = -1, world = 0;
  const peakT = (() => { let best = null; for (const g of SEGS) if (g.a > 8 && (!best || g.lvl > best.lvl)) best = g; return best ? B(best.a) : -1; })();
  motifs.forEach((m, i) => { const t = m.a, len = m.b - m.a, hot = lvlAt(t) >= 0.62;
    if (m.sec || i === 0) { world = (m.fam + (hot ? 1 : 0)) % 2; lastSec = i; }
    const fire = (i - lastSec) % 3 === 2 ? !world : world; // every third motif crosses to the other world for contrast
    const clip = fire ? FIRE[nf++ % FIRE.length] : COOL[nc++ % COOL.length];
    let med = MED[i % MED.length]; if (!hot && med === 'oil' && i % 2) med = i % 4 === 1 ? 'charcoal' : 'ink';
    const opt = med === 'oil' ? {red: hot && fire, tiers: len > 1.5 ? [0, 1, 2] : [0, 2], pk: PK[i % PK.length]} : {quiet: !hot};
    if (len < 0.5) { SH(t, clip, i % 2 ? 'raw' : 'ink', {roll: true}); return; }
    const rawLead = m.ev.length > 1 && i % 3 !== 1; // most motifs show the living footage first, then paint over it on the next response
    SH(t, clip, rawLead ? 'raw' : med, rawLead ? {} : opt); if (rawLead) SH(m.ev[1].start, clip, med, opt);
    if (m.sec || (hot && i % 2 === 0)) REDF.push(t);
    for (const e of m.ev.slice(rawLead ? 2 : 1)) { if (e.start < busyTo) continue; const nx = PS.find(y => y.start > e.start)?.start ?? m.b, el = Math.min(nx, m.b) - e.start;
      const k = FX[fx++ % FX.length];
      if (k === 'zoom') ZOOMS.push([e.start, Math.min(m.b, e.start + Math.max(el, 0.35)), 2 + 0.3 * (fx % 2), 0.35 + 0.15 * (fx % 3), 0.45]);
      else if (k === 'red') REDF.push(e.start);
      else if (k === 'sketch' && el >= 0.25) SKETCH.push([e.start, e.start + Math.min(el, 0.45)]);
      else if (k === 'silk' && m.b - e.start >= 0.6) { SILK.push([e.start, m.b, SILKC[fx % 3]]); busyTo = m.b; }
      else if (k === 'sgraf' && m.b - e.start >= 0.6) { SGRAF.push([e.start, m.b]); busyTo = m.b; }
      else if (k === 'fold' && m.b - e.start >= 0.6) { FOLD.push([e.start, m.b, 'light']); busyTo = m.b; }
      else if (k === 'trip' && m.b - e.start >= 0.9) { TRIPS.push([e.start, m.b]); busyTo = m.b; }
      else REDF.push(e.start); }
  });
  if (peakT > 3) { const m = motifs.findLast(x => x.a <= peakT - 0.1); if (m && peakT - m.a > 1) { JOIN = [m.a, peakT]; SHOTS.push([m.a, 'hibiscus', 0.3, 'raw', {}]); } }
}
SHOTS.sort((a, b) => a[0] - b[0]);
const ALLROLL = ROLL_ON.slice();
let TRIP = TRIPS[0];
const ENDC = Infinity;
const SPLAT = [];

const RW = 960, RH = 540, RLC = mk(RW, RH), RLX = cx2(RLC);
let PREVIEW = false, RLN = 0;
function relief() { if (PREVIEW && (RLN++ % 3)) { out.globalCompositeOperation = 'overlay'; out.globalAlpha = 0.55; out.drawImage(RLC, 0, 0, W, H); out.globalAlpha = 1; out.globalCompositeOperation = 'source-over'; return; } RLX.drawImage(cv, 0, 0, RW, RH); const id = RLX.getImageData(0, 0, RW, RH), d = id.data; const h = new Float32Array(RW * RH);
  for (let i = 0; i < h.length; i++) h[i] = d[i * 4] * 0.3 + d[i * 4 + 1] * 0.59 + d[i * 4 + 2] * 0.11;
  for (let y = 1; y < RH - 1; y++) for (let x = 1; x < RW - 1; x++) { const i = y * RW + x; const v = cl(128 + (h[i - RW - 1] - h[i + RW + 1]) * 1.6, 0, 255); d[i * 4] = d[i * 4 + 1] = d[i * 4 + 2] = v; d[i * 4 + 3] = 255; }
  RLX.putImageData(id, 0, 0); out.globalCompositeOperation = 'overlay'; out.globalAlpha = 0.55; out.drawImage(RLC, 0, 0, W, H); out.globalAlpha = 1; out.globalCompositeOperation = 'source-over'; }
const TPC = mk(W, H), TPX = cx2(TPC);
const TPCOL = [[38, 74, 158], [214, 158, 30], [28, 118, 98], [226, 92, 30]];
const SEED0 = SEED; const TPBG = TPCOL.map((c, i) => { const g = mk(W, H), x = cx2(g); SEED = 91 + i; x.fillStyle = `rgb(${c})`; x.fillRect(0, 0, W, H);
  for (let k = 0; k < 140; k++) { const y = R() * H, x0 = -100 + R() * W, len = 300 + R() * 900, w = 30 + R() * 90, d = (R() - 0.5) * 0.35; const f = 0.8 + R() * 0.4;
    x.strokeStyle = `rgba(${c.map(v => Math.min(255, v * f) | 0)},0.55)`; x.lineWidth = w; x.lineCap = 'round'; x.beginPath(); x.moveTo(x0, y); x.lineTo(x0 + len, y + len * d * 0.2); x.stroke(); }
  x.globalCompositeOperation = 'multiply'; for (let i2 = 0; i2 < W; i2 += 256) for (let j = 0; j < H; j += 256) x.drawImage(weave, i2, j); return g; }); SEED = SEED0;
function triptych(t) { const hb = (TRIP[1] - TRIP[0]) / 3; const n = 1 + Math.floor((t - TRIP[0]) / hb * 1.0001); TPX.drawImage(cv, 0, 0); out.drawImage(TPBG[TRIPS.indexOf(TRIP) % TPBG.length], 0, 0); out.fillStyle = 'rgba(0,0,0,0.55)'; for (let k = 0; k < 3; k++) out.fillRect(28 + k * ((W - 112) / 3 + 28) + 10, 120, (W - 112) / 3, H - 220);
  const g = 28, pw = (W - g * 4) / 3, ph = H - 2 * 110; for (let k = 0; k < Math.min(3, n + 0); k++) { const x = g + k * (pw + g), y = 110; const sx = W / 2 - pw / 2 + (k - 1) * pw * 0.35;
    out.save(); out.beginPath(); out.rect(x, y, pw, ph); out.clip(); out.filter = k === 0 ? 'grayscale(1) contrast(1.6) brightness(1.1)' : k === 2 ? 'grayscale(1) contrast(1.9) brightness(1.05)' : 'none'; out.drawImage(TPC, sx, y, pw, ph, x, y, pw, ph); out.filter = 'none';
    if (k === 2) { out.globalCompositeOperation = 'multiply'; out.fillStyle = '#c3121c'; out.fillRect(x, y, pw, ph); out.globalCompositeOperation = 'source-over'; } out.restore(); } }
const SKC = mk(AW, AH), SKX = cx2(SKC);
// ===== art effects (2026-10-09): sgraffito, silkscreen misregistration, decalcomania fold, joiner =====
const FPS30 = 1 / 30;
const FX1 = mk(W, H), FXX1 = cx2(FX1), FX2 = mk(W, H), FXX2 = cx2(FX2);
const SGC = new Map();
function hiAt(t) { const s = shotAt(t); const F = FRH[s[1]]; return F[fiOf(F.length, t - s[0] + s[2])]; }
function sgStrokes(a) { if (SGC.has(a)) return SGC.get(a); const c = mk(AW, AH), x = cx2(c); x.filter = 'grayscale(1) blur(1px)'; x.drawImage(hiAt(a + 0.02), 0, 0, AW, AH); x.filter = 'none';
  const d = x.getImageData(0, 0, AW, AH).data; const L = new Float32Array(AW * AH); for (let i = 0; i < L.length; i++) L[i] = d[i * 4] / 255;
  const pts = []; let s0 = SEED; SEED = Math.floor(a * 1000) + 17; let tot = 0; const mags = new Float32Array(AW * AH), gxA = new Float32Array(AW * AH), gyA = new Float32Array(AW * AH);
  for (let y = 1; y < AH - 1; y++) for (let X = 1; X < AW - 1; X++) { const i = y * AW + X; const gx = L[i + 1] - L[i - 1] + 0.5 * (L[i - AW + 1] - L[i - AW - 1] + L[i + AW + 1] - L[i + AW - 1]); const gy = L[i + AW] - L[i - AW] + 0.5 * (L[i + AW - 1] - L[i - AW - 1] + L[i + AW + 1] - L[i - AW + 1]); const m = Math.hypot(gx, gy); mags[i] = m > 0.06 ? m * m : 0; gxA[i] = gx; gyA[i] = gy; tot += mags[i]; }
  const cdf = new Float32Array(mags.length); let s = 0; for (let i = 0; i < mags.length; i++) { s += mags[i]; cdf[i] = s; }
  for (let n = 0; n < 1100 && s > 0; n++) { const u = R() * s; let lo = 0, hi = cdf.length - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (cdf[m] < u) lo = m + 1; else hi = m; }
    let px = (lo % AW + R()) * S, py = (((lo / AW) | 0) + R()) * S; const seg = [[px, py]]; const len = 4 + R() * 10;
    for (let k = 0; k < len; k++) { const ix = cl(Math.round(px / S), 1, AW - 2), iy = cl(Math.round(py / S), 1, AH - 2), i = iy * AW + ix; let tx = -gyA[i], ty = gxA[i]; const m = Math.hypot(tx, ty) || 1; tx /= m; ty /= m; if (k && (tx * (px - seg[k - 1][0]) + ty * (py - seg[k - 1][1])) < 0) { tx = -tx; ty = -ty; } px += tx * 6; py += ty * 6; seg.push([px, py]); }
    pts.push({seg, w: 1.6 + R() * 3.4}); }
  SEED = s0; SGC.set(a, pts); return pts; }
function sgraffito(t, a, b) { const mid = a + (b - a) / 2; const all = sgStrokes(a); const N = all.length;
  const n = Math.floor(N * 0.55 * cl((t - a + FPS30) / (3 * FPS30)) + N * 0.45 * (t >= mid ? cl((t - mid + FPS30) / (3 * FPS30)) : 0));
  FXX1.setTransform(1, 0, 0, 1, 0, 0); FXX1.globalCompositeOperation = 'source-over'; FXX1.filter = 'saturate(2.4) contrast(1.25) brightness(1.55)'; FXX1.drawImage(cv, 0, 0); FXX1.filter = 'none';
  FXX2.setTransform(1, 0, 0, 1, 0, 0); FXX2.globalCompositeOperation = 'source-over'; FXX2.clearRect(0, 0, W, H); FXX2.strokeStyle = '#fff'; FXX2.lineCap = 'round'; FXX2.lineJoin = 'round';
  for (let k = 0; k < n; k++) { const {seg, w} = all[k]; FXX2.lineWidth = w; FXX2.beginPath(); seg.forEach(([x, y], i) => i ? FXX2.lineTo(x, y) : FXX2.moveTo(x, y)); FXX2.stroke(); }
  FXX1.globalCompositeOperation = 'destination-in'; FXX1.drawImage(FX2, 0, 0); FXX1.globalCompositeOperation = 'source-over';
  out.fillStyle = '#0c0a09'; out.fillRect(0, 0, W, H); out.globalCompositeOperation = 'overlay'; out.globalAlpha = 0.18; for (let i = 0; i < W; i += 256) for (let j = 0; j < H; j += 256) out.drawImage(weave, i, j); out.globalAlpha = 1; out.globalCompositeOperation = 'source-over';
  out.drawImage(FX1, 0, 0); }
const SKW = 960, SKH = 540, SLC = mk(SKW, SKH), SLX = cx2(SLC); const PL = [0, 1, 2].map(() => { const c = mk(SKW, SKH); return [c, cx2(c)]; });
const DITH = new Float32Array(SKW * SKH); { const s0 = SEED; SEED = 555; for (let i = 0; i < DITH.length; i++) DITH[i] = (R() - 0.5) * 0.12; SEED = s0; }
function silk(t, a, b, col) { const mid = a + (b - a) / 2; SLX.drawImage(cv, 0, 0, SKW, SKH); const d = SLX.getImageData(0, 0, SKW, SKH).data;
  const cols = [col, [195, 18, 28], [22, 18, 18]]; const ids = PL.map(([c, x]) => x.createImageData(SKW, SKH));
  for (let i = 0; i < SKW * SKH; i++) { const L = (d[i * 4] * 0.3 + d[i * 4 + 1] * 0.59 + d[i * 4 + 2] * 0.11) / 255 + DITH[i]; const m = [L > 0.5 && L < 0.86, L > 0.2 && L < 0.58, L < 0.3];
    for (let p = 0; p < 3; p++) { const o = ids[p].data; o[i * 4] = cols[p][0]; o[i * 4 + 1] = cols[p][1]; o[i * 4 + 2] = cols[p][2]; o[i * 4 + 3] = m[p] ? 235 : 0; } }
  PL.forEach(([c, x], p) => x.putImageData(ids[p], 0, 0));
  const reg = t >= mid; const OFF = reg ? [[3, -2], [-2, 1], [0, 0]] : [[-26, 14], [22, -12], [0, 0]];
  out.fillStyle = '#ece2cc'; out.fillRect(0, 0, W, H); out.globalCompositeOperation = 'multiply'; for (let i = 0; i < W; i += 256) for (let j = 0; j < H; j += 256) out.drawImage(weave, i, j);
  PL.forEach(([c], p) => out.drawImage(c, OFF[p][0] - 30, OFF[p][1] - 17, W + 60, H + 34)); out.globalCompositeOperation = 'source-over'; }
function fold(t, a, b, m) { const mid = a + (b - a) / 2; if (t < mid) return; FXX1.setTransform(1, 0, 0, 1, 0, 0); FXX1.globalCompositeOperation = 'source-over'; FXX1.drawImage(cv, 0, 0);
  if (m === 'light') { out.save(); out.globalCompositeOperation = 'lighten'; out.translate(W, 0); out.scale(-1, 1); out.drawImage(FX1, 0, 0); out.restore(); out.globalCompositeOperation = 'source-over'; return; }
  if (m === 'glow') { out.save(); out.globalCompositeOperation = 'darken'; out.translate(W, 0); out.scale(-1, 1); out.drawImage(FX1, 0, 0); out.restore(); out.globalCompositeOperation = 'source-over'; return; }
  out.save(); out.beginPath(); out.rect(W / 2, 0, W / 2, H); out.clip(); out.fillStyle = '#e8e0d0'; out.globalAlpha = 0.5; out.fillRect(W / 2, 0, W / 2, H); out.globalAlpha = 1;
  out.translate(W, 0); out.scale(-1, 1); out.filter = 'grayscale(0.3) contrast(1.9) blur(1.2px)'; out.globalCompositeOperation = 'multiply'; out.drawImage(FX1, 4, 3); out.filter = 'none'; out.restore(); out.globalCompositeOperation = 'source-over';
  const g = out.createLinearGradient(W / 2 - 14, 0, W / 2 + 14, 0); g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(0.45, 'rgba(20,16,14,0.45)'); g.addColorStop(0.55, 'rgba(255,250,240,0.35)'); g.addColorStop(1, 'rgba(0,0,0,0)'); out.fillStyle = g; out.fillRect(W / 2 - 14, 0, 28, H); }
const JT = [[60, 70, 700, 470, -4], [700, 40, 640, 450, 3], [1260, 90, 600, 440, -2], [40, 520, 620, 500, 2.5], [600, 470, 720, 520, -3.5], [1250, 520, 620, 500, 5], [360, 260, 560, 420, 6], [980, 300, 560, 400, -5.5]];
function joiner(t) { const [a, b] = JOIN; const n = Math.min(JT.length, 1 + Math.floor((t - a) / ((b - a) / JT.length) + 1e-4)); out.drawImage(TPBG[2], 0, 0); const F = FRH.hibiscus;
  for (let k = 0; k < n; k++) { const [x, y, w, h, r] = JT[k]; const img = F[fiOf(F.length, 0.4 + k * 0.53)]; out.save(); out.translate(x + w / 2, y + h / 2); out.rotate(r * Math.PI / 180);
    out.shadowColor = 'rgba(0,0,0,0.5)'; out.shadowBlur = 22; out.shadowOffsetY = 8; out.fillStyle = '#f3efe6'; out.fillRect(-w / 2 - 12, -h / 2 - 12, w + 24, h + 24); out.shadowColor = 'transparent';
    out.filter = 'contrast(1.15) saturate(0.9)'; const sx = (x + w / 2 - W / 2) * 0.3 + W / 2 - w / 2, sy = (y + h / 2 - H / 2) * 0.3 + H / 2 - h / 2; out.drawImage(img, sx / W * img.width, sy / H * img.height, w / W * img.width, h / H * img.height, -w / 2, -h / 2, w, h); out.filter = 'none'; out.restore(); } }
function artFx(t) { for (const [a, b] of SGRAF) if (t >= a && t < b) sgraffito(t, a, b); for (const [a, b, c] of SILK) if (t >= a && t < b) silk(t, a, b, c);
  for (const [a, b, m] of FOLD) if (t >= a && t < b) fold(t, a, b, m); if (t >= JOIN[0] && t < JOIN[1]) joiner(t); }

function sketch(hi) { SKX.filter = 'grayscale(1) blur(0.6px)'; SKX.drawImage(hi, 0, 0, AW, AH); SKX.filter = 'none'; const id = SKX.getImageData(0, 0, AW, AH), d = id.data; const L = new Float32Array(AW * AH); for (let i = 0; i < L.length; i++) L[i] = d[i * 4];
  for (let y = 1; y < AH - 1; y++) for (let x = 1; x < AW - 1; x++) { const i = y * AW + x; const gx = L[i + 1] - L[i - 1] + 0.5 * (L[i - AW + 1] - L[i - AW - 1] + L[i + AW + 1] - L[i + AW - 1]), gy = L[i + AW] - L[i - AW] + 0.5 * (L[i + AW - 1] - L[i - AW - 1] + L[i + AW + 1] - L[i - AW + 1]); const m = Math.hypot(gx, gy);
    const v = 255 - cl(m * 2.4 - 18, 0, 235) - (L[i] < 70 ? 40 : 0); d[i * 4] = v * 0.98; d[i * 4 + 1] = v * 0.95; d[i * 4 + 2] = v * 0.9; }
  SKX.putImageData(id, 0, 0); { const p4 = PALS[4][1]; out.fillStyle = `rgb(${p4[0]},${p4[1]},${p4[2]})`; out.fillRect(0, 0, W, H); } out.globalCompositeOperation = 'multiply'; out.globalAlpha = 0.6; out.drawImage(charPaper, 0, 0); out.globalAlpha = 1; out.drawImage(SKC, 0, 0, W, H); out.globalCompositeOperation = 'screen'; { const p1 = PALS[1][1]; out.fillStyle = `rgb(${p1[0]},${p1[1]},${p1[2]})`; out.fillRect(0, 0, W, H); } out.globalCompositeOperation = 'source-over'; } const RT = mk(W, H), RTX = cx2(RT);
const SHOT_T = SHOTS.map(s => s[0]);
const shotAt = t => SHOTS[cl(lastIdx(SHOT_T, t), 0, SHOTS.length - 1)];
const plaster = makePaper('#d9c7a6', 0.3, 0.2, 91); const cyanPaper = makePaper('#ece8db', 0.14, 0.1, 93);

// ---------- paint state ----------
const PC = mk(W, H), P = cx2(PC);
const small = mk(AW, AH), SM = cx2(small);
const srcC = mk(AW, AH), SC = cx2(srcC);
const coldpress = makePaper('#f5f1e7', 0.2, 0.1, 61); const etchPaper = makePaper('#eee3cc', 0.12, 0.1, 71);
const GROUND = {oil: null, ink: rice, charcoal: charPaper, vg: null, water: coldpress, etch: etchPaper};
function ground(med, keep = 0) {
  P.setTransform(1, 0, 0, 1, 0, 0); P.globalCompositeOperation = 'source-over'; P.filter = 'none';
  P.globalAlpha = 1 - keep; if (med === 'under') { P.clearRect(0, 0, W, H); P.globalAlpha = 1; return; }
  if (med === 'dark') { const c = mk(W, H), x = cx2(c); const g0 = PALS[1][1]; x.fillStyle = `rgb(${g0[0] * 0.55 | 0},${g0[1] * 0.55 | 0},${g0[2] * 0.55 | 0})`; x.fillRect(0, 0, W, H); x.globalCompositeOperation = 'overlay'; x.globalAlpha = 0.25; for (let i = 0; i < W; i += 256) for (let j = 0; j < H; j += 256) x.drawImage(weave, i, j); P.drawImage(c, 0, 0); }
  else if (med === 'oil' || med === 'vg') { const c = mk(W, H), x = cx2(c); x.fillStyle = med === 'vg' ? '#c9a873' : '#b9a789'; x.fillRect(0, 0, W, H); x.globalCompositeOperation = 'multiply'; for (let i = 0; i < W; i += 256) for (let j = 0; j < H; j += 256) x.drawImage(weave, i, j); P.drawImage(c, 0, 0); }
  else if (med === 'charcoal') P.drawImage(tonedPaper(), 0, 0);
  else P.drawImage(GROUND[med], 0, 0);
  P.globalAlpha = 1;
}
let TONK = null, TONC = null;
function tonedPaper() { if (TONK === PALS) return TONC; TONK = PALS; const c = TONC || mk(W, H), x = cx2(c); TONC = c; const g0 = PALS[1][1], g1 = PALS[0][1]; x.globalCompositeOperation = 'source-over'; x.globalAlpha = 1; x.fillStyle = `rgb(${(g0[0] * 0.6 + g1[0] * 0.4) | 0},${(g0[1] * 0.6 + g1[1] * 0.4) | 0},${(g0[2] * 0.6 + g1[2] * 0.4) | 0})`; x.fillRect(0, 0, W, H); x.globalCompositeOperation = 'overlay'; x.globalAlpha = 0.5; x.drawImage(charPaper, 0, 0); x.globalAlpha = 0.3; for (let i = 0; i < W; i += 256) for (let j = 0; j < H; j += 256) x.drawImage(weave, i, j); x.globalCompositeOperation = 'source-over'; x.globalAlpha = 1; return c; }
const N = AW * AH; const jxx = new Float32Array(N), jxy = new Float32Array(N), jyy = new Float32Array(N), t2 = new Float32Array(N);
function boxBlur(a, r, o) { for (let y = 0; y < AH; y++) { let s = 0; for (let x = -r; x <= r; x++) s += a[y * AW + cl(x, 0, AW - 1)]; for (let x = 0; x < AW; x++) { t2[y * AW + x] = s / (2 * r + 1); s += a[y * AW + Math.min(AW - 1, x + r + 1)] - a[y * AW + Math.max(0, x - r)]; } }
  for (let x = 0; x < AW; x++) { let s = 0; for (let y = -r; y <= r; y++) s += t2[cl(y, 0, AH - 1) * AW + x]; for (let y = 0; y < AH; y++) { o[y * AW + x] = s / (2 * r + 1); s += t2[Math.min(AH - 1, y + r + 1) * AW + x] - t2[Math.max(0, y - r) * AW + x]; } } return o; }
const bxx = new Float32Array(N), bxy = new Float32Array(N), byy = new Float32Array(N), lum = new Float32Array(N);
const TD = new Uint8ClampedArray(N * 4); let SD;
const INK = [16, 14, 14], REDC = [178, 18, 26]; let PAL = false, REDP = 0, LBI = -1;
const ST = [0, 0.22, 0.42, 0.62, 0.82, 1]; const mkp = cs => cs.map((c, i) => [ST[i], c]);
const PALSET = {
  nocturne: mkp([[18, 14, 13], [30, 38, 58], [74, 62, 56], [156, 120, 78], [214, 196, 160], [240, 232, 214]]),
  ember: mkp([[16, 8, 6], [70, 16, 14], [140, 54, 24], [210, 112, 36], [238, 190, 104], [252, 238, 206]]),
  cobalt: mkp([[8, 12, 26], [16, 34, 82], [36, 76, 150], [92, 138, 190], [176, 204, 222], [240, 244, 240]]),
  verdigris: mkp([[8, 16, 14], [18, 52, 46], [44, 98, 86], [112, 150, 120], [196, 206, 170], [240, 236, 214]]),
  violet: mkp([[14, 8, 22], [44, 22, 74], [104, 52, 118], [176, 92, 132], [226, 172, 186], [250, 236, 238]]),
  sulfur: mkp([[10, 11, 10], [34, 38, 36], [66, 70, 58], [124, 114, 62], [192, 172, 98], [238, 228, 192]])};
let PALS = PALSET.nocturne;
const CLIPPAL = {dandelion: 'cobalt', whiteflower: 'nocturne', daffodil: 'sulfur', amaryllis: 'ember', tulips: 'ember', passion: 'violet', orchid: 'violet', hibiscus: 'cobalt', rose: 'violet', alstro: 'verdigris'};
function palMap(L, r, g, b) { L = cl((L - 0.08) / 0.84); let k = 0; while (k < PALS.length - 2 && PALS[k + 1][0] < L) k++; const [a0, c0] = PALS[k], [a1, c1] = PALS[k + 1]; const u = cl((L - a0) / (a1 - a0));
  const o = [c0[0] + (c1[0] - c0[0]) * u, c0[1] + (c1[1] - c0[1]) * u, c0[2] + (c1[2] - c0[2]) * u]; const warm = (r - (g + b) / 2) / 255; if (warm > 0.32 && L > 0.15 && L < 0.7) { const w = cl((warm - 0.32) * 4); o[0] += (REDC[0] - o[0]) * w; o[1] += (REDC[1] - o[1]) * w; o[2] += (REDC[2] - o[2]) * w; } return o; }
let AN_K = null;
function analyse(img, med, red) { const ak = [img, med, red, PAL, PALS]; if (AN_K && ak.every((v, i) => v === AN_K[i])) return; AN_K = ak;
  SC.filter = med === 'water' ? 'blur(3px)' : 'none'; SC.drawImage(img, 0, 0, AW, AH); SC.filter = 'none'; SD = SC.getImageData(0, 0, AW, AH).data;
  for (let i = 0; i < N; i++) lum[i] = (SD[i * 4] * 0.3 + SD[i * 4 + 1] * 0.59 + SD[i * 4 + 2] * 0.11) / 255;
  let LLO = 0, LHI = 1; if (PAL) { const hs = new Uint32Array(256); for (let i = 0; i < N; i += 7) hs[(lum[i] * 255) | 0]++; let acc = 0, tot = Math.ceil(N / 7); for (let v = 0; v < 256; v++) { acc += hs[v]; if (acc < tot * 0.04) LLO = v / 255; if (acc < tot * 0.97) LHI = v / 255; } }
  for (let y = 1; y < AH - 1; y++) for (let x = 1; x < AW - 1; x++) { const i = y * AW + x; const gx = lum[i + 1] - lum[i - 1], gy = lum[i + AW] - lum[i - AW]; jxx[i] = gx * gx; jxy[i] = gx * gy; jyy[i] = gy * gy; }
  boxBlur(jxx, 5, bxx); boxBlur(jxy, 5, bxy); boxBlur(jyy, 5, byy);
  // target image per medium
  for (let i = 0; i < N; i++) { const L = lum[i], j = i * 4; let r = SD[j], g = SD[j + 1], b = SD[j + 2];
    if (med === 'ink') { const c = L < 0.36 ? INK : (L < 0.55 && red) ? REDC : [241, 236, 224]; r = c[0]; g = c[1]; b = c[2]; }
  else if (med === 'charcoal') { const m = palMap(0.08 + 0.84 * Math.pow(cl((L - 0.12) / 0.7), 1.15), r, g, b); r = m[0]; g = m[1]; b = m[2]; }
    else if (med === 'vg') { const m = (r + g + b) / 3; r = cl(m + (r - m) * 1.9, 0, 255); g = cl(m + (g - m) * 1.8, 0, 255); b = cl(m + (b - m) * 1.9 + 10, 0, 255); }
    else if (med === 'water') { r = r * 0.62 + 98; g = g * 0.62 + 96; b = b * 0.6 + 92; }
    else if (med === 'etch') { const v = 25 + Math.pow(cl((L - 0.12) / 0.7), 1.1) * 215; r = v; g = v * 0.95; b = v * 0.88; }
    else if (med === 'oil' && PAL) { const m = palMap(0.08 + 0.84 * cl((L - LLO) / Math.max(0.1, LHI - LLO)), r, g, b); r = m[0]; g = m[1]; b = m[2]; }
    else if (med === 'oil') { // Turner-ish warm storm: lift into ochre/umber
      r = cl(r * 1.15 + 22, 0, 255); g = cl(g * 1.02 + 8, 0, 255); b = cl(b * 0.8, 0, 255); }
    TD[j] = r; TD[j + 1] = g; TD[j + 2] = b; TD[j + 3] = 255; }
}
const ix = (x, y) => cl(Math.round(y), 0, AH - 1) * AW + cl(Math.round(x), 0, AW - 1);
const dirAt = (x, y) => { const i = ix(x, y); return 0.5 * Math.atan2(2 * bxy[i], bxx[i] - byy[i]) + Math.PI / 2; };
const edgeAt = (x, y) => { const i = ix(x, y); return bxx[i] + byy[i]; };
const colAt = (x, y) => { const i = ix(x, y) * 4; return [TD[i], TD[i + 1], TD[i + 2]]; };
const GC = 8, GW = AW / GC, GH = AH / GC; const err = new Float32Array(GW * GH);
let DARKEN = false;
function errorMap() {
  SM.drawImage(PC, 0, 0, AW, AH); const PD = SM.getImageData(0, 0, AW, AH).data; err.fill(0);
  for (let y = 0; y < AH; y += 2) for (let x = 0; x < AW; x += 2) { const i = (y * AW + x) * 4; const d = DARKEN ? Math.max(0, (PD[i] + PD[i + 1] + PD[i + 2]) - (TD[i] + TD[i + 1] + TD[i + 2]) - 30) : Math.abs(PD[i] - TD[i]) + Math.abs(PD[i + 1] - TD[i + 1]) + Math.abs(PD[i + 2] - TD[i + 2]); err[((y / GC) | 0) * GW + ((x / GC) | 0)] += d; }
  for (let i = 0; i < err.length; i++) err[i] /= (GC * GC / 4) * 3 * 255;
}
function trace(x, y, len, step, rot = 0) { const pts = [[x, y]]; let px = x, py = y, prev = dirAt(x, y) + rot; const c = colAt(x, y); for (let s = 0; s < len; s += step) { let a = dirAt(px, py) + rot; if (Math.cos(a - prev) < 0) a += Math.PI; prev = a; px += Math.cos(a) * step; py += Math.sin(a) * step; const cc = colAt(px, py); if (Math.abs(cc[0] - c[0]) + Math.abs(cc[1] - c[1]) + Math.abs(cc[2] - c[2]) > 80 && s > len * 0.35) break; pts.push([px, py]); } return pts; }

// ---------- growing strokes ----------
let QUEUE = [];
function mkStroke(x, y, w, med, rot = 0) {
  const c = colAt(x, y); if (med === 'etch' && c[0] > 205) return null; if (med === 'ink' && c[0] > 230) return null; if (med === 'charcoal' && c[0] + c[1] + c[2] < 150) return null;
  const lenF = med === 'etch' ? 5 + R() * 4 : med === 'vg' ? 1.6 + R() * 1.2 : med === 'charcoal' ? 4 + R() * 4 : med === 'ink' ? 3 + R() * 4 : 3.5 + R() * 3;
  const ap = trace(x, y, (w / S) * lenF, Math.max(1.2, w / S * 0.35), rot); if (ap.length < 2) ap.push([x + 0.8, y]);
  const pts = ap.map(p => [p[0] * S, p[1] * S]);
  const nrm = pts.map((p, i) => { const q = pts[Math.min(i + 1, pts.length - 1)], o = pts[Math.max(i - 1, 0)]; const a = Math.atan2(q[1] - o[1], q[0] - o[0]); return [-Math.sin(a), Math.cos(a)]; });
  if (REDP > 0 && med === 'oil' && w > 14 && c[0] + c[1] + c[2] > 150 && c[0] + c[1] + c[2] < 560 && R() < REDP) { c[0] = REDC[0]; c[1] = REDC[1]; c[2] = REDC[2]; }
  const j = (R() - 0.5) * (med === 'vg' ? 40 : 22); const col = [cl(c[0] + j, 0, 255) | 0, cl(c[1] + j, 0, 255) | 0, cl(c[2] + j * 0.8, 0, 255) | 0];
  const lines = []; const [r, g, b] = col;
  if (med === 'oil' || med === 'vg') {
    if (med === 'vg') lines.push([0, w * 1.08, `rgba(${r * 0.4 | 0},${g * 0.4 | 0},${b * 0.45 | 0},0.3)`]);
    lines.push([0, w, `rgba(${r},${g},${b},0.93)`]);
    if (w >= 4) { const nb = Math.round(cl(w / 4, 3, 10)); for (let k = 0; k < nb; k++) { const o = (R() - 0.5) * 0.9 * w; const dk = R() < 0.55;
      lines.push([o, Math.max(0.7, w * (0.03 + R() * 0.06)), dk ? `rgba(${r * 0.62 | 0},${g * 0.6 | 0},${b * 0.62 | 0},${0.18 + R() * 0.25})` : `rgba(${Math.min(255, r * 1.15 + 20) | 0},${Math.min(255, g * 1.15 + 20) | 0},${Math.min(255, b * 1.12 + 20) | 0},${0.15 + R() * 0.2})`]); }
      lines.push([-w * 0.38, Math.max(0.8, w * 0.1), `rgba(${Math.min(255, r * 1.25 + 38) | 0},${Math.min(255, g * 1.25 + 38) | 0},${Math.min(255, b * 1.2 + 38) | 0},0.45)`]);
      lines.push([w * 0.47, Math.max(0.8, w * 0.09), 'rgba(18,10,6,0.22)']); }
  } else if (med === 'ink') { const a = 0.78 + R() * 0.2; lines.push([0, w, `rgba(${r},${g},${b},${a})`]); if (R() < 0.5) lines.push([(R() - 0.5) * 0.6 * w, Math.max(0.6, w * 0.04), 'rgba(241,236,224,0.28)']); lines.push([w * 0.45, Math.max(0.8, w * 0.12), `rgba(${r},${g},${b},0.35)`]); }
  else if (med === 'etch') { const d = (255 - c[0]) / 255; const nl = d > 0.6 ? 4 : 3; for (let k = 0; k < nl; k++) lines.push([(k - (nl - 1) / 2) * w / nl, 1.0 + d * 0.8, `rgba(32,22,16,${0.55 + 0.4 * d})`]); }
  else if (med === 'charcoal') { const d = cl((c[0] + c[1] + c[2]) / 765 * 1.3); for (let k = 0; k < 3; k++) { const lf = 1 + R() * 0.18; lines.push([(R() - 0.5) * w, 1.4 + R() * 2.6, `rgba(${Math.min(255, r * lf + 8) | 0},${Math.min(255, g * lf + 8) | 0},${Math.min(255, b * lf + 8) | 0},${Math.min(1, (0.35 + 0.65 * d) * (0.65 + R() * 0.35))})`]); } }
  return {pts, nrm, lines, done: 1, speed: (med === 'charcoal' || med === 'ink') ? Math.ceil(pts.length / 2) + 1 : Math.max(2, Math.ceil(pts.length / 5))};
}
function growStrokes() {
  P.lineCap = 'round'; P.lineJoin = 'round'; P.globalAlpha = 1; P.globalCompositeOperation = 'source-over';
  for (const s of QUEUE) { const a = Math.max(0, s.done - 1), b = Math.min(s.pts.length, s.done + s.speed);
    for (const [o, lw, cs] of s.lines) { P.strokeStyle = cs; P.lineWidth = lw; P.beginPath(); for (let i = a; i < b; i++) { const x = s.pts[i][0] + s.nrm[i][0] * o, y = s.pts[i][1] + s.nrm[i][1] * o; if (i === a) P.moveTo(x, y); else P.lineTo(x, y); } if (b - a === 1) P.lineTo(s.pts[a][0] + 0.5, s.pts[a][1]); P.stroke(); }
    s.done = b; }
  QUEUE = QUEUE.filter(s => s.done < s.pts.length);
}
function blob(x, y, w) { const c = colAt(x, y); const a = dirAt(x, y); P.save(); P.globalCompositeOperation = 'multiply'; P.translate(x * S, y * S); P.rotate(a);
  const rx = w * (1.4 + R() * 0.8), ry = w * (0.7 + R() * 0.4); P.beginPath(); for (let i = 0; i <= 14; i++) { const th = i / 14 * 6.283; const rr = 1 + (R() - 0.5) * 0.25; P.lineTo(Math.cos(th) * rx * rr, Math.sin(th) * ry * rr); } P.closePath();
  P.fillStyle = `rgba(${c[0]},${c[1]},${c[2]},0.3)`; P.fill(); P.strokeStyle = `rgba(${c[0] * 0.75 | 0},${c[1] * 0.75 | 0},${c[2] * 0.78 | 0},0.35)`; P.lineWidth = 1.6; P.stroke(); P.restore(); }
const cdf = new Float32Array(GW * GH);
function paint(count, wBig, wSmall, thr, med) {
  let s = 0; for (let i = 0; i < err.length; i++) { const e = err[i] > thr ? err[i] * err[i] : 0; s += e; cdf[i] = s; } if (s <= 0) return;
  const list = [];
  for (let n = 0; n < count; n++) { const u = R() * s; let lo = 0, hi = cdf.length - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (cdf[m] < u) lo = m + 1; else hi = m; }
    const gx = lo % GW, gy = (lo / GW) | 0; const x = (gx + R()) * GC, y = (gy + R()) * GC; const k = cl(edgeAt(x, y) * 60);
    const w = (wBig + (wSmall - wBig) * k) * (0.75 + R() * 0.5);
    if (med === 'water') { blob(x, y, w); continue; }
    const st = mkStroke(x, y, w, med); if (st) list.push([w, st]);
    if (med === 'etch' && colAt(x, y)[0] < 120) { const s2 = mkStroke(x, y, w, med, 1.05); if (s2) list.push([w, s2]); } }
  list.sort((a, b) => b[0] - a[0]); for (const [, st] of list) QUEUE.push(st);
}

// ---------- woodblock (printed block by block) ----------
const QW = 960, QH = 540; const qc = mk(QW, QH), QX = cx2(qc); const WOOD = mk(W, H), WX = cx2(WOOD);
const WPAL = [[251, 246, 232], [196, 210, 206], [126, 164, 190], [47, 93, 138], [24, 36, 70]];
const layerC = mk(QW, QH), LX = cx2(layerC);
let CUTP = null;
function woodFrame(img, t) {
  QX.filter = 'blur(2.5px) contrast(1.25)'; QX.drawImage(img, 0, 0, QW, QH); QX.filter = 'none'; const d = QX.getImageData(0, 0, QW, QH).data;
  const Ls = new Float32Array(QW * QH); for (let i = 0; i < QW * QH; i++) Ls[i] = (d[i * 4] * 0.3 + d[i * 4 + 1] * 0.59 + d[i * 4 + 2] * 0.11) / 255;
  if (!CUTP) { const so = Array.from(Ls.filter((_, i) => i % 7 === 0)).sort((a, b) => a - b); CUTP = [0.82, 0.6, 0.36, 0.14].map(q => so[Math.floor(q * so.length)]); }
  const cls = new Uint8Array(QW * QH); for (let i = 0; i < QW * QH; i++) { const L = Ls[i]; cls[i] = L > CUTP[0] ? 0 : L > CUTP[1] ? 1 : L > CUTP[2] ? 2 : L > CUTP[3] ? 3 : 4; }
  WX.globalCompositeOperation = 'source-over'; WX.globalAlpha = 1; WX.drawImage(washi, 0, 0);
  const bi = lastIdx(BEATS, t); const nLayers = bi - 18 + 1; // beat 18 (8.09s) prints block 1
  for (let k = 1; k <= 5; k++) { if (k > nLayers) break; const isKey = k === 5; const id = LX.createImageData(QW, QH), o = id.data;
    const c = isKey ? [18, 24, 48] : WPAL[k];
    for (let y = 0; y < QH; y++) for (let x = 0; x < QW; x++) { const i = y * QW + x; let on;
      if (isKey) { const c0 = cls[i]; on = x < QW - 1 && y < QH - 1 && (Math.abs(c0 - cls[i + 1]) + Math.abs(c0 - cls[i + QW]) > 0) && c0 >= 2; }
      else on = cls[i] >= k; if (on) { o[i * 4] = c[0]; o[i * 4 + 1] = c[1]; o[i * 4 + 2] = c[2]; o[i * 4 + 3] = isKey ? 235 : 240; } }
    LX.putImageData(id, 0, 0);
    // baren rub: newest block wipes in over 0.18s
    const tb = B(18 + k - 1); const wp = k === nLayers ? cl((t - tb) / 0.18) : 1; if (wp <= 0) continue;
    const mx = (k % 2 ? 1 : -1) * 3, my = (k % 3) - 1;
    WX.save(); WX.beginPath(); WX.rect(0, 0, W * wp, H); WX.clip(); WX.globalCompositeOperation = 'source-over'; WX.globalAlpha = 0.9; WX.imageSmoothingEnabled = true; WX.drawImage(layerC, mx, my, W, H); WX.restore(); }
  WX.globalCompositeOperation = 'multiply'; WX.globalAlpha = 0.07; WX.drawImage(woodgrain, 0, 0); WX.globalAlpha = 0.6; WX.drawImage(washi, 0, 0); WX.globalAlpha = 1; WX.globalCompositeOperation = 'source-over';
}

// ---------- render ----------
let lastF = -1, lastShot = null; const FPS = 30;
const pulse = (t, arr, k) => { const i = lastIdx(arr, t); return i < 0 ? 0 : Math.exp(-(t - arr[i]) * k); };
const NZ = (() => { const c = noiseCanvas(AW, AH, 20, 12, 81), x = cx2(c); x.globalCompositeOperation = 'overlay'; x.drawImage(noiseCanvas(AW, AH, 90, 50, 82), 0, 0); const d = x.getImageData(0, 0, AW, AH).data; const o = new Float32Array(AW * AH); for (let i = 0; i < o.length; i++) o[i] = d[i * 4] / 255; return o; })();
const wc = mk(AW, AH), WCX = cx2(wc);
const WG = [[0, [38, 48, 86]], [0.3, [70, 92, 128]], [0.5, [164, 120, 84]], [0.7, [214, 186, 150]], [0.85, [245, 241, 231]], [1, [255, 255, 255]]];
function wcGrad(L) { L = cl((L - 0.15) / 0.75); for (let i = 1; i < WG.length; i++) if (L <= WG[i][0]) { const u = (L - WG[i - 1][0]) / (WG[i][0] - WG[i - 1][0]); return WG[i - 1][1].map((v, k) => v + (WG[i][1][k] - v) * u); } return WG[WG.length - 1][1]; }
function waterFrame(img, t, t0) {
  WCX.filter = 'blur(6px) contrast(1.3)'; WCX.drawImage(img, 0, 0, AW, AH); WCX.filter = 'none'; const id = WCX.getImageData(0, 0, AW, AH), d = id.data;
  const bi = lastIdx(BEATS, t) - lastIdx(BEATS, t0); const bp = pulse(t, BEATS, 5); const prog = cl(0.18 + bi * 0.2 + (1 - bp) * 0.08, 0, 1.2);
  const q = new Uint8Array(AW * AH);
  for (let i = 0; i < AW * AH; i++) { const L = (d[i * 4] * 0.3 + d[i * 4 + 1] * 0.59 + d[i * 4 + 2] * 0.11) / 255; q[i] = Math.min(5, Math.floor(L * 6)); }
  for (let y = 0; y < AH; y++) for (let x = 0; x < AW; x++) { const i = y * AW + x, j = i * 4; const L = q[i] / 5;
    const edge = (x < AW - 1 && q[i + 1] !== q[i]) || (y < AH - 1 && q[i + AW] !== q[i]) || (x > 0 && q[i - 1] !== q[i]);
    // pigment: flattened tone, lifted toward paper, slightly cool
    const Lc = (d[j] * 0.3 + d[j + 1] * 0.59 + d[j + 2] * 0.11) / 255; const pg = wcGrad(Lc); let r = pg[0], g = pg[1], b = pg[2]; if (edge) { r *= 0.72; g *= 0.72; b *= 0.76; }
    const m = cl(((prog - NZ[i] * 0.9) - 0.02) / 0.06); // wet bloom front
    const front = m > 0 && m < 1 ? 0.75 : 1; d[j] = r * front; d[j + 1] = g * front; d[j + 2] = b * front; d[j + 3] = m * 255; }
  WCX.putImageData(id, 0, 0);
  P.setTransform(1, 0, 0, 1, 0, 0); P.globalAlpha = 1; P.globalCompositeOperation = 'source-over'; P.drawImage(coldpress, 0, 0);
  P.globalCompositeOperation = 'multiply'; P.imageSmoothingEnabled = true; P.drawImage(wc, 0, 0, W, H); P.globalAlpha = 0.5; P.drawImage(coldpress, 0, 0); P.globalAlpha = 1; P.globalCompositeOperation = 'source-over';
}
const EW = 960, EH = 540; const ec = mk(EW, EH), ECX = cx2(ec);
function etchFrame(img, t, t0) {
  ECX.filter = 'blur(1px) contrast(1.2)'; ECX.drawImage(img, 0, 0, EW, EH); ECX.filter = 'none'; const id = ECX.getImageData(0, 0, EW, EH), d = id.data;
  const nb = FULL ? 9 : lastIdx(BEATS, t) - lastIdx(BEATS, t0) + 2; const front = FULL || !ACID ? 1e9 : (t - t0) / 0.4 * (EW + 200) - 100;
  const TH = [0.78, 0.55, 0.36, 0.2]; const ANG = [[1, 0.35], [0.5, -1], [-1, 0.9], [1, 1]];
  const lumA = new Float32Array(EW * EH); for (let i = 0; i < EW * EH; i++) lumA[i] = (d[i * 4] * 0.3 + d[i * 4 + 1] * 0.59 + d[i * 4 + 2] * 0.11) / 255;
  for (let y = 0; y < EH; y++) for (let x = 0; x < EW; x++) { const i = y * EW + x, L = lumA[i]; let ink = 0; if (x > front + NZ[((y / 1.5) | 0) * AW + ((x / 1.5) | 0)] * 120) { d[i * 4 + 3] = 0; continue; }
    for (let k = 0; k < Math.min(nb, 4); k++) { if (L >= TH[k]) continue; const [ax, ay] = ANG[k]; const ph = (x * ax + y * ay) / 4.2 + L * 3.0; const f = ph - Math.floor(ph); const wdt = 0.18 + 0.5 * (TH[k] - L) / TH[k]; if (f < wdt) { ink = Math.max(ink, 0.9); } }
    const e = x > 0 && y > 0 ? Math.abs(L - lumA[i - 1]) + Math.abs(L - lumA[i - EW]) : 0; if (e > 0.16) ink = Math.max(ink, 0.95);
    d[i * 4] = 34; d[i * 4 + 1] = 24; d[i * 4 + 2] = 18; d[i * 4 + 3] = ink * 255; }
  ECX.putImageData(id, 0, 0);
  P.setTransform(1, 0, 0, 1, 0, 0); P.globalAlpha = 1; P.globalCompositeOperation = 'source-over'; P.drawImage(etchPaper, 0, 0);
  P.imageSmoothingEnabled = true; P.drawImage(ec, 0, 0, W, H); P.globalCompositeOperation = 'multiply'; P.globalAlpha = 0.35; P.drawImage(etchPaper, 0, 0); P.globalAlpha = 1; P.globalCompositeOperation = 'source-over';
  if (ACID && !FULL) { const fx = front / EW * W; const a = cl(1 - (t - t0 - 0.4) / 0.6); if (a > 0) { P.globalCompositeOperation = 'multiply'; P.fillStyle = `rgba(196,206,150,${0.55 * a})`; P.fillRect(0, 0, Math.min(W, fx + 60), H); P.globalCompositeOperation = 'source-over';
    if (fx < W + 100) { SEED = 31; for (let k = 0; k < 160; k++) { const y = R() * H, x = fx + NZ[((y / 3) | 0) * AW] * 80 - R() * 50; P.strokeStyle = 'rgba(70,80,40,0.5)'; P.lineWidth = 1.2; P.beginPath(); P.arc(x, y, 2 + R() * 6, 0, 6.283); P.stroke(); } } } }
}
// ---- cyanotype: exposure develops one step per beat
const EWc = 960, EHc = 540; const cy = mk(EWc, EHc), CYX = cx2(cy);
const coat = (() => { const c = mk(W, H), x = cx2(c); SEED = 777; x.fillStyle = '#fff'; x.beginPath(); x.moveTo(90, 70); for (let i = 0; i <= 40; i++) x.lineTo(90 + i * (W - 180) / 40, 70 + (R() - 0.5) * 30); for (let i = 0; i <= 24; i++) x.lineTo(W - 90 + (R() - 0.5) * 40, 70 + i * (H - 140) / 24); for (let i = 40; i >= 0; i--) x.lineTo(90 + i * (W - 180) / 40, H - 70 + (R() - 0.5) * 30); for (let i = 24; i >= 0; i--) x.lineTo(90 + (R() - 0.5) * 40, 70 + i * (H - 140) / 24); x.fill();
  x.globalCompositeOperation = 'destination-out'; for (let i = 0; i < 400; i++) { const e = R() < 0.5; x.fillStyle = 'rgba(0,0,0,0.6)'; x.fillRect(e ? (R() < 0.5 ? 70 + R() * 50 : W - 120 + R() * 50) : 90 + R() * (W - 180), e ? 70 + R() * (H - 140) : (R() < 0.5 ? 55 + R() * 35 : H - 90 + R() * 35), 2 + R() * 18, 1 + R() * 3); } return c; })();
function cyanFrame(img, t, t0) {
  CYX.filter = 'contrast(1.25)'; CYX.drawImage(img, 0, 0, EWc, EHc); CYX.filter = 'none'; const id = CYX.getImageData(0, 0, EWc, EHc), d = id.data;
  const nb = FULL ? 4 : lastIdx(BEATS, t) - lastIdx(BEATS, t0) + 1; const e = cl(nb / 4 + (t - BEATS[lastIdx(BEATS, t)]) * 0.15, 0, 1.15);
  for (let i = 0; i < EWc * EHc; i++) { const L = (d[i * 4] * 0.3 + d[i * 4 + 1] * 0.59 + d[i * 4 + 2] * 0.11) / 255; const den = cl((1 - L) * 1.25 * e - 0.05); d[i * 4] = 236 - 222 * den; d[i * 4 + 1] = 234 - 188 * den; d[i * 4 + 2] = 222 - 126 * den; d[i * 4 + 3] = 255; }
  CYX.putImageData(id, 0, 0);
  P.setTransform(1, 0, 0, 1, 0, 0); P.globalAlpha = 1; P.globalCompositeOperation = 'source-over'; P.drawImage(cyanPaper, 0, 0);
  const tmp = TMPC; const tx = cx2(tmp); tx.globalCompositeOperation = 'source-over'; tx.clearRect(0, 0, W, H); tx.drawImage(cy, 0, 0, W, H); tx.globalCompositeOperation = 'destination-in'; tx.drawImage(coat, 0, 0);
  P.globalCompositeOperation = 'multiply'; P.drawImage(tmp, 0, 0); P.globalAlpha = 0.3; P.drawImage(cyanPaper, 0, 0); P.globalAlpha = 1; P.globalCompositeOperation = 'source-over'; }
const TMPC = mk(W, H);
// ---- fresco: lime plaster, faded earth palette, cracks spread on the beats
const FG = [[0, [52, 40, 34]], [0.35, [126, 70, 52]], [0.6, [176, 150, 104]], [0.8, [148, 160, 132]], [1, [232, 222, 198]]];
function fGrad(L) { for (let i = 1; i < FG.length; i++) if (L <= FG[i][0]) { const u = (L - FG[i - 1][0]) / (FG[i][0] - FG[i - 1][0]); return FG[i - 1][1].map((v, k) => v + (FG[i][1][k] - v) * u); } return FG[FG.length - 1][1]; }
const CRACKS = (() => { SEED = 4242; const out = []; const walk = (x, y, a, len, gen, t0) => { const pts = [[x, y]]; for (let s = 0; s < len; s += 9) { a += (R() - 0.5) * 0.7; x += Math.cos(a) * 9; y += Math.sin(a) * 9; pts.push([x, y]); if (gen < 3 && R() < 0.07) walk(x, y, a + (R() < 0.5 ? 1 : -1) * (0.6 + R() * 0.8), len * 0.5, gen + 1, t0 + s / len); } out.push({pts, gen, t0}); };
  for (let k = 0; k < 7; k++) walk(R() * W, R() * H, R() * 6.28, 500 + R() * 700, 0, 0); return out; })();
const fc = mk(AW, AH), FCX = cx2(fc);
function frescoFrame(img, t, t0) {
  FCX.filter = 'blur(2px)'; FCX.drawImage(img, 0, 0, AW, AH); FCX.filter = 'none'; const id = FCX.getImageData(0, 0, AW, AH), d = id.data;
  for (let i = 0; i < AW * AH; i++) { const L = (d[i * 4] * 0.3 + d[i * 4 + 1] * 0.59 + d[i * 4 + 2] * 0.11) / 255; const c = fGrad(cl(L * 1.2)); const fade = NZ[i] > 0.72 ? 0.35 : 1; d[i * 4] = c[0] + (232 - c[0]) * (1 - fade); d[i * 4 + 1] = c[1] + (222 - c[1]) * (1 - fade); d[i * 4 + 2] = c[2] + (198 - c[2]) * (1 - fade); d[i * 4 + 3] = 255; }
  FCX.putImageData(id, 0, 0);
  P.setTransform(1, 0, 0, 1, 0, 0); P.globalAlpha = 1; P.globalCompositeOperation = 'source-over'; P.drawImage(plaster, 0, 0); P.globalCompositeOperation = 'multiply'; P.drawImage(fc, 0, 0, W, H); P.globalCompositeOperation = 'source-over';
  const nb = FULL ? 6 : lastIdx(BEATS, t) - lastIdx(BEATS, t0); const grow = nb + cl((t - BEATS[lastIdx(BEATS, t)]) / 0.12) ;
  for (const c of CRACKS) { const u = cl((grow - c.t0) / 1.0); if (u <= 0) continue; const n = Math.max(2, Math.floor(c.pts.length * u)); for (const [col, lw, oy] of [['rgba(250,240,220,0.5)', 2.2 / (1 + c.gen * 0.5), 1.5], ['rgba(30,20,14,0.85)', 1.6 / (1 + c.gen * 0.5), 0]]) { P.strokeStyle = col; P.lineWidth = lw; P.beginPath(); for (let i = 0; i < n; i++) P.lineTo(c.pts[i][0], c.pts[i][1] + oy); P.stroke(); }
    if (c.gen === 0) { SEED = 99 + c.pts.length; for (let i = 0; i < n; i += 6) if (R() < 0.35) { const [x, y] = c.pts[i]; P.fillStyle = 'rgba(222,208,182,0.95)'; P.beginPath(); for (let k = 0; k < 6; k++) { const a = k / 6 * 6.28, r = 6 + R() * 16; P.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r); } P.fill(); } } } }
// ---- gold leaf mosaic over the live crowd
const GT = 22; const GORD = (() => { SEED = 515; const n = Math.ceil(W / GT) * Math.ceil(H / GT); const o = new Float32Array(n); for (let i = 0; i < n; i++) o[i] = R(); return o; })();
const gs = mk(Math.ceil(W / GT), Math.ceil(H / GT)), GSX = cx2(gs);
function goldOver(t, t0, hi, shake) {
  const gw = gs.width, gh = gs.height; GSX.drawImage(hi, 0, 0, gw, gh); const d = GSX.getImageData(0, 0, gw, gh).data;
  const nb = FULL ? 9 : lastIdx(BEATS, t) - lastIdx(BEATS, t0); const cov = cl(0.12 + nb * 0.2 + cl((t - BEATS[lastIdx(BEATS, t)]) / 0.1) * 0.05, 0, 0.82); const bp = pulse(t, BEATS, 7);
  for (let j = 0; j < gh; j++) for (let i = 0; i < gw; i++) { const k = j * gw + i; const L = (d[k * 4] * 0.3 + d[k * 4 + 1] * 0.59 + d[k * 4 + 2] * 0.11) / 255; const o = GORD[k]; const thr = L > 0.55 ? cov * 1.3 : cov * 0.8; if (o > thr) continue;
    const x = i * GT, y = j * GT; const sh = rnd(k * 3.1 + Math.floor(t * 8) * 0.37);
    if (L > 0.42) { const v = 0.75 + 0.35 * sh + 0.4 * bp * (o < 0.2 ? 1 : 0); out.fillStyle = `rgb(${Math.min(255, 212 * v) | 0},${Math.min(255, 168 * v) | 0},${Math.min(255, 72 * v) | 0})`; }
    else if (L > 0.22) out.fillStyle = `rgb(${120 + 40 * sh | 0},${48 + 20 * sh | 0},${30})`; else out.fillStyle = `rgb(${18 + 14 * sh | 0},${16 + 10 * sh | 0},${14})`;
    if (shake) { const dt = t - shake - o * 0.25; if (dt > 0) { if (dt > 1.2) continue; const vx = (rnd(k * 1.7) - 0.5) * 300, vy = -150 - rnd(k * 2.3) * 250; out.save(); out.translate(x + GT / 2 + vx * dt, y + GT / 2 + vy * dt + 1800 * dt * dt); out.rotate(dt * (rnd(k) - 0.5) * 20); out.scale(Math.cos(dt * 9 * (0.5 + rnd(k * 5))), 1); out.fillRect(-GT / 2 + 1, -GT / 2 + 1, GT - 2, GT - 2); out.restore(); continue; } }
    out.fillRect(x + 1, y + 1, GT - 2, GT - 2); out.fillStyle = 'rgba(255,240,200,0.25)'; out.fillRect(x + 1, y + 1, GT - 2, 2); }
}
let FULL = false, ACID = false;
let lastPaint = null;
function step(t) {
  const sh = shotAt(t); const med = sh[3]; const clip = FR[sh[1]]; const tq = sh[4].dark ? Math.max(sh[0], BEATS[lastIdx(BEATS, t)]) : t; const fi = fiOf(clip.length, tq - sh[0] + sh[2]); // dark oil: paint holds one footage frame per beat (stop-motion)
  SEED = (Math.floor(t * FPS) * 7919) % 2147483646 + 1;
  const cut = sh !== lastShot; lastShot = sh;
  if (med === 'raw') return;
  if (med === 'wood') { if (sh[4].peel && t >= sh[4].peel[0]) return; woodFrame(clip[fi], t); return; }
  FULL = !!sh[4].climax; ACID = !!sh[4].acid;
  if (med === 'water') { waterFrame(clip[fi], t, sh[0]); lastPaint = med; return; }
  if (med === 'cyan') { cyanFrame(FRH[sh[1]][fiOf(FRH[sh[1]].length, t - sh[0] + sh[2])], t, sh[0]); lastPaint = med; return; }
  if (med === 'fresco') { if (sh[4].fall && t >= sh[4].fall) return; frescoFrame(clip[fi], t, sh[0]); lastPaint = med; return; }
  if (med === 'gold') return;
  if (med === 'etch') { etchFrame(FRH[sh[1]][fiOf(FRH[sh[1]].length, t - sh[0] + sh[2])], t, sh[0]); lastPaint = med; return; }
  const red = RED.includes(sh[0]); const und = sh[4].under;
  PAL = !!sh[4].pal; PALS = PALSET[sh[4].pk || CLIPPAL[sh[1]] || 'nocturne']; REDP = sh[4].red ? 0.06 * pulse(t, BEATS, 7) : 0;
  if (cut) { QUEUE = []; if (med === 'ink' && lastPaint === 'ink') ground('ink', 0.22); else ground(und ? 'under' : sh[4].dark ? 'dark' : med); lastPaint = med; }
  analyse(clip[fi], med, red); DARKEN = med === 'etch' || med === 'water'; errorMap();
  const bp = pulse(t, BEATS, 9), bs = bass(t); const cb = cut && !und;
  const curB = lastIdx(BEATS, t); const onB = !cut && curB !== LBI; LBI = curB;
  if (med === 'ink') { if (cut) paint(sh[4].roll ? 1100 : 700, 34, 7, 0.04, 'ink'); else { ground('ink', onB ? 0.8 : 0.95); paint(onB ? (sh[4].roll ? 500 : 380) : 45, onB ? 30 : 14, 6, 0.04, 'ink'); } }
  else if (med === 'oil' && sh[4].dark) { // coarse -> medium -> fine, one tier per beat, fine hand keeps working between beats
    const bi = lastIdx(BEATS, t) - lastIdx(BEATS, sh[0]); const tier = sh[4].tiers[cl(bi, 0, sh[4].tiers.length - 1)]; const TW = [[52, 26], [32, 14], [22, 8]][tier]; const TC = [1100, 1500, 1700][tier];
    const hit = onB || bp > 0.75 ? 1 : 0; paint(Math.round((cut ? 1400 : 0) + TC * 0.55 * hit), TW[0] + 10 * bs, TW[1], 0.02, 'oil');
    paint(Math.round(70 + 90 * bs + (tier === 2 ? 120 : 0)), tier === 0 ? 16 : 11, 4, 0.03, 'oil'); }
  else if (med === 'charcoal') { const bi = curB - lastIdx(BEATS, sh[0]); const fine = bi >= 2;
    if (cut) paint(520, 26, 8, 0.06, 'charcoal'); else if (onB) { ground('charcoal', 0.82); paint(fine ? 380 : 460, fine ? 14 : 24, fine ? 4 : 7, 0.06, 'charcoal'); } else { ground('charcoal', 0.95); paint(50, 12, 4, 0.06, 'charcoal'); } }
  else if (med === 'vg') { paint(Math.round((cb ? 2000 : 120) + 1100 * bp * (bp > 0.7 ? 1 : 0.15)), 20, 10, 0.03, 'vg'); }
  else if (med === 'water') { paint(Math.round((cut ? 500 : 40) + 300 * bp * (bp > 0.7 ? 1 : 0.1)), 30 + 20 * bs, 12, 0.05, 'water'); }
  else if (med === 'etch') { paint(Math.round((cut ? 900 : 160) + 500 * bp * (bp > 0.7 ? 1 : 0.2)), 16, 8, 0.04, 'etch'); }
  growStrokes();
}
const MEDN = {wood: ['WOODBLOCK', '木版'], ink: ['SUMI INK', '墨'], oil: ['IMPASTO OIL', '油彩'], charcoal: ['CHARCOAL', '木炭'], vg: ['BROKEN COLOUR', '点彩'], water: ['WATERCOLOUR', '水彩'], etch: ['ETCHING', '銅版'], cyan: ['CYANOTYPE', '青写真'], fresco: ['FRESCO', '壁画'], gold: ['GOLD LEAF', '金箔']};
function label(t, sh) { const nx = SHOT_T[lastIdx(SHOT_T, t) + 1] ?? 99; if (nx - sh[0] < 1.8) return; if (sh[3] === 'ink' || sh[3] === 'raw' || sh[4].climax || (sh[4].fall && t >= sh[4].fall)) return; const dt = t - sh[0]; const a = cl(dt / 0.25) * cl((sh[3] === 'wood' ? 4.4 : 1.6) - dt); if (a <= 0) return; const [en, jp] = MEDN[sh[3]];
  const dark = !(sh[3] === 'oil' || sh[3] === 'vg' || sh[3] === 'gold'); out.globalAlpha = a; out.fillStyle = dark ? 'rgba(20,18,16,0.85)' : 'rgba(245,238,225,0.9)';
  out.font = '22px JB'; out.textBaseline = 'alphabetic'; out.fillText(en, 72, H - 74); out.font = 'italic 34px ISI'; out.fillText('chornic — ', 72, H - 110); const wq = out.measureText('chornic — ').width; out.font = '30px SM'; out.fillText(jp, 72 + wq, H - 112); out.globalAlpha = 1; }
const KA = -15 * Math.PI / 180;
function knife(t, kt, raw) { const t0 = kt - 0.12; if (t < t0) return; const p = cl((t - t0) / 0.24); const idx = Math.round(kt * 10) % 2; const cy = idx ? H * 0.62 : H * 0.36; const bw = 230;
  const L = -300 + p * (W + 600);
  out.save(); out.translate(0, cy); out.rotate(KA * (idx ? -1 : 1)); out.beginPath(); out.rect(-300, -bw / 2, L + 300, bw); out.restore();
  out.save(); out.clip(); raw(); out.restore();
  out.save(); out.translate(0, cy); out.rotate(KA * (idx ? -1 : 1)); out.lineCap = 'round';
  for (const sgn of [-1, 1]) { out.strokeStyle = 'rgba(18,24,48,0.55)'; out.lineWidth = 10; out.beginPath(); out.moveTo(-300, sgn * (bw / 2 + 4)); out.lineTo(L, sgn * (bw / 2 + 4)); out.stroke();
    out.strokeStyle = 'rgba(250,244,228,0.8)'; out.lineWidth = 4; out.beginPath(); out.moveTo(-300, sgn * (bw / 2 - 1)); out.lineTo(L, sgn * (bw / 2 - 1)); out.stroke(); }
  if (p < 1) { out.fillStyle = 'rgba(30,40,70,0.95)'; out.beginPath(); out.ellipse(L, 0, 26, bw / 2 + 14, 0, 0, 6.283); out.fill(); }
  out.restore(); }
const SPC = mk(W, H), SPX = cx2(SPC); let spShot = null;
function splatter(t, sh) { if (sh !== spShot) { SPX.clearRect(0, 0, W, H); spShot = sh; }
  if (sh[3] === 'raw' || sh[4].roll) return;
  for (const st of SPLAT) { if (t >= st && t - st < 1 / 30 + 1e-6) { SEED = Math.round(st * 1000); const cx = W * (0.2 + R() * 0.6), cy0 = H * (0.25 + R() * 0.5); SPX.fillStyle = 'rgba(150,10,18,0.92)';
    SPX.beginPath(); for (let k = 0; k <= 18; k++) { const a = k / 18 * 6.283, r = 40 + R() * 45; SPX.lineTo(cx + Math.cos(a) * r, cy0 + Math.sin(a) * r * 0.8); } SPX.fill();
    for (let k = 0; k < 70; k++) { const a = R() * 6.283, dd = 60 + Math.pow(R(), 1.6) * 420, r = 1.5 + R() * 9 * (1 - dd / 520); SPX.beginPath(); SPX.ellipse(cx + Math.cos(a) * dd, cy0 + Math.sin(a) * dd, r * 1.8, r, a, 0, 6.283); SPX.fill(); }
    for (let k = 0; k < 6; k++) { const x = cx + (R() - 0.5) * 120; SPX.fillRect(x, cy0, 3 + R() * 5, 60 + R() * 200); } } }
  out.globalCompositeOperation = 'multiply'; out.drawImage(SPC, 0, 0); out.globalCompositeOperation = 'source-over'; }
const LASTF = mk(W, H), LFX = cx2(LASTF), PREVF = mk(W, H), PFX = cx2(PREVF), WM = mk(W, H), WMX = cx2(WM); let wShot = null, wT = -9;
function wipe(t, sh) {
  if (sh !== wShot) { const isRoll = sh[4].roll || (wShot && wShot[4].roll); if (wShot && !isRoll) { PFX.clearRect(0, 0, W, H); PFX.drawImage(LASTF, 0, 0); wT = t; } wShot = sh; }
  const dt = t - wT, D = 0.3;
  if (dt >= 0 && dt < D) { const p = Math.pow(dt / D, 0.8); WMX.globalCompositeOperation = 'source-over'; WMX.clearRect(0, 0, W, H); WMX.drawImage(PREVF, 0, 0);
    WMX.globalCompositeOperation = 'destination-out'; SEED = Math.round(wT * 100); WMX.save(); WMX.translate(W / 2, H / 2); WMX.rotate(-0.26); const L = -1300 + p * 2600;
    WMX.fillStyle = '#000'; WMX.fillRect(-1300, -800, L + 1300 - 60, 1600);
    for (let k = 0; k < 140; k++) { const y = -800 + k * 1600 / 140; const ext = 20 + R() * 140; WMX.fillRect(L - 60, y, ext, 1600 / 140 * (0.4 + R() * 0.8)); }
    WMX.restore(); out.drawImage(WM, 0, 0);
    // wet edge of the loaded brush
    out.save(); out.translate(W / 2, H / 2); out.rotate(-0.26); out.globalCompositeOperation = 'source-over'; for (let k = 0; k < 90; k++) { const y = -800 + k * 1600 / 90; out.fillStyle = `rgba(${150 + R() * 40 | 0},${12 + R() * 20 | 0},${20},${0.5 + R() * 0.4})`; out.fillRect(L - 60 + R() * 60, y, 6 + R() * 30, 1600 / 90 * 0.7); } out.restore(); }
  LFX.drawImage(out.canvas, 0, 0);
}
// ---- woodblock sheet peeled off from the bottom-right corner
function halfPlane(x, C, d, f, keepLess) { const Q = [C[0] + d[0] * f, C[1] + d[1] * f], n = [-d[1], d[0]], s = keepLess ? -1 : 1; x.beginPath(); x.moveTo(Q[0] + n[0] * 5000, Q[1] + n[1] * 5000); x.lineTo(Q[0] - n[0] * 5000, Q[1] - n[1] * 5000); x.lineTo(Q[0] - n[0] * 5000 + s * d[0] * 5000, Q[1] - n[1] * 5000 + s * d[1] * 5000); x.lineTo(Q[0] + n[0] * 5000 + s * d[0] * 5000, Q[1] + n[1] * 5000 + s * d[1] * 5000); x.closePath(); }
const PD0 = (() => { const l = Math.hypot(W, H * 0.8); return [-W / l, -H * 0.8 / l]; })();
function peel(t, [a, b], raw) { const u = cl((t - a) / (b - a)); const e = u * u * (3 - 2 * u); const f = e * 1300 + u * u * 1000; const C = [W, H], d = PD0;
  raw();
  out.save(); halfPlane(out, C, d, f, false); out.clip(); out.drawImage(WOOD, 0, 0);
  // shadow cast by the lifted flap onto the print
  const Q = [C[0] + d[0] * f, C[1] + d[1] * f]; const g = out.createLinearGradient(Q[0], Q[1], Q[0] + d[0] * (40 + f * 0.25), Q[1] + d[1] * (40 + f * 0.25)); g.addColorStop(0, 'rgba(0,0,0,0.45)'); g.addColorStop(1, 'rgba(0,0,0,0)'); out.fillStyle = g; out.fillRect(0, 0, W, H); out.restore();
  // the flap: back of the washi, reflected across the fold line
  const k = d[0] * C[0] + d[1] * C[1] + f; out.save(); out.setTransform(1 - 2 * d[0] * d[0], -2 * d[0] * d[1], -2 * d[0] * d[1], 1 - 2 * d[1] * d[1], 2 * d[0] * k, 2 * d[1] * k);
  out.beginPath(); out.rect(0, 0, W, H); out.clip(); halfPlane(out, C, d, f, true); out.clip(); out.drawImage(washiBack, 0, 0);
  const g2 = out.createLinearGradient(Q[0], Q[1], Q[0] - d[0] * 220, Q[1] - d[1] * 220); g2.addColorStop(0, 'rgba(60,50,40,0.35)'); g2.addColorStop(0.3, 'rgba(255,255,255,0.12)'); g2.addColorStop(1, 'rgba(0,0,0,0.12)'); out.fillStyle = g2; out.fillRect(-3000, -3000, 9000, 9000); out.restore(); }
const washiBack = (() => { const c = mk(W, H), x = cx2(c); x.drawImage(makePaper('#efe7d4', 0.12, 0.1, 97), 0, 0); x.globalAlpha = 0.18; x.scale(-1, 1); x.drawImage(WOOD, -W, 0); return c; })();
// ---- fresco plaster falls off in chunks
const CHUNKS = (() => { SEED = 2024; const nx = 9, ny = 6, P0 = []; for (let j = 0; j <= ny; j++) { const r = []; for (let i = 0; i <= nx; i++) r.push([i * W / nx + (i > 0 && i < nx ? (R() - 0.5) * 120 : 0), j * H / ny + (j > 0 && j < ny ? (R() - 0.5) * 100 : 0)]); P0.push(r); }
  const o = []; for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) { const pts = [P0[j][i], P0[j][i + 1], P0[j + 1][i + 1], P0[j + 1][i]]; const cx = pts.reduce((a, p) => a + p[0], 0) / 4, cy = pts.reduce((a, p) => a + p[1], 0) / 4; o.push({pts, cx, cy, del: R() * 0.22 + (1 - cy / H) * 0.08, vx: (R() - 0.5) * 260, rot: (R() - 0.5) * 3}); } return o; })();
// plaster flakes away from the cracks, a ring per beat
const MW = 320, MH = 180, MS = W / MW; const LOSS = (() => { const dist = new Float32Array(MW * MH).fill(1e9); const q = [];
  for (const c of CRACKS) for (const [x, y] of c.pts) { const i = Math.floor(cl(x / MS, 0, MW - 1)), j = Math.floor(cl(y / MS, 0, MH - 1)); const k = j * MW + i; if (dist[k] > 0) { dist[k] = 0; q.push(k); } }
  for (let h = 0; h < q.length; h++) { const k = q[h], x = k % MW, y = (k / MW) | 0; for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const nx = x + dx, ny = y + dy; if (nx < 0 || ny < 0 || nx >= MW || ny >= MH) continue; const n = ny * MW + nx; if (dist[n] > dist[k] + 1) { dist[n] = dist[k] + 1; q.push(n); } } }
  let mx = 0; for (const v of dist) mx = Math.max(mx, v); const nz = noiseCanvas(MW, MH, 40, 22, 303), nd = cx2(nz).getImageData(0, 0, MW, MH).data; const o = new Float32Array(MW * MH);
  for (let k = 0; k < o.length; k++) o[k] = Math.pow(dist[k] / mx, 0.7) * 0.75 + (nd[k * 4] / 255) * 0.3; const idx = Array.from(o.keys()).sort((a, b) => o[a] - o[b]); idx.forEach((k, r) => { o[k] = r / idx.length; }); return o; })();
const MKC = mk(MW, MH), MKX = cx2(MKC), SHC = mk(W, H), SHX = cx2(SHC); const fcol = mk(MW, MH), FCOL = cx2(fcol);
function fall(t, t0) { const i0 = lastIdx(BEATS, t0), bi = lastIdx(BEATS, t) - i0, fr = (t - BEATS[lastIdx(BEATS, t)]) / (BEATS[lastIdx(BEATS, t) + 1] - BEATS[lastIdx(BEATS, t)]);
  const step = k => k <= 0 ? 0 : k; const prog = (bi + 1) * 0.34 - 0.02; // hard step exactly on the beat, then hold // each beat bites, then holds
  const id = MKX.createImageData(MW, MH), d = id.data; for (let k = 0; k < MW * MH; k++) { d[k * 4 + 3] = LOSS[k] < prog ? 0 : 255; } MKX.putImageData(id, 0, 0);
  // plaster thickness: shadow of the remaining plaster cast into the hole
  SHX.globalCompositeOperation = 'source-over'; SHX.clearRect(0, 0, W, H); SHX.imageSmoothingEnabled = true; SHX.drawImage(MKC, 0, 0, W, H); SHX.globalCompositeOperation = 'source-in'; SHX.fillStyle = 'rgba(20,14,10,0.6)'; SHX.fillRect(0, 0, W, H);
  out.save(); out.filter = 'blur(4px)'; out.drawImage(SHC, 7, 9); out.filter = 'none'; out.restore();
  // rough lime edge
  SHX.globalCompositeOperation = 'source-over'; SHX.clearRect(0, 0, W, H); SHX.drawImage(MKC, 0, 0, W, H); SHX.globalCompositeOperation = 'source-in'; SHX.fillStyle = '#e9dcc0'; SHX.fillRect(0, 0, W, H); out.drawImage(SHC, -2, -2);
  SHX.globalCompositeOperation = 'source-over'; SHX.clearRect(0, 0, W, H); SHX.drawImage(MKC, 0, 0, W, H); SHX.globalCompositeOperation = 'source-in'; SHX.drawImage(PC, 0, 0); out.drawImage(SHC, 0, 0);
  // flakes popping off the fresh edge + lime dust
  FCOL.drawImage(PC, 0, 0, MW, MH); const cd = FCOL.getImageData(0, 0, MW, MH).data;
  for (let b = 0; b <= -1; b++) { const tb = BEATS[i0 + b]; const dt = t - tb; if (dt < 0 || dt > 0.7) continue; const pa = b * 0.34 - 0.02, pb = (b + 1) * 0.34 - 0.02; SEED = 1000 + b * 77;
    for (let n = 0; n < 2600; n++) { const k = (R() * MW * MH) | 0; const L = LOSS[k]; const r0 = R(), r1 = R(), r2 = R(), r3 = R(); if (L < pa || L >= pb || r0 > 0.2) continue; const x = (k % MW) * MS, y = ((k / MW) | 0) * MS;
      const del = (L - pa) / (pb - pa) * 0.3, u = dt - del; if (u < 0) continue; const a = cl(1 - u / 0.55); if (a <= 0) continue;
      const sz = 3 + r1 * 9; out.save(); out.translate(x + (r2 - 0.5) * 60 * u, y + 30 * u + 900 * u * u); out.rotate(u * (r3 - 0.5) * 14); out.globalAlpha = a;
      out.fillStyle = `rgb(${cd[k * 4]},${cd[k * 4 + 1]},${cd[k * 4 + 2]})`; out.beginPath(); out.moveTo(-sz, -sz * 0.6); out.lineTo(sz * 0.8, -sz * 0.9); out.lineTo(sz, sz * 0.5); out.lineTo(-sz * 0.4, sz); out.closePath(); out.fill(); out.fillStyle = 'rgba(240,230,210,0.8)'; out.fillRect(-sz, -sz * 0.6, sz * 1.6, 1.5); out.restore();
      if (r1 > 0.85) { out.globalAlpha = a * 0.18; out.fillStyle = '#efe6d2'; out.beginPath(); out.arc(x, y + 20 * u, 8 + 70 * u, 0, 6.283); out.fill(); } }
    out.globalAlpha = 1; } }
function endCard(t) { const a = cl((t - ENDC) / 0.06); out.globalAlpha = a; out.drawImage(charPaper, 0, 0); out.globalAlpha = 1;
  const i0 = lastIdx(BEATS, t); const x0 = 160, x1 = W - 160, y = 610; const n = BEATS.length;
  for (let i = 0; i < n; i++) { const x = x0 + (x1 - x0) * BEATS[i] / 73.51; const db = RM.beats[i].downbeat; const past = i <= i0; const hit = i === i0 ? pulse(t, BEATS, 9) : 0;
    out.fillStyle = i === i0 ? '#c3121c' : past ? 'rgba(24,20,18,0.9)' : 'rgba(24,20,18,0.25)'; const h = (db ? 64 : 34) + hit * 40; out.fillRect(x - (db ? 2 : 1), y - h, db ? 4 : 2, h); }
  out.fillStyle = 'rgba(24,20,18,0.9)'; out.fillRect(x0, y + 10, x1 - x0, 2); out.fillStyle = '#c3121c'; out.fillRect(x0, y + 10, (x1 - x0) * cl(t / 73.51), 2);
  out.fillStyle = '#181412'; out.textBaseline = 'alphabetic'; out.font = 'italic 120px ISI'; out.fillText('chornic', x0, 400); const w = out.measureText('chornic').width; out.font = '30px JB'; out.fillText('@chornicsucide', x0 + w + 36, 396);
  out.font = '24px JB'; out.fillStyle = 'rgba(24,20,18,0.75)'; out.fillText('RHYTHM MAPPED BY', x0, 720); out.font = 'bold 54px JB'; out.fillStyle = '#181412'; out.fillText('BeatScope', x0, 780);
  out.font = '26px JB'; out.fillStyle = '#c3121c'; out.fillText('github.com/chosuicide/beatscope', x0, 830); out.font = '22px JB'; out.fillStyle = 'rgba(24,20,18,0.6)'; out.fillText('MUSIC  Shattered Heartbeat', x1 - 420, 720); out.fillText('PAINT · CODE  chornic', x1 - 420, 756); }
const render = (tt, preview = false) => { PREVIEW = preview;
  const t = T0 + tt; const f = Math.round(tt * FPS);
  if (preview) { if (f <= lastF) { lastShot = null; QUEUE = []; } /* live preview: never replay, paint the current instant */ }
  else if (f !== lastF + 1 && f > lastF && lastF >= 0 && f - lastF <= 15 && shotAt(T0 + lastF / FPS) === shotAt(t)) { for (let k = lastF + 1; k < f; k++) step(T0 + k / FPS); }
  else if (f !== lastF + 1) { lastShot = null; QUEUE = []; const s0 = shotAt(t)[0]; const k0 = Math.max(0, Math.ceil((s0 - T0) * FPS - 1e-6)); for (let k = k0; k < f; k++) step(T0 + k / FPS); }
  step(t); lastF = f; const sh = shotAt(t);
  const bp = pulse(t, BEATS, 12); const dp = 0;
  // static close-ups: hard cut on the beat, held still until the next beat
  let z = 1, zx = 0.5, zy = 0.5; for (const [a, b, zz, x, y] of ZOOMS) if (t >= a && t < b) { z = zz; zx = x; zy = y; }
  out.setTransform(1, 0, 0, 1, 0, 0); out.globalCompositeOperation = 'source-over'; out.globalAlpha = 1; out.filter = 'none';
  const hi = FRH[sh[1]][fiOf(FRH[sh[1]].length, t - sh[0] + sh[2])];
  const raw = () => { out.filter = 'contrast(1.08) saturate(0.85)'; out.drawImage(hi, 0, 0, W, H); out.filter = 'none'; };
  out.save(); const hx = W / (2 * z), hy = H / (2 * z); out.scale(z, z); out.translate(-cl(zx * W, hx, W - hx) + hx, -cl(zy * H, hy, H - hy) + hy);
  if (sh[3] === 'raw') raw();
  else if (sh[3] === 'gold') { raw(); goldOver(t, sh[0], hi, sh[4].shake); }
  else if (sh[3] === 'wood') { if (sh[4].peel && t >= sh[4].peel[0]) peel(t, sh[4].peel, raw); else out.drawImage(WOOD, 0, 0); }
  else if (sh[3] === 'fresco' && sh[4].fall && t >= sh[4].fall) { raw(); fall(t, sh[4].fall); }
  else { if (sh[4].under) raw(); out.drawImage(PC, 0, 0);
    if (sh[4].bleed) { const u = cl((t - sh[4].bleed[0]) / (sh[4].bleed[1] - sh[4].bleed[0])); if (u > 0) { out.globalCompositeOperation = 'multiply'; out.globalAlpha = 0.9 * Math.pow(u, 0.7); raw(); out.globalAlpha = 1; out.globalCompositeOperation = 'source-over'; } } }
  out.restore();
  if (sh[3] === 'oil' && sh[4].dark) relief();
  if ((sh[3] === 'oil' || sh[3] === 'vg') && !sh[4].under) { out.globalCompositeOperation = 'soft-light'; out.globalAlpha = 0.35; out.drawImage(blotch, 0, 0); out.globalAlpha = 1; }
  const vg = out.createRadialGradient(W / 2, H / 2, 420, W / 2, H / 2, 1150); vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, `rgba(0,0,0,${sh[3] === 'oil' ? 0.5 : 0.28})`); out.globalCompositeOperation = 'source-over'; out.fillStyle = vg; out.fillRect(0, 0, W, H);
  const f2 = 0; out.globalCompositeOperation = 'overlay'; out.globalAlpha = 0.1; const ox = Math.floor(rnd(f2) * 512), oy = Math.floor(rnd(f2 + 3) * 512); for (let x = -ox; x < W; x += 512) for (let y = -oy; y < H; y += 512) out.drawImage(grain, x, y);
  out.globalCompositeOperation = 'source-over'; out.globalAlpha = 1;
  for (const tr of TRIPS) if (t >= tr[0] && t < tr[1]) { TRIP = tr; triptych(t); }
  artFx(t);
  if (SKETCH.some(([a, b]) => t >= a && t < b)) sketch(FRH[sh[1]][fiOf(FRH[sh[1]].length, Math.max(sh[0], BEATS[lastIdx(BEATS, t)]) - sh[0] + sh[2])]);
  if (REDF.some(r => t >= r && t - r < 0.17)) { RTX.drawImage(cv, 0, 0); out.filter = 'grayscale(1) contrast(1.9) brightness(1.05)'; out.drawImage(RT, 0, 0); out.filter = 'none'; out.globalCompositeOperation = 'multiply'; out.fillStyle = '#c3121c'; out.fillRect(0, 0, W, H); out.globalCompositeOperation = 'source-over'; }
  if (sh[4].flash) { const a = cl(1 - (t - sh[0]) / 0.3); if (a > 0) { out.fillStyle = `rgba(255,255,250,${a})`; out.fillRect(0, 0, W, H); } }
  // wipe(t, sh); rejected 17:23 "大刷子太土了"
  const s2 = Math.max(outCanvas.width / W, outCanvas.height / H); octx.setTransform(1, 0, 0, 1, 0, 0); octx.drawImage(cv, (outCanvas.width - W * s2) / 2, (outCanvas.height - H * s2) / 2, W * s2, H * s2);
  return true;
};
ground('oil');
render.dispose = () => {};
render.preview = t => render(t, true);
return render;
}
