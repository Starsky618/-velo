# RIDEMAP v1 技术规格文档（终版）

> 本文档为 Claude Code 开发参考。每个子任务是一个独立可实现、可测试的工作单元。
> 前端开发参考附录 A（API 对照表）对齐接口路径。
>
> 终版修订说明（基于 v3，由 Claude 审查后修正）：
> - **[严重修复]** PostGIS 空间查询 `ST_DWithin` 必须转 `::geography` 才能用米为单位
> - **[严重修复]** 部署方案新增 Caddy 反向代理，提供 HTTPS（微信小程序强制要求）
> - **[修复]** 所有 API 响应中的距离统一返回公里（km），不再混用米和公里
> - **[修复]** 时区约定：数据库存 UTC，涉及"本周/本月"计算按北京时间 UTC+8
> - **[修复]** GPX 上传校验增加 BOM 头跳过处理
> - **[新增]** `PATCH /api/activities/{id}` 编辑活动标题接口
> - **[新增]** users 表增加 `is_admin` 字段，创建路段需管理员权限
> - **[新增]** JWT 过期静默续期机制说明
> - **[修复]** 分页参数统一为 `page_size`（非 `limit`）

---

## 0. 全局约束

### 技术栈
- **后端框架**: FastAPI（同步模式，不使用 async def）
- **数据库**: PostgreSQL 16 + PostGIS 扩展
- **ORM**: SQLAlchemy 2.0（同步 session）
- **异步任务队列**: Redis Queue (rq)
- **文件存储**: 本地文件系统（开发）/ 腾讯云 COS（生产），通过抽象层切换
- **前端**: 微信小程序（本文档定义 API 接口 + 骑行卡片 canvas 规格）
- **认证**: 微信 OAuth 2.0 → 服务端 JWT

> **为什么全同步？** FastAPI 支持同步路由函数（def 而非 async def），此时由线程池处理并发。v1 用户量（<100 活跃）远不需要 async 的性能优势，而全同步意味着 rq Worker 和 API 共用同一套 SQLAlchemy session 逻辑，代码复杂度减半。

### 项目结构
```
ridemap/
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置管理（环境变量）
│   ├── database.py             # 数据库连接与同步 session
│   ├── dependencies.py         # 公共依赖（认证、数据库 session）
│   │
│   ├── user/
│   │   ├── models.py           # SQLAlchemy 模型
│   │   ├── schemas.py          # Pydantic 请求/响应模型
│   │   ├── router.py           # API 路由
│   │   └── service.py          # 业务逻辑（含统计聚合）
│   │
│   ├── activity/
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── gpx_parser.py       # GPX 解析（纯函数）
│   │   ├── simplify.py         # Douglas-Peucker 轨迹简化（纯函数）
│   │   └── worker.py           # rq 异步任务
│   │
│   ├── segment/
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── router.py           # 含 /api/activities/{id}/segments 路由
│   │   ├── service.py          # 含粗筛逻辑（数据库空间查询）
│   │   └── matcher.py          # 精确匹配算法（纯函数，不碰数据库）
│   │
│   └── storage/
│       ├── base.py             # 抽象接口
│       ├── local.py            # 本地文件系统实现
│       └── cos.py              # 腾讯云 COS 实现（预留）
│
├── miniprogram/                # 微信小程序前端
│   ├── pages/
│   │   ├── home/               # 首页（动态流 + 周数据）
│   │   ├── upload/             # 上传 GPX
│   │   ├── detail/             # 活动详情
│   │   ├── leaderboard/        # 排行榜
│   │   ├── explore/            # 探索路线
│   │   └── profile/            # 我的
│   ├── components/
│   │   └── share-card/         # 骑行卡片 canvas 组件
│   └── utils/
│       └── api.js              # API 调用层（路径以附录 A 为准）
│
├── migrations/                 # Alembic 数据库迁移
├── tests/
│   └── fixtures/               # 测试用 GPX 文件
├── worker.py                   # rq worker 启动入口
├── docker-compose.yml          # 最小部署配置
├── Dockerfile
├── requirements.txt
└── .env
```

### 模块依赖方向（单向，不可违反）
```
User ← Activity ← Segment
```
- Activity 可以 import user 的模型/service，反过来不行
- Segment 可以 import activity 的模型/service，反过来不行
- User 模块查统计数据时，直接从 activities 表聚合（SQL JOIN），不 import activity 的 service。这是"读数据"而非"调逻辑"，不违反依赖方向
- 途经赛段接口 `GET /api/activities/{id}/segments` 的路由注册在 segment 模块的 router 中（Segment 依赖 Activity，方向正确）

### API 通用约定
- 所有接口返回 JSON
- 认证：请求头 `Authorization: Bearer <jwt_token>`
- 错误格式：`{"detail": "错误描述"}`
- 分页：`?page=1&page_size=20`（参数名统一为 `page_size`，不用 `limit`），响应包含 `total` 字段
- RESTful 命名：资源用复数名词（`/activities` 不是 `/activity`），动作用 HTTP 方法
- **距离单位**：所有 API 响应中的距离字段统一返回**公里（km）**，保留 1 位小数。数据库内部存储仍为米，转换在 service 层完成
- **时区约定**：数据库所有 TIMESTAMP 字段存储 UTC 时间。涉及"本周/本月/今年"等周期计算时，按北京时间（UTC+8）确定边界。API 响应中的时间字段返回 ISO 8601 格式带时区标记（如 `2026-04-07T06:42:00+08:00`）

### JWT 过期与静默续期
- JWT 有效期 7 天
- 前端收到任何接口的 `401` 响应时，自动调用 `wx.login()` 静默获取新 code，再调 `POST /api/user/login` 换新 token，用户无感知
- 前端不需要 refresh token 机制，微信小程序的 `wx.login()` 本身就是静默授权

### GPX 文件校验策略
上传接口做两级校验：
1. **快速校验**（同步，上传接口内）：后缀 .gpx + 大小 ≤ 50MB + 前 256 字节内容检查（见下）
2. **深度校验**（异步，Worker 内）：gpxpy 解析时自然报错，捕获为 GPXParseError

> **BOM 处理**：部分软件导出的 GPX 文件开头有 UTF-8 BOM（`\xEF\xBB\xBF`）。快速校验时先跳过 BOM 再检查是否以 `<?xml` 或 `<gpx` 开头。代码示例：`header = file_bytes[:256].lstrip(b'\xef\xbb\xbf')`

---

## 1. 基础设施任务（先于所有模块）

