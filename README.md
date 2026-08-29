# BeatScope

简体中文 | [English](README.en.md)

一个把歌曲节奏变成可播放视觉参考与 Agent 可复用时序包的本地个人项目。

BeatScope 允许用户上传一首歌，在浏览器里一边播放，一边查看随 LOW、MID、HIGH、瞬态与段落变化运动的粒子球、频段曲线和全曲结构。分析结果还会整理成 8 小节 cue map，并导出为带 <code>SKILL.md</code> 的 Codex 包，让后续视觉项目不必重新猜测同一首歌的节奏。

[![BeatScope 动态演示；点击播放原声视频](docs/demo/beatscope-preview.gif)](docs/demo/beatscope-demo.mp4)

**点击动画播放 10 秒原声演示。**

> BeatScope 展示的是节奏强度、频段分布和时间结构，不会把不确定的瞬态冒充成 kick、snare 或 808。音频在本机分析，临时上传文件会在处理后删除。

## 为什么做这个项目

音乐可视化真正麻烦的部分通常不是画一个会动的图形，而是确定它为什么在这一刻动、应该动多大，以及同一套动画怎样适应节奏密度完全不同的歌曲。

直接把每个峰值映射成一次爆炸，很快会遇到问题：稀疏歌曲看起来有冲击，密集歌曲却会让球体持续炸开；只看总音量又会丢失低频重量、高频细节和段落转换。下一次把音乐交给另一个 Agent 时，这些判断还要重新做一遍。

BeatScope 尝试把这段工作留下来。Python 负责读取音频、建立节拍网格和提取多频段能量；浏览器使用 <code>audio.currentTime</code> 作为唯一时钟；粒子动画把普通节拍、连续湍流、局部冲击和稀有重击分成不同层级。最终结果既可以直接观看，也可以作为下一次创作的时间参考。

## 一次使用怎样展开

~~~text
上传本地音频 → 建立节拍与多频段能量
            → 自动进入 Signal player
            → 播放、暂停、拖动与查看全曲结构
            → 在 8-bar cue map 中试听或框选循环
            → 导出 Codex package 继续制作视觉项目
~~~

1. 用户选择 WAV、FLAC、MP3、OGG 或 M4A 文件。
2. 本地服务生成节拍、瞬态、LOW / MID / HIGH 能量和段落概览。
3. 页面平滑移动到播放器，粒子球、频段线和频谱随播放位置变化。
4. Rhythm pattern overview（节奏概览）用整首歌的视角显示能量与段落，并允许跳转。
5. 8-bar cue map 把当前窗口整理成 impact、scale、flow、flash 和 bloom 参考。
6. Codex 导出包保存分析数据、视觉状态函数、说明与可移植 Skill。

<details>
<summary>查看更多播放器状态</summary>

### 安静段

![BeatScope 安静段](docs/screenshots/beatscope-player-calm.jpg)

### 高密度段

![BeatScope 高密度段](docs/screenshots/beatscope-player-dense.jpg)

</details>

## 页面不只是一颗会动的球

### Rhythm pattern overview：先看完整首歌

![BeatScope 全曲结构导航](docs/screenshots/beatscope-track-structure.png)

这条导航把整首歌压缩成段落、LOW / MID / HIGH 能量曲线与瞬态分布。点击任意小节即可跳转，红色框始终标出 cue map 当前查看的八小节，因此不用在一条长时间轴里盲目寻找变化。

### 8-bar cue map：把听感拆成可操作时间点

![BeatScope 八小节节奏参考图](docs/screenshots/beatscope-cue-map.png)

同一个八小节窗口同时展示 IMPACT、LOW / SCALE、MID / FLOW、HIGH / FLASH 与 ACCENT / BLOOM。它不是鼓组转写，而是一张面向动画的运动提示图：可以单击试听瞬态，也可以拖出循环，再把时间、强度与频段驱动交给下一段视觉代码。

### Export for Codex：把分析结果带走

![BeatScope Codex 导出区域](docs/screenshots/beatscope-codex-export.png)

导出包不仅包含分析 JSON，还包含 seek-safe 的 <code>visual-state.js</code>、使用说明、Schema 与项目级 <code>SKILL.md</code>。把 ZIP 放进新的 Codex 项目，Agent 就能沿用同一套时间与视觉语义，而不是重新听歌猜节奏。

## 音乐怎样影响画面

播放器不会把所有强拍都当成同一种事件。它先在当前歌曲内部比较瞬态强度和局部密度，再给动画分配有限的视觉预算。

