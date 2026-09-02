# BeatScope

English | [简体中文](README.zh-CN.md)

**One track. One deterministic timing package. Different visual stacks.**

BeatScope is a local, audio-reactive instrument that turns one song into two things: a visual you can play, and timing data an agent can reuse. v0.9 closes the loop: the exported package is now a self-describing handoff contract that independent visual stacks — Canvas 2D, Three.js, and Remotion — all drive through the same deterministic frame function, with validation commands that prove it.

Upload a track and BeatScope builds a beat grid, multiband energy, transients, tempo changes, and a neutral whole-song structure. The browser turns those facts into a seek-safe particle performance and an eight-bar motion cue map. The export turns the same analysis into a portable package with a manifest, an Agent routing document, a self-checking probe, its own <code>SKILL.md</code>, visual recipe, and scene timeline. The player, MCP server, export, and all three reference consumers read the same timing model instead of inventing four slightly different versions of the song.

[![BeatScope animated preview; click to play with sound](docs/demo/beatscope-preview.gif)](docs/demo/beatscope-demo.mp4)

**Click the animation to play the 10-second demo with sound.**

> BeatScope reports rhythm strength, frequency distribution, and timing structure. It does not present uncertain transients as kicks, snares, or 808s. Audio is analysed locally and request-scoped temporary files are removed after processing.

## One package, three visual stacks

The repository ships a frozen handoff fixture (<code>examples/shared/fixture.beatscope</code>, sha256-pinned by <code>fixture-lock.json</code>) and three reference consumers that share nothing but that package:

| Example | Stack | Clock | What it proves |
| --- | --- | --- | --- |
| [examples/canvas-particles](examples/canvas-particles) | Canvas 2D, zero-build | <code>audio.currentTime</code> | play/seek/replay resolve to identical geometry; reduced motion scales displacement to exactly 0.25× |
| [examples/threejs-geometry](examples/threejs-geometry) | three@0.169.0 via import map, no bundler | <code>audio.currentTime</code> | framework glue stays three-free and pure; seeded geometry; declared draw-call budget |
| [examples/remotion-composition](examples/remotion-composition) | Remotion 4.0.520 | <code>frame / fps</code> | the same second maps to the same state at 24/30/60 fps; scene ownership freezes beyond the last scene while timing extrapolates |

Each consumer is a complete, runnable project — open <code>examples/canvas-particles/index.html</code> (or the Three.js one) through any static server and pick an audio file; the Remotion composition renders offline with <code>npx remotion render</code>. Their pinned dependencies live in each example's own <code>package.json</code> and never enter BeatScope's core.

The whole contract is one function call:

~~~js
import { getBeatScopeFrame } from "./fixture.beatscope/visual-state.js";

function paint(audioTime) {
  const { timing, scene } = getBeatScopeFrame(audioTime);
  // timing → bar, beat, beatPhase, low/mid/high, onset, accent
  // scene  → composition (spread, twist, flow, orbit, void, contrast),
  //          transition envelopes, family identity
}
~~~

Consumers choose the clock (media time or frame/fps) and map the returned values to any visual property, but they never re-analyse audio, never guess timestamps, and never copy the BeatScope player.

## Why I built it

The hard part of music visualisation is not making a shape move. It is deciding why it moves now, how much motion this moment deserves, and how the same system survives both a sparse track and a dense one.

A direct peak-to-explosion mapping works for sparse music and quickly falls apart on a dense track. Looking only at total volume loses low-frequency weight, high-frequency detail, and section changes. Handing the same song to another agent later also means repeating those decisions from the beginning.

BeatScope keeps those decisions as data. Python tracks the song; the browser samples <code>audio.currentTime</code>; the motion system separates ordinary pulse, sustained flow, local impact, and rare hero events. You can watch the result now, then hand the exact same timing evidence to the next creative build — whatever stack it uses.

## What one session looks like

~~~text
Upload local audio → build beats and multiband energy
                   → move into the Signal player
                   → play, seek, and inspect whole-song structure
                   → audition or loop an eight-bar cue range
                   → export a handoff package for the next visual project
~~~

1. Choose a WAV, FLAC, MP3, OGG, or M4A file.
2. The local service tracks beats and tempo changes, then derives transients, LOW / MID / HIGH energy, and a structural overview.
3. The page moves into the player, where the particle sphere, traces, and spectrum follow playback.
4. The rhythm pattern overview provides a whole-song view and direct navigation.
5. The eight-bar cue map translates the current window into impact, scale, flow, flash, and bloom references.
6. The export preserves the analysis, a deterministic visual-state function, the self-describing contract, instructions, and a portable Skill.