### 任务 1.1：项目骨架初始化
**做什么**：创建项目结构、安装依赖、配置 FastAPI 应用入口。
**输入**：无
**输出**：可启动的空 FastAPI 应用，`GET /health` 返回 `{"status": "ok"}`
**依赖**：无

```
requirements.txt 核心依赖:
- fastapi
- uvicorn
- sqlalchemy
- psycopg2-binary
- alembic
- pydantic-settings
- python-jose
- httpx
- rq
- redis
- gpxpy
- geoalchemy2
```

### 任务 1.2：数据库连接与 session 管理
**做什么**：配置 SQLAlchemy **同步** engine 和 session factory，写 FastAPI 依赖注入函数 `get_db()`。

```python
# database.py — 全同步，rq Worker 和 API 共用
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**输入**：`.env` 中的 `DATABASE_URL`（格式：`postgresql://user:pass@host:5432/ridemap`）
**输出**：其他模块通过 `Depends(get_db)` 获取 session；Worker 直接 `SessionLocal()`
**依赖**：任务 1.1

### 任务 1.3：文件存储抽象层
**做什么**：定义 `StorageBackend` 抽象基类，实现 `LocalStorage`。

```python
# storage/base.py
from abc import ABC, abstractmethod

class StorageBackend(ABC):
    @abstractmethod
    def upload(self, file_bytes: bytes, filename: str) -> str: ...
    @abstractmethod
    def download(self, file_id: str) -> bytes: ...
    @abstractmethod
    def delete(self, file_id: str) -> bool: ...
```

`LocalStorage` 实现：文件存到 `./uploads/{年月}/{uuid}.gpx`，返回相对路径。
**依赖**：任务 1.1

### 任务 1.4：Redis 连接与 rq worker 配置
**做什么**：配置 Redis 连接，创建 rq 队列，写 worker 启动脚本。

```python
# worker.py
from redis import Redis
from rq import Worker, Queue

redis_conn = Redis.from_url(settings.REDIS_URL)
queue = Queue("ridemap", connection=redis_conn)

if __name__ == "__main__":
    Worker([queue], connection=redis_conn).work()
```

**输入**：`.env` 中的 `REDIS_URL`
**输出**：`python worker.py` 可启动后台 worker
**依赖**：任务 1.1

---

## 2. User 模块

### 模块契约
| 项目 | 说明 |
|------|------|
| **职责** | 管理用户身份、骑行属性、骑行统计聚合 |
| **输入** | 微信授权 code |
| **输出** | 用户 ID、JWT token、用户资料、骑行统计 |
| **承诺** | 给一个合法微信 code，一定返回唯一用户。新用户自动创建 |
| **不管** | 用户的具体活动内容、成绩、排名 |

### 数据模型
```sql
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    openid          VARCHAR(64) UNIQUE NOT NULL,
    nickname        VARCHAR(64),
    avatar_url      TEXT,
    ftp             INTEGER,                        -- 功能阈值功率 (W)，可为 NULL
    weight          FLOAT,                          -- 体重 (kg)
    bike_type       VARCHAR(20),                    -- road / gravel / mtb
    weekly_goal     FLOAT DEFAULT 200.0,            -- 周目标公里数
    is_admin        BOOLEAN DEFAULT FALSE,          -- 管理员标记，v1 手动在数据库设置
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
```

> 新增 `weekly_goal` 字段，前端首页需要显示周目标进度。

### 任务 2.1：User 数据模型 + 迁移
**做什么**：创建 SQLAlchemy User 模型，生成 Alembic 迁移。
**依赖**：任务 1.2

### 任务 2.2：微信登录接口
**路径**：`POST /api/user/login`
**输入**：`{"code": "微信授权code"}`
**处理流程**：
1. 用 code 调微信 `jscode2session` 接口，换取 openid + session_key
2. 用 openid 查数据库：存在则取出，不存在则创建
3. 签发 JWT（有效期 7 天）
4. 返回 `{"token": "xxx", "user_id": 1, "is_new_user": true/false}`
**错误处理**：
- 微信接口错误 → `401 "微信授权失败"`
- code 过期 → `401 "code已过期，请重新授权"`

```
微信 jscode2session 接口：
GET https://api.weixin.qq.com/sns/jscode2session
参数：appid, secret, js_code, grant_type=authorization_code
响应：{"openid": "xxx", "session_key": "xxx"}
```
**依赖**：任务 2.1

### 任务 2.3：JWT 认证中间件
**做什么**：实现 `get_current_user()` 依赖函数。
**输入**：`Authorization: Bearer <token>`
**输出**：当前 user_id（int）
**错误处理**：
- 无 token → `401 "未登录"`
- token 过期 → `401 "登录已过期"`
- token 非法 → `401 "无效凭证"`
**依赖**：任务 2.2

### 任务 2.4：用户资料接口
**接口 1**：`GET /api/user/profile`
**响应**：
```json
{
    "id": 1,
    "nickname": "Tim",
    "avatar_url": "https://...",
    "ftp": 235,
    "weight": 72.0,
    "bike_type": "road",
    "weekly_goal": 200.0,
    "created_at": "2026-04-01T00:00:00"
}
```

**接口 2**：`PUT /api/user/profile`
**可更新字段**：nickname, avatar_url, ftp, weight, bike_type, weekly_goal
**校验规则**：
- ftp: 50-500 整数，或 null（清除）
- weight: 30.0-200.0
- bike_type: road / gravel / mtb
- weekly_goal: 10.0-2000.0
**依赖**：任务 2.3

### 任务 2.5：骑行统计接口
**路径**：`GET /api/user/stats?period=week`
**参数**：
- `period`：`week`（本周，默认）/ `month`（本月）/ `year`（今年）/ `all`（全部）
**响应**：
```json
{
    "period": "week",
    "distance": 142.6,
    "rides": 4,
    "elevation_gain": 1820.0,
    "duration": 18432,
    "weekly_goal": 200.0,
    "goal_percent": 71
}
```
**实现**：直接对 activities 表做聚合查询（不 import activity service）：
```sql
SELECT
    COALESCE(SUM(distance), 0) / 1000.0 as distance_km,
    COUNT(*) as rides,
    COALESCE(SUM(elevation_gain), 0) as elevation_gain,
    COALESCE(SUM(duration), 0) as duration
FROM activities
WHERE user_id = :user_id
  AND status = 'completed'
  AND started_at >= :period_start
```
**时间范围计算**：
- week：本周一 00:00:00（ISO 周一为周首日）
- month：本月 1 日 00:00:00
- year：今年 1 月 1 日 00:00:00
- all：不加时间条件

