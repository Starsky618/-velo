# Sprint Frontend 实施计划 · 总览（README）

> **For agentic workers**: REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 任务卡按 checkbox（`- [ ]`）执行追踪。

> 这是 velo "小程序 UI 4 tab 重构 + 接 Sprint 2 endpoint + admin H5 真用回归" 的实施计划目录。
>
> **对应产品文档**：`docs/prd/phase-4-prd.md`（v0.2 / commit `14eba8d`）
> **预估工期**：4 周（两批各 2 周 + admin H5 真用全程并行）
> **目录命名说明**：临时叫 `sprint-frontend/`，避免跟 `phase5/task-4.X.md`（v5 收尾任务）撞名。整期收尾时 Tim 拍最终命名（phase-6 / sprint-frontend / 别的）+ 整目录 `mv`。

---

## 一句话目标

**让 v5 期建好的后端能力（power_curve / heatmap / city / 看他人 profile / 候选池新赛段 / AI 介绍）真正被小程序前端消费起来，让骑手在 velo 看到自己的进步、找到值得骑的赛段、互相看到对方。同时让 admin H5 通过三人真用进入稳定可交付状态。**

具体见 `docs/prd/phase-4-prd.md` §2 用户故事 + §3 4 tab 新结构。

---

## 怎么用这份实施计划（给执行 Agent 的操作规程）

两层扁平结构：

```
README.md（你在看）          ← 全局约定 + 任务索引 + 依赖图
task-4.1.md ~ task-4.5.md   ← 5 张任务卡 + 1 张前置后端补 endpoint
```

### 每个 subagent 启动时**必须加载且只加载**以下 2 份文件：

1. **本文件 `README.md`**（全局约定 + 依赖 + ops 流程提要）
2. **你被分配的 `task-4.X.md`**（你当前任务完整细节）

**不要一次性加载多个 task 文件**——防止跨任务风格污染、注意力稀释。

如需参考另一任务产出的字段名 / endpoint 路径 → 先查本 README 末尾「字段索引 + endpoint 索引」，不够再打开对应 task 卡。

---

## 全局约定（执行期硬性必守 / 沿用 phase5/README.md 14 条 + 前端补 4 条）

### 沿用 phase5/README.md 全局约定 14 条（不重复列）

参 `docs/plans/phase5/README.md` § "全局约定（执行期硬性必守 14 条）"。重点回顾：

| 条目 | 在前端任务里的具体含义 |
|---|---|
| #1 truthiness 陷阱 | profile.city / introduction 等可能 null / "" / undefined 的字段判存在用 `is not None` 等价（小程序 wxml 用 `wx:if="{{x !== null && x !== undefined}}"`）|
| #6 单文件 ≤ 300 行黄灯 | profile.wxml 改造后预测 250-300 行；超 300 必拆 component |
| #9 commit 颗粒度 | 每个 task 一个独立 commit `feat(miniprogram): 任务4.X 简要描述` |
| #11 代码层三审 | Claude 双审 + Codex 异源审 commit 前必跑 / 跳过场景写 commit message |
| #12 时区硬约定 | NEW 标签判断"30 天内"按北京时间 UTC+8 算（`new Date().getTime() - 30*24*60*60*1000`）|

### 前端 sprint 专属补充 4 条

| # | 规则 | 为什么 |
|---|------|-------|
| F1 | **wx:if vs hidden 陷阱**（CLAUDE.md 陷阱 #17）：canvas / map 类组件统一用 `hidden` 不用 `wx:if` / setData callback 用 `setTimeout(fn, 100)` 替代 `wx.nextTick` | v5 90% 设备折线图不渲染事故的根因 / 必须遵守 |
| F2 | **沟通格式**（PRD 完工汇报给 Tim 看的）严守 CLAUDE.md §2.3：讲用户故事 + 禁堆术语 + 用生活类比。**违反 = 沟通失败**（"颗粒度 / 闭环 / 消费端 / 触点 / 抓手" 等禁用词清单）| Tim 是产品设计师不是程序员 |
| F3 | **"做完不好就删"哲学**：每功能 ship 后 1 周内 Tim/CCF/颜颜真用，发现 UI 不直观 / 用户场景不顺 → 直接删 / 重做，不留半成品 | PRD §0 开发哲学 / D10 |
| F4 | **不预设细节决策**：颜色 / 字号 / 布局间距 / 字段顺序 / 等留给 implementation；spec 卡只写信息优先级 + 状态 + 流程 | PRD §0 / Tim 不审视觉参数 |

