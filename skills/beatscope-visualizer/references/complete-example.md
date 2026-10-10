# From package to a playable sample

This instructional example uses your saved stages and one resolved cue. It does
not supply a style for your MV. Existing projects keep their renderer and score;
use the example only in a new directory. Read AGENT.md first.

Layout: `work/timing/` contains this extracted package, `work/song.mp3` is the
matching original, and `work/sample-project/` will contain the new sample source.
From `work/timing/`, run:

```sh
node consumer-probe.js .
node query.mjs 0 3 --stages --accents --limit 8
node examples/start.mjs --out ../sample-project --start 0 --seconds 3
node music-brief.mjs --score ../sample-project/score.json --mv
node render.mjs --entry ../sample-project/scene.html --root .. --audio ../song.mp3 --out ../sample.mp4 --seconds 3 --memory-mb 512
node verify.mjs --score ../sample-project/score.json --video ../sample.mp4 --out ../sample.sync.json
```

The song must be at least three seconds for these exact commands. For a shorter
song use its duration for the query, generation and render. For a later excerpt,
pass the same `--start` to generation and rendering. All score times stay in
song seconds, never reset to the excerpt. The saved edit plan supplies full-song
stage boundaries; geometry changes at the selected cue and then recovers.

Only rendering requires FFmpeg/FFprobe plus an already installed Playwright and
browser. Use `--playwright /path/to/playwright/index.mjs --browser msedge` when
the module is not in the project's dependencies and Edge is installed. These
tools never install anything. See rendering.md for the adapter and resume rules.

The output includes playable video with original audio and a render provenance
report. verify reports cue binding, frame quantization and picture-change
candidates, with limitations. Review this short moving sample with sound, then
deliver media, source, the exact rerender command, credits and remaining differences.
Do not render the whole song merely to validate this example.
