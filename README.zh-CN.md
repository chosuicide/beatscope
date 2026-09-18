# BeatScope

[English](README.md) | 简体中文

[![CI](https://github.com/chosuicide/beatscope/actions/workflows/ci.yml/badge.svg)](https://github.com/chosuicide/beatscope/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.12.1-c65032)](https://github.com/chosuicide/beatscope/releases/tag/v0.12.1)
[![License: MIT](https://img.shields.io/badge/license-MIT-171713.svg)](LICENSE)

**上传一首歌，生成踩准节奏的影片；也可以把准确时序交给 Coding Agent。**

BeatScope 会测量拍点、真实瞬态、能量变化、速度变化和重复段落。Beathi Studio 用这些数据生成影片预览，也能导出一份可复用的时序包。所有处理都在本机完成，音频不会上传。

[![观看 BeatScope 产品演示](docs/demo/product-tour-loop.webp)](https://github.com/chosuicide/beatscope/releases/download/v0.12.0/beatscope-v0.12.0-product-tour.mp4)

**[▶ 观看 57 秒产品演示](https://github.com/chosuicide/beatscope/releases/download/v0.12.0/beatscope-v0.12.0-product-tour.mp4)**

## 你只需要做三步

1. 上传 WAV、FLAC、MP3、OGG 或 M4A 音频。
2. 查看影片预览、歌曲结构和节奏图。
3. 渲染视频、导出 MIDI/CSV，或者把 `.beatscope` 包交给 Coding Agent。

![Beathi Studio 播放影片，节奏图与同一个音频时钟同步](docs/demo/beathi-studio.gif)

## 下载与运行

### Windows

下载 **[Beathi Studio v0.12.1](https://github.com/chosuicide/beatscope/releases/download/v0.12.1/Beathi-Studio-v0.12.1-windows-x64.zip)**，解压后双击 **Beathi Studio.exe**。便携包已经带好分析器、浏览器和 FFmpeg。

### Python 3.10+

从 [v0.12.1 Release](https://github.com/chosuicide/beatscope/releases/tag/v0.12.1) 下载 wheel，然后运行：

```powershell
pip install beatscope-0.12.1-py3-none-any.whl
beatscope serve --open
```

## 两种实用输出

### 直接观看的影片

内置模板会立即生成音乐影片预览，也可以渲染成 MP4。预览、播放头和节奏图使用同一个音频时钟；拖动进度不会重新分析歌曲。

### Coding Agent 能使用的时序

![Coding Agent 根据 BeatScope 时序和视觉参考制作另一种影片](docs/demo/agent-to-film.webp)

导出 `.beatscope` 包，再把它与你的影像、图片或参考作品一起交给 Agent。包里只有测量所得的时序，没有锁死视觉风格，因此 Agent 可以创造新作品，也不需要猜音乐在什么时候落下。

```text
你的歌曲
   ↓
BeatScope 测量准确时序
   ↓
.beatscope 包 + 你的素材 + 你的想法
   ↓
Coding Agent 制作视觉作品
```

## BeatScope 会测量什么

![全曲结构和八小节节奏细节](docs/demo/beathi-analysis-map.png)

- 拍、小节和速度变化；
- 原始瞬态时间——不会为了整齐把声音吸附到拍格；
- LOW / MID / HIGH 三段能量；
- A / B / A′ 这类中性的重复结构；
- 密集歌曲的可选响应排序，避免画面什么都响应。

BeatScope 不会假装知道某个声音一定是底鼓、军鼓或 808。它只提供可验证的事实，由渲染器决定如何表现。

<details>
<summary><strong>Agent 包里有什么？</strong></summary>

其中包含 `rhythm-map.json`、MIDI、CSV、确定性 JavaScript runtime、自检脚本、成员哈希和简短的 Agent 使用说明。它不包含源音频、视觉模板，也不会替用户预设创作任务。

`response_relevance` 只负责给已有瞬态排序。它不是概率、置信度或“音乐真理”；任何瞬态都不会被新建、删除或移动。

</details>

## 开发者入口

```powershell
git clone https://github.com/chosuicide/beatscope.git
cd beatscope
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,mcp]"
beatscope serve --open
```

项目还提供：

- 本地 stdio MCP 服务，用于分析和有界时序查询；
- Beathi Studio 内的七个 WebMCP 工具；
- 可用于 Web Worker 和离线渲染器的确定性 runtime；
- Canvas、Three.js 和 Remotion 参考消费者。

继续阅读：[影片渲染器](docs/local-movie.md) · [MCP](docs/mcp.md) · [WebMCP](docs/webmcp-studio.md) · [Agent Skill](skills/beatscope-visualizer/SKILL.md)

## 目前的限制

- Studio 当前只内置一套影片模板。
- 结构字母只表示重复关系，不代表主歌、副歌或情绪。
- 真实音乐上的拍点、速度和结构评测仍需要更广泛的公开基准。
- MP3 支持依赖本机 libsndfile 或 FFmpeg。

## 许可证

[MIT](LICENSE)
