# WebMCP Director demo fixtures

Frozen assets for the static WebMCP Director demo (`/?demo=webmcp`,
v0.10 plan section 17). `project.json`, `visual-recipe.json` and
`visual-timeline.json` were produced by a real BeatScope run — never hand
edited — from the audio in this directory:

```text
python scripts/make_webmcp_demo_audio.py demo-src/demo.wav
python -m beatscope.cli analyze demo-src/demo.wav -o demo-src/demo.rhythm.json
python -m beatscope.cli visual-build demo-src/demo.rhythm.json
```

## Audio rights

`audio.mp3` is **original music synthesized by
`scripts/make_webmcp_demo_audio.py`** (deterministic numpy synthesis, no
samples, no third-party material). It is published with this repository
under the repository license and is safe for public demo use.

`fixture-lock.json` pins the SHA-256 of all four files;
`scripts/build_webmcp_demo.py` refuses to build when anything drifts, and
`tests/test_webmcp_demo.py` enforces the same lock. The demo page never
calls the local analysis API: it loads these files and registers the eight
Director tools against them.
