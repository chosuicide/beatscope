import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const helper = new URL('../beatscope/agent_skill/reference-tools.mjs', import.meta.url).pathname.replace(/^\/(?=[A-Za-z]:)/, '');
function call(program, args, cwd) {
  return spawnSync(program, args, { cwd, encoding: 'utf8', windowsHide: true, timeout: 120_000 });
}
function digest(data) { return createHash('sha256').update(data).digest('hex'); }
function available(program) { return call(program, ['-version']).status === 0; }

function filmPlan(duration, timingHash) {
  return {
    schema: 'beatscope-film-plan-1', duration, work_interval: [0, duration], render_interval: [0, duration],
    concept: { subject: 'a held field', development: 'sustain one visual state' },
    timing_source: { path: 'timing.json', sha256: timingHash },
    sections: [{ id: 'a', interval: [0, duration], purpose: 'establish a field', continuity: 'preserve its color' }],
    shots: [{ id: 'hold', section_id: 'a', interval: [0, duration], subject: 'field', purpose: 'sustain', composition: 'full frame', material: 'procedural color', motion: 'hold', entry: { reason: 'opening', carries: 'initial field', changes: 'none' } }],
    actions: [],
  };
}
function sequenceReview(record, interval) {
  return { interval, method: 'ordered-frames', evidence_path: record.preview.path, evidence_sha256: record.preview.sha256,
    preview_sha256: record.preview.sha256, plan_sha256: record.preview.plan_sha256,
    checks: { continuity: 'matched', pacing: 'matched', motion: 'matched', timing: 'matched' }, result: 'Synthetic declaration for structural tests only.' };
}

test('dense reference inspection retains native frames and source clocks, slowdown is a separate muted proxy', async t => {
  if (!available('ffmpeg') || !available('ffprobe')) { t.skip('FFmpeg unavailable'); return; }
  const root = await mkdtemp(join(tmpdir(), 'beatscope dense reference '));
  const input = join(root, 'fast.mp4');
  // Include a one-frame red flash that an 8fps overview can miss.
  const made = call('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'color=white:s=160x90:r=60:d=1.2', '-vf', "drawbox=color=red:t=fill:enable='eq(n,17)'", '-c:v', 'libx264', '-pix_fmt', 'yuv420p', input], root);
  assert.equal(made.status, 0, made.stderr);
  const result = call('node', [helper, 'inspect', '--input', input, '--out', join(root, 'native'), '--slowdown', '4'], root);
  assert.equal(result.status, 0, result.stderr);
  const sample = JSON.parse(result.stdout).samples[0];
  assert.equal(sample.sampling, 'native');
  assert.equal(sample.frames.length, 72, 'short clip inspection must not stop at the old 40-frame cap');
  assert.equal(sample.timestamp_precision, 'source-pts');
  assert.ok(Math.abs(sample.frames[17].source_time - 17 / 60) < .000001);
  const proxy = join(root, 'native', sample.slow_preview);
  const streams = JSON.parse(call('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_type,nb_frames:format=duration', '-of', 'json', proxy], root).stdout);
  assert.equal(streams.streams.filter(s => s.codec_type === 'video')[0].nb_frames, '72');
  assert.ok(!streams.streams.some(s => s.codec_type === 'audio'));
  assert.ok(Number(streams.format.duration) > 4.6);
  const sampled = call('node', [helper, 'inspect', '--input', input, '--out', join(root, 'sampled'), '--fps', '12'], root);
  assert.equal(sampled.status, 0, sampled.stderr);
  assert.equal(JSON.parse(sampled.stdout).samples[0].sampling, 'resampled');
  const invalid = call('node', [helper, 'inspect', '--input', input, '--out', join(root, 'bad'), '--fps', '0'], root);
  assert.equal(invalid.status, 2);
});

