"""
GPX 解析器（v2）——"第一个翻译官"。

把骑行码表导出的 GPX 文件（XML 格式）翻译成统一的 ParseResult 格式。
这是从 activity/gpx_parser.py 搬过来并升级的版本。

主要升级点（对比旧版 activity/gpx_parser.py）：
- 输出从 dict 变为 ParseResult（frozen dataclass），下游统一消费
- 新增逐点 speed（m/s）和 distance（累计米）字段
- 地理计算调用 geo_math.py（不再内嵌）
- 统计摘要调用 stats_calculator.py（不再内嵌）
- 新增坐标系检测（读 GPX <creator> 字段，查 GCJ-02 映射表）

数据流：
  GPX 字节流 → XML 解析 → 提取原始点 → 逐点计算 speed/distance
  → 创建 Trackpoint 列表 → stats_calculator 算摘要
  → simplify_track 简化轨迹 → 组装 ParseResult

注意事项：
- 纯函数模块，不碰数据库、不碰文件系统
- 轨迹点上限 50000（内存保护）
- GPS 漂移检测：速度 > 120km/h 的段不计入距离
- 坐标系检测只影响 metadata 标记，实际转换由 coord_normalizer 完成
"""

from datetime import timedelta, timezone

import gpxpy
import gpxpy.gpx

from app.activity.power_zones import calculate_power_zones
from app.activity.simplify import simplify_track
from app.parsing.geo_math import haversine, MAX_SPEED_MS
from app.parsing.stats_calculator import calculate_summary
from app.parsing.types import (
    CoordSystem,
    DataSource,
    ParseMetadata,
    ParseResult,
    Trackpoint,
)


# 北京时区（UTC+8）/ 中国主用户群假设
# Sprint 5 task-2 day 1 部署 verify 发现 GPX timezone bug：
# 326 GPX 上传 started_at 19:40:23+00 / Strava 同骑行 11:40:23+00 = 差 8h
# 根因：GPX 文件 trkpt timestamp 不带时区 / gpxpy 解析后是 naive datetime /
# SQLAlchemy 把 naive 当 UTC 直接存 → 实际是北京时间被错误标记 UTC。
# 修法：parser 内 normalize naive → 假设北京时间 → astimezone(UTC)
BEIJING_TZ = timezone(timedelta(hours=8))


# ==================== 常量 ====================

# 轨迹点数量上限（内存保护：50000 点 × ~200 字节/点 ≈ 10MB）
_MAX_TRACKPOINTS = 50000

# 已知使用 GCJ-02 坐标系的 GPX creator（持续维护，遇到新 App 就加）
# 所有码表硬件（佳明/iGPSport/迈金/Wahoo/Bryton）都是 WGS84，
# 只有中国手机 App 导出的 GPX 可能是 GCJ-02
_GCJ02_CREATORS = {
    "xingzhe",          # 行者
    "keep",             # Keep
    "codoon",           # 咕咚
    "huawei health",    # 华为运动健康（大陆版）
    "两步路",           # 两步路户外
}

# 传感器数据的 XML 标签名候选列表
# 不同品牌码表用不同的标签名，列出常见的候选
_HR_TAGS = ["hr", "heartrate", "HeartRate"]
_CAD_TAGS = ["cad", "cadence", "Cadence"]
_POWER_TAGS = ["power", "Power", "watts", "Watts", "pwr"]


# ==================== 异常类 ====================


class GPXParseError(Exception):
    """GPX 解析失败时的自定义异常"""
    pass


# ==================== 核心类 ====================


