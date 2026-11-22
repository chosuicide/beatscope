# BeatScope × Visual Director Workflow

将 **BeatScope（本地音乐时序测量 / 编辑计划 / 帧序列封装与同步验收）** 与 **双脑解耦导演工作流（导演 LLM × 盲态技术 LLM + 多管线按需组合 + 多帧探针门禁 + 锁段外科手术审片）** 融合的**风格中立**音乐视觉生产框架。

无论用户想做**极简字体排版、梦幻胶片、二次元/插画拼贴、清透 60fps 3D 设计、暗房实验暴力美学，还是“蓝天不动、云朵原地异变”的白昼见鬼 MV**，都可以直接使用本套工作流，不会被写死在某一种个人画风里。

---

## 核心设计：三层彻底解耦（风格 ≠ 管线）

| 层级 | 职责 | 是否绑定风格 |
| --- | --- | --- |
| **Layer 1｜通用核心层** | BeatScope 权威时序、双脑物理隔离（防抄袭）、反“单物件换色屏保”、`--probe` 试妆门禁、锁段外科手术修片、证据诚实原则 | **完全风格中立**（所有项目强制受益） |
| **Layer 2｜渲染管线箱** | 按项目需求自由挑选或混搭的 3 种纯技术管线：<br>1. `3D-Scene-Pass`（完整 3D 场景 + `beauty/depth/mask` 通道合成）<br>2. `Layer-Decoupled`（透明主体 `fg_rgba` × 独立底板池 / 局部原位遮罩异变）<br>3. `2D-Editorial-Hybrid`（纯 2D 图形、字体排版、插画/实拍或生成底板二次创作） | **纯工程能力**（不绑定任何画风） |
| **Layer 3｜风格配方库（`presets/`）** | 若干已实战跑通的可选美学配方（如暗房实验、清透多底板、同背景原位异变），仅作参考起点，用户随时可自由定义全新风格 | **完全可选、可扩展** |

---

## 核心铁律

> **参考视频只能给「导演 LLM」，绝对不能给「技术 LLM」。**
> - **导演 LLM** 看参考视频（或仅凭用户文字创意）+ 读 BeatScope `query.mjs` 摘要 → 剥离原片具象物件，将底层节奏、明暗与转场语法映射到目标曲目的 `stages / cues / bands`，按用户想要的风格挑选管线与防廉价 Profile，产出工程规范 `project_spec.md`。
> - **技术 LLM** 只拿 `project_spec.md` + BeatScope 烘焙好的 `frame-timeline.json` → 实现渲染代码，先跑 `--probe` 出多帧诊断拼图（含去色测骨），通过后再渲染完整 PNG 序列并直连 BeatScope `render.mjs --frames-dir` 封片与 `verify.mjs` 核验。

---

## 仓库结构

```text
beatscope-visual-director/
├── README.md                                          # 本说明文档与三层架构总览
├── DIRECTOR_SYSTEM_PROMPT.md                          # 【核心】风格中立的音乐视觉导演与管线监制 System Prompt
├── docs/
│   ├── 01_VIDEO_DECONSTRUCTION.md                     # 通用拆片法（视觉基因剥离 + BeatScope 音乐字段映射）
│   ├── 02_ANTI_CHEAPNESS_MANIFESTO.md                 # 通用反廉价底线 + 分级可配置静态门禁 Profile
│   ├── 03_SPEC_TEMPLATE_BEATSCOPE_BLENDER_OPENCV.md   # 通用工程规范模板（按需选择渲染管线与风格规则）
│   └── 04_SURGICAL_REVIEW_PLAYBOOK.md                 # 导演审片五步快诊 + 锁段外科手术修片指南
├── presets/                                           # 【可选】已实战验证的风格配方示例（绝非限制）
│   ├── README.md
│   ├── darkroom_brutalist.md                          # 示例 1：暗房三通道 × 零文字物理摧毁
│   ├── hyper_keshiki.md                               # 示例 2：60fps 清透金属 × 多底板平面排版
│   └── in_place_mutation.md                           # 示例 3：背景锁死 × 局部原位异变 × 双世界反射
├── prompts/
│   ├── kick_off_tech_llm.md                           # 给盲态技术 LLM 的【首次开工口令】
│   ├── surgical_patch_template.md                     # 给技术 LLM 的【锁段外科手术修改单】
│   └── swap_scene_template.md                         # 给技术 LLM 的【保引擎换场景 / 换歌模板】
├── pipeline/
│   ├── anti_cheapness_lint.py                         # 可配置 AST + 正则静态门禁（含 universal-baseline）
│   ├── music_state.py                                 # 读取 BeatScope frame-timeline.json，驱动因果平滑状态机
│   ├── opencv_fx.py                                   # NumPy 向量化通用后处理与像素算子库
│   ├── blender_scene.py                               # Blender 5.x Headless bpy 示例场景与通道导出
│   └── run_pipeline.py                                # Chunk 并行主控（--probe 拼图 + 全量 PNG + 调 render.mjs/verify.mjs）
└── tests/
    └── test_pipeline.py                               # 端到端自动化验证
```

