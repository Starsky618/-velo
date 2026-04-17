# 第 4 期实施计划 · 总览（README）

> 这是 VELO 第 4 期「前端反馈环闭合 + Strava 集成加固」的实施计划目录。
> 对应技术文档：`docs/spec-v4.md`（v4 版，Critical=0）。
> 工期预估：1 周编码 + 2 天测试部署 ≈ 9 天。

---

## 本期做什么（一句话）

**把后端早就做好的成就数据（通知 / 荣誉 / Strava 同步）真正送到用户眼前**，顺手修 8 个历史坑 + 埋 3 颗多运动种子。

具体见 spec-v4.md 开场白。

---

## 怎么用这份实施计划（给执行 Agent 的操作规程）

这份实施计划是**两层结构**：

```
README.md（你在看这个）← 根：全局约定 + 任务索引 + 依赖图 + 符号索引
task-7.1.md ~ 7.11.md ← 叶子：每任务独立的完整实现 + 测试 + commit
```

> **为什么不加第三层 INDEX.md**：叶子已经有 11 个，再加一层索引层会变成"索引的索引"——新增一级心智成本不抵省的一点查找时间。符号索引合并到本文件末尾的"符号索引"节即可。

### 每个子 agent 启动时**必须加载且只加载**以下 2 份文件：

1. **本文件 `README.md`**（全局约定 + 依赖 + 符号索引——你需要知道的所有前置）
2. **你被分配的 `task-7.X.md`**（你当前要执行的任务完整细节）

**不要一次性加载多个 task 文件**——防止跨任务风格污染、注意力稀释。

### 如果你在执行任务 7.X 时发现需要参考另一个任务 7.Y 的细节：

- 先查本文件末尾的"符号索引"节——如果你要用的只是"7.Y 产出的函数签名"，那里就有
- 只有当符号索引信息不够时，才打开 `task-7.Y.md` 精确查阅

---

## 全局约定（执行期硬性必守 10 条）

这些是从项目 CLAUDE.md 提炼、所有任务共用的执行纪律。**每个任务都必须遵守，无例外。**

| # | 规则 | 为什么 |
|---|------|-------|
| 1 | **truthiness 陷阱**：判断 bool 字段用 `is True` / `== False`，不用 `if x` | 历史踩坑：`if user.mute_notifications` 会把 NULL 当 False |
| 2 | **状态机前置校验**：status 变更前 `assert` 前置状态 | 防止跳跃或倒退（如 completed → processing） |
| 3 | **SAVEPOINT 隔离**：循环里 flush 后可能 rollback 的用 `db.begin_nested()` | 防 rollback 炸掉循环外已 flush 数据 |
| 4 | **日志格式**：关键步骤 `logger.info("xxx user_id=%d activity_id=%d", uid, aid)` | Worker 在后台跑，日志是唯一的眼睛 |
| 5 | **单向依赖**：新代码**禁止反向 import**，固定为 user ← activity ← segment ← notification ← strava | 防循环依赖 |
| 6 | **代码健康度**：单文件 ≤300 行黄灯 / ≤500 行红灯 | 防文件臃肿到无法理解 |
| 7 | **DB 改动走 Alembic**：禁止手动 ALTER TABLE | 环境可复现 |
| 8 | **测试先行**：纯函数模块先写 fixture 再写实现 | TDD 纪律 |
| 9 | **commit 颗粒度**：每个子任务一个独立 commit，格式 `feat(模块): 任务 7.X 简要描述` | 便于 revert 单步 |
| 10 | **完工三问**：每任务结束必答 task 文件末尾「自检三问」，答不满意不交付 | 质量前移 |

---

## 任务依赖图

```
┌──────────────────────┐
│  7.1 Alembic + 模型   │ ← 全局根任务（加字段 / 改外键 / 改 tz）
└────────┬─────────────┘
         │
    ┌────┴────┬─────────────┬──────────────┬──────────────┐
    ↓         ↓             ↓              ↓              ↓
  ┌─────┐  ┌─────┐        ┌─────┐        ┌─────┐        ┌─────┐
  │ 7.2 │  │ 7.4 │        │ 7.5 │        │ 7.7 │        │ 7.8 │
  │OAuth│  │Web  │        │impor│        │解析 │        │mark │
  │state│  │hook │        │t-pro│        │器分 │        │-all │
  └──┬──┘  │白名 │        │gress│        │流   │        │-read│
     │     │单   │        └──┬──┘        └─────┘        └─────┘
     ↓     └─────┘           │
  ┌─────┐                    ↓
  │ 7.3 │                 ┌─────┐
  │call │                 │ 7.9 │
  │back │                 │sched│
  │防重 │                 │uler │
  │绑   │                 │容器 │
  └──┬──┘                 └─────┘
     │
     ↓
  ┌─────┐
  │ 7.6 │
  │现有 │
  │函数 │
  │加固 │
  └─────┘

所有后端（7.1~7.9）完成后
     ↓
┌──────────────────────┐
│ 7.10 小程序前端       │ ← 6 页/组件
└─────────┬────────────┘
          ↓
┌──────────────────────┐
│ 7.11 集成测试 + 收尾   │ ← 更新 architecture-guide.md + 黑盒度体检
└──────────────────────┘
```

---

## 11 个任务一览

