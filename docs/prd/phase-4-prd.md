# velo Sprint 4 战术 PRD（phase-4-prd）

> **本文件性质**：Sprint 4 **战术 PRD**，给执行 spec subagent 看的执行手册。
>
> **写作规范**（沿用 phase-5-prd 风格 / Tim 2026-04-28 拍）：每个子任务严格 **9 章节**（用户目标 / 使用场景 / 功能范围 / 用户流程 / 页面&状态 / 数据需求 / 异常情况 / 验收标准 / 不做项）+ 来源追溯一行。
> - PRD 不写具体数据库表结构 / API 路径
> - PRD 可写必要技术约束（小程序 / 性能要求）
> - UI/UX 只写页面结构 / 信息优先级 / 流程 / 状态，不写视觉参数
>
> **读者分层**：
> - **§0-§5（前半 / Tim 必审）**：用户故事 + 4 tab 新结构 + 6 功能落点 + 拆 2 批节奏 + 决策记录
> - **§6-§12（后半 / subagent 必读 + Codex 异源审接住）**：5 个子任务卡 + admin H5 真用回归 ops 流程 + 验收标准
>
> **维护**：Tim + Claude 协作，最后更新 2026-05-06。版本 **v0.1**（首版）。

---

## 0. Sprint 4 north star（顶层概览）

**双主轴并行**：

- **主轴 1 - 小程序 UI 重构 + 接 Sprint 2 endpoint**：5 tab → 4 tab，砍排行榜 tab，6 功能落地
- **主轴 2 - admin H5 真用回归**：Tim/CCF/颜颜全 sprint 真用 admin 4 个工具收 bug，hotfix 模式修

**开发哲学**：

> 每功能 ship 后 1 周内 Tim/CCF/颜颜真用 → 必要时回收/重做。"做出来不好就删"是默认状态。

不预设细节决策（颜色 / 布局 / 字段格式），留给 implementation。

**预估工期**：4 周（两批各 2 周 + admin H5 真用全程并行）

**前置依赖**：
- v5 Sprint 2 已 ship（power_curve / heatmap / city / profile 后端 endpoint 全部就位 / 详 CLAUDE.md 进度）
- v5 Sprint 3 已 ship（admin H5 部署外网 9000 / 候选池 + AI 草稿 + 批量管理 + 创建工具全部就位 / 详 CLAUDE.md 进度）

---

## 1. 共用规范引用（spec subagent 必读）

### 1.1 语言风格

参 `agent-rules/product-decisions.md` §7 禁用词清单 / §6 RUBRIC-CONTENT 活人感标准。

**Sprint 4 特殊调性**：
- 给 Tim 看的输出（PRD 前半 / brainstorm 对话 / 完工汇报）严守 `~/.claude/CLAUDE.md` §2.3：讲用户故事 + 禁堆术语 + 用生活类比。**违反 = 沟通失败**
- 给 codex / 其他 subagent 看的技术规范（PRD 后半 / spec / 任务卡 grep 结果）可正常用术语

### 1.2 技术栈

参 `CLAUDE.md` "技术栈"章节。Sprint 4 不引新技术。

后端：Python + FastAPI + PostgreSQL（已部署）
前端：微信小程序原生（v0/v1/v4 同款）
admin H5：React + AntD + Vite（v5 Sprint 3 已部署 9000）

### 1.3 边界（INV / D-P）

参 `agent-rules/product-decisions.md` §1（INV-P01 ~ P06）+ §5（D-P01 ~ D-P10）。任何 spec 决策违反 → REJECT escalate Tim。

**关键 D-P 红线**（看他人主页相关）：
- D-P08：看他人主页字段严格白名单（详 phase-5-prd `5.A.2`），不允许返回敏感字段（手机 / openid / Strava token / etc.）

### 1.4 规则界限

- **防火墙式扩展**：核心表（users / activities / segments / segment_efforts）不动 / 不加字段（CLAUDE.md "防火墙"）
- **强制检查清单 + 技术栈陷阱清单**：CLAUDE.md（每个子任务实施前必扫第 17 条 wx:if canvas 渲染陷阱）
- **沟通格式**：CLAUDE.md §2.3 禁用词（颗粒度 / 闭环 / 消费端 / 触点 / 抓手 等）
- **commit 前 4 问**：CLAUDE.md "🔴 commit 前 4 问"
- **代码层三审**：双审 + Codex 异源审（CLAUDE.md "三重审判"）

### 1.5 前置条件检查（subagent 开工前 grep 验证）

```bash
# 后端 endpoint 全部就位
grep -n "me/power-curve\|me/heatmap\|me/profile\|{user_id}/profile" app/user/router.py
# 应见 4 行（v5 Sprint 2 ship）

# admin H5 已部署
ssh -t ubuntu@114.132.190.245 "sudo docker compose ps | grep admin-h5"
# 应见 Up

# 小程序当前 5 tab 结构
cat miniprogram/app.json | head -40
# 应见 home / explore / upload / leaderboard / profile
```

任一不符 → 停下报 Tim，不擅自修复。

---

## 2. 用户故事（**Tim 必读**）

### 2.1 小明（已注册老用户 / 北京 / 严肃骑手）

**周三晚上骑完车回来打开 velo 小程序**：