**注意**：distance 在数据库中存的是米，返回给前端时转换为公里（除以 1000，保留 1 位小数）。
**依赖**：任务 2.3, 3.1（需要 activities 表存在）

### 任务 2.6：User 模块测试
1. 合法 code 登录 → token + user_id + is_new_user=true
2. 同一 openid 再次登录 → 相同 user_id + is_new_user=false
3. 非法 code → 401
4. 无 token 访问 profile → 401
5. 合法 token 获取 profile → 200
6. 更新 ftp=600（越界）→ 422
7. 更新 bike_type="car" → 422
8. 正常更新 profile → 200
9. 获取统计（无骑行记录）→ 全部为 0
10. 获取统计（有记录）→ 正确聚合值
11. period=month → 只统计本月数据
12. period 参数非法 → 422

> 微信接口用 pytest monkeypatch mock。
> 统计测试需要先在 activities 表插入测试数据。

---

## 3. Activity 模块

### 模块契约
| 项目 | 说明 |
|------|------|
| **职责** | 接收 GPX 文件、异步解析、存储轨迹和衍生统计数据 |
| **输入** | 用户 ID + GPX 文件 |
| **输出** | 活动 ID + 结构化轨迹 + 分段数据 + 功率区间 |
| **承诺** | 合法 GPX 返回 activity_id，异步解析完成后可查询全部数据 |
| **不管** | 轨迹匹配了哪个路段、排名多少 |

### 数据模型
```sql
CREATE TABLE activities (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    title           VARCHAR(128),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
                    -- pending → processing → completed → failed
    file_url        TEXT NOT NULL,
    error_message   TEXT,

    -- 解析完成后填充
    distance        FLOAT,                     -- 总距离 (米)
    duration        INTEGER,                   -- 总时间 (秒)
    elevation_gain  FLOAT,                     -- 总爬升 (米)
    avg_speed       FLOAT,                     -- 平均速度 (km/h)
    max_speed       FLOAT,                     -- 最大速度 (km/h)
    avg_power       FLOAT,                     -- 平均功率 (W)，可为 NULL
    max_power       FLOAT,                     -- 最大功率 (W)
    avg_hr          FLOAT,                     -- 平均心率 (bpm)
    max_hr          FLOAT,                     -- 最大心率
    avg_cadence     FLOAT,                     -- 平均踏频
    calories        FLOAT,                     -- 估算卡路里 (kcal)
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,

    -- 简化轨迹（前端地图渲染 + 卡片绘制）
    simplified_track JSONB,                    -- [{lat, lon, ele}, ...] 约 500-1000 点

    -- 每 10km 分段数据
    splits          JSONB,                     -- [{km:"0-10", avg_speed, avg_power, avg_hr, elevation_gain}, ...]

    -- 功率区间分布（依赖用户 FTP，无 FTP 则为 NULL）
    power_zones     JSONB,                     -- [{zone:"Z1", name:"恢复", min_w, max_w, seconds, percent}, ...]

    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE trackpoints (
    id              SERIAL PRIMARY KEY,
    activity_id     INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    elevation       FLOAT,
    timestamp       TIMESTAMP,
    heart_rate      INTEGER,
    cadence         INTEGER,
    power           INTEGER,
    geom            GEOMETRY(POINT, 4326)
);

CREATE INDEX idx_trackpoints_activity ON trackpoints(activity_id);
CREATE INDEX idx_trackpoints_geom ON trackpoints USING GIST(geom);
CREATE INDEX idx_activities_user_status ON activities(user_id, status);
CREATE INDEX idx_activities_user_started ON activities(user_id, started_at);
```

> **两份轨迹的用途**：trackpoints 全量逐点存储用于 Segment 精确匹配（需要时间戳和传感器数据）。simplified_track 是 Douglas-Peucker 简化后的坐标子集（仅 lat/lon/ele），用于前端地图渲染和卡片绘制，单次 API 响应 <100KB。
>
> **新增字段说明**：avg_power / max_power / avg_hr / max_hr / avg_cadence / calories / splits / power_zones 都在 GPX 解析时计算。如果 GPX 不含功率/心率/踏频数据，对应字段为 NULL。

### 任务 3.1：Activity 数据模型 + 迁移
**做什么**：创建 Activity 和 Trackpoint 的 SQLAlchemy 模型（含 GeoAlchemy2），生成迁移。
**注意**：Activity 模型包含 simplified_track / splits / power_zones 三个 JSONB 字段。新增 activities 表的两个索引。
**依赖**：任务 2.1

### 任务 3.2：GPX 解析器（纯函数）
**做什么**：实现 `gpx_parser.py`。纯函数，无数据库依赖，无用户信息依赖。
**输入**：GPX 文件内容（bytes 或 string）
**输出**：
```python
{
    "title": "Morning Ride",                 # 从 GPX <name> 提取，可为 None
    "started_at": datetime,
    "finished_at": datetime,
    "distance": 42195.0,                     # 米
    "duration": 7200,                        # 秒
    "elevation_gain": 580.0,                 # 米
    "avg_speed": 21.1,                       # km/h
    "max_speed": 52.3,                       # km/h
    "avg_power": 198.0,                      # W，无功率数据则为 None
    "max_power": 612.0,                      # W
    "avg_hr": 148.0,                         # bpm，无心率则为 None
    "max_hr": 178.0,
    "avg_cadence": 88.0,                     # rpm，无踏频则为 None
    "calories": 1120.0,                      # kcal，估算公式见下
    "trackpoints": [
        {"seq": 0, "lat": 37.76, "lon": 112.55, "ele": 800.0,
         "time": datetime, "hr": 145, "cad": 85, "power": 200},
        ...
    ],
    "splits": [                              # 每 10km 分段
        {"km": "0-10", "avg_speed": 28.4, "avg_power": 195.0,
         "avg_hr": 142.0, "elevation_gain": 82.0},
        ...
    ]
}
```

**分段（splits）计算逻辑**：
1. 遍历 trackpoints，按累计距离每 10km 切一刀
2. 每段内计算：avg_speed（段距离/段时间）、avg_power（段内功率均值）、avg_hr（段内心率均值）、elevation_gain（段内正爬升累加）
3. 最后一段可能不足 10km，标注为 "40-48.2"（实际距离）
4. 如果总距离 <10km，只有一段 "0-{distance_km}"
5. 功率/心率为 None 的点不参与对应均值计算