<details>
<summary>More player states</summary>

### Quiet passage

![BeatScope quiet passage](docs/screenshots/beatscope-player-calm.jpg)

### Dense passage

![BeatScope dense passage](docs/screenshots/beatscope-player-dense.jpg)

</details>

## More than a sphere that moves

### Rhythm pattern overview: see the whole song first

![BeatScope whole-song structure navigator](docs/screenshots/beatscope-track-structure.png)

This navigator compresses the complete track into structural segments, LOW / MID / HIGH energy traces, and transient density. Since v0.7 the top strip draws one block per whole-song structural segment: families are neutral letters (<code>A</code>, <code>B</code>, ...) that mark repetition — never Verse/Chorus recognition — a variant (<code>A′</code>) marks material related to its family but audibly changed, and a repeat of a family always wears the same neutral shade. Boundary ticks are weighted by how strongly the analysis judged each change. Clicking a bar seeks directly to it, and <code>Shift+←/→</code> jumps between segment starts. The red frame always marks the eight bars currently shown in the cue map, so changes do not have to be found by scrubbing blindly through one long timeline.

### Eight-bar cue map: turn listening into usable timing

![BeatScope eight-bar motion cue map](docs/screenshots/beatscope-cue-map.png)

The same eight-bar window exposes IMPACT, LOW / SCALE, MID / FLOW, HIGH / FLASH, and ACCENT / BLOOM. This is not a drum transcription; it is a motion-oriented reference. A transient can be auditioned with one click, a loop can be dragged out, and the resulting timing, strength, and band drivers can be passed into the next visual build.

### The particle instrument

![BeatScope particle instrument at a transient impact](docs/screenshots/particle-impact.png)

The player's central body is an organic three-lobed particle field drawn beneath the instrument chrome. Tension gathers the cloud before a locally distinct hit; the body then moves as one coherent form around a local hot core while stable edge particles extend into flow-guided streamers. Three surrounding orbit belts receive the same beat later in sequence, so an impact travels outwards instead of making every layer jump at once.

![BeatScope particle instrument during anticipation](docs/screenshots/particle-anticipation.png)

Every phase comes from the tempo-aware motion director and the playback clock alone: the same instant of a song always produces the same frame. Particle seeds may change a streamer's reach or grain size, but never its timing. Fixed-time captures of the other states — rest, recoil, dense passage, a variable-tempo boundary, and reduced motion — live in <code>docs/screenshots/</code>.

### Structural scenes: composition that follows the song

v0.8 turns the structural view into two deterministic artifacts. <code>visual-recipe.json</code> gives every repeat family a stable identity — motif, palette slot, composition base — plus shared tokens for transition timing and motion limits; <code>visual-timeline.json</code> instantiates those identities on the real song as scenes and boundary transitions timed from real beat intervals. The shared <code>runtime/scene-director.js</code> turns both into one seek-safe state function: every boundary moves through approach, cross, and settle envelopes, family identity carries the composition across the change, and only the boundary impulse may be discontinuous. A variant (<code>A′</code>) keeps its family's identity with two bounded secondary changes, and <code>BREAK</code> uses a reserved neutral suspended treatment. The player exposes this through a Follow structure toggle (hidden until artifacts exist) and an accessible scene summary; beats stay locally reactive inside every scene.

## How music changes the scene

The player does not treat every strong beat as the same event. It compares transient strength and local density inside the current song, then spends a limited visual budget.

| Musical state | Visual response |
| --- | --- |
| Ordinary beat | Coherent body breath, a short local core response, then a restrained belt ripple |
| Continuous strong rhythm | Macro flow and surface travel increase without repeated explosions |
| Locally distinct transient | The three lobes separate briefly and edge streamers carry motion outwards |
| Rare hit or section change | Full body expansion and a delayed three-belt propagation when the cooldown allows it |
| LOW / MID / HIGH | Weight and scale, surface flow, detail and brightness |
| Playback position | One clock for particles, traces, structure, and cue map |

The scene is rendered by a deterministic WebGL2 instrument in one draw call: up to 18,000 body points plus three seeded orbit belts of roughly 690 grains each. Anticipation, impact, recoil, aftershock, the continuous macro flow field, lobe-local halo, streamers, and delayed belt ripples are all computed from playback time — never from wall-clock physics. The belts receive one event at three bounded delays instead of mirroring the body on the same frame. The renderer tracks measured cost in rolling 180-frame windows and moves between three body-quality tiers (18,000 / 11,000 / 6,000 points with device-pixel-ratio caps) only after sustained over- or under-load, with a cooldown between changes. When WebGL2 is unavailable or the context is lost, a Canvas 2D fallback with a fixed 680-point body budget keeps the scene alive, and <code>prefers-reduced-motion</code> switches to the restrained variant live. The structure navigator and cue overlay update less often than the main instrument so they do not compete with recording performance; the audio clock itself is never downsampled.