1. 进**个人页**（最右 tab）→ 看到自己头像、累计骑行数据、**功率曲线图**（5s/30s/5min/1h 4 段进步线，最近 3 个月数据）
2. 同一页往下滚 → **骑行热力图**，显示他过去所有骑过的区域分布（按颜色深浅表示密度）
3. 名片右上角写着"北京"**city badge**（identity tag）可选城市可不选

**周四中午刷动态 tab**：

4. 看到 CCF 昨天的骑行卡片 → 点击 CCF 头像 → 进**CCF 的用户详情页**（独立页 / 不是个人 tab）
5. 看到 CCF 的功率曲线 + 热力图 + 城市，但看不到 CCF 的手机号 / Strava 绑定状态等隐私字段

### 2.2 小张（新用户 / 上海 / 想找北京的赛段练）

**计划下周末去北京骑车**：

1. 进**探索 tab**（左二，原来"即将上线")→ 现在是赛段瀑布流卡片
2. 顶部按城市筛选条选"北京" → 列表只剩北京赛段
3. 点"妙峰山" → 进**赛段详情页**（独立页 / 不在底部 tab）
4. 第一屏：海拔曲线 + 城市 + 坡度 + 距离/爬升数字
5. 往下滚 → **AI 介绍**："海拔 1090m，下苇甸到上苇甸 12km……"
6. 再往下 → **我的记录**（如果他骑过这条）
7. - **全网排行榜前端展示**（赛段详情页展示 top 10和我的排名）

### 2.3 新骑友小李（首次进 velo）

1. 微信一键登录 → 个人页（空名片：FTP 待补 / 体重待补）
2. 切探索 tab → 看到候选池新赛段瀑布流
3. 切动态 tab → 看到 Tim/CCF 的最近骑行
4. 想找朋友 → 点 Tim 头像 → 看 Tim 的用户详情页

---

## 3. 4 tab 新结构 + 6 功能落点（**Tim 必读**）

### 3.1 5 tab → 4 tab

| 旧（5 tab） | 新（4 tab） | 备注 |
|---|---|---|
| 动态 (home) | 动态 (home) | 不变 |
| 探索 (explore) | 探索 (explore) | **大改造**：占位 → 赛段瀑布流 + 城市筛选 |
| 上传 (upload) | 上传 (upload) | 不变 |
| 赛段 (leaderboard) | **砍掉** | "完全没用 / 跟探索重合"（Tim 2026-05-06 拍） |
| 个人 (profile) | 个人 (profile) | **改造**：加功率曲线 / 热力图 |

**新增 2 个独立页**（不在底部 tab，从其他页跳转进入）：

- **赛段详情页**（segment/[id]）：从探索 tab 卡片点击进入
- **用户详情页**（user/[id]）：从动态 / 通知中心点击骑友头像进入

### 3.2 6 功能落点

| # | 功能 | 落点 | 数据来源 |
|---|---|---|---|
| 1 | 功率曲线 | 个人页 | `GET /api/user/me/power-curve`（已有） |
| 2 | 骑行热力图 | 个人页 | `GET /api/user/me/heatmap`（已有） |
| 3 | 看他人主页 | 新建用户详情页 | `GET /api/user/{user_id}/profile`（已有） |
| 4 | AI 介绍 | 新建赛段详情页 | `GET /api/segments/{id}` 已有 introduction 字段 |
| 5 | 城市筛选 | 探索 tab 顶部 | `GET /api/segments?city=xxx` 已有筛选参数 |
| 6 | 候选池新赛段曝光 | 探索 tab 主体瀑布流 | `GET /api/segments?city=xxx`（默认 `order_by(created_at desc)` / 新赛段自然排前面 / 前端按 created_at < 30 天显示 NEW）|

### 3.3 砍掉的功能

- **leaderboard tab 整体删除**（pages/leaderboard 目录 + app.json tabBar 配置 + 其他页面跳转引用）
- 后端 `GET /api/segments/{id}/leaderboard` endpoint **保留**（不影响 / 未来需要再开）

---

## 4. 拆 2 批节奏 + 开发哲学（**Tim 必读**）

### 4.1 批 1 - 用户维度（~2 周）

**主战场**：个人页 + 新建用户详情页

**第一步（独立 ship 验证稳定）**：

- **任务 4.1 个人页框架改造**：把现有个人页拆成"框架 + 槽位"结构。框架先 ship，4 个槽位先空着或显示"功能加载中"，确保不破现有功能（登录 / 累计统计 / 我的荣誉跳转 / 设置跳转都能正常用）

**第二步（4 内容并行塞入）**：

- 任务 4.2 个人页内容塞入（功率曲线 / 热力图 / 城市标签（若有，若没有就不显示））— 3 个 subagent 并行
- 任务 4.3 用户详情页新建

**ship 后**：Tim/CCF/颜颜真用 1 周 → 反馈喂批 2 设计

### 4.2 批 2 - 赛段端（~2 周）

**主战场**：探索 tab 大改造 + 新建赛段详情页 + 删 leaderboard tab

**任务**（可并行）：

- 任务 4.4 探索 tab 改造（瀑布流 + 城市筛选 + 候选池曝光 + 砍 leaderboard tab + 跳转重映射）（未来要改造升级为地图内嵌入赛段，类strava）
- 任务 4.5 赛段详情页新建（AI 介绍 + 我的记录 + 全网 top 10 排行榜 + 我的排名 / D7 反转）

**ship 后**：Tim/CCF/颜颜真用 1 周 → 收尾 + 决定是否进 Sprint 5

### 4.3 admin H5 真用回归（全 sprint 并行 / ops 模式）

