# RIDEMAP v2 技术规格文档 — 数据来源抽象层（翻译层）

> 本文档为第 1 期开发参考。前置条件：第 0 期（地基修补）已完成。
> 设计目标：让系统能消化 GPX、FIT、Strava 三种数据来源，统一输出格式后
> 喂给现有的 Worker → 数据库 → API → 前端链路，不改动下游逻辑。
>
> **设计决策记录（2026-04-15，Starsky 确认）：**
> - 速度内部单位 m/s，API 层转 km/h
> - 新增 speed、distance 字段（temperature、grade 仅预留不实现）
> - 数据源自带摘要就用自带的（FIT session / Strava summary），GPX 自己算
> - 老数据不回填，兼容 NULL
> - Strava 10000 点降采样上限接受，不做额外处理
> - 坐标系统一 WGS84，GCJ-02 来源在入口转换
> - FIT 解析库用 garmin-fit-sdk（Garmin 官方维护）
> - GCJ-02→WGS84 转换用 xyconvert（NumPy 批量处理）

---

## 0. 架构总览

### 设计原则

1. **模块化隔离**：每个解析器是独立文件，互不 import，任何一个出 bug 不影响其他
2. **单向数据流**：原始字节 → 解析器 → 统一格式 → 坐标归一化 → Worker → 数据库
3. **不可变数据**：解析器输出的数据是只读的，下游不能修改，只能创建新的
4. **接口契约**：所有解析器遵守同一个输出格式，Worker 不关心数据来自哪里

### 数据流全景

```
数据入口                    翻译层                        现有系统（不改动）
==========          ====================              ====================

GPX 文件 (bytes)─→ GPXParser.parse() ──→┐
                                        │
FIT 文件 (bytes)─→ FITParser.parse() ──→├→ ParseResult ──→ CoordNormalizer
                                        │   (frozen)         │
Strava Streams ──→ StravaAdapter    ───→┘                    │
  (JSON dict)       .from_streams()                          ▼
                                                      ParseResult (WGS84)
                                                             │
                                                             ▼
                                                    Worker（现有，小改）
                                                      ├→ Activity 表
                                                      ├→ Trackpoint 表
                                                      └→ 自动赛段匹配
```

### 新增项目结构

```
app/
├── parsing/                        # 翻译层（新增模块）
│   ├── __init__.py                 # 模块说明
│   ├── types.py                    # 统一数据结构定义（Trackpoint, ParseResult 等）
│   ├── gpx_parser.py              # GPX 解析器（从 activity/gpx_parser.py 重构迁移）
│   ├── fit_parser.py              # FIT 解析器（新增）
│   ├── strava_adapter.py          # Strava Streams 适配器（新增）
│   ├── coord_normalizer.py        # 坐标系检测 + GCJ-02→WGS84 转换（新增）
│   ├── geo_math.py                # 通用地理计算（haversine、爬升累加，从旧 gpx_parser 抽出）
│   └── stats_calculator.py        # 通用统计计算（splits、卡路里，从旧 gpx_parser 抽出）
│
├── strava/                         # Strava 集成模块（第 2 期，本期只定接口）
│   ├── __init__.py
│   ├── client.py                  # Strava API 客户端（OAuth + 请求封装）
│   ├── import_scheduler.py        # 渐进导入调度器
│   └── webhook.py                 # Webhook 接收端
│
├── activity/
│   ├── gpx_parser.py              # → 废弃，逻辑迁移到 parsing/gpx_parser.py
│   ├── worker.py                  # 小改：调用 parsing 模块而不是旧 gpx_parser
│   └── ...                        # 其他文件不动
```

### 模块依赖方向（单向，禁止反向 import）

```
parsing/types.py          ← 所有解析器 import 这个（数据结构定义）
parsing/geo_math.py       ← gpx_parser、stats_calculator import 这个
parsing/stats_calculator.py ← gpx_parser import 这个（FIT/Strava 不需要，它们有自带摘要）
parsing/coord_normalizer.py ← Worker import 这个

activity/worker.py        ← import parsing/types, parsing/coord_normalizer
activity/worker.py        ← import parsing/gpx_parser 或 fit_parser（根据文件类型选择）

segment/matcher.py        ← 不改动，继续接收 dict 格式的 trackpoints
```

---

## 1. 统一数据结构（types.py）

