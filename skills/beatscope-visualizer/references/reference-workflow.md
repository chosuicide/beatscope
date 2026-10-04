# Reference-led creation with BeatScope

Use this guide for observing and comparing a supplied visual reference. `video-workflow.md` owns the production sequence and shot-continuity review for all video tasks. The user's request and actual media determine creative direction. Keep plans and review records in the **job directory**, outside the timing package.

## 1. Inventory and roles

List each existing input with a stable ID, path, SHA-256, and one or more explicit roles: `target_audio`, `reference`, `usable_asset`, `source_template`. A reference video's frames or soundtrack are not automatically usable assets. Reuse already answered preferences; ask only when a conflict or genuinely missing choice changes the result. If a runnable template is supplied, inspect its output and relevant implementation before replacing it. Record missing media, inaccessible files and reproduction limits plainly.

## 2. Observe the actual reference

For video, measure duration, dimensions and frame rate. Make an 8–16-frame overview contact sheet, then inspect ordered frames or playback from 2–4 defining intervals: sustained motion, a characteristic effect or accent, and a transition if present. Sample faster around rapid changes; a single still cannot prove movement. Note whether observation was playback or frames. Use source time intervals, not vague style labels. Describe subject placement and negative space; materials, type and compositing; light and color; which layers move, hold and recover; and edit/transition relationships. Mark absent features `not_applicable` instead of inventing them.

For sped-up or densely edited references, inspect at native frame rate and use a slowed, muted inspection copy. A five-second clip may contain hundreds of distinct frames. Do not infer its construction from a low-rate overview or a fixed 8fps sample. The helper accepts `--fps native --slowdown 4`; short clips default to native-frame samples covering the whole clip in bounded intervals. Split a long/dense interval rather than silently dropping its later frames. Source timestamps remain authoritative; slowed inspection time is a separate clock and the slowdown factor does not establish the reference's original pre-acceleration speed. Record frame coverage and sampling limits. Review native-speed pace separately; do not claim an audio/feel review from silent slowed footage.

Keep observations separate from hypotheses. “The background scrolls while the portrait stays still from 00:06–00:09” is an observation; “use a fragment shader” is an implementation hypothesis. Do not copy reference-video cut times onto the target song's different timeline.

Before designing the preview, inventory three distinct feature types: **persistent anchor** (the subject/material that must survive changes), **state sequence** (distinct compositions or environments and their order), and **within-state evolution** (what changes while a state holds, including interruption and recovery). For each observed type, cite sampled observation IDs and the requirements that protect it. Mark a genuinely absent type `not_applicable` with a concrete reason. The checker rejects a missing category: fast backgrounds cannot silently replace the defining subject, and correct palettes cannot silently erase a passage's internal choreography.

An anchor can also be a recurring graphic, typography, compositional axis, treatment or theme; it does not require a single object to remain on screen. Use `visual-relations.md` to distinguish shape, motion, representation, graphic, recurring, thematic and contrast relationships. Use `material-treatment.md` when points/dots/pixels are a defining material feature. Give each supplied reference its requested role: a main sequence reference can govern editing while a second reference governs only material treatment. Do not import the second reference's layout, UI, pacing or soundtrack unless requested.

For multiple main references, observe each separately before comparing shared grammar. Describe both recurring operations and differences, with source intervals from each. A role handoff, foreground surviving a background cut, a deliberate full-frame interruption, or source-derived reflection/fragmentation can provide coherence. Do not force uninterrupted physical continuity or full-time intact asset recognition onto a reference that deliberately changes them. Preserve required identity at the appropriate sequence level and keep explicit departures visible in the review.

## 3. Bind a concrete brief

From observations and explicit user changes, write a few testable features. For each, name the reference interval, target output interval, usable source asset, responsible source module and observable preview criterion. Prefer preserving the reference's defining motion and composition while making only requested changes. If a feature cannot be implemented with the available tools/assets, record the gap before promising it. Avoid a default “glitch,” “cinematic,” or other house look: different references must produce different briefs.

Delegated creative direction still includes the supplied references. When adapting their objects or colors, retain and review their defining transformation, spatial progression and relative pace of visual changes. Do not silently reduce those features to easier criteria such as "the same object stays visible" or "a circular wipe happens". Record the retained feature and any proposed departure explicitly; a technical pass cannot approve that departure on the user's behalf.

The target song's BeatScope events supply measured trigger times. Continuous media movement, drift and recovery can occur between events. A selected onset is a candidate for a discrete action, not an obligation to cut or shake the whole frame. Decide pacing, minimum shot holds and conflicting events in the consumer, without moving selected event timestamps. Never force a cut every two beats or turn every band value into whole-screen motion. `response_relevance` is ordering, not confidence, probability or taste approval. When it is absent, the chronological fallback is not a learned edit schedule.

Do not compress a feature to a palette adjective. For an anchor, describe geometry, material treatment and visibility across changes. For a sequence, describe the visible order without copying source-song cut times. For within-state evolution, describe start, intermediate transformation, hold and recovery. A `matched` review needs visible evidence for the relationship, not merely the right color or subject appearing once. If a repair strengthens one feature but degrades another, retain both findings and repair the regression.

