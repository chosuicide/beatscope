# BeatScope 公开版工程规格书

> 目标读者：接手项目的开发者或能力一般的编码 AI。严格按阶段执行，不要跳步，不要擅自更换技术栈。

## 1. 产品结论

BeatScope 不是普通音乐可视化器，也不是“AI 自动扒鼓谱”。它是面向 FL Studio、Ableton Live 等 DAW 用户的本地节奏参考工具：

1. 拖入一首歌。
2. 自动建立可信的拍点和小节网格。
3. 显示综合、低频、中频、高频、重音五条节奏轨道。
4. 同时显示原始瞬态和量化位置，让用户看到 groove offset。
5. 点击任意格试听该瞬态。
6. 导出通用 rhythm reference MIDI、JSON 和截图。
7. 可选生成与歌曲同步的动态视觉预览。

一句话介绍：

> Turn any song into a DAW-ready rhythm reference map.

核心差异不是“识别 kick/snare/808”。除非模型置信度经过严格验证，否则产品只陈述事实：时间、频段、强度、拍点、偏移和相似结构。

## 2. 成功标准

公开版必须满足：

- 新用户安装后，拖入歌曲即可完成分析，不需要手动运行 Beat This 或寻找 Demucs stem。
- 分析过程有阶段进度、取消、错误恢复和缓存。
- 同一文件、同一配置得到完全一致的 JSON。
- 1/16 和 1/32 来回切换不会改变原始时间。
- 播放、点击试听、循环窗口和播放头保持同步。
- README 第一屏能在 10 秒内解释价值。
- 提供一个可公开分发的短音频示例，禁止提交 Night Owl 原文件。
- Windows 首先做到一条命令启动；随后补 macOS/Linux。

不要承诺星数。GitHub 传播目标应是：独特、可运行、有演示、有清晰技术解释。

## 3. 明确不做

- 不把频段能量伪装成 kick、snare、hi-hat 或 808。
- 不默认联网，不上传用户音频。
- 不在第一版引入账号、云同步、协作、订阅或数据库。
- 不迁移到 React/Vue。当前 vanilla HTML/CSS/JS 足够，先把产品闭环做好。
- 不加入十几种彩色频谱模式。动态视觉属于可选输出，不是主页核心。
- 不让 BPM 手工修正覆盖原始分析文件。修正只存入 project adjustments。

## 4. 当前代码资产

保留并逐步整理：

```text
beatscope/
  analysis.py       # 旧版轻量乐器候选分析，仅作为 legacy
  high_quality.py   # 旧版高质量实验路径，仅作为 legacy
  rhythm.py         # 当前事实性节奏地图核心
  separation.py     # Demucs stem 支持
  midi.py           # MIDI 基础写入
  server.py         # 本地 HTTP 服务
  cli.py            # CLI 入口
  web/
    index.html
    style.css
    app.js
tests/
.beatscope-cache/
videos/night-owl-pulse-preview/  # 实验性动态视觉，不进入发行包
```

新增模块：

```text
beatscope/
  project.py        # 项目目录、内容哈希、配置与缓存
  jobs.py           # 分析任务状态、取消和阶段进度
  audio_io.py       # 解码、重采样、时长和媒体类型验证
  beatgrid.py       # Beat This 调用、解析、拍点插值和 fallback
  features.py       # STFT、多频段 novelty、瞬态检测
  structure.py      # 小节向量、相似组、break/fill 解释标签
  exports.py        # rhythm MIDI、CSV、PNG 数据准备
  schema.py         # v3 schema 生成和验证
  web_api.py        # API handler 逻辑，与 server.py 分离
beatscope/web/
  app.js            # 入口与控制器
  state.js          # 单一状态容器
  api.js            # fetch 与 job polling
  audio.js          # 播放、循环、短试听
  grid.js           # 时间与格子换算纯函数
  renderer.js       # Canvas 静态层和播放头层
  inspector.js      # 选择详情
  import.js         # 拖放、上传、进度
```