### 1.1 Trackpoint — 单个轨迹点

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True, slots=True)
class Trackpoint:
    """
    统一轨迹点——"骑行数据的最小单元"。

    好比心电图上的一个采样点：记录了某一瞬间你在哪、骑多快、心跳多少。
    所有数据源（GPX/FIT/Strava）解析后都变成这个格式，
    下游模块只认这一种"货币"，不关心它原来是什么"外币"。

    frozen=True：创建后不可修改，防止下游模块意外篡改解析结果。
    slots=True：内存优化，50000 个点省下约 14MB。
    """
    seq: int                        # 序号（0 开始，按时间顺序递增）
    lat: float                      # 纬度（度，WGS84）
    lon: float                      # 经度（度，WGS84）
    ele: float | None               # 海拔（米），GPS 可能无高程数据
    time: datetime | None           # UTC 时间戳，极少数文件可能无时间
    hr: int | None                  # 心率（bpm），无心率传感器为 None
    cad: int | None                 # 踏频（rpm），无踏频传感器为 None
    power: int | None               # 功率（W），无功率计为 None
    speed: float | None             # 速度（m/s），GPX 需计算，FIT/Strava 直接提供
    distance: float | None          # 累计距离（米），GPX 需计算，FIT/Strava 直接提供
    # ---- 以下字段仅预留定义，本期不实现 ----
    # temperature: int | None       # 温度（°C）
    # grade: float | None           # 坡度（%）
```

### 1.2 ActivitySummary — 活动统计摘要

```python
@dataclass(frozen=True)
class ActivitySummary:
    """
    活动统计摘要——"成绩单"。

    FIT 和 Strava 数据源自带这些数据（设备端或服务端计算，精度更高）。
    GPX 没有摘要，由 stats_calculator 从 trackpoints 算出。
    """
    distance: float                 # 总距离（米）
    duration: int | None            # 总时间（秒），无时间戳时为 None
    elevation_gain: float           # 总爬升（米）
    avg_speed: float | None         # 平均速度（m/s）
    max_speed: float | None         # 最大速度（m/s）
    avg_power: float | None         # 平均功率（W）
    max_power: int | None           # 最大功率（W）
    avg_hr: float | None            # 平均心率（bpm）
    max_hr: int | None              # 最大心率（bpm）
    avg_cadence: float | None       # 平均踏频（rpm）
    calories: float | None          # 估算卡路里（kcal）
    started_at: datetime | None     # 骑行开始时间（UTC）
    finished_at: datetime | None    # 骑行结束时间（UTC）
    splits: list[dict] | None       # 每 10km 分段统计
    normalized_power: int | None    # 标准化功率（NP），FIT 自带，GPX 无法算
```

### 1.3 ParseMetadata — 解析元数据

```python
from enum import Enum

class CoordSystem(Enum):
    """坐标系枚举"""
    WGS84 = "wgs84"        # GPS 标准，所有码表用这个
    GCJ02 = "gcj02"        # 中国火星坐标，部分国内 App 用这个

class DataSource(Enum):
    """数据来源枚举"""
    GPX = "gpx"
    FIT = "fit"
    STRAVA = "strava"

@dataclass(frozen=True)
class ParseMetadata:
    """
    解析元数据——"快递单上的寄件信息"。

    记录数据从哪来、什么格式、什么坐标系，
    供 CoordNormalizer 判断是否需要坐标转换。
    """
    source: DataSource              # 数据来源
    coord_system: CoordSystem       # 坐标系（解析器根据 creator 字段推断）
    title: str | None               # 活动标题
    creator: str | None             # GPX 的 <creator> 字段 / FIT 的 manufacturer
    file_hash: str | None           # 文件 SHA-256 哈希（去重用）
```

### 1.4 ParseResult — 解析器统一输出

```python
@dataclass(frozen=True)
class ParseResult:
    """
    解析器的统一输出——"翻译完成的标准文件袋"。

    不管原始数据是 GPX、FIT 还是 Strava Streams，
    解析后都变成这一个格式。Worker 只认这个格式，
    不关心数据来自哪里。
    """
    trackpoints: list[Trackpoint]   # 轨迹点列表（按时间排序）
    summary: ActivitySummary        # 统计摘要
    metadata: ParseMetadata         # 元数据（来源、坐标系等）
    simplified_track: list[dict] | None  # Douglas-Peucker 简化后的轨迹（前端地图用）
    power_zones: list[dict] | None       # 功率区间分布（需要 user.ftp，可能为 None）
```

### 1.5 解析器接口契约

```python
from typing import Protocol

class RideParser(Protocol):
    """
    解析器接口——所有解析器必须实现这个方法签名。

    用 Protocol（鸭子类型）而不是继承，
    这样三个解析器文件之间零依赖，互不 import。
    """
    def parse(self, content: bytes, **kwargs) -> ParseResult: ...