test('production stage binds usable assets, layers, visible criteria and musical roles without requiring a render', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beatscope production '));
  const timing = JSON.stringify({duration: 2, beats: [], onsets: [{id: 9,time: .5}]});
  await writeFile(join(root,'timing.json'),timing);await writeFile(join(root,'asset.png'),'asset bytes');
  const plan = filmPlan(2,digest(timing));plan.production_required = true;
  plan.actions=[{id:'hit',shot_id:'hold',interval:[.5,.7],description:'local mask displacement',reason:'punctuate authored reveal',scope:'local',trigger:{kind:'onset',id:9,time:.5}}];
  const planText=JSON.stringify(plan);await writeFile(join(root,'plan.json'),planText);
  const record={schema:'beatscope-creative-review-2',reference_mode:'original',delivery_mode:'plan-only',user_request:{task:'Plan only; no demonstration',supplied_choices:[],authorized_assumptions:[]},inputs:[{id:'asset',path:'asset.png',sha256:digest('asset bytes'),roles:['usable_asset']}],requirements:[{id:'shape',instruction:'preserve shape',priority:'critical',success_criterion:'identifiable source outline'}],preview:{plan_path:'plan.json',plan_sha256:digest(planText)}};
  const base={schema:'beatscope-production-plan-1',film_plan_sha256:digest(planText),translations:[{id:'t',requirement_id:'shape',observation_ids:[],asset_ids:['asset'],layer_ids:['image'],operation:'move source mask',preserved:'source silhouette',departures:'none',implementation_status:'candidate',steps:[{interval:[0,1],change:'mask opens from left edge'}],checks:[{interval:[0,1],criterion:'source edge remains readable'}]}],layers:[{id:'image',shot_id:'hold',interval:[0,2],role:'primary',asset_ids:['asset'],appearance:'source silhouette',motion:'local mask opening',entry:'visible',exit:'held'}],music_uses:[{id:'m',shot_id:'hold',interval:[.5,.7],role:'local',source:'onset',layer_ids:['image'],action_ids:['hit'],effect:'small local displacement',reason:'punctuate reveal'}]};
  const save=async p=>{const raw=JSON.stringify(p);await writeFile(join(root,'production.json'),raw);record.production={path:'production.json',sha256:digest(raw)};await writeFile(join(root,'review.json'),JSON.stringify(record));};
  const check=stage=>call('node',[helper,'check','--record',join(root,'review.json'),'--stage',stage],root);
  await writeFile(join(root,'review.json'),JSON.stringify(record));assert.match(check('plan').stdout,/production binding missing/);
  await save(base);assert.equal(check('production').status,0,'no video/source renderer needed for plan-only delivery');
  assert.equal(check('preview').status,1,'planning must not imply render completion');
  const reject=async(mut,pattern)=>{const p=structuredClone(base);mut(p);await save(p);const r=check('production');assert.equal(r.status,1,r.stdout);assert.match(r.stdout,pattern);};
  await reject(p=>p.translations[0].asset_ids=['unknown'],/translation incomplete/);
  await reject(p=>p.layers[0].interval=[0,3],/layer image outside/);
  await reject(p=>p.translations[0].checks=[],/visual criteria missing/);
  await reject(p=>p.music_uses[0].action_ids=['unknown'],/music action binding invalid/);
  await reject(p=>p.music_uses[0].interval=[1,2],/music action binding invalid/);
  await reject(p=>p.translations[0].implementation_status='blocked',/translation blocked/);
  await save(base);await writeFile(join(root,'production.json'),'{}');assert.match(check('production').stdout,/production plan missing, stale/);
  record.inputs[0].roles=['reference'];await save(base);assert.equal(check('production').status,1,'reference-only input is not usable material');
});

