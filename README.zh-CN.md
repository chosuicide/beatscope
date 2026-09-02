# BeatScope

[English](README.md) | 简体中文

**一首歌。一份确定性时序包。不同的视觉技术栈。**

BeatScope 是一个本地音频响应乐器：把一首歌同时变成可播放的视觉，以及 Agent 可以继续复用的时序数据。v0.9 补完了这个闭环：导出包现在是自带说明的 handoff 契约，三个互相独立的视觉栈 —— Canvas 2D、Three.js 和 Remotion —— 通过同一个确定性帧函数驱动它，并且有验证命令来证明这一点。

上传一首歌，BeatScope 会建立节拍网格、多频段能量、瞬态、速度变化与中性的全曲结构。浏览器把这些事实变成 seek-safe 的粒子演出和 8 小节运动提示图；导出则把同一份分析装进带 manifest、Agent 路由文档、自检 probe、<code>SKILL.md</code>、视觉配方和场景时间轴的可移植包。播放器、MCP、导出与三个参考消费者读取同一套时间模型，不再各自猜一遍歌曲。

[![BeatScope 动态演示；点击播放原声视频](docs/demo/beatscope-preview.gif)](docs/demo/beatscope-demo.mp4)

**点击动画播放 10 秒原声演示。**

> BeatScope 展示的是节奏强度、频段分布和时间结构，不会把不确定的瞬态冒充成 kick、snare 或 808。音频在本机分析，临时上传文件会在处理后删除。

## 一份包，三种视觉栈

仓库内置一份冻结的 handoff fixture（<code>examples/shared/fixture.beatscope</code>，由 <code>fixture-lock.json</code> 以 sha256 锁定）和三个只共享这份包的参考消费者：

| 示例 | 技术栈 | 时钟 | 证明什么 |
| --- | --- | --- | --- |
| [examples/canvas-particles](examples/canvas-particles) | Canvas 2D，零构建 | <code>audio.currentTime</code> | 播放/跳转/重播还原出完全一致的几何；reduced motion 把位移精确缩放到 0.25× |
| [examples/threejs-geometry](examples/threejs-geometry) | three@0.169.0（import map，无打包器） | <code>audio.currentTime</code> | 框架胶水层保持 three 无关且纯净；seeded 几何；声明的 draw-call 预算 |
| [examples/remotion-composition](examples/remotion-composition) | Remotion 4.0.520 | <code>frame / fps</code> | 同一秒在 24/30/60 fps 下映射到同一状态；越过最后场景后场景归属冻结而 timing 按文档外推 |

每个消费者都是完整可运行的项目 —— 用任意静态服务器打开 <code>examples/canvas-particles/index.html</code>（Three.js 同理）并选择一个音频文件；Remotion 组合用 <code>npx remotion render</code> 离线渲染。它们各自 pinned 的依赖只存在于每个示例自己的 <code>package.json</code> 中，绝不进入 BeatScope 核心。

整套契约就是一次函数调用：

~~~js
import { getBeatScopeFrame } from "./fixture.beatscope/visual-state.js";

function paint(audioTime) {
  const { timing, scene } = getBeatScopeFrame(audioTime);
  // timing → bar, beat, beatPhase, low/mid/high, onset, accent
  // scene  → composition (spread, twist, flow, orbit, void, contrast),
  //          transition 包络, 家族身份
}
~~~

消费者自行选择时钟（媒体时间或 frame/fps），可以把返回值映射到任何视觉属性，但绝不重新分析音频、绝不猜测时间戳、也绝不拷贝 BeatScope 播放器。

## 为什么做这个项目

音乐可视化真正麻烦的不是让图形动起来，而是决定它为什么此刻要动、这一刻值得多大幅度，以及同一套系统怎样同时撑住稀疏和密集的歌曲。

直接把每个峰值映射成一次爆炸，很快会遇到问题：稀疏歌曲看起来有冲击，密集歌曲却会让球体持续炸开；只看总音量又会丢失低频重量、高频细节和段落转换。下一次把音乐交给另一个 Agent 时，这些判断还要重新做一遍。

BeatScope 把这些判断保存成数据。Python 负责追踪歌曲，浏览器只采样 <code>audio.currentTime</code>，运动系统把普通脉冲、持续流动、局部冲击与稀有重击分开处理。结果既能现在观看，也能把完全相同的时序证据交给下一次创作 —— 无论下一次用什么技术栈。

