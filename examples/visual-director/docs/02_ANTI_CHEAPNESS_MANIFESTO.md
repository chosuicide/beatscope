# 02｜防廉价死线：通用底线 + 分级可配置静态门禁

本工作流**不锁死任何单一视觉风格**，但坚决封杀代码生成视频最常见的“AI 偷懒廉价感”。因此将规则拆成两层：
1. **通用反廉价底线**（任何风格都必须遵守）；
2. **按项目选配的静态代码门禁 Profile**（由 `pipeline/anti_cheapness_lint.py` 自动扫描）。

---

## 一、 所有风格都必须避开的 5 种“廉价病”
1. **字面占位符偷懒**：看到“故障/科技/异常”就乱画 `ERR 1-07`、`NO SIGNAL`、`LOADING...`、`SYSTEM ERROR` 等假报错 UI。
2. **两张皮贴纸感与曝光断崖**：前景主体与背景色域/光照方向打架；或高频切换的两套画面明度、镜头尺度落差过大（例如户外大晴天硬切黑棚拍微距），产生廉价拼贴感。
3. **单一物件换色屏保**：15–30 秒的高能片子只靠一个 3D 物体或单种图形来回换色板滤镜撑完，毫无景别与视觉形态变化。
4. **音乐机械抽搐病（BeatScope 场景特有）**：把每个 `onset` 都绑成全屏闪白，或把未平滑的原始 `bands` 直接乘进缩放/机位导致 15–30Hz 抽搐抖动，毫无留白与呼吸。
5. **非确定性随机（破坏 seek-safe）**：使用无种子的 `random.random()` / `np.random.rand()`，导致每次重渲或局部热替换帧结果不一致。

---

## 二、 分级可配置的静态代码门禁（`pipeline/anti_cheapness_lint.py`）

渲染前自动执行 AST + 正则扫描；项目按实际风格选用对应 Profile（单行特例可加 `# lint-allow: 原因` 经导演批准放行）：

### 1. `universal-baseline`（通用默认，适用绝大多数风格）
- **完全风格中立**：允许文字排版、允许柔和景深/光学辉光、允许运动模糊、允许淡入淡出。
- **仅拦截通用工程/偷懒硬伤**：
  - 禁止无种子非确定性 `random.random` / `random.randint` / `random.uniform` / `random.choice`（强制使用基于 `frame_idx` 播种的 `np.random.default_rng` 或 `random.Random(seed)`）；
  - 禁止硬编码廉价假故障占位文案（如 `ERR 1-07`、`NO SIGNAL`、`SYSTEM ERROR`）。

### 2. `editorial-kinetic`（平面杂志 / 动效排版 / 清透设计风）
- 允许克制排版与干净矢量网格，继续封杀廉价高斯模糊辉光贴片（`GaussianBlur` / `blur` / `BLOOM` / `GLARE`）与 `use_motion_blur` 滥用。

### 3. `strict-darkroom`（暗房实验 / 零文字纯影像 / 物理摧毁风）
- **零文字 / 零 UI**：禁用 `cv2.putText`、`ImageDraw.text`、`bpy.ops.object.text_add`、`FONT`。
- **零柔化与辉光**：禁用 `GaussianBlur`、`blur`、`medianBlur`、`addWeighted`、`use_bloom`、`CompositorNodeGlare`、`use_motion_blur`。

### 4. `custom` / `off`
- `custom`：由导演按本次作品专属禁忌生成 `lint_rules.json`（`forbidden_calls` / `forbidden_attrs` / `forbidden_regex`），通过 `--rules lint_rules.json` 执行；
- `off`：关闭风格禁令，仅做 Python 语法检查。

---

## 三、 治好“两张皮”的通用合成武器（按风格选用）
不同风格有不同的光学融合手段，但**严禁直接把未做任何光影衔接的前景硬贴到背景上**：
- **物理环境反射匹配**（3D 金属/玻璃/高光材质）：给 Blender 世界球加载与背景同源（或原位对齐）的环境贴图与色温主光；
- **边缘天光包裹 / 大气散射**（写实/日系/梦幻）：轻微提取背景边缘色向主体轮廓漫射，或在远景暗部混入天空环境色；
- **统一物理介质层**（胶片/版画/暗房）：在合成末尾叠加基于 `frame_idx` 锁频的胶片颗粒、和纸纤维或有序网点，让前景与背景共享同一张介质；
- **零羽化硬边刀切**（超现实/暗房抠洞）：刻意二值化并 `cv2.dilate` 膨胀 `2px` 彻底吃净抗锯齿白边。

---

## 四、 通用成品验收 4 条底线
1. **去色测骨（`probe_grid_gray.png`）**：去掉色彩只看黑白明暗，构图骨架、主次对比和光影层次必须立得住，不能偏灰发闷。
2. **形态多样性核查**：扫一眼整张多帧 `probe_grid.png`，严禁超过 60% 的格子都是同一个物体/同一景别仅换色板。
3. **接缝与切换连贯性**：检查主体边缘是否有 1px 泛白锯齿、检查高频切景/局部异变是否存在未设计的明度断崖或尺度割裂。
4. **带原曲实听 + `verify.mjs` 核验**：稳态是否克制？爆发是否落点精准？绝不用静音静帧图代替带音频动态验收。
