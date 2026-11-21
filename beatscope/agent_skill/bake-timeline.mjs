#!/usr/bin/env node
// Bake authoritative BeatScope timing (and optional edit score) per frame for
// non-JS/offline renderers (Python, Blender, OpenCV, etc.). Measured facts only.
import { mkdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { options, number, jsonFile, saveJson, hashFile } from './tool-utils.mjs';
import * as timing from './visual-state.js';
import plan from './edit-plan.json' with { type: 'json' };
import { resolveEditPlan } from './edit-plan.js';
import { createChoreography } from './choreography.js';
import { createEditScore } from './edit-score.js';

const round6 = (n) => (typeof n === 'number' && Number.isFinite(n) ? Math.round(n * 1e6) / 1e6 + 0 : null);

function pickProbeFrames(frames, cues, stages, start, duration, count) {
  if (!frames.length) return [];
  const lastIdx = frames.length - 1;
  const clamp = (i) => Math.max(0, Math.min(lastIdx, Math.round(i)));
  const used = new Set();
  const result = [];
  const take = (idx, role, reason) => {
    let candidate = clamp(idx);
    if (used.has(candidate)) {
      for (let delta = 1; delta <= lastIdx; delta++) {
        if (candidate + delta <= lastIdx && !used.has(candidate + delta)) { candidate += delta; break; }
        if (candidate - delta >= 0 && !used.has(candidate - delta)) { candidate -= delta; break; }
      }
    }
    if (used.has(candidate)) return;
    used.add(candidate);
    const f = frames[candidate];
    result.push({ frame: f.frame, time: f.time, role, reason, stageId: f.stageId });
  };

  if (count === 4 && frames.length >= 4) {
    // 1. Steady opening landmark (~10% into window)
    take(Math.floor(lastIdx * 0.1), 'opening_steady', 'Early steady frame (~10% of window)');

    // 2. Prominent resolved cue in the first ~60% of the window
    const midCues = cues.filter((c) => c.frameIndex >= Math.floor(lastIdx * 0.15) && c.frameIndex <= Math.floor(lastIdx * 0.65));
    const chosenCue = (midCues.length ? midCues : cues)
      .slice()
      .sort((a, b) => (Number(b.manual) - Number(a.manual)) || (b.strength - a.strength) || (a.time - b.time))[0];
    if (chosenCue) {
      take(chosenCue.frameIndex, 'cue_impact', `Resolved cue ${chosenCue.id} (strength ${chosenCue.strength})`);
    } else {
      take(Math.floor(lastIdx * 0.35), 'cue_impact', 'Mid-early landmark (~35% of window; no cues in span)');
    }

    // 3. Peak spectral novelty activity frame (preferring 40%..85% of window)
    const peakLo = Math.floor(lastIdx * 0.4);
    const peakHi = Math.max(peakLo, Math.floor(lastIdx * 0.85));
    let bestIdx = Math.floor(lastIdx * 0.65);
    let bestAll = -1;
    for (let i = peakLo; i <= peakHi; i++) {
      const val = frames[i].bands.all ?? 0;
      if (val > bestAll && !used.has(i)) { bestAll = val; bestIdx = i; }
    }
    take(bestIdx, 'peak_activity', `Peak bands.all novelty (${round6(bestAll)}) in middle-late span`);

    // 4. Internal stage boundary near the late span, or closing frame (~90%)
    const boundaryStage = stages.find((s) => s.start > start + duration * 0.55 && s.start < start + duration * 0.96);
    if (boundaryStage) {
      take(boundaryStage.startFrame, 'stage_boundary', `Resolved stage boundary ${boundaryStage.id}`);
    } else {
      take(Math.floor(lastIdx * 0.9), 'closing_frame', 'Late/closing landmark (~90% of window)');
    }
    return result.sort((a, b) => a.frame - b.frame);
  }

  for (let k = 0; k < Math.min(count, frames.length); k++) {
    const pos = count === 1 ? 0 : Math.round((k * lastIdx) / (count - 1));
    take(pos, `landmark_${k + 1}`, `Evenly distributed landmark ${k + 1}/${count}`);
  }
  return result.sort((a, b) => a.frame - b.frame);
}

export async function bakeMain(argv) {
  const opts = options(
    argv,
    ['help'],
    ['out', 'score', 'start', 'seconds', 'fps', 'probe-count'],
  );
  if (opts.help) {
    console.log(
      'Usage: node bake-timeline.mjs --out ../frame-timeline.json [--score ../score.json] [--start 0] [--seconds 8] [--fps 24] [--probe-count 4]',
    );
    return;
  }
  if (!opts.out) throw Error('Provide --out PATH for frame-timeline.json');

  const root = dirname(fileURLToPath(import.meta.url));
  const map = timing.RHYTHM_MAP;
  const resolved = resolveEditPlan(map, plan);
  const start = number(opts.start, 0, 0, map.duration, 'start');
  const maxSeconds = Math.max(1 / 120, map.duration - start);
  const seconds = number(opts.seconds, maxSeconds, 1 / 120, maxSeconds + 1e-6, 'seconds');
  const fps = number(opts.fps, 24, 1, 120, 'fps');
  const probeCount = number(opts['probe-count'], 4, 1, 16, 'probe-count');
  if (!Number.isInteger(probeCount)) throw Error('probe-count must be an integer');

  const frameCount = Math.max(1, Math.ceil(seconds * fps));
  const duration = frameCount / fps;
  const end = Math.min(map.duration, start + duration);
  if (start + (frameCount - 1) / fps > map.duration + 1e-6) {
    throw Error('Requested interval exceeds timing package duration');
  }

  let compiled = null;
  let isEditScore = false;
  let scoreHash = null;
  if (opts.score) {
    const scorePath = resolve(opts.score);
    const score = await jsonFile(scorePath);
    scoreHash = await hashFile(scorePath);
    if (score.source?.sha256 && map.source?.sha256 && score.source.sha256 !== map.source.sha256) {
      throw Error('Score source does not match timing source');
    }
    if (Array.isArray(score.shots)) {
      compiled = createEditScore(score, timing);
      isEditScore = true;
    } else {
      compiled = createChoreography(score, timing);
    }
  }

  const accentIds = new Set((map.cues?.accent || []).map((c) => c.onset_id ?? c.onset ?? c.id));
  const stages = resolved.stages
    .filter((s) => s.end > start && s.start < end)
    .map((s) => {
      const clippedStart = Math.max(start, s.start);
      const clippedEnd = Math.min(end, s.end);
      return {
        id: s.id,
        index: s.index,
        start: round6(s.start),
        end: round6(s.end),
        clippedStart: round6(clippedStart),
        clippedEnd: round6(clippedEnd),
        startFrame: Math.max(0, Math.min(frameCount - 1, Math.floor((clippedStart - start) * fps + 1e-9))),
        endFrame: Math.max(0, Math.min(frameCount - 1, Math.ceil((clippedEnd - start) * fps - 1e-9))),
      };
    });

  const cues = resolved.cues
    .filter((c) => c.time >= start - 1e-9 && c.time <= end + 1e-9)
    .map((c) => {
      const frameIndex = Math.max(0, Math.min(frameCount - 1, Math.floor((c.time - start) * fps + 1e-9)));
      const frameTime = start + frameIndex / fps;
      return {
        id: c.id,
        time: round6(c.time),
        frameIndex,
        frameOffsetMs: round6((frameTime - c.time) * 1000),
        strength: round6(c.strength),
        manual: Boolean(c.manual),
        sourceTime: round6(c.sourceTime),
        sourceId: c.sourceId ?? null,
        isAccent: Boolean(c.manual || accentIds.has(c.sourceId)),
      };
    });

  const cuesByFrame = new Map();
  for (const cue of cues) {
    if (!cuesByFrame.has(cue.frameIndex)) cuesByFrame.set(cue.frameIndex, []);
    cuesByFrame.get(cue.frameIndex).push({
      id: cue.id,
      time: cue.time,
      strength: cue.strength,
      manual: cue.manual,
      isAccent: cue.isAccent,
      frameOffsetMs: cue.frameOffsetMs,
    });
  }

  const frames = new Array(frameCount);
  for (let i = 0; i < frameCount; i++) {
    const t = Math.min(map.duration, start + i / fps);
    const state = timing.getVisualState(t);
    const stage = resolved.stages.find((s) => t >= s.start && (t < s.end || (t === map.duration && s.end === map.duration)))
      ?? resolved.stages[resolved.stages.length - 1];
    const stageSpan = Math.max(1e-9, stage.end - stage.start);
    const stagePhase = Math.max(0, Math.min(1, (t - stage.start) / stageSpan));

    let scoreState = null;
    if (compiled) {
      const evaluated = compiled.at(t);
      scoreState = isEditScore
        ? {
            viewId: evaluated.view.id,
            setup: evaluated.view.setup,
            visit: evaluated.view.visit,
            cutIndex: evaluated.view.cutIndex,
            sinceCut: round6(evaluated.view.sinceCut),
            localTime: round6(evaluated.view.localTime),
            sampleTime: round6(evaluated.view.sampleTime),
            clockMode: evaluated.view.clockMode,
            rhythmMode: evaluated.rhythm?.mode ?? null,
            values: evaluated.values,
          }
        : { values: evaluated.values };
    }

    frames[i] = {
      frame: i,
      time: round6(t),
      stageId: stage.id,
      stageIndex: stage.index,
      stagePhase: round6(stagePhase),
      beat: state.beat ?? null,
      bar: state.bar ?? null,
      beatIndex: state.beatIndex ?? null,
      beatPhase: round6(state.beatPhase),
      barPhase: round6(state.barPhase),
      bands: {
        low: round6(state.low ?? 0),
        mid: round6(state.mid ?? 0),
        high: round6(state.high ?? 0),
        all: round6(state.all ?? 0),
      },
      onset: state.onset
        ? { value: round6(state.onset.value ?? 0), age: round6(state.onset.age) }
        : { value: 0, age: null },
      accent: state.accent
        ? { value: round6(state.accent.value ?? 0), age: round6(state.accent.age) }
        : null,
      structure: state.structure
        ? {
            id: state.structure.id ?? null,
            family: state.structure.family ?? null,
            label: state.structure.label ?? null,
            index: state.structure.index ?? null,
            phase: round6(state.structure.phase),
            nextBoundaryTime: round6(state.structure.nextBoundaryTime),
            secondsToBoundary: round6(state.structure.secondsToBoundary),
            ...(state.structure.meanRms !== undefined ? { meanRms: round6(state.structure.meanRms) } : {}),
          }
        : null,
      cueHits: cuesByFrame.get(i) ?? [],
      ...(scoreState ? { score: scoreState } : {}),
    };
  }

  const probeFrames = pickProbeFrames(frames, cues, stages, start, duration, probeCount);

  // Seek-determinism sanity check on landmark frames (reverse order).
  for (const landmark of probeFrames.slice().reverse()) {
    const exactT = Math.min(map.duration, start + landmark.frame / fps);
    const checkState = timing.getVisualState(exactT);
    if (round6(checkState.beatPhase) !== frames[landmark.frame].beatPhase) {
      throw Error(`Non-deterministic seek at frame ${landmark.frame}`);
    }
  }

  const outPath = resolve(opts.out);
  await mkdir(dirname(outPath), { recursive: true });
  const document = {
    schema: 'beatscope-frame-timeline-1',
    scope: 'Authoritative BeatScope timing baked per frame for external/offline renderers. Measured facts only; no visual style.',
    source: {
      display_name: map.source?.display_name ?? 'audio',
      duration: round6(map.duration),
      sha256: map.source?.sha256 ?? '',
      bpm: round6(map.bpm),
      time_signature: map.time_signature ?? [4, 4],
      rhythm_sha256: await hashFile(join(root, 'rhythm-map.json')),
      edit_plan_sha256: await hashFile(join(root, 'edit-plan.json')),
      score_sha256: scoreHash,
    },
    window: {
      start: round6(start),
      seconds: round6(seconds),
      duration: round6(duration),
      fps: round6(fps),
      frameCount,
    },
    stages,
    cues,
    probeFrames,
    frames,
  };
  await saveJson(outPath, document);
  console.log(
    JSON.stringify(
      {
        schema: document.schema,
        out: outPath,
        sha256: await hashFile(outPath),
        window: document.window,
        stageCount: stages.length,
        cueCount: cues.length,
        probeFrames,
      },
      null,
      2,
    ),
  );
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  bakeMain(process.argv.slice(2)).catch((error) => {
    console.error(error.message);
    process.exitCode = 2;
  });
}