```

---

## 2. GPX 解析器重构（parsing/gpx_parser.py）

### 2.1 职责

从现有 `activity/gpx_parser.py` 迁移，改为输出 `ParseResult` 格式。

### 2.2 变更点

| 项目 | 旧（activity/gpx_parser.py） | 新（parsing/gpx_parser.py） |
|------|---------------------------|--------------------------|
| 输出格式 | plain dict | ParseResult（frozen dataclass） |
| trackpoint 格式 | `{"seq", "lat", "lon", "ele", "time", "hr", "cad", "power"}` | Trackpoint dataclass，新增 speed、distance |
| 地理计算 | 内嵌在文件里 | 抽到 geo_math.py |
| 统计计算 | 内嵌在文件里 | 抽到 stats_calculator.py |
| 坐标系检测 | 不做 | 读 `<metadata><creator>` 推断坐标系 |
| speed | 不计算 | 逐点计算（m/s），存入 Trackpoint.speed |
| distance | 不计算 | 逐点累加（米），存入 Trackpoint.distance |
| 速度单位 | avg_speed 用 km/h | 统一 m/s，API 层转 km/h |

### 2.3 坐标系来源识别

GPX 文件的 `<metadata><creator>` 字段标识了生成软件/设备。维护一张映射表：

```python
# 已知使用 GCJ-02 的 creator（持续维护，遇到新 App 就加）
_GCJ02_CREATORS = {
    "xingzhe",          # 行者
    "keep",             # Keep
    "codoon",           # 咕咚
    "huawei health",    # 华为运动健康（大陆版）
    "两步路",           # 两步路户外
}

def _detect_coord_system(creator: str | None) -> CoordSystem:
    """
    根据 GPX creator 字段推断坐标系。
    未知来源默认 WGS84（因为所有码表都是 WGS84）。
    """
    if creator:
        creator_lower = creator.lower()
        for gcj_name in _GCJ02_CREATORS:
            if gcj_name in creator_lower:
                return CoordSystem.GCJ02
    return CoordSystem.WGS84
```

### 2.4 GPX 解析核心流程

```python
def parse(content: bytes, weight: float = 70.0) -> ParseResult:
    """
    GPX 解析器入口。

    参数：
        content: GPX 文件字节流
        weight: 骑行者体重（kg），用于卡路里估算

    返回：
        ParseResult（可能是 GCJ-02 坐标，由 CoordNormalizer 统一转换）
    """
    # 1. XML 解析（跳过 BOM，gpxpy 解析）
    # 2. 提取 creator 字段 → 推断坐标系
    # 3. 逐点提取：lat, lon, ele, time, hr, cad, power
    # 4. 逐点计算：speed（m/s）、distance（累计米）← 调用 geo_math
    # 5. 计算统计摘要 ← 调用 stats_calculator
    # 6. 计算 simplified_track ← 调用现有 simplify.py
    # 7. 组装 ParseResult 返回
```

---

## 3. FIT 解析器（parsing/fit_parser.py）

### 3.1 依赖

```
garmin-fit-sdk >= 21.200.0
```

### 3.2 核心流程

```python
def parse(content: bytes, weight: float = 70.0) -> ParseResult:
    """
    FIT 解析器入口。

    FIT 是 Garmin 定义的二进制格式，所有品牌码表（佳明/iGPSport/迈金/Wahoo）
    都支持导出 FIT。它比 GPX 紧凑、字段更丰富（自带速度、距离、坡度）。
    """
    # 1. garmin-fit-sdk 解码（自动转换 scale/offset/timestamp）
    # 2. 遍历 record_mesgs → 提取逐点数据
    #    - position_lat/long：semicircles → 度（需手动转换）
    #    - enhanced_speed：m/s（优先用 enhanced 版本）
    #    - enhanced_altitude：米
    #    - distance：累计米
    #    - heart_rate, cadence, power：直接取
    #    - timestamp：已自动转为 Python datetime（UTC）
    # 3. 从 session_mesgs → 提取统计摘要（设备端计算，比我们后算的准）
    #    - total_distance, total_timer_time, total_ascent
    #    - avg_speed, max_speed（m/s）
    #    - avg_power, max_power, normalized_power
    #    - avg_heart_rate, max_heart_rate, avg_cadence
    #    - total_calories
    # 4. 如果 session 摘要缺字段 → 用 stats_calculator 从 trackpoints 补算
    # 5. 计算 simplified_track
    # 6. 坐标系：FIT 文件全部来自码表硬件 → 固定 WGS84
    # 7. 组装 ParseResult 返回
```

### 3.3 FIT 特有的字段映射

| FIT record 字段 | Trackpoint 字段 | 转换 |
|----------------|----------------|------|
| `position_lat` | `lat` | `× (180 / 2^31)` semicircles→度 |
| `position_long` | `lon` | 同上 |
| `enhanced_altitude` / `altitude` | `ele` | 直接取（米），优先 enhanced |
| `timestamp` | `time` | SDK 自动转 datetime（UTC） |
| `heart_rate` | `hr` | 直接取（bpm） |
| `cadence` | `cad` | 直接取（rpm） |
| `power` | `power` | 直接取（W） |
| `enhanced_speed` / `speed` | `speed` | 直接取（m/s），优先 enhanced |
| `distance` | `distance` | 直接取（累计米） |

### 3.4 错误处理

```python
class FITParseError(Exception):
    """FIT 解析失败"""
    pass