---

## 任务依赖图

```
批 1：用户维度（~2 周 / 主战场 = 个人页 + 新建用户详情页）
┌──────────────────────────────────────────────┐
│  task-4.1 个人页框架改造  ← 第一步独立 ship   │
│        ↓ ship 验证稳定                        │
│  task-4.2 个人页内容塞入  ← 2 个 subagent 并行 │
│        ├─ 4.2.A 功率曲线                      │
│        └─ 4.2.B 热力图                        │
│  task-4.3 用户详情页新建  ← 含前置后端补 2 个 │
│         endpoint（看他人 power-curve/heatmap）│
└──────────────────────────────────────────────┘
        ↓ 批 1 ship 后 Tim/CCF/颜颜真用 1 周

批 2：赛段端（~2 周 / 主战场 = 探索 tab + 新建赛段详情页）
┌──────────────────────────────────────────────┐
│  task-4.4 探索 tab 改造 + 砍 leaderboard tab  │
│  task-4.5 赛段详情页新建（独立页 / 4 区块）   │
│         （AI 介绍 + 我的记录 + top 10 + 我排名）│
│  4.4 + 4.5 可并行（互不依赖）                 │
└──────────────────────────────────────────────┘
        ↓ 批 2 ship 后 Tim/CCF/颜颜真用 1 周

admin H5 真用回归（全 sprint 并行 / ops）
┌──────────────────────────────────────────────┐
│  Tim/CCF/颜颜每天用 admin H5 4 个工具        │
│  发现 bug → hotfix commit（不进任务卡）      │
│  详 phase-4-prd.md §11                       │
└──────────────────────────────────────────────┘
```

---

## 5 张任务卡一览

| # | 任务名 | 预估 | 前置 | 详情 |
|---|--------|------|------|------|
| 4.1 | 个人页框架改造（批 1 容器 / 第一步独立 ship）| 2-3d | 无 | task-4.1.md |
| 4.2 | 个人页内容塞入（功率曲线 + 热力图 / 2 并行）| 4-5d | 4.1 | task-4.2.md |
| 4.3 | 用户详情页新建（含前置后端补 2 endpoint）| 4-5d | 4.1 | task-4.3.md |
| 4.4 | 探索 tab 改造 + 砍 leaderboard tab | 5-6d | 批 1 ship | task-4.4.md |
| 4.5 | 赛段详情页新建（AI + 我的记录 + top 10）| 5-6d | 批 1 ship | task-4.5.md |

**合计**：~25-30 工作日 / 三人并行折算 4 周（含真用 1 周缓冲）

---

## 字段索引（subagent 写代码不要脑补）

### 后端已有 endpoint（v5 Sprint 2+3 ship / 直接调）

| endpoint | 方法 | 描述 | 调用方 task |
|---|---|---|---|
| `/api/user/login` | POST | 微信登录拿 token | 各页面统一 |
| `/api/user/profile` | GET | 自己 profile（含 city 字段） | 4.1 框架 |
| `/api/user/me/power-curve` | GET | 自己功率曲线 / period 参数 | 4.2 |
| `/api/user/me/heatmap` | GET | 自己热力图 / city 参数 | 4.2 |
| `/api/user/{user_id}/profile` | GET | 看他人 profile / 严格白名单 | 4.3 |
| `/api/user/efforts?segment_id=X` | GET | 我在某赛段的成绩（含 PB） | 4.5 |
| `/api/segments` | GET | 赛段列表（city / page / page_size 参数 / 默认按 created_at desc 排序）| 4.4 |
| `/api/segments/{id}` | GET | 赛段详情（含 introduction 字段）| 4.5 |
| `/api/segments/{id}/leaderboard?limit=10` | GET | 全网 top 10 + 我的排名 | 4.5 |

