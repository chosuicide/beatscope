# Local music-video Studio

The studio's layout skeleton, surface treatment and motion contract are frozen in
[`design/movie-studio.md`](design/movie-studio.md) — read that before changing the screen.

Open `/app/`, upload an audio file, and keep the local BeatScope server running. Analysis unlocks the live preview; **rendering is on demand** — the film is produced only when the user presses `生成视频`, because the preview already shows the same composition for free.

The screen is an editor, not a landing page: a facts rail on the left lists the measured structure (family, bars, time, energy — click to seek), the stage in the middle shows the composition (the **live template** — the same `mv-frame`/`mv-visual`/`mv-plan` code the renderer uses, driven by the audio clock — while the analysis and render run, then the film itself; there is no separate preview toggle), and the inspector rail on the right carries render state (status, progress, elapsed/estimate, output format, cancel/retry), the exports and the template identity. The original cue map is docked underneath full-width: whole-song overview plus the eight-bar subdivision grid with the motion-cue rail, both read-only instruments that follow playback, where a click seeks. Space is the transport plus a one-line flicker warning; there is no marketing copy, no step list and no editor panel. The interface is English by default with an `EN / 中文` switch in the top bar (`web-src/src/movie/copy.ts`).

Rendering is a separate, optional step: after analysis the studio plays the live template and offers one `生成视频` action (progress, elapsed/estimate, cancel, and `重新生成视频` afterwards). The MP4 is the only artifact that step produces.

Exports are split into two independent tracks — data is available as soon as the analysis is done and never depends on a render, while the film exists only after `生成视频`:

- **data**: `数据包 · codex.zip`, which now carries the rhythm `MIDI`/`CSV` inside it as well;
- **film**: `影片 · MP4`, enabled only once a render has completed.

The data track is the Agent handoff, and it is **timing facts only**: `导出包 · codex.zip` carries `rhythm-map.json`, the response-relevance sidecar, the same facts as `rhythm.mid` / `rhythm.csv`, `visual-state.js` plus `beatscope-runtime.js`, `worker-example.js`, `consumer-probe.js`, the agent documents (`AGENT.md`, `BEATSCOPE.md`, `SKILL.md`, `references/schema.md`), the MIT `LICENSE`, and the self-describing manifest with per-member hashes. It deliberately ships **no visual layer** — no recipe, no scene timeline, no scene surface, no task statement — because the visual is the consumer's decision: a package that pre-decides it stops the agent from asking the user what they want. The studio adds only the film itself (`影片 · MP4`, once rendered).

The current built-in procedural voxel material group is the only enabled template; a saved random seed rotates compatible background ordering. There is no style or material picker.

The template draws its backgrounds from a fixed set of sixteen procedural worlds (paper ink, circuit, red circuit, sky, datamosh, magenta, mono blocks, stripes, scan green, green flat, rainbow glitch, halftone print, CRT phosphor, blueprint, ink wash, data rain). Each musical family owns a rotation of them, so a repeated section returns to the same material while the cut palette keeps moving; sections the analysis reports beyond the three named families cycle the full set with a per-family offset. Version `voxel-phrase-2` added the last five.

The current prototype supports audio up to 10 minutes and exports the complete track at 1080×1080 / 30 fps. Offline rendering can take longer than playback; on the reference machine it renders at roughly **3.5× real time** through the in-page encoder, so a 2–4 minute track takes about 35–70 s (a 128.8 s track: 36 s). This is a local service, not a static Pages feature. High-contrast cuts/local flicker remain; it is not photosensitive-safe. Playback is never automatic.

## Encoding path

The worker renders the film through **in-page WebCodecs encoding** by default: each rendered canvas frame goes straight into a `VideoEncoder` (H.264, Annex B) and FFmpeg only muxes the compressed stream with the audio (`-c:v copy`), so no screenshot ever crosses the process boundary. That removes the per-frame PNG encode/decode round trip: on the reference machine a full 128.8 s track drops from 120 s to **36 s** (the in-page encoder is deliberately single-page — each page owns an independent H.264 stream — while the screenshot path gets three parallel capture pages, so short clips show a smaller gap: 6 s clip, 4.0 s vs 12.1 s). Both paths pin and tag BT.709.

