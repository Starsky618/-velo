# VELO 后端技术交接文档

> **用途**：本文档是项目现状的完整快照，可直接转发给任何 LLM（ChatGPT / Claude / Gemini）或新加入的开发者，让对方在零上下文的情况下完整理解项目"建到了哪、缺什么、怎么接着盖"。
>
> **生成时间**：2026-04-08
> **项目阶段**：后端 MVP 全部完工，前端未开始，尚未部署上线

---

## 目录

1. [系统总览](#1-系统总览)
2. [架构拓扑](#2-架构拓扑)
3. [模块分解与依赖关系](#3-模块分解与依赖关系)
4. [已完成任务清单](#4-已完成任务清单)
5. [数据模型](#5-数据模型)
6. [API 接口全表](#6-api-接口全表)
7. [关键算法与设计决策](#7-关键算法与设计决策)
8. [代码健康度报告](#8-代码健康度报告)
9. [缺失项与待办](#9-缺失项与待办)
10. [建议扩展路线图](#10-建议扩展路线图)
11. [开发隐患与注意事项](#11-开发隐患与注意事项)
12. [前端接入指南](#12-前端接入指南)
13. [新后端模块接入规范](#13-新后端模块接入规范)
14. [部署操作手册](#14-部署操作手册)

---

## 1. 系统总览

**VELO** 是一个公路骑行垂直平台，目标用户 ~100 人。

**MVP 核心链路**：
```
用户微信登录 → 上传 GPX 文件 → 后台异步解析（距离/速度/功率/轨迹）
→ 自动匹配赛段 → 生成排行榜 → 前端渲染骑行卡片 → 分享
```

**技术栈**（已锁定，不可变更）：
| 层 | 技术 | 为什么选它 |
|---|---|---|
| 后端框架 | FastAPI（**纯同步 `def`**，非 async） | <100 用户量级，同步模式让 API 和 Worker 共用一套 session 逻辑，复杂度减半 |
| ORM | SQLAlchemy 2.0 同步 session | 和 FastAPI 同步模式配合 |
| 数据库 | PostgreSQL 16 + PostGIS 3.4 | 空间查询（赛段匹配需要 ST_DWithin） |
| 任务队列 | Redis Queue (rq) | 比 Celery 轻量，MVP 够用 |
| 认证 | 微信 OAuth → 服务端 JWT（7天有效期） | 微信小程序生态的标准方案 |
| 前端 | 微信小程序 | 目标用户都在微信生态 |
| 反向代理 | Caddy 2 | 自动 HTTPS（微信强制要求），零配置 SSL |

---

## 2. 架构拓扑

```
                      ┌────────────────────────┐
                      │     微信小程序前端       │
                      │   （尚未开发）           │
                      └──────────┬─────────────┘
                                 │ HTTPS
                      ┌──────────▼─────────────┐
                      │     Caddy 反向代理      │  ← 自动申请 Let's Encrypt 证书
                      │     (端口 80/443)       │
                      └──────────┬─────────────┘
                                 │ HTTP :8000
                      ┌──────────▼─────────────┐
                      │   FastAPI API 服务      │  ← 同步模式，uvicorn 线程池并发
                      │   (app/main.py)         │
                      └──┬──────────────────┬───┘
                         │                  │
              ┌──────────▼──────┐  ┌────────▼────────┐
              │  PostgreSQL 16  │  │    Redis 7       │
              │  + PostGIS 3.4  │  │  (任务队列后端)   │
              └──────────▲──────┘  └────────▲────────┘
                         │                  │
                      ┌──┴──────────────────┴───┐
                      │   rq Worker 进程         │  ← 和 API 同一个 Docker 镜像
                      │   (worker.py)            │     不同启动命令
                      └─────────────────────────┘
```

**数据流控制回路**（控制论视角）：
```
输入 → 处理 → 输出 → 反馈
 │       │       │       │
GPX    Worker  Activity  赛段自动匹配
上传   异步解析  数据入库  ← 输出触发下一轮输入
                          （匹配结果写入 segment_efforts）
```

每次骑行解析完成后，系统自动执行赛段匹配——这是一个**前馈控制**：不需要用户手动触发，数据从 Activity 模块自动流向 Segment 模块。单个赛段匹配失败用 SAVEPOINT 隔离，不影响其他赛段——这是**故障隔离**策略。

---

## 3. 模块分解与依赖关系

### 依赖方向（铁律，不可违反）
```
User ← Activity ← Segment
 │        │          │
 │        │          ├── 可以 import Activity 的 models
 │        │          └── 可以 import User 的 models
 │        └── 可以 import User 的 models
 └── 不可以 import 任何右侧模块
```

**违反后果**：循环 import → 启动崩溃。User 模块查骑行统计时，直接用 SQL JOIN 读 activities 表数据，不 import Activity 的 service——"读数据"不违反依赖方向，"调逻辑"才违反。

### 模块职责一览

```
app/
├── main.py              # 入口：挂载所有路由，健康检查 /health
├── config.py            # 配置：从环境变量读取所有配置项
├── database.py          # 数据库：engine + SessionLocal + Base + get_db()
├── dependencies.py      # 认证：JWT 验证 → 返回 user_id
│
├── user/                # 用户模块（会员系统）
│   ├── models.py        #   User 表：openid, nickname, ftp, bike_type, is_admin...
│   ├── schemas.py       #   请求/响应格式定义
│   ├── router.py        #   路由：登录、资料、统计
│   └── service.py       #   业务逻辑：微信登录、JWT签发、统计聚合
│
├── activity/            # 活动模块（骑行记录）
│   ├── models.py        #   Activity 表 + Trackpoint 表
│   ├── schemas.py       #   请求/响应格式定义
│   ├── router.py        #   路由：上传、列表、详情、编辑、删除、状态轮询
│   ├── service.py       #   业务逻辑：CRUD、文件管理
│   ├── gpx_parser.py    #   纯函数：GPX → 统计数据 + 轨迹点
│   ├── power_zones.py   #   纯函数：功率区间计算（Z1-Z6）
│   ├── simplify.py      #   纯函数：Douglas-Peucker 轨迹简化
│   └── worker.py        #   rq 异步任务：解析 GPX + 触发赛段匹配
│
├── segment/             # 赛段模块（竞速排行榜）
│   ├── models.py        #   Segment 表 + SegmentEffort 表
│   ├── schemas.py       #   请求/响应格式定义
│   ├── router.py        #   路由：赛段CRUD、排行榜、用户成绩、活动途经赛段
│   ├── service.py       #   业务逻辑：赛段管理、排行榜查询（485 行，黄灯⚠）
│   ├── matcher.py       #   纯函数：GPS 精确匹配算法（4步：找起→找终→覆盖验证→计时）
│   └── auto_match.py    #   Worker 调用：PostGIS 粗筛 → 逐赛段精确匹配 → 写入成绩
│
└── storage/             # 文件存储抽象层
    ├── base.py          #   抽象基类 StorageBackend
    └── local.py         #   本地文件系统实现（生产够用）
```

### 测试覆盖
```
tests/
├── conftest.py          # SQLite 内存数据库 + 假 PostGIS 函数 + 公共 fixture
├── test_user.py         # 12 个测试用例
├── test_activity.py     # 28 个测试用例
├── test_segment.py      # 21 个测试用例
└── fixtures/            # 测试用 GPX 文件
```

**61 个测试全部通过，耗时 1.87 秒**（绿灯，远低于 10 秒黄线）。

---

## 4. 已完成任务清单

### 阶段一：基础设施 ✅
| 任务 | 说明 | 关键产出 |
|------|------|---------|
| 1.1 | 项目骨架 | FastAPI 入口 + requirements.txt + /health 端点 |
| 1.2 | 数据库连接 | engine + SessionLocal + get_db() 依赖注入 |
| 1.3 | 文件存储抽象层 | StorageBackend 基类 + LocalStorage 实现 |
| 1.4 | Redis + rq 配置 | worker.py 启动入口 + 队列连接 |

### 阶段二：User 模块 ✅
| 任务 | 说明 | 关键产出 |
|------|------|---------|
| 2.1 | User 数据模型 | users 表（openid, nickname, ftp, bike_type, is_admin...） |
| 2.2 | 微信登录接口 | POST /api/user/login（code → openid → JWT） |
| 2.3 | JWT 认证中间件 | get_current_user() 依赖函数 |
| 2.4 | 用户资料接口 | GET/PUT /api/user/profile |
| 2.5 | 骑行统计接口 | GET /api/user/stats?period=week/month/year/all |
| 2.6 | User 模块测试 | 12 个用例 |

### 阶段三：Activity 模块 ✅
| 任务 | 说明 | 关键产出 |
|------|------|---------|
| 3.1 | Activity 数据模型 | activities 表 + trackpoints 表 |
| 3.2 | GPX 解析器 | gpxpy 解析 + 统计量计算 + GPS 漂移过滤 |
| 3.3 | 功率区间计算 | Z1-Z6 区间，基于 FTP 百分比 |
| 3.4 | 轨迹简化 | Douglas-Peucker 迭代算法，10000→800 点 |
| 3.5 | GPX 上传接口 | POST /api/activities/upload（快速校验 + 入队列） |
| 3.6 | 异步解析 Worker | GPX 解析 + 统计写入 + 赛段匹配触发 |
| 3.7 | 活动查询接口 | 列表/详情/编辑/删除/状态轮询 |
| 3.8 | Activity 模块测试 | 28 个用例 |

### 阶段四：Segment 模块 ✅
| 任务 | 说明 | 关键产出 |
|------|------|---------|
| 4.1 | Segment 数据模型 | segments 表 + segment_efforts 表 |
| 4.2 | 路段管理接口 | 创建（管理员）/ 列表（附近搜索）/ 详情 |
| 4.3 | GPS 精确匹配算法 | 4 步纯函数：找起→找终→覆盖验证→计时 |
| 4.4 | 粗筛 + 自动匹配触发 | PostGIS ST_DWithin 粗筛 → 逐赛段精确匹配 |
| 4.5 | 排行榜查询接口 | 排行榜 + 用户成绩 |
| 4.6 | 活动途经赛段接口 | GET /api/activities/{id}/segments |
| 4.7 | Segment 模块测试 | 21 个用例 |

### 阶段六：部署文件 ✅
| 任务 | 说明 | 关键产出 |
|------|------|---------|
| 6 | Docker 部署方案 | Dockerfile + docker-compose.yml + Caddyfile + .dockerignore + .env.example |

---

## 5. 数据模型

### ER 关系图
```
┌──────────────┐       ┌──────────────────┐       ┌──────────────┐
│    users     │       │   activities     │       │   segments   │
├──────────────┤       ├──────────────────┤       ├──────────────┤
│ id        PK │◄──┐   │ id            PK │       │ id        PK │
│ openid    UQ │   └───│ user_id       FK │       │ name         │
│ nickname     │       │ title            │       │ distance     │
│ avatar_url   │       │ status           │       │ elevation    │
│ ftp          │       │ file_url         │       │ start/end    │
│ weight       │       │ distance         │       │ ref_line  GEO│
│ bike_type    │       │ duration         │   ┌──►│ tolerance    │
│ weekly_goal  │       │ elevation_gain   │   │   │ match_ratio  │
│ is_admin     │       │ avg_speed/power  │   │   └──────────────┘
│ created_at   │       │ simplified_track │   │
│ updated_at   │       │ splits     JSONB │   │
└──────────────┘       │ power_zones JSONB│   │
       ▲               │ created_at       │   │
       │               └────────┬─────────┘   │
       │                        │              │
       │               ┌───────▼──────────┐   │
       │               │  trackpoints     │   │
       │               ├──────────────────┤   │
       │               │ id            PK │   │
       │               │ activity_id   FK │   │
       │               │ seq              │   │
       │               │ lat/lon/ele      │   │
       │               │ timestamp        │   │
       │               │ hr/cadence/power │   │
       │               │ geom         GEO │   │
       │               └──────────────────┘   │
       │                                      │
       │       ┌──────────────────────┐       │
       │       │  segment_efforts     │       │
       │       ├──────────────────────┤       │
       └───────│ user_id          FK  │       │
               │ activity_id     FK ──┤──(CASCADE)
               │ segment_id      FK ──┘───────┘
               │ elapsed_time        │
               │ avg_speed/power     │
               │ start/end_index     │
               │ UQ(segment,activity)│
               └──────────────────────┘
```

### 关键约束
- `segment_efforts` 联合唯一 `(segment_id, activity_id)`：一次骑行在同一赛段只有一条成绩
- `activity_id` ON DELETE CASCADE：删活动 → 自动删 trackpoints + segment_efforts
- `reference_line` GIST 空间索引：加速附近赛段查询
- 距离单位：**数据库存米，API 返回公里**，转换在 service 层

---

## 6. API 接口全表

### 认证规则
- 所有接口（除 `/health` 和 `/api/user/login`）需要 JWT
- 请求头：`Authorization: Bearer <jwt_token>`
- JWT 有效期 7 天，前端收到 401 自动 `wx.login()` 静默续期
- 错误统一格式：`{"detail": "错误描述"}`
- 分页参数：`page`（默认1）+ `page_size`（默认20）

### User 模块
| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/user/login` | 否 | 微信登录，body: `{"code": "wx_code"}` → 返回 JWT + 用户信息 |
| GET | `/api/user/profile` | 是 | 获取当前用户资料 |
| PUT | `/api/user/profile` | 是 | 修改资料（nickname/avatar_url/ftp/weight/bike_type/weekly_goal） |
| GET | `/api/user/stats?period=week` | 是 | 骑行统计（period: week/month/year/all），返回 ride_count/distance/duration/elevation_gain |

### Activity 模块
| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/activities/upload` | 是 | 上传 GPX，multipart/form-data 字段名 `file`，≤50MB |
| GET | `/api/activities` | 是 | 活动列表（分页），只返回自己的 |
| GET | `/api/activities/{id}` | 是 | 活动详情（含 simplified_track/splits/power_zones），仅本人 |
| PATCH | `/api/activities/{id}` | 是 | 编辑标题（1-128 字符），仅本人 |
| DELETE | `/api/activities/{id}` | 是 | 删除活动（级联删 trackpoints + efforts + 文件），仅本人 |
| GET | `/api/activities/{id}/status` | 是 | 轮询解析状态（pending/processing/completed/failed） |

### Segment 模块
| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/segments` | 是+管理员 | 创建赛段，body: name/description/reference_points |
| GET | `/api/segments` | 是 | 赛段列表，可选 near_lat/near_lon/radius 附近搜索 |
| GET | `/api/segments/{id}` | 是 | 赛段详情 + TOP20 排行榜 |
| GET | `/api/segments/{id}/leaderboard` | 是 | 完整排行榜（分页），可选 bike_type 过滤 |
| GET | `/api/user/efforts` | 是 | 当前用户所有赛段成绩（含 rank） |
| GET | `/api/activities/{id}/segments` | 是 | 活动途经赛段（含 rank + is_pr），仅本人 |

### 系统
| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/health` | 否 | 健康检查，返回 `{"status": "ok"}` |

---

## 7. 关键算法与设计决策

### 7.1 GPS 赛段匹配算法（matcher.py，238 行）

**4 步流程**：
```
步骤 1：找起点 → 遍历轨迹点，第一个距赛段起点 < tolerance 的点（"多次经过取第一次"）
步骤 2：找终点 → 从起点之后，找距赛段终点最近且 < tolerance 的点
步骤 3：覆盖验证 → 起点到终点之间的轨迹点，计算每个点到参考折线的距离，
                   在 tolerance 内的比例 ≥ min_match_ratio 才算通过
步骤 4：计算用时 → end.timestamp - start.timestamp（秒）
```

**关键设计决策**：
- 起点用"第一个在范围内的"（spec 规定：多次经过取第一次），终点用"最近的"（更精确）
- 距离计算用 Haversine 公式（地球表面球面距离，R=6371000m）
- 点到折线距离用投影法（把点投影到折线的每段线段上，取最短距离）
- `cos_lat` 保护：`max(math.cos(mid_lat), 1e-10)` 防止极端纬度除零

### 7.2 粗筛 + 自动匹配（auto_match.py，206 行）

```
GPX 解析完成（Worker）
  → PostGIS 粗筛：ST_DWithin(reference_line::geography, 轨迹凸包::geography, 100m)
  → 对每个通过粗筛的赛段：
      → 加载轨迹点，字段映射（latitude→lat, longitude→lon, timestamp→time）
      → 调用 matcher.match_segment()
      → 匹配成功 → 检查是否已有成绩（防重复）→ 创建 SegmentEffort
      → 每个赛段用 SAVEPOINT 隔离，单个失败不影响其他
```

**SAVEPOINT 隔离（关键）**：用 `db.begin_nested()` 创建保存点，单赛段匹配异常时 `savepoint.rollback()` 只回滚当前赛段，已成功的 efforts 不受影响。

### 7.3 Douglas-Peucker 轨迹简化（simplify.py）

将 10000+ 个 GPS 点压缩到 ~800 个点，保留轨迹形状特征。用于前端地图渲染和骑行卡片绘制，单次 API 响应 <100KB。使用迭代（非递归）实现，避免深层递归栈溢出。

### 7.4 GPX 解析器（gpx_parser.py）

- 使用 gpxpy 库解析 XML
- GPS 漂移过滤：>120km/h 的段不累加距离
- BOM 头处理：`file_bytes[:256].lstrip(b'\xef\xbb\xbf')` 跳过 UTF-8 BOM
- 分段统计（splits）：每 10km 一段，计算段内平均速度/功率/心率/爬升

### 7.5 单位与时区约定

| 规则 | 说明 |
|------|------|
| 距离 | 数据库存**米**，API 返回**公里**（保留 1 位小数），转换在 service 层 |
| 时间 | 数据库存 **UTC**，"本周/本月"按**北京时间 UTC+8** 计算边界 |
| PostGIS | ST_DWithin 必须转 `::geography` 才能用**米**做单位，否则是**度** |
| 速度 | 数据库和 API 都用 **km/h** |

---

## 8. 代码健康度报告

### 文件行数（2026-04-08）
| 文件 | 行数 | 状态 |
|------|------|------|
| `segment/service.py` | 485 | ⚠ **黄灯**（阈值 500 红灯） |
| `tests/test_activity.py` | 480 | ⚠ **黄灯**（测试文件，优先级低） |
| `tests/test_segment.py` | 464 | ⚠ **黄灯**（测试文件，优先级低） |
| `tests/conftest.py` | 318 | ⚠ **黄灯**（测试基础设施） |
| `user/service.py` | 266 | 绿灯 |
| `segment/matcher.py` | 238 | 绿灯 |
| `segment/auto_match.py` | 206 | 绿灯 |
| `activity/worker.py` | 175 | 绿灯 |
| 其余所有文件 | <200 | 绿灯 |

**总代码量**：4086 行（app/）+ 1499 行（tests/）= 5585 行

### 测试健康度
| 指标 | 当前值 | 阈值 |
|------|--------|------|
| 测试总数 | 61 | - |
| 测试耗时 | 1.87s | <10s 绿灯 |
| 通过率 | 100% | - |

### 需要关注
- `segment/service.py`（485 行）距红灯 500 行只差 15 行。如果后续需要在此文件加函数，**必须先拆分**。可能的拆分策略：将 `get_leaderboard` + `get_user_efforts` + `get_activity_segments` 提取到 `segment/query.py`。

---

## 9. 缺失项与待办

### 9.1 必须完成（上线前）

| 缺项 | 说明 | 紧急度 | 预计工作量 |
|------|------|--------|-----------|
| **Alembic 迁移** | 数据库表结构的版本管理。目前表定义在代码里，但没生成迁移脚本。部署到 PostgreSQL 前必须执行 `alembic revision --autogenerate` + `alembic upgrade head` | 🔴 关键 | 0.5h |
| **微信小程序前端** | 整个前端：首页、上传、详情、排行榜、探索、个人中心 | 🔴 关键 | 主要工作量 |
| **骑行卡片 canvas** | 750×1334px 的分享卡片组件（spec 5.1-5.3） | 🔴 关键 | 前端任务 |
| **实际部署** | 买服务器 + 配域名 + docker-compose up + 初始化数据库 | 🔴 关键 | 1-2h |

### 9.2 可以后做（MVP 后）

| 缺项 | 说明 | 优先级 |
|------|------|--------|
| 腾讯云 COS 文件存储 | `app/storage/cos.py` 目前是空壳预留。100 用户本地存储够用 | 低 |
| 动态流（feed） | 社交功能，v1 spec 明确标注"不实现" | v2 |
| 探索路线 | 发现附近骑行路线，v1 spec 标注"不实现" | v2 |
| 点赞/评论/关注 | 社交互动功能，v1 不做 | v2 |

### 9.3 已知技术债

| 债务 | 说明 | 影响 |
|------|------|------|
| N+1 查询 | 排行榜的 rank 和 is_pr 目前每条成绩单独子查询。<100 用户不是问题，超过 1000 条 efforts 时需要优化成窗口函数 | 低（当前用户量） |
| bike_type 过滤语义 | 排行榜按 bike_type 过滤查的是用户**当前**车型，不是骑行时的车型。用户换车后历史成绩车型会变 | MVP 可接受 |
| 测试用 SQLite 代替 PostgreSQL | 用假 PostGIS 函数注册到 SQLite。真正的空间查询（ST_DWithin、粗筛逻辑）没有被测试覆盖 | 部署后需手动验证空间查询 |

---

## 10. 建议扩展路线图

按控制论"增量反馈"原则，每个阶段都有可验证的交付物：

### Phase 1：上线（当前 → 可用）
```
1. 生成 Alembic 迁移文件
2. 部署到云服务器（腾讯云 2C4G）
3. 手动创建 2-3 个测试赛段
4. 开发微信小程序 MVP（只做核心链路：登录→上传→查看→排行榜）
5. 内部 10 人测试
```

### Phase 2：完善（可用 → 好用）
```
6. 骑行卡片 canvas 组件 + 分享功能
7. 用户资料完善（头像上传等）
8. 骑行详情页优化（地图渲染、分段图表）
9. 排行榜筛选优化（时间范围、车型）
10. 腾讯云 COS 文件存储
```

### Phase 3：社交（好用 → 有粘性）
```
11. 动态流（feed）——看朋友的骑行
12. 点赞/评论系统
13. 关注系统
14. 骑行路线探索（基于已有轨迹聚合热门路线）
15. 骑行挑战/赛事系统
```

### Phase 4：增长（有粘性 → 有规模）
```
16. 数据分析仪表盘（训练趋势、FTP 变化曲线）
17. Strava / 行者数据导入
18. 骑行俱乐部功能
19. 推送通知（被超越提醒、好友骑行提醒）
20. 支付/会员系统
```

### 每个 Phase 新增后端模块时的依赖方向
```
User ← Activity ← Segment ← Feed ← Social
                              ↑
                           Challenge
```
新模块只能依赖左侧模块，不能反向。

---

## 11. 开发隐患与注意事项

### 🔴 高危（不处理会出生产事故）

**1. PostGIS 空间查询必须转 geography**
```python
# ❌ 错误：ST_DWithin 的单位是"度"（1度≈111km），50000 度 = 全地球
ST_DWithin(reference_line, point, 50000)

# ✅ 正确：转 geography 后单位是"米"
ST_DWithin(cast(reference_line, Geography), cast(point, Geography), 50000)
```

**2. GPX BOM 头**
部分骑行软件导出的 GPX 文件开头有 UTF-8 BOM（`\xEF\xBB\xBF`），如果不跳过，XML 解析会失败。当前代码已处理，但新增任何 GPX/XML 解析逻辑时必须注意。

**3. is_admin server_default 在 SQLite 中的行为**
`server_default="false"` 在 SQLite 中存为字符串 `"false"`，布尔判断为 `True`。测试中必须**显式设置** `is_admin=False`，不能依赖 server_default。PostgreSQL 无此问题。

**4. 同步模式锁定**
整个项目使用 `def`（同步），**不能改为 `async def`**。一旦混用，SQLAlchemy 同步 session 会在异步事件循环中阻塞，导致性能骤降甚至死锁。如果未来需要 async，必须整体迁移（包括 session、ORM 查询、所有依赖注入）。

### ⚠ 中危（不处理会影响功能正确性）

**5. WKT 坐标顺序是 (longitude, latitude)**
PostGIS 的 WKT 格式 `LINESTRING(lon1 lat1, lon2 lat2, ...)`，经度在前、纬度在后。与通常的 (lat, lon) 习惯**相反**。auto_match.py 中的 `_parse_linestring_wkt()` 已做了 lon/lat → lat/lon 转换。

**6. match_tolerance / min_match_ratio 的 server_default**
这两个字段有 `server_default`，但在 ORM 插入时 Python 侧拿到的是 `None`（server_default 是数据库层的，ORM flush 前 Python 不知道）。当前代码已做显式赋值兜底：
```python
segment.match_tolerance = match_tolerance if match_tolerance is not None else 50.0
```

**7. 删除活动的级联行为**
删除 Activity 时，ON DELETE CASCADE 会自动删除：
- 所有 Trackpoints
- 所有 SegmentEfforts

确保前端在删除前有二次确认。Service 层还会额外删除文件系统中的 GPX 文件。

**8. 赛段匹配的 SAVEPOINT 隔离**
`auto_match.py` 中每个赛段的匹配用 `db.begin_nested()`（SAVEPOINT）隔离。如果改为 `db.rollback()`，**会清空所有已匹配的 efforts**——这是之前踩过的坑。

### 💡 低危（知道就好）

**9. 排行榜 rank 是实时计算的**
每次查询排行榜时，rank 通过子查询 `COUNT(*) + 1` 实时计算，不是预存字段。用户量小时没问题；超过 10000 条 efforts 后考虑物化视图或定时计算。

**10. simplified_track 存在 JSONB 字段**
轨迹简化后的坐标存为 JSON 数组。查询活动列表时**不返回此字段**（太大），只在详情接口返回。如果将来需要在列表页显示缩略轨迹，需要额外加一个更小的 preview_track 字段。

**11. Worker 和 API 共享同一个 Docker 镜像**
优点：维护一份代码。风险：Worker 重启时正在执行的 GPX 解析任务会中断，活动状态卡在 `processing`。需要定期扫描并重置超时的 processing 状态活动（当前未实现）。

**12. Alembic 迁移尚未生成**
`alembic/` 目录和迁移文件尚未创建。首次部署时需要：
```bash
alembic init migrations
# 修改 alembic.ini 和 env.py 指向正确的数据库 URL 和 Base.metadata
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

---

## 12. 前端接入指南

### 认证流程
```javascript
// 1. 微信登录 → 获取 code
const { code } = await wx.login();

// 2. 换取 JWT
const res = await wx.request({
  url: 'https://api.velo.cn/api/user/login',
  method: 'POST',
  data: { code }
});
const token = res.data.token;
wx.setStorageSync('token', token);

// 3. 后续请求带 token
wx.request({
  url: 'https://api.velo.cn/api/activities',
  header: { 'Authorization': `Bearer ${token}` }
});

// 4. 收到 401 → 静默续期
// 在请求拦截器中：if (statusCode === 401) → 重新 wx.login() → 重新请求
```

### 核心数据获取
```javascript
// 活动详情（2 个并行请求）
const [detail, segments] = await Promise.all([
  api.get(`/api/activities/${id}`),           // 轨迹 + 统计 + 功率区间
  api.get(`/api/activities/${id}/segments`),   // 途经赛段 + 排名
]);

// 用户首页（2 个并行请求）
const [profile, stats] = await Promise.all([
  api.get('/api/user/profile'),                // 基本资料
  api.get('/api/user/stats?period=week'),       // 本周骑行统计
]);
```

### 前端路径对照表
| 功能 | 后端路径 | 方法 |
|------|---------|------|
| 微信登录 | `/api/user/login` | POST |
| 获取/修改资料 | `/api/user/profile` | GET / PUT |
| 骑行统计 | `/api/user/stats?period=week` | GET |
| 用户赛段成绩 | `/api/user/efforts` | GET |
| 上传 GPX | `/api/activities/upload` | POST (multipart) |
| 活动列表 | `/api/activities?page=1&page_size=20` | GET |
| 活动详情 | `/api/activities/{id}` | GET |
| 编辑活动 | `/api/activities/{id}` | PATCH |
| 删除活动 | `/api/activities/{id}` | DELETE |
| 轮询状态 | `/api/activities/{id}/status` | GET |
| 途经赛段 | `/api/activities/{id}/segments` | GET |
| 赛段列表 | `/api/segments?near_lat=&near_lon=&radius=` | GET |
| 赛段详情 | `/api/segments/{id}` | GET |
| 排行榜 | `/api/segments/{id}/leaderboard?page=&bike_type=` | GET |

### v1 不实现的接口（前端保留 mock）
- 动态流 `/api/activity/feed`
- 探索路线 `/api/explore/routes`
- 点赞/评论/关注 `/api/social/*`
- 骑行卡片（改为前端 canvas 生成，不走后端）

---

## 13. 新后端模块接入规范

### 创建新模块的 4 步流程

**Step 1：建目录结构**
```
app/
  your_module/
    __init__.py    # 模块说明（必须有"这是干什么的"+"注意事项"）
    models.py      # 数据表（继承 Base）
    schemas.py     # 请求/响应（Pydantic BaseModel）
    router.py      # API 路由（APIRouter）
    service.py     # 业务逻辑
```

**Step 2：注册路由**
```python
# app/main.py
from app.your_module.router import router as your_router
app.include_router(your_router)
```

**Step 3：复用认证**
```python
from app.dependencies import get_current_user
from app.database import get_db

@router.get("/api/your-resource")
def your_endpoint(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ...
```

**Step 4：生成迁移**
```bash
alembic revision --autogenerate -m "add your_table"
alembic upgrade head
```

### 硬性规则
| 规则 | 原因 |
|------|------|
| 用 `def`，不用 `async def` | 整个项目同步模式，混用会死锁 |
| 依赖方向只向左 | 新模块可 import user/activity/segment，反过来不行 |
| 距离存米，返回公里 | 全局约定，不一致会出 bug |
| 时间存 UTC | 全局约定 |
| 路径用 RESTful 复数 | `/api/comments` 不是 `/api/comment` |
| 分页用 page + page_size | 不用 limit/offset |
| 文件 >300 行黄灯，>500 行必拆 | 代码健康度标准 |
| 函数 >50 行黄灯，>80 行必拆 | 代码健康度标准 |

### 复用异步任务
```python
# 在任意 service 或 router 中入队
from redis import Redis
from rq import Queue
from app.config import settings

q = Queue(connection=Redis.from_url(settings.REDIS_URL))
job = q.enqueue(your_task_function, arg1, arg2)

# 在 worker.py 中，rq Worker 会自动发现并执行队列中的任务
```

---

## 14. 部署操作手册

### 前置条件
- 域名（如 `api.velo.cn`），A 记录指向服务器 IP
- 服务器开放 80（HTTP）和 443（HTTPS）端口
- 安装 Docker + Docker Compose

### 部署步骤
```bash
# 1. 上传代码到服务器
scp -r velo/ user@server:/opt/velo

# 2. 配置环境变量
cd /opt/velo
cp .env.example .env
# 编辑 .env，填入：
#   DB_PASSWORD=<随机强密码>
#   JWT_SECRET=<python -c "import secrets; print(secrets.token_hex(32))" 生成>
#   WX_APPID=<微信公众平台获取>
#   WX_SECRET=<微信公众平台获取>

# 3. 修改域名
# 编辑 Caddyfile，将 api.velo.cn 替换为你的实际域名

# 4. 启动
docker-compose up -d

# 5. 初始化数据库（首次部署）
docker-compose exec api alembic upgrade head

# 6. 验证
curl https://你的域名/health
# 应返回 {"status": "ok"}

# 7. 配置微信小程序
# 微信公众平台 → 开发管理 → 服务器域名 → 添加 https://你的域名
```

### 运维命令
```bash
# 查看日志
docker-compose logs -f api
docker-compose logs -f worker

# 重启服务
docker-compose restart api worker

# 更新代码后重新部署
docker-compose build api
docker-compose up -d api worker

# 数据库迁移（更新模型后）
docker-compose exec api alembic revision --autogenerate -m "描述"
docker-compose exec api alembic upgrade head

# 手动设置管理员
docker-compose exec db psql -U velo -d velo \
  -c "UPDATE users SET is_admin = true WHERE id = 1;"
```

### Docker 服务拓扑
```
┌─────────────────────────────────────────────────┐
│                 docker-compose                   │
│                                                  │
│  ┌──────┐  ┌───────┐  ┌─────┐  ┌────────┐  ┌──────┐  │
│  │  db  │  │ redis │  │ api │  │ worker │  │ caddy│  │
│  │:5432 │  │:6379  │  │:8000│  │        │  │:80   │  │
│  │本机  │  │本机   │  │内部 │  │        │  │:443  │  │
│  └──────┘  └───────┘  └─────┘  └────────┘  └──────┘  │
│   ↑ 只监听 127.0.0.1     ↑ 只对 caddy 可见     ↑ 对外  │
│   │ 不暴露公网            │ expose 8000         │ 公网  │
└─────────────────────────────────────────────────┘
```

---

## 附：文件清单与行数

| 路径 | 行数 | 职责 |
|------|------|------|
| `app/main.py` | 46 | 应用入口，路由挂载 |
| `app/config.py` | 46 | 配置管理 |
| `app/database.py` | 52 | 数据库连接 |
| `app/dependencies.py` | 51 | JWT 认证 |
| `app/user/models.py` | 67 | User 表 |
| `app/user/schemas.py` | 111 | User 请求/响应 |
| `app/user/router.py` | 111 | User 路由 |
| `app/user/service.py` | 266 | User 业务逻辑 |
| `app/activity/models.py` | 164 | Activity + Trackpoint 表 |
| `app/activity/schemas.py` | - | Activity 请求/响应 |
| `app/activity/router.py` | - | Activity 路由 |
| `app/activity/service.py` | 204 | Activity 业务逻辑 |
| `app/activity/gpx_parser.py` | - | GPX 解析 |
| `app/activity/power_zones.py` | - | 功率区间 |
| `app/activity/simplify.py` | - | 轨迹简化 |
| `app/activity/worker.py` | 175 | 异步任务 |
| `app/segment/models.py` | 119 | Segment + SegmentEffort 表 |
| `app/segment/schemas.py` | 183 | Segment 请求/响应 |
| `app/segment/router.py` | 205 | Segment 路由 |
| `app/segment/service.py` | 485 | Segment 业务逻辑 ⚠ |
| `app/segment/matcher.py` | 238 | 匹配算法 |
| `app/segment/auto_match.py` | 206 | 自动匹配 |
| `app/storage/base.py` | 50 | 存储抽象 |
| `app/storage/local.py` | 94 | 本地存储 |
| `worker.py` | 31 | Worker 启动入口 |
| `tests/conftest.py` | 318 | 测试基础设施 |
| `tests/test_user.py` | 206 | 用户测试 |
| `tests/test_activity.py` | 480 | 活动测试 |
| `tests/test_segment.py` | 464 | 赛段测试 |
| **app/ 合计** | **4086** | |
| **tests/ 合计** | **1499** | |
| **项目总计** | **~5600** | |
