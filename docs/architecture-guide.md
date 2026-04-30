# velo 系统架构全景 v2

> **Primary audience: AI coding agents.** Humans may reference but will find it terse.
> Structured for query, not narrative. Every field/path/port/env-var is precise.
>
> Mental model primer (human-friendly one-paragraph): velo 是一台 "骑行成绩加工厂"。用户上传骑行数据,工厂拆解为成绩单、排行榜、通知,用户拿走结果。加工厂由 6 个车间组成,共享 7 个后厨(容器),数据存 7 张表。数据单向流动,不回头。— 往下不再使用此类比喻。

---

## 目录

1. [系统边界](#1-系统边界)
2. [业务模块(6+1)](#2-业务模块61)
3. [运行时容器(7)](#3-运行时容器7)
4. [数据表(7)](#4-数据表7)
5. [API 汇总](#5-api-汇总)
6. [前端结构](#6-前端结构)
7. [依赖方向规则](#7-依赖方向规则)
8. [AI 改动定位表](#8-ai-改动定位表)
9. [已知风险状态](#9-已知风险状态)
10. [文档交叉引用](#10-文档交叉引用)

---

## 1. 系统边界

### 1.1 包含

- 微信小程序前端(velo)
- 后端 API(FastAPI)
- 异步 Worker(rq)
- 调度器(scheduler)
- 僵尸扫描(cleanup)
- PostgreSQL + PostGIS 数据库
- Redis(队列 + state + 限流)
- Caddy 反向代理
- 第三方集成: Strava OAuth/API/Webhook

### 1.2 不包含(明确排除)

- iOS / Android 原生 app(v7+ 才考虑)
- 实时导航(跳转高德,见 ADR-010)
- 骑行路线算法生成(只推荐历史轨迹,见 ADR-010)
- 机器学习 / 深度学习模型(RAG 作为独立小项目隔离,见 ADR-009)
- 视频内容
- 电商 / 支付(v8+ 考虑,不在任何当前期)

### 1.3 代码量基线(v5 Sprint 1 end / 2026-04-30)

| 层 | 行数 |
|---|---|
| 后端 Python | ~10500（+segment v5 扩展 / agent / monitor / common） |
| 小程序前端 | ~2000 |
| **总计** | **~12500** |

⚠️ agent 注意: 当前期 PR 评估健康度黄灯阈值更新为后端 11000 行(CLAUDE.md 健康度自动巡检规则)。

---

## 2. 业务模块(8+1)

### 2.1 模块清单

| 模块 | 文件夹 | 代码量 | 引入版本 | 核心职责 |
|---|---|---|---|---|
| user | `app/user/` | 591 行 | v0 | 微信登录、JWT、个人资料、统计 |
| activity | `app/activity/` | 1617 行 | v0 | 骑行活动 CRUD、异步解析调度 |
| segment | `app/segment/` | ~2320 行 | v0 | 赛段定义、匹配算法、排行榜、即时反馈、from-activity（v5 +474 行）|
| parsing | `app/parsing/` | 1802 行 | v1 | GPX/FIT/Strava 三源统一翻译层(纯函数) |
| strava | `app/strava/` | 1996 行 | v2 | Strava OAuth/API/Webhook/tier1-2 导入 |
| notification | `app/notification/` | 693 行 | v3 | PR/KOM/KOM_lost 事件检测、通知列表 |
| **agent** | `app/agent/` | **252 行** | **v5** | **AI 赛段介绍生成（DeepSeek + RQ async）** |
| **monitor** | `app/monitor/` | **138 行** | **v5** | **worker 软目标监控（4min 阈值 + 飞书告警）** |
| **common** | `app/common/` | **61 行** | **v5** | **跨模块工具：地理函数 / haversine / city 推断** |

### 2.2 模块内部结构(统一约定)

```
app/<模块名>/
  __init__.py      # 对外暴露什么
  models.py        # SQLAlchemy 数据模型
  schemas.py       # Pydantic 请求/响应
  router.py        # FastAPI 路由
  service.py       # 业务逻辑,不碰 HTTP
  worker.py        # rq 异步任务(仅 activity 有;segment/strava 的异步逻辑混在 service 或单独文件)
  README.md        # 模块画像(占位,逐模块补)
```

实际模块文件清单(v5 Sprint 1 end):

- `app/activity/`: models / schemas / router / service / worker / simplify / power_zones
- `app/segment/`: models / schemas / router / service / auto_match / matcher / coord_convert / _geo_utils / **algorithms** (v5) / **exceptions** (v5)
- `app/parsing/`: gpx_parser / fit_parser / strava_adapter / stats_calculator / coord_normalizer / geo_math / types
- `app/strava/`: models / router / service / client / import_scheduler
- `app/notification/`: models / schemas / router / service / detector(在 service 内部)
- `app/user/`: models / schemas / router / service
- **`app/agent/`** (v5): __init__ / segment_writer / tasks（DeepSeek + RQ）
- **`app/monitor/`** (v5): __init__ / processing_health（cron 60s + 飞书告警）
- **`app/common/`** (v5): __init__ / geo（haversine / infer_city_from_coords）

⚠️ agent 注意:
- 新增模块必须遵守此结构,不得自创
- `service.py` 超过 300 行需要评估拆分(见 tech-debt.md)
- 纯函数文件(如 `parsing/gpx_parser.py`, `segment/matcher.py`)不碰 DB,独立可测(见 ADR-008)

### 2.3 模块依赖图

```
             parsing(纯函数层)
             ↑          ↑
             │          │
    user ← activity ← segment ← notification
              ↑          ↑
              │          │
              └── strava ┘
              (strava 依赖 user/activity/segment/parsing,
               通过 import_scheduler 写入 activities + segment_efforts + notifications)
```

**实际依赖**(grep 验证,v4 end):

- `user`: 无业务模块依赖
- `parsing`: 纯函数层,不 import 任何业务模块
- `activity`: 依赖 `user` + `parsing`
- `segment`: 依赖 `user` + `activity`(通过 trackpoints 查询)
- `notification`: 依赖 `user` + `activity` + `segment`
- `strava`: 依赖 `user` + `activity` + `segment` + `parsing`(`import_scheduler.py` import `activity.models.Activity` / `activity.worker.save_parse_result` / `segment.models.SegmentEffort` / `segment.auto_match.match_activity_against_segments`)

⚠️ agent 注意:
- strava **不是**"独立只出不入"——它反向消费 activity/segment 的 model 和 worker 函数,这是当前写入 Strava 导入活动的必经之路
- 违反核心依赖方向(user ← activity ← segment ← notification)= 循环 import = FastAPI 启动崩溃
- strava 反向 import activity/segment 不构成循环(activity/segment 不 import strava),但新增时必须确认单向

---

## 3. 运行时容器(8)

### 3.1 容器清单

| 容器 | 镜像/启动 | 端口 | 引入版本 | 职责 |
|---|---|---|---|---|
| caddy | `caddy:2-alpine` | 80, 443(外) | v0 | HTTPS 终结、证书续期、反向代理 |
| api | `velo-api` | 8000(内) | v0 | FastAPI, 接用户请求 |
| worker | `velo-worker` | - | v0 | rq worker,异步解析/匹配（v5 起加 ai_drafts 队列） |
| scheduler | `velo-scheduler` | - | **v4** | 每 30s 推进 Strava 导入(tier1/tier2) |
| cleanup | `velo-cleanup` | - | v0 | 每 5min 扫 status=processing 超 10 分钟的 activity 置 failed |
| **monitor** | `velo-monitor` | - | **v5** | **每 60s 扫 stuck 4min+ activity 推飞书告警（task-1.C.1）** |
| db | `postgis/postgis:16-3.4` | 5432(内) | v0 | PostgreSQL 16 + PostGIS 3.4 |
| redis | `redis:7-alpine` | 6379(内) | v0 | rq 队列 + OAuth state nonce + 限流计数 |

### 3.2 容器职责细则

#### caddy

- 配置文件: `Caddyfile`(生产) / `Caddyfile.dev`(本地)
- 自动 Let's Encrypt 证书续期
- 代理规则: `api.velo.xxx` → `api:8000`
- 失败症状: 用户完全无法访问,502/504

#### api

- 启动: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- 全**同步**模式(见 ADR-001,禁止 async def)
- 连接池: `pool_size=8, max_overflow=12, pool_recycle=3600`
- 失败症状: 小程序报 500

#### worker

- 启动: `python worker.py`
- rq 单 worker 进程,listen `rq:queue:default`
- 子进程 fork 模式执行任务(崩溃隔离)
- 超时 300s,重试 3 次,失败 → dead letter queue
- 失败症状: 上传后永远"处理中"

#### scheduler(v4 新增)

- 启动: `python scheduler.py`
- 每 30s 执行 `_run_tier1` + `_run_tier2`
- Redis 连接**每次新建**(tech-debt #5,见 §9.2)
- Redis 限速: 每 user 每秒 1 次 Strava API 调用
- 失败症状: `/api/strava/import-progress` 的 `view_status` 为 `stalled`

#### cleanup

- 启动: `sh -c "while true; do python scripts/cleanup_zombies.py; sleep 300; done"`(脚本路径在 `scripts/`,不是根目录)
- 每 300s 扫描: `SELECT * FROM activities WHERE status='processing' AND updated_at < now() - interval '10 minutes'`
- 批量置 `failed`
- 失败症状: 僵尸 activity 越积越多

#### monitor(v5 task-1.C.1 新增)

- 启动: `sh -c "while true; do python -m app.monitor.processing_health || true; sleep 60; done"`
- 每 60s 扫: `SELECT * FROM activities WHERE status='processing' AND updated_at < now() - interval '4 minutes'`（软阈值，4min 是 cleanup 10min 硬上限的 80%）
- 命中 → 推飞书机器人（`FEISHU_BOT_WEBHOOK` env / 没配则跳过推送）
- 不写业务表 / 不改 status —— **只读 + 告警**，硬上限自愈仍走 cleanup
- 失败症状: 用户上传 GPX 卡 4-10 分钟时我们三人收不到飞书

#### db

- 挂载 volume: `pgdata:/var/lib/postgresql/data`
- 备份策略(未做,tech-debt)
- 失败症状: 所有功能 500

#### redis

- 挂载 volume: (目前仅 docker-compose 默认,无显式持久化 volume 配置)
- 三用途: rq 队列 / OAuth state nonce(TTL 10min) / 限流计数(TTL 1s)
- 失败症状: Worker 收不到任务 / OAuth 回调失败 / 限流失效

### 3.3 容器拓扑

```
外部 HTTPS
    ↓
[caddy] ─────────┐
                 ↓
            [api] ←──→ [redis]
              ↓           ↑
            [db] ←──── [worker]
              ↑           ↑
              │        [scheduler]
              │
              └──── [cleanup]
```

⚠️ agent 注意:
- 所有容器通过 docker-compose 内部网络通信,不暴露除 80/443 外的端口到宿主机(db/redis 仅绑定 127.0.0.1)
- 容器重启顺序依赖: `db` → `redis` → `api/worker/scheduler/cleanup` → `caddy`
- 修改 `docker-compose.yml` 需要全栈重启,不是热加载

---

## 4. 数据表(10 / v5 +3)

### 4.1 表清单

| 表 | 引入版本 | 量级预估 | 负责模块 |
|---|---|---|---|
| `users` | v0（v5 加 city / mute_notifications） | 1k-10k | user |
| `activities` | v0（v5 加 activity_type） | 30k-300k | activity |
| `trackpoints` | v0 | 3M-30M | activity |
| `segments` | v0（**v5 加 difficulty / max_gradient / city / elevation_loss / avg_gradient**） | 30-500 | segment |
| `segment_efforts` | v0 | 5k-50k | segment |
| `strava_imports` | v2 | 同 users | strava |
| `notifications` | v3（v5 加 payload JSONB） | 5k-50k | notification |
| **`segment_ai_drafts`** | **v5** | **同 segments** | **agent**（pending→human_edited→approved/rejected 状态机）|
| **`segment_curation_pool`** | **v5** | **30-500** | **segment**（admin 候选池 + 周期性脚本算分）|
| **`progress_records`** | **v5** | **同 users × period** | **notification**（5W 进步推送幂等记录，task-0.6 建表 / 5.C.3 起用）|

### 4.2 表字段规格

> 所有字段以 `app/*/models.py` 为准。文档每期收尾对照 models.py 校验。

#### 4.2.1 users

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| openid | str(64) unique | 微信 openid |
| nickname | str(64) | 微信昵称(可空) |
| avatar_url | text | 微信头像 URL(可空) |
| ftp | int | 功率阈值 W(可空) |
| weight | float | 体重 kg(可空) |
| bike_type | str(20) | `road`/`gravel`/`mtb`(v4,可空) |
| **weekly_goal** | float | 周目标公里,server_default=200.0(v4) |
| is_admin | bool | 管理员标记,server_default=false(v1 手动改 DB 赋权) |
| **strava_athlete_id** | BigInteger unique | Strava 用户 ID(v2,可空) |
| **strava_access_token** | str(255) | Strava 访问令牌(v2,可空) |
| **strava_refresh_token** | str(255) | Strava 刷新令牌(v2,可空) |
| **strava_token_expires_at** | timestamp tz | Strava token 过期时间(v2,可空) |
| **mute_notifications** | bool | 免打扰预留字段(v3,可空;本期前端不读写,仅占位) |
| created_at | timestamp | server_default=now() |
| updated_at | timestamp | onupdate=now() |

⚠️ agent 注意:
- **没有** `unionid` / `role` 字段(文档早期版本曾列出,已证伪)
- `mute_notifications` 是预留字段,三态(NULL/true/false),实际开关存前端本地
- `strava_*` token 字段明文存储(tech-debt,后续应加密)

#### 4.2.2 activities

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| user_id | int FK → users.id | |
| title | str(128) | 可空 |
| status | str(20) | `pending`/`processing`/`importing`(Strava)/`completed`/`failed`(见 §4.3) |
| **file_url** | text | 原始文件存储路径,GPX/FIT 必填,Strava 来源为 NULL |
| **file_hash** | str(64) | SHA-256 去重,用 `UNIQUE(user_id, file_hash)` 兜底 |
| error_message | text | 解析失败时的错误信息,可空 |
| distance | float | 米,可空 |
| duration | int | 秒,可空 |
| elevation_gain | float | 米,可空 |
| **avg_speed** | float | **m/s**(以 parsing/stats_calculator 为准,可空) |
| **max_speed** | float | **m/s**(可空) |
| avg_power | float | W,可空 |
| **max_power** | float | W,可空 |
| **normalized_power** | float | NP,FIT 自带,GPX/Strava 为 NULL |
| **avg_hr** | float | bpm,可空(字段名**不是** `avg_heart_rate`) |
| **max_hr** | float | bpm,可空 |
| avg_cadence | float | rpm,可空 |
| **calories** | float | kcal,可空 |
| started_at | timestamp | 骑行开始,可空 |
| finished_at | timestamp | 骑行结束,可空 |
| **data_source** | str(20) | `gpx`/`fit`/`strava`(v2,老数据 NULL) |
| **activity_type** | str(20) | `cycling`/`running`/`hiking`,server_default=cycling(v4) |
| **strava_activity_id** | BigInteger unique | Strava 活动 ID,非 Strava 来源为 NULL |
| simplified_track | jsonb | Douglas-Peucker 简化轨迹 |
| **splits** | jsonb | 每 10km 分段(v4) |
| **power_zones** | jsonb | 功率区间分布(v4,依赖 FTP) |
| created_at | timestamp | |
| updated_at | timestamp | |

索引: `idx_activities_user_status(user_id, status)` / `idx_activities_user_started(user_id, started_at)` / `UNIQUE(user_id, file_hash) uq_user_file_hash`

⚠️ agent 注意:
- 字段名是 **`file_url`** 不是 `gpx_file_url`,**`avg_hr`** 不是 `avg_heart_rate`
- **没有** `moving_time` 字段(早期文档误列,实际只有 `duration`)
- **没有** `card_image_url` 字段(v1 规划但后端卡片流水线从未实现,前端 Canvas 一条路)
- **没有** `is_deleted` 软删字段(硬删 + 外键级联)
- 速度字段单位是 **m/s**(stats_calculator 统一口径),activity/models.py 字段注释写的 `km/h` 是旧注释错误,以 parsing 层为准

#### 4.2.3 trackpoints

| 字段 | 类型 | 说明 |
|---|---|---|
| id | serial PK | |
| activity_id | int FK → activities.id ON DELETE CASCADE | |
| seq | int | 顺序 |
| latitude | float | 必填 |
| longitude | float | 必填 |
| elevation | float | 米,可空 |
| timestamp | timestamp | 可空 |
| heart_rate | int | bpm,可空 |
| cadence | int | rpm,可空 |
| power | int | W,可空 |
| **speed** | float | 瞬时速度 m/s(v2,老数据 NULL) |
| **distance** | float | 累计距离米(v2,老数据 NULL) |
| geom | `GEOMETRY(POINT, 4326)` | PostGIS 几何列,可空 |

索引: `idx_trackpoints_activity(activity_id)` + `idx_trackpoints_geom GIST(geom)`

⚠️ agent 注意:
- 缺少 `UNIQUE(activity_id, seq)` 约束(tech-debt,Worker 重试可能插重复)
- 批量插入用 `bulk_insert_mappings`,不要 `session.add` 循环
- 上限 50000 点/activity(见 CLAUDE.md 已知风险)

#### 4.2.4 segments

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| name | str(128) | 必填 |
| **description** | text | 可空 |
| distance | float | 米,必填 |
| elevation_gain | float | 米,可空 |
| elevation_loss | float | 米,可空 |
| avg_gradient | float | %,可空 |
| **elevation_profile** | **text** | 海拔采样 JSON 字符串(约 80 个数值)——**不是 jsonb** |
| start_lat | float | 必填 |
| start_lon | float | 必填 |
| end_lat | float | 必填 |
| end_lon | float | 必填 |
| match_tolerance | float | server_default=50.0(米) |
| min_match_ratio | float | server_default=0.8 |
| reference_line | `GEOMETRY(LINESTRING, 4326)` | 参考轨迹,必填 |
| created_at | timestamp | |

索引: **`idx_segments_geom GIST(reference_line)`**(真实索引名不是 `idx_segments_reference_line`)

⚠️ agent 注意:
- **没有** `updated_at` 字段(只有 `created_at`)
- **没有** `status`(draft/active/archived)/`city`/`category`/`reference_points jsonb` 字段(v1 规划未实现)
- 创建/删除只能 admin 通过 API 做

#### 4.2.5 segment_efforts

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| segment_id | int FK → segments.id | |
| activity_id | int FK → activities.id ON DELETE CASCADE | |
| user_id | int FK → users.id | 冗余存储,排行榜查询不必 JOIN |
| elapsed_time | int | 秒,必填 |
| **avg_speed** | float | km/h,可空 |
| avg_power | float | W,可空 |
| **start_index** | int | 匹配到的 trackpoint seq 起,必填 |
| **end_index** | int | 匹配到的 trackpoint seq 止,必填 |
| created_at | timestamp | |

索引 + 约束:
- **`UNIQUE(segment_id, activity_id) uq_segment_activity`**(**两列**,不是三列)
- `idx_efforts_segment_time(segment_id, elapsed_time)` — 排行榜
- `idx_efforts_user(user_id)` — 个人成绩
- `idx_efforts_segment_user_time(segment_id, user_id, elapsed_time)` — PR 检测 index-only scan

⚠️ agent 注意:
- **没有** `avg_heart_rate` / `started_at` 字段
- **没有** `is_pr` / `is_kom` 字段(PR/KOM 是 notification.service 计算后的事件,只在 `notifications` 表有,见 ADR-004)
- PR/KOM 展示需要前端 join `/api/activities/{id}/segments` + `/api/notifications?event_type=pr` 两个接口

#### 4.2.6 strava_imports(v2)

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| user_id | int FK → users.id | 一个用户可能多次解绑再绑,同时只一个 active |
| **strava_athlete_id** | BigInteger | 冗余存储,不必 JOIN users |
| **total_activities** | int | 首扫列表后填入,扫描前 NULL |
| **tier1_completed** | **int**(**计数器**,不是 bool) | server_default=0,第一层列表扫描完成数 |
| **tier2_completed** | int | server_default=0,第二层详情+轨迹完成数 |
| **tier2_skipped** | int | server_default=0,跳过数(非骑行/无轨迹等) |
| **cursor_before** | timestamp tz | 断点续传时间游标,NULL=从最新起 |
| status | str(20) | `active`/`paused`/`completed`,server_default=active |
| created_at | timestamp | naive |
| **updated_at** | timestamp tz | v4 改为 tz-aware(stalled 判定用) |

⚠️ agent 注意:
- `updated_at` 是 tz-aware,其他表的 datetime 是 naive(tech-debt #1)
- 不要直接 `datetime.utcnow()`,用 `datetime.now(timezone.utc)`
- **没有** `tier2_cursor`(实际叫 `cursor_before`)/`last_strava_sync_at`/`total_imported`/`total_skipped`/`last_error` 字段(文档早期版本误列,已证伪)
- `tier1_completed` 是计数器 int,不是 bool —— 判断"tier1 扫完"的逻辑在 service 层,不在 DB 字段层面

#### 4.2.7 notifications(v3)

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| user_id | int FK → users.id ON DELETE CASCADE | 接收人 |
| event_type | str(20) | `pr`/`kom`/`kom_lost`,CHECK 约束 |
| **segment_id** | int FK → segments.id ON DELETE SET NULL | v4 外键改 SET NULL,可空 |
| **activity_id** | int FK → activities.id ON DELETE SET NULL | v4 外键改 SET NULL,可空 |
| **effort_id** | int FK → segment_efforts.id ON DELETE SET NULL | 关联成绩,可空 |
| **elapsed_time** | int | 用时快照秒数(kom_lost 时 NULL) |
| **rank** | int | 排名快照,PR 且 rank>10 时 NULL |
| **rival_user_id** | int FK → users.id ON DELETE SET NULL | KOM 被夺时的对手 |
| expires_at | timestamp | created_at+60 天 |
| created_at | timestamp | |
| **is_read** | bool | server_default=false(v4 新增) |

索引 + 约束:
- `UNIQUE(effort_id, event_type) uq_notif_effort_type` — 幂等防护,同成绩不重复生成同类通知
- `idx_notif_user_created(user_id, created_at)` — 列表按用户+时间倒序
- `idx_notif_expires(expires_at)` — 过期清理
- `idx_notifications_user_unread(user_id) WHERE is_read=FALSE` — **v4 部分索引**,加速 unread_count 查询(在 phase4_frontend_consume migration 建)
- `CheckConstraint event_type IN ('pr','kom','kom_lost') ck_notif_event_type`

⚠️ agent 注意:
- **没有** `message` / `meta jsonb` 字段(文档早期版本误列,实际通知内容由前端按 event_type 组装)
- `effort_id` 是幂等防护主键,不是可选字段——新通知必须带 effort_id(kom_lost 可为 NULL 是特例)

### 4.3 表关系图

```
users (1) ─── (N) activities ─── (N) trackpoints (CASCADE)
  │                │
  │                ├─── (N) segment_efforts (CASCADE) ──(N)── segments
  │                │
  │                └─── (N) notifications (SET NULL)
  │                                 │
  │                                 ├─ segment_id (SET NULL) → segments
  │                                 ├─ effort_id (SET NULL) → segment_efforts
  │                                 └─ rival_user_id (SET NULL) → users
  │
  └─── (1..N) strava_imports (同一 user 可有多条,同时只一条 active)
```

### 4.4 Activity 状态机

```
[不存在]
   │ upload
   ▼
[pending] ─── worker 抢锁 ──► [processing] ─── 解析成功 ──► [completed]
                                  │                            │
                                  │ 10min 超时                  │ 匹配 + 通知触发
                                  ▼                            │
                              [failed]                          │
                                                                ▼
                                                        (不再变状态)

Strava 导入路径:
[不存在] ──► [importing] ─── 解析成功 ──► [completed]
                 │
                 │ 失败
                 ▼
             [failed]
```

⚠️ agent 注意:
- 完成态叫 `completed` 不叫 `done`(CLAUDE.md 技术栈陷阱 #10 — 不要脑补状态值)
- worker 抢锁用 `UPDATE activities SET status='processing' WHERE id=X AND status='pending'`,原子,幂等
- 禁止非法状态转换,应用层校验(DB 层无 CHECK 约束,tech-debt)

### 4.5 StravaImport 状态机

```
[active] ──── 用户点暂停 ──► [paused]
   │          ◄── 用户点继续
   │
   │ tier1_completed=total 且 tier2 扫完全部历史
   ▼
[completed]
```

⚠️ agent 注意: `active` 不叫 `running`,`completed` 不叫 `done`。

---

## 5. API 汇总

### 5.1 用户(4)

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/user/login` | 微信登录,body `{code: str}`,return `{token, user, is_new}` |
| GET | `/api/user/profile` | 个人资料 |
| PUT | `/api/user/profile` | 更新个人资料 |
| GET | `/api/user/stats` | 骑行统计(总里程等) |

### 5.2 活动(7)

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/activities/upload` | 上传 GPX/FIT,multipart/form-data |
| GET | `/api/activities` | 活动列表,分页 `page` + `page_size` |
| GET | `/api/activities/{id}` | 活动详情 |
| PATCH | `/api/activities/{id}` | 改标题等 |
| DELETE | `/api/activities/{id}` | 删 |
| GET | `/api/activities/{id}/timeseries` | 速度/心率/功率时间序列 |
| GET | `/api/activities/{id}/status` | 轮询解析进度 |

### 5.3 赛段(8 / v5 +1)

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/segments` | 创建赛段,admin only |
| DELETE | `/api/segments/{id}` | 删,admin only |
| GET | `/api/segments` | 赛段列表，支持 `?near_lat&near_lon&radius` 附近搜索 + **v5 加 `?search&city&difficulty` 三筛选**（公开访问，PRD §B-P02）|
| GET | `/api/segments/{id}` | 详情 + TOP20，**v5 响应字段加 `max_gradient` / `city` / `difficulty` / `avg_gradient`** |
| GET | `/api/segments/{id}/leaderboard` | 完整排行榜 |
| **GET** | **`/api/segments/{id}/efforts/me`** | **即时反馈对比 6 字段（current/last/pr/diff/is_pr/is_first）/ v5 task-1.A.3 新增** |
| GET | `/api/user/efforts` | 我的所有赛段成绩(挂载在 user_effort_router) |
| GET | `/api/activities/{id}/segments` | 此活动经过的赛段 + 成绩(activity_segment_router) |

### 5.4 通知(3)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/notifications` | 列表,支持 `unread_only` 参数,响应必带 `unread_count` |
| POST | `/api/notifications/mark-all-read` | 一键标读,幂等 |
| GET | `/api/user/honors` | KOM + Top 10 荣誉聚合(挂载在 honor_router) |

### 5.5 Strava(7 路由,6 行展示)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/strava/authorize` | 获取授权链接,Redis nonce state |
| GET | `/api/strava/callback` | OAuth 回调,防重复绑定 + 换号清理 |
| GET | `/api/strava/status` | 绑定状态,响应含 `bound`=`connected` |
| GET | `/api/strava/webhook` | Webhook 订阅验证(challenge) |
| POST | `/api/strava/webhook` | Webhook 事件推送,subscription_id 校验防伪造 |
| POST | `/api/strava/sync` | 手动触发同步,联动 tier1_completed |
| GET | `/api/strava/import-progress` | 进度,含 `view_status`: `none/active/stalled/paused/completed`,Redis 1s/user 限速 |

**API 总路由数: 25**(user 4 + activity 7 + segment 5 + user_effort 1 + activity_segment 1 + notification 2 + honor 1 + strava 7 − 1(`/api/user/efforts` 归 segment 一组统计)= 25,按业务组 4+7+7+3+7 加总 25 不变)。

⚠️ agent 注意:
- 完整 OpenAPI schema: `/api/docs`(FastAPI 自动生成)
- 所有需登录接口都走 JWT 中间件,401 时前端应该 `wx.login` 静默续期
- API 路径用**复数**(`/activities` 不是 `/activity`),但 `/user/*` 不复数(单用户 resource)

---

## 6. 前端结构

### 6.1 小程序 5 tabs(v4 实际)

| # | 名称 | 图标 | 职责 |
|---|---|---|---|
| 1 | 动态 | 屋子 | 我的活动列表 + 周统计卡片 + 铃铛通知入口(未来加关注 feed) |
| 2 | 探索 | 指南针 | (v4 瘦身后暂空,待 v5/v6 填热图 + 附近赛段) |
| 3 | 上传 | 加号 | GPX/FIT 上传 → 解析 → 跳详情页 |
| 4 | 赛段 | 山峰 | 赛段列表 + 排行榜 + 我的成绩(leaderboard 页) |
| 5 | 我的 | 人像 | 个人资料(profile) + 骑行记录 + 设置 + 荣誉入口 |

### 6.2 子页(非 tab)

- `miniprogram/pages/notification/` — 通知中心(从铃铛进入)
- `miniprogram/pages/honor/` — 荣誉页(我的 → 荣誉入口)
- `miniprogram/pages/settings/` — 设置页(免打扰开关)
- `miniprogram/pages/detail/` — 活动详情页(任何列表点击进入)
- `miniprogram/pages/leaderboard/` — 赛段 tab 兼详情(含坡度剖面,v5 待完整化)
- `miniprogram/pages/upload/` — 上传 tab
- `miniprogram/pages/explore/` — 探索 tab(v4 暂空)
- `miniprogram/pages/profile/` — 我的 tab
- `miniprogram/pages/home/` — 动态 tab

### 6.3 前端-后端数据流示例

**"动态 tab 显示活动卡片上的 PR 徽章"的真实数据流**:

```
home.onShow()
  │
  ├─── GET /api/activities  ──► 活动列表 A
  │
  ├─── GET /api/notifications?unread_only=true&page_size=1 ──► unread_count(铃铛红点)
  │
  └─── 对每条活动 A[i]:
        GET /api/activities/{A[i].id}/segments ──► 经过的赛段 + 成绩
        GET /api/notifications?activity_id={A[i].id}&event_type=pr ──► PR 事件
        合并后渲染 "PR <段名> <时间>" 徽章
```

⚠️ agent 注意:
- PR/KOM 数据**不在** `/api/activities/{id}` 主响应里(见 ADR-004)
- 前端要 join 两个接口(activities/segments + notifications)才能算出徽章
- v4 前端瘦身后,探索 tab 和信息流 feed 暂时空白,v5+ 填内容

---

## 7. 依赖方向规则

### 7.1 铁律

```
核心链:   user ← activity ← segment ← notification
纯函数层: parsing (被 activity + strava 调用, 无反向依赖)
集成层:   strava 依赖 user + activity + segment + parsing
         (通过 import_scheduler 写入 activities + segment_efforts + notifications)
```

- `user`: 不 import 任何业务模块
- `parsing`: 纯函数,不 import 任何业务模块
- `activity`: 只 import `user` 和 `parsing`
- `segment`: 只 import `user` 和 `activity`(通过 trackpoints)
- `notification`: 只 import `user / activity / segment`
- `strava`: import `user / activity(models+worker) / segment(models+auto_match) / parsing`

**strava 不是独立"只出不入"**——它反向消费 activity/segment 的 model 和函数,这是把 Strava 活动落入 velo 数据库的必经路径。只要 activity/segment **不反向** import strava,就不构成循环。

### 7.2 防火墙式扩展

**新功能默认新表、新模块,禁止修改核心表**(`users` / `activities` / `segments` / `segment_efforts`),除非修 bug。

- ✅ 正例: 积分系统建 `user_progress` 独立表,不在 `users` 加 `score/level`
- ❌ 反例: v4 把 `mute_notifications` 加到 `users`(已做,未来想砍代价大)
- ❌ 反例: v4 把 `activity_type` 加到 `activities`(已做)

详见 ADR-008(为什么防火墙式扩展)。

### 7.3 agent-native 独立性

v7+ 的 agent 模块与主 SaaS 通过**薄接口**连接,不共享 session / 不互相 import。见 ADR-009(为什么 agent 层独立)。

---

## 8. AI 改动定位表

用于: agent 告诉 Tim"我改了 X 文件",Tim 5 秒内判断影响范围。

| AI 说改了这个文件 | 动的是 | 需要警惕 | 哪个容器重启 |
|---|---|---|---|
| `app/user/*.py` | 登录/资料 | 所有登录相关 | api |
| `app/activity/models.py` | activities/trackpoints 表 | **必须 Alembic 迁移** | api + worker + 迁移 |
| `app/activity/service.py` | 活动业务逻辑 | 跨模块依赖 | api |
| `app/activity/worker.py` | 异步解析调度 + `save_parse_result` | 幂等、重入、strava 复用 | worker |
| `app/activity/simplify.py` / `power_zones.py` | 纯函数后处理 | 无副作用必须保持 | worker |
| `app/segment/auto_match.py` | 赛段匹配总调度 | 匹配假阳/假阴率 | worker |
| `app/segment/matcher.py` | 纯函数空间匹配 | 无副作用必须保持 | worker |
| `app/segment/service.py` | 排行榜查询 | N+1 查询 | api |
| `app/notification/detector.py` 或 service 内部 | PR/KOM 检测纯函数 | 事件逻辑 | worker |
| `app/notification/service.py` | 通知列表/标读/荣誉 | 前端红点 | api |
| `app/parsing/gpx_parser.py` | GPX 解析纯函数 | 所有 GPX 上传 | worker |
| `app/parsing/fit_parser.py` | FIT 解析纯函数 | 所有 FIT 上传 | worker |
| `app/parsing/strava_adapter.py` | Strava 数据 → ParseResult | Strava 导入链路 | worker + scheduler |
| `app/parsing/stats_calculator.py` | 统计字段生成 | splits/power_zones 口径 | worker |
| `app/strava/service.py` | Strava OAuth/业务 | token 失效、换号 | api + scheduler |
| `app/strava/client.py` | Strava API client | 限流、token 刷新 | api + scheduler |
| `app/strava/import_scheduler.py` | tier1/2 推进 | Redis 连接复用(tech-debt #5)、SAVEPOINT 隔离 | scheduler |
| `app/main.py` | 路由注册 | 新 API 能否访问 | api |
| `scheduler.py` | scheduler 入口 | Strava 同步是否跑 | scheduler |
| `worker.py` | worker 入口 | 队列监听 | worker |
| **`scripts/cleanup_zombies.py`** | 僵尸扫描 | processing 超时兜底 | cleanup |
| `migrations/versions/*.py` | **数据库结构** | 上生产前必须本地 PG 跑通 | 需 alembic upgrade |
| `Dockerfile` / `docker-compose.yml` | 镜像/容器配置 | 端口、volume、环境变量 | 全栈 |
| `requirements.txt` | Python 依赖 | 版本兼容 | docker-compose build |
| `.env` | 秘钥 | 不许进 git | api + worker + scheduler |
| `Caddyfile` | 反向代理 | TLS、路由 | caddy |
| `miniprogram/pages/home/*` | 动态 tab | 周统计、铃铛 | 小程序 |
| `miniprogram/pages/notification/*` | 通知中心页 | 红点点击 | 小程序 |
| `miniprogram/pages/leaderboard/*` | 赛段详情/排行 | segment_id 参数、定位 | 小程序 |
| `miniprogram/pages/detail/*` | 活动详情 | 地图、海拔、数据 | 小程序 |
| `miniprogram/pages/honor/*` | 荣誉页 | KOM + Top10 | 小程序 |
| `miniprogram/pages/settings/*` | 设置页 | 免打扰开关 | 小程序 |

---

## 9. 已知风险状态

### 9.1 已修复(🟢,但 agent 需知道这些陷阱存在)

| 风险 | 修复方式 | 修复版本 |
|---|---|---|
| Worker 重入 | UPDATE WHERE status='pending' 原子抢锁 | v0 |
| 僵尸 activity | cleanup 容器每 5min 扫描 | v0 |
| 重复上传 | file_hash SHA-256 + UNIQUE(user_id, file_hash) | v0 |
| 内存爆炸 | trackpoint 上限 50000 + 批量插入 | v0 |
| 连接池不足 | pool_size=8, max_overflow=12 | v0 |
| OAuth state CSRF/重放 | Redis nonce GETDEL 一次性消费 | v4 |
| Webhook 伪造 | subscription_id 校验 | v4 |
| scheduler 不跑 | 独立容器启动 | v4 |
| mark-all-read 非幂等 | 改为幂等 | v4 |
| datetime tz 不一致(strava_imports.updated_at) | 改 tz-aware | v4 |

### 9.2 待修(🟡 / 🔴,tech-debt)

| 风险 | 级别 | 状态 |
|---|---|---|
| datetime tz 不一致(activities/notifications 其他字段) | 🟡 P1 | tech-debt #1 |
| ensure_valid_token 行锁约束 | 🟡 P1 | tech-debt #2 |
| ensure_valid_token 未绑定用户路径 | 🟡 P1 | tech-debt #3 |
| SQLAlchemy legacy .get() | 🟢 低 | tech-debt #4 |
| scheduler Redis 连接每次新建 | 🟡 P1 | tech-debt #5 |
| N+1 查询(排名循环) | 🟡 | 代码 TODO |
| 孤儿文件清理 | 🟡 | 无机制 |
| 匹配断裂静默跳过 | 🟡 | 无回溯 |
| trackpoints 无 UNIQUE(activity_id, seq) | 🟡 | 缺 DB 约束 |
| status 无 CHECK 约束 | 🟡 | 应用层校验 |
| trackpoints 无分区策略 | 🟡 | 未来事 |
| 删 importing 中 activity 外键报错 | 🟡 | 未处理 |
| strava token 明文存储 | 🟡 | 未加密 |

⚠️ agent 注意: 新期开工前**必须扫 tech-debt.md**,新期 spec 不允许依赖还在 tech-debt 清单里的功能(CLAUDE.md 防黑盒化机制 3)。

---

## 10. 文档交叉引用

本文档是 velo 系统的**静态画像**。动态数据流见 `data-flow-guide.md`。

| 深入方向 | 参考文档 |
|---|---|
| 数据流链路、状态转换时序 | `docs/data-flow-guide.md`(占位,待建) |
| 技术决策背后的原因 | `docs/adr/*.md` |
| 跨模块契约精确规格 | `docs/contracts/*.md`(占位,待建) |
| 当前期任务清单 | `docs/spec-v{current}.md` |
| 产品方向、市场、用户 | `docs/prd/prd-v{current}.md`(占位,当前仅 TEMPLATE.md) |
| 模块内部画像 | `app/<模块>/README.md`(占位,待逐模块补) |
| 技术债务 | `docs/tech-debt.md` |
| 开发约束规则 | `/CLAUDE.md` |
| 变更历史 | `docs/changelog.md` |
| 竞品分析与产品警示 | `docs/competitive-analysis/*.md` |

⚠️ agent 注意: 标注"占位"的引用目前在仓库里不存在,是未来会建立的文档槽位。遇到这些死链不用自动创建,等本期 spec 明确要求时再补。

---

## 附录 A: 部署信息

| 项 | 值 |
|---|---|
| IP | 114.132.190.245 |
| 用户 | ubuntu |
| 代码路径 | ~/velo |
| Docker 命令前缀 | sudo |
| 数据库迁移 | `sudo docker compose exec api python3 -m alembic upgrade head` |
| 看日志 | `sudo docker compose logs <service> --tail 30` |

## 附录 B: 技术栈版本

| 层 | 值 |
|---|---|
| Python | 3.11+ |
| FastAPI | latest(同步模式) |
| SQLAlchemy | 2.0(同步 session) |
| PostgreSQL | 16 |
| PostGIS | 3.4 |
| Redis | 7-alpine |
| Caddy | 2-alpine |
| rq | latest |
| 微信小程序 | 原生 |
| FIT 解析 | garmin-fit-sdk |
| GPX 解析 | 自研 + gpxpy |
| 坐标转换 | xyconvert + numpy(GCJ-02 ↔ WGS-84) |

## 附录 C: 收尾体检(v4)

- 10 分钟能给陌生人讲清系统 ✅
- 画清典型用户操作全链路 ✅
- 文件 / 函数 30 秒可读 ⚠️ 2 处待清理(strava/service.py handle_callback, import_scheduler.py _run_tier1)

下期必答的收尾三问(CLAUDE.md 防黑盒化机制)。