```

- 文件不是合法 FIT → `FITParseError("文件格式错误")`
- 无 record 消息 → `FITParseError("文件无轨迹数据")`
- sport != cycling → `FITParseError("非骑行活动")`（或 log 警告后继续）
- 轨迹点超过 50000 → `FITParseError("轨迹点过多")`

---

## 4.（已迁移至第 2 期设计 → 6.3 节）

---

## 5. 坐标系归一化（parsing/coord_normalizer.py）

### 5.1 职责

检查 ParseResult 的坐标系，如果是 GCJ-02 则转换为 WGS84。

### 5.2 依赖

```
xyconvert >= 0.4.0    # NumPy 批量坐标转换，比 eviltransform 快 50-70 倍
```

### 5.3 核心流程

```python
def normalize(result: ParseResult) -> ParseResult:
    """
    坐标系归一化——确保输出的 ParseResult 坐标是 WGS84。

    如果已经是 WGS84 → 原样返回（零开销）。
    如果是 GCJ-02 → 创建新的 ParseResult，所有坐标转为 WGS84。
    不修改原始输入（frozen dataclass 保证）。
    """
    if result.metadata.coord_system == CoordSystem.WGS84:
        return result  # 大多数情况走这里，零开销

    # GCJ-02 → WGS84 批量转换
    # 1. 提取所有 (lon, lat) 为 numpy 数组
    # 2. xyconvert.gcj2wgs(coords) 批量转换
    # 3. 创建新的 Trackpoint 列表（frozen，不能改旧的）
    # 4. 更新 metadata.coord_system = WGS84
    # 5. 同步转换 simplified_track 中的坐标
    # 6. 返回新的 ParseResult
```

### 5.4 性能

- xyconvert 使用 NumPy 向量化，50000 个点的转换 < 10ms
- 转换精度 < 0.5 米，远在 50m 匹配容差之内

---

## 6. 通用计算工具

### 6.1 geo_math.py — 地理计算

从现有 `gpx_parser.py` 抽出的纯函数：

```python
def haversine(lat1, lon1, lat2, lon2) -> float:
    """两点球面距离（米）"""

def calculate_elevation_gain(trackpoints: list[Trackpoint], threshold: float = 2.0) -> float:
    """累计爬升（米），去噪阈值默认 2m"""

def calculate_speed(tp_prev: Trackpoint, tp_curr: Trackpoint) -> float | None:
    """两点间速度（m/s），异常值 > 33.3 m/s（120km/h）返回 None"""

def calculate_cumulative_distances(trackpoints: list[Trackpoint]) -> list[float]:
    """逐点累计距离（米），用于 GPX 数据补算 distance 字段"""
```

### 6.2 stats_calculator.py — 统计计算

从现有 `gpx_parser.py` 抽出的纯函数：

```python
def calculate_summary(trackpoints: list[Trackpoint], weight: float = 70.0) -> ActivitySummary:
    """从 trackpoints 计算完整统计摘要（GPX 专用，FIT/Strava 自带摘要不走这里）"""

def calculate_splits(trackpoints: list[Trackpoint], split_km: float = 10.0) -> list[dict]:
    """每 N km 分段统计"""

def calculate_calories(avg_power: float | None, duration: int, weight: float) -> float | None:
    """卡路里估算：有功率用功率公式，无功率用 MET 法"""
```

---

## 7. Worker 改造（activity/worker.py）

### 7.1 改动范围

Worker 是翻译层的唯一消费方。改动最小化：只改"调哪个解析器"和"怎么读结果"。

### 7.2 变更点

```python
# 旧代码（worker.py 内）
from app.activity.gpx_parser import parse_gpx
result = parse_gpx(content, weight=user.weight)
activity.distance = result["distance"]
# ...

# 新代码
from app.parsing.gpx_parser import GPXParser
from app.parsing.fit_parser import FITParser
from app.parsing.coord_normalizer import normalize

# 根据文件类型选择解析器
if file_ext == ".fit":
    parser = FITParser()
else:
    parser = GPXParser()

result = parser.parse(content, weight=user.weight)
result = normalize(result)  # 坐标归一化