**卡路里估算公式**：
- 有功率数据：`calories = avg_power * duration / 1000 * 3.6 * 0.25`（假设 25% 效率）
- 无功率数据：`calories = duration / 3600 * weight * 8`（粗估 8 MET），weight 从参数传入，无则默认 70kg
- 注意：gpx_parser 本身不访问用户数据，calories 计算中的 weight 由调用方（Worker）传入

**错误处理**：
- 非法 XML → `GPXParseError("文件格式错误")`
- 无轨迹点 → `GPXParseError("文件无轨迹数据")`
- 无时间戳 → 仍解析坐标，duration/speed/splits 中的速度为 None

**解析规则**：
- 只解析 GPX 核心字段（lat/lon/ele/time）。心率/功率/踏频从 extensions 尝试提取，取不到为 None
- haversine 地球半径 6371000 米
- 爬升去噪：相邻点高差 >2m 才累加
- 速度异常：相邻点速度 >120km/h 视为 GPS 漂移，该段距离不累加
- gpxpy 库会处理大部分 GPX extensions 格式（Garmin/Wahoo/igpsport 等），不需要手动适配

**依赖**：无（纯函数）

### 任务 3.3：功率区间计算（纯函数）
**做什么**：实现一个独立函数，根据用户 FTP 和 trackpoints 中的功率数据计算功率区间分布。
**位置**：可以放在 `gpx_parser.py` 中作为独立函数，也可以单独文件。

```python
def calculate_power_zones(trackpoints: list[dict], ftp: int) -> list[dict]:
    """
    输入：trackpoints（含 power 和 time 字段）+ 用户 FTP
    输出：6 个区间的时间分布
    如果 trackpoints 中无功率数据（所有 power 为 None），返回 None
    """
```

**功率区间定义（基于 FTP 百分比）**：

| Zone | 名称 | 范围 |
|------|------|------|
| Z1 | 恢复 | 0 - 55% FTP |
| Z2 | 耐力 | 55% - 75% FTP |
| Z3 | 节奏 | 75% - 90% FTP |
| Z4 | 阈值 | 90% - 105% FTP |
| Z5 | VO2max | 105% - 120% FTP |
| Z6 | 无氧 | >120% FTP |

**输出格式**：
```json
[
    {"zone": "Z1", "name": "恢复", "min_w": 0, "max_w": 129, "seconds": 480, "percent": 8},
    {"zone": "Z2", "name": "耐力", "min_w": 130, "max_w": 176, "seconds": 1320, "percent": 22},
    ...
]
```

**计算逻辑**：
1. 遍历相邻 trackpoints，计算每对点之间的时间差（秒）
2. 将时间差归入对应功率区间（按前一个点的功率值）
3. percent = 该区间秒数 / 总有功率秒数 * 100，四舍五入到整数

**关键规则**：用户未设 FTP（ftp=None）→ 调用方不调用此函数，activity.power_zones 存 NULL。

**依赖**：无（纯函数）

### 任务 3.4：Douglas-Peucker 轨迹简化（纯函数）
**做什么**：实现 `simplify.py`。
**输入**：trackpoints 列表 + target_count（默认 800）
**输出**：`[{lat, lon, ele}, ...]`（仅保留绘图所需，不含时间和传感器数据）
**算法**：标准 Douglas-Peucker，二分搜索 epsilon 使输出点数接近 target_count（±20%）。
**注意**：输入 <target_count 时直接返回。始终保留首尾点。
**依赖**：无

### 任务 3.5：GPX 上传接口
**路径**：`POST /api/activities/upload`
**输入**：multipart form-data，字段 `file`
**处理流程**：
1. 从 JWT 获取 user_id
2. 校验后缀 .gpx
3. 校验大小 ≤ 50MB
4. 读前 256 字节，跳过可能存在的 BOM（`\xEF\xBB\xBF`），确认以 `<?xml` 或 `<gpx` 开头
5. StorageBackend.upload() 存储，拿到 file_url
6. 创建 Activity 记录，status="pending"
7. 入 rq 队列：`queue.enqueue(parse_activity, activity_id)`
8. 返回 `{"activity_id": 1, "status": "pending"}`
**错误处理**：
- 非 .gpx → `400 "只接受.gpx文件"`
- >50MB → `400 "文件大小不能超过50MB"`
- 前 256 字节非 XML → `400 "文件内容不是有效的GPX格式"`
- 存储失败 → `500 "文件上传失败"`
**依赖**：任务 1.3, 1.4, 2.3, 3.1

### 任务 3.6：异步解析 Worker
**做什么**：实现 rq 任务函数 `parse_activity(activity_id)`。
**使用同步 session**（与 API 共用 `SessionLocal`）。

**处理流程**：
1. `db = SessionLocal()`
2. 取 activity 记录 + 关联的 user 记录（需要 user.ftp 和 user.weight）
3. 从 StorageBackend 下载 GPX
4. 更新 status="processing"
5. 调 `gpx_parser.parse(gpx_content, weight=user.weight)` 解析
6. 将统计量写入 activity（distance, duration, elevation_gain, avg_speed, max_speed, avg_power, max_power, avg_hr, max_hr, avg_cadence, calories, splits）
7. 调 `simplify()` 生成简化轨迹 → activity.simplified_track
8. 如果 user.ftp 不为 None 且轨迹包含功率数据 → 调 `calculate_power_zones(trackpoints, user.ftp)` → activity.power_zones；否则 power_zones = None
9. 批量插入 trackpoints（每 500 条一批），生成 PostGIS geom
10. 更新 status="completed"
11. **触发 Segment 匹配**（调用 `segment.service.match_activity_against_segments(activity_id, db)`）
12. `db.close()`

**失败处理**：
- GPXParseError → status="failed"，error_message=错误信息
- 未预期异常 → status="failed"，error_message="系统内部错误"
- 无论成功失败都更新 updated_at 并 close db
**依赖**：任务 3.1, 3.2, 3.3, 3.4, 1.3, 1.4

### 任务 3.7：活动查询接口

**接口 1**：`GET /api/activities` — 当前用户活动列表
- 分页：page + page_size
- 排序：created_at 降序
- **响应字段**（不含轨迹和大 JSON）：
```json
{
    "items": [
        {
            "id": 1,
            "title": "龙城大道晨骑",
            "status": "completed",
            "distance": 48.2,
            "duration": 5534,
            "elevation_gain": 386.0,
            "avg_speed": 31.4,
            "avg_power": 198.0,
            "avg_hr": 148.0,
            "started_at": "2026-04-07T06:42:00+08:00",
            "created_at": "2026-04-07T06:42:00+08:00"
        }
    ],
    "total": 42,
    "page": 1,
    "page_size": 20
}
```

