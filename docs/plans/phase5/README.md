# 第 5 期实施计划 · 总览（README）

> 这是 VELO 第 5 期「赛段内容深化 + 数据成长 + 个人页 + admin 工具」的实施计划目录。
> 对应技术文档：`docs/spec-v5.md`（v5 版，3 轮双审 Critical=0 已收敛）。
> 对应产品文档：`docs/prd/phase-5-prd.md`。
> 工期预估：8-10 周（三人并行折算）。

---

## 本期做什么（一句话）

**让赛段从"光秃数据"变成"有人味的内容"，让个人页从"流水账"变成"看得见的进步"，让 admin 团队有手感地做内容运营。**

具体见 `docs/spec-v5.md` 开场白 + `docs/prd/phase-5-prd.md` § 用户故事。

---

## 怎么用这份实施计划（给执行 Agent 的操作规程）

两层扁平结构：

```
README.md（你在看这个）← 根：全局约定 + 任务索引 + 依赖图 + 符号索引
task-0.1.md ~ task-4.4.md ← 叶子：每任务独立的完整实现 + 测试 + commit
```

> 任务数 29 张 ≤ 100，**禁止加第三层索引文件**（如 INDEX.md / SYMBOLS.md）—— 符号索引并入本 README 末尾即可。

### 每个 subagent 启动时**必须加载且只加载**以下 2 份文件：

1. **本文件 `README.md`**（全局约定 + 依赖 + 符号索引——所有前置）
2. **你被分配的 `task-N.X.md`**（你当前要执行的任务完整细节）

**不要一次性加载多个 task 文件**——防止跨任务风格污染、注意力稀释。

### 如果你执行任务 N.X 时需要参考另一个任务 N.Y 的细节：

- 先查本文件末尾的「符号索引」节—— 80% 场景"前置任务产出的函数签名 / 字段名"已在那
- 不够再打开 `task-N.Y.md` 精确查阅

---

## 全局约定（执行期硬性必守 14 条）

从项目 CLAUDE.md + spec-v5 决策记录提炼，所有任务共用的执行纪律。**每任务都遵守，无例外。**