# 读取统一格式
activity.distance = result.summary.distance
activity.avg_speed = result.summary.avg_speed * 3.6  # m/s → km/h（存入 DB 仍用 km/h）
# ...
```

### 7.3 Trackpoint 写入变更

新增 speed 和 distance 列的写入：

```python
tp_obj = TrackpointModel(
    activity_id=activity_id,
    seq=tp.seq,
    latitude=tp.lat,
    longitude=tp.lon,
    elevation=tp.ele,
    timestamp=tp.time,
    heart_rate=tp.hr,
    cadence=tp.cad,
    power=tp.power,
    speed=tp.speed,          # 新增：m/s
    distance=tp.distance,    # 新增：累计米
    geom=f"SRID=4326;POINT({tp.lon} {tp.lat})",
)
```

---

## 8. 数据库变更

### 8.1 Trackpoint 表新增列（Alembic 迁移）

```sql
ALTER TABLE trackpoints ADD COLUMN speed FLOAT;        -- 速度（m/s）
ALTER TABLE trackpoints ADD COLUMN distance FLOAT;     -- 累计距离（米）
```

- 两列均可为 NULL（老数据兼容）
- 不加索引（这两列不参与查询条件，只用于 API 输出）

### 8.2 Activity 表变更

新增字段：

```sql
ALTER TABLE activities ADD COLUMN normalized_power FLOAT;   -- 标准化功率（NP），FIT 自带
ALTER TABLE activities ADD COLUMN data_source VARCHAR(20);  -- 数据来源：gpx / fit / strava
```

### 8.3 上传接口变更

`upload_gpx` → `upload_ride`：接受 .gpx 和 .fit 文件。

文件类型校验：
- `.gpx`：Content-Type `application/gpx+xml` 或 `text/xml`
- `.fit`：Content-Type `application/octet-stream`（二进制）
- 文件大小上限不变：50MB
- 轨迹点上限不变：50000

---

## 9.（已迁移至第 2 期设计 → 6.4 节）

---

## 10. 前端地图坐标转换（第 3 期预留）

### 10.1 问题

微信小程序 map 组件强制使用 GCJ-02 坐标系。
数据库存的是 WGS84。直接显示会偏移 100-600 米。

### 10.2 方案

在时序 API 或轨迹 API 中增加可选参数 `coord=gcj02`：

```
GET /api/activities/{id}/timeseries?points=500&coord=gcj02
```

后端用 xyconvert 批量转换后返回。前端无需感知坐标系差异。

---

## 11. 任务拆分与开发顺序

### 第 1 期：翻译层（本期）

| 任务 | 描述 | 依赖 | 预估改动 |
|------|------|------|---------|
| 5.1 | types.py — 定义 Trackpoint, ParseResult 等数据结构 | 无 | 新文件 |
| 5.2 | geo_math.py — 从 gpx_parser 抽出地理计算工具 | 无 | 新文件 |
| 5.3 | stats_calculator.py — 从 gpx_parser 抽出统计计算 | 5.2 | 新文件 |
| 5.4 | GPX 解析器重构 — 迁移到 parsing/，输出 ParseResult | 5.1, 5.2, 5.3 | 重构 |
| 5.5 | coord_normalizer.py — 坐标系检测 + GCJ-02→WGS84 转换 | 5.1 | 新文件 |
| 5.6 | Trackpoint 表 Alembic 迁移 — 新增 speed, distance 列 | 无 | 迁移脚本 |
| 5.7 | Worker 改造 — 调用新的 parsing 模块 | 5.4, 5.5, 5.6 | 小改 |
| 5.8 | FIT 解析器 — 实现 fit_parser.py | 5.1, 5.2 | 新文件 |
| 5.9 | 上传接口改造 — 支持 .fit 文件上传 | 5.7, 5.8 | 小改 |
| 5.10 | 翻译层测试 — 单元测试 + 集成测试 | 5.1-5.9 | 新文件 |

### 第 2 期：Strava 集成（下一期）

| 任务 | 描述 | 依赖 |
|------|------|------|
| 6.1 | Strava OAuth 接入 — 用户授权流程 | 第 1 期完成 |
| 6.2 | Strava API 客户端 — 封装请求 + 限流 | 6.1 |
| 6.3 | Strava 适配器 — from_streams() 实现 | 5.1（types.py） |
| 6.4 | 导入调度器 — 三层渐进策略 + 轮转 + 断点续传 | 6.2, 6.3 |
| 6.5 | Webhook 接收 — 新活动自动导入 | 6.2 |
| 6.6 | 导入进度 API — 前端显示"导入中 50%" | 6.4 |
| 6.7 | Strava 集成测试 | 6.1-6.6 |

### 第 3 期：事件通知 + 地图

（暂不详细拆分，等第 1-2 期完成后再设计）

---

# 第 2 期详细设计：Strava 集成

> 以下设计与上方任务 6.1-6.7 一一对应。
> 编码时按任务号找对应小节即可。
> 第 4 章（Strava 适配器）和第 9 章（导入调度器）是第 1 期已有的设计，
> 此处不重复，只标注引用位置。
>
> **设计决策记录（2026-04-15，Starsky 确认）：**
> - users 表直接加 4 列存 Strava token（不新建关联表）
> - 开发阶段 OAuth 用浏览器手动跑通，小程序 UI 等 ICP 后再做
> - Token 刷新用"调用前检查"策略，不用定时任务
> - Webhook + 手动同步双保险（香港服务器有公网 HTTPS，无阻塞）
> - 解绑功能后面再做，先跑通绑定 + 导入

## 6.1 设计：Strava OAuth 接入

### 数据库变更

```sql
-- users 表新增 4 列
ALTER TABLE users ADD COLUMN strava_athlete_id BIGINT UNIQUE;     -- Strava 用户 ID
ALTER TABLE users ADD COLUMN strava_access_token VARCHAR(255);     -- API 访问令牌
ALTER TABLE users ADD COLUMN strava_refresh_token VARCHAR(255);    -- 刷新令牌
ALTER TABLE users ADD COLUMN strava_token_expires_at TIMESTAMP;    -- 令牌过期时间（UTC）