| # | 任务名 | 预估 | 前置依赖 | 修补什么 Critical/Important | 详情 |
|---|--------|------|---------|---------------------------|------|
| 7.1 | Alembic 迁移 + 模型改动 | 1h | — | C3 C5 I1 I4 | task-7.1.md |
| 7.2 | Strava OAuth state 加固 | 1.5h | 7.1 | C1 C8 | task-7.2.md |
| 7.3 | callback 防重复绑定 + 换号清理 | 2h | 7.1 / 7.2 | C2 I6 | task-7.3.md |
| 7.4 | Webhook subscription_id 校验 | 1h | — | C4 | task-7.4.md |
| 7.5 | import-progress stalled + 限速 | 1h | 7.1 | C7 I11 | task-7.5.md |
| 7.6 | Strava 现有函数加固 | 2h | 7.3 | I7 I8 I9 I10 | task-7.6.md |
| 7.7 | 解析器入口分流（种子 3）| 1h | 7.1 | — | task-7.7.md |
| 7.8 | mark-all-read + unread_count | 1.5h | 7.1 | I2 I3 | task-7.8.md |
| 7.9 | scheduler 容器部署 | 1h | 7.5 | C3 | task-7.9.md |
| 7.10 | 小程序前端（6 页/组件）| 2d | 7.1~7.9 | — | task-7.10.md |
| 7.11 | 集成测试 + 收尾 | 1d | 全部 | — | task-7.11.md |

**合计后端**：≈ 12h 编码（可并行 7.4、7.5、7.7、7.8 四任务）
**前端**：≈ 2d
**测试 + 收尾**：≈ 1d
**总计**：~7-9 工作日

---

## 符号索引（subagent 查前置任务产出时用）

**用途**：当你执行任务 7.X 需要知道前置任务 7.Y 产出了什么，先查这张表。如果签名还不够，再打开对应的 task 文件看详情。

### 新增字段（task-7.1）

| 字段 | 所在表 | 定义 |
|------|-------|------|
| `is_read` | notifications | BOOLEAN NOT NULL DEFAULT FALSE |
| `activity_type` | activities | VARCHAR(20) NOT NULL DEFAULT 'cycling' |
| `mute_notifications` | users | BOOLEAN NULLABLE（种子字段）|

字段改动：`strava_imports.updated_at` → `DateTime(timezone=True)`
外键改动：`notifications.segment_id/activity_id` → ON DELETE SET NULL
新增索引：`idx_notifications_user_unread`（部分索引）

### 新增函数（按任务归属）

| 任务 | 新增 / 改动 | 函数 |
|------|-----------|------|
| task-7.2 | 新增 | `build_authorize_url(user_id, redis) -> str` |
| task-7.2 | 新增 | `verify_state_and_consume(state, redis) -> int` |
| task-7.3 | 重写 | `handle_callback(db, code, state, redis) -> dict`（注意新加 redis 参数）|
| task-7.3 | 新增 | `_cleanup_old_athlete_activities(db, user_id, old_athlete_id) -> int` |
| task-7.6 | 改 | `ensure_valid_token`（401 分支 pause imports）|
| task-7.6 | 改 | `_run_tier1`（连续 2 次空才判完成）|
| task-7.6 | 改 | `handle_manual_sync`（更新 tier1_completed）|
| task-7.7 | 改 | `parse_activity`（activity_type 分流，非 cycling 置 failed）|
| task-7.8 | 新增 | `mark_all_read(db, user_id) -> int` |
| task-7.8 | 改 | `get_notifications`（加 `unread_only` 参数 + 响应加 `unread_count`）|

### 新增异常类

| 任务 | 类 | 用途 |
|------|---|------|
| task-7.2 | `InvalidStateError` | state 已使用/过期/跨用户 |
| task-7.3 | `BoundByOtherUserError` | 该 Strava 账号已绑到其他 VELO 账号 |

### 新增 / 改动接口

| 任务 | 方法 | 路径 | 改动 |
|------|------|------|------|
| task-7.8 | POST | `/api/notifications/mark-all-read` | 新增接口 |
| task-7.8 | GET | `/api/notifications` | 加 `unread_only` 参数 + 响应加 `unread_count` |
| task-7.5 | GET | `/api/strava/import-progress` | 响应加 `view_status`（支持 stalled）|
| task-7.4 | POST | `/api/strava/webhook` | 加 subscription_id 校验 + 未配置返 503 |

### 新增配置 / 部署

| 任务 | 项 | 位置 |
|------|---|------|
| task-7.4 | 环境变量 `STRAVA_WEBHOOK_SUBSCRIPTION_ID` | config.py + .env.example + docker-compose.yml |
| task-7.9 | 新容器 `scheduler` | docker-compose.yml |
| task-7.9 | 新脚本 `scheduler.py` | 项目根目录 |
| task-7.10 | Caddy 新路由 `/strava/bind/*` | Caddyfile |

---

## 执行顺序建议

### 可串行可并行的组（避免混乱推荐串行）

1. **第 1 天**：7.1（根任务，必先完成）
2. **第 2-3 天并行**：7.2 → 7.3，7.4，7.5，7.7，7.8（多个 subagent 同时跑）
3. **第 4 天**：7.6（依赖 7.3 完成）
4. **第 5 天**：7.9（依赖 7.5）+ 后端集成测试
5. **第 6-7 天**：7.10 小程序前端
6. **第 8-9 天**：7.11 集成测试 + 收尾

---

## 每任务的自检三问（所有任务通用）

任务收尾时必须答：

1. 这个任务新增/改动的代码，**10 分钟内能讲清楚它做什么吗**？如果要想 30 秒以上才能讲，**拆分或加注释**
2. 如果**这段代码崩在运行时**，系统会处于什么状态？能自愈吗？孤儿数据吗？
3. 我是否**没做 spec 没要求的"顺手优化"**？（边界纪律，防 scope creep）

---

## 修订记录

- 2026-04-17：初版，对应 spec-v4.md v4