- 本周内启动（不等批 1 ship）
- Tim/CCF/颜颜每天用 admin H5 的 4 个工具（候选池 / AI 草稿 / 批量管理 / 创建工具）
- 发现的 bug 进 hotfix commit / 不写进 PRD 任务卡
- 期待 bug 类型：UI 体验 / 跨端数据流（admin 改动后小程序消费不到）/ 边界 case 漏处理

详 §11。

### 4.4 开发哲学（实施纪律）

- **每功能 ship 后 1 周内 Tim 真用反馈**：UI 不直观 / 用户场景不顺 / 数据不准 → 直接删 / 重做，不留半成品
- **不预设细节决策**：颜色 / 字号 / 布局间距 / 字段顺序 / 等留给 implementation；spec 卡只写信息优先级 + 状态 + 流程
- **小修小补 vs 重做的判断**：
  - 数据流不通 / 用户根本看不懂 → 重做
  - 视觉小问题 / 字段顺序调整 → 小修小补
- **批 1 反馈喂批 2**：批 1 ship 后真用 1 周收的"模式级反馈"（比如"这种数据可视化形态没人看 / 应该改成 X"）应该影响批 2 设计

---

## 5. 关键决策记录（Tim 可读 / subagent 必读）

| # | 决策 | 拍板者 | 时间 | 来源 |
|---|---|---|---|---|
| D1 | Sprint 4 = 小程序 UI + admin H5 真用回归（不含监测告警通道，已 D 决策搁置）| Tim | 2026-05-06 | brainstorm Q1 |
| D2 | 范围宽（**v0.2 调整**：用户维度 2 + 看他人 1 + 赛段端 3 = 6 主功能 + city badge 顺带做 / brainstorm Q2 原拍 7 含 city badge / v0.2 把 city 降为非主任务）| Tim | 2026-05-06 | brainstorm Q2 + PRD v0.2 自审 |
| D3 | 拆 2 批 ship + ship 后 1 周真用反馈喂下一批 | Tim | 2026-05-06 | brainstorm Q3 |
| D4 | 批 1 第一步：先做空个人页框架，验证稳定后再塞内容 | Tim | 2026-05-06 | brainstorm post-Q3 |
| D5 | 砍 leaderboard tab，5 tab 变 4 tab（"完全没用 / 跟探索重合"） | Tim | 2026-05-06 | brainstorm Q4 前置 |
| D6 | 探索 tab 主体 = 单流瀑布流（不嵌内层 tab "发现/全部"） | Tim | 2026-05-06 | brainstorm Q4 |
| D7 | 赛段详情页加"我的记录"（个人维度）+ 全网排行榜 top 10 + 我的排名（**Tim 2026-05-06 在 PRD v0.1 → v0.2 自审时反转 / 之前砍前端展示，现确认展示**） | Tim | 2026-05-06 | PRD v0.2 自审 |
| D8 | 看他人主页用新建独立页（不复用个人 tab + 切换） | Tim 接受 Claude 推荐 | 2026-05-06 | brainstorm post-Q3 |
| D9 | city 字段在 profile 内可选（不强制设置 / city 有值时名片角落自动显示 / 无值不显示 / 不做引导设置弹窗）—— **Tim PRD v0.2 自审改：城市标签从 7 主功能里砍掉 / 不作独立 4.2.C 任务 / 在 4.1 框架里作小细节顺带做** | Tim | 2026-05-06 | PRD v0.2 自审 |
| D10 | 开发哲学：做完不好就删（每功能 ship 1 周真用 → 回收/重做） | Tim | 2026-05-06 | brainstorm post-Q2 |
| D11 | 后端 `GET /api/segments/{id}/leaderboard` endpoint 保留 + 前端 4.5 任务调用展示 top 10（D7 反转后此条作为执行配套）| Tim | 2026-05-06 | PRD v0.2 自审 |
| D12 | admin H5 真用回归本周启动（不等批 1 ship）| Tim | 2026-05-06 | brainstorm Q3 配套 |
| D13 | heatmap 时间窗：用户全部历史骑行数据（之前"半年内"改全部 / 真实"我的足迹"感更强） | Tim | 2026-05-06 | PRD v0.2 自审 |
| D14 | 赛段详情页第一屏不展示难度评级 badge（仅 海拔曲线 + 城市 + 坡度 + 距离/爬升数字 / 难度评级算法可在 Sprint 5 细化）| Tim | 2026-05-06 | PRD v0.2 自审 |
| D15 | 探索 tab 改造**未来方向**：批 2 ship 后真用反馈如积极，Sprint 5 升级"地图嵌入赛段"形态（类 Strava）/ 当前批 2 = 瀑布流形态 | Tim | 2026-05-06 | PRD v0.2 自审 |
| D16 | power-curve `period` 真实枚举校正：`this_month / last_month / this_year / last_year / all_time`（PowerCurvePeriod / 默认 `this_month`）—— Sprint 4 baseline curl prod 实证 / Claude PRD 之前脑补 `last3months` 全错 | Codex 异源审 confirm + Tim | 2026-05-06 | Sprint 4 baseline 实证 |
| D17 | heatmap `city` 真实 schema 校正：UserCity 7 枚举（6 城 + `unknown`）/ 必填 / 无 default —— Claude PRD 之前脑补 `auto` 全错 / 前端逻辑：profile.city 有值默认填 / 无值默认 `unknown` | Codex 异源审 confirm + Tim | 2026-05-06 | Sprint 4 baseline 实证 |
| D18 | self profile schema 加 `city` 字段（`app/user/schemas.py` UserProfile）—— 跟看他人 UserProfileResponse `city` 字段对齐 / 让 4.1 city badge fallback 直接 `profile.city` 拿值不用多打 fetch | Codex 异源审 A 推荐 + Tim | 2026-05-06 | P1-3 codex 异源 |
| D19 | 看他人 schema 砍 `ftp` 字段（`app/user/schemas.py` UserProfileResponse + `app/user/service.py` _PROFILE_RESPONSE_KEYS）—— Tim "默认公开"是页面层（路径任意人能看），不等于字段层（FTP 是骑手生理数据 / Strava 也允许独立隐私层）/ schemas.py 注释明写 D-P08 红线 | Codex 异源审 A 推荐 + Tim 拍 | 2026-05-06 | P1-4 codex 异源 |
| D20 | 写 PRD/plans 提及 endpoint 字段 / 枚举值前必须 grep schemas.py + curl prod 实证 / Claude 自检三问完全没抓到 4 处 drift / memory `feedback_grep_endpoint_schema_before_specs.md` 沉淀 | Tim 强调"异源审重要 / 你经常出错且自己意识不到" | 2026-05-06 | Sprint 4 baseline 教训 |