**接口 2**：`GET /api/activities/{activity_id}` — 活动详情
- 包含全部统计量 + simplified_track + splits + power_zones
- **不返回** trackpoints 表数据
- 仅允许查看自己的活动 → 否则 `403`
- status=pending/processing 时可查询，simplified_track/splits/power_zones 为 null
- **响应字段**：
```json
{
    "id": 1,
    "user_id": 1,
    "title": "龙城大道晨骑",
    "status": "completed",
    "distance": 48.2,
    "duration": 5534,
    "elevation_gain": 386.0,
    "avg_speed": 31.4,
    "max_speed": 52.1,
    "avg_power": 198.0,
    "max_power": 612.0,
    "avg_hr": 148.0,
    "max_hr": 178.0,
    "avg_cadence": 88.0,
    "calories": 1120.0,
    "started_at": "2026-04-07T06:42:00",
    "finished_at": "2026-04-07T08:14:14",
    "simplified_track": [{"lat": 37.76, "lon": 112.55, "ele": 800.0}, ...],
    "splits": [{"km": "0-10", "avg_speed": 28.4, "avg_power": 195.0, "avg_hr": 142.0, "elevation_gain": 82.0}, ...],
    "power_zones": [{"zone": "Z1", "name": "恢复", "min_w": 0, "max_w": 129, "seconds": 480, "percent": 8}, ...],
    "created_at": "2026-04-07T06:42:00"
}
```

**接口 3**：`PATCH /api/activities/{activity_id}` — 编辑活动信息
- 仅允许编辑自己的活动，否则 `403`
- 可编辑字段：`title`（1-128 字符）
- 返回更新后的活动摘要
- 用途：GPX 文件中的标题可能为空或不合适（如 "Morning Ride"），用户需要能自定义

**接口 4**：`DELETE /api/activities/{activity_id}`
- 仅允许删除自己的活动
- 级联删除：trackpoints + 关联 segment_efforts
- 删除 StorageBackend 中的原始文件
- 返回 `204 No Content`

**接口 5**：`GET /api/activities/{activity_id}/status` — 轮询解析状态
- 返回 `{"status": "pending|processing|completed|failed", "error_message": null}`
- 前端上传后每 2 秒轮询
**依赖**：任务 2.3, 3.1

### 任务 3.8：Activity 模块测试

GPX 解析器（纯函数）：
1. 合法 GPX（含功率心率）→ 正确的全部统计量
2. 合法 GPX（无功率无心率）→ avg_power/avg_hr/calories 为 None 或粗估值
3. 空轨迹 → GPXParseError
4. 非 XML → GPXParseError
5. 无时间戳 → 坐标正常，speed=None，splits 中速度为 None
6. GPS 漂移（>120km/h）→ 该段距离不累加

分段（splits）：
7. 48.2km 骑行 → 5 段（0-10, 10-20, 20-30, 30-40, 40-48.2）
8. 8km 骑行 → 1 段（0-8）
9. 段内功率部分为 None → avg_power 只算有值的点

功率区间：
10. FTP=235, 有功率数据 → 6 个区间 percent 之和 = 100
11. FTP=235, 无功率数据 → 返回 None
12. FTP=None → 调用方不调用，不测

轨迹简化：
13. 10000 点 → 输出 640-960 点
14. 100 点 → 原样返回
15. 首尾点保留

上传接口：
16. 合法 .gpx → 201 + activity_id + status=pending
17. .txt → 400
18. PDF 改后缀 .gpx → 400（256 字节校验）
19. 未登录 → 401

Worker：
20. 正常解析 → status=completed，所有字段有值
21. 解析失败 → status=failed，error_message 有值

查询/删除：
22. 活动列表 → 200 + 分页，不含 simplified_track
23. 活动详情 → 200，含 simplified_track + splits + power_zones
24. 查别人活动 → 403
25. 删除活动 → 204，trackpoints/effort/文件全部清理
26. 删别人活动 → 403
27. 编辑活动标题 → 200，title 更新
28. 编辑别人的活动 → 403
29. 标题超 128 字符 → 422

> 测试 GPX：`tests/fixtures/test_ride.gpx`（含功率心率，约 100 点）+ `tests/fixtures/test_ride_no_power.gpx`（无功率）+ `tests/fixtures/fake.gpx`（PDF 改后缀）

---

## 4. Segment 模块

### 模块契约
| 项目 | 说明 |
|------|------|
| **职责** | 管理预设路段、匹配轨迹、维护排行榜、查询活动途经赛段 |
| **输入** | 活动 ID + 路段库 |
| **输出** | 匹配结果 + 排行榜 + 活动途经赛段 |
| **承诺** | 活动解析完成后自动匹配。匹配成功计算成绩并更新排行榜 |
| **不管** | 轨迹怎么来的、用户资料细节 |

### 数据模型
```sql
CREATE TABLE segments (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    description     TEXT,
    distance        FLOAT NOT NULL,                -- 米
    elevation_gain  FLOAT,

    start_lat       DOUBLE PRECISION NOT NULL,
    start_lon       DOUBLE PRECISION NOT NULL,
    end_lat         DOUBLE PRECISION NOT NULL,
    end_lon         DOUBLE PRECISION NOT NULL,

    reference_line  GEOMETRY(LINESTRING, 4326) NOT NULL,

    match_tolerance FLOAT DEFAULT 50.0,
    min_match_ratio FLOAT DEFAULT 0.8,

    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_segments_geom ON segments USING GIST(reference_line);

CREATE TABLE segment_efforts (
    id              SERIAL PRIMARY KEY,
    segment_id      INTEGER NOT NULL REFERENCES segments(id),
    activity_id     INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id),

    elapsed_time    INTEGER NOT NULL,              -- 秒
    avg_speed       FLOAT,
    avg_power       FLOAT,

    start_index     INTEGER NOT NULL,              -- trackpoint seq
    end_index       INTEGER NOT NULL,

    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(segment_id, activity_id)
);

CREATE INDEX idx_efforts_segment_time ON segment_efforts(segment_id, elapsed_time);
CREATE INDEX idx_efforts_user ON segment_efforts(user_id);
```

### 任务 4.1：Segment 数据模型 + 迁移
**依赖**：任务 2.1, 3.1

### 任务 4.2：路段管理接口