-- activities 表新增 1 列
ALTER TABLE activities ADD COLUMN strava_activity_id BIGINT UNIQUE;  -- Strava 活动 ID（去重用）

-- 新建 strava_imports 表（schema 见第 9.5 节）
```

- 所有列 nullable：未绑定 Strava 的用户这些字段为 NULL
- strava_athlete_id 加 UNIQUE：一个 Strava 账号只能绑定一个系统用户

### OAuth 授权流程

```
用户点"连接 Strava"
    │
    ▼
后端 GET /api/strava/authorize
    → 生成 Strava 授权 URL（含 client_id + redirect_uri + scope）
    → 返回 URL 给前端
    │
    ▼
用户在浏览器打开 URL → 登录 Strava → 点"授权"
    │
    ▼
Strava 带着 code 跳回 redirect_uri
    → GET /api/strava/callback?code=xxx
    │
    ▼
后端用 code 调 Strava API 换 token
    → POST https://www.strava.com/oauth/token
    → 拿到 access_token + refresh_token + expires_at + athlete.id
    │
    ▼
后端把 token 写入 users 表
    → 同时创建 strava_imports 记录（status='active'，启动历史导入）
```

### API 端点

```python
# 生成授权 URL（前端调用，拿到 URL 后引导用户跳转）
GET /api/strava/authorize
→ 返回 {"authorize_url": "https://www.strava.com/oauth/authorize?..."}

# 授权回调（Strava 跳回时调用，浏览器直接访问）
GET /api/strava/callback?code=xxx&scope=xxx
→ 用 code 换 token → 写入 DB → 返回 HTML 页面（"授权成功，请返回小程序"）

# 查询绑定状态（前端轮询用）
GET /api/strava/status
→ 返回 {"connected": true/false, "athlete_id": 12345}
```

### Token 刷新策略

```python
def _ensure_valid_token(db, user) -> str:
    """
    每次调 Strava API 前调用。
    检查 access_token 是否过期，过期则用 refresh_token 刷新。
    Strava access_token 有效期 6 小时。
    """
    if user.strava_token_expires_at > now():
        return user.strava_access_token

    resp = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": settings.STRAVA_CLIENT_ID,
        "client_secret": settings.STRAVA_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": user.strava_refresh_token,
    })
    user.strava_access_token = resp["access_token"]
    user.strava_refresh_token = resp["refresh_token"]
    user.strava_token_expires_at = resp["expires_at"]
    db.commit()
    return user.strava_access_token
```

### 配置项

```python
# app/config.py 新增
STRAVA_CLIENT_ID: str          # Strava API 应用 ID
STRAVA_CLIENT_SECRET: str      # Strava API 密钥
STRAVA_REDIRECT_URI: str       # 回调地址（开发：localhost，生产：域名）
```

### scope 权限

`scope=read,activity:read`（读取用户信息 + 活动数据，不需要写入权限）

---

## 6.2 设计：Strava API 客户端

### 职责

封装所有 Strava API 请求，统一处理认证、限流、重试、错误。
好比"外交官"：所有和 Strava 的交流都通过它。

### 文件位置

`app/strava/client.py`

### 核心接口

```python
class StravaClient:
    """Strava API 客户端。每个请求自动带 token、检查限流、处理错误。"""

    def __init__(self, db, user):
        self.db = db
        self.user = user

    def get_athlete_activities(self, page=1, per_page=30) -> list[dict]:
        """获取活动列表（第一层：骨架信息）"""

    def get_activity_detail(self, activity_id: int) -> dict:
        """获取活动详情（第二层：完整摘要）"""

    def get_activity_streams(self, activity_id: int) -> dict:
        """获取活动轨迹流（第三层：逐点数据）"""