class GPXParser:
    """
    GPX 翻译官——把 GPX 文件翻译成统一的 ParseResult 格式。

    遵循 RideParser Protocol 接口：parse(content, **kwargs) -> ParseResult。
    不需要显式继承，只要方法签名匹配就行（鸭子类型）。
    """

    def parse(self, content: bytes, **kwargs) -> ParseResult:
        """
        解析 GPX 文件，返回统一格式的 ParseResult。

        参数：
            content: GPX 文件字节流
            **kwargs:
                weight (float): 骑行者体重（kg），默认 70，用于卡路里估算
                ftp (int): 用户 FTP（功能阈值功率），有值时计算功率区间
                file_hash (str): 文件 SHA-256 哈希，由上传接口传入

        返回：
            ParseResult — 统一格式的解析结果（坐标可能是 GCJ-02，
            由 coord_normalizer 统一转换）

        异常：
            GPXParseError: 文件格式错误、无轨迹数据、轨迹点过多
        """
        weight = kwargs.get("weight", 70.0)
        ftp = kwargs.get("ftp")
        file_hash = kwargs.get("file_hash")

        # ===== 1. XML 解析 =====
        text = _decode_content(content)
        try:
            gpx = gpxpy.parse(text)
        except Exception:
            raise GPXParseError("文件格式错误")

        # ===== 2. 提取原始轨迹点 =====
        raw_points = []
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    raw_points.append(point)

        if not raw_points:
            raise GPXParseError("文件无轨迹数据")

        if len(raw_points) > _MAX_TRACKPOINTS:
            raise GPXParseError(
                f"轨迹点过多（{len(raw_points)}），上限 {_MAX_TRACKPOINTS}"
            )

        # ===== 2.5 时区 normalize（Sprint 5 task-2 day 1 实证修）=====
        # GPX 文件 trkpt timestamp 标准是 UTC（ISO 8601 带 Z），但实际很多设备/导出工具用 local time
        # （无时区信息） → gpxpy.parse 返回 naive datetime → SQLAlchemy 把 naive 当 UTC 存 → 实际差 N 小时
        # 修法：naive → 假设北京时间（中国主用户群 100% 量级 / 海外极少）→ 转 UTC
        #      aware → 标准化到 UTC（防 +08:00 直接进 DB 后再比较时被 SQLAlchemy 当 UTC 误判）
        # 实证：326 上传时 started_at 错存 19:40:23+00 / Strava 同骑行 103 是 11:40:23+00（真 UTC）
        # → 时差 8h / dedupe 算法 5min 容差外漏判
        _normalize_naive_times_to_utc(raw_points)

        # ===== 3. 提取元数据 =====
        creator = gpx.creator if hasattr(gpx, "creator") else None
        coord_system = _detect_coord_system(creator)
        title = (gpx.tracks[0].name
                 if gpx.tracks and gpx.tracks[0].name else None)

        # ===== 4. 构建 Trackpoint 列表（含 speed/distance）=====
        trackpoints = _build_trackpoints(raw_points)

        # ===== 5. 计算统计摘要 =====
        summary = calculate_summary(trackpoints, weight=weight)

        # ===== 6. 轨迹简化（simplify_track 期望 list[dict]）=====
        tp_dicts_for_simplify = [
            {"lat": tp.lat, "lon": tp.lon, "ele": tp.ele}
            for tp in trackpoints
        ]
        simplified = simplify_track(tp_dicts_for_simplify)

        # ===== 7. 功率区间（可选，需要 ftp）=====
        power_zones = None
        if ftp and ftp > 0:
            # calculate_power_zones 期望 list[dict]，需要 power 和 time
            tp_dicts_for_pz = [
                {"power": tp.power, "time": tp.time}
                for tp in trackpoints
            ]
            power_zones = calculate_power_zones(tp_dicts_for_pz, ftp)

        # ===== 8. 组装元数据 =====
        metadata = ParseMetadata(
            source=DataSource.GPX,
            coord_system=coord_system,
            title=title,
            creator=creator,
            file_hash=file_hash,
        )

        # ===== 9. 组装最终结果 =====
        return ParseResult(
            trackpoints=trackpoints,
            summary=summary,
            metadata=metadata,
            simplified_track=simplified,
            power_zones=power_zones,
        )


# ==================== 内部函数 ====================


def _normalize_naive_times_to_utc(points: list) -> None:
    """
    把 gpxpy 解析出来的 trackpoint.time 标准化到 tz-aware UTC。

    设计思路：
    - GPX 文件 trkpt timestamp 标准（Topografix GPX 1.1）应是 UTC + ISO 8601 + Z 后缀，
      但实际很多设备/软件导出的是 local time（无时区）→ gpxpy 解析后是 naive datetime
    - 主用户群在中国（100% 量级），naive timestamp 假设北京时间（UTC+8）→ 转 UTC
    - 带 tzinfo 的 timestamp（aware）也 .astimezone(UTC) 标准化（防 +08:00 后续被当 UTC 误判）

    类比国际机场航班板：本地时间 vs 当地时间 vs UTC，必须统一显示语种才能比较。

    踩坑实证（2026-05-11 / Sprint 5 task-2 day 1 部署 verify）：
    - 326 上传 started_at 19:40:23+00 / Strava 同骑行 103 是 11:40:23+00（真 UTC）
    - 时差 8h / dedupe 算法 5min 容差外漏判 / 326 误判为独立活动
    - 跟 task-0.1（DB 列 tz-aware）配合：DB 列已正确 / 但数据进 DB 前没 normalize
    """
    for p in points:
        if p.time is None:
            continue
        if p.time.tzinfo is None:
            # naive → 假设北京时间（中国主用户群 / 海外用户极少）
            p.time = p.time.replace(tzinfo=BEIJING_TZ).astimezone(timezone.utc)
        else:
            # aware → 标准化到 UTC
            p.time = p.time.astimezone(timezone.utc)