## How the eight-bar reference works

BeatScope aligns raw transients to a 1/16 or 1/32 grid while keeping the real timestamp, quantised position, and offset. It exposes timing facts rather than asking the user to trust an instrument label:

| Cue | Suggested visual direction |
| --- | --- |
| IMPACT | A short geometry, camera, or composition impulse |
| LOW / SCALE | Size, weight, and depth |
| MID / FLOW | Surface and directional movement |
| HIGH / FLASH | Edge light, fine particles, and brief exposure |
| ACCENT / BLOOM | Rare hero events and global emphasis |

Click a cue to audition its nearby transient. Drag to define a loop range. Selection and dragging do not restart the song.

## Rhythm IR: facts, semantics, and presentation

v0.6 tracks beats and tempo on the real timeline: beats come from novelty-guided tracking (local tempo candidates, a global tempo path, per-beat reconstruction, and piecewise-constant tempo segments), not from a uniform global-BPM grid. v0.7 adds whole-song structure to the same ladder: bar-synchronous harmony, timbre, rhythm, and energy views are aggregated per bar, a multi-scale novelty pass proposes boundaries, and a length-constrained assignment labels repeat families (<code>A</code>, <code>B</code>, ...) with variants (<code>A′</code>) — deterministic, cache-honest, and free of confidence scores. All rhythm data is arranged into three layers, each depending only on the one above it:

1. **Facts**: what the audio directly supports — beat times, transients (with band energy and strength), and multiband energy frames. No guessing happens here.
2. **Semantics**: derived from facts — global BPM and tempo segments, the bar grid, quantised positions, the section overview, the whole-song structural segments and boundaries, and accent cues. Every field can be traced to its source (<code>analysis.provenance</code>) and its computation (<code>analysis.diagnostics</code>).
3. **Presentation**: maps semantics onto a visual budget — the pulse, turbulence, burst, and hero tiers are allocated by <code>runtime/visual-profile.js</code>, and the player is just one of its consumers. Since v0.8 the compiled visual recipe and timeline live beside the project as separate artifacts; the rhythm IR itself stays schema v4 with no presentation data inside.

Project data is written as schema v4 (<code>schema_version: "4.0"</code>) and validated; v3 projects are migrated on load, and the structure block lives in optional <code>patterns.segments</code> fields, so consumers written before v0.7 keep working unchanged. Core output contains no kick, snare, hihat, or 808 identity, and strength is never renamed into confidence — the page shows the backend, pipeline version, and interpretable diagnostics (provenance methods, migration notes, pregrid merge counts, warning counts).

The shared JavaScript runtime <code>beatscope/runtime/runtime.js</code> is dependency-free ESM with no DOM, Audio, Canvas, or wall-clock access; <code>track.at(time)</code> always returns the same result for the same input, and bar/beat phase in variable-tempo material is derived from adjacent real beats and downbeat spans instead of assuming a global BPM. Meter phase itself remains heuristic continuous numbering from the first tracked beat (provenance marks it as inferred), not a dedicated downbeat model. Since v0.7 <code>track.at(time)</code> also carries a <code>structure</code> block — the active segment, its phase, and the seconds to the next boundary — plus <code>structureLead</code> and <code>boundaryImpulse</code> signals, all pure functions of time. Since v0.8 <code>runtime/scene-director.js</code> sits beside it as the scene counterpart under the same purity contract: scene identity and transition envelopes are pure functions of playback time. The web player, the page diagnostics, the export, and the reference consumers are all built on them.

## Measured accuracy

The numbers below are generated by the benchmark harness (<code>beatscope benchmark</code>: synthetic audio with ground truth, 70 ms beat and 50 ms onset tolerance) and match <code>build/benchmark-v06/benchmark-results.md</code>; the command exits non-zero when a hard gate fails:

| Case | BPM error | Beat MAE | Beat F1 | Tempo MAE | Segments | Onset F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-120 | 0.18 BPM | 5.78 ms | 1.00 | 0.18 BPM | 1 | 1.00 |
| fixed-90 | 0.16 BPM | 5.65 ms | 1.00 | 0.12 BPM | 1 | 1.00 |
| dense-128 | 0.16 BPM | 5.07 ms | 1.00 | 0.40 BPM | 1 | 1.00 |
| sparse-100 | 0.20 BPM | 9.83 ms | 1.00 | 0.35 BPM | 1 | 1.00 |
| tempo-change | — | 5.79 ms | 1.00 | 0.25 BPM | 2 | 1.00 |
| offgrid | 0.75 BPM | 29.41 ms | 1.00 | 0.73 BPM | 1 | 1.00 |
| bass-heavy | 0.27 BPM | 3.13 ms | 0.97 | 0.18 BPM | 1 | 0.28 |
| silence | — | — | — | — | 1 | — |
| gradual-drift | — | 5.85 ms | 1.00 | 1.74 BPM | 6 | 1.00 |
| micro-drift | — | 5.69 ms | 1.00 | 1.28 BPM | 1 | 1.00 |
| octave-trap | 0.18 BPM | 6.14 ms | 1.00 | 0.18 BPM | 1 | 1.00 |

Hard gates (commit-blocking): a valid schema, fixed-BPM error ≤ 5 BPM, beat F1 ≥ 0.5, at most 20 false events on silence, plus baseline regression windows for the fixed-tempo cases (beat F1 may not drop more than 0.03 and beat MAE may not worsen more than 15 ms) and declared floors for the variable cases — tempo-change must reach beat F1 ≥ 0.55 with per-segment BPM error ≤ 5 BPM, change-point error ≤ 1 s, and at most one missing or extra beat at the seam; gradual-drift needs beat F1 ≥ 0.65 and tempo MAE ≤ 6 BPM; micro-drift allows no octave errors and at most 3 segments; octave-trap allows no octave errors. All 11 cases currently pass (0 gates failed). The v0.5 → v0.6 change is concentrated where it should be: tempo-change beat F1 went from 0.16 to 1.00 (two segments, segment BPM errors 0.185 / 0.325 BPM, change-point error 0.01 s, seam missing 0 / extra 0) while every fixed-tempo case held its ground. Bass-heavy onset F1 is report-only by design: high-frequency onset recall in a bass-dominated synthetic mix is limited by the fixture itself.

Structure accuracy has its own harness: ten synthetic arrangements (A-B-A, an A-B-A-C-B form with a variant, energy/harmony/rhythm-only changes, a two-bar break, monotony, a sub-four-bar track, a tempo-change repeat, and gradual drift) are gated against frozen truth for boundary precision/recall/F1, repeat-family accuracy, and over/under-segmentation — with the same no-confidence, neutral-letter contract. Run it with <code>beatscope benchmark-structure</code>; the v0.7 acceptance run is written to <code>build/benchmark-v07/</code>.

Visual orchestration is the third harness: <code>beatscope benchmark-visual</code> compiles thirteen frozen scene fixtures and drives them through the real runtime (scene director, motion director, particle geometry, and an inline WebGL2 stub for draw-call counting) via one generated Node process. It enforces 28 blocking gates covering determinism (recipe and timeline bytes, query order, seek, cross-surface parity against the MCP bridge, dense-onset stability), identity (family motif and palette equality, variant stability, the BREAK reservation), timeline coverage and transition timing, motion continuity (composition continuous across boundaries, impulse-only jumps, reduced-motion scaling, the combined spread cap, settle exactness), and performance budgets (scene query p95 under 0.10 ms, director query p95 under 0.35 ms, exactly one draw call per render, an allocation smoke test). A gate whose probe is unavailable — for example when Node is not installed — is reported as <code>unavailable</code>, never silently passed, and 117 golden checkpoint frames are verified on every run.

## The handoff package

~~~text
beatscope-codex.zip
├── beatscope-package.json   # v0.9 self-describing manifest: entry, capabilities, integrity
├── AGENT.md                 # v0.9 routing document written for the consuming Agent
├── consumer-probe.js        # v0.9 dependency-free probe: canonical frames + checkpoint replay
├── SKILL.md
├── references/schema.md
├── rhythm-map.json
├── visual-state.js
├── worker-example.js
├── beatscope-runtime.js
├── scene-director.js
├── visual-recipe.json
├── visual-timeline.json
├── visual-recipe-data.js
├── visual-timeline-data.js
├── BEATSCOPE.md
└── README.md
~~~

<code>visual-state.js</code> keeps <code>getVisualState(time)</code> — the shared runtime's <code>track.at(time)</code> — and, when the package carries compiled visual artifacts, adds <code>getSceneState(time)</code> and a one-call <code>getBeatScopeFrame(time)</code> returning <code>{ timing, scene }</code>. The browser player and the export package use the same <code>beatscope-runtime.js</code> and <code>scene-director.js</code>. <code>worker-example.js</code> runs that API in a module Worker while the main thread keeps ownership of the audio element and sends <code>audio.currentTime</code>. Pause, seek, replay, main-thread use, and Worker use therefore resolve the same instant to the same frame.