## 一次使用怎样展开

~~~text
上传本地音频 → 建立节拍与多频段能量
            → 自动进入 Signal player
            → 播放、暂停、拖动与查看全曲结构
            → 在 8-bar cue map 中试听或框选循环
            → 导出 handoff package 继续制作视觉项目
~~~

1. 用户选择 WAV、FLAC、MP3、OGG 或 M4A 文件。
2. 本地服务追踪节拍与速度变化，生成瞬态、LOW / MID / HIGH 能量和段落概览。
3. 页面平滑移动到播放器，粒子球、频段线和频谱随播放位置变化。
4. Rhythm pattern overview（节奏概览）用整首歌的视角显示能量与段落，并允许跳转。
5. 8-bar cue map 把当前窗口整理成 impact、scale、flow、flash 和 bloom 参考。
6. 导出包保存分析数据、确定性视觉状态函数、自带说明的契约、说明文档与可移植 Skill。

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

这条导航把整首歌压缩成结构段落、LOW / MID / HIGH 能量曲线与瞬态分布。v0.7 起，顶部条带按全曲结构段落绘制：家族是中性字母（<code>A</code>、<code>B</code>……），只表示重复关系，不是 Verse/Chorus 识别；变体（<code>A′</code>）表示与家族相关但听感有变化；同一家族的重复永远使用同一中性色。边界刻度的权重来自分析对这次变化的强度判断。点击任意小节即可跳转，<code>Shift+←/→</code> 可在上一个/下一个段落起点之间跳转，红色框始终标出 cue map 当前查看的八小节，因此不用在一条长时间轴里盲目寻找变化。

### 8-bar cue map：把听感拆成可操作时间点

![BeatScope 八小节节奏参考图](docs/screenshots/beatscope-cue-map.png)

同一个八小节窗口同时展示 IMPACT、LOW / SCALE、MID / FLOW、HIGH / FLASH 与 ACCENT / BLOOM。它不是鼓组转写，而是一张面向动画的运动提示图：可以单击试听瞬态，也可以拖出循环，再把时间、强度与频段驱动交给下一段视觉代码。

### 粒子乐器

![BeatScope 瞬态冲击时刻的粒子乐器](docs/screenshots/particle-impact.png)

播放器的主体是一片有机的三叶粒子场，绘制在仪表刻度层之下。局部突出的重击到来之前，张力先把粒子云收拢；随后主体作为一个整体围绕局部光核运动，边缘的一组稳定粒子沿流场延伸成拖尾。外围三条轨道带会稍晚、依次接住同一个拍子，让冲击向外传递，而不是所有图层在同一帧一起跳动。

![BeatScope 预备阶段的粒子乐器](docs/screenshots/particle-anticipation.png)

每个阶段都只由 tempo-aware motion director 和播放时钟推导：同一首歌的同一时刻永远渲染出同一帧。粒子 seed 可以改变拖尾长度或颗粒大小，但不会改变动作时机。其余状态（安静段、recoil、高密度段、变速边界、reduced motion）的固定时刻截图保存在 <code>docs/screenshots/</code>。

### 结构场景：跟随歌曲的构图

v0.8 把结构视图变成两个确定性产物。<code>visual-recipe.json</code> 给每个重复家族一个稳定身份 —— motif、调色板槽位、构图基准 —— 外加共享的转场时机与运动上限 token；<code>visual-timeline.json</code> 把这些身份落到真实歌曲上，形成场景与按真实节拍间隔定时的边界转场。共享的 <code>runtime/scene-director.js</code> 把两者变成一个 seek-safe 的状态函数：每个边界都经过 approach、cross、settle 包络，家族身份把构图带过变化，唯一允许不连续的只有边界脉冲。变体（<code>A′</code>)保留家族身份并只做两处有界次要变化，<code>BREAK</code> 使用保留的中性悬置处理。播放器通过 Follow structure 开关（产物存在前隐藏）和可访问的场景摘要暴露这些信息；每个场景内部节拍仍然保持局部响应。

## 音乐怎样影响画面

播放器不会把所有强拍都当成同一种事件。它先在当前歌曲内部比较瞬态强度和局部密度，再给动画分配有限的视觉预算。

