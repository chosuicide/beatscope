# Three.js reference consumer — seeded shell geometry

The realtime-external-engine proof (plan section 11): the same handoff
package that drives the Canvas example drives a Three.js point cloud
through one thin mapping module, with no BeatScope player code and no
re-analysis of audio.

## What it proves

- Three.js is pinned **inside this example only** (`package.json` +
  `package-lock.json`, exact version `0.169.0`); the BeatScope core
  package gains no Three.js dependency.
- `src/beatscope-mapping.js` is the whole integration: a pure,
  Three-free function from frame to scene properties (scale, twist,
  transition cross, camera phase, family colour, opacity). It contains
  no beat mathematics — all timing facts come from the package frame.
- Every transform derives from the current media time and frame, never
  from accumulated deltas: rotation is `time * 0.08 + composition twist`,
  scale is `1 + timing.low * 0.25 (+ accent pulse)`, the camera breathes
  on `sin(time * 0.08 * 0.7)`. Direct seek and sequential playback land
  on identical geometry.
- Geometry is seeded (`src/seeded-geometry.js`, golden-angle spiral plus
  deterministic hashes) — reproducible everywhere, no `Math.random`.
- No analyser node, FFT, or beat detection exists anywhere in the
  example; the package is the only musical brain.
- WebGL context loss shows an honest fallback message instead of a
  frozen frame; reduced motion scales displacement amplitudes only.
- The debug hook `window.__BEATSCOPE_CONSUMER__` follows the shared
  contract, and `diagnostics()` reports `drawCalls` against the
  declaration's `draw_call_budget`.

## Run it

```powershell
cd examples/threejs-geometry
npm install            # installs the pinned three@0.169.0
npm start              # serves the repository root on 127.0.0.1:8766
# open http://127.0.0.1:8766/examples/threejs-geometry/
```

A build step is not required: an import map resolves `three` straight
from `node_modules`. Choose a local audio file and press Play (no
autoplay with sound); timing comes from the shared fixture package.

## Validate it

```powershell
python -c "from beatscope.cli import main; main(['validate-consumer','examples/threejs-geometry'])"
node tests/test_threejs_consumer.js
```

The Node test pins checkpoint parity through the package's own probe,
mapping purity, seek-vs-sequential transform equality, seeded geometry
reproducibility, and the declaration's draw-call budget.

## Limitations

- Rendering a real frame needs a WebGL browser; Node tests cover the
  mapping and geometry layers, and the browser layer of
  `validate-consumer` covers interactive behaviour where wired.
- The mapping is an example, not an official Three.js SDK.