如果不使用 JS modules，则仍按这些职责拆文件，并在 index.html 中按依赖顺序加载。不要重新塞回一个超长 app.js。

## 5. 项目目录与缓存

每首歌建立独立项目：

```text
.beatscope-cache/projects/<sha256-prefix>/
  project.json
  source.json
  analysis-config.json
  rhythm.json
  adjustments.json
  waveform.json
  stems/
  exports/
  logs/
```

内容哈希逻辑：

```python
def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
```

缓存键必须包含：

```python
cache_key = sha256(
    audio_sha256
    + schema_version
    + analyzer_version
    + canonical_json(analysis_config)
)
```

禁止只用文件名缓存。两个同名文件可能不同，一个文件改名后内容仍相同。

## 6. v3 数据结构

`rhythm.json` 顶层：

```json
{
  "schema_version": "3.0",
  "project_id": "12-char-hash",
  "source": {},
  "analysis": {},
  "tempo": {},
  "grid": {},
  "beats": [],
  "onsets": [],
  "energy": {},
  "overview": [],
  "exports": {}
}
```

关键字段：

```json
{
  "source": {
    "display_name": "song.wav",
    "duration": 153.8214,
    "sample_rate": 44100,
    "channels": 2,
    "sha256": "..."
  },
  "analysis": {
    "pipeline": "beat-this+demucs-drums+multiband-novelty",
    "analyzer_version": "0.3.0",
    "created_at": "ISO timestamp",
    "warnings": [],
    "separation_used": true
  },
  "tempo": {
    "global_bpm": 130.435,
    "confidence": 0.91,
    "variable_tempo": false
  },
  "grid": {
    "time_signature": [4, 4],
    "origin": 3.68,
    "default_subdivision": 16,
    "bars": 82
  }
}
```

Beat：

```json
{
  "time": 3.68,
  "beat": 1,
  "bar": 1,
  "downbeat": true,
  "confidence": 0.94,
  "sequence_gap": false
}
```

Onset 永远保存原始事实，不把当前 UI subdivision 写死：

```json
{
  "id": 173,
  "raw_time": 4.6208,
  "strength": 0.4238,
  "bands": {
    "all": 0.4238,
    "low": 0.0312,
    "mid": 0.3911,
    "high": 0.0221
  },
  "accent": false,
  "confidence": 0.71
}
```

`bar/beat/step/quantized_time/offset_ms` 应由前端或导出器根据当前网格即时计算。不要永久写入 onset，否则切换 1/16 与 1/32 容易产生旧元数据。

Energy 应压缩体积。不要保存每个 STFT frame 的冗长对象：

```json
{
  "energy": {
    "fps": 100,
    "start": 0,
    "bands": {
      "all": [0.0, 0.02, 0.15],
      "low": [0.0, 0.01, 0.04],
      "mid": [0.0, 0.01, 0.12],
      "high": [0.0, 0.0, 0.02]
    }
  }
}
```

服务端可返回紧凑 JSON；开发模式可 `indent=2`。

## 7. 音频分析流水线

### 7.1 导入与验证

支持 WAV、FLAC、MP3、OGG、M4A。流程：

1. 读取文件头，不只相信扩展名。
2. 限制默认最大 500 MB，可通过 CLI 配置。
3. 用 soundfile 优先解码；不支持的格式调用系统 ffmpeg。
4. 分析统一转换为 mono float32，但原文件保留供播放。
5. 峰值超过 1 时归一化，记录 warning，不静默修改源文件。

```python
def load_analysis_audio(path, target_sr=44100):
    y, sr = decode(path)
    y = to_mono_float32(y)
    if sr != target_sr:
        y = librosa.resample(y, orig_sr=sr, target_sr=target_sr)
        sr = target_sr
    return y, sr
```

### 7.2 分离策略

默认设置：`separation=auto`。