### 后端待补 endpoint（task-4.3 前置 / **必须先做**）

| endpoint | 方法 | 描述 | 工作量 |
|---|---|---|---|
| `/api/user/{user_id}/power-curve` | GET | 看他人功率曲线 / period 参数 | < 30 行 + 4 单测 |
| `/api/user/{user_id}/heatmap` | GET | 看他人热力图 / city 参数 | < 30 行 + 4 单测 |

### 关键字段值域（不要脑补 / 沿用 phase5 规范）

| 字段 | 真实值域 | 来源 |
|------|---------|------|
| `User.city` | NULL OR 6 城枚举 + 'unknown' | spec §3.1.3 |
| `Segment.city` | 6 城枚举 + 'unknown'（NOT NULL）| spec §3.1.3 |
| `Segment.introduction` | TEXT NULL（admin 审核后填）| Sprint 1+3 已落地 |
| `Segment.created_at` | TIMESTAMPTZ NOT NULL | 默认 NOW() / 用作 NEW 标签判断 |
| 6 城枚举 | `beijing / shanghai / hangzhou / shenzhen / chengdu / taiyuan` | spec §3.1.3 |

---

## 小程序文件路径索引（subagent 改造前 grep 验证现状）

| 模块 | 路径 | 当前状态 |
|---|---|---|
| 主入口 | `miniprogram/app.json` | 5 tab 配置（home/explore/upload/leaderboard/profile）+ 9 pages |
| 主入口 JS | `miniprogram/app.js` | 全局 token / globalData |
| 动态 tab | `miniprogram/pages/home/` | 不动 |
| **探索 tab** | `miniprogram/pages/explore/` | 当前占位"即将上线"／**4.4 大改造** |
| 上传 tab | `miniprogram/pages/upload/` | 不动 |
| **赛段 tab** | `miniprogram/pages/leaderboard/` | **4.4 删整目录** |
| **个人 tab** | `miniprogram/pages/profile/` | **4.1 改造 + 4.2 塞内容** |
| 活动详情 | `miniprogram/pages/detail/` | 不动 / 4.4 改"途经赛段"section 跳转 |
| 通知中心 | `miniprogram/pages/notification/` | 不动 / 头像跳转改向用户详情页 |
| 荣誉 | `miniprogram/pages/honor/` | 不动 |
| 设置 | `miniprogram/pages/settings/` | 不动 / city 字段编辑入口已有 |
| **用户详情页** | `miniprogram/pages/user/` | **4.3 新建** |
| **赛段详情页** | `miniprogram/pages/segment/` | **4.5 新建** |
| API 工具 | `miniprogram/utils/api.js` | 各 task 加新 endpoint 调用方法 |

---

## admin H5 真用回归 ops（全 sprint 并行 / 详 phase-4-prd.md §11）

- **启动时间**：本周内（不等批 1 ship）
- **参与人员**：Tim / CCF / 颜颜（admin 权限已配 / 详 CLAUDE.md "新会话起手必读"步骤 5）
- **bug 收集流程**：发现 bug → 截图 + 操作步骤 → 群里发 Tim → 评估 P0/P1/P2 → P0/P1 进 hotfix commit / P2 入 tech-debt
- **不进任务卡数**：bug 不论多少都走 hotfix 路径，跟 5 张开发任务卡解耦
- **配套监测**：velo `app/monitor/admin_h5_health.py` 每 60s 探针 / log-only 模式

---

## 收尾规则

- 每 task 完工后 commit message 沿用现有格式
- 所有 5 张 task 完成后**不立刻**做"sprint 收尾刷文档"——等"v5 + Sprint 4 整期一起收尾"（参 README 顶部目录命名说明）
- 整期收尾时 phase5/task-4.1 ~ 4.4（v5 收尾 4 任务）和本目录的 task-4.1 ~ 4.5（前端 5 任务）一起做完结归档

**END README v0.1**