def _decode_content(content: bytes) -> str:
    """
    解码 GPX 字节流为字符串，跳过可能存在的 BOM。

    BOM（Byte Order Mark）是某些编辑器/系统在文件头加的隐藏标记，
    XML 解析器遇到它可能报错，所以要先去掉。
    """
    # 跳过 UTF-8 BOM（3 字节）
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]
    return content.decode("utf-8")


def _detect_coord_system(creator: str | None) -> CoordSystem:
    """
    根据 GPX creator 字段推断坐标系。

    码表硬件（佳明/iGPSport/迈金/Wahoo/Bryton）全部输出 WGS84。
    只有中国手机 App（行者/Keep/咕咚/华为）可能输出 GCJ-02。
    未知来源默认 WGS84（安全假设：绝大多数骑行者用码表）。
    """
    if creator:
        creator_lower = creator.lower()
        for gcj_name in _GCJ02_CREATORS:
            if gcj_name in creator_lower:
                return CoordSystem.GCJ02
    return CoordSystem.WGS84


def _build_trackpoints(raw_points: list) -> list[Trackpoint]:
    """
    从 gpxpy 原始点列表构建 Trackpoint 列表，包含 speed 和 distance。

    核心逻辑：逐对相邻点计算距离和速度，累加距离，过滤 GPS 漂移。
    GPS 漂移检测：如果两点间速度 > 120km/h（33.3 m/s），
    认为是 GPS 传感器跳点，该段距离不计入累计，速度标记为 None。
    """
    trackpoints = []
    cumulative_dist = 0.0

    for i, point in enumerate(raw_points):
        # 提取传感器数据
        hr = _get_extension_value(point, _HR_TAGS)
        cad = _get_extension_value(point, _CAD_TAGS)
        power = _get_extension_value(point, _POWER_TAGS)

        speed = None
        distance = 0.0

        if i > 0:
            prev_point = raw_points[i - 1]
            seg_dist = haversine(
                prev_point.latitude, prev_point.longitude,
                point.latitude, point.longitude,
            )

            # GPS 漂移检测：有时间戳才能算速度
            is_drift = False
            if point.time and prev_point.time:
                dt = (point.time - prev_point.time).total_seconds()
                if dt > 0:
                    seg_speed = seg_dist / dt
                    if seg_speed > MAX_SPEED_MS:
                        # 速度异常，这段距离不计入总距离
                        is_drift = True
                    else:
                        speed = seg_speed

            # 只有非漂移段才累加距离
            if not is_drift:
                cumulative_dist += seg_dist

            distance = cumulative_dist

        trackpoints.append(Trackpoint(
            seq=i,
            lat=point.latitude,
            lon=point.longitude,
            ele=point.elevation,
            time=point.time,
            hr=hr,
            cad=cad,
            power=power,
            speed=speed,
            distance=distance,
        ))

    return trackpoints


def _get_extension_value(point, tag_names: list[str]) -> int | None:
    """
    从 GPX trackpoint 的 extensions 中提取传感器数据（心率/功率/踏频）。

    不同品牌的码表用的 XML 标签名不完全一样，
    所以传入一个候选标签名列表，依次尝试匹配。
    gpxpy 已经帮我们处理了大部分命名空间问题。
    """
    if point.extensions is None:
        return None

    for ext in point.extensions:
        # 递归搜索所有子节点
        for elem in ext.iter():
            # 去掉命名空间前缀，只比较标签本名
            # 例如 "{http://ns.garmin.com}hr" → "hr"
            local_name = (
                elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            )
            if local_name in tag_names and elem.text:
                try:
                    return int(float(elem.text))
                except (ValueError, TypeError):
                    continue
    return None