**接口 1**：`POST /api/segments` — 创建路段（**需管理员权限**）
- **权限**：仅 `is_admin=True` 的用户可调用，否则 `403 "需要管理员权限"`
- 输入：name, description, reference_points（经纬度数组）
- 处理：转 PostGIS LineString，自动算 distance/elevation_gain，提取首尾点
- 返回：segment 完整信息

**接口 2**：`GET /api/segments` — 路段列表
- 可选：`near_lat`, `near_lon`, `radius`（米，默认 50000）
- 有坐标时用 `ST_DWithin(reference_line::geography, ST_MakePoint(lon, lat)::geography, radius)` 过滤（必须转 geography，距离单位才是米）
- 返回字段：id, name, distance, elevation_gain, start/end 坐标, entries（该路段的 effort 总数）

**接口 3**：`GET /api/segments/{segment_id}` — 路段详情
- 返回路段信息 + 前 20 名排行榜
- 排行榜字段：rank, user_id, nickname, avatar_url, elapsed_time, avg_speed, avg_power, created_at

**依赖**：任务 4.1, 2.3

### 任务 4.3：GPS 精确匹配算法（纯函数）
**做什么**：实现 `matcher.py`。纯函数，只接收坐标数组。

```python
def match_segment(
    trackpoints: list[dict],           # [{lat, lon, time, seq}, ...]
    segment_start: tuple[float,float],
    segment_end: tuple[float,float],
    reference_coords: list[tuple],     # [(lat, lon), ...]
    match_tolerance: float = 50.0,
    min_match_ratio: float = 0.8,
) -> dict:
    # 返回 {matched: True, start_index, end_index, elapsed_time}
    # 或 {matched: False}
```

**算法**：
1. 找起点：距 segment_start 最近且在 tolerance 内 → start_index
2. 找终点：从 start_index 之后，距 segment_end 最近且在 tolerance 内 → end_index
3. 覆盖验证：start_index~end_index 之间的点，计算有多少在 reference_coords 折线 tolerance 范围内，≥ min_match_ratio
4. elapsed_time = time[end_index] - time[start_index]

**规则**：haversine 距离 / 无时间戳→False / 多次经过取第一次
**依赖**：无

### 任务 4.4：粗筛 + 自动匹配触发（service 层）
**做什么**：`segment/service.py` 中实现 `match_activity_against_segments(activity_id, db)`。由 Worker 调用。

**处理流程**：
1. PostGIS 粗筛（**注意：必须转 geography 类型，否则距离单位是度不是米**）：
   ```sql
   SELECT * FROM segments
   WHERE ST_DWithin(
       reference_line::geography,
       (SELECT ST_ConvexHull(ST_Collect(geom))::geography FROM trackpoints WHERE activity_id = :id),
       100  -- 单位：米。转 geography 后 ST_DWithin 以米为单位
   )
   ```
2. 取该活动全部 trackpoints
3. 对每个通过粗筛的 segment 调 `matcher.match_segment()`
4. 匹配成功 → 创建 segment_effort
5. 计算 avg_speed 和 avg_power（从 start_index 到 end_index 的 trackpoints）
6. 单个 segment 失败不影响其他

**依赖**：任务 3.6, 4.1, 4.3

### 任务 4.5：排行榜查询接口

**接口 1**：`GET /api/segments/{segment_id}/leaderboard`
- elapsed_time 升序
- 分页
- 字段：rank, user_id, nickname, avatar_url, elapsed_time, avg_speed, avg_power, bike_type, created_at
- 可选过滤：`bike_type`

**接口 2**：`GET /api/user/efforts` — 当前用户所有路段成绩
- 返回字段：segment_id, segment_name, elapsed_time, avg_speed, rank, created_at

**依赖**：任务 4.1, 4.2, 2.3

### 任务 4.6：活动途经赛段接口
**路径**：`GET /api/activities/{activity_id}/segments`
**路由注册位置**：segment 模块的 router（Segment 依赖 Activity，方向正确）
**响应**：
```json
{
    "items": [
        {
            "segment_id": 1,
            "segment_name": "龙城大道冲刺段",
            "elapsed_time": 142,
            "avg_speed": 36.2,
            "avg_power": 245.0,
            "rank": 2,
            "is_pr": false
        },
        {
            "segment_id": 2,
            "segment_name": "汾河北段计时",
            "elapsed_time": 522,
            "avg_speed": 28.1,
            "avg_power": 198.0,
            "rank": 1,
            "is_pr": true
        }
    ]
}
```

**is_pr 判断**：该 effort 的 elapsed_time 等于该用户在该 segment 上的最佳成绩。

**rank 计算**：该 effort 在该 segment 所有 effort 中按 elapsed_time 排第几。
实现方式：子查询 `SELECT COUNT(*) + 1 FROM segment_efforts WHERE segment_id = :sid AND elapsed_time < :this_time`

**权限**：仅允许查看自己活动的途经赛段 → 否则 403
**依赖**：任务 4.1, 3.1, 2.3

### 任务 4.7：Segment 模块测试

匹配算法（纯函数）：
1. 完全覆盖 → matched=True, elapsed_time 正确
2. 经过起点未到终点 → False
3. 偏离超 tolerance → False
4. 方向相反 → False
5. 无时间戳 → False

粗筛（需数据库）：
6. 轨迹附近 → 通过
7. 50km 外 → 排除

集成测试：
8. 上传 GPX → 自动匹配 → effort 入库
9. 同一活动同一路段不重复
10. 排行榜按 elapsed_time 排序
11. 删除活动 → effort 级联删除
12. 查活动途经赛段 → 返回匹配的 segment + rank + is_pr
13. 查别人活动的途经赛段 → 403

> 测试数据：一条 segment reference_points + 一条匹配 GPX + 一条不匹配 GPX

---

## 5. 骑行卡片模块（前端 canvas）

### 设计规格

**尺寸**：750 × 1334 px

