# Six music-to-picture choices

Read AGENT.md. Query a window: `node query.mjs START END --accents --beats
--stages --limit 12`. Resolve saved edits first. Strength thresholds are local
selection aids, not calibrated confidence; activity is novelty, not loudness.
Roles are authored/user labels. Examples use geometry and synthetic sound only.
Score keys use seconds; frame counts below assume 30fps and must be rescaled.
In scores, `focus` names what to watch; `change` describes the visual before/after;
`music` records audible or measured evidence; `reason` explains the rhythm choice;
`relation` describes the shot's spatial/layer arrangement; `action` gives concrete motion.

1. **Single strong attack**
   Evidence: a resolved cue near the top of local strength (e.g. ≥0.8 when present).
   Choose a cut, compression/impact, or brief occlusion; not all three by default.
   Prepare 3–6 frames → impact on the cue → recover over 6–10 frames.
   [Score](../examples/directing/accent.json) · [2s with sound](../examples/directing/accent.mp4).
   Avoid: dense strong attacks; pick the meaningful one instead.
2. **A transition is an event**
   Evidence: a selected resolved cue near a saved stage/shot handoff.
   Choose growing material, a mask revealing the next world, or linked shapes.
   Prepare 4 frames → half-cover at the cue → finish over 4 frames.
   [Score](../examples/directing/transition.json) · [Sound](../examples/directing/transition.mp4) · [Late center](../examples/directing/transition-late.mp4).
   Avoid: forcing a midpoint onto a deliberate hard cut; late starts drag arrival.
3. **Build before an authored drop**
   Evidence: rising window.onsetDensity/activity; drop time is user-marked or a hypothesis.
   Choose tighter framing, fewer colors, or faster secondary detail; then release.
   Prepare ~15 frames → hold briefly before the cue → expand over 9 frames.
   [Score](../examples/directing/buildup.json) · [Sound](../examples/directing/buildup.mp4).
   Avoid: assuming every rise is a drop; this example labels its drop as authored.
4. **Dense small rhythms**
   Evidence: close resolved cue gaps or rising onset density; not instrument identity.
   Choose specks, fine lines, or small light pulses; keep the subject readable.
   Prepare 0 frames → detail pulse on selected cues → recover over 2 frames.
   [Score](../examples/directing/dense.json) · [Sound](../examples/directing/dense.mp4).
   Avoid: a full shot change on every little attack; fatigue erases emphasis.
5. **Gap or deliberate pause**
   Evidence: a cue gap plus low activity; confirm the audible pause before designing it.
   Choose a held pose with dust, a blink, or a single moving line.
   Settle over 3 frames → hold through the gap → resume over 6 frames.
   [Score](../examples/directing/pause.json) · [Sound](../examples/directing/pause.mp4).
   Avoid: treating slow drift as a neutral substitute for a deliberate hold.
6. **A theme returns changed**
   Evidence: recurrence in automaticSections plus an authored link between saved stages.
   Choose the same composition with a missing line, changed light, or reversed relation.
   Recall over 0–4 frames → reveal the difference on the cue → retain it ≥6 frames.
   [Score](../examples/directing/return.json) · [Sound](../examples/directing/return.mp4).
   Avoid: identical replay without development, or unfamiliar compositions called a return.

See [common failures](common-failures.md), [complete example](complete-example.md)
and [renderer adapter](rendering.md). Inspect moving references with audio once;
cache observations and test changed windows within the user's render limits.
