# 风格配方：`darkroom_brutalist`（暗房实验 / 零文字物理摧毁）

- **推荐管线（Layer 2）**：`3D-Scene-Pass`（Blender Cycles/EEVEE 输出 `beauty` + 16-bit `depth` + 硬边 `mask`）
- **推荐帧率**：`24fps`（配合 `6fps` 阶梯抽帧双时钟拉扯）
- **推荐 Lint Profile**：`strict-darkroom`（零文字、零 Blur、零 Bloom）

## 核心美学配方
1. **光影骨架**：高角度硬阴影 `SUN` 灯（`angle = 0.012~0.025 rad`），受光面接近轻微过曝溢白，杜绝灰扑扑棚拍感；叠加基于 `frame_idx` 播种的 `1~2px` 确定性微晃。
2. **像素摧毁算子（复用 `pipeline/opencv_fx.py`）**：
   - `depth_hard_cutout`：仅在筛选后的强 `cueHits` 触发 3–5 帧素数长度死黑裂缝，`dilate_px >= 2` 吃净 1px 抗锯齿白边；
   - `fast_pixel_sort_band`：受 16-bit `depth` 约束，前景实体遮挡物纹丝不动，仅中远景炸开像素瀑布；
   - `slit_scan_xerox_array`：高潮段 6fps 阶梯步进扫描仪卡纸列阵 + 1px 死黑裁切线；
   - `stepped_iris_close` → `unified_media_pass`：末尾 4 档阶梯光圈/闸刀收口**必须位于**全图锁频粗颗粒与 Bayer 4×4 暗房网点之前，让粗颗粒吃掉一切光滑几何边缘。
3. **适用题材**：暗房印刷机、工业机械、黑白胶片实验影像、零文字高对比“白天见鬼”物理摧毁风格。
