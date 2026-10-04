# BeatScope timing package: consumer-fixture

Read `AGENT.md` first. Query data; do not load the map in full into context.

## Files

- `beatscope-package.json`: capabilities, functions, inventory and member hashes;
  summary `stage_count` is the resolved stage total, not a count of user edits.
- `rhythm-map.json`: authoritative measured facts, stored once without rounding.
- `visual-state.js`: synchronous timing accessors using the JSON documents.
- `beatscope-runtime.js`: shared query implementation.
- `choreography.js`: renderer-neutral, seek-safe authored tracks and shared moments.
- `edit-score.js`: grouped cuts, reusable shots and deterministic revisit clocks.
- `edit-plan.json`, `edit-plan.js`: stage boundaries and compact cue overrides;
  resolve with `resolveEditPlan(rhythm, plan)` before authoring the score.
- `picture-tools.js`: optional target framing and native picture bindings; no style.
- `music-brief.mjs`: one bounded music summary query, no dependencies.
- `consumer-probe.js`, `worker-example.js`: contract check and module-worker adapter.
- `SKILL.md`: API examples; `BEATSCOPE.md`: timing invariants.
- `references/schema.md`: fields; `references/directing.md`: video workflow.
- `references/picture-tools.md`: optional framing/binding API; read only if needed.
- `LICENSE`: shipped code terms.

## Not in this package

No audio, assets, style, visual scene plan, rendered video or machine paths. Pair this
with `consumer-fixture` and the user's task. References and assets are optional;
follow AGENT.md for direction and source authorization. CSV and MIDI remain separate
BeatScope exports. Job-specific sources, decisions and evidence stay in the job.

## Authority

`rhythm-map.json` is the measured factual source; `edit-plan.json` is authored
passage/response timing. The entry imports facts with JSON
import attributes; use Node 22+ or a current Chromium browser/module worker.
In a browser, serve the package over HTTP with JSON MIME `application/json` and
JavaScript MIME `text/javascript`; opening a file URL is insufficient. No build
step or extra runtime dependency is required. Accessors remain synchronous after
module loading. Use the manifest instead of guessing capabilities.