---

> **以下章节（§6-§12）= subagent 必读 + Codex 异源审接住。Tim 不审。**

---

## 6. 子任务 4.1 - 个人页框架改造（批 1 容器 / **第一步独立 ship**）

**用户目标**：进个人 tab 不感觉"改了什么"——登录 / 累计统计 / 我的荣誉 / 设置全部和现在一样能用，但页面骨架已为后续塞入功率曲线 / 热力图留好位置。

**使用场景**：日常打开个人 tab，看自己骑行数据 + 跳转其他页面。框架改造对用户不可见，但为下一周的内容塞入打地基。

**功能范围**：

- 现有 `pages/profile/profile.wxml` 拆分为 4 个区块：
  - 用户信息名片（含登录态切换 + 头像 + 昵称 + ID + FTP/体重/W·kg + **city 自动渲染**：profile.city 有值时名片角落显示 city badge / 无值时不显示 / 不引导设置弹窗 / D9）
  - 累计骑行卡片（不变）
  - **功率曲线槽位**（占位 placeholder："功能加载中"）
  - **骑行热力图槽位**（占位 placeholder："功能加载中"）
  - 导航卡片（我的荣誉 + 设置 / 不变）
- profile.js 中预留 2 个 fetch 方法（fetchPowerCurve / fetchHeatmap），先返回空对象 / `null`，等后续任务塞实际逻辑
- city 字段沿用现有 fetchUserData 拿（不需要专用 fetch 方法）
- 不改 onShow 主流程（保持登录态判断 + fetchUserData 主路径）

**用户流程**：

1. 用户切到个人 tab
2. onShow 触发，与现有逻辑一致（检查登录态 / 调 GET /api/user/profile + GET /api/user/stats）
3. 渲染：登录卡片（未登录） OR 用户信息名片 + 累计统计 + 2 个槽位 placeholder + 导航卡片（已登录）
4. 用户体验等同现状，槽位 placeholder 只是"功能加载中"提示

**页面/状态**：

- 未登录：登录卡片（不变）
- 已登录（数据齐）：完整渲染，2 个槽位显示 placeholder
- 已登录（profile fetch fail）：保持现有 fail 处理（toast 提示），不破其他卡片
- 框架改造**不允许引入新的 loading 死循环 / 渲染竞态**

**数据需求**：

- 沿用现有 `GET /api/user/profile` + `GET /api/user/stats`
- 不调新 endpoint（4.2 任务里再调）

**异常情况**：

- 现有功能（我的荣誉跳转 / 设置跳转 / 退出登录）必须 100% 保持
- 红线：profile.js 里**禁止**直接调 me/power-curve / me/heatmap（留给 4.2）

**验收标准**：

- 切到个人 tab 与改造前**视觉行为完全一致**（除了 2 个新槽位 placeholder）
- 登录 / 退出登录 / 跳转荣誉 / 跳转设置全部正常
- profile.wxml 文件行数 ≤ 300（黄灯阈值 / 超 300 提示拆 component）
- 至少 4 个 e2e 单测覆盖（登录态 / 未登录态 / fetch fail / 跳转）

**不做项**：

- 不实现功率曲线渲染（4.2 做）
- 不实现热力图渲染（4.2 做）
- 不动用户详情页（4.3 做）

**来源追溯**：D4（先做空框架）+ D9（city 顺带做）+ §3.2 / 用户故事 §2.1。

---

## 7. 子任务 4.2 - 个人页内容塞入（批 1 内容 / **2 个并行**）

**用户目标**：进个人 tab → 看到自己的功率曲线（4 段进步线）/ 骑行热力图（用户全部历史骑行数据 / D13）。这 2 个内容是骑手"看见自己"的核心。city badge 已在 4.1 框架里顺带做（D9）。

**使用场景**：参用户故事 §2.1（小明骑完车回来看自己进步）。

**功能范围**：

可拆 2 个 subagent 并行（互不依赖）：

**4.2.A 功率曲线**：

