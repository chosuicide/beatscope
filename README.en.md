# BeatScope

[简体中文](README.md) | English

A local personal project that turns a song's rhythm into a playable visual reference and a reusable timing package for coding agents.

BeatScope lets you upload a track, play it in the browser, and watch a particle sphere, frequency traces, and a whole-song structure view respond to LOW, MID, HIGH, transients, and section changes. The same analysis is arranged into an eight-bar cue map and exported as a Codex package with its own <code>SKILL.md</code>, so the next visual project does not have to guess the timing of the same song again.

[![BeatScope animated preview; click to play with sound](docs/demo/beatscope-preview.gif)](docs/demo/beatscope-demo.mp4)

**Click the animation to play the 10-second demo with sound.**

> BeatScope reports rhythm strength, frequency distribution, and timing structure. It does not present uncertain transients as kicks, snares, or 808s. Audio is analysed locally and request-scoped temporary files are removed after processing.

## Why I built it

The difficult part of music visualisation is usually not drawing a shape that moves. It is deciding why it should move at this exact moment, how far it should move, and how the same animation should behave when two songs have completely different rhythmic density.

A direct peak-to-explosion mapping works for sparse music and quickly falls apart on a dense track. Looking only at total volume loses low-frequency weight, high-frequency detail, and section changes. Handing the same song to another agent later also means repeating those decisions from the beginning.

BeatScope keeps that work. Python reads the audio, builds the beat grid, and extracts multiband energy. The browser uses <code>audio.currentTime</code> as its only clock. The particle system separates ordinary pulse, sustained turbulence, local impact, and rare hero events. The result can be watched directly or reused as timing evidence in the next creative build.

## What one session looks like

~~~text
Upload local audio → build beats and multiband energy
                   → move into the Signal player
                   → play, seek, and inspect whole-song structure
                   → audition or loop an eight-bar cue range
                   → export a Codex package for the next visual project
~~~

1. Choose a WAV, FLAC, MP3, OGG, or M4A file.
2. The local service derives beats, transients, LOW / MID / HIGH energy, and a structural overview.
3. The page moves into the player, where the particle sphere, traces, and spectrum follow playback.
4. The rhythm pattern overview provides a whole-song view and direct navigation.
5. The eight-bar cue map translates the current window into impact, scale, flow, flash, and bloom references.
6. The Codex export preserves the analysis, a deterministic visual-state function, instructions, and a portable Skill.

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

This navigator compresses the complete track into sections, LOW / MID / HIGH energy traces, and transient density. Clicking a bar seeks directly to it. The red frame always marks the eight bars currently shown in the cue map, so changes do not have to be found by scrubbing blindly through one long timeline.

### Eight-bar cue map: turn listening into usable timing

![BeatScope eight-bar motion cue map](docs/screenshots/beatscope-cue-map.png)

The same eight-bar window exposes IMPACT, LOW / SCALE, MID / FLOW, HIGH / FLASH, and ACCENT / BLOOM. This is not a drum transcription; it is a motion-oriented reference. A transient can be auditioned with one click, a loop can be dragged out, and the resulting timing, strength, and band drivers can be passed into the next visual build.

### Export for Codex: carry the analysis forward

![BeatScope Codex export panel](docs/screenshots/beatscope-codex-export.png)

The package contains more than analysis JSON. It also carries a seek-safe <code>visual-state.js</code>, usage notes, the schema, and a project-level <code>SKILL.md</code>. Drop the ZIP into a new Codex project and the agent can reuse the same timing and visual semantics instead of listening and guessing again.

## How music changes the scene

The player does not treat every strong beat as the same event. It compares transient strength and local density inside the current song, then spends a limited visual budget.

| Musical state | Visual response |
| --- | --- |
| Ordinary beat | Small sphere breath and short core response |
| Continuous strong rhythm | More surface motion and turbulence, without repeated explosions |
| Locally distinct transient | Limited particle separation and a short impact |
| Rare hit or section change | Full expansion when the cooldown allows it |
| LOW / MID / HIGH | Weight and scale, surface flow, detail and brightness |
| Playback position | One clock for particles, traces, structure, and cue map |