v0.9 makes the package self-describing. <code>beatscope-package.json</code> declares the entry module, exported function names, the clock semantics (<code>media-time</code>, <code>[0, duration]</code>), which capabilities the package actually carries, and a sha256 integrity map over every member. <code>AGENT.md</code> is the short routing document a consuming Agent reads first: which file to import, which clock to feed, that re-analysis is never needed, and how to verify with the probe. <code>consumer-probe.js</code> is a dependency-free ESM probe that inspects the package, renders canonical frames, and replays recorded checkpoints — a package either passes it or names what failed.

MIDI, CSV, PNG, and raw JSON remain under **Advanced tools**. MIDI is a quantised timing reference, not a reconstructed drum performance.

## Validating a handoff or a consumer

The base checks are local and network-free. Add the opt-in execution layer that matches the consumer:

~~~powershell
python -m beatscope.cli validate-handoff path\to\package.beatscope --checkpoints checkpoints.json
python -m beatscope.cli validate-consumer examples\canvas-particles
python -m beatscope.cli validate-consumer examples\canvas-particles --browser
python -m beatscope.cli validate-consumer examples\remotion-composition --offline
~~~

<code>validate-handoff</code> checks archive paths, manifest shape, independent hashes, rhythm data, executable bytes against the installed BeatScope templates, checkpoint replay, worker startup, and leakage. Package JavaScript runs only after all four trust gates — path safety, manifest, integrity, and executable-template identity — pass. <code>validate-consumer --browser</code> starts pinned Chromium, loads a synthetic local WAV, and checks play/pause, seek, replay, deterministic frames, reduced-motion timing, console errors, and the frozen debug hook. <code>--offline</code> loads the declared frame adapter and checks repeatability plus 24/30/60fps parity. Exit <code>0</code> means every requested required layer passed; <code>1</code> is a contract failure; <code>2</code> means a required layer was skipped or its tooling is unavailable. Browser tooling is pinned under <code>tests/browser</code> and enforced in CI.

## Cross-Agent evaluation: pending, not claimed

<code>evaluations/agent-interoperability/</code> freezes the evaluation harness: a byte-stable task (the only permitted variation is the target-framework placeholder), a strict metadata-only run recorder (no prompts, credentials, or chain of thought; records hash-pin the task and the package), an eight-category conformance rubric whose weights total 100 with artistic taste scored separately, and a deterministic conformance table — see [the generated table](evaluations/agent-interoperability/conformance.md).

Status, matching the recorded evidence exactly: the three reference consumers pass every automatable required gate, and **zero** independent Coding Agent runs are recorded so far. The claim "validated across Coding Agents" stays **pending** until at least two distinct Coding Agent products complete the frozen task under the publication threshold (fresh-context run, documented repairs, reviewed source, failures kept visible). CI replays the checked-in evidence and never contacts remote Agents.

## Current implementation

- Local audio loading, format checks, and a safe FFmpeg fallback
- One analysis pipeline: beat grid, transients, multiband energy, and whole-song structural segments with repeat families
- Schema v4 validation, v3 project migration, and provenance/diagnostics metadata
- A shared JavaScript runtime: web, export, and consumers query time through one implementation
- A visual recipe compiler (<code>beatscope visual-build</code>): structure becomes family identities, palette slots, and a scene timeline stored beside the project
- A shared scene director (<code>runtime/scene-director.js</code>): structural scenes and boundary envelopes as pure functions of playback time
- A deterministic WebGL2 particle instrument with coherent lobe motion, flow-guided streamers, delayed orbit belts, adaptive quality tiers, and a Canvas 2D fallback
- Canvas 2D frequency traces, light field, and spectrum deck
- Motion tiers derived from within-song distribution and rhythmic density
- Playback, volume, seek, and eight-bar looping
- Whole-song structure navigation with segment jumps and 1/16 or 1/32 cue maps
- The page shows the analysis backend and interpretable diagnostics, never a fake confidence
- A benchmark with accuracy gates that generates the accuracy report
- A visual orchestration benchmark with 28 blocking quality and performance gates (<code>beatscope benchmark-visual</code>)
- A self-describing handoff contract: manifest, AGENT.md routing, and a dependency-free consumer probe in every export
- Handoff and consumer validation commands with honest exit-code semantics (<code>validate-handoff</code>, <code>validate-consumer</code>)
- Three reference consumers of the same package: Canvas 2D (zero-build), Three.js (pinned, import map), Remotion (offline, frame/fps clock)
- A frozen cross-Agent evaluation harness: task, run recorder, rubric, conformance table, replay-only CI
- Codex ZIP, Skill, JSON, CSV, PNG, and reference MIDI exports
- Request-scoped temporary files, a 250 MB upload cap, and local project cache
- Python, plain JavaScript, and GitHub Actions regression checks