- profile.wxml 槽位接入 power_curve 折线图组件（建议用现有 detail 页 echart-canvas 模式或 wx-canvas）
- profile.js fetchPowerCurve 调 `GET /api/user/me/power-curve?period=this_month`（**真实枚举 / Sprint 4 baseline 实证**）：默认 `this_month` / 5 档可选 `this_month / last_month / this_year / last_year / all_time`（PowerCurvePeriod / 详 `app/user/schemas.py`）
- 渲染 4 条线：5s / 30s / 5min / 1h 各时段最大功率随时间变化
- 状态：loading / 数据完整 / 数据空（"还没数据，多骑几次就有了"）/ fetch fail（toast）

**4.2.B 热力图**：

- profile.wxml 槽位接入 heatmap 组件（建议用 wx-map 或自定义 canvas + 网格涂色）
- profile.js fetchHeatmap 调 `GET /api/user/me/heatmap?city=<city>`（**真实 schema / city 必填 / 无 default**）：UserCity 7 枚举 `beijing / shanghai / hangzhou / shenzhen / chengdu / taiyuan / unknown`（详 `app/user/schemas.py`）。前端逻辑：profile.city 有值 = 默认填该值；无值 = 默认 `unknown`（拿全部历史 / D13）
- 渲染：地图 + 网格涂色（颜色深浅 = 该网格被骑过的次数密度）
- 状态：loading / 数据完整 / 数据空（"还没骑过任何路线"）/ fetch fail（toast）

**用户流程**：

参用户故事 §2.1。

**页面/状态**：

- 个人页（已登录） → 框架渲染 + 2 槽位异步填充
- 注意 wx:if vs hidden 陷阱（CLAUDE.md 陷阱 #17）：canvas 类组件用 `hidden` 不用 `wx:if` / setData callback 用 `setTimeout` 替代 wx.nextTick
- **2 个 fetch 失败不互相影响**（A 失败不挡 B 渲染）

**数据需求**：

- `GET /api/user/me/power-curve`（已有 / v5 Sprint 2）
- `GET /api/user/me/heatmap`（已有 / v5 Sprint 2）

**异常情况**：

- 4 段功率曲线某段无数据（如新用户没有 1h 段）→ 该线不画 / 不报错
- heatmap 地图组件加载失败 → 降级显示"地图加载失败"+ retry 按钮，不破其他槽位

**验收标准**：

- 真用回归：Tim/CCF/颜颜各自看自己的功率曲线 + 热力图能正常显示
- 用 Strava 假数据账号（含至少 6 个月骑行）能看到完整 4 段曲线 + 热力图分布
- 单测覆盖：3 个 fetch 路径（power-curve / heatmap / fail-降级）
- canvas 渲染在 90% 设备稳定（CLAUDE.md 陷阱 #17 / setTimeout 兜底）

**不做项**：

- 不做 power_curve 单条 vs 多条对比（"我 vs Tim"留 Sprint 5）
- 不做 heatmap 跨城市切换（默认 auto / 6 城选项预留）
- 不做 city 字段引导设置弹窗（D9 / 没值就不显示）

**来源追溯**：§3.2 / 用户故事 §2.1。

---

## 8. 子任务 4.3 - 用户详情页新建（批 1 看他人）

**用户目标**：从动态 / 通知中心点击别人头像 → 进对方主页看 ta 的功率曲线 / 热力图 / 累计数据 / city badge（if exists）。隐私边界严格：看不到对方手机 / openid / Strava token。

**使用场景**：参用户故事 §2.1 周四中午（小明看 CCF 主页）。

**功能范围**：

- 新建 `pages/user/user.wxml` + `user.js` + `user.json`（接受 query 参数 `?id=xxx`）
- 注册到 `app.json` pages 数组（不在 tabBar）
- 页面结构（**与个人页结构同步但只读 + 隐私白名单字段**）：
  - 用户信息名片（头像 + 昵称 + ID + city badge if exists / D9 fallback 同 4.1）
  - 累计骑行卡片（总里程 + 总次数 + 总爬升）
  - 功率曲线（看 ta 的）
  - 骑行热力图（看 ta 的）
  - **不展示**：FTP / 体重 / W·kg（敏感生理数据 / Sprint 4 codex 异源审 2026-05-06 拍后端砍看他人 schema 的 ftp 字段 / D-P08 严格执行）/ 我的荣誉跳转 / 设置跳转
- 调用 `GET /api/user/{user_id}/profile`（v5 Sprint 2 已有 / 字段白名单严格执行 / D-P08）

**前置后端任务（subagent 必须先做）**：

经 grep 确认 `app/user/router.py`，目前只有 `/me/power-curve` 和 `/me/heatmap`，看他人版本不存在。

任务 4.3 启动前必须先补两个后端 endpoint：

- `GET /api/user/{user_id}/power-curve?period=this_month` — period 用 PowerCurvePeriod 5 枚举（同 me 版本 / 默认 `this_month`），权限 = 任意登录用户，复用现有 service.get_user_power_curve
- `GET /api/user/{user_id}/heatmap?city=<city>` — city 用 UserCity 7 枚举必填（同 me 版本 / 无 default），权限 = 任意登录用户，复用现有 service.get_user_heatmap

注意：FastAPI 路由匹配 `/me/...` 静态路径优先（router.py 注释行 123 已说明），新加的 `/{user_id}/power-curve` 不会跟 `/me/power-curve` 冲突。后端任务工作量小（< 30 行 + 4 单测）。

**用户流程**：

