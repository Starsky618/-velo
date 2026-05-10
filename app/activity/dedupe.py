"""
GPX 重复检测算法（Sprint 5 task-2 / Day 1）。

干啥用：
- 一个用户传同一条骑行的两个不同导出（GPX 直传 vs Strava 同步），
  字节级 SHA-256 file_hash 不一样所以现有去重漏判，本模块做"语义级 dedupe"。
- 4 维 activity signature 比对：起骑时间 / 总距离 / 总时长 / 起点 GPS 坐标。
  全在容差内 → 视为同一骑行（一定是同一次的两份记录，不可能是巧合）。
- 比 score 决定哪个数据更全（带功率/心率/踏频/数据点更多的留），
  另一份标 duplicate_of 隐藏（不删 / 留 audit）。

操作注意（关键设计）：
- **纯函数模块 / 不碰 DB 不碰文件系统**：只接收参数返回结果，DB 读写在 service 层。
  类比 segment/matcher.py、parsing/gpx_parser.py 的风格（CLAUDE.md "纯函数规则"段）
- **4 维全过才算重复**：任一超容差 = 不同骑行 = 立即返 False（短路省算）
- **容差从 GPS / 设备物理误差推导**，不是拍脑袋：
  - time 5min：GPS 时钟漂移 + 设备开停时间差 + Strava 同步上报偏移
  - distance 100m：GPS 累计误差（10km ~50m / 50km ~200m）
  - duration 60s：开停时机
  - start 100m：首次定位 fix 慢
- **completeness score 不是相同骑行内"哪条更准"，是"哪份导出数据更全"**。
  如：Strava 同步带功率心率 + 自动计算（score 高），用户后传 GPX 只有轨迹（score 低）→ 留 Strava 那条。

数据流：
- 入：两个 ActivitySig（datetime + distance + duration + 起点 lat/lon）
- 中：4 维比对（短路）
- 出：bool（是否潜在重复）
- 评分入：ActivityScoreData（avg_power/hr/cadence + trackpoint_count）
- 评分出：float（高的保留）

部署：service 层 caller（如 worker.py parse_activity）查 DB candidates → 构造 ActivitySig → 调本模块。
"""

from dataclasses import dataclass
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from typing import Optional


# ============================================================
# 数据结构 — 纯输入，不依赖 SQLAlchemy ORM
# ============================================================


@dataclass(frozen=True)
class ActivitySig:
    """
    activity 的 dedupe 关键签名。

    刻意不绑 ORM —— service 层从 Activity 模型构造，
    本模块只看 5 个原始字段。这样测试可注入任意场景，不需要 DB。

    类比身份证号 + 出生年月 + 户籍地 —— 多维度组合识别"同一个人不同照片"。
    """

    started_at: datetime  # 起骑时间（必须 tz-aware UTC / CLAUDE.md 陷阱 #2）
    distance: float       # 总距离（米）
    duration: int         # 总时长（秒）
    start_lat: float      # 起点纬度
    start_lon: float      # 起点经度


@dataclass(frozen=True)
class ActivityScoreData:
    """
    activity 的数据完整度信息（用于决定 duplicate 保留哪份）。

    Strava 同步带传感器（功率/心率/踏频）→ score 高 → 留。
    用户后传简化 GPX 只有轨迹 → score 低 → 标 duplicate_of。
    """

    avg_power: Optional[float] = None       # 平均功率（W），无功率计为 None
    avg_hr: Optional[float] = None          # 平均心率（bpm），无心率带为 None
    avg_cadence: Optional[float] = None     # 平均踏频（rpm），无踏频感应为 None
    trackpoint_count: int = 0                # 简化后的 trackpoint 数（数据密度）


# ============================================================
# 容差常量 — 集中定义，方便未来按真实数据调
# ============================================================


# 时间容差：5 分钟
# Why：GPS 时钟漂移（普通设备 ±2s/天）+ 设备开/停时间差（用户先按开始 1-2 分钟才骑）
#      + Strava 同步从设备到云的上报时间差（几秒到几十秒）
# 类比家里时钟：墙上钟 vs 微波炉钟 vs 手机钟，差几分钟正常
DEFAULT_TIME_TOLERANCE_SEC = 300

# 距离容差：100 米
# Why：GPS 累计误差与距离正相关（10km 骑 ~50m / 50km 骑 ~200m），100m 折中。
#      不同导出格式可能 simplify 不同精度，导致总距离略差
DEFAULT_DISTANCE_TOLERANCE_M = 100.0

