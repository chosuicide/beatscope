# Make a video with a BeatScope timing package

Give the Agent the ZIP, original song and task. Assets and references are optional.
When supplying references, identify main-look and material-treatment roles if they
differ. The Agent can use procedural visuals or authorized online sources.
If both direction and source authorization are unclear, it asks once together;
it does not require references, technical parameters or engineering versions.
The Agent authors the edit;
users do not fill in motion parameters or a shot table.

## Engine integration: package format 0.19.2 (editable stages and cues)

`beatscope.exports.generate_codex_export` is the shared exporter for the Studio
download (`GET /api/projects/:id/export/codex.zip`), legacy server and MCP
`beatscope_export_package`. Each exports the current bundled code and guides;
there is no song-specific candidate builder in the product path. The Studio copy prompt
directs the receiving Agent to that package-owned workflow.

The handoff checks source hash, score duration and revision binding before
resuming a matching project. A materialRoot or ready flag alone is insufficient.
Without a matching project it creates a new work, without inventing accepted
history or carrying over another song's timeline. Visual assets and renderer
definitions may be reused separately within authorization. It reads selected
summary fields instead of dumping embedded timing/ranking caches or recursive
asset inventories. Manifest `stage_count` means resolved stage total, not edits.

For a matching project, the handoff starts with the accepted requirements,
cached reference observations, assets, renderer and job-local score. It requests
a scoped patch rather than a new production. The latest saved editor plan stays
authoritative when the live preview has not been refreshed. Package probe results
may be reused for identical package bytes; music briefs are cached by rhythm and
edit-plan hashes. Revisions check affected intervals and necessary seams only.
No style, palette or effect preference from one project becomes a package default.

Editable boundaries use flags on the original plots' time rulers. Editable onset
markers use the original purple `ACCENT / BLOOM` row. Hollow diamonds distinguish
authored marks from filled measured accents; the lower `MOTION CUES` rail keeps
its original measured summary. Cue times remain exact;
zoom changes that same rhythm graph. There are no separate editor tracks.
Add at the playhead, drag, select/delete, undo/redo, snap and restore automatic
suggestions use compact icon buttons, accessible names and hover hints.
The whole-song structure band retains measured recurrence families and original
spans. Authored stages are numbered separately. Selecting a ruler flag highlights
its interval and shows its exact start/end; authored flags stay accented after
reload. The original plots fit their container without horizontal clipping.
Edits save atomically per project with ETag conflict checks, without reanalysis.

The ZIP carries measured timing, compact authored timing overrides, optional
onset ordering, generic choreography and edit execution. No song audio, sources, visual style, job score or rendered
movie is embedded. CSV/MIDI remain separate exports. Size depends on song data;
the older Mafia v26 ZIP was359850bytes, not a universal size limit.

## Contents and execution

- `beatscope-package.json`: capabilities, entry points and member SHA256 hashes.
- `rhythm-map.json`: beat/onset times, multiband activity, optional structure,
  segment waveform RMS and timing diagnostics, stored once.
- `response-relevance.json` when available: ordering values for selecting a
  bounded set of existing onsets; not confidence or automatic edit instructions.
- `visual-state.js`, `beatscope-runtime.js`: synchronous media-time queries.
- `choreography.js`: named moments and global/local property tracks. Several
  tracks may share a cue; continuous beat-paced travel retains final progress.
- `edit-score.js`: stages, reusable shots, grouped cuts/holds, return clocks and
  executable rhythm blocks. The renderer consumes both shot setup and values.
- `edit-plan.json`, `edit-plan.js`: shared passage boundaries and cue overrides.
  Original onset facts stay unchanged. `resolveEditPlan` returns contiguous stages
  and cues, retaining source times. The built-in preview and renderer use the same
  compiler; render jobs freeze this sidecar at submission. Studio and MCP exports
  include saved edits. Untouched cues stay ranked candidates; moved/added cues are
  explicit responses. This editing layer does not prescribe the receiving Agent's
  picture, shot sequence or motion style.
- `picture-tools.js`: optional 2D/3D target framing and native picture bindings.
  Reuse existing code when suitable; helpers add no required production pass.
- `music-brief.mjs`: bounded music summary, dense onset groups and score checks.
  `stages` uses the resolved editor plan. `automaticSections` and
  `measuredAnchorCandidates` describe analysis evidence separately. Manual cue
  inspection is bounded and reports truncation; execute the full resolved plan.
- `consumer-probe.js`, `worker-example.js`: contract checks and worker adapter.
- `AGENT.md`, `SKILL.md`, `BEATSCOPE.md`, `README.md`, schema/directing references,
  optional `references/picture-tools.md`
  and `LICENSE`: entry workflow, API examples, semantics and code terms.

The receiving Agent reuses one job-local `score.json` outside the package and
creates it only when missing. For
an MV use `intent:"music-video"`; choose stage rhythm (hold, switch, alternate)
from musical passages before authoring related views and their motion. Ordinary
beats, dense onsets and accents may organize combinations. No built-in pattern,
cut frequency, shake or visual motif is selected by the engine.

MV shot clocks default to continuous: they advance offscreen from first visit.
Other scores default to visible time; visible/restart remain explicit choices.
Use a global travel track for one process viewed across cuts, and cut-local time
only for deliberate settling. Finishing a short impact does not stop that global
process. The adapter supplies geometry, media decoding, materials and camera.

Read the picture API only when a helper is needed, and use the section matching
the chosen renderer. 2D and 3D are independent options, not two required builds.
The Studio's copy instructions refer to the package workflow rather than
duplicating it. This integration changes the source engine and rebuilt frontend;
previously distributed Windows executables need a separate rebuild to include it.

## Bounded workflow and checks

Read `AGENT.md` first. Cache one probe and bounded music brief. Inspect continuous
reference passages when provided; slow accelerated references without guessing
original speed. Author and compile the compact score. Run
`node package/music-brief.mjs --score score.json --mv` after score changes.

Technical checks cover stage/rhythm spans, anchors, property-writer conflicts,
declared shot changes, return clocks, backwards queries and visits missed by
30fps output. Use the actual render FPS for frame warnings. Package integrity
and executable trust can also be checked with `beatscope validate-handoff`.

Default visual review uses one representative24–30fps passage containing ordinary
beats, an accent and a stage handoff. Inspect post-impact motion and returning
views, not only impact frames. Repair concrete failures in their affected
intervals. Whole-song animatics, long reports and parallel trials are not default
gates. Deliver playable media, source, rerender command and remaining differences.

## Semantics and limits

Beat grids and structure may be provisional; successful runtime checks do not
certify them. Activity measures spectral novelty, not loudness or instruments.
Segment RMS is waveform amplitude, not perceived loudness. Family labels express
recurrence, not verse/chorus roles. Cuts use measured onset times without silent
quantisation. Alternate timing candidates require separate evidence.

JSON imports need Node22+ or current Chromium over HTTP with correct JSON/JS
MIME types. Accessors require no extra runtime dependency after module loading.
Use absolute media time for repeatable seeks and offline frames.

The package executes an authored score, not automatic visual direction. Neither
validation nor a completed score establishes beauty, musical fit, reference
fidelity or user acceptance. Production assets and evidence stay outside the ZIP.