- 如果 Demucs 可用，提取 drums stem，并把原音作为辅助。
- 如果 Demucs 不可用，继续使用原音，但在结果中写 warning。
- `separation=off` 强制跳过。
- 缓存 stem，绝不重复分离相同文件。

进度阶段：

```text
decode 0-10%
separate 10-55%
beatgrid 55-70%
features 70-88%
structure 88-96%
serialize 96-100%
```

### 7.3 拍点与小节

优先 Beat This。封装为适配器，不让 CLI 输出格式泄漏到其他模块：

```python
class BeatGridAnalyzer:
    def analyze(self, audio_path: Path) -> BeatGridResult: ...
```

解析规则：

- 时间必须严格递增。
- beat 只能为 1、2、3、4。
- 如果第一行不是 beat 1，前面的不完整小节标记为 bar 0。
- beat 序列不是预期的下一拍时，`sequence_gap=true`。
- BPM 使用相邻 beat interval 的中位数，排除 MAD 异常值。

```python
intervals = np.diff(beat_times)
median = np.median(intervals)
mad = np.median(np.abs(intervals - median))
valid = intervals[np.abs(intervals - median) <= max(3 * mad, 0.03)]
bpm = 60 / np.median(valid)
```

不要仅用 `origin + n * 60/bpm` 代替真实 Beat This 时间。量化时使用真实相邻 beats 插值：

```python
def quantize_to_beat_grid(t, beats, subdivision):
    left_index = searchsorted(beat_times, t) - 1
    left = beats[left_index]
    right = beats[left_index + 1]
    parts_per_beat = subdivision // 4
    candidates = [
        left.time + (right.time - left.time) * part / parts_per_beat
        for part in range(parts_per_beat + 1)
    ]
    q = min(candidates, key=lambda candidate: abs(candidate - t))
    return q, (t - q) * 1000
```

Beat This 在歌曲尾部停止时，不应把后面整段伪造成稳定拍点：

- 如果尾部 drums energy 很低，标记 `untracked_silence`。
- 如果尾部仍有明显能量，尝试以最后 8 个可信间隔短距离外推，最多 8 小节，并写 warning。
- UI 用虚线区分推测网格。

### 7.4 多频段能量

使用 STFT：

```python
n_fft = 2048
hop = 256
spectrum = abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
```

频段：

```text
LOW   20-180 Hz
MID   180-4000 Hz
HIGH  4000-min(16000, Nyquist) Hz
ALL   三者加权和
```

novelty 不是原始能量，而是正向变化：

```python
energy = np.mean(spectrum[mask], axis=0)
novelty = np.maximum(0, np.diff(np.log1p(energy), prepend=energy[:1]))
```

Robust normalization，禁止大量硬截断为 1：

```python
lo = np.percentile(values, 10)
hi = np.percentile(values, 99.5)
normalized = np.clip((values - lo) / max(hi - lo, 1e-8), 0, 1)
compressed = np.sqrt(normalized)
```

验收：`strength >= 0.99` 的比例默认应小于 2%。超过则 normalization 有问题。

### 7.5 瞬态检测

使用局部峰值与最小间距，不要依赖 scipy 才能运行：

```python
candidate = (
    values[1:-1] >= values[:-2]
    and values[1:-1] > values[2:]
    and values[1:-1] >= adaptive_threshold
)
```

阈值：

```python
threshold = max(0.10, percentile(novelty_all, 75))
minimum_distance_sec = 0.045
```

峰值冲突时保留更强者。每个 onset 的 bands 读取同一 frame 的归一化值。

Accent 不用固定 `strength >= 0.72`，改用歌曲分段统计：

```python
local_window = strengths within +/- 4 bars
accent = strength >= percentile(local_window, 85)
```

### 7.6 小节相似组

为每小节建立向量：

```text
[16 个 ALL step max,
 16 个 LOW step max,
 16 个 MID step max,
 16 个 HIGH step max,
 mean energy,
 onset count normalized]
```