```

### 限流策略

```python
# 调用前主动检查，不等 429 再停
# 用 Redis 计数器实现滑动窗口
DAILY_LIMIT = 1000          # 全 App 每天 1000 次
WINDOW_15MIN_LIMIT = 200    # 全 App 每 15 分钟 200 次
```

### 错误处理

| HTTP 状态码 | 含义 | 处理 |
|------------|------|------|
| 200 | 成功 | 正常返回 |
| 401 | Token 失效 | 尝试刷新，刷新失败则标记需重新授权 |
| 403 | 权限不足 | 记录日志，跳过 |
| 404 | 活动不存在 | 跳过（用户可能删了） |
| 429 | 限流 | 停止当前批次，等下一个窗口 |
| 500+ | Strava 服务端错误 | 重试 1 次，仍失败则跳过 |

---

## 6.3 设计：Strava 适配器（parsing/strava_adapter.py）

### 职责

不解析文件，而是将 Strava API 返回的 JSON 转换为 ParseResult。

### 核心流程

```python
def from_streams(
    streams: dict,              # Strava Streams API 返回的 JSON
    activity_detail: dict,      # Strava Activity Detail API 返回的 JSON
) -> ParseResult:
    """
    Strava 适配器入口。

    Strava 的数据结构是"并行数组"——所有 stream 等长、按索引对齐。
    我们需要按索引遍历，把并行数组"旋转"成逐点的 Trackpoint 列表。
    """
    # 1. 从 streams 取各数组：
    #    time[], distance[], latlng[][], altitude[],
    #    velocity_smooth[], heartrate[], cadence[], watts[]
    # 2. 计算绝对时间戳：activity_detail.start_date + time[i] 秒
    # 3. 按索引遍历，生成 Trackpoint 列表：
    #    - lat, lon: latlng[i][0], latlng[i][1]
    #    - speed: velocity_smooth[i]（已是 m/s）
    #    - distance: distance[i]（已是累计米）
    #    - 可选字段不存在则为 None
    # 4. 从 activity_detail 取摘要（Strava 已算好的）：
    #    - distance, moving_time, elapsed_time
    #    - average_speed（m/s）, max_speed（m/s）
    #    - average_watts, max_watts
    #    - average_heartrate, max_heartrate
    #    - average_cadence
    #    - calories, total_elevation_gain
    # 5. 坐标系：Strava 返回 WGS84（但原始来源不确定，见下文）
    # 6. 组装 ParseResult 返回
```

### 坐标系风险

Strava 本身存储 WGS84，但如果用户的 Strava 活动原始来源是中国手机 App
（行者、Keep 等），那坐标可能已经是 GCJ-02 被当作 WGS84 存储了。

**处理策略**：默认标记为 WGS84，如果匹配时发现系统性偏移，再人工标记。
这是已知的不完美折衷，完美方案成本远超 MVP 收益。

---

## 6.4 设计：导入调度器（strava/import_scheduler.py）

### API 限额约束

| 约束 | 值 | 说明 |
|------|---|------|
| 每日读取上限 | 1000 次/天 | **全 App 共享**，不是 per-user |
| 15 分钟读取上限 | 200 次/15min | 短期限流 |
| 每条活动导入成本 | 2 次 | 详情 1 次 + 轨迹流 1 次 |
| 列表查询成本 | 1 次/30 条 | 分页，每页 30 条 |

### 预算分配

| 预算 | 分配 | 说明 |
|------|------|------|
| 日常操作预留 | 200 次/天 | 新上传触发的 Strava 同步等 |
| 历史导入预算 | 800 次/天 | 最多导入 400 条活动/天 |

### 三层渐进策略

```
第一层（列表）：
    - 调用 GET /athlete/activities?per_page=30
    - 成本低：500 条只需 17 次调用
    - 用户立刻看到活动列表（骨架信息：名称、日期、距离）
    
第二层（摘要）：
    - 调用 GET /activities/{id}
    - 每条 1 次调用
    - 用户看到完整卡片（统计数据、速度、功率等）
    
第三层（轨迹）：
    - 调用 GET /activities/{id}/streams?keys=...&key_by_type=true
    - 每条 1 次调用
    - 赛段匹配开始工作
    - 可跳过：非骑行活动、距离 < 5km、远离所有赛段的活动
