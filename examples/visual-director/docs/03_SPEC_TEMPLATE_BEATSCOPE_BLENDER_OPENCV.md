# 03｜通用工程规范模板（BeatScope × 多管线视频 Spec）

导演 LLM 在向盲态技术 LLM 下发新项目任务时，**必须按本模板填写并输出完整 `.md` 工程规范文档**（如 `project_spec.md`），并与 BeatScope 烘焙好的 `frame-timeline.json` 一并交付。**严禁附带参考视频路径**，严禁写模糊散文。

---

## 模板正文（输出时替换 `【...】` 内容）

### 1. 项目定位、曲目窗口与核心美学
- **BeatScope 时序源**：`frame-timeline.json`（由 `node bake-timeline.mjs --out frame-timeline.json --start 【S】 --seconds 【D】 --fps 【24 或 60】` 生成）。
- **画幅与帧率**：`【1280x720 / 1920x1080 / 1080x1920】`，`【24 / 30 / 60】 fps`，总帧数严格等于 `timeline.window.frameCount`（**严禁写死帧数**）。
- **视觉风格与情绪基调**：`【按用户需求填写，例如：清透日系白昼 × 血肉局部异变 / 温柔胶片极简歌词 / 东方浮世绘卷 / 暗房实验暴力美学】`
- **参考风格配方（可选）**：`【无（全新自由定制） / presets/darkroom_brutalist.md / presets/hyper_keshiki.md / presets/in_place_mutation.md】`
- **核心场景与主体世界**：`【填写具体原创世界观、空间、角色/雕塑或平面元素，严禁复用参考片具象物件】`

### 2. 防廉价门禁与工程底线
- **静态门禁 Profile**：`【universal-baseline（通用默认） / editorial-kinetic / strict-darkroom / custom】`（详见 `docs/02_ANTI_CHEAPNESS_MANIFESTO.md`）。
- 若选 `custom`，附带 `lint_rules.json` 定义本项目专属禁用 API/正则。
- **强制确定性（seek-safe）**：禁止无种子随机函数；所有噪点、颗粒、抖动必须由 `frame_idx` 派生种子。
- **防高频机械抽搐**：禁止把未平滑的原始逐帧 `bands.low/mid/high` 直接乘进 3D 顶点、缩放或机位；必须走 `pipeline/music_state.py` 的因果攻释包络或节拍缓动曲线。

### 3. 选用的渲染管线（Layer 2，按需单选或混搭）
勾选并细化本项目实际采用的管线：
- [ ] **`3D-Scene-Pass`（完整 3D 场景 + 通道合成）**：
  - Blender Headless（`max_workers=1` 防显存 OOM）按 Chunk 输出对齐非 EXR PNG：`beauty`（8-bit RGB）+ `depth`（16-bit 灰度）+ `mask`（8-bit 硬边遮罩）；
  - 写明渲染引擎（`CYCLES` / `BLENDER_EEVEE`）、采样数、灯光方向与色彩管理（`AgX` / `Standard`）。
- [ ] **`Layer-Decoupled`（透明主体 × 底板池 / 局部原位异变）**：
  - Blender（`film_transparent=True`）或 2D 引擎输出 `fg_rgba` 透明主体；
  - 若存在多世界/表里翻转，写明对应的**环境反射球贴图**与**背景锁定规则**（例如：背景蓝天/曝光 100% 锁死，仅遮罩内局部元素原地异变；同一镜头共享完全一致的视差参数）。
- [ ] **`2D-Editorial-Hybrid`（纯 2D / 图形排版 / 实拍或生成底板）**：
  - 写明底板素材清单、排版网格比例、字体/字号约束、颜色 LUT 与动态运动规则。

### 4. 多幕视觉形态编排（反“单一物件换色屏保”铁律）
> 15–30 秒高能片段必须包含 **≥4 种截然不同的视觉形态或景别落差**，按 BeatScope `stages` 与关键 `cues` 分配（严禁写死固定帧号）：
- **开场定场（Stage 1）**：`【景别、主体、节奏克制度、可选预告闪帧设计】`
- **蓄力推进（Stage 2）**：`【形态变化、景别切换、如何引入核心冲突】`
- **高潮爆发（Stage 3）**：`【至少 2–3 种跨形态/跨景别碰撞机制与卡点触发方式】`
- **过渡呼吸 / 回归变奏（Stage 4）**：`【如何制造留白与反差】`
- **收束定格（Closing）**：`【子弹时间定格 / 一帧硬切归位 / 阶梯收口 / 柔和留白等】`

### 5. 光影衔接、合成算子与物理介质统一
- **前背景光学咬合规则**：`【例如：统一环境反射球 + 边缘天光包裹 / 零羽化 2px 膨胀刀切 / 统一胶片 LUT 与锁频颗粒】`
- **跨世界/拍点切换曝光衔接规则**：`【明确高频切换时如何避免意外明度断崖或尺度脱节】`
- **OpenCV / NumPy 向量化后处理清单**：`【列出本次用到的具体算子，如像素拉伸、半调网点、径向甩镜、局部遮罩异变、锁频颗粒、光学辉光等，并写明 BeatScope 驱动字段与参数范围】`

### 6. 并行渲染与 BeatScope 封片命令
- 帧输出统一落盘为 `frames/frame-%06d.png`（0-based 连续编号，总数等于 `timeline.window.frameCount`）。
- 最终直连 BeatScope 工具链封片与同步核验：
  ```powershell
  node render.mjs --frames-dir ..\job\frames --frame-pattern frame-%06d.png --frame-start 0 --audio ..\song.mp3 --out ..\job\preview.mp4 --start 【S】 --seconds 【D】 --fps 【FPS】 --width 【W】 --height 【H】
  node verify.mjs --score ..\job\score.json --video ..\job\preview.mp4 --start 【S】 --out ..\job\sync.json
  ```

### 7. 开工前强制「多帧音乐节点探针（`--probe`）」
- 写完代码后**严禁直接渲染全量帧**，必须先运行 `--probe` 仅渲染 **4～16 个跨幕关键节点帧**（覆盖开场稳态、核心卡点/异变、高潮峰值、阶段转场与收口），输出：
  - `probe_grid.png`（多帧彩色诊断接触表）
  - `probe_grid_gray.png`（去色测骨灰度版）
- 未经导演与用户审过探针拼图前，禁止启动全量渲染。
