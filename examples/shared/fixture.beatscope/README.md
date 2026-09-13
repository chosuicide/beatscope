# BeatScope timing package - consumer-fixture

The measured timing facts for one audio file, packaged for a coding agent or a
visual tool. Start with `AGENT.md`: it owns the flow and explains how to read
this package without loading megabytes into context.

## Files

- `rhythm-map.json` - the authoritative timing data: duration, tempo and origin,
  bars and beats, raw onsets with strength and band energy, accents, sampled
  energy, and structure segments. Query it; do not read it in full.
- `rhythm.mid` - the same facts for a DAW: a tempo map plus one note per onset,
  velocity from strength. Quantised; `BEATSCOPE.md` says what that means for
  edits.
- `rhythm.csv` - the same facts as a table: `raw_time` next to
  `quantized_time` and `offset_ms`, bar/beat/step, strength, band energy,
  accent flag.
- `beatscope-package.json` - the routing manifest: entry module, probe, honest
  capabilities, exported function names, a short summary, and the sha256 of
  every member.
- `visual-state.js` - dependency-free accessor: `getVisualState(time)`, plus
  `getResponseEvents(start, end, budget)` when the manifest declares it.
- `beatscope-runtime.js` - the shared runtime `visual-state.js` builds on.
- `worker-example.js` - a module Worker adapter: the main thread sends audio
  time, the worker returns the frame facts.
- `consumer-probe.js` - self-check: `node consumer-probe.js .`.
- `AGENT.md` - the entry point: the flow, the questions, the deliverable.
- `BEATSCOPE.md` - the timing invariants and field meanings.
- `SKILL.md`, `references/schema.md` - how to consume the API, exact field
  semantics.
- `LICENSE` - terms for the shipped code.

## Not in this package

No audio: pair the package with the original local file named
`consumer-fixture`. No assets, no fonts, no palette, no style, no scene timeline,
no rendered video, and no statement about aspect ratio, frame rate or pacing.
Those are decisions for you and the user to make together. The package also
never contains machine paths or cache locations.

## Authority

`rhythm-map.json` is the authoritative data. `visual-state.js` embeds the same
map only so that `import` works without a build step or a fetch layer; when the
two ever disagree, the JSON wins.
