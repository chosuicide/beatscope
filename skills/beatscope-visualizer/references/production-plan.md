# Translate observations into a production plan before writing render code

For new video jobs, use the existing film plan plus a compact job-local `production-plan.json`. Fill it yourself. Reuse the user's material and decisions; do not ask them to populate a form. This is an implementation brief, not a style preset or a renderer.

## First decide the authorized deliverable

If the user asks for analysis or a plan and explicitly suspends demos/rendering, set `delivery_mode: "plan-only"` in the review record. Deliver the readable translation table and layer plan, sources/assumptions and unresolved implementation questions. Stop before renderer code, frame generation or video production. Source reference inspection remains allowed. Do not call plan completeness a preview or reference-fidelity success.

For an authorized video, prepare and self-check the same plan, then continue to the already authorized preview/render. This stage is not an extra user approval gate. Ask only for a genuinely blocking choice not already settled.

## What to write

Each retained requirement gets a translation row: observation IDs, actual usable asset IDs, responsible layers, proposed operation, visible stages, what remains recognizable, departures and concrete visual checks. Distinguish `candidate`, `verified`, and `blocked` implementation status. A GitHub lead is a candidate, not a verified effect. A blocked requirement needs resolution or an explicit limitation, never silent removal.

Each shot gets layers with a role, appearance, absolute-song-time interval, motion, entrance and exit. Describe how supporting layers enter/leave or take over the focal role. Layers can be still; a one-layer work is valid. Use film-plan `entry` fields for cross-shot handoffs or intended interruptions. Avoid using a stock palette, global scale pulse or the phrase "same style" as the entire plan.

Connect musical facts after authoring these operations. Explain their roles: composition, local event, sustained movement, density, or deliberate hold. Link discrete uses to the film plan's measured actions. Continuous uses name actual API fields and a visible response; `source: "none"` explains intentional time-driven/still behavior. Do not require all roles or fields in every shot. Correct source IDs do not prove the visual result.

## Make the action readable, not just noticeable

For each defining action, name the subject and write `visual_logic` in the film-plan action: `before`, `preparation`, `change`, `consequence`, and `next_use`. These describe visible conditions, not code parameters. Preparation can be absent for an intentional immediate interruption; explain that choice. A consequence may persist, transfer to another layer, recover deliberately, or resolve into a hold. Recovery is a choice, not a default spring-back after each beat. `next_use` explains what a later action inherits, or why the resolved state is held. Do not invent anticipation or narrative for a work that calls for a direct cut or a cycle.

A meaningful action might let a foreground edge conceal part of the source, build directional pressure there, open that edge on a selected impact, then use the opening to reveal the next material. The image's new condition survives the impact. This is one illustration, not a recommended universal effect. Repeated scale/rotation, cards, oversized type and diagonal panels are not substitutes for the user's intended action language. Derive roles from the supplied references and inspect the user's actual sources before assigning landmarks.

For musical expression, choose where the listener should read an onset, where continuous facts should shape an ongoing action, and where the result should settle. Separate the envelope of the authored action from the raw field's fast changes. A causal smoothing filter alone does not make a readable gesture. Limit strong responses to the layers and intervals that need them; inspect attack, event visibility, release and retained consequence in consecutive frames. Compare with target audio when available; do not claim a listening review from stills or pixel differences.

Before building, identify repetitive mechanisms across the whole excerpt. If the same zoom/rotation/reveal does every handoff, or text and panels repeatedly occupy the focal role without a reference-based reason, revise the action design. Varied states are useful only when their relationships are readable. A simple shot and a deliberate hold remain valid.

## Job-local contract

Keep `beatscope-film-plan-1` and review schema v2. Add `production: {"path":"production-plan.json","sha256":"actual hash"}` to the review; `preview.plan_path`/`plan_sha256` still bind the film plan and do not imply a video exists. The new file uses:

Set `production_required: true` and `perceptual_review_required: true` on new film plans. Omitting the production binding cannot pass the plan stage; the latter marker requires declared perceptual findings at preview/final. Historical plans without these markers remain readable.

Also set `action_intent_required: true` for new jobs. Each declared film action then needs the five `visual_logic` strings described above. Actions may remain empty for an intentional still work. At preview/final, include `action_readability: {"status":"matched", "reason":"actual visible attack, change and consequence, or justified hold"}` alongside the other perceptual findings. Earlier plans without this marker retain their earlier contract.