Particle count adapts to the measured render cost of a frame. The structure navigator and cue overlay update less often than the main instrument so they do not compete with recording performance; the audio clock itself is never downsampled.

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

v0.4 arranges all rhythm data into three layers, each depending only on the one above it:

1. **Facts**: what the audio directly supports — beat times, transients (with band energy and strength), and multiband energy frames. No guessing happens here.
2. **Semantics**: derived from facts — global BPM and tempo segments, the bar grid, quantised positions, the section overview, and accent cues. Every field can be traced to its source (<code>analysis.provenance</code>) and its computation (<code>analysis.diagnostics</code>).
3. **Presentation**: maps semantics onto a visual budget — the pulse, turbulence, burst, and hero tiers are allocated by <code>runtime/visual-profile.js</code>, and the player is just one of its consumers.

Project data is written as schema v4 (<code>schema_version: "4.0"</code>) and validated; v3 projects are migrated on load. Core output contains no kick, snare, hihat, or 808 identity, and strength is never renamed into confidence — the page shows the backend, pipeline version, and interpretable diagnostics (provenance methods, migration notes, pregrid merge counts, warning counts).

The shared JavaScript runtime <code>beatscope/runtime/runtime.js</code> is dependency-free ESM with no DOM, Audio, Canvas, or wall-clock access; <code>track.at(time)</code> always returns the same result for the same input, and bar/beat phase in variable-tempo material is derived from adjacent real beats and downbeat spans instead of assuming a global BPM. The web player, the page diagnostics, and the Codex export are all built on it.

## Measured accuracy

The numbers below are generated by the benchmark harness (<code>beatscope benchmark</code>: synthetic audio with ground truth, 70 ms beat and 50 ms onset tolerance) and match <code>build/benchmark/benchmark-results.md</code>; the command exits non-zero when a hard gate fails:

| Case | BPM error | Beat MAE | Beat F1 | Onset F1 |
| --- | ---: | ---: | ---: | ---: |
| fixed-120 | 0.19 BPM | 3.17 ms | 0.97 | 1.00 |
| fixed-90 | 0.12 BPM | 10.70 ms | 1.00 | 1.00 |
| dense-128 | 0.40 BPM | 18.29 ms | 1.00 | 1.00 |
| sparse-100 | 0.35 BPM | 9.39 ms | 1.00 | 1.00 |
| tempo-change | — | 35.20 ms | 0.16 | 1.00 |
| offgrid | 0.19 BPM | 17.29 ms | 1.00 | 1.00 |
| bass-heavy | 0.19 BPM | 3.17 ms | 0.97 | 0.27 |
| silence | — | — | 0.00 | — |

Hard gates (commit-blocking): a valid schema, fixed-BPM error ≤ 5 BPM, beat F1 ≥ 0.5, at most 20 false events on silence, and no more than 0.15 beat-F1 regression against the baseline — all 8 cases currently pass (0 gates failed). Tempo-change beat F1 and bass-heavy onset F1 are report-only by design: measuring variable tempo with one global segment is inherently unfair, and high-frequency onset recall in a bass-dominated synthetic mix is limited by the fixture itself. The report carries the more meaningful measurements for those cases (segment BPM errors 19.67 / 0.33 BPM, quantisation offsets 33.12 ms / 2.97 ms).

## The Codex package

~~~text
beatscope-codex.zip
├── SKILL.md
├── references/schema.md
├── rhythm-map.json
├── visual-state.js
├── beatscope-runtime.js
├── BEATSCOPE.md
└── README.md
~~~