| 音乐状态 | 视觉反应 |
| --- | --- |
| 普通节拍 | 主体整体呼吸、局部光核短促响应，随后出现克制的轨道波纹 |
| 连续强拍 | 宏观流动与表面行波增加，但不会连续炸开 |
| 局部突出瞬态 | 三个叶瓣短暂分离，边缘拖尾把运动带向外围 |
| 稀有重击或段落变化 | 冷却允许时触发主体完整展开与三条轨道带的延迟传播 |
| LOW / MID / HIGH | 分别控制重量与尺度、表面流动、细节与亮度 |
| 播放位置 | 粒子、曲线、结构导航和 cue map 使用同一时间来源 |

整个场景由确定性的 WebGL2 乐器一次 draw call 渲染：最多 18,000 个主体点，再加上三条每条约 690 个颗粒的 seeded 轨道带。anticipation、impact、recoil、aftershock、连续宏观流场、叶瓣局部光核、拖尾和轨道延迟波纹都完全由播放时间计算，不依赖系统时钟物理；三条轨道带以三个受控延迟接住同一个事件，而不是和主体同时响应。渲染器用滚动 180 帧窗口统计实测开销，只在持续过载或欠载时于三档主体质量（18,000 / 11,000 / 6,000 点，各带设备像素比上限）之间移动，且两次调整之间有冷却间隔。WebGL2 不可用或上下文丢失时，固定 680 个主体点预算的 Canvas 2D 回退继续维持画面；<code>prefers-reduced-motion</code> 变化时会实时切换到克制版本。结构导航与 cue map 使用较低刷新频率，避免它们与主动画争抢录屏资源；音频时间本身不会因此降采样。

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

v0.6 在真实时间轴上追踪节拍与速度：拍点来自 novelty 引导的追踪（局部速度候选、全局速度路径、逐拍重建与分段恒速 tempo segments），而不是全局 BPM 均匀网格。v0.7 在同一阶梯上加入全曲结构：按小节聚合和声、音色、节奏、能量四类视图，多尺度 novelty 提议边界，再用长度受限的分配标注重复家族（<code>A</code>、<code>B</code>……）与变体（<code>A′</code>）——全程确定性、缓存诚实、不含 confidence。所有节奏数据整理成三层结构，每层只依赖上一层：

1. **事实层**：音频直接支持的内容 —— 节拍时间、瞬态（含频段能量与强度）、多频段能量帧。这一层不做任何猜测。
2. **语义层**：从事实推导的内容 —— 全曲 BPM 与变速段、小节网格、量化位置、段落概览、全曲结构段落与边界、accent cue。每个字段都能追溯到来源（<code>analysis.provenance</code>）与计算过程（<code>analysis.diagnostics</code>）。
3. **呈现层**：把语义映射成视觉预算 —— pulse、turbulence、burst、hero 分层由 <code>runtime/visual-profile.js</code> 统一分配，播放器只是它的一个消费者。v0.8 起，编译出的视觉配方与时间轴作为独立产物存放在项目旁边；节奏 IR 本身保持 schema v4，内部不含呈现数据。

项目数据使用 schema v4（<code>schema_version: "4.0"</code>）写入并通过 validator 校验；v3 项目读取时自动迁移，结构数据放在可选的 <code>patterns.segments</code> 字段里，v0.7 之前编写的 v4 消费者不受影响。核心输出不包含 kick、snare、hihat 或 808 等乐器身份，也不把强度伪装成 confidence —— 页面显示的是 backend、pipeline 版本和可解释的诊断信息（来源方法、迁移记录、pregrid 合并数量、警告条数）。

共享 JavaScript 运行时 <code>beatscope/runtime/runtime.js</code> 是纯 ESM，不依赖 DOM、Audio、Canvas 或系统时钟；<code>track.at(time)</code> 对相同输入始终返回相同结果，变速段落的小节/拍相位由相邻真实节拍与小节下拍推导，而不是假设全局 BPM。小节相位本身仍然是从第一个追踪拍开始的启发式连续编号（provenance 已标记为推断值），不是专用 downbeat 模型。v0.7 起 <code>track.at(time)</code> 还携带 <code>structure</code> 块 —— 当前段落、段内相位与距下一个边界的秒数 —— 以及 <code>structureLead</code>、<code>boundaryImpulse</code> 信号，全部是时间的纯函数。v0.8 起 <code>runtime/scene-director.js</code> 以同一纯度契约成为它的场景对应物：场景身份与转场包络都是播放时间的纯函数。网页播放器、页面诊断、导出与参考消费者都构建在它们之上。

## 实测精度

