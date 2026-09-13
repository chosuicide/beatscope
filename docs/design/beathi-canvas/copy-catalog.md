# Beathi Canvas bilingual copy catalog (frozen)

English is the default language; Chinese (zh-CN) is the explicit switch. Every shipped
interface, error and empty-state string ships in both catalogs; runtime machine
translation is forbidden (plan §8.3). The React shell loads strings from this catalog
(`web-src/app/locales/` in Commit 2); changes here are design-gate scoped.

Legend: **key** — EN / zh-CN

## 1. Top project bar

- `topbar.project.untitled` — Untitled project / 未命名项目
- `topbar.saveState.saved` — All changes saved / 全部更改已保存
- `topbar.saveState.saving` — Saving… / 正在保存…
- `topbar.saveState.offline` — Offline draft / 离线草稿
- `topbar.saveState.conflict` — Save conflict / 保存冲突
- `topbar.action.present` — Present / 放映
- `topbar.action.preview` — Preview / 预览
- `topbar.action.newAudio` — New audio / 新音频
- `topbar.action.export` — Export / 导出
- `topbar.language.en` — EN / EN
- `topbar.language.zh` — 中文 / 中文

## 2. Left dock

- `dock.scenes` — Scenes / 场景
- `dock.layers` — Layers / 图层
- `dock.motion` — Motion / 动效
- `dock.drivers` — Drivers / 驱动
- `dock.motions` — Motions / 动作
- `dock.scenes.caption` — Scenes — {project} / 场景 — {project}
- `dock.layers.caption` — Layers — Scene {index} · {title} / 图层 — 场景 {index} · {title}
- `dock.moreScenes` — More scenes ({count}) / 更多场景（{count}）
- `dock.footer.scenes` — {count} scenes · {duration} / {count} 个场景 · {duration}
- `dock.footer.layers` — {count} layers · {hidden} hidden / {count} 个图层 · 隐藏 {hidden} 个
- `dock.empty.scenes` — No scenes yet. Load audio to build the timeline. / 还没有场景。载入音频以生成时间线。
- `dock.empty.layers` — Select a board to inspect its layers. / 选择一块画板以查看其图层。
- `dock.empty.motion` — Select a layer to see its response chains. / 选择一个图层以查看其响应链。

## 3. Canvas

- `canvas.coach.title` — Beathi Canvas / Beathi Canvas
- `canvas.coach.subtitle` — First run — {project} / 首次运行 — {project}
- `canvas.coach.step1` — Select a board to inspect its layers and responses. / 选择一块画板，查看它的图层与响应链。
- `canvas.coach.step2` — Change one response and preview the result. / 修改一条响应并预览结果。
- `canvas.coach.step3` — Export the direction package for your Coding Agent. / 为你的编码智能体导出方向包。
- `canvas.coach.skip` — Skip / 跳过
- `canvas.liveTag` — LIVE / 播放中
- `canvas.minimap.label` — Canvas overview / 画布总览
- `canvas.webglUnavailable.title` — Live preview unavailable / 实时预览不可用
- `canvas.webglUnavailable.body` — WebGL is disabled, so boards show cached poster frames. Editing still works. / WebGL 已停用，画板将显示缓存海报帧。编辑功能不受影响。
- `canvas.posterCache.note` — Cached poster · {time} / 缓存海报 · {time}

## 4. Inspector

- `inspector.crumb` — {project} / Scene {index} / {layer} / {project} / 场景 {index} / {layer}
- `inspector.section.transform` — Transform / 变换
- `inspector.section.crop` — Crop / 裁剪
- `inspector.section.responses` — Responses / 响应链
- `inspector.section.transition` — Transition out / 出场过渡
- `inspector.label.rotation` — Rotation / 旋转
- `inspector.label.leftRight` — Left / Right / 左 / 右
- `inspector.label.topBottom` — Top / Bottom / 上 / 下
- `inspector.label.sourceOffset` — Source offset / 源偏移
- `inspector.label.trigger` — Trigger / 触发
- `inspector.label.operator` — Operator / 算子
- `inspector.label.amount` — Amount / 强度
- `inspector.label.duration` — Duration / 时长
- `inspector.label.combine` — Combine / 叠加方式
- `inspector.label.curve` — Curve / 曲线
- `inspector.action.resetCrop` — Reset crop / 重置裁剪
- `inspector.note.budget` — Budget {n} responses / bar · {free} free at bar {bar}. / 每小节预算 {n} 条响应 · 第 {bar} 小节还可加 {free} 条。
- `inspector.note.deterministicSeek` — seek stays deterministic / 跳转保持确定性
- `inspector.empty.noSelection` — Nothing selected. Select a board or layer. / 未选择任何内容。请选择画板或图层。
- `inspector.unsupportedLayer` — Unsupported layer kind (preserved) / 不支持的图层类型（已保留）

## 5. Floating transport

- `transport.play` — Play / 播放
- `transport.pause` — Pause / 暂停
- `transport.loop` — Loop / 循环
- `transport.zoomToCurrent` — Zoom to current scene / 缩放到当前场景
- `transport.sceneAria` — Current scene: {title} / 当前场景：{title}

## 6. Direction proposal (frame D)

