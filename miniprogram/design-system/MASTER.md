# Design System: VELO · MASTER

> **真相源声明**：本文件是 velo 小程序全部 UI 的唯一真相源。改样式先改这里，再改代码；页面级偏差写 `pages/<页面>.md`（存在即覆盖本文件对应项）。
> 状态：**v0.4**（2026-06-12 / Tim 拍板「苹果方案」——历经五轮原创设计语言探索全部被否后定案）。

## 0. 方向定案（先读这条，防止重蹈覆辙）

**velo 不做原创设计语言。整体趴在 Apple HIG（iOS 人机界面规范）上 + 系统橙 accent，到此为止。**

依据（2026-06-12 实证）：五轮原创探索（深红码表 / 夜场荧光 / 白昼证书 / 照片卡 / Stitch 生成）全部被 Tim 否决；Tim 朋友用 Codex 生成的「纯 iOS 原生感 + 橙 accent」首页一次通过 Tim 的眼睛——零原创、全成熟分布。结论已焊进 frontend-design skill「成熟度分层」：**零设计师团队的目标是"专业可信"，distinctive 是过早优化**。未来任何 agent 提议"给 velo 做品牌化设计语言"→ 先读本节再说。

**标杆**（Tim 眼睛验收过的两张图，效果优先级高于本文件一切文字）：
1. Tim 朋友的 Codex 首页图（2026-06-12 对话）：白底、橙胶囊、大圆角卡、地图卡、等宽数据行、毛玻璃 tab bar
2. Strava 真实照片水印（Tim 提供）：数据白字直接印在用户照片上，无框无底

## 1. Design Read

velo 读作：iPhone 用户为主的骑行成就与社交工具。观感目标 = **像一个苹果生态里的原生 App**。
不可妥协项（Tim 既有判例）：字段缺失整块隐藏、永不显示 "-" 占位；正式版禁止小字备注/提醒。

## 2. 色板（全部用 iOS 系统语义色，不自创颜色）

- **背景** `#F2F2F7`（systemGroupedBackground）
- **表面** `#FFFFFF`（卡片）
- **主文字** `#1C1C1E`（label）
- **次文字** `#8A8A8E`（secondaryLabel）
- **分隔线** `#E5E5EA`（separator）
- **Accent** `#FF9500`（systemOrange）——唯一强调色：主按钮、选中态、tab 高亮、品牌字标；按压态 `#E07F00`
- 浅橙衬底 `rgba(255,149,0,.12)` 配深橙字（chips/标签）
- 语义色也走 iOS：成功 `#34C759` / 警示 `#FF9F0A` / 错误 `#FF3B30`（仅语义场景）

**已废弃（永久，别再提）**：Race Red `#E03A33`（v0.1，Tim 否）、Volt 荧光 `#D6FF42` 与夜场深底（v0.2-v0.3，Tim 明确讨厌）、旧线上四色系混战（`#FF2D55`/`#f04452`/`#0f766e` 等，逐页清除中）。

## 3. 字体与数字

- 系统字（-apple-system / PingFang SC）。**禁用窄体/赛车体 display 字**（v2 实证翻车）
- **中文字重铁律：≤600**。PingFang 真字重上限 600，写 700+ 触发合成加粗笔画糊——"字体丑"头号来源（2026-06-12 探索页实证，Tim 一眼抓出）
- **数字等宽禁用 mono 字体族**（落到 Menlo 呆板）：用系统字 + `font-variant-numeric: tabular-nums; font-feature-settings: 'tnum'`——iOS 原生 App 的真实做法，数字保持 SF 现代字形且宽度对齐。数据行格式 `10.0 km · 561 m`（无中文前缀）
- 层级靠字重（600 标题 / 400 正文）和系统级字号节奏，不靠夸张字号跳跃

## 4. 形状与海拔

- 卡片圆角 `32rpx`，胶囊 `999rpx`，小元素 `12rpx`
- 卡片无边框，轻阴影 `0 2rpx 16rpx rgba(0,0,0,.05)`
- 大图卡：图全宽在上、信息白区在下（标杆图语言）

## 5. 成绩分享 = 照片水印（哲学保留，形态待真机定稿）

