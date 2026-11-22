# 给技术 LLM 的【保引擎换场景 / 换歌量产模板】

当整套 BeatScope + 渲染合成管线已经跑通且质感稳定，想换一个新的视觉场景、更换风格配方或换一首新歌继续制作时，直接复制以下口令：

```text
保持现有的 `pipeline/music_state.py` 因果时序状态机、`pipeline/anti_cheapness_lint.py` 门禁与 `pipeline/run_pipeline.py` 流水线框架完全不动。

请仅替换场景/底板模块（或切换新曲目的 BeatScope `frame-timeline.json`）：
- 新视觉主题 / 场景：【填入具体原创空间、主体或底板池，例如：黄昏海滨电车站台 / 日式和纸版画世界 / 极简建筑画廊】
- 沿用/选用的渲染管线：【3D-Scene-Pass / Layer-Decoupled / 2D-Editorial-Hybrid】
- 防廉价 Lint Profile：【universal-baseline / editorial-kinetic / strict-darkroom / custom】
- 新歌曲时序源：【填入由 `node bake-timeline.mjs` 新生成的 `frame-timeline.json` 路径】
- 替换完成后先运行 `--probe` 输出多帧音乐节点诊断拼图 `probe_grid.png` 与去色测骨 `probe_grid_gray.png` 供我验收构图、光影与切换连贯性。
```
