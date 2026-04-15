"""
Strava Streams 适配器——"同声传译员"。

不解析文件，而是把 Strava API 返回的 JSON 数据"翻译"成 ParseResult 标准格式。
好比联合国大会上的同声传译：演讲者说法语（Strava JSON），
传译员翻成英语（ParseResult），听众只听英语，不知道原来说的是法语。

Strava 的数据结构很特别——"并行数组"：
所有数据类型各一个等长数组，按索引对齐。好比 Excel 表：
  时间列: [0, 5, 10, 15, ...]
  距离列: [0, 50, 120, 200, ...]
  经纬列: [[30.1, 120.1], [30.2, 120.2], ...]
每一行就是一个轨迹点，本模块把这种"横着看"变成"竖着看"的 Trackpoint 列表。

注意事项：
- 这是纯函数模块，不碰数据库、不碰文件系统
- streams 参数接收 Strava API 原始 JSON（key_by_type=true 格式），
  内部自己提取 .data 数组，caller 不需要预处理
- 某些 stream key 可能不存在（如 watts 只有有功率计的骑行才有），全部用 .get() 安全访问
- 轨迹点上限 50000（与 GPX/FIT 一致），Strava 降采样上限约 10000，正常不会触发
"""

import logging
from datetime import datetime, timedelta, timezone

from app.activity.power_zones import calculate_power_zones
from app.activity.simplify import simplify_track
from app.parsing.stats_calculator import calculate_splits
from app.parsing.types import (
    ActivitySummary,
    CoordSystem,
    DataSource,
    ParseMetadata,
    ParseResult,
    Trackpoint,
)

logger = logging.getLogger(__name__)

# 轨迹点数量硬上限（与 GPX/FIT 解析器一致）
# Strava 降采样上限约 10000 点，正常不会触碰此上限
_MAX_TRACKPOINTS = 50_000


class StravaAdapterError(Exception):
    """Strava 数据转换失败时抛出。"""
    pass


