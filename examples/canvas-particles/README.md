# Canvas reference consumer — planar particle field

The zero-build proof of the v0.9 interoperability contract: one BeatScope
handoff package drives an original Canvas 2D visual with no BeatScope
player code, no build system, and no re-analysis of audio.

## What it proves

- The handoff package is the **only** musical timing source. `app.js`
  imports `getBeatScopeFrame` from `../shared/fixture.beatscope/` and
  never touches `rhythm-map.json` directly.
- `audio.currentTime` is the **only** clock. The one
  `requestAnimationFrame` loop reads the current media time and repaints;
  there is no wall-clock timing and no accumulated frame state, so
  pause, seek, replay, and single-frame rendering are exact by
  construction.
- The geometry (`visual-field.js`) is a pure function of particle
  identity plus the current frame: deterministic per-particle hashes
  replace `Math.random()`, and resize changes rendering only.
- Reduced motion (checkbox, defaulting to the OS setting) scales
  displacement only; timing state is unchanged.
- The consumer declares itself in `beatscope-consumer.json`
  (`beatscope-consumer-1`) and exposes the frozen debug hook
  `window.__BEATSCOPE_CONSUMER__` (`frameAt`, `seek`, `pause`,
  `resume`, `diagnostics`) for automated browser validation.

The visual is an authored **planar particle field** — receding rows with
flow curvature, sparkle, and boundary palette easing — deliberately not a
copy of BeatScope's radial three-lobe player.

## Run it

Serve the repository root with any static server (ES module imports need
HTTP; opening `index.html` via `file://` will not work):

```powershell
python -m http.server 8765
# then open http://127.0.0.1:8765/examples/canvas-particles/
```

Choose any local audio file with the file picker. Playback stays paused
until you press Play (no autoplay with sound). The timing comes from the
fixture package, so any audio file acts as a transport of the right
roughly-30-second length; the shared fixture's own synthetic audio is
regenerable from the test suite and never ships in Git.

## Validate it

```powershell
python -c "from beatscope.cli import main; main(['validate-consumer','examples/canvas-particles'])"
```

The base command validates the declaration, handoff package, checkpoints,
worker, leakage, and static source hygiene. Add `--browser` to launch the
pinned Chromium probe and exercise real audio loading, play/pause, seek,
replay, reduced motion, deterministic frames, and console cleanliness.

Node-side checkpoint parity for this consumer's geometry lives in
`tests/test_canvas_consumer.js` (`node --test tests/test_canvas_consumer.js`).

## Accessibility (plan section 17)

- Semantic Play/Pause button and a keyboard-operable range-input seek;
- visible `:focus-visible` outlines everywhere;
- elapsed / total time text, tabular numerals;
- reduced-motion toggle that takes effect live;
- canvas fallback text and an accessible description of the visual;
- no autoplay with sound, no full-screen flashing;
- the audio filename is shown in the options bar only, never as the
  visual subject.

## Limitations

- The example consumes the frozen shared fixture package; point
  `package_path` at your own export to reuse the visual.
- Rendering quality is intentionally plain: the point is the timing
  contract, not art direction.
- `frameAt(time)` evaluates the package directly, so automated checks
  can compare it against the shipped checkpoints bit for bit.