| # | 规则 | 为什么 |
|---|------|-------|
| 1 | **truthiness 陷阱**：bool 字段判 `is True` / `== False`，存在性判 `is not None` | v0/v4 踩坑两次：`if user.mute_notifications` 把 NULL 当 False；`if power` 把 0 当 None |
| 2 | **状态机前置校验**：status 变更前 `assert` 前置状态 | 防跳跃 / 倒退（如 completed → processing） |
| 3 | **SAVEPOINT 隔离**：循环 flush 后可能 rollback 用 `db.begin_nested()` | 防 rollback 炸循环外已 flush 数据（matcher / import_scheduler 沿用） |
| 4 | **日志格式**：关键步骤 `logger.info("xxx user_id=%d activity_id=%d", uid, aid)` | Worker 后台跑无界面，日志是唯一眼睛 |
| 5 | **单向依赖（强化版）**：`user ← activity ← segment ← notification ← strava`；**新增 `app/common/*` 在所有模块下方**（任意模块可向下依赖 common，common 不依赖任何业务模块） | 防循环依赖；v5 抽 `app/common/geo.py` 解决 user → segment 反向依赖 |
| 6 | **代码健康度**：单文件 ≤ 300 行黄灯 / ≤ 500 行红灯；同一职责的"成绩单计算器"不强拆 | 防文件臃肿；职责混杂才拆 |
| 7 | **DB 改动走 migrations/**：禁止手动 ALTER TABLE。**真实路径是 `migrations/versions/`**（不是 `alembic/versions/`） | 环境可复现；spec §0.1 已查实 |
| 8 | **测试先行**：纯函数模块先写 fixture 再写实现；每纯函数 ≥ 5 case 含边界 | TDD 纪律 + 边界覆盖 |
| 9 | **commit 颗粒度**：每 task 一个独立 commit，格式 `feat(模块): 任务 N.X 简要描述` | 便于 revert 单步 |
| 10 | **完工三问**：每任务结束必答 task 文件末尾「自检三问」，答不满意不交付 | 质量前移 |
| 11 | **代码层三审**（commit 前硬性）：Claude 双审（A 忠 spec / B 集成审）+ Codex 异源第三审。**跳过场景**：纯文档 / 单文件 < 50 行 / 紧急 hotfix（理由写 commit message） | architect 信条 5 + CLAUDE.md 强制 |
| 12 | **时区硬约定**：DB 存 UTC（DateTime 字段 `timezone=True`）；"本周 / 本月 / 本年"按**北京时间 UTC+8** 计算（先 `datetime.now(UTC).astimezone(BJ_TZ)` 再 `.replace(day=1)` 算月初） | CLAUDE.md 关键技术约定 + v5 spec §3.3 §3.6 已对齐 |
| 13 | **Redis 单一连接源**：`from app.queue import redis_conn`，**禁止**各模块自己 `Redis.from_url`。Queue 实例（default_queue / ai_drafts_queue）也在 `app/queue.py` expose | Sprint 0 task 0.8 拍板 + 第三轮双审 R3-I4 |
| 14 | **配置走 settings.XXX**：`from app.config import settings` + `settings.ANTHROPIC_API_KEY`，**禁止**顶层常量 `from app.config import ANTHROPIC_API_KEY` | 项目现有 30+ 处一致风格 |

---

## 任务依赖图（跨 Sprint 的全景）

```
Sprint 0：地基修补 (5-8 天，单 worktree 串行)
┌─────────────────────────────────────────────────────────┐
│  0.1 datetime tz-aware       ← 必先（Sprint 1+ 假设依赖） │
│  0.2 ensure_valid_token 锁注释化                          │
│  0.3 ensure_valid_token 未绑定路径                        │
│  0.4 SQLAlchemy legacy .get() 替换                        │
│  0.5 scheduler Redis 复用                                 │
│  0.6 v5 主迁移（segments 加字段 + 新表）  依赖 0.1        │
│  0.7 老数据回填脚本                       依赖 0.6        │
│  0.8 app/queue.py 单一连接源              独立            │
└─────────────────────────────────────────────────────────┘
        ↓ 0.1 + 0.6 + 0.7 + 0.8 全完成 = closure
─────────────────────────────────────────────────────────
Sprint 1：B 主轴 + worker 软目标 (10-14 天，3 模块组并行)
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ A: segment   │  │ B: agent 模块 │  │ C: monitor 模块│
│  1.A.1 字段+算法│  │  1.B.1 segment│  │  1.C.1 健康度  │
│  1.A.2 service │  │   _writer +   │  │     扫描       │
│  1.A.3 router  │  │   tasks.py    │  │                │
│  组内串行       │  │ 独立 worktree │  │ 独立 worktree  │
└──────────────┘  └──────────────┘  └──────────────┘
        ↓ Sprint 1 closure
─────────────────────────────────────────────────────────
Sprint 2：C 主轴 + A 主轴 (12-15 天，3 模块组并行)
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│ A: notification│  │ B: activity  │  │ C: user 模块（串）│
│  2.A.1 progress│  │  power_zones │  │  2.C.1 models city│
│   detector    │  │  2.B.1 power │  │  2.C.2 service ×5 │
│  独立 worktree │  │   curve 算法 │  │  2.C.3 router ×4  │
│              │  │ 独立 worktree │  │ 组内严格串行      │
└──────────────┘  └──────────────┘  └──────────────────┘
        ↓ Sprint 2 closure
─────────────────────────────────────────────────────────
Sprint 3：D 主轴 (12-18 天，3 模块组并行)
┌──────────────────────────────┐  ┌─────────────┐  ┌─────────┐
│ A: admin 模块（5 严格串行）    │  │ B: H5 admin │  │ C: 脚本 │
│  3.A.1 框架（依赖+router 骨架）│  │  独立 repo  │  │  3.C.1  │
│  3.A.2 5.D.1 候选池 endpoint   │  │  3.B.1 项目 │  │ 候选池+ │
│  3.A.3 5.D.2 草稿审核 endpoint │  │             │  │  cron   │
│  3.A.4 5.D.3 批量管理 endpoint │  │             │  │         │
│  3.A.5 5.D.4 from-activity     │  │             │  │         │
└──────────────────────────────┘  └─────────────┘  └─────────┘
        ↓ Sprint 3 closure
─────────────────────────────────────────────────────────
Sprint 4：收尾 (5-7 天，主 agent 主导)
  4.1 文档刷新 / 4.2 黑盒度三问 / 4.3 集成测试 + 部署 / 4.4 复盘归档
```

---

## 29 个任务一览

### Sprint 0：地基修补（依赖 — 无）

| # | 任务名 | 预估 | 前置 | 修补什么 | 详情 |
|---|--------|------|------|---------|------|
| 0.1 | datetime 全局 tz-aware | 2-3d | — | 陷阱 #2 + B2B-2 | task-0.1.md |
| 0.2 | ensure_valid_token 行锁注释化 | 1d | — | tech-debt | task-0.2.md |
| 0.3 | ensure_valid_token 未绑定路径 | 0.5d | — | tech-debt | task-0.3.md |
| 0.4 | SQLAlchemy legacy `.get()` 替换 | 0.5d | — | tech-debt | task-0.4.md |
| 0.5 | scheduler Redis 连接复用 | 0.5d | 0.8 | tech-debt | task-0.5.md |
| 0.6 | v5 主迁移（新字段 + 新表） | 0.5d | 0.1 | C11 | task-0.6.md |
| 0.7 | 老数据回填脚本 | 0.5-1d | 0.6 | C11 | task-0.7.md |
| 0.8 | app/queue.py 单一 Redis 源 | 1d | — | B3B-1 + R3-I4 | task-0.8.md |

### Sprint 1：B 主轴 + worker 软目标（依赖 Sprint 0 closure）

| # | 任务名 | 预估 | 前置 | 模块组 | 详情 |
|---|--------|------|------|--------|------|
| 1.A.1 | segment 模块：算法纯函数 + city/difficulty/max_gradient 字段 | 2d | 0.6 | A 串 | task-1.A.1.md |
| 1.A.2 | segment service 扩展（搜索 + 即时反馈 + from-activity） | 3d | 1.A.1 | A 串 | task-1.A.2.md |
| 1.A.3 | segment router 扩展 + 即时反馈 endpoint | 1d | 1.A.2 | A 串 | task-1.A.3.md |
| 1.B.1 | agent 模块新建（segment_writer + tasks.py） | 2d | 0.8 | B 独立 | task-1.B.1.md |
| 1.C.1 | monitor 模块新建（worker 软目标 + 飞书告警） | 2d | 0.8 | C 独立 | task-1.C.1.md |

### Sprint 2：C 主轴 + A 主轴（依赖 Sprint 1）

| # | 任务名 | 预估 | 前置 | 模块组 | 详情 |
|---|--------|------|------|--------|------|
| 2.A.1 | notification.progress_detector + payload 字段 | 2d | 1.A.1 | A 独立 | task-2.A.1.md |
| 2.B.1 | activity.power_zones：calculate_power_curve + _from_activities | 2d | — | B 独立 | task-2.B.1.md |
| 2.C.1 | user.models 加 city 字段 | 0.5d | 0.6 | C 串 | task-2.C.1.md |
| 2.C.2 | user.service：5 个新函数（power-curve / heatmap / city / profile） | 4d | 2.C.1 + 2.B.1 | C 串 | task-2.C.2.md |
| 2.C.3 | user.router：4 个新 endpoint | 1d | 2.C.2 | C 串 | task-2.C.3.md |

### Sprint 3：D 主轴（依赖 Sprint 1）

| # | 任务名 | 预估 | 前置 | 模块组 | 详情 |
|---|--------|------|------|--------|------|
| 3.A.1 | admin 模块框架（dependencies + router 骨架） | 1d | 2.C.2 | A 严格串 | task-3.A.1.md |
| 3.A.2 | 5.D.1 候选池 endpoint（GET + PATCH） | 2d | 3.A.1 + 3.C.1 | A 严格串 | task-3.A.2.md |
| 3.A.3 | 5.D.2 AI 草稿审核 endpoint | 2d | 3.A.2 + 1.B.1 | A 严格串 | task-3.A.3.md |
| 3.A.4 | 5.D.3 批量管理 endpoint（GET + PATCH） | 2d | 3.A.3 | A 严格串 | task-3.A.4.md |
| 3.A.5 | 5.D.4 from-activity endpoint（advisory lock） | 2d | 3.A.4 + 1.A.2 | A 严格串 | task-3.A.5.md |
| 3.B.1 | H5 admin 项目（独立 repo） | 5-7d | 3.A.* | B 独立 | task-3.B.1.md |
| 3.C.1 | scripts/generate_curation_pool.py + cron 配 | 1.5d | 0.6 | C 独立 | task-3.C.1.md |

### Sprint 4：收尾（5-7 天，主 agent 主导）

| # | 任务名 | 预估 | 前置 | 详情 |
|---|--------|------|------|------|
| 4.1 | 文档刷新（architecture-guide + data-flow-guide + changelog + tech-debt） | 1d | 全部 | task-4.1.md |
| 4.2 | 黑盒度三问体检 | 0.5d | 4.1 | task-4.2.md |
| 4.3 | 集成测试 + 部署验证 | 2d | 全部 | task-4.3.md |
| 4.4 | v5 复盘归档（memory + adr） | 1d | 4.3 | task-4.4.md |

**合计**：Sprint 0 (5-8d) + 1 (10-14d) + 2 (12-15d) + 3 (12-18d) + 4 (5-7d) ≈ **44-62 工作日 / 三人并行折算 8-10 周**。

---

## 符号索引（subagent 查前置任务产出时用）

### 新增字段（按表归属）

| 表 | 字段 | 类型 | 默认 | NULL | CHECK | 任务 |
|----|------|------|------|------|-------|------|
| segments | difficulty | VARCHAR(16) | 'medium' | NOT NULL | IN ('easy','medium','hard','extreme') | 0.6 |
| segments | max_gradient | FLOAT | NULL | NULL | — | 0.6 |
| segments | city | VARCHAR(32) | 'unknown' | NOT NULL | IN (6 城 + 'unknown') | 0.6 |
| users | city | VARCHAR(32) | NULL | NULL | NULL OR IN (6 城 + 'unknown') | 0.6 + 2.C.1 |
| notifications | payload | JSONB | NULL | NULL | — | 2.A.1 |

### 新增表（v5 全新）

| 表 | 主键 | 关键字段 | 任务 |
|----|------|---------|------|
| segment_ai_drafts | id | segment_id (UNIQUE FK) / ai_draft_text / human_edited_text / status (CHECK 4 值) / editor_user_id | 0.6 |
| segment_curation_pool | id | segment_id (UNIQUE FK) / pool_score / selected_for_v5 / pool_reason | 0.6 |

### 既有关键枚举值（subagent 写代码时不要脑补）

| 字段 | 真实值域 | 来源 |
|------|---------|------|
| `Activity.status` | `pending / processing / completed / failed / importing` | spec §0.1 已查实 |
| `Activity.data_source` | `gpx / fit / strava` | 不是 'upload' |
| `StravaImport.status` | `active / paused / completed` | 不是 running/pending |
| `Notification.event_type` | `pr / kom / kom_lost / progress_segment_pb / progress_5min_power` | v5 新增后 2 种 |
| `SegmentAiDraft.status` | `pending / human_edited / approved / rejected` | v5 新增 |
| 6 城枚举 | `beijing / shanghai / hangzhou / shenzhen / chengdu / taiyuan / unknown` | spec §3.1.3 |

### 新增函数（按任务归属）

| 任务 | 模块 | 函数 | 签名 |
|------|------|------|------|
| 1.A.1 | `app/common/geo.py` | `infer_city_from_coords(lat, lon) -> str` | 坐标 → 6 城枚举 |
| 1.A.1 | `app/segment/service.py` | `_haversine_distance(lat1, lon1, lat2, lon2) -> float` | 米 |
| 1.A.1 | `app/segment/service.py` | `calculate_max_gradient(trackpoints) -> float \| None` | 100m 滑窗最大坡度 % |
| 1.A.1 | `app/segment/service.py` | `calculate_difficulty(distance, elev_gain, max_gradient) -> str` | 4 档枚举 |
| 1.A.2 | `app/segment/service.py` | `get_segment_list(...search/city/difficulty)` | tuple[list, int]，**保留现有契约** |
| 1.A.2 | `app/segment/service.py` | `get_my_effort_with_compare(db, segment_id, user_id) -> dict` | 即时反馈 6 字段 |
| 1.A.2 | `app/segment/service.py` | `create_segment_from_activity(db, activity_id, name, start, end, ...) -> Segment` | advisory lock 串行 |
| 1.B.1 | `app/agent/segment_writer.py` | `generate_segment_draft(segment_props) -> str` | 同步调 Anthropic |
| 1.B.1 | `app/agent/tasks.py` | `generate_segment_draft_task(segment_id) -> None` | RQ 异步入口 |
| 2.A.1 | `app/notification/progress_detector.py` | `detect_5min_power_progress(db, user_id, activity_id) -> Notification \| None` | baseline ≤ 0 守卫 |
| 2.B.1 | `app/activity/power_zones.py` | `calculate_power_curve(trackpoints, windows_sec) -> dict` | 单次骑行 |
| 2.B.1 | `app/activity/power_zones.py` | `calculate_power_curve_from_activities(activities_tps, windows_sec) -> dict` | 跨 N 次骑行 per-window max |
| 2.C.2 | `app/user/service.py` | `get_user_power_curve(db, user_id, period) -> dict` | + Redis 缓存 |
| 2.C.2 | `app/user/service.py` | `invalidate_power_curve_cache(user_id) -> None` | worker hook 调 |
| 2.C.2 | `app/user/service.py` | `get_user_heatmap(db, user_id, city) -> list` | JSONB 聚合 + 缓存 |
| 2.C.2 | `app/user/service.py` | `update_user_city(db, user_id, city) -> User` | + 失效热图缓存 |
| 2.C.2 | `app/user/service.py` | `get_user_profile_for_others(db, target, requester) -> dict` | RESPONSE_KEYS 白名单 |

### 新增 / 改动接口

| 任务 | 方法 | 路径 | 权限 | 改动 |
|------|------|------|------|------|
| 1.A.3 | GET | `/api/segments` | **公开** | 加 search / city / difficulty 参数（不加 current_user，沿用现有匿名访问） |
| 1.A.3 | GET | `/api/segments/{id}` | 沿用 | 响应加 max_gradient / city / difficulty 字段 |
| 1.A.3 | GET | `/api/segments/{id}/efforts/me` | current_user | 即时反馈 6 字段；router 显式查 segment 抛 404 |
| 2.C.3 | GET | `/api/users/me/power-curve?period=` | current_user | 6 个 period 枚举 |
| 2.C.3 | GET | `/api/users/me/heatmap?city=` | current_user | 城市筛 |
| 2.C.3 | PATCH | `/api/users/me` | current_user | body 加 city 字段（不替换现有 PUT /profile）|
| 2.C.3 | GET | `/api/users/{user_id}/profile` | current_user | RESPONSE_KEYS 白名单过滤 |
| 3.A.* | * | `/api/admin/*` | require_admin | 新前缀，全部新建 |
| 3.A.3 | POST | `/api/admin/ai/segment-drafts/{id}/generate` | require_admin | 202 Accepted + enqueue RQ |

### 新增配置 / 部署

| 任务 | 项 | 位置 |
|------|---|------|
| 0.6 | migrations revision 2 份（A=tz-aware / B=v5 主迁移） | `migrations/versions/` |
| 0.7 | `scripts/backfill_phase5.py` | 项目根 + docker-compose 跑一次性容器 |
| 0.8 | `app/queue.py` 新建（redis_conn / default_queue / ai_drafts_queue） | 项目根 |
| 1.B.1 | 环境变量 `ANTHROPIC_API_KEY` | `app/config.py settings` + `.env.example` + docker-compose.yml |
| 1.B.1 | `requirements.txt` 加 `anthropic` SDK | requirements.txt |
| 1.B.1 | docker-compose worker `RQ_QUEUES=velo,ai_drafts` env | docker-compose.yml |
| 1.C.1 | 环境变量 `FEISHU_BOT_WEBHOOK` | settings + .env + docker-compose.yml |
| 1.C.1 | monitor 容器（while true; sleep 60）+ `--scale worker=3` 部署文档 | docker-compose.yml |
| 3.B.1 | H5 admin 独立 repo + `admin.velo.com` 域名 + Caddyfile 反代 | 部署文档 |
| 3.C.1 | cron 容器跑 `generate_curation_pool.py`（每周一次） | docker-compose.yml |

### 新增异常类

| 任务 | 类 | 用途 |
|------|---|------|
| 1.A.2 | `SegmentOverlapError` | from-activity 重复检测命中（Hausdorff 阈值）|
| 1.A.2 | `InvalidSegmentRangeError` | start_index >= end_index / 子序列点数不足 / 太短 |

---

## 执行顺序建议

1. **Sprint 0 串行跑完**（0.1 → 0.6 → 0.7 ；0.2-0.5 / 0.8 可与上述并行）
2. **Sprint 1 三模块组并行**（A 串 / B 独立 / C 独立）
3. **Sprint 2 三模块组并行**（A 独立 / B 独立 / C 串）
4. **Sprint 3**：A 严格串 + B/C 跟 A 并行
5. **Sprint 4**：主 agent 主导收尾

每完成一个 task：
- 跑代码层 Claude 双审（A 忠 spec / B 集成审）
- 跑 Codex 异源第三审（按 `docs/agent-rules/codex-division-of-labor.md §4 场景 B`）
- Critical 修完才 commit
