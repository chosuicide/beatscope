# Identify material treatment before choosing a particle technique

Use this guide when a reference suggests turning supplied images, footage or shapes into points, dots, pixels, fragments or a limited-color surface. Treat the user's material as the source of recognizable shape and value information. A generic particle background does not demonstrate that transformation.

## Observe first

Inspect a native-size crop and several consecutive frames. Record point spacing, size, edge sharpness, palette, tonal levels, silhouette, holes, apparent depth, occlusion, motion, transparency and layers that remain untreated. Small dots visible in a finished film do not prove the creator used a particle simulation.

Separate three implementation candidates:

- **Screen-space halftone / ordered dithering:** brightness determines a stable dot or pixel pattern. Suitable when the grid is regular and the visible effect mainly preserves a source image or shaded surface. Recolor using a foreground/background or limited tonal palette; preserve edge and volume cues. It can process footage or a rendered 3D subject without inventing a 3D reconstruction.
- **Image-sampled point field:** points derive their location, occupancy, size or opacity from a source's mask and values. Suitable for image disassembly, reassembly and controlled displacement. Derive points from the supplied source rather than scattering unrelated dots around it. A depth estimate is an approximation and must be identified as such.
- **Geometry / volume sampled point cloud:** positions come from actual mesh or volume data, with projection and occlusion. Suitable when the brief requires actual spatial motion and usable geometry exists. A single image is not automatically a mesh or volumetric scan.

These routes can be combined, but state the hypothesis and test it against the observed result. Avoid substituting random emitters, neon sparks, network links, ASCII characters or large pixel blocks for a fine single-hue dot treatment unless that substitution is wanted.

## Resolve implementation locally

Search existing skills/components and primary source repositories using the observed mechanism (for example "ordered dithering Bayer shader," "image sampled point field," or "mesh surface points"), not only "particles." Inspect actual code and a comparable output before selecting. Repository descriptions and a SKILL.md are leads, not proof of reference fidelity. Keep dependency choices and source notes in the job directory; the timing package contains no mandatory third-party visual engine.

Adapt a live demo's clock, cursor inputs, random seeds and accumulated simulation to absolute media time. For feedback or physics, use a deterministic cached trajectory or fixed-step replay; arbitrary seeks cannot depend on which frames happened to be viewed earlier. For video sampling, ensure the decoded source frame also matches the requested time.

Keep enough point/tonal resolution for the user's subject to remain recognizable at final size. Stabilize the pattern through time: uncontrolled per-frame random sampling may flicker, while a coarse grid can destroy thin features. Monochrome means a coherent hue/value system, not necessarily a flat binary mask. Protect clean text or UI from the material pass when the reference treats it separately.

## Verify before promising the full treatment

Compare reference and treated material at native-size crops and ordered intervals. Check shape/negative space, dot scale/density, value range, motion and layer separation. Distinguish a successful color conversion from successful dot treatment and a successful dot treatment from 3D fidelity. Write material bindings with the actual source asset, transformation and source module. If reconstruction or temporal stability remains unverified, retain that finding; a timing pass cannot resolve it.
