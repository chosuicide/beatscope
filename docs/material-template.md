# Beathi movie templates

v0.15.0 provides two choices: **Voxel Interference / 体素干扰** and **Prismatic Echo / 棱镜残像**. Both render the whole song at 1080×1080, 30 fps. The live preview uses 540×540.

## Prismatic Echo

The accepted template combines grey, blue and red footage with mirrored seams, kaleidoscopes, inward motion, upright droplet-derived crops, contour echoes and sparse moving negative windows. Photographs are short inserts with motion; long passages return to moving footage. The pack contains 28 videos and 23 photographs. Each render chooses suitable sources instead of forcing every asset into every song.

Authors, source pages, licenses, dimensions and SHA-256 are in `beatscope/web/material-library.json`. Media use the Pexels license, separately from the code's MIT license. Reference clips and demo music are not included in the material pack.

## Install the materials

The Windows portable release contains `materials/` beside the executable. For a Python or source install, download `Beathi-Materials-v0.15.0.zip` from the release and extract it into your working directory, retaining `materials/SOURCES.json` and `materials/assets/library/`.

To use a different location:

```powershell
$env:BEATSCOPE_MATERIAL_ROOT='D:\Documents\Beathi\materials'
beatscope serve --open
```

Python movie rendering requires Node.js, FFmpeg, Playwright and a supported Chromium browser. See [local movie setup](local-movie.md).

## Edit and render

Select a template and a seed. Edit stage flags and cue markers on the rhythm graph; undo/redo and snapping are available. Edits save to `edit-plan.json` without recompiling every insertion. Click **Update preview** to apply the saved plan to the preview. **Generate video** always freezes the latest saved plan into the full-song job, even when the preview is stale.

Jobs retain `score.json` (`intent:music-video`), compiled timelines, frame atlases and render modules. The score comes from edited stages/cues; no new music analysis is required. Agent timing packages export that same saved plan.

The renderer freezes its own code and prepared images, so existing jobs remain reproducible after later template updates. Preparation is cached by song hash, seed, material/plan version and edit-plan hash. Renderer-only updates do not invalidate source atlases.

## Rendering and validation

WebGL2 performs composition, mirrors, kaleidoscopes, contour masks and negative region selection. H.264 encoding prefers hardware. Unsupported GPU capabilities select the previous Canvas path; runtime context loss reports an error. Image and GPU caches are bounded.

First preparation still decodes and grades footage with FFmpeg on the CPU. Acceleration reduces rendering work but does not make preparation free or guarantee identical gains on every PC. [Measured comparison and bounded rerender commands](prismatic-gpu-composite.md).

This is a reusable automatic edit; individual songs can still benefit from artistic review. GPU sampling and antialiasing differ slightly from Canvas. The template does not claim exact reproduction of any reference.