**卡片布局（深色主题为默认）**：
```
┌──────────────────────────────────────┐
│                                      │
│  [头像] 昵称          RIDEMAP logo   │  ← 顶栏 (80px)
│                                      │
├──────────────────────────────────────┤
│                                      │
│         骑行标题                      │  ← 标题区 (80px)
│         2026.04.07 · 22°C · 晴       │
│                                      │
├──────────────────────────────────────┤
│                                      │
│      ┌────────────────────────┐      │
│      │                        │      │
│      │   simplified_track     │      │  ← 路线图 (400px)
│      │   折线渲染              │      │
│      │                        │      │
│      │   ●起点         终点●   │      │
│      │                        │      │
│      └────────────────────────┘      │
│                                      │
├──────────────────────────────────────┤
│                                      │
│   距离         时间         均速      │  ← 核心数据 (160px)
│   65.3km     2:05:48    31.1km/h    │
│                                      │
│   爬升         功率         心率      │
│   720m        221W       162bpm     │
│                                      │
├──────────────────────────────────────┤
│                                      │
│  🏆 汾河北段 #1  ·  龙城大道 #2     │  ← 赛段标签 (80px, 有赛段时显示)
│                                      │
├──────────────────────────────────────┤
│                                      │
│  [小程序码]  扫码查看完整骑行数据     │  ← 底栏 (100px)
│              RIDEMAP · 骑行地图      │
│                                      │
└──────────────────────────────────────┘
```

**无赛段时**：赛段区域不渲染，路线图区域向下扩展 80px。

### 任务 5.1：骑行卡片 canvas 组件
**做什么**：小程序 `components/share-card/share-card`。
**输入**：
- 活动详情（`GET /api/activities/{id}` 响应）
- 途经赛段（`GET /api/activities/{id}/segments` 响应，可为空）
- 用户信息（nickname, avatar_url）
- 主题（dark / light）

**技术方案**：
```javascript
// 使用离屏 canvas
const canvas = wx.createOffscreenCanvas({type: '2d', width: 750, height: 1334});
const ctx = canvas.getContext('2d');

// 绘制顺序：
// 1. 背景（深色：#1D1D1F 渐变 / 浅色：#FFFFFF）
// 2. 用户头像（wx.getImageInfo 加载 → 圆形裁剪 ctx.arc + ctx.clip）
// 3. 用户昵称 + RIDEMAP logo
// 4. 标题 + 日期
// 5. 路线图：
//    - 从 simplified_track 提取 lat/lon
//    - bounding box: minLat/maxLat/minLon/maxLon
//    - 坐标映射：
//      canvasX = padding + (lon - minLon) / (maxLon - minLon) * drawWidth
//      canvasY = padding + (1 - (lat - minLat) / (maxLat - minLat)) * drawHeight
//      （注意 lat 在 Y 轴方向是反的：纬度越大越靠上）
//    - ctx.beginPath() → ctx.moveTo() → ctx.lineTo() 循环 → ctx.stroke()
//    - 线宽 3px，颜色 #FF2D55，圆角 lineCap="round"
//    - 起点：绿色圆点(r=6)，终点：主题色圆点(r=6)
//    - 背景区：深色 #2C2C2E 圆角矩形
// 6. 六个数据格（2行×3列），数值大字 + 标签小字
//    - 值为 null 时显示 "--"
// 7. 赛段标签（如有）：每个标签一个圆角矩形，PR 用主题色背景
// 8. 底栏：小程序码（需预置一张 miniprogram_qr.png）+ 文字
// 9. 导出：
//    canvas.toTempFilePath({fileType: 'jpg', quality: 0.92})
```

**关键细节**：
- bounding box 加 10% padding 避免轨迹贴边
- 轨迹只有 2 个点 → 画直线，不崩溃
- 轨迹只有 1 个点 → 显示单个圆点
- 用户无头像 → 绘制昵称首字彩色圆

### 任务 5.2：卡片分享交互
**交互流程**：
1. 活动详情页点"分享" → 弹底部面板
2. 面板内显示卡片缩略预览
3. 可切换主题（深色/浅色）
4. "保存到相册" → `wx.saveImageToPhotosAlbum`（需授权）
5. "发送给朋友" → `wx.shareImageMessage`
6. "发朋友圈" → 保存后提示用户手动发

### 任务 5.3：卡片组件测试
1. 完整数据（含功率心率赛段）→ 所有区域正常渲染
2. 无功率数据 → 功率格显示 "--"
3. 无匹配赛段 → 赛段区不显示，路线图扩展
4. simplified_track 2 个点 → 直线
5. simplified_track 1 个点 → 单圆点
6. 无头像 → 首字占位
7. 深色/浅色切换 → 背景和文字颜色正确

---

## 6. 部署方案

### 开发环境
```bash
# 依赖：Python 3.11+, PostgreSQL 16 + PostGIS, Redis
uvicorn app.main:app --reload --port 8000    # API
python worker.py                              # Worker（另一个终端）
```

### 生产环境（docker-compose 单机部署）

**推荐**：腾讯云轻量应用服务器 2C4G（学生优惠约 60 元/月）

> **HTTPS 是硬性要求**：微信小程序强制所有 API 请求走 HTTPS。使用 Caddy 作为反向代理，自动申请和续期 Let's Encrypt 证书，零配置 HTTPS。

**前置条件**：需要一个域名（如 `api.ridemap.cn`），A 记录指向服务器 IP，服务器开放 80/443 端口。

```yaml
# docker-compose.yml
version: "3.8"
services:
  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_DB: ridemap
      POSTGRES_USER: ridemap
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "127.0.0.1:5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "127.0.0.1:6379:6379"

  api:
    build: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    environment:
      DATABASE_URL: postgresql://ridemap:${DB_PASSWORD}@db:5432/ridemap
      REDIS_URL: redis://redis:6379/0
      JWT_SECRET: ${JWT_SECRET}
      WX_APPID: ${WX_APPID}
      WX_SECRET: ${WX_SECRET}
    expose:
      - "8000"                    # 不再暴露到宿主机，只允许 Caddy 访问
    depends_on:
      - db
      - redis
    volumes:
      - uploads:/app/uploads

  worker:
    build: .
    command: python worker.py
    environment:
      DATABASE_URL: postgresql://ridemap:${DB_PASSWORD}@db:5432/ridemap
      REDIS_URL: redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - uploads:/app/uploads

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"                   # HTTP（证书验证 + 自动跳转 HTTPS）
      - "443:443"                 # HTTPS
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - api

volumes:
  pgdata:
  uploads:
  caddy_data:
  caddy_config:
```

```
# Caddyfile（仅两行，Caddy 自动申请 SSL 证书）
api.ridemap.cn {
    reverse_proxy api:8000
}
```

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

**部署步骤**：
1. 购买域名，A 记录指向服务器 IP，服务器防火墙开放 80/443 端口
2. 服务器装 Docker + Docker Compose
3. 上传代码 + `.env` + `Caddyfile`（将 `api.ridemap.cn` 替换为你的实际域名）
4. `docker-compose up -d`（Caddy 自动申请 SSL 证书）
5. `docker-compose exec api alembic upgrade head`（初始化数据库）
6. 微信小程序后台 → 开发管理 → 服务器域名 → 添加 `https://你的域名`