## Stack

| Part | Technology |
| --- | --- |
| Analysis | Python, NumPy, SoundFile |
| Optional high-quality path | librosa, Demucs, Beat This |
| Local service | Python HTTP server |
| Playback | HTML Audio, audio.currentTime |
| Visuals | WebGL2 particles, Canvas 2D, vanilla JavaScript, CSS |
| Reference consumers | Canvas 2D, three.js 0.169.0, Remotion 4.0.520 (example-local deps) |
| Exports | JSON, CSV, PNG, Standard MIDI, ZIP handoff package |
| Verification | pytest, Node Test Runner, GitHub Actions |

## Repository structure

~~~text
beatscope/
├── analysis.py             # baseline audio analysis
├── rhythm.py               # fact-based rhythm project
├── beatgrid.py             # beat, quantisation, and offset logic
├── structure.py            # whole-song section overview
├── structure_features.py   # v0.7 bar-synchronous multi-view structure features
├── structure_segments.py   # v0.7 boundaries, repeat families, and variants
├── pipeline.py             # one analysis pipeline, assembles schema v4 projects
├── schema.py               # v4 validator and v3 migration
├── benchmark.py            # synthetic ground-truth benchmark with accuracy gates
├── visual_recipe.py        # v0.8 structure → visual recipe/timeline compiler
├── visual_recipe_schema.py # v0.8 visual artifact validators and canonical bytes
├── visual_benchmark.py     # v0.8 visual orchestration benchmark and gates
├── consumer_contract.py    # v0.9 manifest/AGENT/probe/checkpoint contract rules
├── consumer_validation.py  # v0.9 validate-handoff and validate-consumer engine
├── exports.py              # Codex, CSV, PNG, and MIDI exports
├── server.py               # local upload, project, and media service
├── mcp/                    # MCP server (service, PathPolicy, runtime bridge)
│   └── runtime_worker.mjs  #   Node worker: shared-runtime time queries
├── runtime/                # shared JavaScript runtime (web and export share it)
│   ├── runtime.js          #   track.at / quantize and other time queries
│   ├── scene-director.js   #   v0.8 structural scene and transition state
│   ├── consumer-probe.js   #   v0.9 dependency-free package probe shipped in exports
│   └── visual-profile.js   #   pulse/turbulence/burst/hero visual budget
├── agent_skill/            # portable Skill included in each ZIP
└── web/
    ├── app.js              # page state and interaction
    ├── visual-stage.js     # stage controller: layers, director frames, quality tiers
    ├── particle-geometry.js# deterministic three-lobe body and orbit-belt point sets
    ├── particle-shaders.js # WebGL2 vertex/fragment sources
    ├── particle-field.js   # one-draw-call WebGL2 particle renderer
    ├── renderer.js         # instrument chrome, structure, and cue-map rendering
    ├── audio.js            # single audio clock and transport
    └── index.html
examples/                    # v0.9 reference consumers of one frozen package
├── shared/                 #   fixture.beatscope, checkpoints.json, fixture-lock.json
├── canvas-particles/       #   zero-build Canvas 2D consumer
├── threejs-geometry/       #   three@0.169.0 consumer (example-local deps)
└── remotion-composition/   #   Remotion offline consumer (frame/fps clock)
evaluations/                 # MCP evaluation Q&A and fixed fixture
└── agent-interoperability/ # v0.9 frozen task, run recorder, rubric, reports
tests/                       # Python and JavaScript regression tests
skills/beatscope-visualizer/ # repository Skill
docs/                        # screenshots, demo video, and docs/mcp.md contract
~~~

## Run locally

Python 3.10 or newer is required.

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
beatscope serve
~~~

Open <code>http://127.0.0.1:8765</code> and choose an audio file. WAV, FLAC, and OGG use SoundFile. When the installed libsndfile cannot decode MP3, BeatScope falls back to FFmpeg.

Useful commands:

~~~powershell
beatscope serve
beatscope rhythm song.wav --drums drums.wav --beat-this song.beats --output rhythm.json
beatscope visual-build rhythm.json
beatscope validate-handoff examples\shared\fixture.beatscope --checkpoints examples\shared\checkpoints.json
beatscope validate-consumer examples\canvas-particles
beatscope separate song.wav --output-dir .beatscope-cache\song\stems --model htdemucs --device cuda
beatscope benchmark
beatscope benchmark-visual
beatscope doctor
~~~

