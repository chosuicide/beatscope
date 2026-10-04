---
name: beatscope-visualizer
description: Use BeatScope music facts, grouped edits and seek-safe motion for video with optional references. Read AGENT.md first; no fixed visual style.
---

# Query music and execute an edit
Read AGENT.md. Resume a matching project within scope, or create a new work.
Verify source hash, score duration and revision binding before timeline reuse;
an asset directory or ready flag is not proof of an accepted matching project.
Check supplied inputs and clearly linked workspace records only; do not search
the whole machine for assets/history or ask users to resolve internal cache versions.
When linked records disagree, do not invent accepted requirements. Recover the
matching record when possible; otherwise ask about the intended visual direction
or whether to start a new work, in ordinary language.
Extract summaries and selected fields. Never dump entire maps, caches embedding
rhythm/ranking, or recursive asset inventories into context.
Cache `node music-brief.mjs` by rhythm/edit-plan hashes; query an uncertain window with
`node music-brief.mjs 81 103`. Exact meanings: BEATSCOPE.md/references/schema.md.
Visual decisions: references/directing.md. JSON imports need Node22+ or current
Chromium over HTTP with JSON/JS MIME, no build/runtime dependencies.
The brief's `stages` are resolved editor stages; `automaticSections` and
`measuredAnchorCandidates` remain factual suggestions. `cueEdits.shown` is a
bounded inspection list, not the full cue schedule. Resolve the plan for execution.

## Facts
```js
import * as music from './visual-state.js';
import {createTrack} from './beatscope-runtime.js';
const track = createTrack(music.RHYTHM_MAP);
const candidates = (start,end,budget) => typeof music.getResponseEvents === 'function'
  ? music.getResponseEvents(start,end,budget) : track.responseBetween(start,end,budget);
function frame(frameIndex,fps,excerptStart) {
  return music.getVisualState(excerptStart+frameIndex/fps);
}
```
State includes beat/bar phase, bands, onset/accent and optional structure/meanRms.
The budget returns possible measured anchors, not musical functions or cut rules.
Use ordinary beats and continuous activity alongside accent anchors.

## Edit score: authored by Agent, executed by code
Resolve the supplied editor plan once before authoring:
```js
import plan from './edit-plan.json' with {type:'json'};
import {resolveEditPlan} from './edit-plan.js';
const {stages,cues} = resolveEditPlan(music.RHYTHM_MAP, plan);
```
These stages define contiguous passage boundaries; add focus/change/rhythm to
them in your score. Unchanged cues are measured candidates; `manual:true` cues
are added/moved response anchors. Deleted cues are omitted. Use resolved cues
for authored responses so overrides take effect. Keep `sourceTime` for citation;
do not also fire the old time of a moved/deleted cue. A cue can drive several
layers, a cut or a returning sequence. It does not specify one isolated action.

Keep one job-local score.json outside this package. Reuse it when present;
preserve accepted shots, effects, asset bindings and unrelated timing during
scoped edits. If it belongs to another song, reuse suitable visual definitions
separately and author timing against this package. Users do not fill it in.
For an MV set `intent:"music-video"`. First author the musical passages and
their visual rhythm, then shot setups/sequences, then motion inside shots.
Import `createEditScore` from edit-score.js. The score contains:
- stages: adjacent whole-song `{id,start,end,focus,change,entry}`. entry names a
  shot at that boundary; `carry:true` explicitly continues an earlier shot.
  Each MV stage has rhythm blocks covering it exactly, with
  `{start,end,mode,music,reason,anchors,action?}`. Anchors use the same time API.
  mode hold permits one shot identity and requires action describing its motion
  and destination; switch requires at least one identity change; alternate
  requires at least two. music describes the actual musical passage; reason
  connects its visual choices. anchors are increasing music cues inside it.
  These checks enforce declared edits, not taste or a universal cut frequency.
- shots: reusable `{id,relation,setup,values,tracks,clock,duration}`. setup is
  renderer configuration; values are static named properties; optional tracks
  animate those properties in LOCAL seconds. relation describes why shots belong
  together. The renderer still provides actual footage/geometry/materials.
- cuts: optional individual `{at,shot}` entries.
- groups: `{id,stage,anchors,sequence}` binds one authored combination to several
  real music events. Sequence cells name shots; null holds the current shot while
  other music-linked tracks may act. Lengths match unless `repeat:true` explicitly
  repeats the supplied combination. No built-in combination or cut frequency.
- moments and global tracks: shared music-time anchors and motion, as below.
  Global property writers cannot overlap shot-local property writers.