以下数字由基准测试自动生成（<code>beatscope benchmark</code>，合成音频 + 人工标注真值，拍匹配容差 70 ms、瞬态容差 50 ms），与 <code>build/benchmark-v06/benchmark-results.md</code> 保持一致；硬门槛未通过时命令会以非零码退出：

| 场景 | BPM 误差 | 拍 MAE | 拍 F1 | Tempo MAE | Segments | 瞬态 F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed-120 | 0.18 BPM | 5.78 ms | 1.00 | 0.18 BPM | 1 | 1.00 |
| fixed-90 | 0.16 BPM | 5.65 ms | 1.00 | 0.12 BPM | 1 | 1.00 |
| dense-128 | 0.16 BPM | 5.07 ms | 1.00 | 0.40 BPM | 1 | 1.00 |
| sparse-100 | 0.20 BPM | 9.83 ms | 1.00 | 0.35 BPM | 1 | 1.00 |
| tempo-change | — | 5.79 ms | 1.00 | 0.25 BPM | 2 | 1.00 |
| offgrid | 0.75 BPM | 29.41 ms | 1.00 | 0.73 BPM | 1 | 1.00 |
| bass-heavy | 0.27 BPM | 3.13 ms | 0.97 | 0.18 BPM | 1 | 0.28 |
| silence | — | — | — | — | 1 | — |
| gradual-drift | — | 5.85 ms | 1.00 | 1.74 BPM | 6 | 1.00 |
| micro-drift | — | 5.69 ms | 1.00 | 1.28 BPM | 1 | 1.00 |
| octave-trap | 0.18 BPM | 6.14 ms | 1.00 | 0.18 BPM | 1 | 1.00 |

硬门槛（阻断提交）：schema 必须有效、固定 BPM 场景误差 ≤ 5 BPM、拍 F1 ≥ 0.5、静音误报 ≤ 20 个；固定速度场景相对基线的回归窗口（拍 F1 下降不超过 0.03、拍 MAE 恶化不超过 15 ms）；变速场景的声明下限 —— tempo-change 拍 F1 ≥ 0.55、分段 BPM 误差 ≤ 5 BPM、变速点误差 ≤ 1 s、接缝漏拍/多拍各 ≤ 1；gradual-drift 拍 F1 ≥ 0.65 且 tempo MAE ≤ 6 BPM；micro-drift 不允许八度错误且 tempo segments ≤ 3；octave-trap 不允许八度错误。当前 11 个场景全部通过（0 gates failed）。v0.5 → v0.6 的提升集中在该出现的地方：tempo-change 拍 F1 从 0.16 提升到 1.00（两段 tempo segments，分段 BPM 误差 0.185 / 0.325 BPM，变速点误差 0.01 s，接缝漏拍 0 / 多拍 0），所有固定速度场景保持原有水平。bass-heavy 的瞬态 F1 按计划仅作报告参考：低频主导混音中的高频瞬态召回受合成素材本身限制。

结构精度有独立的基准：十个合成编曲（A-B-A、含变体的 A-B-A-C-B、仅能量/和声/节奏变化、两小节 break、单调、不足四小节、变速重复、渐变漂移）对照冻结真值，考核边界 precision/recall/F1、重复家族准确率与过/欠分割数量，沿用同一套无 confidence、中性字母的契约。用 <code>beatscope benchmark-structure</code> 运行；v0.7 验收结果写入 <code>build/benchmark-v07/</code>。

视觉编排有第三套基准：<code>beatscope benchmark-visual</code> 编译十三个冻结场景 fixture，通过一个生成的 Node 进程把它们送进真实运行时（场景 director、motion director、粒子几何体，以及用于 draw call 计数的内联 WebGL2 stub）。它强制执行 28 个阻断门槛，覆盖确定性（配方/时间轴字节、查询顺序、seek、对照 MCP bridge 的跨端一致、密集 onset 稳定性）、身份（家族 motif 与调色板一致、变体稳定、BREAK 保留）、时间轴覆盖与转场时机、运动连续性（构图跨边界连续、仅脉冲可跳变、reduced motion 缩放、combined spread 上限、settle 精确落点），以及性能预算（场景查询 p95 低于 0.10 ms、director 查询 p95 低于 0.35 ms、每次渲染恰好一次 draw call、分配冒烟测试）。探测不可用（例如未安装 Node）的门槛会被记为 <code>unavailable</code>，绝不静默通过；每次运行还会校验 117 个 golden 检查点帧。