- `proposal.crumb` — {project} / Proposal {index} / {project} / 提案 {index}
- `proposal.title` — Direction proposal / 方向提案
- `proposal.state.pending` — pending / 待审阅
- `proposal.state.applied` — applied / 已应用
- `proposal.state.rejected` — rejected / 已拒绝
- `proposal.source` — beatscope.propose_direction_patch / beatscope.propose_direction_patch
- `proposal.section.summary` — Summary / 摘要
- `proposal.label.intent` — Intent / 意图
- `proposal.label.scope` — Scope / 范围
- `proposal.label.basis` — Basis / 依据
- `proposal.section.changes` — Changes / 变更
- `proposal.diff.added` — {n} added / 新增 {n} 项
- `proposal.diff.changed` — {n} changed / 修改 {n} 项
- `proposal.diff.removed` — {n} removed / 移除 {n} 项
- `proposal.group.added` — Added / 新增
- `proposal.group.changed` — Changed / 修改
- `proposal.group.removed` — Removed / 移除
- `proposal.group.none` — None / 无
- `proposal.action.apply` — Apply patch / 应用补丁
- `proposal.action.reject` — Reject / 拒绝
- `proposal.rawJson` — Raw JSON / 原始 JSON
- `proposal.rawJson.lines` — {n} lines / {n} 行
- `proposal.toggle.before` — Before / 之前
- `proposal.toggle.after` — After / 之后

## 7. Export package

- `export.section.title` — Export package / 导出包
- `export.check.references` — References / 参考内容
- `export.check.verified` — {n} verified / 已验证 {n} 项
- `export.check.assets` — Included assets / 包含素材
- `export.check.assetsValue` — {count} files · {size} / {count} 个文件 · {size}
- `export.check.audio` — Audio / 音频
- `export.check.audioExcluded` — excluded by policy / 按策略不包含
- `export.action.export` — Export… / 导出…
- `export.action.copyChecklist` — Copy checklist / 复制清单
- `export.copied` — Checklist copied / 清单已复制

## 8. Boot and load states (§3.5)

- `boot.state.booting` — Starting Beathi Canvas… / 正在启动 Beathi Canvas…
- `boot.state.loadingProject` — Loading project… / 正在载入项目…
- `boot.state.recoveringDraft` — Recovering local draft… / 正在恢复本地草稿…
- `boot.state.ready` — Ready / 就绪
- `boot.state.readOnlyDemo` — Demo mode — changes stay in this browser / 演示模式 — 更改仅保存在本浏览器
- `boot.state.conflict.title` — Direction conflict / 方向文档冲突
- `boot.state.conflict.body` — The server copy changed since your last save. Compare or download before overwriting. / 服务器上的副本在上次保存后发生了变化。请先比较或下载，再决定覆盖。
- `boot.state.fatal.title` — The project could not be opened / 无法打开项目
- `boot.state.fatal.body` — The direction document failed validation. You can still download the raw file. / 方向文档未通过校验。你仍可下载原始文件。
- `boot.action.downloadRaw` — Download raw JSON / 下载原始 JSON
- `boot.action.returnToProject` — Return to project / 返回项目

## 9. Errors, empty states and inline notices

- `error.noBeatGrid` — No beat grid in this project. Bar anchors are unavailable; time anchors are used instead. / 该项目没有节拍网格，小节锚点不可用，已改用时间锚点。
- `error.driverUnavailable` — {driver} has no measured data in this project and shows as unavailable. / {driver} 在该项目中没有实测数据，显示为不可用。
- `error.assetTooLarge` — {name} is {size}. Maximum is {limit}. / {name} 为 {size}，超出上限 {limit}。
- `error.assetUnsupported` — {name} is not a supported image or muted video file. / {name} 不是受支持的图片或静音视频文件。
- `error.assetBudget` — Project asset budget reached ({limit}). Remove assets to continue. / 项目素材预算已达上限（{limit}）。请先删除部分素材。
- `error.saveConflict` — Save conflict: the server has a newer revision ({etag}). / 保存冲突：服务器存在更新的版本（{etag}）。
- `error.directionInvalid` — Direction document rejected: {reason} / 方向文档被拒绝：{reason}
- `error.analysisFailed` — Analysis failed: {reason}. You can retry or cancel. / 分析失败：{reason}。可以重试或取消。
- `error.webmRecorderUnavailable` — WebM recording is not supported in this browser. Storyboard PNG is still available. / 当前浏览器不支持 WebM 录制。分镜图 PNG 仍然可用。
- `empty.noScenes` — This project has no scenes yet. / 该项目还没有任何场景。
- `empty.noAssets` — No project assets yet. Imported images and muted videos appear here. / 还没有项目素材。导入的图片与静音视频会显示在这里。
- `empty.noProposals` — No pending proposals. / 没有待审阅的提案。

## 10. Demo

- `demo.badge` — Bundled demo / 内置演示
- `demo.reset` — Reset demo / 重置演示
- `demo.persistNote` — Demo edits persist only in this browser (IndexedDB). / 演示编辑仅保存在本浏览器（IndexedDB）。
- `demo.importProposal` — Import proposal JSON / 导入提案 JSON
