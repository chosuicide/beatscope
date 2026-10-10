# Custom images and output formats (development)

These changes implement the first stage of issues #9 and #10 in the source checkout. They are not part of the previously published v0.15.0 portable archive.

| Aspect | 720p | 1080p |
| --- | --- | --- |
| 1:1 | 720×720 | 1080×1080 |
| 16:9 | 1280×720 | 1920×1080 |
| 9:16 | 720×1280 | 1080×1920 |

All formats retain 30 fps. Preview uses a 540-pixel short edge. All three templates render directly at the selected aspect. Prismatic Echo places rectangular windows and edge marks relative to the actual width and height, while circles, rotation angles, line widths and text use a uniform short-edge scale. Ordinary pictures cover the frame with the selected focal crop; only authored mirror/kaleidoscope shots reflect the source. Radial effects and circular wipes extend far enough to cover rectangular corners. Per-aspect focal-point overrides apply before composition. There is no mirrored padding or square-output crop.

Custom media belong to Prismatic Echo and Pastel Bloom. They replace source pictures before composition: Prismatic Echo shares its crops, mirrors, kaleidoscopes, contours, trails, negative bursts and transitions; Pastel Bloom shares its painterly strokes and surface treatments. Voxel Interference remains procedural and does not use custom media. Image previews and thumbnails use JPEG proxies with a 960-pixel long edge. Export crops from the oriented original before resizing, preserving detail around the chosen focal point. Prepared picture/frame caches use a resolution-dependent limit of 6–12 bitmaps; frames required for the current transition remain protected. Concurrent requests for the same frame share one decode. Decoded originals close after preparation; original files remain in project storage.

After importing a song, analysis must finish before beat-driven preview becomes available. Media can be queued while waiting and stay queued through analysis completion, retries and song changes. Add PNG, JPEG or WebP files through **+ Media** or drop them onto the preview. Each image is limited to 25 MiB and 32 megapixels; the existing project storage budget is 500 MiB, and an arrangement supports up to 100 media items. HEIC must be converted before import. The browser decodes image orientation; originals remain unchanged in the project asset store. Upload tiles clear only after the arrangement saves successfully; a failed save retains the original file and a retry action.

The bottom strip shows images and their placement on the song timeline. Drag a thumbnail onto the image timeline or use **Pin at playhead**. Placement snaps to the closest available beat or authored stage boundary. Click an image to set its normalized focal point, zoom and fill/fit mode. Save a default focus or an override for one aspect. A small deterministic camera move prevents a still image from becoming a frozen frame. Only the active thumbnail receives subtle downbeat feedback; reduced-motion preferences disable that feedback.

## Video clips

Short clips mix into the same arrangement. MP4, MOV, M4V and WebM files are accepted (≤60 seconds, ≤100 MiB); the browser reads the duration locally when it can decode the container and otherwise defers to the server. After the original uploads, the server derives two assets with FFmpeg: a JPEG poster (960-pixel long edge, taken at the earlier of one second or mid-clip) and a browser-safe preview clip — H.264 MP4 at CFR 30 with a short edge of at most 720 pixels, or VP9 WebM when libx264 is unavailable. The poster feeds thumbnails, lane slots and the preview fallback. Valid derived assets are reused on repeated imports, preserving existing focal-point edits.

The Studio preview plays the derived clip in a muted `<video>` element and snapshots its frame into the template pipeline. Asset HTTP routes stream byte ranges for playback and seeking; the inspector and preview use these URLs directly instead of retaining whole-file blobs. Clips no longer needed by the current composition release their decoder and bitmap. If a clip cannot decode, its poster remains available as a fallback. Export extracts each video slot's exact frames to JPEG with FFmpeg (`ceil(length×30)` frames per slot), using the selected 720/1080 short edge. Cancellation stops an active extraction process, and temporary sequences are removed after the job. To rerender, submit the same saved project/settings through the movie API, which regenerates these temporary frames.

A video slot additionally stores `offset`, the seconds into the clip where the slot starts. Moving a slot keeps its offset; the right edge cannot extend past `duration − offset`; dragging the left edge trims like an NLE by shifting the offset. The inspector's Clip section drags the slot's window along the full clip in 1/30-second steps. Automatic placement only offers a video to cells at least as long as the clip is long enough to fill, and picks a random valid offset from the arrangement's seeded RNG. Video slots are fixed-size in the clip dimension but still move, resize and unpin like image slots; the still-image Ken Burns drift is disabled while a clip is on screen.

Coverage measures the time images are the primary picture, divided by song duration. User pins take priority and count toward the target; pins may exceed it. Automatic assignments fill the remaining budget without adjacent repeats. When constraints prevent reaching the target, the UI displays the actual coverage. Transitions do not count twice. Four-beat windows and saved authored boundaries/cues define placement opportunities; these are authoring choices, not new analysis facts. A **Shuffle unpinned** action redistributes only automatic placements. Adding images and changing the target otherwise preserve valid existing assignments where possible.

Changes apply on the next available beat during playback, and immediately while paused. The newest pending change replaces earlier pending changes. Saving, not preview timing, determines the exported arrangement. Each export freezes output settings, timing edits, image arrangement and a copy of each referenced original. Queued updates are never needed to finalize an export. Changing the song carries image files and focus settings into the new project but resets their old timing positions.

The saved `custom-media.json` sidecar uses optimistic concurrency and is bound to the source song hash. Undo/redo covers import, deletion, ordering, shuffle, pin/unpin, coverage and focal-point edits within the current session. Removing an image from the arrangement retains its stored original, allowing undo. Those retained originals still consume project storage. Analysis failure retains queued images for retry; queued files before project creation are memory-only and do not survive closing or refreshing the page.

The Agent timing export includes `custom-media.json` with asset metadata and SHA-256 references for originals, image proxies and video preview clips, with integrity hashes for that sidecar. Media bytes are **not** embedded in that timing ZIP; the Agent must reuse the matching project's `assets/` directory or receive missing originals separately. Automatic face detection and additional style presets are deferred.

**Follow scene palette** is a global custom-media switch, off by default. When
enabled, its 0–100% strength follows the palette of each authored shot while
retaining source luminance and detail. It does not turn off composition effects.
Settings are saved in the media sidecar, participate in undo/redo, and travel with
media to another song. Preview, native export and the renderer ZIP share the same
processor. The optional GPU processor initializes only on first use and has a
bounded cache; the Canvas fallback applies the same color calculation.

Validation uses synthetic music and images, not the user's original song:

```powershell
rtk python -m pytest tests/test_custom_media.py tests/test_movie_jobs.py tests/test_assets.py -q
node --test tests/test_custom_media.mjs
rtk python tests/browser/studio_webmcp_server.py --port 8772 --short-render
# In another terminal: full six-format native export check.
node tests/browser/custom-media-smoke.mjs http://127.0.0.1:8772
# UI-only smoke for CI; no template material pack or FFmpeg required.
node tests/browser/custom-media-smoke.mjs http://127.0.0.1:8772 --ci
node tests/browser/custom-media-effects.mjs http://127.0.0.1:8772
node tests/browser/custom-media-aspects.mjs http://127.0.0.1:8772
node tests/browser/custom-media-interactions.mjs http://127.0.0.1:8772
node tests/browser/custom-media-regressions.mjs http://127.0.0.1:8772
# Video clip import, offset editing and deterministic export frames.
node tests/browser/custom-media-video.mjs http://127.0.0.1:8772
```