## Handoff 导出包

~~~text
beatscope-codex.zip
├── beatscope-package.json   # v0.9 自描述 manifest：entry、能力、完整性
├── AGENT.md                 # v0.9 面向消费 Agent 的路由文档
├── consumer-probe.js        # v0.9 无依赖 probe：规范帧 + 检查点重放
├── SKILL.md
├── references/schema.md
├── rhythm-map.json
├── visual-state.js
├── worker-example.js
├── beatscope-runtime.js
├── scene-director.js
├── visual-recipe.json
├── visual-timeline.json
├── visual-recipe-data.js
├── visual-timeline-data.js
├── BEATSCOPE.md
└── README.md
~~~

<code>visual-state.js</code> 保留 <code>getVisualState(time)</code> —— 即共享运行时的 <code>track.at(time)</code> —— 并在包内带有编译视觉产物时追加 <code>getSceneState(time)</code> 与一次调用返回 <code>{ timing, scene }</code> 的 <code>getBeatScopeFrame(time)</code>。网页播放器和导出包使用同一份 <code>beatscope-runtime.js</code> 与 <code>scene-director.js</code>。<code>worker-example.js</code> 可以把这套 API 放进模块 Worker，主线程只负责读取音频元素并发送 <code>audio.currentTime</code>。因此暂停、拖动、重播、主线程调用与 Worker 调用都会把同一时刻还原成同一帧。

v0.9 让导出包自我描述。<code>beatscope-package.json</code> 声明入口模块、导出函数名、时钟语义（<code>media-time</code>、<code>[0, duration]</code>）、包真正携带的能力，以及覆盖每个成员的 sha256 完整性映射。<code>AGENT.md</code> 是消费 Agent 第一个读的短路由文档：导入哪个文件、喂什么时钟、为什么永远不需要重新分析、以及如何用 probe 验证。<code>consumer-probe.js</code> 是零依赖的 ESM probe，负责检查包内容、渲染规范帧并重放录制的检查点 —— 一个包要么通过它，要么说出自己哪里失败了。

MIDI、CSV、PNG 和原始 JSON 仍然保留在 **Advanced tools** 中。MIDI 只是量化时间参考，不是重建出来的鼓组演奏。

## 验证 handoff 与消费者

基础检查完全在本地运行且无需网络；再按消费者类型显式开启对应执行层：

~~~powershell
python -m beatscope.cli validate-handoff path\to\package.beatscope --checkpoints checkpoints.json
python -m beatscope.cli validate-consumer examples\canvas-particles
python -m beatscope.cli validate-consumer examples\canvas-particles --browser
python -m beatscope.cli validate-consumer examples\remotion-composition --offline
~~~

<code>validate-handoff</code> 检查归档路径、manifest 形状、独立哈希、rhythm 数据、可执行文件是否与当前 BeatScope 模板逐字节一致、检查点重放、worker 启动与泄露。只有路径安全、manifest、完整性、可执行模板身份四道门槛全部通过，包内 JavaScript 才会运行。<code>validate-consumer --browser</code> 会真正启动固定版本 Chromium，加载本地合成 WAV，并检查播放/暂停、seek、重播、帧确定性、reduced-motion 时序、控制台错误与冻结调试钩子；<code>--offline</code> 则加载声明的帧适配器，核对重复运行与 24/30/60fps 一致性。退出码 <code>0</code> 表示所请求的必需层全部通过，<code>1</code> 表示契约失败，<code>2</code> 表示必需层被跳过或工具不可用。浏览器工具固定在 <code>tests/browser</code>，并由 CI 强制执行。

## 跨 Agent 评估：pending，不声明

<code>evaluations/agent-interoperability/</code> 冻结了评估基础设施：字节级稳定的任务文本（唯一允许的变化是目标框架占位符）、只记录元数据的严格 run recorder（不含 prompt、凭据或思考链；记录哈希锁定任务与包）、总权重为 100 的八类一致性评分表（艺术品味单独记录、不影响分数），以及确定性的 conformance 表 —— 见[自动生成的表格](evaluations/agent-interoperability/conformance.md)。

与记录证据完全一致的状态：三个参考消费者通过了所有可自动化的必需门槛，而独立的 Coding Agent 运行记录目前为 **0**。"validated across Coding Agents" 的声明保持 **pending**，直到至少两个不同的 Coding Agent 产品在发布阈值下完成冻结任务（全新上下文运行、记录人工修复、审查生成源码、失败保持可见）。CI 只重放已入库的证据，绝不访问远程 Agent。