1. 用户在动态 / 通知里看到 CCF 的内容
2. 点击 CCF 头像 → 跳转 `/pages/user/user?id={user_id}`
3. 页面渲染：CCF 的公开数据 + 累计 + 功率曲线 + 热力图
4. 看完返回（无关注 / 私信操作 / 留 Sprint 5+）

**页面/状态**：

- loading（首次加载）
- 数据完整（白名单字段都有）
- 数据部分缺失（如对方还没数据 → 各槽位 placeholder）
- user_id 不存在（404 → 提示"用户不存在"+ 返回按钮）
- 我点自己的 → 直接跳到个人 tab（避免双视图混淆）

**数据需求**：

- `GET /api/user/{user_id}/profile`（已有，返回白名单字段）
- `GET /api/user/{user_id}/power-curve`（**前置任务补**）
- `GET /api/user/{user_id}/heatmap`（**前置任务补**）

**异常情况**：

- query 参 id 缺失 / 非法 → toast"无效用户" + 返回
- profile fetch 失败 → 通用错误页 + retry
- 看他人时 power-curve / heatmap 数据空 → "对方还没数据"

**验收标准**：

- 真用回归：Tim 进 CCF 详情页能看 CCF 的功率曲线 + 热力图，看不到 CCF 手机号 / FTP / 体重
- D-P08 白名单测试：尝试构造请求看敏感字段 → 后端 403 / 字段不返回
- 单测：3 个路径（正常加载 / 404 / 自己看自己 → 跳个人 tab）

**不做项**：

- 不做关注 / 私信 / 拉黑（Sprint 5+）
- 不做对方骑过的赛段列表（Sprint 5+）
- 不在 home / notification / leaderboard 拼用户名旁加跳转引导（保持现有头像点击跳转模式）

**来源追溯**：§3.2 #4 / D8 / 用户故事 §2.1 周四中午。

---

## 9. 子任务 4.4 - 探索 tab 改造 + 砍 leaderboard tab（批 2 主体）

**用户目标**：进探索 tab → 看到全部赛段瀑布流（含 admin 刚批准的新赛段排前面 + NEW 标签）→ 顶部按城市筛选 → 点一条进赛段详情页。这是 velo 的"赛段图书馆"。

**使用场景**：参用户故事 §2.2（小张找北京赛段）+ §2.3（小李首次发现）。

**功能范围**：

**4.4.A 探索 tab 主体改造**：

- `pages/explore/explore.wxml` 现状（占位"即将上线"）→ 改造为：
  - 顶部城市筛选条（横向滚动 chip：北/上/杭/深/成/太 + 全部）
  - 主体瀑布流卡片列表（每张卡 = 赛段名 + 距离 / 爬升 / 难度 / 城市 / NEW 标签 if `created_at` < 30 天前 / AI 介绍前 30 字）
  - 点击卡片跳转 `pages/segment/segment?id={segment_id}`（4.5 新建赛段详情页）
- explore.js 调 `GET /api/segments?city={city}&page={n}&page_size=20`
  - **后端默认排序**：经 grep `app/segment/service_query.py:82` 确认默认 `order_by(Segment.created_at.desc())`，新创建赛段自然排前面 / 不需要补 sort_by 参数
  - **NEW 标签判断**：前端逻辑 `if (segment.created_at > 30天前) 显示 NEW`，无需后端改动
- 分页支持 onReachBottom 触发下一页

**4.4.B 砍 leaderboard tab**：

- 删 `pages/leaderboard/` 整个目录（leaderboard.js / wxml / wxss / json）
- 改 `app.json` tabBar.list 删除 leaderboard 项（5 项 → 4 项 / 调整图标 path）
- grep 全代码 `pages/leaderboard` 引用 → 改向探索 tab 或赛段详情页（重点查 home / detail / notification）
  - `detail.wxml` "途经赛段"section 跳转 → 改向 `/pages/segment/segment?id={id}`
  - 其他页面引用 → case-by-case 处理
- 测试：4 tab 切换流畅 / 没有死链接

**用户流程**：

参用户故事 §2.2 + §2.3。

**页面/状态**：

- 首次加载：loading + 空白瀑布流
- 数据完整：瀑布流 + 城市筛选 chip
- 城市筛选切换：refetch + 局部 loading
- 分页加载：onReachBottom + 下一页 spinner
- 空数据（某城市没赛段）：空状态"该城市暂无赛段"
- fetch fail：retry 按钮

**数据需求**：

- `GET /api/segments?city={city}&page={n}&page_size=20`
  - 字段：id / name / distance / elevation_gain / difficulty / city / created_at / introduction（前 30 字）
  - **introduction 字段**：v5 Sprint 1+3 已有 / 由 admin 在 admin H5 草稿审核页填
  - **created_at 字段**：segments 表已有 / 用作"NEW 标签"判断（< 30 天 / 前端逻辑判断）
  - 后端默认 `order_by(created_at desc)`（service_query.py:82 / 新赛段自然排前面）

**异常情况**：

- 用户城市 = null 或 unknown → 默认显示"全部"列表（D9 / 不弹窗引导设置）
- segments 列表为空（极端 case，全砍）→ 空状态文案 + 引导贡献入口（暂不实现，Sprint 5+ 加）
- 砍 leaderboard 后小程序底部导航因 tab 数变化导致 icon 错位 → 必须真机测试

**验收标准**：

