# Movie studio — frozen UI structure (v1)

The movie studio is the product surface: open a song, the analysis lands, the
built-in template plays as a live preview, and rendering a film is an explicit
action. **Its structure is frozen as of this version** — layout skeleton, panel
inventory, surface treatment and motion contract below are the reference.
Changing the skeleton is a design decision, not a refactor.

Entry: `/` (redirects to `/app/`), implemented by `web-src/src/movie/Studio.tsx`.
Shell chrome comes from `web-src/src/styles/tokens.css` + `shell.css`; the
studio's own sheet is `web-src/src/movie/studio.css`.

## Skeleton

```
.mv-shell                        the wall (see Surface)
├─ .topbar                       brand · file + tempo facts · status chip · 换一首歌
├─ .mv-body                      grid: 224px | minmax(0,1fr) | 264px
│  ├─ .mv-rail  (left)           结构: rail-cap · .seg-list rows · rail-foot
│  ├─ .mv-stage                  stage-head · .mv-frame (preview or film) ·
│  │                             .mv-transport · warning line
│  └─ .mv-rail  (right)          .card ×3 — 视频 / 数据导出 / 模板
├─ section.cm                    CueMap: BEATSCOPE / ANALYSIS · 全曲总览 ·
│                                bar grid · MOTION CUES · collapse toggle
└─ <audio>                       the only clock; hidden
```

The stage is the hero and takes the space the analysis panel leaves. The cue map
is docked under the body, collapsed state persisted in
`localStorage['beathi.cuemap.collapsed']`.

## Two export tracks, independent

- **Data** — available as soon as the analysis lands: `导出包 · codex.zip`, the
  timing-only Agent handoff (rhythm map, response ordering, `rhythm.mid` /
  `rhythm.csv`, the accessor and runtime, the probe, the agent documents, the
  manifest). It ships no visual layer by design; see `docs/local-movie.md`.
- **Film** — only after `生成视频` runs; the film is `影片 · MP4`.

Previewing never renders and never writes a file. Playback is never automatic.

## Surface

The page is one continuous sheet: a supplied drawing (`paper.css` +
`paper-wall.avif/.webp`, baked by `build/bake-paper-wall.py`) painted with
`background-attachment: fixed` and `cover`, with the chrome that used to paint
its own paper tone set transparent (`.topbar`, `.mv-body`, `.mv-stage`,
`.mv-rail`, `.card`, and the `section.cm` panel). The texture keeps its own
colour; the paper tokens remain only as the pre-load fallback.

## Copy

English is the default; the top-bar `EN / 中文` switch flips the whole screen and
remembers the choice (`localStorage['beathi.studio.lang']`). All strings live in
`web-src/src/movie/copy.ts` — the Chinese column is typed against the English
one, so a missing key fails the typecheck instead of rendering blank.

The screen carries labels, not explanations: the panel headers and values, the
transport state and the measurement facts. The only sentence-length copy left is
the photosensitivity warning under the transport, which stays in both languages.

Instruments stay opaque on purpose, so data never sits directly on the drawing:
`.mv-frame` (the film), `.cm-stack` (chart plates, 58% wash) and
`.mv-transport` (62% wash).

## Motion contract

| Gesture | Motion |
|---|---|
| Cue map 收起 / 展开 | height `grid-template-rows 1fr→0fr` 440ms `--ease-settle` + mask wipe (`--cm-wipe` 0→240px) + the four blocks staggered 60/120/180/240ms out, 0/40/80/120ms back |
| Panels and rows arriving after analysis | 460ms `translateY(10px)`→0 + fade; cards 0/70/140ms, segment rows 30ms steps |
| Timeline drag | pointer capture on a custom track; the track renders from its own value during the gesture so the clock cannot pull the knob back |

`prefers-reduced-motion` zeroes durations (`tokens.css`) and delays
(`studio.css`).

## Not part of this freeze

This is the only surface the product ships. The previous ones — the canvas
workspace (`?canvas`), the composition workbench (`?composition=1`), and the
old studio page (`/legacy.html`) — were retired together with the compiled
visual layer they were built on; `/` routes to this studio and nothing else.