## 当前实现

- 本地音频读取、格式检查与 FFmpeg 安全回退
- 单一分析管线：节拍网格、瞬态、多频段能量和带重复家族的全曲结构段落
- schema v4 校验、v3 项目迁移与来源/诊断元数据
- 共享 JavaScript 运行时：网页、导出与消费者使用同一份时间查询实现
- 视觉配方编译器（<code>beatscope visual-build</code>）：结构变成家族身份、调色板槽位与场景时间轴，存放在项目旁
- 共享场景 director（<code>runtime/scene-director.js</code>）：结构场景与边界包络是播放时间的纯函数
- 确定性的 WebGL2 粒子乐器：整体叶瓣运动、流场拖尾、延迟轨道带、自适应质量分级与 Canvas 2D 回退
- Canvas 2D 频段曲线、光晕与频谱面板
- 根据歌曲分布和节奏密度分配动画层级
- 播放、暂停、音量、跳转和 8 小节循环
- 全曲结构导航（含段落跳转）与 1/16、1/32 cue map
- 页面显示分析 backend 与可解释诊断，不显示虚假 confidence
- 带 accuracy gates 的 benchmark，自动生成精度报告
- 带有 28 个阻断级质量与性能门槛的视觉编排 benchmark（<code>beatscope benchmark-visual</code>）
- 自描述的 handoff 契约：每个导出包含 manifest、AGENT.md 路由与零依赖 consumer probe
- 退出码诚实的 handoff 与消费者验证命令（<code>validate-handoff</code>、<code>validate-consumer</code>）
- 同一份包的三个参考消费者：Canvas 2D（零构建）、Three.js（pinned，import map）、Remotion（离线，frame/fps 时钟）
- 冻结的跨 Agent 评估基础设施：任务、run recorder、评分表、conformance 表、只重放的 CI
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
| 视觉 | WebGL2 粒子、Canvas 2D、原生 JavaScript、CSS |
| 参考消费者 | Canvas 2D、three.js 0.169.0、Remotion 4.0.520（依赖仅限示例目录） |
| 导出 | JSON、CSV、PNG、Standard MIDI、ZIP handoff package |
| 验证 | pytest、Node Test Runner、GitHub Actions |

## 项目结构

~~~text
beatscope/
├── analysis.py             # 基础音频分析
├── rhythm.py               # 事实型节奏项目
├── beatgrid.py             # 节拍、量化与偏移
├── structure.py            # 全曲段落与模式概览
├── structure_features.py   # v0.7 按小节聚合的多视图结构特征
├── structure_segments.py   # v0.7 边界、重复家族与变体
├── pipeline.py             # 单一分析管线，组装 schema v4 项目
├── schema.py               # v4 validator 与 v3 迁移
├── benchmark.py            # 合成真值基准与 accuracy gates
├── visual_recipe.py        # v0.8 结构 → 视觉配方/时间轴编译器
├── visual_recipe_schema.py # v0.8 视觉产物校验与规范字节
├── visual_benchmark.py     # v0.8 视觉编排基准与门槛
├── consumer_contract.py    # v0.9 manifest/AGENT/probe/检查点契约规则
├── consumer_validation.py  # v0.9 validate-handoff 与 validate-consumer 引擎
├── exports.py              # Codex、CSV、PNG 与 MIDI 导出
├── server.py               # 本地上传、项目与媒体服务
├── mcp/                    # MCP 服务器（service、PathPolicy、runtime bridge）
│   └── runtime_worker.mjs  #   Node worker：共享运行时的时间查询
├── runtime/                # 共享 JavaScript 运行时（网页与导出同源）
│   ├── runtime.js          #   track.at / quantize 等时间查询
│   ├── scene-director.js   #   v0.8 结构场景与转场状态
│   ├── consumer-probe.js   #   v0.9 随导出发布的零依赖包 probe
│   └── visual-profile.js   #   pulse/turbulence/burst/hero 视觉预算
├── agent_skill/            # 打入 ZIP 的可移植 Skill
└── web/
    ├── app.js              # 页面状态和交互
    ├── visual-stage.js     # 舞台控制器：图层、director 帧、质量分级
    ├── particle-geometry.js# 确定性三叶主体与轨道带点集
    ├── particle-shaders.js # WebGL2 顶点/片段着色器
    ├── particle-field.js   # 单 draw call 的 WebGL2 粒子渲染器
    ├── renderer.js         # 仪表刻度、结构与 cue map 渲染
    ├── audio.js            # 单一音频时钟与播放控制
    └── index.html