<code>visual-state.js</code> does one thing: <code>getVisualState(time)</code> is the shared runtime's <code>track.at(time)</code>. The browser player and the export package use the same <code>beatscope-runtime.js</code>, so the state an agent consumes is produced by the same implementation the player shows. An agent can read beat phase, band energy, transient impulses, and sections without analysing the audio again, and the scene recovers from pause, seek, or replay using the same playback time.

MIDI, CSV, PNG, and raw JSON remain under **Advanced tools**. MIDI is a quantised timing reference, not a reconstructed drum performance.

## Current implementation

- Local audio loading, format checks, and a safe FFmpeg fallback
- One analysis pipeline: beat grid, transients, multiband energy, and whole-song structure
- Schema v4 validation, v3 project migration, and provenance/diagnostics metadata
- A shared JavaScript runtime: web and export query time through one implementation
- Canvas 2D particle sphere, frequency traces, light field, and spectrum deck
- Motion tiers derived from within-song distribution and rhythmic density
- Playback, volume, seek, and eight-bar looping
- Whole-song structure navigation and 1/16 or 1/32 cue maps
- The page shows the analysis backend and interpretable diagnostics, never a fake confidence
- A benchmark with accuracy gates that generates the accuracy report
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
| Visuals | Canvas 2D, vanilla JavaScript, CSS |
| Exports | JSON, CSV, PNG, Standard MIDI, ZIP Skill package |
| Verification | pytest, Node Test Runner, GitHub Actions |

## Repository structure

~~~text
beatscope/
├── analysis.py             # baseline audio analysis
├── rhythm.py               # fact-based rhythm project
├── beatgrid.py             # beat, quantisation, and offset logic
├── structure.py            # whole-song section overview
├── pipeline.py             # one analysis pipeline, assembles schema v4 projects
├── schema.py               # v4 validator and v3 migration
├── benchmark.py            # synthetic ground-truth benchmark with accuracy gates
├── exports.py              # Codex, CSV, PNG, and MIDI exports
├── server.py               # local upload, project, and media service
├── runtime/                # shared JavaScript runtime (web and export share it)
│   ├── runtime.js          #   track.at / quantize and other time queries
│   └── visual-profile.js   #   pulse/turbulence/burst/hero visual budget
├── agent_skill/            # portable Skill included in each ZIP
└── web/
    ├── renderer.js         # player, structure, and cue-map rendering
    ├── audio.js            # single audio clock and transport
    ├── app.js              # page state and interaction
    └── index.html
skills/beatscope-visualizer/ # repository Skill
tests/                       # Python and JavaScript regression tests
docs/                        # README images and demo video
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
beatscope separate song.wav --output-dir .beatscope-cache\song\stems --model htdemucs --device cuda
beatscope benchmark
beatscope doctor
~~~

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
node --test tests\test_grid.js tests\test_interaction.js
node --test tests\test_runtime.js tests\test_visual_profile.js tests\test_playback_characterization.js
beatscope benchmark
~~~

On the JavaScript side the grid and interaction tests cover page behaviour; the runtime and visual profile tests cover the shared runtime contract and purity constraints; the characterisation test compares the web player and the Codex export paths at the same instants. GitHub Actions runs the core checks on Windows and Ubuntu with Python 3.10 and 3.12.

## Known limits

- The built-in analysis does not reliably identify kick, snare, or 808 identity. It reports transient and frequency evidence.
- Canvas 2D particles are still limited by browser and GPU performance during high-resolution recording. WebGL is the next step for consistently high frame rates.
- Automatic section labels describe energy and repetition, not human arrangement notation.
- MP3 support depends on local libsndfile or FFmpeg.
- BeatScope is a local creative reference, not a DAW, FLP generator, or exact drum transcription tool.

## Project status

BeatScope now covers the complete local path from audio upload and playable visualisation to whole-song structure, an eight-bar cue map, and a Codex Skill export. It remains a personal experiment in progress. The next priority is not adding more file formats, but keeping the same visual language stable across more songs, devices, and recording conditions.

## License

This project is available under the [MIT License](LICENSE).
