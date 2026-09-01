# Remotion reference composition

The offline-rendering proof (plan section 12): the same handoff package
drives a deterministic Remotion composition where the clock is
`frame / fps` — no `Date.now`, no `performance.now`, no audio element,
no `requestAnimationFrame`.

## What it proves

- Remotion dependencies stay **inside this example**
  (`package.json` + `package-lock.json`, exact pins: `remotion` /
  `@remotion/cli` `4.0.520`, `react` / `react-dom` `19.2.8`); the
  BeatScope core package gains no Remotion or React dependency.
- `src/state.js` is the whole integration: a pure, React-free module
  that turns a media time into one serializable state object using the
  package's `getBeatScopeFrame`. The React tree (`BeatScopeScope.tsx`)
  only renders that object, so rendering frame N twice yields identical
  serialized state before rasterization.
- The clock follows the plan's rule exactly: `time =
  Math.max(0, (frame - startFrame) / fps)`, then
  `getBeatScopeFrame(time)`. The same second maps to the same state at
  24, 30, and 60 fps (pinned by tests).
- Duration derives from the package: `compositionDuration(fps) =
  ceil(30.0001 * fps)`; beyond-duration frames clamp to the final state,
  and start offsets clamp to zero.
- The composition uses **structure for layout**: the owning scene's
  family and composition channels arrange structural blocks, and
  boundary transitions ease them — not just amplitude bars.
- No per-frame JSON scan: the composition imports the package's
  precompiled data modules once through `visual-state.js`.

## Run it

```powershell
cd examples/remotion-composition
npm install
npm run studio        # opens Remotion Studio on the composition
npm run render        # renders out/beatscope.mp4 (needs Chrome, per Remotion)
```

Rendering does not require a BeatScope process: the composition is pure
JavaScript over the frozen package. Supply your own audio track only if
you want sound in the rendered file; the timing comes from the shared
fixture package either way.

## Validate it

```powershell
python -c "from beatscope.cli import main; main(['validate-consumer','examples/remotion-composition','--offline'])"
node tests/test_remotion_consumer.js
```

## Flashing-content responsibility

The reference composition contains no unsafe flashing (bounded
translates, opacity >= 0.55, no full-frame inversions), but authored
variants are the author's responsibility: anyone adapting this
composition must review flashing content before publishing renders.

## Limitations

- `npm run render` needs Chrome/Headless Shell, which Remotion
  downloads on first render; CI rendering is wired by the later v0.9
  commits.
- The visual is deliberately simple: the point is the offline frame
  contract, not art direction.