examples/                    # v0.9 消费同一份冻结包的参考消费者
├── shared/                 #   fixture.beatscope、checkpoints.json、fixture-lock.json
├── canvas-particles/       #   零构建 Canvas 2D 消费者
├── threejs-geometry/       #   three@0.169.0 消费者（依赖仅限示例目录）
└── remotion-composition/   #   Remotion 离线消费者（frame/fps 时钟）
evaluations/                 # MCP evaluation 问答与固定 fixture
└── agent-interoperability/ # v0.9 冻结任务、run recorder、评分表、报告
tests/                       # Python 与 JavaScript 回归测试
skills/beatscope-visualizer/ # 仓库内 Skill
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
beatscope visual-build rhythm.json
beatscope validate-handoff examples\shared\fixture.beatscope --checkpoints examples\shared\checkpoints.json
beatscope validate-consumer examples\canvas-particles
beatscope separate song.wav --output-dir .beatscope-cache\song\stems --model htdemucs --device cuda
beatscope benchmark
beatscope benchmark-visual
beatscope doctor
~~~

运行参考消费者：把仓库根目录用静态服务器打开 —— 例如 <code>python -m http.server 8766</code> 后访问 <code>http://127.0.0.1:8766/examples/canvas-particles/</code> —— 再选择音频文件。Three.js 示例需先 <code>npm install</code> 安装 pinned 依赖；Remotion 组合在其目录内用 <code>npx remotion render</code> 离线渲染。

## MCP 服务器：让 Agent 直接使用节奏事实

BeatScope 内置本地 MCP 服务器（`beatscope_mcp`）。Codex、Claude Desktop 等 MCP 客户端可以不经网页、不读源码，直接分析本地歌曲、按时间窗查询节拍、瞬态与 cue，并导出供 Agent 使用的 handoff ZIP。时间语义（bar/beat 相位、能量插值、onset 脉冲、量化）由与网页播放器和导出包完全相同的 JavaScript 运行时计算，所有路径不会各说各话。

安装与启动：

~~~powershell
pip install -e ".[mcp]"
beatscope-mcp
~~~

服务器走 stdio；分析在本机完成，不向网络发送音频或任何数据。

| 工具 | 作用 |
| --- | --- |
| `beatscope_list_projects` | 列出缓存项目（BPM、小节、backend、provenance） |
| `beatscope_get_project` | 读取 summary / timing / 完整 JSON；结构摘要附带逐段 LOW / MID / HIGH 均值 |
| `beatscope_analyze_audio` | 分析音频并缓存；支持进度与取消，多配置可共存 |
| `beatscope_get_visual_state` | 某一时刻的完整视觉状态，与网页播放器一致；带编译产物时响应追加 `visual` 块（scene、transition、composition） |
| `beatscope_get_events` | (start, end] 区间内的 beats / onsets / cues / patterns / segments / boundaries / scenes |
| `beatscope_export_package` | 导出便携 Agent ZIP（原子写入，含 SKILL 与 schema） |

编译后的视觉产物存放在项目旁边（<code>visual-recipe.json</code>、<code>visual-timeline.json</code>），本地 web API 以相同路径提供它们，<code>beatscope_get_project</code> 会报告存在哪些产物。

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
node --test tests\test_grid.js tests\test_interaction.js tests\test_runtime.js tests\test_scene_director.js tests\test_visual_profile.js tests\test_playback_characterization.js tests\test_playback_state.js tests\test_visual_stage.js tests\test_particle_geometry.js tests\test_particle_uniforms.js tests\test_consumer_probe.js tests\test_canvas_consumer.js tests\test_threejs_consumer.js tests\test_remotion_consumer.js
beatscope validate-handoff examples\shared\fixture.beatscope --checkpoints examples\shared\checkpoints.json
beatscope benchmark
beatscope benchmark-structure
beatscope benchmark-visual
~~~

