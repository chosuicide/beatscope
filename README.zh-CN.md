# BeatScope

[English](README.md) | 简体中文

[![CI](https://github.com/chosuicide/beatscope/actions/workflows/ci.yml/badge.svg)](https://github.com/chosuicide/beatscope/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.9.0-c65032)](https://github.com/chosuicide/beatscope/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-171713.svg)](LICENSE)

**把一首本地歌曲变成可播放的节奏地图，再把同一份确定性时序交给 Canvas、Three.js、Remotion 或 Coding Agent。**

[![BeatScope 播放器动态预览；点击观看有声视频](docs/demo/beatscope-preview.gif)](docs/demo/beatscope-demo.mp4)

BeatScope 同时提供三个部分：

- **Studio**：上传音频、检查节拍与结构、循环八小节，并观看可安全 Seek 的音乐视觉仪器。
- **时序包**：导出不包含原始音频、可移植且能自检的 `.beatscope` 交接包。
- **Runtime + MCP**：让视觉项目或 Coding Agent 在同一播放时刻读取同一帧，无需重新分析音乐。

它报告时间、瞬态强度、频段分布和中性的重复结构，但**不会**把不确定事件硬说成 kick、snare 或 808。

## 三分钟开始

需要 Python 3.10 或更高版本。

```powershell
git clone https://github.com/chosuicide/beatscope.git
cd beatscope
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
beatscope serve
```

打开 `http://127.0.0.1:8765`，选择 WAV、FLAC、MP3、OGG 或 M4A 文件并播放。分析完全在本地完成，请求产生的临时文件会在处理后清理。

## 一份时序包，不同的视觉语言

下面三个参考作品读取同一份冻结交接包。它们只共享时序事实，不共享组件、渲染器或视觉隐喻。

[![同一 BeatScope 时序包驱动三个视觉栈](docs/demo/consumer-showcase.gif)](docs/demo/consumer-showcase.mp4)

| Canvas 2D | Three.js | Remotion |
| --- | --- | --- |
| ![暖色单色信号印刷](docs/demo/consumer-canvas.png) | ![悬浮编织几何体](docs/demo/consumer-threejs.png) | ![黑白红编辑式画面](docs/demo/consumer-remotion.png) |
| 零构建交互作品 | 固定 `three@0.169.0` 的雕塑 | 确定性离线合成 |
| [打开示例](examples/canvas-particles) | [打开示例](examples/threejs-geometry) | [打开示例](examples/remotion-composition) |

三者都只读取一个函数：

```js
import { getBeatScopeFrame } from "./fixture.beatscope/visual-state.js";

function render(time) {
  const { timing, scene } = getBeatScopeFrame(time);
  // timing：小节、拍、相位、LOW/MID/HIGH、onset、accent
  // scene：跟随结构的构图与过渡包络
}
```

交互播放器使用 `audio.currentTime`，离线渲染器使用 `frame / fps`。暂停、Seek、重放和重复渲染都会把同一时刻解析为同一状态。

## 一次全新上下文的 Codex 实测

第四个作品并非在 BeatScope 仓库上下文中设计。一个全新的 Codex 任务只拿到了冻结需求、检查点和导出的交接包，随后独立生成了零依赖 Canvas 作品 **Orbital Notation**。

![Orbital Notation 使用冻结 BeatScope fixture 运行](docs/demo/codex-orbital-notation.gif)

上面的动图是在合成 fixture 音频真实播放时录制的。该次运行通过全部 5 个必需验证层，包括浏览器播放、Seek、重放、确定性状态和 reduced-motion 时序。生成代码没有经过人工修复；操作者只向验证器提供了仓库固定的浏览器测试路径。[查看运行记录](evaluations/agent-interoperability/runs/codex-canvas-2026-09-02.json)，或[查看自动生成的符合性表格](evaluations/agent-interoperability/conformance.md)。

**证据状态：** 已记录 1 个全新上下文 Coding Agent 产品。只有第二个独立产品通过同一冻结任务后，项目才会声明 “validated across Coding Agents”。

## 上传后发生了什么

```text
本地音频
   │
   ├─ 拍点 + 变速段
   ├─ 瞬态 + LOW / MID / HIGH 能量
   └─ 中性结构：A / B / A′ + 边界
                │
                ├─ Studio 播放器与八小节 cue map
                ├─ 确定性视觉配方 + 场景时间线
                ├─ MCP 查询
                └─ 自描述交接包
```

### Studio

![BeatScope 全曲结构导航](docs/screenshots/beatscope-track-structure.png)

全曲导航把能量、瞬态密度和重复结构放在一起。字母只表示重复关系，不是假装识别段落名称：`A′` 与 `A` 有关，但不意味着“副歌”或“主歌”。点击小节可直接 Seek，`Shift+←/→` 可跳转到结构边界。

![BeatScope 八小节动效提示图](docs/screenshots/beatscope-cue-map.png)

当前八小节会给出 `IMPACT`、`LOW / SCALE`、`MID / FLOW`、`HIGH / FLASH` 和 `ACCENT / BLOOM`。点击 cue 可试听附近瞬态，拖拽可设置循环，并且不会让歌曲重新播放。

### 交接包

每次导出都会带上节奏地图、确定性 runtime、场景文件、Agent 路由说明、Skill、完整性哈希和零依赖探针：

```text
project.beatscope/
├── beatscope-package.json
├── AGENT.md
├── rhythm-map.json
├── visual-state.js
├── visual-recipe.json
├── visual-timeline.json
├── consumer-probe.js
├── beatscope-runtime.js
├── scene-director.js
├── worker-example.js
├── SKILL.md
└── references/schema.md
```

交接包绝不携带原始音频。消费者可以先验证路径、manifest、哈希、可执行模板、检查点和时钟语义，再运行包内 JavaScript。

```powershell
beatscope validate-handoff path\to\project.beatscope --checkpoints checkpoints.json
beatscope validate-consumer examples\canvas-particles --browser
beatscope validate-consumer examples\remotion-composition --offline
```

## MCP：不打开 Studio 也能查询音乐

```powershell
pip install -e ".[mcp]"
beatscope-mcp
```

本地 stdio 服务提供六个工具：

| 工具 | 用途 |
| --- | --- |
| `beatscope_list_projects` | 查找本地缓存的分析项目 |
| `beatscope_get_project` | 读取时序、来源和结构摘要 |
| `beatscope_analyze_audio` | 带进度与取消能力地分析本地音频 |
| `beatscope_get_visual_state` | 查询某个时刻的精确视觉状态 |
| `beatscope_get_events` | 查询时间窗内的拍点、瞬态、cue、边界或场景 |
| `beatscope_export_package` | 原子写入可移植交接包 |

路径受 `BEATSCOPE_ALLOWED_ROOTS` 限制，分析和查询都留在本机。完整配置见 [MCP 契约与客户端设置](docs/mcp.md)。

## 为什么它不会越播越偏

BeatScope 把信息分为三层：

1. **事实**：拍点时间、瞬态和多频段能量。
2. **语义**：变速段、小节、量化 cue、结构边界和重复家族。
3. **表现**：动效预算、结构场景和过渡包络。

零依赖 JavaScript runtime 不接触 DOM、Audio、Canvas 或墙上时钟。播放器、MCP bridge、导出包和参考消费者查询的是同一套模型，而不是各自保存一份略有差异的歌曲解释。

内置 WebGL2 粒子仪器只是示例，不是产品边界。它通过播放时间驱动三瓣粒子场、流向拖尾和延迟轨道带，保持单次 draw call，并提供自适应质量、Canvas 后备与实时 reduced-motion。

<details>
<summary><strong>准确度、确定性与 benchmark 门槛</strong></summary>

音频 benchmark 含 11 个带冻结真值的合成场景：固定、密集、稀疏、离网格、重低音、静音、突然变速、渐变速度、微漂移和八度陷阱。当前全部门槛通过。tempo-change 的拍点 F1 从 `0.16` 提升到 `1.00`；两个速度段误差为 `0.185 / 0.325 BPM`，变速点误差 `0.01 s`，接缝没有漏拍或多拍。

结构另有十种编排 benchmark。视觉编排另有 28 个阻断门槛，覆盖 Seek/顺序确定性、家族身份、边界连续性、reduced-motion 比例、draw call 和运行时预算。CI 在 Windows、Ubuntu、Python 3.10 与 3.12 上运行，并包含固定浏览器消费者和 Remotion 离线证据任务。

```powershell
beatscope benchmark
beatscope benchmark-structure
beatscope benchmark-visual
```

</details>

## 常用命令

```powershell
beatscope serve
beatscope rhythm song.wav --output rhythm.json
beatscope visual-build rhythm.json
beatscope doctor
beatscope benchmark
```

针对密集混音，可通过 `.[high-quality]` 使用可选的 Beat This 与 Demucs 输入；选择 CUDA 后不会静默退回 CPU。

## 文档

- [MCP 服务与客户端设置](docs/mcp.md)
- [消费者符合性结果](evaluations/agent-interoperability/conformance.md)
- [冻结的跨 Agent 任务](evaluations/agent-interoperability/TASK.md)
- [仓库 Skill](skills/beatscope-visualizer/SKILL.md)
- [版本发布](https://github.com/chosuicide/beatscope/releases)

## 开发验证

```powershell
pytest -q
node --test (Get-ChildItem tests\test_*.js | ForEach-Object FullName)
beatscope validate-handoff examples\shared\fixture.beatscope --checkpoints examples\shared\checkpoints.json
```

仓库包含 Python、JavaScript、浏览器、包完整性、MCP、benchmark 和跨平台回归测试。CI 只重放已经提交的证据，不会在流水线里联系远程 Agent。

## 已知边界

- BeatScope 提供确定性音乐时序，不替代完整的艺术指导。
- 结构家族描述重复关系，不识别情绪、歌词或主歌/副歌。
- 内置分析器报告瞬态与频段证据，不判断乐器身份。
- 导出包和示例不包含原始音频。
- MP3 需要本地 libsndfile 支持或 FFmpeg。
- 很长、渐变或结构含糊的歌曲可能诚实地只得到一个结构段。

## 许可证

[MIT](LICENSE)
