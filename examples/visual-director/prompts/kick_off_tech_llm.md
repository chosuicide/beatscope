# 给盲态技术 LLM 的【首次开工口令】

将导演生成的工程规范 `project_spec.md` 与 BeatScope 烘焙好的 `frame-timeline.json` 发送给盲态技术 LLM / 独立子代理（**物理隔离：绝对不要附带参考视频路径**），同时复制以下口令发给它：

```text
严格按附件中的工程规范 `project_spec.md` 与 BeatScope 逐帧时序文件 `frame-timeline.json` 实现整套渲染与合成管线。

执行死命令：
1. 严禁写死固定帧号时间轴：所有段落状态、视觉切换/局部异变、能量调制与收口必须读取 `frame-timeline.json`（严格保持 seek-safe 确定性，禁止无种子随机）。
2. 防高频机械抽搐：严禁把原始逐帧 `bands.low/mid/high` 直接乘进 3D 顶点、缩放或机位；必须通过 `pipeline/music_state.py` 的 `causal_attack_release_envelope` 因果攻释包络或节拍缓动曲线驱动。
3. 严格遵守规范中指定的防廉价门禁 Profile（默认 `universal-baseline`，或规范指定的 `editorial-kinetic` / `strict-darkroom` / `custom`），启动前必须通过 `pipeline/anti_cheapness_lint.py` 静态代码扫描，杜绝假报错占位文案与单一物件换色屏保。
4. 按规范选定的 Layer 2 渲染管线实现（`3D-Scene-Pass` / `Layer-Decoupled` / `2D-Editorial-Hybrid` 或其组合），严格守住规范中的前背景光影咬合与切换曝光连贯性规则。
5. 写完代码后【不要直接渲染全片】，先运行 `--probe` 模式渲染 `frame-timeline.json` 跨幕关键节点帧（4~16 帧），输出 `probe_grid.png` 与去色测骨 `probe_grid_gray.png` 给我验收。
6. 等我确认探针拼图的「形态多样性 + 光影和谐度 + 切换连贯性」合格后，再执行全量渲染，并用 BeatScope `render.mjs --frames-dir` 封装带原曲校验的 MP4（局部修片时配合 `--start-frame/--end-frame` 与 `--reuse-unchanged` 复用未改分段）及 `verify.mjs` 跑同步诊断。
```
