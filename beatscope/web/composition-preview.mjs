import { compileComposition } from './composition-runtime.mjs';
const $ = s => document.querySelector(s), audio = $('#audio');
const fetchJSON = async path => { const r = await fetch(path); if (!r.ok) throw Error('Missing ' + path); return r.json(); };
function script(path) { return new Promise((resolve, reject) => { const tag = document.createElement('script'); tag.src = path; tag.onload = resolve; tag.onerror = () => reject(Error('Missing ' + path)); document.head.append(tag); }); }
try {
  const [doc, rhythm, assets] = await Promise.all([fetchJSON('./composition.json'), fetchJSON('./timing/rhythm-map.json'), fetchJSON('./assets.json')]);
  const ranking = await fetch('./timing/response-relevance.json').then(r => r.ok ? r.json() : null);
  const runtime = compileComposition(doc, rhythm, ranking), stage = $('#stage'), holder = $('#holder');
  stage.style.width = doc.artwork.width + 'px'; stage.style.height = doc.artwork.height + 'px'; stage.style.background = doc.artwork.color;
  const resize = () => { const scale = Math.min((innerWidth - 48) / doc.artwork.width, (innerHeight - 135) / doc.artwork.height); holder.style.width = doc.artwork.width * scale + 'px'; holder.style.height = doc.artwork.height * scale + 'px'; stage.style.transform = `scale(${scale})`; }; resize(); addEventListener('resize', resize);
  let ctx, visualizer, source, lastURL;
  if (doc.background.preset_id) {
    await script('./composition-engine.js'); await script('./composition-presets.js');
    const canvas = document.createElement('canvas'); canvas.style.opacity = doc.background.opacity; stage.append(canvas); ctx = new AudioContext();
    const engine = window.butterchurn.default || window.butterchurn, pack = window.butterchurnPresets.default || window.butterchurnPresets;
    visualizer = engine.createVisualizer(ctx, canvas, { width: 1280, height: Math.round(1280 * doc.artwork.height / doc.artwork.width), pixelRatio: 1 });
    const preset = pack.getPresets()[doc.background.preset_id]; if (!preset) throw Error('Unavailable background preset');
    visualizer.loadPreset(preset, 0); source = ctx.createMediaElementSource(audio); source.connect(ctx.destination); visualizer.connectAudio(source); visualizer.render();
    audio.addEventListener('play', () => void ctx.resume());
  }
  const nodes = doc.objects.map(o => {
    const root = document.createElement('div'); root.className = 'object'; root.hidden = !o.visible;
    Object.assign(root.style, { left: o.transform.x + 'px', top: o.transform.y + 'px', width: o.transform.width + 'px', height: o.transform.height + 'px' });
    const crop = document.createElement('div'); crop.className = 'crop'; root.append(crop);
    const content = document.createElement('div'); content.className = 'content'; crop.append(content);
    Object.assign(content.style, { width: 100 / (1 - o.crop.left - o.crop.right) + '%', height: 100 / (1 - o.crop.top - o.crop.bottom) + '%', left: -100 * o.crop.left / (1 - o.crop.left - o.crop.right) + '%', top: -100 * o.crop.top / (1 - o.crop.top - o.crop.bottom) + '%' });
    const node = document.createElement(o.kind === 'text' ? 'div' : o.kind === 'image' ? 'img' : 'video'); content.append(node);
    if (o.kind === 'text') { node.className = 'text'; node.textContent = o.text; node.style.fontSize = o.font_size + 'px'; node.style.color = o.color; }
    else { if (!assets[o.asset_id]) throw Error('Missing media ' + o.asset_id); node.src = assets[o.asset_id].path; if (o.kind === 'video') { node.muted = true; node.playsInline = true; } }
    stage.append(root); return { o, root, node };
  });
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function frame() {
    const state = runtime.at(audio.currentTime, reduced.matches);
    for (const { o, root, node } of nodes) {
      root.style.transform = `rotate(${o.transform.rotation}deg) scale(${state[o.id].scale})`; root.style.opacity = state[o.id].opacity;
      if (o.kind === 'video' && Number.isFinite(node.duration)) {
        const target = o.loop ? (audio.currentTime + o.source_offset) % node.duration : Math.min(Math.max(0, node.duration - .001), audio.currentTime + o.source_offset);
        if (Math.abs(node.currentTime - target) > (audio.paused ? .001 : .12)) node.currentTime = target;
        if (audio.paused || (!o.loop && audio.currentTime + o.source_offset >= node.duration)) node.pause(); else if (node.paused) void node.play().catch(() => {});
      }
    }
    if (visualizer && !audio.paused && !document.hidden && !reduced.matches) visualizer.render();
    requestAnimationFrame(frame);
  }
  frame();
  $('#file').onchange = async e => {
    try {
      const file = e.target.files[0]; if (!file) return; audio.pause();
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())), b => b.toString(16).padStart(2, '0')).join('');
      if (digest !== doc.source_rhythm_sha256) throw Error('Wrong audio file: SHA-256 does not match this composition.');
      if (lastURL) URL.revokeObjectURL(lastURL); lastURL = URL.createObjectURL(file); audio.src = lastURL; $('#status').textContent = 'Audio verified'; $('#error').textContent = '';
    } catch (e) { $('#error').textContent = String(e); }
  };
} catch (e) { $('#error').textContent = String(e); }