def from_streams(
    streams: dict,
    activity_detail: dict,
    **kwargs,
) -> ParseResult:
    """
    Strava 适配器入口——把 Strava API 的 JSON 翻译成 ParseResult。

    参数：
        streams: Strava Streams API 返回的原始 JSON（key_by_type=true 格式）
                 格式：{"time": {"data": [...]}, "latlng": {"data": [...]}, ...}
        activity_detail: Strava Activity Detail API 返回的 JSON
        **kwargs: ftp (int|None) — 用户 FTP，用于功率区间计算

    返回：
        ParseResult（标准格式，与 GPX/FIT 解析器输出完全一致）
    """
    ftp = kwargs.get("ftp")

    # ===== 1. 提取 streams 数组（安全访问，缺失的返回 None）=====
    # 必需的三个数组：时间、距离、经纬度
    time_data = _extract_stream(streams, "time")
    distance_data = _extract_stream(streams, "distance")
    latlng_data = _extract_stream(streams, "latlng")

    if not time_data or not latlng_data or not distance_data:
        raise StravaAdapterError("Strava 数据缺少必需的 time/latlng/distance 轨迹流")

    # 可选数组：海拔、速度、心率、踏频、功率
    altitude_data = _extract_stream(streams, "altitude")
    speed_data = _extract_stream(streams, "velocity_smooth")
    hr_data = _extract_stream(streams, "heartrate")
    cad_data = _extract_stream(streams, "cadence")
    power_data = _extract_stream(streams, "watts")

    # ===== 2. 解析起始时间 =====
    start_dt = _parse_start_date(activity_detail.get("start_date"))

    # ===== 3. 构建 Trackpoint 列表 =====
    num_points = len(time_data)

    if num_points > _MAX_TRACKPOINTS:
        raise StravaAdapterError(
            f"轨迹点过多（{num_points}），上限 {_MAX_TRACKPOINTS}"
        )

    trackpoints = []
    for i in range(num_points):
        # latlng 是 [[lat, lon], [lat, lon], ...]，某些点可能缺失或值为 [None, None]
        ll = latlng_data[i] if i < len(latlng_data) else None
        if not ll or len(ll) < 2 or ll[0] is None or ll[1] is None:
            continue  # 跳过无坐标的点

        # time_data 元素可能为 None（传感器丢失），此时该点无时间戳
        t_sec = time_data[i] if i < len(time_data) else None

        tp = Trackpoint(
            seq=len(trackpoints),
            lat=float(ll[0]),
            lon=float(ll[1]),
            ele=_safe_index(altitude_data, i),
            time=(start_dt + timedelta(seconds=t_sec)
                  if start_dt and t_sec is not None else None),
            hr=_safe_int(_safe_index(hr_data, i)),
            cad=_safe_int(_safe_index(cad_data, i)),
            power=_safe_int(_safe_index(power_data, i)),
            speed=_safe_index(speed_data, i),
            distance=_safe_index(distance_data, i),
        )
        trackpoints.append(tp)

    if not trackpoints:
        raise StravaAdapterError("Strava 数据无有效轨迹点")

    # ===== 4. 组装统计摘要（Strava 已算好的，直接取）=====
    detail = activity_detail
    elapsed = detail.get("elapsed_time")

    summary = ActivitySummary(
        distance=detail.get("distance", 0.0),
        duration=elapsed,
        elevation_gain=detail.get("total_elevation_gain", 0.0),
        avg_speed=detail.get("average_speed"),
        max_speed=detail.get("max_speed"),
        avg_power=detail.get("average_watts"),
        max_power=_safe_int(detail.get("max_watts")),
        avg_hr=detail.get("average_heartrate"),
        max_hr=_safe_int(detail.get("max_heartrate")),
        avg_cadence=detail.get("average_cadence"),
        calories=detail.get("calories"),
        started_at=start_dt,
        finished_at=(start_dt + timedelta(seconds=elapsed)
                     if start_dt and elapsed is not None else None),
        splits=calculate_splits(trackpoints),
        normalized_power=detail.get("weighted_average_watts"),
    )

    # ===== 5. 轨迹简化（与 GPX 解析器一致）=====
    tp_dicts_for_simplify = [
        {"lat": tp.lat, "lon": tp.lon, "ele": tp.ele}
        for tp in trackpoints
    ]
    simplified = simplify_track(tp_dicts_for_simplify)

    # ===== 6. 功率区间（可选，需要 ftp）=====
    power_zones = None
    if ftp and ftp > 0:
        tp_dicts_for_pz = [
            {"power": tp.power, "time": tp.time}
            for tp in trackpoints
        ]
        power_zones = calculate_power_zones(tp_dicts_for_pz, ftp)

    # ===== 7. 组装元数据 =====
    metadata = ParseMetadata(
        source=DataSource.STRAVA,
        coord_system=CoordSystem.WGS84,  # Strava 返回 WGS84（已知折衷）
        title=detail.get("name"),
        creator="strava",
        file_hash=None,  # Strava 导入无文件哈希
    )

    # ===== 8. 返回 =====
    logger.info(
        "Strava 适配完成 trackpoints=%d distance=%.0f",
        len(trackpoints), summary.distance,
    )

    return ParseResult(
        trackpoints=trackpoints,
        summary=summary,
        metadata=metadata,
        simplified_track=simplified,
        power_zones=power_zones,
    )


# ==================== 内部工具函数 ====================


def _extract_stream(streams: dict, key: str) -> list | None:
    """
    从 Strava Streams JSON 中安全提取指定类型的数据数组。

    Strava 的 key_by_type=true 返回格式：
    {"time": {"data": [0, 5, 10, ...], "series_type": "...", ...}, ...}

    某些 key 可能不存在（如 watts 只有有功率计的骑行才有），
    此时返回 None 而不是报错。
    """
    stream = streams.get(key)
    if stream is None:
        return None
    return stream.get("data")


def _parse_start_date(start_date_str: str | None) -> datetime | None:
    """
    解析 Strava 的 ISO 8601 时间字符串为 datetime 对象。

    Strava 返回格式如 "2024-06-15T08:30:00Z"。
    Python 3.11+ 的 fromisoformat 不直接支持 "Z" 后缀，
    需要替换为 "+00:00" 才能正确解析为 UTC 时区。
    """
    if not start_date_str:
        return None
    try:
        return datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        logger.warning("无法解析 Strava start_date: %s", start_date_str)
        return None


def _safe_index(data: list | None, index: int):
    """安全索引访问——数组为 None 或索引越界时返回 None。"""
    if data is None or index >= len(data):
        return None
    return data[index]


def _safe_int(value) -> int | None:
    """安全转整数——None 或非数字时返回 None。心率/踏频/功率在 Trackpoint 中是 int 类型。"""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