JavaScript 侧：网格与交互测试覆盖页面行为；runtime、scene-director 与 visual profile 测试覆盖共享运行时契约和纯度约束；characterization 测试比较网页播放器与导出两条路径在同一时间点的输出一致性；visual-stage、particle-geometry 与 particle-uniform 测试固定了确定性 director 帧、点集确定性与 uniform 转换，并覆盖自适应质量分级与强制回退路径。consumer 套件固定打包的 probe 以及 Canvas、Three.js、Remotion 三个消费者：声明诚实性、seek 确定性、reduced-motion 缩放、fps 不变的离线状态，以及对照共享 fixture 的检查点一致性。Python 套件还会断言构建出的 wheel 携带 probe 与粒子模块、每个示例都守在自己的声明之内、入库的评估证据可以逐字节重放。结构测试覆盖按小节聚合的特征提取、边界与家族不变量、可选 schema 块、runtime 段落查询以及 MCP/导出一致性；结构基准把十个合成编曲对照冻结真值考核。视觉配方测试固定编译、身份与持久化规则，视觉基准测试固定门槛策略、每个门槛背后的运动语义，以及检查点文件逐字节一致的再生成。MCP 测试覆盖工具契约、路径安全、运行时一致性与导出。GitHub Actions 在 Windows 与 Ubuntu、Python 3.10 与 3.12 上运行核心检查，外加一个 pinned consumer-evidence 任务验证 handoff 并强制示例 lockfile，以及一个带缓存的 Remotion 任务执行短离线渲染。

## 已知限制

- 结果取决于 Coding Agent 与视觉需求本身；BeatScope 提供确定性的音乐时序，而不是成品美术指导。
- v0.9 参考消费者基于 JavaScript；其他技术栈同样可以消费这份包，但未在此演示。
- BeatScope 不识别乐器、情绪、歌词或语义上的歌曲角色。结构家族保持中性字母（<code>A</code>、<code>B</code>、<code>A′</code>），只表示重复关系，不是 Verse/Chorus。
- 导出不包含源音频；包内只有时序事实。
- 示例证明的是契约可移植性，不是普遍的框架支持。
- 第三方依赖包与 Agent 生成的代码使用前仍需人工审查。
- 内置分析不会可靠识别 kick、snare 或 808 身份，只报告瞬态和频段事实。
- WebGL2 粒子乐器最多渲染 18,000 个主体点外加三条轨道带；WebGL2 不可用时 Canvas 2D 回退保持刻意较小的固定主体预算（最多 680 点），因此极高分辨率录屏仍建议使用支持 WebGL2 的浏览器。
- 全曲结构检测宁可诚实也不强行切分：渐变演化、过短的音频和不清晰的重复都可能合法地只产生一个段落；边界携带的是 novelty 权重，而不是确定性声明。
- 编译出的视觉配方描述的是结构，不是艺术指导：家族 motif 与调色板槽位是中性、确定性的起点，变体只做两处有界次要变化，<code>BREAK</code> 保持保留的悬置处理 —— 配方绝不把重复关系变成音乐角色。
- 浏览器验证层在本版本中如实报告 <code>unavailable</code>：交互播放/跳转通过 Node probe 与示例测试套件验证，尚未通过自动化浏览器检查。
- MP3 支持取决于本机 libsndfile 或 FFmpeg。
- 这是本地创作与参考工具，不是 DAW、FLP 生成器或精确鼓组转录器。

## 项目状态

BeatScope 现在覆盖从音频上传到可播放视觉、全曲结构、8 小节 cue map、MCP 查询与可移植 handoff 包的完整本地流程。v0.6 建立了真实时间轴变速追踪和粒子乐器，v0.7 加入中性的结构分段与重复家族，v0.8 再把结构编译成由播放器、MCP 和导出共同使用的确定性视觉配方与场景时间轴，v0.8.1 补齐了实际交接路径（逐段能量摘要、经过测试的模块 Worker 适配器）。v0.9 把导出变成自描述契约 —— manifest、AGENT 路由、零依赖 probe —— 由 <code>validate-handoff</code> 与 <code>validate-consumer</code> 验证，并用三个互相独立的参考消费者（Canvas 2D、Three.js、Remotion）驱动同一份冻结 fixture 来证明，同时附带冻结的跨 Agent 评估基础设施（其运行记录诚实为零）。软件包版本为 0.9.0，音频分析器有意保持 0.7.0，视觉配方契约保持 0.8.0。它仍是个人实验，但公开时序契约已经由回归测试固定，而不是只写在说明里。

## License

本项目使用 [MIT License](LICENSE)。