---

## 四步闭环生产流程

### Step 1：BeatScope 测量原曲并烘焙逐帧时序
在 BeatScope 导出的 `.beatscope` 时序包目录内执行：
```powershell
# 1) 导演 LLM 只看有界摘要，不读整份 rhythm-map.json
node query.mjs --stages --accents --limit 16

# 2) 烘焙权威逐帧时序（支持叠加 score.json，帧率与时长按项目自由设定）
node bake-timeline.mjs --out ..\job\frame-timeline.json --start 0 --seconds 15 --fps 24
```

### Step 2：导演 LLM 确认创意方向 → 输出工程规范 Spec
- 将用户需求（及可选参考视频）+ `query.mjs` 输出给导演 LLM（加载 `DIRECTOR_SYSTEM_PROMPT.md` 与 `docs/`）。
- 导演输出 2–3 个原创「观影感方向确认卡」供用户拍板，按需选择渲染管线（`3D-Scene-Pass` / `Layer-Decoupled` / `2D-Editorial-Hybrid`）与静态门禁 Profile（默认通用 `universal-baseline`，或按风格选用 `editorial-kinetic` / `strict-darkroom` / `custom`）。
- 拍板后按 `docs/03_SPEC_TEMPLATE_BEATSCOPE_BLENDER_OPENCV.md` 产出 `project_spec.md`。

### Step 3：盲态技术 LLM 先跑 `--probe` 多帧试妆（严禁直接渲全片）
```powershell
python pipeline\run_pipeline.py `
  --timeline ..\job\frame-timeline.json `
  --out-dir ..\job\render `
  --package ..\timing `
  --lint-profile universal-baseline `
  --probe
```
启动前自动跑 `anti_cheapness_lint.py`；随后仅渲染关键音乐节点帧，输出：
- `probe_grid.png`（多帧诊断拼图，检视形态多样性、光影咬合与风格统一性）
- `probe_grid_gray.png`（去色测骨灰度版，检视黑白明暗骨架）

### Step 4：锁段外科手术微调 → 全量渲染 → BeatScope 封片与同步核验
- 导演按 `docs/04_SURGICAL_REVIEW_PLAYBOOK.md` 锁死已做绝的时间段，用 `prompts/surgical_patch_template.md` 精确修 2–4 个硬伤。
- 探针验收合格后执行全量渲染，直连 BeatScope `render.mjs --frames-dir`（支持 `--reuse-unchanged` 局部秒级热替换）与 `verify.mjs` 验收同步：
```powershell
python pipeline\run_pipeline.py `
  --timeline ..\job\frame-timeline.json `
  --out-dir ..\job\render `
  --package ..\timing `
  --audio ..\song.mp3 `
  --score ..\job\score.json `
  --lint-profile universal-baseline `
  --mux-mp4 ..\job\preview.mp4
```