test('reference helper decodes media, compares actual preview, and rejects stale or incomplete evidence', async (t) => {
  if (!available('ffmpeg') || !available('ffprobe')) { t.skip('FFmpeg unavailable'); return; }
  const root = await mkdtemp(join(tmpdir(), 'beatscope review 中文 '));
  const reference = join(root, 'reference with spaces.mp4');
  const preview = join(root, 'preview.mp4');
  const source = join(root, 'source.js');
  const plan = join(root, 'plan.json');
  await writeFile(source, 'export const visual = true;\n');
  const timing = JSON.stringify({ duration: 2, beats: [{ id: 1, time: 0.5 }], onsets: [{ id: 2, time: 0.75 }] });
  await writeFile(join(root, 'timing.json'), timing);
  const planText = JSON.stringify(filmPlan(2, digest(timing)));
  await writeFile(plan, planText);
  const make = (path, color) => call('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', `color=c=${color}:s=320x180:r=24:d=2`, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', path], root);
  assert.equal(make(reference, 'red').status, 0);
  assert.equal(make(preview, 'blue').status, 0);
  const inspected = call('node', [helper, 'inspect', '--input', reference, '--out', join(root, 'samples'), '--interval', '0:1'], root);
  assert.equal(inspected.status, 0, inspected.stderr);
  const inspection = JSON.parse(inspected.stdout);
  assert.equal(inspection.samples.length, 1);
  assert.ok(inspection.samples[0].frames.length > 1);
  const referenceHash = digest(await readFile(reference));
  const previewHash = digest(await readFile(preview));
  const sourceHash = digest(await readFile(source));
  const planHash = digest(await readFile(plan));
  const record = {
    schema: 'beatscope-creative-review-2', reference_mode: 'reference-led',
    inputs: [
      { id: 'ref', path: reference, sha256: referenceHash, roles: ['reference'] },
      { id: 'asset', path: preview, sha256: previewHash, roles: ['usable_asset'] },
    ],
    user_request: { task: 'Make a visual informed by the supplied reference', supplied_choices: [], authorized_assumptions: [] },
    observations: [{ id: 'o1', reference_id: 'ref', interval: [0, 1], method: 'ordered-frames', detail: 'red field remains steady', evidence_paths: ['samples/sample-1/001.jpg'] }],
    requirements: [{ id: 'r1', observation_ids: ['o1'], instruction: 'keep a steady field', priority: 'critical', success_criterion: 'no shake' }],
    feature_inventory: [
      { kind: 'persistent-anchor', status: 'observed', observation_ids: ['o1'], requirement_ids: ['r1'] },
      { kind: 'state-sequence', status: 'not_applicable', reason: 'single visual state' },
      { kind: 'within-state-evolution', status: 'not_applicable', reason: 'the field is held' },
    ],
    asset_bindings: [{ requirement_id: 'r1', asset_ids: ['asset'], code_location: 'src/visual.js' }],
    preview: { path: 'preview.mp4', sha256: previewHash, source_path: 'source.js', source_sha256: sourceHash, plan_path: 'plan.json', plan_sha256: planHash, renderer: 'ffmpeg' },
    comparisons: [{ reference_id: 'ref', reference_interval: [0, 1], preview_interval: [0, 1], path: 'comparison.mp4', preview_sha256: previewHash }],
    reviews: [],
    review: { level: 'none', user_accepted: false },
  };
  const recordPath = join(root, 'creative-review.json');
  const save = () => writeFile(recordPath, JSON.stringify(record));
  await save();
  const check = (stage) => call('node', [helper, 'check', '--record', recordPath, '--stage', stage], root);
  assert.equal(check('reference').status, 0);
  assert.equal(check('preview').status, 1);
  const comparison = call('node', [helper, 'compare', '--record', recordPath, '--out', 'comparison.mp4'], root);
  assert.equal(comparison.status, 0, comparison.stderr);
  record.comparisons[0].sha256 = digest(await readFile(join(root, 'comparison.mp4')));
  record.reviews = [{ requirement_id: 'r1', status: 'matched', result: 'Both panels remain steady', paired_evidence: 'comparison.mp4' }];
  record.sequence_reviews = [sequenceReview(record, [0, 2])];
  record.review.level = 'self';
  await save();
  const complete = JSON.parse(check('preview').stdout);
  assert.equal(complete.evidence_status, 'complete');
  assert.equal(complete.aesthetic_verdict, 'not_automatically_determined');
  record.feature_inventory.pop();
  await save();
  assert.match(check('reference').stdout, /feature inventory missing or duplicated: within-state-evolution/);
  assert.equal(check('reference').status, 1, 'an omitted feature category cannot silently pass');
  record.feature_inventory.push({ kind: 'within-state-evolution', status: 'not_applicable', reason: 'the field is held' });
  await save();
  await writeFile(plan, '{"motion":"changed"}\n');
  assert.equal(check('preview').status, 1, 'changed plan must invalidate review');
  assert.equal(call('node', [helper, 'compare', '--record', recordPath, '--out', 'comparison-2.mp4'], root).status, 2, 'changed plan must block new comparison');
  await writeFile(plan, planText);
  await writeFile(source, 'export const visual = false;\n');
  assert.equal(check('preview').status, 1, 'changed source must invalidate review');
  await writeFile(source, 'export const visual = true;\n');
  record.reviews[0].status = 'mismatch';
  await save();
  assert.equal(check('preview').status, 1, 'critical mismatch must block completion');
  record.reviews[0].status = 'matched';
  record.comparisons[0].path = '../outside.mp4';
  await save();
  assert.equal(check('preview').status, 1, 'generated evidence cannot escape review root');
  record.comparisons[0].path = 'comparison.mp4';
  record.preview.sha256 = 'stale';
  await save();
  assert.equal(check('preview').status, 1);
});

test('film sequence gate accepts holds and motivated montage, rejects broken plans and unreviewed sequences', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beatscope sequence '));
  const timing = JSON.stringify({ duration: 10, beats: [{ id: 1, time: 3 }], onsets: [{ id: 7, time: 3.25 }] });
  await writeFile(join(root, 'timing.json'), timing);
  await writeFile(join(root, 'source.js'), '/* test source */');
  // This test validates records, not media decoding or visual fidelity.
  await writeFile(join(root, 'preview.mp4'), 'test media bytes');
  let plan = filmPlan(10, digest(timing));
  plan.work_interval = [2, 8]; plan.render_interval = [2, 4];
  plan.sections[0].interval = [2, 8]; plan.shots[0].interval = [2, 4];
  const record = { schema: 'beatscope-creative-review-2', reference_mode: 'original',
    user_request: { task: 'Hold one field', supplied_choices: [], authorized_assumptions: [] }, inputs: [],
    requirements: [{ id: 'hold', instruction: 'sustain a field', priority: 'critical', success_criterion: 'no cuts' }],
    asset_bindings: [{ requirement_id: 'hold', asset_ids: [], generated_material: 'procedural color', code_location: 'source.js' }],
    preview: { path: 'preview.mp4', sha256: digest('test media bytes'), source_path: 'source.js', source_sha256: digest('/* test source */'), plan_path: 'plan.json', renderer: 'synthetic' },
    reviews: [{ requirement_id: 'hold', status: 'matched', paired_evidence: 'preview.mp4', result: 'Synthetic test declaration' }],
    review: { level: 'self', user_accepted: false },
  };
  const save = async (refresh = true) => {
    const text = JSON.stringify(plan); await writeFile(join(root, 'plan.json'), text);
    record.preview.plan_sha256 = digest(text);
    if (refresh) record.sequence_reviews = [sequenceReview(record, plan.render_interval)];
    await writeFile(join(root, 'review.json'), JSON.stringify(record));
  };
  const check = stage => call('node', [helper, 'check', '--record', join(root, 'review.json'), '--stage', stage], root);
  await save();
  assert.equal(check('plan').status, 0);
  assert.equal(check('preview').status, 0, 'original work needs no fake reference; nonzero excerpt uses song time');
  const valid = structuredClone(plan);
  const rejects = async (mutate, pattern) => {
    plan = structuredClone(valid); mutate(plan); await save(); const result = check('plan');
    assert.equal(result.status, 1, result.stdout); assert.match(result.stdout, pattern);
  };
  await rejects(p => { delete p.shots[0].entry.reason; }, /transition rationale/);
  await rejects(p => { p.shots[0].interval[0] = 2.5; }, /coverage gap/);
  await rejects(p => { p.shots[0].section_id = 'missing'; }, /outside its section/);
  await rejects(p => { p.shots[0].entry.trigger = { kind: 'onset', id: 7, time: 2 }; }, /measured trigger invalid/);
  await rejects(p => { p.actions = [{ id: 'x', shot_id: 'hold', interval: [3.25, 3.5], scope: 'transition', reason: 'cut', description: 'another subject' }]; }, /transition outside shot entrance/);
  await rejects(p => { p.actions = [{ id: 'x', shot_id: 'hold', interval: [3.25, 4.5], scope: 'local', reason: 'reveal', description: 'highlight' }]; }, /action outside its shot/);
  await rejects(p => { p.shots = [null]; }, /shot direction/);
  plan = structuredClone(valid);
  plan.actions = [{ id: 'reveal', shot_id: 'hold', interval: [3.25, 3.5], scope: 'local', reason: 'reveal texture detail', description: 'local exposure change', trigger: { kind: 'onset', id: 7, time: 3.25 } }];
  await save(); assert.equal(check('plan').status, 0, 'a measured cue can drive an authored local action');
  plan.action_intent_required = true;
  await save(); assert.equal(check('plan').status, 1, 'new jobs need visible action logic rather than just a timed parameter change');
  plan.actions[0].visual_logic = { before: 'readable source field', preparation: 'intentional immediate reveal; no anticipation needed', change: 'one material edge opens', consequence: 'new detail remains visible', next_use: 'hold the revealed detail for recognition' };
  await save(); assert.equal(check('plan').status, 0);
  assert.equal(check('preview').status, 1, 'a valid action plan is not a readability review');
  record.sequence_reviews[0].perceptual = { action_readability: { status: 'matched', reason: 'Synthetic declaration: opening is visible, then the detail is held.' } };
  await save(false); assert.equal(check('preview').status, 0);
  record.sequence_reviews[0].perceptual.action_readability.status = 'mismatch';
  await save(false); assert.equal(check('preview').status, 1, 'unreadable action must block completion even when its cue is valid');
  delete plan.action_intent_required;
  const held = structuredClone(plan.shots[0]);
  plan.shots = [0, 1, 2, 3].map(i => ({ ...held, id: `montage-${i}`, interval: [2 + i * 0.5, 2.5 + i * 0.5], entry: { reason: 'compare successive details', carries: 'same material', changes: 'crop detail' } }));
  plan.actions = []; await save(); assert.equal(check('preview').status, 0, 'intentional rapid montage has no arbitrary minimum shot duration');
  record.sequence_reviews[0].checks.continuity = 'mismatch'; await save(false);
  assert.equal(check('preview').status, 1);
  await save(); record.sequence_reviews[0].interval = [0, 2]; await save(false);
  assert.equal(check('preview').status, 1, 'local MP4 time cannot masquerade as song-time review coverage');
  await save(); record.sequence_reviews[0].plan_sha256 = 'old'; await save(false);
  assert.equal(check('preview').status, 1, 'a review from an earlier plan cannot pass');
  await save(); record.sequence_reviews[0].evidence_sha256 = 'old'; await save(false);
  assert.equal(check('preview').status, 1);
  await save(); record.final = { path: 'preview.mp4', sha256: record.preview.sha256, source: 'source.js', rerender_command: 'synthetic', reviewed_intervals: [[2, 4]] };
  await save(false); assert.equal(check('final').status, 1, 'a short preview is not a complete requested film');
  plan.render_interval = [2, 8]; plan.shots = [{ ...held, interval: [2, 8] }];
  await save(); assert.equal(check('final').status, 0);
  plan.perceptual_review_required = true;
  await save(); assert.equal(check('final').status, 1, 'new plans must declare perceptual evidence, even when cue checks pass');
  const perceptual = Object.fromEntries(['development', 'musical_effect', 'material_fidelity'].map(key => [key, { status: 'matched', reason: 'Synthetic declaration: an intentional hold keeps the material readable; musical changes are intentionally omitted.' }]));
  record.sequence_reviews[0].perceptual = structuredClone(perceptual);
  await save(false); assert.equal(check('final').status, 0, 'intentional stillness can pass a declared perceptual review');
  record.sequence_reviews[0].perceptual.musical_effect.status = 'unverified';
  await save(false); assert.equal(check('final').status, 1, 'unverified musical influence cannot pass a marked review');
  record.sequence_reviews[0].perceptual = structuredClone(perceptual);
  delete record.sequence_reviews[0].perceptual.material_fidelity.reason;
  await save(false); assert.equal(check('final').status, 1, 'status labels without visible findings are insufficient');
  record.schema = 'beatscope-creative-review-1'; await save();
  assert.equal(check('preview').status, 1, 'legacy feature records must not silently become continuity evidence');
});