不做卡，做印：用户自己的照片 100% 保持是照片，数据（含 NP 功率——Strava 水印没有的差异点）+ GPS 轨迹线 + VELO 标轻轻印上去。落地链路：选照片（wx.chooseMedia）→ canvas 合成 → 保存/分享，后端零改动。轨迹线/字标颜色随 v0.4 改为白色或系统橙（Volt 方案作废）。

## 6. Anti-Patterns（五轮翻车换来的封杀清单）

- 自创品牌色/设计语言（见 §0）
- 深底夜场日常界面、荧光 glow、证书框、印章、斜条带、ghost 大字
- 窄体赛车数字、装饰编号、三等分卡片行
- "-" 占位、小字备注、emoji 图标
- 数据浮层做成"半透明盒子压在照片上"（水印=无框印字）

## 7. 平台约束备忘

- rpx：设计稿 px×0.879→rpx 惯例；canvas 用 `hidden` 禁 `wx:if`（陷阱 #17）；图标 lucide SVG via image；WXML 不能调数组方法
- 封面图：API 返回相对路径 `/uploads/...`，**必须用 js 拼好 baseUrl 的字段（如 coverSrc）**，wxml 直接绑 cover_url 必然 404（2026-06-12 探索页实证修复）

## 8. 改造进度账

- [x] 探索页（2026-06-12，本方案第一页：HIG 卡片 + 系统橙 + 等宽数据行 + 封面图 bug 修复）
- [x] tabBar selectedColor `#FF2D55` → `#FF9500`
- [x] 路线详情页（2026-06-12：hero 出血 + 补路线名标题 + inset-grouped 手风琴 + 橙主按钮；正文排版立体化：键值表/字段块/步骤条/语录气泡四结构 + 呼吸间距。Tim 验收"先过，以后再迭代"——细节保留项待下轮）
- [x] 约骑模块六页全量重构（2026-06-12，任务卡 `docs/plans/meetup-ui-rebuild.md`）：
  - meetup-create：废弃旧"红色原型 ×0.879 逐像素还原"整套（`#ff1744` ×20+ 处、13-19rpx 蚂蚁字 = "真机字特别小"根源）；字号按 iOS 节奏重建（辅助 ≥21rpx / 正文 ≥25rpx）；编辑步 absolute 贴右控件全部改回文档流（grid auto 1fr auto）；编辑/确认步小尺寸 `<map>` 缩略图换 canvas 自绘轨迹线（位置冲突 bug 根除——原生组件层级盖按钮 + 抢手势）
  - meetup-detail：地图轨迹卡前置到 hero 之后（出血式图卡无标题）；四格数据合并单卡竖 hairline
  - meetups-list：大图卡语言——卡顶轨迹缩略 canvas（按 route_book_id 异步拉 preview_points + 模块级缓存，后端零改动）+ hairline 数据行
  - meetups-mine / meetup-report / map-picker：白卡化 + 字重 800→600 全清 + 状态药丸语义色 + 黑底按钮换橙
- [x] profile（我的）结构重排（2026-06-12）：4 张分散功能卡合并 iOS inset-grouped 单卡；📍⚙🚴 emoji 换 lucide SVG（新建 assets/icons/settings.svg）；清掉 224 行 v4 deprecated 样式；数字 tabular
- [x] 全局地图轨迹线换橙：`utils/map-theme.js` routeColor `#F04452` → `#FF9500`（一处改全部地图生效）
- [x] 共享轨迹缩略工具 `utils/route-thumb.js`（canvas 画"路线形状"非地图；列表卡 + create 缩略共用；⚠ wxss rpx 与 js 绘制 px 必须 2:1）
- [ ] 首页（涉及 feed 形态 = 功能层，与"冷启动内容密度"一起另议）
- [ ] 开奖/分享水印（形态已定，等详情页之后实现）
- [ ] 全局清除旧四色系（grep `#FF2D55|#f04452|#0f766e|#f7f3ea` 逐页勾销；2026-06-12 约骑七页 + map-theme 已清，upload 页深底霓虹 `#c8ff3d` 仍挂账）