向量先做 L2 normalization。Break 判定必须结合平均能量和 onset 数：

```python
is_break = mean_energy < song_energy_p20 and onset_count <= 1
```

相似组算法不必引入 sklearn：

```python
centroids = []
for bar_vector in audible_bars:
    similarities = [cosine(bar_vector, c) for c in centroids]
    if similarities and max(similarities) >= 0.86:
        group = argmax(similarities)
        centroids[group] = 0.8 * centroids[group] + 0.2 * bar_vector
    else:
        centroids.append(bar_vector.copy())
        group = len(centroids) - 1
```

组名 A、B、C。标签解释：

- `break`：低能量且瞬态极少。
- `repeat`：与已有组匹配。
- `fill`：末拍能量显著高于本小节前 3 拍，且不是 break。
- `change`：建立新组。

不要输出 verse、chorus、drop，除非以后有专门模型。

## 8. 后端任务与 API

不要在 HTTP request 中同步跑 Demucs。使用内存任务管理器，单用户本地应用不需要 Redis。

```python
class Job:
    id: str
    state: Literal["queued", "running", "complete", "failed", "cancelled"]
    stage: str
    progress: float
    message: str
    error: str | None
    project_id: str | None
    cancel_event: threading.Event
```

ThreadPoolExecutor 默认 `max_workers=1`，防止同时跑两个 Demucs 爆显存。

API：

```text
POST   /api/jobs/analyze          raw audio body，返回 job_id
GET    /api/jobs/<job_id>         状态与进度
DELETE /api/jobs/<job_id>         请求取消
GET    /api/projects              最近项目列表
GET    /api/projects/<id>         rhythm.json
GET    /api/projects/<id>/audio   原音，支持 Range
GET    /api/projects/<id>/stem?name=drums
POST   /api/projects/<id>/adjustments
GET    /api/projects/<id>/export/rhythm.mid?subdivision=16
GET    /api/projects/<id>/export/rhythm.csv
```

上传要求：

- 使用临时文件流式写入，禁止一次性读入内存。
- 检查 Content-Length，但也必须限制实际读取量。
- 临时文件在成功或失败后都删除。
- 文件名只取 `Path(name).name`，避免路径穿越。

媒体响应实现 Range，否则长音频 seek 很慢：解析 `Range: bytes=start-end`，返回 206、Content-Range 和 Accept-Ranges。

## 9. 前端状态

唯一状态对象：

```javascript
const state = {
  project: null,
  subdivision: 16,
  viewBars: 4,
  startBar: 0,
  selectedOnsetId: null,
  loop: false,
  playbackTime: 0,
  job: null,
  adjustments: { bpm: null, origin: null },
};
```

禁止组件各自保存 BPM 副本。所有转换经过 `grid.js`：

```javascript
export function gridPosition(rawTime, project, subdivision, adjustments) {
  // 优先真实 beat 数组进行局部插值。
  // fallback 才用 global BPM。
  // 返回 bar、beat、stepInBar、quantizedTime、offsetMs、confidence。
}
```

需要给这个纯函数写大量单元测试。

## 10. Canvas 渲染逻辑

画布分两层：

```html
<div class="map-stack">
  <canvas id="mapStatic"></canvas>
  <canvas id="mapOverlay"></canvas>
</div>
```

- static：lane、能量曲线、格线、真实拍点、onset、timing needles。窗口改变时重画。
- overlay：播放头、hover、selected cell。播放时每帧只重画 overlay。

这样避免当前版本播放时反复扫描全部 energy frames。

Retina 尺寸：

```javascript
function resizeCanvas(canvas, cssWidth, cssHeight) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(cssWidth * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  canvas.style.width = `${cssWidth}px`;
  canvas.style.height = `${cssHeight}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
