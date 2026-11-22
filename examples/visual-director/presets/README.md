# 可选风格配方库（`presets/` — Layer 3）

这里收录的是已经实测跑通的**可选风格配方示例**。

> **重要原则**：`presets/` **绝不是限制**。任何用户想要全新风格（如二次元手绘、柔和胶片、极简歌词排版、复古 VHS、赛博霓虹、3D 建筑漫游等），导演 LLM 都可以直接基于 Layer 1（通用铁律）+ Layer 2（渲染管线箱）现场定制，完全无需套用本目录下的任何配方。

## 已收录实战配方

| 配方文件 | 风格气质 | 推荐渲染管线（Layer 2） | 推荐 Lint Profile | 典型特征 |
| --- | --- | --- | --- | --- |
| [`darkroom_brutalist.md`](darkroom_brutalist.md) | 暗房实验 / 粗粝胶片 / 零文字物理摧毁 | `3D-Scene-Pass` | `strict-darkroom` | 24fps、高角度正午硬光、16-bit 景深约束像素拉丝、零羽化死黑抠洞、Bayer 4×4 暗房网点与 6fps 粗颗粒焊死 |
| [`hyper_keshiki.md`](hyper_keshiki.md) | 日系清透 60fps / 金属雕塑 × 多底板平面设计 | `Layer-Decoupled` | `editorial-kinetic` | 60fps、液态银铬/冰晶玻璃透明前景、统一胶片色域底板轮换、半调网点蓝图、非对称画册分栏、子弹时间定格 |
| [`in_place_mutation.md`](in_place_mutation.md) | 同背景原位局部异变 / 表里世界白昼见鬼 | `Layer-Decoupled` | `universal-baseline` | 背景天空与曝光 100% 锁死不动，仅抠出云层/局部物体踩拍原地异变，配合双世界物理环境反射球同步翻转 |