```

### 多用户调度

采用**轮转制**：多个用户同时导入时，按"一人一条"轮转，
确保每个用户持续看到进度，而不是一个人占满额度。

### 进度持久化

```sql
CREATE TABLE strava_imports (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    strava_athlete_id BIGINT NOT NULL,
    total_activities INTEGER,           -- Strava 上的总活动数
    tier1_completed INTEGER DEFAULT 0,  -- 已完成第一层
    tier2_completed INTEGER DEFAULT 0,  -- 已完成第二层
    tier3_completed INTEGER DEFAULT 0,  -- 已完成第三层
    tier3_skipped INTEGER DEFAULT 0,    -- 第三层跳过的（非骑行等）
    last_activity_id BIGINT,            -- 当前处理到的活动
    status VARCHAR(20) DEFAULT 'active', -- active / paused / completed
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

服务器重启后，从 `last_activity_id` 继续，不丢进度不重复拉取。

### 调度算法

```
每 30 秒执行一次：
    1. 检查 15 分钟窗口剩余额度
    2. 检查当天剩余额度
    3. 如果额度 = 0 → 等待
    4. 从所有 status='active' 的导入任务中，轮转选一个用户
    5. 根据该用户的进度，选最高优先级的层级任务
       优先级：第一层 > 第二层（最新的先）> 第三层（最新的先）
    6. 执行一次 API 调用
    7. 更新进度
    8. 如果全部完成 → status = 'completed'
```

---

## 6.5 设计：Webhook + 手动同步

### Webhook 订阅（一次性设置）

```bash
# 用 curl 手动执行一次，注册 Webhook 订阅
POST https://www.strava.com/api/v3/push_subscriptions
  client_id=xxx
  client_secret=xxx
  callback_url=https://你的域名/api/strava/webhook
  verify_token=自定义密钥
```

### Webhook 验证端点

```python
GET /api/strava/webhook?hub.mode=subscribe&hub.challenge=abc123&hub.verify_token=xxx
→ 校验 verify_token → 返回 {"hub.challenge": "abc123"}
```

### Webhook 事件接收

```python
POST /api/strava/webhook
Body: {"object_type": "activity", "aspect_type": "create",
       "object_id": 12345678, "owner_id": 87654321, ...}
```

| object_type | aspect_type | 处理 |
|-------------|-------------|------|
| activity | create | 找到系统用户 → 入队列拉取详情+轨迹 |
| activity | update | 同上（覆盖更新） |
| activity | delete | 删除对应 Activity 记录 |
| athlete | update | 忽略 |
| athlete | delete | 用户撤销授权 → 清除 Strava token |

幂等性：用 strava_activity_id 去重。

### 手动同步端点

```python
POST /api/strava/sync
→ JWT 登录 → 拉取最近 30 条活动 → 新活动入队列
→ 返回 {"new_activities": 3, "message": "发现 3 条新骑行，正在导入"}
```

---

## 6.6 设计：导入进度 API

### 端点

```python
GET /api/strava/import-progress
→ JWT 登录 → 返回当前用户的导入进度
```

### 响应格式

```json
{
    "status": "active",
    "total_activities": 500,
    "tier1_completed": 500,
    "tier2_completed": 120,
    "tier3_completed": 45,
    "tier3_skipped": 30,
    "percent": 24,
    "message": "正在导入详情，已完成 120/500"
}
```

---

## 附录 A：坐标系速查表

| 数据来源 | 坐标系 | 需要转换？ |
|---------|--------|-----------|
| Garmin 码表 GPX/FIT | WGS84 | 不需要 |
| Wahoo 码表 GPX/FIT | WGS84 | 不需要 |
| iGPSport 码表 GPX/FIT | WGS84 | 不需要 |
| Magene 码表 GPX/FIT | WGS84 | 不需要 |
| Bryton 码表 GPX/FIT | WGS84 | 不需要 |
| Strava Streams API | WGS84 | 不需要（原始来源未知时有风险） |
| 行者 App 导出 GPX | GCJ-02 | 需要 → WGS84 |
| Keep App 导出 GPX | GCJ-02 | 需要 → WGS84 |
| 咕咚 App 导出 GPX | GCJ-02 | 需要 → WGS84 |
| 华为运动健康导出 | GCJ-02（大陆）| 需要 → WGS84 |
| 腾讯地图画线创建赛段 | GCJ-02 | 需要 → WGS84 |

## 附录 B：单位速查表

| 字段 | 翻译层内部 | 数据库存储 | API 返回 | 前端显示 |
|------|-----------|-----------|---------|---------|
| 距离 | 米 | 米 | 公里 | 公里 |
| 速度 | **m/s** | **m/s** | km/h | km/h |
| 海拔 | 米 | 米 | 米 | 米 |
| 心率 | bpm | bpm | bpm | bpm |
| 踏频 | rpm | rpm | rpm | rpm |
| 功率 | W | W | W | W |
| 时间 | 秒 | 秒 | 秒 | hh:mm:ss |
| 温度 | °C | °C | °C | °C |

> **注意**：速度单位从 v1 的 km/h 改为 v2 的 m/s（内部和数据库）。
> 这意味着 Activity 表的 avg_speed、max_speed 列在 v2 之后存的是 m/s。
> API 层做 ×3.6 转换，前端不感知变化。
> 老数据（v1）的 avg_speed 是 km/h，需要在 API 层兼容处理。

## 附录 C：FIT 坐标转换公式

```python
# FIT semicircles → 经纬度（度）
degrees = semicircles * (180.0 / 2**31)

# FIT 海拔（raw → 米），仅当使用旧版 altitude 字段时
altitude_meters = (raw_value / 5) - 500

# FIT 速度（raw → m/s），仅当使用旧版 speed 字段时
speed_ms = raw_value / 1000

# Garmin epoch → Unix epoch
unix_timestamp = garmin_timestamp + 631065600
```

> garmin-fit-sdk 开启 `apply_scale_and_offset=True` 后，
> 海拔和速度自动转换，但坐标仍需手动转换。