```

绘制顺序必须固定：

1. 纸张背景和 lane alternating fill。
2. 连续 energy envelope，10% fill + 50% stroke。
3. 1/16 或 1/32 格线。
4. 真实 Beat This beat/downbeat marker。
5. 量化 onset 柱。
6. raw timing needle 与 quantized cell 的连线。
7. selected cell。
8. overlay canvas 的 playhead。

窗口内 energy 数据用二分查找起止 index，不要每帧遍历全曲：

```javascript
const startIndex = lowerBound(times, visibleStart);
const endIndex = upperBound(times, visibleEnd);
```

视觉规范：

- 保持当前“复古企业仪表”：暖灰纸张、炭黑、橄榄绿。
- 不使用渐变、发光、彩虹或粒子。
- 复古感来自排版、方角、测量线和纸张色，不加故障噪声。
- 小节线最重，拍线中等，细分格最浅。
- 真实 beat marker 与理论量化线必须能区分。
- Onset 强度控制高度，不控制随机颜色。

## 11. 播放与试听

主播放使用一个 `<audio>`。禁止创建多个音频元素。

短试听：

```javascript
function previewTransient(rawTime) {
  clearTimeout(previewTimer);
  audio.currentTime = Math.max(0, rawTime - 0.05);
  audio.play();
  previewTimer = setTimeout(() => audio.pause(), 140);
}
```

生产版应记住点击前是否正在播放：如果用户原本播放中，140 ms 后恢复原播放状态，而不是无条件 pause。

Loop：

```javascript
loopStart = timeAtBar(startBar)
loopEnd = timeAtBar(startBar + viewBars)
if (loop && audio.currentTime >= loopEnd - 0.01) {
  audio.currentTime = loopStart
}
```

使用真实 downbeat 时间计算 bar 边界。只有真实拍点缺失时才用 BPM fallback。

## 12. 导出

### Rhythm reference MIDI

定义为参考 MIDI，不是鼓谱：

- Note 60：所有瞬态。
- Velocity：`round(strength * 126) + 1`。
- Note length：30 ticks。
- Tempo meta：global BPM。
- 轨道名：`BeatScope Rhythm Reference`。

可选多轨模式：

- LOW → note 36
- MID → note 38
- HIGH → note 42

必须标注这是频段映射，不是乐器识别。

### CSV

```text
raw_time,quantized_time,offset_ms,bar,beat,step,strength,low,mid,high,accent
```

### PNG

使用 static canvas 生成当前窗口 2x PNG。导出前临时隐藏 hover 和播放头。

## 13. UI 必须补齐的界面

### 空状态

主画布区域显示：

```text
拖入一首歌建立节奏地图
WAV / FLAC / MP3 / OGG / M4A，音频仅在本机处理
[选择音频]
```

允许整个窗口 drag-and-drop，拖入时出现明确边框，不要 modal。

### 分析中

显示真实阶段：分离鼓组、建立拍点、提取瞬态、比较小节。不要只显示旋转 spinner。

### 错误

区分：格式不支持、Beat This 失败、Demucs 显存不足、磁盘空间不足。每个错误提供下一步。

### 项目已加载

顶部显示文件名、时长、BPM、分析方法。不要显示“AI confidence”营销话术。

## 14. CLI

保留：

```powershell
beatscope analyze song.wav --output project-dir
beatscope serve --project project-dir/rhythm.json
beatscope export project-dir/rhythm.json --midi rhythm.mid --subdivision 16
beatscope doctor
```

`doctor` 检查：Python、ffmpeg、Beat This、Demucs、CUDA、可写缓存目录、空闲磁盘。输出清楚的 PASS/WARN/FAIL。

不要让 Web UI 依赖用户先运行 CLI。

## 15. 测试计划

### Python 单元测试

- Beat This 第一拍不是 1，首个 partial bar 为 0。
- beat 时间不递增时失败。
- beat sequence gap 正确标记。
- constant 120 BPM 得到 0.5 s beat interval。
- variable tempo 使用真实 beats 局部插值。
- 1/16 与 1/32 quantization offset 正确。
- normalization 不产生大量 1.0。
- sustained sine 不产生重复瞬态。
- click track 在正确格子产生 onset。
- break 需要低能量且 onset 少。
- 相同 bar vector 进入同一 group。
- 缓存键随配置改变。
- Range 请求返回正确 byte slice。
- 上传超限时不会留下临时文件。

### JS 测试

- `gridPosition` 在 1/16、1/32 间可逆。
- rawTime 永远不变。
- startBar clamp 正确。
- loop boundary 使用真实 bar time。
- hover/click 坐标在 DPR=1、1.5、2 时一致。
- selected onset 切 subdivision 后详情同步更新。

### 浏览器 smoke

- 首页 200。
- 拖入公开 demo 音频。
- 看到每个进度阶段。
- 分析完成后 onsets > 0。
- 点击格子，audio.currentTime 接近 raw_time。
- 切到 1/32，再切回 1/16，选择未丢失。
- 打开循环，播放跨过 loopEnd 后回到 loopStart。
- 控制台无 error/warn。
- 1280、1440、移动宽度无横向页面溢出；Canvas 自身可横向滚动。

## 16. 性能预算

- 首屏静态资源小于 250 KB，不含音频和 JSON。
- 不引入前端框架。
- 播放期间 overlay 绘制目标 60 fps，主线程每帧小于 8 ms。
- rhythm.json 建议小于 2 MB；energy 使用数组、降采样或 gzip。
- API 开启 gzip JSON。
- 分析期间 UI polling 500 ms；完成后停止 polling。

## 17. 发布与 README

README 第一屏顺序：

1. Logo + 一句话。
2. 8-12 秒 GIF：拖入歌曲、出现节奏图、点击瞬态、导出 MIDI。
3. 三条价值，不写十条 feature。
4. 安装命令。
5. “Why BeatScope is different”：事实性频段，不伪装乐器标签。

建议英文主 README，提供 `README.zh-CN.md`。

示例：

```markdown
# BeatScope