To run a reference consumer, serve the repository root statically and open the example's page — for example <code>python -m http.server 8766</code> then <code>http://127.0.0.1:8766/examples/canvas-particles/</code> — and pick an audio file. The Three.js example installs its pinned dependency with <code>npm install</code> first; the Remotion composition renders offline with <code>npx remotion render</code> from its own directory.

## MCP server: let agents use the rhythm facts directly

BeatScope ships a local MCP server (`beatscope_mcp`). MCP clients such as
Codex or Claude Desktop can analyze a local song, query beats, onsets, and
cues in precise time windows, and export the agent handoff ZIP - without
the web page and without reading the source. Timing semantics (bar/beat
phases, energy interpolation, onset impulse, quantisation) are computed by
the same JavaScript runtime the web player and the export package use, so
all paths agree by construction.

Install and start:

~~~powershell
pip install -e ".[mcp]"
beatscope-mcp
~~~

The server speaks stdio; analysis happens locally and no audio or other
data is ever sent over the network.

| Tool | Purpose |
| --- | --- |
| `beatscope_list_projects` | List cached projects (BPM, bars, backend, provenance) |
| `beatscope_get_project` | Read summary / timing / full JSON; structure summaries include per-segment mean LOW / MID / HIGH energy |
| `beatscope_analyze_audio` | Analyze and cache audio; progress and cancellation, multi-config coexistence |
| `beatscope_get_visual_state` | Full visual state at one instant, identical to the web player; with compiled artifacts the response adds the `visual` block (scene, transition, composition) |
| `beatscope_get_events` | beats / onsets / cues / patterns / segments / boundaries / scenes in a (start, end] window |
| `beatscope_export_package` | Export the portable agent ZIP (atomic write, SKILL and schema included) |

Compiled visual artifacts live beside the project (<code>visual-recipe.json</code>, <code>visual-timeline.json</code>), the local web API serves them under the same names, and <code>beatscope_get_project</code> reports which artifacts exist.

Security model: every input and output path must live inside the
`BEATSCOPE_ALLOWED_ROOTS` allowlist (default: the current directory);
anything else is rejected up front. Export destinations must end in `.zip`.

Codex CLI (`~/.codex/config.toml`):

~~~toml
[mcp_servers.beatscope]
command = "C:\\src\\beatscope\\.venv\\Scripts\\beatscope-mcp.exe"

[mcp_servers.beatscope.env]
BEATSCOPE_ALLOWED_ROOTS = "C:\\Users\\me\\Music;D:\\work\\videos"
~~~

Claude Desktop (`claude_desktop_config.json`):

~~~json
{
  "mcpServers": {
    "beatscope": {
      "command": "C:\\src\\beatscope\\.venv\\Scripts\\beatscope-mcp.exe",
      "env": { "BEATSCOPE_ALLOWED_ROOTS": "C:\\Users\\me\\Music" }
    }
  }
}
~~~

Semantics statement: the MCP surface exposes transient and band facts only;
it does not identify kick, snare, hi hat, or 808. The server's instructions
repeat this to the agent.

Troubleshooting: "runtime bridge unavailable" → install Node.js 20+ or set
`BEATSCOPE_MCP_NODE` to the node binary; "outside BeatScope's allowed
roots" → add the file's directory to `BEATSCOPE_ALLOWED_ROOTS` and restart;
"does not exist" → check `beatscope_list_projects` first or create the
project with `beatscope_analyze_audio`. The full contract lives in
[docs/mcp.md](docs/mcp.md).

## Optional high-quality path

The built-in analyser is enough to try the player. For a dense mix, install the optional dependencies and provide Beat This timing with a Demucs drums stem:

~~~powershell
pip install -e ".[high-quality]"
beatscope separate "song.wav" --output-dir .beatscope-cache\song\stems --model htdemucs --device cpu
beatscope rhythm "song.wav" --drums drums.wav --beat-this song.beats --output rhythm.json
beatscope serve --project rhythm.json
~~~

When <code>--device cuda</code> is selected, BeatScope does not silently fall back to CPU.

## Verification

~~~powershell
pytest -q
python -m pytest tests\mcp -q
node --test tests\test_grid.js tests\test_interaction.js tests\test_runtime.js tests\test_scene_director.js tests\test_visual_profile.js tests\test_playback_characterization.js tests\test_playback_state.js tests\test_visual_stage.js tests\test_particle_geometry.js tests\test_particle_uniforms.js tests\test_consumer_probe.js tests\test_canvas_consumer.js tests\test_threejs_consumer.js tests\test_remotion_consumer.js
beatscope validate-handoff examples\shared\fixture.beatscope --checkpoints examples\shared\checkpoints.json
beatscope benchmark
beatscope benchmark-structure
beatscope benchmark-visual
~~~