## 4. Render, compare and repair

Follow `video-workflow.md` to plan the work and render a representative continuous passage. Include the shots around a difficult transition. Record source/plan and preview hashes before building a comparison.

Build a paired comparison of the reference and preview with clearly labeled **source times on both sides**. Preserve each panel's native playback speed; hold a shorter panel on its last frame rather than stretching it. Mute the comparison or use only one specified soundtrack—never let two BGMs compete. **Watch the resulting comparison** or inspect sufficiently dense ordered frames. For each brief feature, record `matched`, `mismatch` or `unverified` with a concrete visible observation. Examples of mismatch: subject much larger than reference, stationary layer shaking, sustained flow reduced to isolated pulses, effect never recovering, supplied footage replaced by generic geometry.

Repair mismatches in the real consumer and re-render the affected interval. Normally allow two local repair passes; then disclose remaining mismatch or ask one targeted question if the reference is genuinely ambiguous. Do not quietly drop a difficult requirement. Expand to the authorized complete piece via the same renderer once no critical mismatch remains, unless the user wants to approve the preview first.

## 5. Job-local review record

Use `creative-review.json` as a compact, machine-readable notebook. This is not a replacement for looking at images/video. Generated evidence paths are relative to the review file's directory; original input paths may be absolute and are read-only. Never copy paths or binary media into the timing ZIP or a prompt. At minimum:

```json
{
  "schema": "beatscope-creative-review-2",
  "reference_mode": "reference-led",
  "user_request": {"task": "Make an MV using my portrait and the supplied reference", "supplied_choices": [], "authorized_assumptions": []},
  "inputs": [{"id": "ref-1", "path": "reference.mp4", "sha256": "...", "roles": ["reference"]}, {"id": "portrait-1", "path": "portrait.png", "sha256": "...", "roles": ["usable_asset"]}, {"id": "texture-1", "path": "texture.png", "sha256": "...", "roles": ["usable_asset"]}],
  "observations": [{"id": "obs-1", "reference_id": "ref-1", "interval": [6, 9], "method": "playback", "detail": "portrait holds; background scrolls", "evidence_paths": ["samples/sample-1/001.jpg"]}],
  "requirements": [{"id": "flow", "observation_ids": ["obs-1"], "instruction": "keep portrait still while texture moves", "priority": "critical", "success_criterion": "continuous drift without portrait shake"}],
  "feature_inventory": [{"kind": "persistent-anchor", "status": "observed", "observation_ids": ["obs-1"], "requirement_ids": ["flow"]}, {"kind": "state-sequence", "status": "not_applicable", "reason": "single sustained state"}, {"kind": "within-state-evolution", "status": "observed", "observation_ids": ["obs-1"], "requirement_ids": ["flow"]}],
  "asset_bindings": [{"requirement_id": "flow", "asset_ids": ["portrait-1", "texture-1"], "code_location": "src/composition.js"}],
  "preview": {"path": "preview.mp4", "sha256": "...", "source_path": "src/composition.js", "source_sha256": "...", "plan_path": "creative-plan.json", "plan_sha256": "...", "renderer": "..."},
  "comparisons": [{"reference_id": "ref-1", "reference_interval": [6, 9], "preview_interval": [14, 17], "path": "comparison.mp4", "sha256": "...", "preview_sha256": "..."}],
  "reviews": [{"requirement_id": "flow", "status": "matched", "paired_evidence": "comparison.mp4", "result": "both panels retain a steady portrait"}],
  "sequence_reviews": [],
  "repairs": [],
  "final": {"path": null, "source": null, "rerender_command": null, "reviewed_intervals": []},
  "review": {"level": "none", "reviewer": null, "user_accepted": false}
}
```

Keep the source and plan files inside the review directory so their hashes can be rechecked. Update `status` to `reference_observed`, `preview_rendered`, `comparison_reviewed`, `final_rendered` only after the named action. `review.level` is `none`, `self`, `independent`, or `user`; a checker cannot set this based on file existence. Record repair attempts and hashes; regenerate comparison if source, preview or plan changed. For `not_applicable`, include the reason. Keep reference and output intervals separate. A preview-stage structural pass expects every requirement to have a binding and a concrete review. To produce the comparison, set its intervals and path, run the helper, then fill in the returned SHA-256 and review it visually before writing the review result.

Fill `sequence_reviews` according to `video-workflow.md`; individual feature matches alone cannot pass a v2 preview. For authorized procedural/generated material, a binding can use `asset_ids: []` with a concrete `generated_material` description and the responsible `code_location`. Do not invent an input asset. Reference comparison intervals use local MP4 times; sequence reviews use target-song times.

`reference-tools.mjs` can help inspect metadata/frames, construct comparisons, and check record completeness and stale hashes. Its structural pass **does not** judge fidelity or quality. A passing package probe only proves timing-package integrity; a playable render only proves the renderer ran. Final delivery includes the playable work, source and rerender command, with any known departures made clear.