- `BEATSCOPE_MV_ENCODER=png` forces the screenshot + FFmpeg encode path; a browser without WebCodecs falls back to it automatically, and the fallback is reported in the job's completion line and console output.
- `BEATSCOPE_MV_BITRATE` (default 8000000) sets the in-page encoder's target bitrate.
- Determinism: two runs with the in-page encoder produce **byte-identical** files (verified); frame content was already pixel-identical across pages, repeats and call histories.
- The two paths measure as equivalent and are exactly frame-aligned. Read the canvas back as ground truth and the screenshot path sits ≈26.4 dB from it against ≈25.8 dB for the in-page path, while the two films agree with *each other* at 28–30 dB on the same frame; a lag sweep settles the alignment (matching frame N against N±1 collapses to ≈19 dB, the clip's own frame-to-frame baseline). The residual against the canvas is dominated by the shared YUV 4:2:0 conversion on this highly chromatic content, not by the capture method. `scripts/movie-bench/ab-probe.mjs` regenerates the sheet in `build/ab-compare.png` (canvas | screenshot path | in-page path).

## Performance

Measured on the reference machine over real template frames (1080×1080):

| Stage | Cost | Note |
|---|---|---|
| `renderAt` (the WebGL composition) | 0.7 ms/frame | the GPU work is essentially free |
| In-page path, end to end | **9.3 ms/frame** | render + `VideoEncoder` + mux into FFmpeg stdin (single page, 36 s for 3864 frames) |
| Frame capture, 1 page | 27.7 ms/frame | CDP `Page.captureScreenshot` PNG with `optimizeForSpeed` — lossless |
| Frame capture, 3 pages | 17.5 ms/frame | several pages render and grab frames in parallel, chunk by chunk |
| x264 `slower` CRF 20 `-tune film` | 21 ms/frame | runs in parallel with capture |

On the fallback screenshot path capture and encoding run at the same time, so a track renders at roughly **32 frames per second** end to end (a 128.8 s track: 120 s, 132 MB, about 1.0 MB per second of video); the in-page path does the same track in 36 s at a similar size. Capture is pixel-identical to the single-page path by construction — every frame is a pure function of its media time, and a probe confirms the same PNG bytes across pages, repeats and different call histories. On the fallback path the H.264 bitstream is *not* byte-identical run to run (threaded rate control reacts to CPU contention); two runs of the same job measure ≈43 dB PSNR against each other, i.e. codec noise rather than a picture difference. The in-page encoder is byte-identical run to run.

Quality is preserved by construction on the capture side and measured on the encode side: the encoder output sits ≈41 dB PSNR against the lossless frames at CRF 20 (≈42 dB at CRF 18), and AV1/HEVC and the hardware encoders were measured and rejected — SVT-AV1 p8 was 30% larger at the same quality on this content, NVENC needs a newer driver than this machine has, and QSV was slower and larger.

Tunable through the environment (defaults in parentheses): `BEATSCOPE_MV_ENCODER` (`webcodecs`), `BEATSCOPE_MV_BITRATE` (8000000), `BEATSCOPE_MV_PAGES` (3), `BEATSCOPE_MV_PRESET` (`slower`), `BEATSCOPE_MV_CRF` (20). Lowering the preset to `medium` buys ~25% more speed for ~15% more bytes; raising CRF to 22 cuts another ~18% of bytes at ~2.4 dB PSNR. The probes that measured them are committed under `scripts/movie-bench/`: `mv-perf-bench.mjs`, `mv-capture-bench.mjs`, `mv-encoder-bench.mjs`, `mv-parallel-bench.mjs`, `mv-determinism-probe.mjs`, `mv-history-probe.mjs` and `ab-probe.mjs`. Each takes a rendered job directory (the cache directory of a finished movie job) and writes its table to stdout.

## Renderer setup

Node, FFmpeg, Playwright and a compatible installed browser are required. Put installations on the user's chosen tools/project disk. The renderer looks for Playwright in the portable build's `tools/` first, then in `tests/browser/node_modules` (where `tests/browser/package.json` declares it) and `web-src/node_modules`; an explicit path always wins:

```powershell
$env:BEATSCOPE_PLAYWRIGHT_MODULE='D:/Tools/your-playwright-install/node_modules/playwright/index.mjs'
$env:BEATSCOPE_BROWSER_CHANNEL='msedge'
rtk python -m beatscope.cli serve --port 8776
```

FFmpeg is resolved from PATH or `BEATSCOPE_FFMPEG`. On Windows the default browser channel is `msedge`; elsewhere it is `chromium` (Playwright's browser must be installed). Missing tools produce a visible setup message; no dummy movie is returned. These optional render dependencies are not silently installed by the Python package.

## API

- `GET /api/movies/capabilities`: tool availability (does not prove GPU/browser launch works).
- `POST /api/movies` with `{ "project_id": "…" }`: one active local task; repeated submit of the same active project returns its task.
- `GET /api/movies/<id>`: persisted status and progress.
- `POST /api/movies/<id>/cancel`: cooperative stop.
- `GET /api/movies/<id>/video`: completed MP4, with Range support; `?download=1` downloads it.

Task directories under `.beatscope-cache/movies/` contain source-analysis snapshots, a seed, the cut plan, logs and final MP4. They are local and are not part of the Agent export. They are retained for diagnosis/replay and currently have no automatic retention policy. One task runs at a time. A server restart marks unfinished saved jobs as failed; there is no distributed queue or resumable rendering.

The existing analysis engine, relevance model and export contracts are unchanged. The template uses the approved consumer-side anchor/support policy, not a fixed every-two-beat grid. Thresholds and response spacing are artistic choices, not musical facts or confidence. Unsupported/missing ranking fails honestly. No new musical timestamps are invented. FFmpeg trims/muxes audio and encodes frames; no external-footage preprocessing is exercised by this procedural template.

The studio is the only page the server serves. The canvas workspace, the composition workbench and the old studio page (`/legacy.html`) were retired together with the compiled visual layer they were built on, so `/app/?canvas=1` and `/app/?composition=1` no longer resolve to anything.

The studio under `beatscope/web/app` is build output and is not tracked: run
`npm run build --prefix web-src` before packaging or before serving a checkout,
otherwise the wheel and the portable app ship without a page.