# 时长容差：60 秒
# Why：用户开/停 GPS 时机差异（先到达再按停 vs 没下车就按停）
DEFAULT_DURATION_TOLERANCE_SEC = 60

# 起点距离容差：100 米
# Why：设备首次定位 fix 慢（冷启动 30s-2min），第一个点漂移大
DEFAULT_START_TOLERANCE_M = 100.0


# 地球半径（米） / 用于 haversine
EARTH_RADIUS_M = 6_371_000.0


# ============================================================
# 核心函数
# ============================================================


def haversine_meters(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """
    球面两点距离（米）/ haversine 公式。

    设计思路：
    - 输入 (lat, lon) tuple，单位为度
    - 输出米 / 不输出度（避免 ST_DWithin 类陷阱 / CLAUDE.md 陷阱 #6）
    - 地球简化为球（大圆距离），1km 内误差 < 0.5%，对 dedupe 起点比对足够

    类比测两个城市的直线距离 —— 不绕公路，只算"飞过去多远"。

    参数：
        p1, p2: (latitude, longitude) tuple，度

    返回：
        距离（米）
    """
    lat1, lon1 = radians(p1[0]), radians(p1[1])
    lat2, lon2 = radians(p2[0]), radians(p2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return EARTH_RADIUS_M * c


def is_potential_duplicate(
    a: ActivitySig,
    b: ActivitySig,
    *,
    time_tol_sec: int = DEFAULT_TIME_TOLERANCE_SEC,
    distance_tol_m: float = DEFAULT_DISTANCE_TOLERANCE_M,
    duration_tol_sec: int = DEFAULT_DURATION_TOLERANCE_SEC,
    start_tol_m: float = DEFAULT_START_TOLERANCE_M,
) -> bool:
    """
    4 维 signature 比对 / 全在容差内 → 视为重复。

    设计思路：
    - 4 维全过才算重复 —— 任一超容差 = 不同骑行 = 立即返 False（短路）
    - 4 维独立坐标系：时间（when）+ 长度（how long）+ 时长（how much）+ 位置（where）
      四维同时碰撞才能造成"巧合"，单一维度撞车（如同一时间起骑但不同地）不算
    - 容差是默认值 / caller 可按场景调（如赛事场景容差更紧）

    类比身份核验 —— 名字、生日、户籍、照片，对上才算同一人；
    单"名字一样"是巧合（重名），单"生日一样"也是巧合，组合极小概率。

    参数：
        a, b: 两个 ActivitySig
        time_tol_sec / distance_tol_m / duration_tol_sec / start_tol_m: 各维容差

    返回：
        True = 4 维全在容差内 = 视为同一骑行的两份记录
        False = 任一维超容差 = 不同骑行
    """
    # 第 1 维：时间（最便宜的判断 / 大部分非重复都被这里短路掉）
    time_diff = abs((a.started_at - b.started_at).total_seconds())
    if time_diff > time_tol_sec:
        return False

    # 第 2 维：总距离
    if abs(a.distance - b.distance) > distance_tol_m:
        return False

    # 第 3 维：总时长
    if abs(a.duration - b.duration) > duration_tol_sec:
        return False

    # 第 4 维：起点 GPS 距离（最贵的判断 / 留最后）
    start_dist = haversine_meters(
        (a.start_lat, a.start_lon),
        (b.start_lat, b.start_lon),
    )
    if start_dist > start_tol_m:
        return False

    return True


def compute_completeness_score(d: ActivityScoreData) -> float:
    """
    活动数据完整度评分 / 重复时高分留、低分标 duplicate_of。

    设计思路：
    - 三个传感器（功率 / 心率 / 踏频）各 1 分 —— 有 = +1，无 = 0
    - trackpoint_count 折算分（密度奖励）：每 1000 点 +1，封顶 5 分
      防止超长骑行（10000+ 点）单一维度统治评分
    - 合计 0 ~ 8 分（理论最高 = 3 传感器 + 5 数据密度）

    类比体检报告 —— 项目越多越完整，但单项无限叠加不再加分。

    参数：
        d: ActivityScoreData

    返回：
        float 评分（数值越大数据越全）
    """
    score = 0.0
    if d.avg_power is not None:
        score += 1
    if d.avg_hr is not None:
        score += 1
    if d.avg_cadence is not None:
        score += 1
    score += min(d.trackpoint_count / 1000, 5)
    return score