A shot clock uses `{mode,offset:0,rate:1}`:
continuous (MV default) advances since first visit including offscreen time;
visible (other scores' default) advances only while onscreen; restart resets on
every explicit visit. Choose visible/restart when a pause/replay has a purpose.
Returning can continue an action, pause it or deliberately replay it. duration
bounds sampled local tracks; view.localTime reports raw clock and view.sampleTime
reports bounded time. Footage decoding/looping remains the renderer's job.

Abstract example; replace relationships, views and anchors for the actual job:
```js
import * as music from './package/visual-state.js';
import {createEditScore} from './package/edit-score.js';
const score = {
  intent:'music-video',
  stages:[{id:'first',start:0,end:music.RHYTHM_MAP.duration,entry:'wide',
    focus:'chosen subject',change:'detail changes our reading of the whole',
    rhythm:[{start:0,end:music.RHYTHM_MAP.duration,mode:'alternate',
      music:'example repeated attacks; replace with actual passages',
      reason:'whole and detail reveal the same subject',anchors:[{beat:1},{beat:3}]}]}],
  shots:[
    {id:'wide',relation:'whole subject',clock:{mode:'visible'},
      values:{'camera.z':10},setup:{sourceId:'chosen-source'}},
    {id:'detail',relation:'detail of that subject',clock:{mode:'continuous'},
      values:{'camera.z':2},setup:{sourceId:'chosen-source'}}
  ],
  groups:[{id:'phrase',stage:'first',
    anchors:[{beat:1},{beat:2},{beat:3}],
    sequence:['detail',null,'wide']}],
  tracks:[]
};
const edit = createEditScore(score,music);
function seek(localTime,excerptStart=0) {
  const state = edit.at(excerptStart+localTime);
  // Select state.view.id/setup; apply state.values through one adapter.
  // Use view.sampleTime for local motion/media; decode before final rendering.
  return state;
}
```
A view is a complete shot setup, not automatically a photo card or a slide.
Repeated visits do not require a new object. Combine cuts, holds and continuous
shots according to the reference and musical phrase. at(t) is independent of
query order. `cuts` exposes resolved times; `frameWarnings(fps)` identifies visits
with no output frame. These warnings never silently shift measured anchors.

## Optional picture tools
Reuse existing framing/bindings when suitable. Read references/picture-tools.md
only if needed: `frame2D` fits a 2D target, `frame3D` fits a perspective target,
`createPictureBindings` connects compiled shots/properties to native setters.
They add no production step. Read the relevant API section for the chosen
renderer; helpers provide no style or automatic camera path.

## Shared motion
`createChoreography(score,music)` remains available for motion-only work.
moments are named anchors; tracks are unique `{id,keys}` property writers.
Keys: `{at,value,ease}`; value is a number, numeric vector, string or boolean.
Outgoing ease: linear, smooth, in-cubic, out-cubic, hold. Discrete changes need
hold. The destination value is exact on its key; last values persist.
Anchor: seconds, `{beat:index}` (zero-based array index), `{onset:id}` (measured
instant), or `{moment:name}`. Object anchors accept offsetBeats then offset
seconds. Real local beat spacing preserves fractional onset phase; no quantizing.
Several tracks can share one moment with different preparation/aftermath.
Optional `pace:{from,to,every,step,mode}` adds a scalar/vector increment per beat
interval; step advances discretely, travel continuously. Final advance persists.
Optional `activity:{band,amount}` adds selected low/mid/high/all activity to that
same property writer. No default pump, shake, particles or slow easing.

For travel that must survive cuts, add one GLOBAL progress track to score.tracks:
```js
{id:'world.travel',keys:[{at:0,value:0,ease:'hold'}],
 pace:{from:{moment:'enter'},to:{moment:'arrival'},every:1,step:1,mode:'travel'}}
```
Define enter/arrival from the actual job's anchors. This value interpolates real
beat spacing, keeps advancing across cuts and retains its result at arrival.
The adapter uses the SAME value for camera path and supporting depth layers;
shot setup chooses the viewpoint. Do not substitute view.sinceCut for world
progress: it restarts each cut. Use sinceCut only for deliberate cut-local settling.
Short impact/arrival easing may finish while travel continues. Once the journey
ends, author the next process or an intentional rest; continuous agitation is
not required. If the candidate grid is unsuitable, use a linear global track
between chosen measured seconds instead of claiming beat-locked motion.

## One technical check
Run `node package/music-brief.mjs --score score.json --mv` once after MV changes.
It checks spans, anchors, cut conflicts, writers, return clocks and reverse query
order and declared rhythm without rendering. It reports switches and longest
visit per passage, plus unsampled visits at30fps; inspect with the
actual output fps. It does not prove beauty, reference fidelity or listening.
For a dense interval `node music-brief.mjs --groups start end maxGap [minEvents]`
reports numerical onset runs (bounded output, explicitly marked truncation).
They are not confirmed phrases or an automatic cut schedule. Programmatic
`groupOnsets(map,start,end,{maxGap,minEvents})` returns complete runs when needed.