- 真用回归：Tim/CCF/颜颜进探索 tab 能看到 220 条赛段瀑布流，新批准的赛段（< 30 天）有 NEW 标签
- 城市筛选准确（"北京" → 只剩北京赛段）
- 分页滑到底部加载下一页正常
- 4 tab 切换流畅，没有死链接（grep 无 `pages/leaderboard` 残留引用）
- 单测：城市筛选 / 分页 / 空状态 / 跳转赛段详情页

**不做项**：

- 不做地图视图（瀑布流足够，地图留 Sprint 5+ 看真用反馈再决定）
- 不做"附近赛段"GPS 定位（同上）
- 不做赛段贡献入口（Sprint 5+）

**来源追溯**：§3.2 #6 + #7 / D5 / D6 / 用户故事 §2.2。

---

## 10. 子任务 4.5 - 赛段详情页新建（批 2 独立页）

**用户目标**：点探索 tab 卡片进入赛段详情 → 看到海拔曲线 + 城市 + 坡度 + 距离/爬升数字 + AI 介绍 + 我的记录 + 全网 top 10 排行榜 + 我的排名。这是骑手判断"这条值不值得骑"+"我跟自己比进步多少"+"我在全网什么位置"的核心页面。

**使用场景**：参用户故事 §2.2（小张点妙峰山）。

**功能范围**：

- 新建 `pages/segment/segment.wxml` + `segment.js` + `segment.json`（接受 query `?id=xxx`）
- 注册 `app.json` pages（不在 tabBar）
- 页面结构（**自上而下**）：
  1. **第一屏**：海拔曲线 + 城市 tag + 4 数字（距离 / 爬升 / 平均坡度 / 最大坡度）。**不展示难度评级 badge**（D14 / 难度算法 Sprint 5 细化）
  2. **AI 介绍 section**：标题"关于这条赛段" + 精选介绍（admin 审核过 / 50-100 字）+ 字数过长时支持展开/收起
  3. **我的记录 section**（D7 改文案 / 之前叫"我的 PB"）：
     - 用户骑过这条 → 显示个人最快时间 + 速度 + 哪天创下 + "你的进步：从 X 到 Y"
     - 用户没骑过 → "还没骑过这条赛段，骑一次试试看"+ 引导文案
  4. **全网排行榜 section**（D7 反转 / v0.1 砍后 v0.2 改回展示）：
     - top 10 列表（昵称 + 完成时间 + 头像 + 是否当前用户高亮）
     - "我的排名"行（独立显示 / 即使在 top 10 之外也展示我排名第几）
     - 未登录用户看到 top 10 但"我的排名"section 显示"登录后查看你的排名"
- 调 `GET /api/segments/{id}` 拿赛段全字段（含 introduction）+ `GET /api/user/efforts?segment_id={id}` 拿用户成绩 + `GET /api/segments/{id}/leaderboard?limit=10` 拿全网 top 10

**用户流程**：

参用户故事 §2.2 步骤 4-7。

**页面/状态**：

- loading（首次加载 / 三 fetch 并行：segment + my efforts + leaderboard）
- 数据完整（赛段 + 我的成绩 + leaderboard 都有）
- 数据完整（赛段有，我无成绩，但有 leaderboard）
- 数据完整（赛段有 introduction = null / 显示"暂无介绍" placeholder）
- 404（segment_id 不存在 → 错误页 + 返回探索按钮）
- 未登录看赛段详情 → 第一屏 + AI + leaderboard 正常显示，"我的记录"+"我的排名" section 显示"登录后查看你的成绩 / 排名"+ 登录按钮

**数据需求**：

- `GET /api/segments/{id}`（已有 / 含 introduction）
- `GET /api/user/efforts?segment_id={id}`（已有 / 单条赛段成绩）
- `GET /api/segments/{id}/leaderboard?limit=10`（已有 / D7 反转后调用 / 返回 top 10 + 当前用户排名）

**异常情况**：

- segment fetch 失败 → 全页错误状态 + retry
- user efforts fetch 失败 → "我的记录" section 显示"成绩加载失败" / 不破赛段信息显示
- leaderboard fetch 失败 → "全网排行榜" section 显示"排行榜加载失败" / 不破赛段信息 + AI 介绍显示
- introduction = "" 或 null → 显示 placeholder "暂无介绍"（不显示空白 section）
- leaderboard 总人数 < 10（小赛段）→ 全部展示，标题改"全网排行榜（共 X 人）"

**验收标准**：

- 真用回归：Tim/CCF 各自骑过的赛段详情页能看到自己的成绩 + 全网排名；没骑过的引导文案 + 仍能看到 leaderboard
- 单测：5 个路径（数据齐 / 没成绩 / 没 introduction / 404 / leaderboard 不足 10 人）
- 视觉沿用 v4 detail.wxml 海拔曲线同款形态（CLAUDE.md 陷阱 #17 wx:if 改 hidden）
- 跳转链路：探索 tab → 赛段详情页 → 返回探索 tab 状态保持（瀑布流位置不重置）

**不做项**：

- 不在第一屏展示难度评级 badge（D14 / 难度算法 Sprint 5 细化）
- 不做"我去过的次数"细粒度统计（efforts 单次记录够用）
- 不做赛段评论 / 收藏（Sprint 5+）
- 不做"附近赛段推荐"（Sprint 5+）

**来源追溯**：§3.2 #5 / D7（反转）/ D14 / 用户故事 §2.2 步骤 4-7。

---

## 11. admin H5 真用回归 ops 流程（**全 sprint 并行 / 非任务卡**）

