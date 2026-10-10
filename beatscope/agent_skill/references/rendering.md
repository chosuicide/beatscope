# Render and inspect an existing scene

Queries and score checks need Node 22+ only. Rendering needs FFmpeg/FFprobe;
browser scenes also need Playwright and an installed browser. PNG sequences use
`--frames-dir` without either (see below). `--playwright MODULE` selects an
existing module; `--browser msedge` selects installed Edge. Alternatively
`--executable /path/to/chromium` selects a local Chromium executable, including
one provided by an ARM environment. Choose executable or channel, not both.
The tools never
download dependencies. BEATSCOPE_FFMPEG and BEATSCOPE_FFPROBE can name executables.

## Small renderer adapter
Expose the existing scene's seek-safe frame function, without replacing its style:

```js
window.beatscopeRender = {
  duration: music.RHYTHM_MAP.duration,
  selector: '#frame',                 // exactly one element
  ready: assetsReady,                  // Promise or omitted
  resize(w, h) { canvas.width=w; canvas.height=h; },
  async renderAt(songSeconds) { draw(edit.at(songSeconds)); },
  dispose() { releaseResources(); }    // optional
};
```

Await decoded images, video seeks and GPU completion inside renderAt. Do not use
wall-clock animation or arbitrary sleeps. The selected element must fill the
requested width/height. Immediately after resize the driver measures the element;
a fixed 1280×720 scene requested at 3840×2160 fails before encoding, with both
sizes in the error. Each captured PNG is also checked for mid-render size changes.
Sources and their package imports must be inside the
explicit HTTP `--root`; symlinks are refused when collecting the source snapshot.

```sh
node render.mjs --entry ../scene.html --root .. --audio ../song.mp3 --out ../sample.mp4 --start 16.5 --seconds 3 --width 1080 --height 1920 --memory-mb 512 --chunk-frames 60
```

## Resume and workload
Rerun the exact command with `--resume`. Complete segments are retained next to
the output in `.render-*`; reuse checks settings, included files in the explicit root,
original audio, tool hashes and each segment's hash/dimensions/frame count. Changed
inputs refuse resume. Rerun without --resume for changed work. Choose a narrow
project root; outputs should live outside it. Do not modify files during a render.
Concurrent renders of the same output are locked. Interrupted partial segments
are rerendered; completed segments survive. No automatic source deletion occurs.

One PNG is in flight and FFmpeg uses one encoder thread. By default the browser
and loaded scene are reused, with recycling after ten rendered segments:
`--browser-restart-every 10`. Use `1` for a fresh browser each segment when a
scene cannot yet seek deterministically. The scene must not accumulate animation
state; reuse does not make a stateful renderer seek-safe. There is no parallel jobs mode.
`--memory-mb` is a **soft working budget**, not an OS/GPU cap:
it limits V8 heap and rejects oversized frame buffers, but scene assets and browser
native allocations can exceed it. Lower dimensions/chunk length or simplify the
scene if memory is scarce. GPU-heavy scenes still need their own optimizations.
## Disk and source snapshot
Segments are muxed directly into the final audio/video output, without a full-size
joined.mp4. Failed temporary mux output is removed; complete segments remain usable.
`--clean` removes the driver's own checkpoints/segments after successful export,
keeping the playable result and its report. Interrupted exports retain completed
segments even with --clean. Cleanup never deletes sources or the input frame directory.
A free-space preflight estimates segments plus final output and margin. CRF output
depends on content, so this estimate cannot guarantee that a disk will never fill.

Use repeated root-relative paths: `--exclude generated-frames --exclude scratch`.
Paths are files or directories, not globs; exclusions are recorded in the report
and fingerprint. An included source tree over 50MiB emits a warning before hashing.
Excluded files cannot be served as renderer dependencies: remove an exclusion if
the scene needs it. This prevents changed excluded assets silently reusing stale
frames. Put final outputs outside the scene root whenever possible.

## Transcoded audio
Exact source SHA-256 is preferred. If the package refers to a WAV and your render
uses its MP3 copy, provide the matching original for comparison:

```sh
node render.mjs --entry ../scene.html --root .. --audio ../song.mp3 --reference-audio ../original.wav --out ../sample.mp4
```

The reference must match the package's source hash. The driver checks duration and
distributed beginning/middle/end decoded waveform and 10ms envelope samples;
silence alone cannot establish a match. Accepted copies report
`audioIdentity: transcoded-match`, comparison metrics and original/reference hashes.
This is an inference, not byte identity; no audio timeline offset is applied.
Changed edits, excessive shifts and unrelated songs are refused. Timing facts stay
untouched. Without a verified original, hash mismatch still needs a reference;
the package contains no source audio to decode. Tutorials use separate synthetic sound.

## Frames from another renderer
No browser or Playwright is needed for an existing PNG sequence:

```sh
node render.mjs --frames-dir ../frames --frame-pattern frame-%06d.png --frame-start 0 --audio ../song.mp3 --out ../sample.mp4 --start 16.5 --seconds 3 --width 1280 --height 720
```

Frame start defaults to zero; --start is song/audio time, not the image number.
Only the requested contiguous frames are hashed and checked for missing files
and dimensions before encoding. Unused frames are not scanned. This shares the
same segmented encode, resume, audio mux and report. A changed selected frame
invalidates resume. --clean leaves all input PNGs untouched. Input is a local PNG
filename pattern with one %d/%0Nd placeholder; no glob or subdirectory pattern.
--root and --exclude apply to browser scenes; they are unnecessary in frame mode.

## Synchronization diagnostics
Add optional `sync` declarations to a job score:

```json
{"sync":[{"at":16.5,"cueId":"u:chosen","kind":"impact"}]}
```

Use an actual resolved cue id/time; `kind:"cut"` also requires a compiled cut.
`node verify.mjs --score ../score.json --video ../sample.mp4 --start 16.5`
reports authored offsets, deleted/missing bindings, first sampled frame and coarse
grayscale change peaks. The render report binds audio hash, offset and video bytes;
verified transcoded matches retain their comparison method and reference identity.
Without that report, start is supplied by the caller; audio identity is unverified.
Unbound cuts get nearest-cue offsets but are not required to coincide with an accent.
Subtle motion, fades and half-cover transitions may produce no peak: that is
**unverified**, not a failed aesthetic test. Detected changes may be subject motion.
Neither tool proves the detected tempo is musically correct.

Tutorials: `node render.mjs --example accent --demo-audio --out ../accent.mp4`
and `node verify.mjs --example accent --video ../accent.mp4`. Their sound is
synthetic teaching material, distinct from the original song.