```json
{
  "schema": "beatscope-production-plan-1",
  "film_plan_sha256": "actual creative-plan.json hash",
  "translations": [{
    "id": "translation-1", "requirement_id": "retained-feature",
    "observation_ids": ["observed-reference-action"], "asset_ids": ["user-city"],
    "layer_ids": ["city-surface"], "operation": "move the same supplied image from a full-screen layer into a curved masked surface",
    "preserved": "the recognizable building and road directions", "departures": "no departure proposed",
    "implementation_status": "candidate",
    "steps": [{"interval": [10, 11], "change": "full-screen image contracts into the curved surface while a line remains"}],
    "checks": [{"interval": [10, 11], "criterion": "the outgoing building can be located on the incoming surface; the image does not disappear before the surface becomes visible"}]
  }],
  "layers": [{
    "id": "city-surface", "shot_id": "shot-1", "interval": [10, 11], "role": "primary",
    "asset_ids": ["user-city"], "appearance": "supplied image with a controlled curved mask",
    "motion": "image footprint contracts; road direction stays aligned", "entry": "already full screen", "exit": "continues as the next shot's foreground"
  }],
  "music_uses": [{
    "id": "music-1", "shot_id": "shot-1", "interval": [10, 11], "role": "sustained", "source": "bands",
    "fields": ["mid"], "layer_ids": ["city-surface"], "action_ids": [],
    "effect": "mid-band energy controls a small local surface distortion without hiding the subject",
    "reason": "add motion inside the authored transformation rather than create more cuts"
  }]
}
```

The example's interval and operation are illustrative, never defaults. Each row's intervals must fit the detailed render interval; layers/music uses belong to their shot. Empty `asset_ids` requires concrete `generated_material`. References are not usable assets unless their roles explicitly permit it. For original work, `observation_ids` may be empty; retain task requirements and bind the user's assets or authorized generated material.

Run `node reference-tools.mjs check --record creative-review.json --stage production`. It checks film coverage, measured trigger claims, file hashes, linked requirements/observations/assets/layers, timed steps, visual criteria and musical roles. Existing historical plans remain readable. New jobs include the production binding so subsequent plan/preview/final checks recheck it. A passing structural audit cannot determine whether prose is specific enough, whether a shader is feasible, or whether the resulting video matches; self-review the translation table for substituted/easier operations and disclose candidate status.

## Keep promises checkable after rendering resumes

After rendering, inspect development within each continuous passage, musical influence on the picture, and the actual material operation. Add `perceptual` to every sequence review, with `development`, `musical_effect` and `material_fidelity`, each containing `status: "matched"` and a concrete `reason`. Missing, mismatch or unverified findings block preview/final for new marked plans. The checker verifies the declaration and existing evidence bindings, not the truth of the visual judgment.

For new action-marked plans, review `action_readability` as well: can a viewer locate the actor, read what happened at its intended time, and recognize the changed condition afterward? Identify gratuitous jitter, imperceptible entrances, repeated resets, obscured gestures and arbitrary layout changes. A large pixel difference or more events cannot pass this review by itself. Do not pre-fill matched findings before watching the evidence; preserve mismatches and disclose actual review limits.

If another Agent or reviewer is available, give them the actual preview, source reference intervals and retained criteria, then ask for observable failures. Record whether this is self-review, independent review or user acceptance. A reviewer comment without viewing the actual evidence is not independent visual approval. Resolve important failures before expanding; normally allow two focused repair passes, then deliver the diagnostic excerpt and report the remaining failure rather than pretending the full-work gate passed.

- **Development:** describe what new visual information arrives, how focal roles/scale/depth/representation change, and where a deliberate hold earns its time. A moving camera or completed reveal followed by a long idle passage is not sufficient by itself. Review internal states and adjacent shots at both original and slowed speed. Do not impose a universal cut rate or require motion when stillness serves the request.
- **Musical effect:** inspect actual field ranges over the requested song interval before choosing response strength. The fields may represent novelty rather than loudness; use the schema's semantics. Keep any normalization and finite attack/release envelope in consumer code, query past facts deterministically, and retain the original facts. Explain which changes affect the main image versus small accents. If every musical response is a border, line or global scale pulse, revisit the roles rather than merely adding more triggers.
- **Material fidelity:** locate source-derived information in the rendered dots, curved surfaces and fragments. Do not silently replace a promised texture fracture with floating rectangular cards, source-shaped dots with a generic emitter, or complex spatial layering with one rotating object. A different implementation is allowed when its visible relationship satisfies the requirement and the departure is disclosed.

When useful, render a same-time comparison with continuous musical modulation disabled while keeping the authored scene schedule. This exposes negligible or excessive responses. Pixel difference is diagnostic, never a universal pass threshold or proof of musical fit. Likewise, more states, higher density or more effects are not automatically better; judge the reference's balance of simultaneous action, handoff, contrast and breathing space.

Reuse translation checks in the actual comparison reviews. Inspect the specified intervals, layers and source-derived information. Retain failures of role handoff, point density, representation changes or layered action even when event times are correct. Update all bound hashes when the film or production plan changes. Planning status, implementation feasibility, rendered evidence and user acceptance are separate claims.
