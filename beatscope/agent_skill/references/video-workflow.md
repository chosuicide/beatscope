# Direct the sequence before connecting musical events

Use this workflow for a video, MV or animated work, with or without a reference. For a CSV, timing query or explicitly requested data visualization, follow the user's task directly. All creative plans and review records belong in the output job directory, outside this timing ZIP.

## Direction and continuity

Inventory the user's brief, song, reference and usable materials. Inspect a supplied reference through `reference-workflow.md`. Reuse answered choices. When creative direction is delegated, choose a concrete concept yourself; otherwise ask one focused question only if a missing creative decision blocks work.

Read `visual-relations.md` when choosing how the sequence is organized. Coherence can come from matching composition, directional movement, representation changes, graphics/typography, recurrence, thematic association or deliberate contrast. Continuous transformation of one object is only one option. Preserve the requested reference's variety and density; do not simplify a layered montage into a slow morph because that is easier to implement. For dot/point material references, use `material-treatment.md` before choosing a renderer.

Before renderer code, use `production-plan.md` to translate retained observations into the user's assets, timed layer operations, handoffs, visible criteria and musical roles. Run the production-stage structural check. If the user currently requests only analysis/planning and suspends demonstrations, deliver this plan and its limitations, then stop. For an authorized video, self-check and continue without inventing an extra approval step.

Before querying onset candidates, write the work's visible subject and how it develops across the requested duration. This may be narrative, abstract, typographic, a continuous shot or a deliberately fragmented montage. Explain what connects its parts: subject, material, movement, space, theme or an intentional contrast. A stylistic rule derived from the brief can justify recurring rapid cuts; do not impose an arbitrary minimum shot length or invent a story the user did not request.

Outline the whole work's sections in target-song time. Give each section a purpose and describe what returns or changes. Repeated musical families can support a returning motif, but family A/B is not automatically a verse/chorus and does not require a new scene. Keep ongoing motion, holds and silences when they serve the work.

Detail shots only for the interval being rendered first. For each shot, describe its subject, composition, material, purpose and motion over time. For each entrance, state what carries over and what changes, and why. A sustained scene can contain multiple musical events without cutting. Do not create a cut list by looping over beats, ranked onsets or equally sized windows.

A transformation may persist and become the next shot's material or spatial condition. State its consequence and how the next action uses it. Returning to the original form is optional; require recovery only when the brief or observed reference calls for it. Continuity can follow a changing object, a fragment, a motion direction or a newly opened space.

Use the action-intent contract in `production-plan.md` for new jobs. Before assigning an onset, describe the action's visible condition, preparation or purposeful immediacy, change, consequence and later use. Musical modulation should support this gesture rather than continually shake an otherwise unchanged layout. Review repetitive motion and decorative focal takeovers at the sequence level; do not impose one required action style.

## Attach timing to authored actions

After designing an action, query a bounded musical window only if synchronization helps it. Choose no event, one event or a small set as required by that action. A selected event does not create an action by itself. Local changes, camera movement, a reveal, a hold and a cut have different jobs; assign one deliberately. Use measured times when claiming an onset/beat trigger. Continuous motion derives from media time and can proceed between triggers.

For a music-responsive brief, connecting a few large entrances is not enough. Design changes within sustained shots: measured band energy can affect material tension, texture or depth; measured beat phase can organize a traveling motion; selected onsets can supply localized impacts; structure can change the way an established motif develops. These are examples, not mandatory mappings or a fixed style. Choose appropriate facts, preserve their measured time, and specify visible response strength and duration. Do not replace music with an arbitrary oscillator or turn every event into a cut. Smooth noisy values causally when needed without erasing the musical attack.

When expanding a successful excerpt, avoid applying its same deformation or pulse across the whole song. Design how the established subject develops in adjacent measured sections, including what persists and which musical responses change their spatial or material role. A section boundary can gradually change behavior without replacing the subject or cutting. Returning material can retain the consequences of earlier transformations. Explain these choices in the job's plan; structure labels do not supply their meaning. Preview a passage across a relevant boundary and inspect both the handoff and sustained behavior afterward before scaling to the full work.

Check whether the musical response is actually visible, separately from whether the data API was called. Compare the same passage with its musical modulation disabled while retaining authored motion, and inspect dense frames around selected attacks. If both versions look effectively identical, repair the response or explain the deliberate restraint. Pixel differences establish an effect, not musical quality; judge feel through playback with the target audio and report any limits of that review. Do not require every data field to be used.

Create `creative-plan.json` using `beatscope-film-plan-1`. The example below describes one continuous two-second excerpt of a two-second requested work; its subject and lengths are illustrative, never defaults. A longer work has a whole-work `sections` outline and a `render_interval` for the representative excerpt, then expands its shots through the same renderer. Fields:

```json
{
  "schema": "beatscope-film-plan-1",
  "production_required": true,
  "perceptual_review_required": true,
  "action_intent_required": true,
  "duration": 2,
  "work_interval": [0, 2],
  "render_interval": [0, 2],
  "concept": {"subject": "a supplied portrait", "development": "a reflection slowly reveals the surrounding space"},
  "timing_source": {"path": "package/rhythm-map.json", "sha256": "actual file hash"},
  "sections": [{"id": "opening", "interval": [0, 2], "purpose": "establish the subject", "continuity": "the same portrait remains visible"}],
  "shots": [{"id": "portrait-hold", "section_id": "opening", "interval": [0, 2], "subject": "portrait", "purpose": "allow recognition", "composition": "portrait framed in reflection", "material": "user portrait image", "motion": "reflection moves continuously while the face holds", "entry": {"reason": "introduce the subject", "carries": "opening frame", "changes": "reflection becomes legible"}}],
  "actions": []
}
```

`duration` is the timing map's audio duration; `work_interval` is the requested output range in that song. `sections` cover `work_interval` without gaps/overlap; `shots` cover `render_interval` in order and belong to their sections. Split a shot's planning entry at a section boundary if necessary; this does not require a visible cut. `actions` may be empty. An action uses `id`, `shot_id`, `interval`, `description`, `reason`, and `scope: "local" | "camera" | "transition"`. A transition action must begin at its shot's entrance. An optional `trigger: {"kind":"onset"|"beat","id":1,"time":0.5}` on an action or shot `entry` claims a measured trigger at that entrance/action start; IDs and times must match the timing source. Without an ID on a historical beat, omit `id` and match its measured time. Timing source paths are resolved relative to the review directory (absolute read-only input paths also work). This plan specifies this particular work, never the universal look of a BeatScope package.

## Render and judge a continuous passage

Use an absolute media-time function such as `renderAt(t)` or `seek(t)`: a repeat or backwards seek to `t` must reproduce the frame. In an excerpt, render frame `i` at `render_interval[0] + i/fps`; its exported video starts at zero. Keep the actual MP4's local times separate from target-song times. Wait for fonts, images and any video frame decoding before capture. Use the same renderer for preview and full output. HTML/Canvas/WebGL with a controlled clock is one option, not a requirement.

Choose an excerpt that exposes the difficult behavior and neighboring shots; around 8–12 seconds often suffices, but length follows the work. If the whole piece is shorter, render it. Review the passage continuously, or use sufficiently dense ordered frames including the transitions and recovery. Inspect it with the target audio when judging musical feel. For reference work, also generate and inspect paired reference/output passages as described in `reference-workflow.md`.

Check the sequence as a whole: can the viewer follow the subject or intended contrast; does each change serve the concept; do holds have room to read; does movement develop rather than just pulse; do transitions preserve the intended relationship? Inspect the actual material treatment too: masks, crops, transparency and overlays must leave the intended subject and transition visible. A plan saying "portal reveal" does not prove that the foreground lets the reveal show. Review actual use of measured timing separately from visual continuity. A frame-perfect beat can still be a poor cut. Repair the consumer and re-render when continuity, motion or reference requirements fail. Normally limit local repairs to two passes before reporting the unresolved issue; do not expand a failing preview into a full-length failure.

## Record evidence without claiming automated taste judgement

Use `schema: "beatscope-creative-review-2"` in `creative-review.json`. Keep the input, reference observations, bindings, preview hashes and comparison fields described in `reference-workflow.md`. For original work, set `reference_mode: "original"`, omit reference-only evidence, and use the rendered preview as `paired_evidence` for any creative requirements. The existing `preview.plan_path` and `plan_sha256` point to `creative-plan.json`. Add `sequence_reviews`:

```json
[{"interval":[0,2],"method":"playback","evidence_path":"preview.mp4","evidence_sha256":"actual evidence hash","preview_sha256":"actual preview hash","plan_sha256":"actual plan hash","checks":{"continuity":"matched","pacing":"matched","motion":"matched","timing":"matched"},"result":"Describe what is actually visible and how its musical timing was checked."}]
```

Intervals in this field use target-song time, and together cover `render_interval`. They must cite evidence bound to the current preview and plan. Each check is `matched`, `mismatch` or `unverified`; unresolved checks block preview completion. `matched` is the reviewer's declaration, not a computer-vision verdict. The tool validates plan coverage, declared cue IDs/times, evidence hashes and review completeness. It cannot decide whether prose is truthful or cuts feel good.

Run `node reference-tools.mjs check --record creative-review.json --stage plan` before rendering; run `--stage preview` after reviewing the actual result. `--stage reference` checks observations alone. For final delivery, expand the plan's render interval to the entire requested work and refresh preview/source/plan hashes and sequence reviews for that final render; then use `--stage final`. Existing v1 records remain historical evidence and must acquire a plan and a new sequence review to pass the v2 workflow; changing the schema string alone is insufficient.

Deliver the playable work, sources, re-render command and a short account of unresolved differences. State separately whether timing was checked, sequence/reference was self-reviewed or independently reviewed, and the user accepted it. Keep the notebook local; do not ask the user to fill out its fields.