On the JavaScript side the grid and interaction tests cover page behaviour; the runtime, scene-director, and visual profile tests cover the shared runtime contract and purity constraints; the characterisation test compares the web player and the export paths at the same instants; the visual-stage, particle-geometry, and particle-uniform tests pin the deterministic director frames, point-set determinism, and uniform conversion, including the adaptive quality tiers and the forced-fallback paths. The consumer suites pin the packaged probe, and the Canvas, Three.js, and Remotion consumers: declaration honesty, seek determinism, reduced-motion scaling, fps-invariant offline state, and checkpoint parity against the shared fixture. The Python suite additionally asserts that the built wheel ships the probe and particle modules, that every example stays inside its declaration, and that the checked-in evaluation evidence replays byte-identically. The structure tests pin bar-synchronous feature extraction, boundary and family invariants, the optional schema block, runtime segment queries, and MCP/export parity; the structure benchmark gates the ten synthetic arrangements against frozen truth. The visual recipe tests pin compilation, identity, and persistence rules, and the visual benchmark tests pin the gate policy, the motion semantics behind each gate, and byte-identical checkpoint regeneration. The MCP tests cover the tool contract, path safety, runtime parity, and export. GitHub Actions runs the core checks on Windows and Ubuntu with Python 3.10 and 3.12, a pinned consumer-evidence job that validates handoffs and enforces example lockfiles, and a cached Remotion job with a short offline render.

## Known limits

- Results depend on the Coding Agent and the visual brief; BeatScope supplies deterministic musical timing, not finished art direction.
- The v0.9 reference consumers are JavaScript-based; other stacks can consume the package but are not demonstrated here.
- BeatScope does not identify instruments, emotion, lyrics, or semantic song roles. Structural families stay neutral letters (<code>A</code>, <code>B</code>, <code>A′</code>) that mark recurrence, never Verse/Chorus.
- Source audio is not included in exports; the package carries timing facts only.
- The examples prove contract portability, not universal framework support.
- Third-party packages and Agent-generated code must still be reviewed before use.
- The built-in analysis does not reliably identify kick, snare, or 808 identity. It reports transient and frequency evidence.
- The WebGL2 particle instrument renders up to 18,000 body points plus three orbit belts; where WebGL2 is unavailable the Canvas 2D fallback keeps a deliberately small fixed body budget (at most 680 points), so very high-resolution recording still favours a WebGL2-capable browser.
- Whole-song structure detection favours honesty over slicing: gradual evolutions, very short tracks, and unclear repeats can legitimately yield a single segment, and boundaries carry a novelty weight rather than a certainty claim.
- Compiled visual recipes describe structure, not art direction: family motifs and palette slots are neutral, deterministic starting points, a variant stays inside two bounded secondary changes, and <code>BREAK</code> keeps its reserved suspended treatment — the recipe never turns recurrence into a musical role.
- The browser validation layer reports <code>unavailable</code> in this release: interactive play/seek are verified through the Node probe and the example test suites, not yet through an automated in-browser pass.
- MP3 support depends on local libsndfile or FFmpeg.
- BeatScope is a local creative reference, not a DAW, FLP generator, or exact drum transcription tool.

## Project status

BeatScope now covers the complete local path from audio upload to a playable visual, whole-song structure, an eight-bar cue map, MCP queries, and a portable handoff package. v0.6 established real-timeline tempo tracking and the particle instrument; v0.7 added neutral structural segmentation and repeat families; v0.8 compiled that structure into a deterministic visual recipe and scene timeline shared by the player, MCP, and exports; v0.8.1 completed the practical handoff paths (per-segment energy summaries, a tested module Worker adapter). v0.9 turns the export into a self-describing contract — manifest, AGENT routing, dependency-free probe — validated by <code>validate-handoff</code> and <code>validate-consumer</code>, and proves it with three independent reference consumers (Canvas 2D, Three.js, Remotion) driven by one frozen fixture, plus a frozen cross-Agent evaluation harness whose run records are honestly empty so far. The package is versioned 0.9.0 while the audio analyser intentionally remains at 0.7.0 and the visual recipe contract at 0.8.0. BeatScope remains a personal experiment, but its public timing contracts are regression-tested rather than left implicit.

## License

This project is available under the [MIT License](LICENSE).
