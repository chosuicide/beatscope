# Pastel Bloom / 粉彩花信 (development)

The local Studio now exposes the template from PR #11 alongside Voxel Interference
and Prismatic Echo. This integrates its oil, ink and pastel stroke renderer with
the existing custom image/video arrangement rather than covering the result with
an unrelated media overlay. The source integration is separate from the previously
published v0.15.0 portable archive.

**+ Media**, drag/drop, coverage, pinning, ordering, focus and per-aspect overrides,
undo/redo and **Follow scene palette** work through the same saved media document.
No user media is required: the supplied ten flower sequences remain the fallback.
Videos use preview proxies and deterministic extracted frames for native export.
Each source change resets the painting interval so the previous source does not
remain underneath a new photo. Images keep a small authored source movement while
the strokes grow.

The canvas uses the actual output dimensions. Supported outputs are 1:1, 16:9 and
9:16 at a 720 or 1080 short edge, 30fps. Frame size, selected focus and layouts
agree with preview; portrait composition is not a center crop of a landscape film.
Painterly detail is lower-resolution in live preview, as are the footage proxies.

The renderer loads requested frames rather than all 1,800 images. The decoded
built-in cache is bounded at 12 images / 32MiB; prepared sources are bounded by
output size. Leaving/disposal closes bitmaps and releases canvases. Frame replay
is confined to the current shot/source interval, making image and extracted-video
seeks deterministic. Cumulative strokes require one export page; hardware encoding
remains available, while brush analysis/drawing still uses Canvas and CPU.

During playback, skipped clock frames continue from the last painted frame rather
than restarting the shot. Backward seeks, source changes and invalidated media
still rebuild their interval. Oil-only passages decode only their held analysis
frames; original detail frames are loaded when footage or an effect actually uses
them. The export frame rate, brush density and beat timing remain unchanged.

`plan.shots` comes from the existing response director and latest saved edits.
An optional `plan.paintScore` can author media/technique shots in beat units;
conversion to seconds happens once, including exact integer-second times.
Saved stage boundaries start new motifs and are not replaced by automatic sections.

Checks: `node tests/browser/paint-template.mjs http://127.0.0.1:8772` uses synthetic
inputs, built-in frames, three aspects, custom images/video, palette and repeated
seeks. Native export can be exercised through the existing movie job API with
`template: "paint"` and the same output settings as the other templates.
See [footage provenance](../beatscope/web/paint-assets/SOURCES.md) for the
Pexels source of each clip.