Turn any song into a DAW-ready rhythm reference map.

- Real beat and downbeat alignment
- Multiband transient map with groove offsets
- Click-to-preview and MIDI/CSV export
```

必须包含：

- 演示 GIF 和两张高清截图。
- 30 秒安装视频或终端录屏。
- 支持格式和硬件要求。
- Beat This、Demucs 等依赖的许可证与署名。
- 隐私说明：local-only processing。
- Known limitations。
- Roadmap。
- CONTRIBUTING.md、CODE_OF_CONDUCT.md、SECURITY.md、MIT LICENSE。

不要提交受版权保护的 Night Owl 音频、stem、JSON 绝对路径或缓存。

## 18. 安装体验

第一阶段 Windows：

```powershell
git clone <repo>
cd beatscope
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
beatscope doctor
beatscope serve
```

第二阶段提供：

- `install.ps1`，但脚本必须可读且支持 `-WhatIf`。
- GitHub Release portable ZIP。
- 后续再考虑 PyInstaller，不要一开始打包 CUDA Demucs。

提供两档：

- Core：无需 GPU，原音分析。
- HQ：Demucs + Beat This，推荐 NVIDIA GPU 或允许 CPU 慢速运行。

## 19. 分阶段施工单

### Milestone 1：代码整理与 schema v3

- 新建 schema.py、project.py、beatgrid.py、features.py、structure.py。
- 把 rhythm.py 拆成 orchestration，不超过约 200 行。
- 建立 v2 → v3 migration。
- 所有现有测试继续通过，再新增 schema 测试。

验收：CLI 能对 Night Owl 本地文件生成 v3 JSON；输出不含绝对路径，除 project.json 的本地私有字段外。

### Milestone 2：拖放即分析

- jobs.py + 新 API。
- 空状态、drag/drop、进度状态、取消。
- 缓存命中时 1 秒内打开已有项目。

验收：从未运行过 CLI 的浏览器用户能完成一次分析。

### Milestone 3：可信网格

- 真实 beats 局部插值。
- variable tempo、partial bar、tail fallback。
- adjustments 独立保存。

验收：测试 click track、缓慢 tempo drift 和首拍不完整样本。

### Milestone 4：Canvas 性能与视觉

- static/overlay 双层 Canvas。
- 连续能量、量化柱、timing needle、真实 beat marker。
- DPR/ResizeObserver。
- PNG export。

验收：Night Owl 播放时稳定，Canvas 无模糊，交互和当前版本一致。

### Milestone 5：导出与发布材料

- MIDI、CSV、PNG。
- doctor。
- 公开示例音频。
- README GIF、双语文档、许可证。

验收：全新 Windows 环境按 README 能运行。

## 20. 给编码 AI 的执行规则

将下面内容与本文件一起交给接手 AI：

```text
你正在维护 BeatScope。先完整阅读 BUILD_SPEC.md、README.md、pyproject.toml、beatscope/rhythm.py、beatscope/server.py、beatscope/web/* 和 tests/*。

规则：
1. 一次只完成一个 Milestone 中的一个可验收子任务。
2. 修改前列出会动的文件和保持不变的行为。
3. 不迁移框架，不删除 legacy 功能，不引入云服务。
4. 所有文件编辑使用补丁，保留用户现有修改。
5. 新逻辑先写纯函数和测试，再接 UI/API。
6. 不伪造 kick/snare/808 标签。
7. raw_time 是事实，不得因 subdivision 改变。
8. 每次完成必须运行 pytest、node --check 和对应浏览器 smoke。
9. 如果测试失败，修复后再继续，不得把失败写成“已知问题”跳过。
10. 不提交 Night Owl 音频、stems、缓存或包含用户绝对路径的文件。
11. 不执行 git commit，除非用户明确要求。
12. 完成后报告：修改文件、数据迁移、测试结果、性能变化、剩余限制。

当前任务：<把一个明确子任务写在这里，不要只说“完成整个项目”>
```

推荐给弱 AI 的任务顺序：

1. “只实现 schema.py 与测试，不改其他运行逻辑。”
2. “只抽取 beatgrid.py，保持 rhythm.py 输出不变。”
3. “只抽取 features.py 并证明 Night Owl 统计接近现状。”
4. “实现 project.py 内容哈希和缓存测试。”
5. “实现 JobManager，不接 UI。”
6. “接 POST/GET/DELETE jobs API。”
7. “实现拖放和进度 UI。”
8. “拆分 grid.js 并写前端测试。”
9. “实现双 Canvas renderer。”
10. “完成 README 与 release checklist。”

不要让能力一般的 AI 一次改后端、前端、算法和发布材料。它会失去边界并破坏已有功能。

## 21. 最终发布门槛

以下全部满足才发布 `v0.3.0`：

- [ ] 全新用户可拖入歌曲分析。
- [ ] 缓存与取消有效。
- [ ] 真实 beat 局部量化。
- [ ] v3 schema 有验证与 migration。
- [ ] 1/16、1/32 可逆。
- [ ] Canvas 双层且播放流畅。
- [ ] MIDI、CSV、PNG 可下载。
- [ ] Core 模式无需 GPU。
- [ ] HQ 模式缺依赖时给明确说明。
- [ ] pytest、JS tests、browser smoke 全过。
- [ ] README GIF 和双语文档完成。
- [ ] LICENSE 与第三方署名完成。
- [ ] 仓库不含 Night Owl 或任何用户绝对路径。
- [ ] GitHub Actions 在 Windows、Ubuntu 运行 Core tests。

达到这些门槛后，BeatScope 才不只是好看的个人原型，而是别人愿意安装、收藏、转发和参与贡献的开源工具。