**目标**：在 Sprint 4 期间通过 Tim/CCF/颜颜真用 admin H5 4 个工具，发现并修复真实使用 bug，让 admin H5 进入"稳定可交付状态"。

**启动时间**：本周内（不等批 1 ship）

**参与人员**：Tim / CCF / 颜颜（admin 权限已配 / user_id=1 token 见 CLAUDE.md "新会话起手必读"步骤 5）

**使用频率目标**：

- Tim：每天 30+ 分钟（候选池审 + 草稿审 + 创建工具）
- CCF：每周 2-3 次 30 分钟（候选池审 + 批量管理）
- 颜颜：每周 1-2 次 20 分钟（AI 草稿审）

**bug 收集流程**：

1. 真用过程发现 bug → 截图 + 一句话描述 + admin 操作步骤 → 群里发 Tim
2. Tim 评估 bug 严重度（P0 阻断使用 / P1 影响体验 / P2 建议优化）→ 决定是否进入 hotfix
3. P0/P1 bug → 主 agent 写 hotfix commit（不进 PRD 任务卡 / 走 commit 前 4 问 + Codex 异源审）
4. P2 bug → 记录到 `docs/tech-debt.md` Sprint 4 ops 章节，留 Sprint 5+ 处理

**期待 bug 类型**：

- UI 体验：按钮点不动 / 文案歧义 / 加载慢 / 异常状态没有反馈
- 跨端数据流：admin 改动后小程序消费不到（如 admin 审过 AI 介绍但小程序赛段详情页没刷新）
- 边界 case：超长文案 / 非法字符 / 并发编辑 / token 过期场景
- 部署稳定性：admin H5 502 / nginx DNS 缓存 / 飞书告警通道（D 决策已搁置）

**配套日志机制**：

- velo `app/monitor/admin_h5_health.py` 探针每 60s 跑一次（已部署 / log-only 模式 / D 决策搁置告警通道）
- 真用期间如发现探针 log 异常 → 同步记录到 deployment-diary.md

**Sprint 4 收尾时**：

- 统计 bug 数 / 修复数 / 残留 P2 数
- 评估 admin H5 是否进入"稳定可交付"状态
- 决定 Sprint 5 是否需要继续投入 admin 端

**来源追溯**：D12 / brainstorm Q3 配套。

---

## 12. 验收标准 + 测试 + 三审纪律

### 12.1 任务级验收（每个任务卡 §6-§10）

每个任务卡的"验收标准"section（§6.7 / §7.7 / §8.7 / §9.7 / §10.7）。

### 12.2 Sprint 4 整体验收

**批 1 ship 后 1 周真用回归**：

- Tim/CCF/颜颜各自看自己的功率曲线 + 热力图正常显示（city badge 有值则展示 / 无值不强制）
- 三人互相看对方用户详情页能看到对方公开字段，看不到敏感字段
- 真用反馈记录到 deployment-diary.md（即使没 bug 也要记"用了哪些场景 / 感受"）

**批 2 ship 后 1 周真用回归**：

- 探索 tab 瀑布流流畅 / 城市筛选准确 / NEW 标签合理
- 赛段详情页 AI 介绍 + 我的记录 + 全网 top 10 排行榜 + 我的排名显示正常
- 4 tab 切换流畅 / 无死链接 / 老用户切换习惯不破坏

**Sprint 4 收尾时**：

- 6 功能全部 ship + 真用过 / 不留半成品（哲学 D10 / city 字段顺带做不计独立功能）
- admin H5 真用回归收的 bug 全部 P0/P1 hotfix 完成
- 黑盒度三问通过（CLAUDE.md "防黑盒化"）
- 刷新 architecture-guide.md / data-flow-guide.md（Sprint 4 新增 4 tab 结构 / 新增 2 独立页）
- changelog.md 加 Sprint 4 章节

### 12.3 三审纪律（CLAUDE.md "三重审判"）

- spec 层（每个子任务 spec 写完）：Claude A 忠 spec / Claude B 集成审 → 收敛
- 代码层（每批 subagent 产出后）：Claude A / Claude B 双审 → Codex 异源第三审（命中 §5 跳过条件 → 跳过并 commit message 写理由）
- 真用层（每批 ship 后 1 周）：Tim 真用反馈 → 决定回收/重做/小修

### 12.4 强制检查清单（每子任务实施前必扫）

CLAUDE.md "强制检查清单"+"技术栈陷阱清单"全条扫一遍，特别注意：

- 陷阱 #17（wx:if vs hidden / canvas 渲染竞态）—— 4.1 / 4.2 / 4.5 都涉及 canvas
- 陷阱 #15（PostGIS ST_* 在 SQLite 不可用）—— 4.4 探索 tab 城市筛选可能涉及 PostGIS（地理筛选）
- chec 第 7 条（truthiness 陷阱）—— 4.2 city = null vs '' vs 0 判断必须 `is not None`

---

## 13. 收尾规则

- 每子任务 commit message：`feat(模块): 任务4.X 简要描述` / 沿用现有规范
- Sprint 4 收尾：跑 `/neat` skill → 更新 CLAUDE.md "进度" + memory + docs
- 与 phase-5-prd.md 关系：Sprint 4 = phase-5 整体收尾的 UI 层（phase-5 已 ship 后端 + admin H5）
- Sprint 4 ship 后 phase-5 整体里程碑达成 → Tim 决定是否进 phase-6 或继续 Sprint 5+ 打磨

**END phase-4-prd v0.1**