| 音乐状态 | 视觉反应 |
| --- | --- |
| 普通节拍 | 球体轻微呼吸，中心与频段线短促响应 |
| 连续强拍 | 表面波动与粒子湍流增加，不连续炸开 |
| 局部突出瞬态 | 少量粒子脱离，并出现短冲击 |
| 稀有重击或段落变化 | 在冷却间隔允许时触发完整展开 |
| LOW / MID / HIGH | 分别控制重量与尺度、表面流动、细节与亮度 |
| 播放位置 | 粒子、曲线、结构导航和 cue map 使用同一时间来源 |

粒子数量会根据单帧渲染耗时自动调整。结构导航与 cue map 使用较低刷新频率，避免它们与主动画争抢录屏资源；音频时间本身不会因此降采样。

## 8 小节参考怎样工作

BeatScope 将原始瞬态对齐到 1/16 或 1/32 网格，同时保留真实发生时间、量化位置和偏移量。页面不要求用户相信某个乐器标签，而是直接显示可验证的节奏事实：

| Cue | 适合参考的视觉方向 |
| --- | --- |
| IMPACT | 几何体、镜头或构图的短促冲击 |
| LOW / SCALE | 尺度、重量和景深 |
| MID / FLOW | 主体表面与方向性运动 |
| HIGH / FLASH | 边缘光、细粒子和短曝光 |
| ACCENT / BLOOM | 少数主事件与全局强调 |

单击 cue 可以试听附近瞬态；拖动可以定义循环范围。选择与拖动不会让歌曲从头重新播放。

## Rhythm IR：事实、语义与呈现

v0.4 把所有节奏数据整理成三层结构，每层只依赖上一层：

1. **事实层**：音频直接支持的内容 —— 节拍时间、瞬态（含频段能量与强度）、多频段能量帧。这一层不做任何猜测。
2. **语义层**：从事实推导的内容 —— 全曲 BPM 与变速段、小节网格、量化位置、段落概览、accent cue。每个字段都能追溯到来源（<code>analysis.provenance</code>）与计算过程（<code>analysis.diagnostics</code>）。
3. **呈现层**：把语义映射成视觉预算 —— pulse、turbulence、burst、hero 分层由 <code>runtime/visual-profile.js</code> 统一分配，播放器只是它的一个消费者。

项目数据使用 schema v4（<code>schema_version: "4.0"</code>）写入并通过 validator 校验；v3 项目读取时自动迁移。核心输出不包含 kick、snare、hihat 或 808 等乐器身份，也不把强度伪装成 confidence —— 页面显示的是 backend、pipeline 版本和可解释的诊断信息（来源方法、迁移记录、pregrid 合并数量、警告条数）。

共享 JavaScript 运行时 <code>beatscope/runtime/runtime.js</code> 是纯 ESM，不依赖 DOM、Audio、Canvas 或系统时钟；<code>track.at(time)</code> 对相同输入始终返回相同结果，变速段落的小节/拍相位由相邻真实节拍与小节下拍推导，而不是假设全局 BPM。网页播放器、页面诊断与 Codex 导出都构建在它之上。

## 实测精度

以下数字由基准测试自动生成（<code>beatscope benchmark</code>，合成音频 + 人工标注真值，拍匹配容差 70 ms、瞬态容差 50 ms），与 <code>build/benchmark/benchmark-results.md</code> 保持一致；硬门槛未通过时命令会以非零码退出：

| 场景 | BPM 误差 | 拍 MAE | 拍 F1 | 瞬态 F1 |
| --- | ---: | ---: | ---: | ---: |
| fixed-120 | 0.19 BPM | 3.17 ms | 0.97 | 1.00 |
| fixed-90 | 0.12 BPM | 10.70 ms | 1.00 | 1.00 |
| dense-128 | 0.40 BPM | 18.29 ms | 1.00 | 1.00 |
| sparse-100 | 0.35 BPM | 9.39 ms | 1.00 | 1.00 |
| tempo-change | — | 35.20 ms | 0.16 | 1.00 |
| offgrid | 0.19 BPM | 17.29 ms | 1.00 | 1.00 |
| bass-heavy | 0.19 BPM | 3.17 ms | 0.97 | 0.27 |
| silence | — | — | 0.00 | — |

硬门槛（阻断提交）：schema 必须有效、固定 BPM 场景误差 ≤ 5 BPM、拍 F1 ≥ 0.5、静音误报 ≤ 20 个、拍 F1 相对基线回归 ≤ 0.15 —— 当前 8 个场景全部通过（0 gates failed）。变速场景的拍 F1 与 bass-heavy 的瞬态 F1 按计划仅作报告参考（不设门槛）：变速用单段全局 BPM 衡量本来就失真，低频主导混音中的高频瞬态召回受合成素材限制；两者的分段 BPM 误差（19.67 / 0.33 BPM）与量化偏移（33.12 ms / 2.97 ms）在报告中有更合理的度量。

## 给 Codex 的导出包