**日志**：`docker-compose logs -f api` / `docker-compose logs -f worker`

---

## 7. 开发顺序

```
阶段一：基础设施
  1.1 → 1.2 → 1.3 → 1.4

阶段二：User 模块
  2.1 → 2.2 → 2.3 → 2.4 → 2.5 → 2.6（测试）
  注意：2.5 依赖 activities 表，但只需要表存在不需要有数据
        测试时用 SQL 直接插入 mock 数据

阶段三：Activity 模块
  3.1 → 3.2（可并行）→ 3.3（可并行）→ 3.4（可并行）→ 3.5 → 3.6 → 3.7 → 3.8（测试）

阶段四：Segment 模块
  4.1 → 4.2 → 4.3（可并行）→ 4.4 → 4.5 → 4.6 → 4.7（测试）

阶段五：骑行卡片（前端，可与阶段三并行）
  5.1 → 5.2 → 5.3（测试）

阶段六：部署
  docker-compose 上线 → 迁移 → 配置域名

阶段七：前端 api.js 对齐（见附录 A）
  按对照表修改所有 API 路径 → 逐接口联调
```

### 端到端验收检查点
1. **User 完成**：登录 → 改资料 → 看周统计（此时为 0）
2. **Activity 完成**：上传 GPX → 轮询状态 → 看详情（含 splits + power_zones + simplified_track）
3. **Segment 完成**：上传 GPX → 自动匹配 → 看排行榜 → 查途经赛段
4. **卡片完成**：详情页分享 → 生成卡片 → 保存到相册
5. **全链路**：登录 → 上传 → 等解析 → 看详情 → 看途经赛段 → 看排行榜 → 分享卡片 → 回首页看周统计更新

---

## 附录 A：前后端 API 路径对照表

前端 `api.js` 需按此表修改所有路径。后端以此表为准实现。

| 功能 | 前端当前路径 | 后端正式路径 | 方法 | 说明 |
|------|-------------|-------------|------|------|
| 微信登录 | `/api/user/wx-login` | `/api/user/login` | POST | 路径简化 |
| 获取资料 | `/api/user/profile` | `/api/user/profile` | GET | ✅ 一致 |
| 更新资料 | `/api/user/profile` | `/api/user/profile` | PUT | ✅ 一致 |
| **骑行统计** | ❌ 无（前端 mock 在 profile 里） | `/api/user/stats?period=week` | GET | **新增接口** |
| **用户赛段成绩** | `/api/segment/my-prs` | `/api/user/efforts` | GET | 路径变更 |
| 上传 GPX | `/api/activity/upload` | `/api/activities/upload` | POST | 单数→复数 |
| 活动列表 | `/api/activity/list` | `/api/activities` | GET | 去掉 /list |
| 活动详情 | `/api/activity/:id` | `/api/activities/:id` | GET | 单数→复数 |
| **编辑活动** | ❌ 无 | `/api/activities/:id` | PATCH | **新增**，可改标题 |
| **删除活动** | ❌ 无 | `/api/activities/:id` | DELETE | **新增** |
| **轮询状态** | `/api/jobs/:jobId/status` | `/api/activities/:id/status` | GET | 改为按 activity_id 查 |
| **途经赛段** | ❌ 无（前端 mock 在详情里） | `/api/activities/:id/segments` | GET | **新增接口** |
| 动态流 | `/api/activity/feed` | ❌ v1 不实现 | - | v3 社交功能，暂不做 |
| 路段列表 | `/api/segment/list` | `/api/segments` | GET | 去掉 /list |
| 路段详情 | `/api/segment/:id/detail` | `/api/segments/:id` | GET | 去掉 /detail |
| 排行榜 | `/api/segment/:id/leaderboard` | `/api/segments/:id/leaderboard` | GET | ✅ 一致 |
| 生成卡片 | `/api/content/share-card/:id` | ❌ 前端 canvas 生成 | - | 不需要后端接口 |
| 添加笔记 | `/api/content/segment-note` | ❌ v1 不实现 | - | |
| 探索路线 | `/api/explore/routes` | ❌ v1 不实现 | - | 前端可保留 mock |
| 点赞 | `/api/social/like/:id` | ❌ v1 不实现 | - | |
| 评论 | `/api/social/comment/:id` | ❌ v1 不实现 | - | |
| 关注 | `/api/social/follow/:id` | ❌ v1 不实现 | - | |

### 前端 api.js 修改要点
1. 所有 `/api/activity/` 改为 `/api/activities/`
2. 所有 `/api/segment/` 改为 `/api/segments/`
3. 去掉 `/list` 和 `/detail` 后缀
4. `wxLogin` 路径改为 `/api/user/login`
5. 新增 `getStats(period)` → `GET /api/user/stats?period=`
6. 新增 `getActivitySegments(activityId)` → `GET /api/activities/:id/segments`
7. 新增 `updateActivity(activityId, {title})` → `PATCH /api/activities/:id`
8. 新增 `deleteActivity(activityId)` → `DELETE /api/activities/:id`
8. 新增 `getActivityStatus(activityId)` → `GET /api/activities/:id/status`
9. 移除 `generateShareCard`（改为前端 canvas）
10. 移除 `getJobStatus`（改为按 activity_id 轮询）
11. v1 不实现的接口（feed, explore, social）保留 mock 即可

### 前端首页数据获取变更
之前 `getProfile()` 返回的 mock 数据包含 `weeklyKm, weeklyRides, weeklyElev` 等统计字段。正式对接后，这些数据从独立接口获取：
```javascript
// 之前（mock 混在 profile 里）
const profile = await API.getProfile();
const weeklyKm = profile.weeklyKm;

// 之后（分两个接口）
const profile = await API.getProfile();   // 只有基本资料
const stats = await API.getStats("week"); // 骑行统计
const weeklyKm = stats.distance;
```

### 前端活动详情页数据获取变更
之前一个接口返回全部数据。正式对接后拆成两个请求：
```javascript
// 之前（全部 mock 在一起）
const detail = await API.getActivityDetail(id);
const segments = detail.matchedSegments;

// 之后（分两个接口，可并行请求）
const [detail, segments] = await Promise.all([
    API.getActivityDetail(id),           // 活动数据 + simplified_track + splits + power_zones
    API.getActivitySegments(id),         // 途经赛段（来自 Segment 模块）
]);
```
