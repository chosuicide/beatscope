#!/usr/bin/env node
// Portable, structural reference-review aids. These commands do not judge taste.
import { createHash } from 'node:crypto';
import { createReadStream, existsSync } from 'node:fs';
import { mkdir, readFile, readdir, realpath, stat } from 'node:fs/promises';
import { dirname, extname, isAbsolute, join, relative, resolve } from 'node:path';
import { spawn } from 'node:child_process';

const schema = 'beatscope-creative-review-2';
const checkSchema = 'beatscope-reference-evidence-check-1';
const maxRuntime = 120_000;
const ffmpeg = process.env.BEATSCOPE_FFMPEG || 'ffmpeg';
const ffprobe = process.env.BEATSCOPE_FFPROBE || 'ffprobe';

function usage() {
  process.stderr.write('Usage: node reference-tools.mjs inspect --input MEDIA --out NEW_DIR [--interval START:END] (repeat up to 4) [--fps native|1..120] [--slowdown 2..8]\n');
  process.stderr.write('       node reference-tools.mjs compare --record creative-review.json --out comparison.mp4\n');
  process.stderr.write('       node reference-tools.mjs check --record creative-review.json --stage reference|production|plan|preview|final\n');
  process.stderr.write('check exit 0 = structural evidence present (not aesthetic approval); 1 = incomplete; 2 = invalid invocation/tool unavailable.\n');
}
function argsOf(argv) {
  const [action, ...tail] = argv;
  if (!['inspect', 'compare', 'check'].includes(action)) throw new Error('invalid action');
  const args = { action, interval: [] };
  for (let i = 0; i < tail.length; i += 2) {
    const key = tail[i];
    const val = tail[i + 1];
    if (!key?.startsWith('--') || !val || val.startsWith('--')) throw new Error(`invalid argument ${key}`);
    const name = key.slice(2);
    if (name === 'interval') args.interval.push(val);
    else if (['input', 'out', 'record', 'stage', 'fps', 'slowdown'].includes(name) && args[name] == null) args[name] = val;
    else throw new Error(`unsupported or repeated argument ${key}`);
  }
  return args;
}
function run(program, argv) {
  return new Promise((done, fail) => {
    const child = spawn(program, argv, { shell: false, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    let error = '';
    const timer = setTimeout(() => child.kill(), maxRuntime);
    child.stdout.on('data', (chunk) => { output += chunk; if (output.length > 2_000_000) child.kill(); });
    child.stderr.on('data', (chunk) => { error += chunk; if (error.length > 2_000_000) child.kill(); });
    child.on('error', (err) => { clearTimeout(timer); fail(new Error(`${program} unavailable: ${err.message}`)); });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) done(output);
      else fail(new Error(`${program} exited ${code}: ${error.slice(-1000)}`));
    });
  });
}
async function hashFile(path) {
  const digest = createHash('sha256');
  for await (const chunk of createReadStream(path)) digest.update(chunk);
  return digest.digest('hex');
}
function finiteInterval(pair, duration, label) {
  if (!Array.isArray(pair) || pair.length !== 2 || !pair.every((n) => Number.isFinite(n)) ||
      pair[0] < 0 || pair[1] <= pair[0] || pair[1] > duration + 0.001) {
    throw new Error(`invalid ${label} interval`);
  }
  return pair;
}
function within(root, locator) {
  if (typeof locator !== 'string' || !locator || isAbsolute(locator)) throw new Error('generated evidence path must be relative');
  const target = resolve(root, locator);
  const rel = relative(root, target);
  if (rel === '..' || rel.startsWith(`..\\`) || rel.startsWith('../') || isAbsolute(rel)) {
    throw new Error('generated evidence path escapes review directory');
  }
  return target;
}
async function existingEvidence(root, locator) {
  const target = await realpath(within(root, locator));
  const actualRoot = await realpath(root);
  const rel = relative(actualRoot, target);
  if (rel === '..' || rel.startsWith('..\\') || rel.startsWith('../') || isAbsolute(rel)) {
    throw new Error('evidence symlink escapes review directory');
  }
  return target;
}
async function metadata(path) {
  const raw = await run(ffprobe, ['-v', 'error', '-show_entries', 'format=duration:stream=codec_type,width,height,r_frame_rate', '-of', 'json', path]);
  const info = JSON.parse(raw);
  const duration = Number(info.format?.duration);
  const video = info.streams?.find((item) => item.codec_type === 'video');
  if (!video || !Number.isFinite(duration) || duration <= 0) throw new Error('media has no decodable video/duration');
  return { duration, width: video.width, height: video.height, frame_rate: video.r_frame_rate };
}
async function inspect(args) {
  if (!args.input || !args.out || args.interval.length > 4) throw new Error('inspect needs input/new output dir and at most four intervals');
  const input = resolve(args.input);
  const output = resolve(args.out);
  if (!(await stat(input)).isFile()) throw new Error('input is not a file');
  if (existsSync(output)) throw new Error('output directory already exists; choose a new one');
  const info = await metadata(input);
  const [numerator, denominator] = info.frame_rate.split('/').map(Number);
  const sourceFps = numerator / denominator;
  if (!Number.isFinite(sourceFps) || sourceFps <= 0) throw new Error('invalid source frame rate');
  const native = (args.fps ?? (info.duration <= 15 ? 'native' : '24')) === 'native';
  const sampleFps = native ? sourceFps : Number(args.fps ?? '24');
  if (!Number.isFinite(sampleFps) || sampleFps <= 0 || (!native && sampleFps > 120)) throw new Error('fps must be native or a number in (0, 120]');
  const slowdown = args.slowdown == null ? null : Number(args.slowdown);
  if (slowdown != null && (!Number.isFinite(slowdown) || slowdown < 2 || slowdown > 8)) throw new Error('slowdown must be in [2, 8]');
  const intervals = args.interval.length
    ? args.interval.map((raw, n) => finiteInterval(raw.split(':').map(Number), info.duration, `interval ${n + 1}`))
    : info.duration <= 15 ? Array.from({ length: Math.ceil(info.duration / 5) }, (_, i) => [i * 5, Math.min(info.duration, (i + 1) * 5)]) : [0.15, 0.48, 0.8].map((p) => {
      const start = Math.max(0, Math.min(info.duration - 0.25, info.duration * p));
      return [start, Math.min(info.duration, start + Math.min(2, info.duration))];
    });
  if (intervals.some(([a, b]) => b - a > 5)) throw new Error('inspect interval exceeds five seconds');
  if (intervals.some(([a, b]) => Math.ceil((b - a) * sampleFps) > 600)) throw new Error('sample exceeds 600 frames; shorten interval or choose lower fps');
  await mkdir(dirname(output), { recursive: true });
  await mkdir(output, { recursive: false });
  const hash = await hashFile(input);
  const overview = join(output, 'overview.jpg');
  const step = Math.max(info.duration / 12, 0.1);
  await run(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-i', input, '-vf', `fps=1/${step.toFixed(6)},scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2,tile=4x3:nb_frames=12`, '-frames:v', '1', '-an', overview]);
  const samples = [];
  for (let index = 0; index < intervals.length; index++) {
    const [start, end] = intervals[index];
    const folder = join(output, `sample-${index + 1}`);
    await mkdir(folder);
    const scale = 'scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2';
    const trim = `trim=start=${start}:end=${end}`;
    await run(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-i', input, '-vf', `${trim},setpts=PTS-STARTPTS,${native ? '' : `fps=${sampleFps},`}${scale}`, '-fps_mode', 'passthrough', '-an', join(folder, '%03d.jpg')]);
    const frames = (await readdir(folder)).sort();
    if (!frames.length) throw new Error(`no frames decoded from interval ${index + 1}`);
    if (frames.length > 600) throw new Error('decoded sample exceeds 600 frames; shorten interval');
    let timestamps = [];
    if (native) {
      const probed = JSON.parse(await run(ffprobe, ['-v', 'error', '-select_streams', 'v:0', '-read_intervals', `${start}%${end}`, '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', input]));
      timestamps = (probed.frames ?? []).map(f => Number(f.best_effort_timestamp_time)).filter(t => Number.isFinite(t) && t >= start - 0.000001 && t < end - 0.000001);
    }
    const exact = native && timestamps.length === frames.length;
    let slowPreview = null;
    if (slowdown != null) {
      slowPreview = `sample-${index + 1}/slow-muted.mp4`;
      await run(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-i', input, '-vf', `${trim},setpts=${slowdown}*(PTS-STARTPTS),${scale}`, '-fps_mode', 'vfr', '-an', '-c:v', 'libx264', '-crf', '20', '-pix_fmt', 'yuv420p', join(output, slowPreview)]);
    }
    samples.push({ interval: [start, end], sampling: native ? 'native' : 'resampled', sample_fps: sampleFps, timestamp_precision: exact ? 'source-pts' : 'approximate', slow_preview: slowPreview, slowdown,
      frames: frames.map((file, n) => ({ path: `sample-${index + 1}/${file}`, ...(exact ? { source_time: timestamps[n] } : {}), approximate_time: exact ? timestamps[n] : start + n / sampleFps })) });
  }
  console.log(JSON.stringify({ schema: 'beatscope-reference-inspection-1', source: input, sha256: hash, metadata: info, overview, samples }, null, 2));
}
async function loadRecord(path) {
  const recordPath = resolve(path);
  return { value: JSON.parse(await readFile(recordPath, 'utf8')), root: dirname(recordPath) };
}
async function verifyBuildInputs(root, preview) {
  if (!preview?.renderer) throw new Error('preview renderer missing');
  for (const kind of ['source', 'plan']) {
    const path = await existingEvidence(root, preview[`${kind}_path`]);
    if (!(await stat(path)).isFile() || await hashFile(path) !== preview[`${kind}_sha256`]) {
      throw new Error(`preview ${kind} hash is stale`);
    }
  }
}
async function compare(args) {
  if (!args.record || !args.out) throw new Error('compare needs record and output');
  const { value: record, root } = await loadRecord(args.record);
  const pairs = record.comparisons;
  if (!Array.isArray(pairs) || pairs.length < 1 || pairs.length > 4) throw new Error('comparisons must contain one to four pairs');
  const preview = await existingEvidence(root, record.preview?.path);
  const output = within(root, args.out);
  if (existsSync(output)) throw new Error('comparison output already exists; use a new path');
  if (extname(output).toLowerCase() !== '.mp4') throw new Error('comparison output must be mp4');
  const previewHash = await hashFile(preview);
  if (previewHash !== record.preview?.sha256) throw new Error('preview hash is stale');
  await verifyBuildInputs(root, record.preview);
  const previewInfo = await metadata(preview);
  const inputArgs = ['-hide_banner', '-loglevel', 'error', '-i', preview];
  const filters = [];
  const outs = [];
  for (let index = 0; index < pairs.length; index++) {
    const pair = pairs[index];
    const referenceInput = record.inputs?.find((item) => item.id === pair.reference_id && item.roles?.includes('reference'));
    if (!referenceInput || typeof referenceInput.path !== 'string') throw new Error('comparison references missing input');
    const referencePath = resolve(root, referenceInput.path);
    if (await hashFile(referencePath) !== referenceInput.sha256) throw new Error('reference hash is stale');
    const referenceInfo = await metadata(referencePath);
    const [rs, re] = finiteInterval(pair.reference_interval, referenceInfo.duration, 'reference');
    const [ps, pe] = finiteInterval(pair.preview_interval, previewInfo.duration, 'preview');
    const length = Math.max(re - rs, pe - ps);
    if (length > 20) throw new Error('comparison pair exceeds twenty seconds');
    inputArgs.push('-i', referencePath);
    const r = index + 1;
    const side = (stream, start, end, title, pad, label) => {
      filters.push(`[${stream}:v]trim=start=${start}:duration=${end - start},setpts=PTS-STARTPTS,fps=24,scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,drawtext=text='${title}':x=12:y=12:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.65,tpad=stop_mode=clone:stop_duration=${pad.toFixed(3)},trim=duration=${length.toFixed(3)},setpts=PTS-STARTPTS[${label}]`);
    };
    side(r, rs, re, `REFERENCE ${rs.toFixed(2)} - ${re.toFixed(2)}`, length - (re - rs), `r${r}`);
    side(0, ps, pe, `OUTPUT ${ps.toFixed(2)} - ${pe.toFixed(2)}`, length - (pe - ps), `p${r}`);
    filters.push(`[r${r}][p${r}]hstack=inputs=2[v${r}]`);
    outs.push(`[v${r}]`);
  }
  filters.push(`${outs.join('')}concat=n=${pairs.length}:v=1:a=0[out]`);
  await mkdir(dirname(output), { recursive: true });
  const actualRoot = await realpath(root);
  const actualParent = await realpath(dirname(output));
  const parentRel = relative(actualRoot, actualParent);
  if (parentRel === '..' || parentRel.startsWith('..\\') || parentRel.startsWith('../') || isAbsolute(parentRel)) throw new Error('comparison output symlink escapes review directory');
  await run(ffmpeg, [...inputArgs, '-filter_complex', filters.join(';'), '-map', '[out]', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output]);
  const hash = await hashFile(output);
  console.log(JSON.stringify({ path: output, sha256: hash, preview_sha256: previewHash, audio: 'muted', pairs: pairs.length }, null, 2));
}
const textPresent = value => typeof value === 'string' && value.trim().length > 0;
const sameTime = (a, b) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= 0.000001;
function covers(rows, interval, label, errors, ordered = true) {
  let cursor = interval[0];
  const spans = rows.map(row => row?.interval).filter(span => {
    try { finiteInterval(span, interval[1], label); return span[0] >= interval[0]; }
    catch { return false; }
  });
  if (spans.length !== rows.length) errors.push(`${label} interval invalid or outside coverage`);
  if (!ordered) spans.sort((a, b) => a[0] - b[0]);
  for (const [start, end] of spans) {
    if (ordered ? !sameTime(start, cursor) : start > cursor + 0.000001) errors.push(`${label} coverage gap or overlap`);
    cursor = Math.max(cursor, end);
  }
  if (!rows.length || !sameTime(cursor, interval[1])) errors.push(`${label} coverage incomplete`);
}
async function checkFilmPlan(root, record, stage, errors) {
  let plan, rhythm;
  try {
    const path = await existingEvidence(root, record.preview?.plan_path);
    if (await hashFile(path) !== record.preview?.plan_sha256) throw new Error();
    plan = JSON.parse(await readFile(path, 'utf8'));
    if (plan?.schema !== 'beatscope-film-plan-1') throw new Error();
    finiteInterval(plan.work_interval, plan.duration, 'work');
    finiteInterval(plan.render_interval, plan.duration, 'render');
    if (!Number.isFinite(plan.duration) || plan.duration <= 0 || plan.render_interval[0] < plan.work_interval[0] || plan.render_interval[1] > plan.work_interval[1]) throw new Error();
  } catch { errors.push('film plan missing, stale or invalid; use beatscope-film-plan-1'); return; }
  if (!textPresent(plan.concept?.subject) || !textPresent(plan.concept?.development)) errors.push('film concept needs subject and development');
  if (plan.production_required === true && !record.production) errors.push('production binding missing for new film plan');
  try {
    const path = resolve(root, plan.timing_source.path);
    if (await hashFile(path) !== plan.timing_source.sha256) throw new Error();
    rhythm = JSON.parse(await readFile(path, 'utf8'));
    if (!sameTime(rhythm.duration, plan.duration) || !Array.isArray(rhythm.beats) || !Array.isArray(rhythm.onsets)) throw new Error();
  } catch { errors.push('film timing source missing, stale or duration differs'); }
  const sections = Array.isArray(plan.sections) ? plan.sections : [];
  const shots = Array.isArray(plan.shots) ? plan.shots : [];
  const actions = Array.isArray(plan.actions) ? plan.actions : [];
  if (!Array.isArray(plan.actions)) errors.push('film actions must be an array (empty is allowed)');
  const uniqueIds = (rows, name) => {
    const ids = new Set();
    for (const row of rows) {
      if (!textPresent(row?.id) || ids.has(row.id)) errors.push(`${name} ID missing or duplicated`);
      ids.add(row?.id);
    }
  };
  uniqueIds(sections, 'section'); uniqueIds(shots, 'shot'); uniqueIds(actions, 'action');
  covers(sections, plan.work_interval, 'sections', errors);
  covers(shots, plan.render_interval, 'shots', errors);
  const trigger = (cue, time, label) => {
    if (cue == null) return; // A designed action may intentionally have no musical trigger.
    const rows = cue.kind === 'onset' ? rhythm?.onsets : cue.kind === 'beat' ? rhythm?.beats : null;
    if (!rows || !sameTime(cue.time, time) || !rows.some(row =>
      (cue.id == null || row.id === cue.id) && sameTime(row.time ?? row.raw_time, cue.time))) errors.push(`measured trigger invalid: ${label}`);
  };
  for (const section of sections) {
    if (!textPresent(section?.purpose) || !textPresent(section?.continuity)) errors.push(`section purpose/continuity missing: ${section?.id}`);
  }
  for (const shot of shots) {
    if (!['subject', 'purpose', 'composition', 'material', 'motion'].every(key => textPresent(shot?.[key])) ||
        !['reason', 'carries', 'changes'].every(key => textPresent(shot?.entry?.[key]))) errors.push(`shot direction or transition rationale missing: ${shot?.id}`);
    const section = sections.find(item => item?.id === shot?.section_id);
    if (!section || !Array.isArray(shot?.interval) || !Array.isArray(section?.interval) || shot.interval[0] < section.interval[0] || shot.interval[1] > section.interval[1]) errors.push(`shot outside its section: ${shot?.id}`);
    trigger(shot?.entry?.trigger, shot?.interval?.[0], shot?.id);
  }
  for (const action of actions) {
    const shot = shots.find(item => item?.id === action?.shot_id);
    try {
      finiteInterval(action?.interval, plan.duration, 'action');
      if (!shot || action.interval[0] < shot.interval[0] || action.interval[1] > shot.interval[1]) throw new Error();
    } catch { errors.push(`action outside its shot: ${action?.id}`); }
    if (!['local', 'camera', 'transition'].includes(action?.scope) || !textPresent(action?.description) || !textPresent(action?.reason)) errors.push(`action intent missing: ${action?.id}`);
    if (plan.action_intent_required === true && !['before', 'preparation', 'change', 'consequence', 'next_use'].every(key => textPresent(action?.visual_logic?.[key]))) errors.push(`visible action logic missing: ${action?.id}`);
    if (action?.scope === 'transition' && !sameTime(action?.interval?.[0], shot?.interval?.[0])) errors.push(`transition outside shot entrance: ${action?.id}`);
    trigger(action?.trigger, action?.interval?.[0], action?.id);
  }
  if (stage === 'plan' || stage === 'production') return;
  const reviews = Array.isArray(record.sequence_reviews) ? record.sequence_reviews : [];
  covers(reviews, plan.render_interval, 'sequence reviews', errors, false);
  for (const review of reviews) {
    if (!['playback', 'ordered-frames'].includes(review?.method) || !textPresent(review?.result) ||
        !['continuity', 'pacing', 'motion', 'timing'].every(key => review?.checks?.[key] === 'matched')) errors.push('sequence review incomplete or unresolved');
    try {
      if (review.preview_sha256 !== record.preview?.sha256 || review.plan_sha256 !== record.preview?.plan_sha256) throw new Error();
      if (await hashFile(await existingEvidence(root, review.evidence_path)) !== review.evidence_sha256) throw new Error();
    } catch { errors.push('sequence review evidence missing or stale'); }
    if (plan.perceptual_review_required === true) {
      for (const key of ['development', 'musical_effect', 'material_fidelity']) {
        const finding = review.perceptual?.[key];
        if (!textPresent(finding?.reason) || finding?.status !== 'matched') errors.push(`perceptual review missing or unresolved: ${key}`);
      }
    }
    if (plan.action_intent_required === true) {
      const finding = review.perceptual?.action_readability;
      if (!textPresent(finding?.reason) || finding?.status !== 'matched') errors.push('perceptual review missing or unresolved: action_readability');
    }
  }
  if (stage === 'final' && !plan.work_interval.every((value, index) => sameTime(value, plan.render_interval[index]))) errors.push('final plan must cover the whole requested work');
}
async function checkProduction(root, record, errors) {
  let production, plan;
  try {
    const file = await existingEvidence(root, record.production?.path);
    if (await hashFile(file) !== record.production?.sha256) throw new Error();
    production = JSON.parse(await readFile(file, 'utf8'));
    plan = JSON.parse(await readFile(await existingEvidence(root, record.preview?.plan_path), 'utf8'));
    if (production.schema !== 'beatscope-production-plan-1' || production.film_plan_sha256 !== record.preview?.plan_sha256) throw new Error();
  } catch { errors.push('production plan missing, stale or not bound to film plan'); return; }
  const layers = Array.isArray(production.layers) ? production.layers : [];
  const translations = Array.isArray(production.translations) ? production.translations : [];
  const uses = Array.isArray(production.music_uses) ? production.music_uses : [];
  const shots = Array.isArray(plan.shots) ? plan.shots : [], assets = (record.inputs ?? []).filter(i => i.roles?.includes('usable_asset'));
  const observations = record.observations ?? [], requirements = record.requirements ?? [];
  const unique = (rows, label) => { const ids = new Set(); for (const row of rows) { if (!textPresent(row?.id) || ids.has(row.id)) errors.push(`${label} ID missing or duplicated`); ids.add(row?.id); } };
  unique(layers, 'layer'); unique(translations, 'translation'); unique(uses, 'music use');
  const interval = (row, span, label) => { try { finiteInterval(row?.interval, span[1], label); if (row.interval[0] < span[0]) throw new Error(); } catch { errors.push(`${label} outside planned interval`); } };
  const boundAssets = row => Array.isArray(row?.asset_ids) && row.asset_ids.every(id => assets.some(a => a.id === id)) && (row.asset_ids.length > 0 || textPresent(row.generated_material));
  for (const layer of layers) {
    const shot = shots.find(s => s.id === layer?.shot_id);
    if (!shot || !['primary', 'support', 'background'].includes(layer?.role) || !['appearance', 'motion', 'entry', 'exit'].every(k => textPresent(layer?.[k])) || !boundAssets(layer)) errors.push(`layer direction or usable material missing: ${layer?.id}`);
    if (shot) interval(layer, shot.interval, `layer ${layer.id}`);
  }
  for (const shot of shots) if (!layers.some(l => l.shot_id === shot.id && l.role === 'primary')) errors.push(`shot has no focal layer: ${shot.id}`);
  for (const translation of translations) {
    const requirement = requirements.find(r => r.id === translation?.requirement_id);
    const referenceLed = record.reference_mode === 'reference-led';
    if (!requirement || !Array.isArray(translation?.observation_ids) || (referenceLed && (!translation.observation_ids.length || !translation.observation_ids.some(id => requirement?.observation_ids?.includes(id)))) || translation.observation_ids.some(id => !observations.some(o => o.id === id)) || !boundAssets(translation) || !textPresent(translation?.operation) || !textPresent(translation?.preserved) || !textPresent(translation?.departures) || !['candidate', 'verified', 'blocked'].includes(translation?.implementation_status)) errors.push(`reference translation incomplete: ${translation?.id}`);
    if (translation?.implementation_status === 'blocked') errors.push(`reference translation blocked: ${translation.id}`);
    if (!Array.isArray(translation?.layer_ids) || !translation.layer_ids.length || translation.layer_ids.some(id => !layers.some(l => l.id === id))) errors.push(`translation layers missing: ${translation?.id}`);
    const steps = Array.isArray(translation?.steps) ? translation.steps : [];
    const checks = Array.isArray(translation?.checks) ? translation.checks : [];
    if (!steps.length || !checks.length) errors.push(`translation steps or visual criteria missing: ${translation?.id}`);
    for (const step of steps) { interval(step, plan.render_interval, 'translation step'); if (!textPresent(step.change)) errors.push('translation step has no visible change'); }
    for (const criterion of checks) { interval(criterion, plan.render_interval, 'visual criterion'); if (!textPresent(criterion.criterion)) errors.push('visual criterion missing'); }
  }
  for (const requirement of requirements) if (!translations.some(t => t.requirement_id === requirement.id)) errors.push(`requirement has no production translation: ${requirement.id}`);
  for (const use of uses) {
    const shot = shots.find(s => s.id === use?.shot_id);
    if (!shot || !['composition', 'local', 'sustained', 'density', 'hold'].includes(use?.role) || !['onset', 'beat', 'bands', 'phase', 'structure', 'none'].includes(use?.source) || !textPresent(use?.effect) || !textPresent(use?.reason) || !Array.isArray(use?.layer_ids) || !use.layer_ids.length || use.layer_ids.some(id => !layers.some(l => l.id === id && l.shot_id === use.shot_id))) errors.push(`music use incomplete: ${use?.id}`);
    if (shot) interval(use, shot.interval, `music use ${use.id}`);
    const actionIds = Array.isArray(use?.action_ids) ? use.action_ids : [];
    if (['onset', 'beat'].includes(use?.source) && !actionIds.length) errors.push(`discrete music use has no measured action: ${use?.id}`);
    for (const id of actionIds) { const action = (plan.actions ?? []).find(a => a.id === id); if (!action || action.shot_id !== use.shot_id || !Array.isArray(use.interval) || action.interval[0] < use.interval[0] || action.interval[1] > use.interval[1] || (['onset', 'beat'].includes(use.source) && action.trigger?.kind !== use.source)) errors.push(`music action binding invalid: ${use.id}`); }
    const allowedFields = { bands: ['low', 'mid', 'high', 'all'], phase: ['beatPhase', 'barPhase', 'beatIndex'], structure: ['structure.phase', 'structure.startTime', 'structure.endTime', 'structure.family'] };
    if (allowedFields[use?.source] && (!Array.isArray(use.fields) || !use.fields.length || use.fields.some(f => !allowedFields[use.source].includes(f)))) errors.push(`continuous music fields missing or invalid: ${use.id}`);
  }
  for (const shot of shots) if (!uses.some(u => u.shot_id === shot.id)) errors.push(`shot has no musical role or deliberate hold: ${shot.id}`);
}
async function check(args) {
  if (!args.record || !['reference', 'production', 'plan', 'preview', 'final'].includes(args.stage)) throw new Error('check needs record and reference|production|plan|preview|final stage');
  const { value: record, root } = await loadRecord(args.record);
  const errors = [];
  if (record.delivery_mode === 'plan-only' && ['preview', 'final'].includes(args.stage)) errors.push('plan-only delivery has no authorized render-stage completion');
  if (record.schema !== schema) errors.push('invalid record schema: v2 needs a film plan and sequence review; v1 is historical evidence');
  const original = record.reference_mode === 'original';
  if (!['original', 'reference-led'].includes(record.reference_mode)) errors.push('reference_mode must be original or reference-led');
  const inputs = Array.isArray(record.inputs) ? record.inputs : [];
  const ids = new Set();
  for (const input of inputs) {
    if (!input?.id || ids.has(input.id)) errors.push('input IDs must be nonempty and unique');
    ids.add(input?.id);
    if (!Array.isArray(input?.roles) || !input.roles.length) errors.push(`input roles missing: ${input?.id}`);
    try { if (await hashFile(resolve(root, input.path)) !== input.sha256) errors.push(`input hash mismatch: ${input.id}`); }
    catch { errors.push(`input missing: ${input?.id}`); }
  }
  if (!record.user_request?.task) errors.push('user_request.task missing');
  if (!Array.isArray(record.user_request?.supplied_choices) || !Array.isArray(record.user_request?.authorized_assumptions)) errors.push('user_request choices/assumptions must be explicit arrays');
  if (!original && !inputs.some((item) => item.roles?.includes('reference'))) errors.push('reference input missing');
  const observations = Array.isArray(record.observations) ? record.observations : [];
  const obsIds = new Set();
  if (!original && observations.length === 0) errors.push('reference observations missing');
  for (const obs of observations) {
    if (!obs?.id || obsIds.has(obs.id)) errors.push('observation IDs must be nonempty and unique');
    obsIds.add(obs?.id);
    if (!inputs.some((item) => item.id === obs?.reference_id && item.roles?.includes('reference'))) errors.push(`observation reference missing: ${obs?.id}`);
    try { finiteInterval(obs.interval, Number.MAX_SAFE_INTEGER, `observation ${obs.id}`); } catch (error) { errors.push(error.message); }
    if (!obs.detail || !['playback', 'ordered-frames'].includes(obs.method)) errors.push(`observation detail/method missing: ${obs?.id}`);
    const files = Array.isArray(obs.evidence_paths) ? obs.evidence_paths : [];
    if (!files.length) errors.push(`observation sample files missing: ${obs?.id}`);
    for (const file of files) { try { if (!(await stat(await existingEvidence(root, file))).isFile()) throw new Error(); } catch { errors.push(`observation file missing: ${file}`); } }
  }
  const requirements = Array.isArray(record.requirements) ? record.requirements : [];
  if (!requirements.length && !original) errors.push('requirements missing');
  const reqIds = new Set();
  for (const req of requirements) {
    if (!req?.id || reqIds.has(req.id)) errors.push('requirement IDs must be nonempty and unique');
    reqIds.add(req?.id);
    if (!req.instruction || !req.success_criterion || !['critical', 'normal'].includes(req.priority)) errors.push(`requirement incomplete: ${req?.id}`);
    if (!original && (!Array.isArray(req.observation_ids) || !req.observation_ids.length || req.observation_ids.some((id) => !obsIds.has(id)))) errors.push(`requirement observation missing: ${req?.id}`);
  }
  if (!original) {
    const inventory = Array.isArray(record.feature_inventory) ? record.feature_inventory : [];
    for (const kind of ['persistent-anchor', 'state-sequence', 'within-state-evolution']) {
      const entries = inventory.filter((item) => item?.kind === kind);
      if (entries.length !== 1) { errors.push(`feature inventory missing or duplicated: ${kind}`); continue; }
      const entry = entries[0];
      if (entry.status === 'not_applicable') {
        if (typeof entry.reason !== 'string' || !entry.reason.trim()) errors.push(`feature inventory reason missing: ${kind}`);
      } else if (entry.status === 'observed') {
        if (!Array.isArray(entry.observation_ids) || !entry.observation_ids.length || entry.observation_ids.some((id) => !obsIds.has(id)) ||
            !Array.isArray(entry.requirement_ids) || !entry.requirement_ids.length || entry.requirement_ids.some((id) => {
              const req = requirements.find((item) => item.id === id);
              return !reqIds.has(id) || !req?.observation_ids?.some((obsId) => entry.observation_ids.includes(obsId));
            })) {
          errors.push(`feature inventory evidence missing: ${kind}`);
        }
      } else errors.push(`feature inventory status invalid: ${kind}`);
    }
    if (inventory.some((item) => !['persistent-anchor', 'state-sequence', 'within-state-evolution'].includes(item?.kind))) errors.push('unknown feature inventory kind');
  }
  let mismatch = 0;
  let unverified = 0;
  if (args.stage !== 'reference') await checkFilmPlan(root, record, args.stage, errors);
  if (args.stage === 'production' || (args.stage !== 'reference' && record.production != null)) await checkProduction(root, record, errors);
  if (['preview', 'final'].includes(args.stage)) {
    const bindings = Array.isArray(record.asset_bindings) ? record.asset_bindings : [];
    for (const req of requirements) {
      if (!bindings.some((item) => item.requirement_id === req.id && item.code_location && Array.isArray(item.asset_ids) && (item.asset_ids.length || textPresent(item.generated_material)) && item.asset_ids.every((id) => ids.has(id)))) errors.push(`asset binding missing: ${req.id}`);
    }
    try {
      const path = await existingEvidence(root, record.preview?.path);
      if (await hashFile(path) !== record.preview?.sha256) throw new Error();
    } catch { errors.push('preview missing or stale'); }
    try { await verifyBuildInputs(root, record.preview); }
    catch { errors.push('preview source or plan missing or stale'); }
    const pairs = Array.isArray(record.comparisons) ? record.comparisons : [];
    if (!original && !pairs.length) errors.push('comparison missing');
    for (const pair of pairs) {
      if (!inputs.some((item) => item.id === pair.reference_id && item.roles?.includes('reference'))) errors.push('comparison reference missing');
      try {
        finiteInterval(pair.reference_interval, Number.MAX_SAFE_INTEGER, 'reference');
        finiteInterval(pair.preview_interval, Number.MAX_SAFE_INTEGER, 'preview');
        if (pair.preview_sha256 !== record.preview?.sha256 || await hashFile(await existingEvidence(root, pair.path)) !== pair.sha256) throw new Error();
      } catch { errors.push('comparison missing or stale'); }
    }
    const reviews = Array.isArray(record.reviews) ? record.reviews : [];
    for (const req of requirements) {
      const review = reviews.find((item) => item.requirement_id === req.id);
      const evidenceMatches = original ? review?.paired_evidence === record.preview?.path : pairs.some((pair) => pair.path === review?.paired_evidence);
      if (!review || !['matched', 'mismatch', 'unverified'].includes(review.status) || !review.result || !review.paired_evidence || !evidenceMatches) {
        errors.push(`feature review missing: ${req.id}`); unverified++;
      } else if (review.status === 'unverified' && req.priority === 'critical') { unverified++; errors.push(`critical feature unverified: ${req.id}`); }
      else if (review.status === 'mismatch' && req.priority === 'critical') { mismatch++; errors.push(`critical feature mismatch: ${req.id}`); }
    }
    if (!['self', 'independent', 'user'].includes(record.review?.level)) errors.push('review level missing; file existence is not visual review');
  }
  if (args.stage === 'final') {
    try {
      if (await hashFile(await existingEvidence(root, record.final?.path)) !== record.final?.sha256 || record.final.sha256 !== record.preview?.sha256 || record.final.source !== record.preview?.source_path || !record.final.rerender_command || !record.final.reviewed_intervals?.length) throw new Error();
    } catch { errors.push('final artifact, source, render instruction or review missing'); }
  }
  const renderedStage = ['preview', 'final'].includes(args.stage);
  const report = { schema: checkSchema, stage: args.stage, assessment_scope: renderedStage ? 'declared_render_evidence' : 'planning_structure', evidence_status: errors.length ? 'incomplete' : 'complete', critical_mismatches: renderedStage ? mismatch : null, unverified_requirements: renderedStage ? unverified : null, implementation_verdict: 'not_automatically_determined', aesthetic_verdict: 'not_automatically_determined', user_acceptance: record.review?.user_accepted === true ? 'declared_in_record' : 'not_recorded', errors };
  console.log(JSON.stringify(report, null, 2));
  if (errors.length) process.exitCode = 1;
}
try {
  const args = argsOf(process.argv.slice(2));
  if (args.action === 'inspect') await inspect(args);
  if (args.action === 'compare') await compare(args);
  if (args.action === 'check') await check(args);
} catch (error) {
  usage();
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 2;
}