~~~text
beatscope-codex.zip
├── SKILL.md
├── references/schema.md
├── rhythm-map.json
├── visual-state.js
├── beatscope-runtime.js
├── BEATSCOPE.md
└── README.md
~~~

<code>visual-state.js</code> 只做一件事：<code>getVisualState(time)</code> 就是共享运行时的 <code>track.at(time)</code>。网页播放器和导出包使用同一份 <code>beatscope-runtime.js</code>，因此浏览器里看到的状态和 Agent 拿到的状态来自同一个实现。Agent 可以直接读取节拍相位、频段能量、瞬态脉冲与段落，不必再次分析音频；暂停、拖动和跳转后仍然由同一个播放时间恢复画面。

MIDI、CSV、PNG 和原始 JSON 仍然保留在 **Advanced tools** 中。MIDI 只是量化时间参考，不是重建出来的鼓组演奏。

## 当前实现

- 本地音频读取、格式检查与 FFmpeg 安全回退
- 单一分析管线：节拍网格、瞬态、多频段能量和全曲结构分析
- schema v4 校验、v3 项目迁移与来源/诊断元数据
- 共享 JavaScript 运行时：网页与导出使用同一份时间查询实现
- Canvas 2D 粒子球、频段曲线、光晕与频谱面板
- 根据歌曲分布和节奏密度分配动画层级
- 播放、暂停、音量、跳转和 8 小节循环
- 全曲结构导航与 1/16、1/32 cue map
- 页面显示分析 backend 与可解释诊断，不显示虚假 confidence
- 带 accuracy gates 的 benchmark，自动生成精度报告
- Codex ZIP、Skill、JSON、CSV、PNG 和参考 MIDI 导出
- 请求级临时文件、250 MB 上传限制和本地项目缓存
- Python、纯 JavaScript 与 GitHub Actions 回归测试

## 技术栈

| 部分 | 使用的技术 |
| --- | --- |
| 分析 | Python、NumPy、SoundFile |
| 高质量可选流程 | librosa、Demucs、Beat This |
| 本地服务 | Python HTTP server |
| 播放 | HTML Audio、audio.currentTime |
| 视觉 | Canvas 2D、原生 JavaScript、CSS |
| 导出 | JSON、CSV、PNG、Standard MIDI、ZIP Skill package |
| 验证 | pytest、Node Test Runner、GitHub Actions |

## 项目结构

~~~text
beatscope/
├── analysis.py             # 基础音频分析
├── rhythm.py               # 事实型节奏项目
├── beatgrid.py             # 节拍、量化与偏移
├── structure.py            # 全曲段落与模式概览
├── pipeline.py             # 单一分析管线，组装 schema v4 项目
├── schema.py               # v4 validator 与 v3 迁移
├── benchmark.py            # 合成真值基准与 accuracy gates
├── exports.py              # Codex、CSV、PNG 与 MIDI 导出
├── server.py               # 本地上传、项目与媒体服务
├── mcp/                    # MCP 服务器（service、PathPolicy、runtime bridge）
│   └── runtime_worker.mjs  #   Node worker：共享运行时的时间查询
├── runtime/                # 共享 JavaScript 运行时（网页与导出同源）
│   ├── runtime.js          #   track.at / quantize 等时间查询
│   └── visual-profile.js   #   pulse/turbulence/burst/hero 视觉预算
├── agent_skill/            # 打入 ZIP 的可移植 Skill
└── web/
    ├── renderer.js         # 粒子播放器、结构与 cue map
    ├── audio.js            # 单一音频时钟与播放控制
    ├── app.js              # 页面状态和交互
    └── index.html
skills/beatscope-visualizer/ # 仓库内 Skill
tests/                       # Python 与 JavaScript 回归测试
evaluations/                 # MCP evaluation 问答与固定 fixture
docs/                        # 截图、演示视频与 docs/mcp.md 契约文档
~~~

## 本地运行

需要 Python 3.10 或更新版本。

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
beatscope serve
~~~

打开 <code>http://127.0.0.1:8765</code>，然后选择音频。WAV、FLAC 和 OGG 通过 SoundFile 读取；本机 libsndfile 不支持 MP3 时会使用 FFmpeg 回退。

常用命令：

~~~powershell
beatscope serve
beatscope rhythm song.wav --drums drums.wav --beat-this song.beats --output rhythm.json
beatscope separate song.wav --output-dir .beatscope-cache\song\stems --model htdemucs --device cuda
beatscope benchmark
beatscope doctor
~~~

## MCP 服务器：让 Agent 直接使用节奏事实

BeatScope 内置本地 MCP 服务器（`beatscope_mcp`）。Codex、Claude Desktop 等 MCP 客户端可以不经网页、不读源码，直接分析本地歌曲、按时间窗查询节拍、瞬态与 cue，并导出供 Agent 使用的 handoff ZIP。时间语义（bar/beat 相位、能量插值、onset 脉冲、量化）由与网页播放器和导出包完全相同的 JavaScript 运行时计算，三条路径不会各说各话。

安装与启动：

~~~powershell
pip install -e ".[mcp]"
beatscope-mcp
~~~

服务器走 stdio；分析在本机完成，不向网络发送音频或任何数据。

| 工具 | 作用 |
| --- | --- |
| `beatscope_list_projects` | 列出缓存项目（BPM、小节、backend、provenance） |
| `beatscope_get_project` | 读取项目 summary / timing / 完整 JSON |
| `beatscope_analyze_audio` | 分析音频并缓存；支持进度与取消，多配置可共存 |
| `beatscope_get_visual_state` | 某一时刻的完整视觉状态，与网页播放器一致 |
| `beatscope_get_events` | (start, end] 区间内的 beats / onsets / cues / patterns |
| `beatscope_export_package` | 导出便携 Agent ZIP（原子写入，含 SKILL 与 schema） |

安全模型：所有输入输出路径必须位于 `BEATSCOPE_ALLOWED_ROOTS` 白名单内（默认当前目录），越界请求会被直接拒绝；导出目标必须是 `.zip`。

Codex CLI（`~/.codex/config.toml`）：

~~~toml
[mcp_servers.beatscope]
command = "C:\\src\\beatscope\\.venv\\Scripts\\beatscope-mcp.exe"

[mcp_servers.beatscope.env]
BEATSCOPE_ALLOWED_ROOTS = "C:\\Users\\me\\Music;D:\\work\\videos"
~~~

Claude Desktop（`claude_desktop_config.json`）：

~~~json
{
  "mcpServers": {
    "beatscope": {
      "command": "C:\\src\\beatscope\\.venv\\Scripts\\beatscope-mcp.exe",
      "env": { "BEATSCOPE_ALLOWED_ROOTS": "C:\\Users\\me\\Music" }
    }
  }
}
~~~

语义声明：MCP 只暴露瞬态与频段事实，不识别 kick、snare、hihat 或 808；服务器 instructions 也会向 Agent 重复这一点。

常见问题：报 "runtime bridge unavailable" → 安装 Node.js 20+，或用 `BEATSCOPE_MCP_NODE` 指向 node 可执行文件；报 "outside BeatScope's allowed roots" → 把文件所在目录加入 `BEATSCOPE_ALLOWED_ROOTS` 后重启；报 "does not exist" → 先 `beatscope_list_projects` 查看，或用 `beatscope_analyze_audio` 生成。完整契约见 [docs/mcp.md](docs/mcp.md)。

## 可选高质量流程

内置分析器足够体验播放器。对于鼓组埋在完整混音中的歌曲，可以安装额外依赖并提供 Beat This 时间与 Demucs drums stem：

~~~powershell
pip install -e ".[high-quality]"
beatscope separate "song.wav" --output-dir .beatscope-cache\song\stems --model htdemucs --device cpu
beatscope rhythm "song.wav" --drums drums.wav --beat-this song.beats --output rhythm.json
beatscope serve --project rhythm.json
~~~

选择 <code>--device cuda</code> 时，BeatScope 不会静默改用 CPU。

## 验证

~~~powershell
pytest -q
python -m pytest tests\mcp -q
node --test tests\test_grid.js tests\test_interaction.js
node --test tests\test_runtime.js tests\test_visual_profile.js tests\test_playback_characterization.js
beatscope benchmark
~~~

JavaScript 侧：网格与交互测试覆盖页面行为；runtime 与 visual profile 测试覆盖共享运行时契约和纯度约束；characterization 测试比较网页播放器与 Codex 导出两条路径在同一时间点的输出一致性。MCP 测试覆盖工具契约、路径安全、运行时一致性与导出。GitHub Actions 会在 Windows 与 Ubuntu、Python 3.10 与 3.12 上运行相同的核心检查。

## 已知限制

- 内置分析不会可靠识别 kick、snare 或 808 身份，只报告瞬态和频段事实。
- Canvas 2D 粒子在高分辨率录屏时仍受浏览器和 GPU 性能影响；稳定高帧率的下一步是迁移到 WebGL。
- 自动段落标签来自能量与重复关系，不等同于人工编曲标注。
- MP3 支持取决于本机 libsndfile 或 FFmpeg。
- 这是本地创作与参考工具，不是 DAW、FLP 生成器或精确鼓组转录器。

## 项目状态

BeatScope 已完成从音频上传、播放式可视化、全曲结构、8 小节 cue map 到 Codex Skill 导出的完整本地流程。它仍是一个持续调整的个人实验；后续重点不是增加更多导出格式，而是让同一套视觉语法在更多歌曲、设备和录制环境中保持稳定。

## License

本项目使用 [MIT License](LICENSE)。
