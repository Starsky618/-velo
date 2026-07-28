"""个人热图栅格瓦片。

热图不是“把几百条活动各自压成一条折线”——那种做法会在点数预算下把山路弯道
拉成直线。本模块按地图缩放级别读取当前瓦片附近的连续 GPS 点，先在服务端聚合成
透明 PNG，再交给小程序贴到腾讯底图上。客户端只下载当前视野需要的少量图片。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
import xyconvert

from app.activity.models import Activity, Trackpoint


_TILE_SIZE = 512  # 2x retina tile；地图上仍覆盖一个标准 Web-Mercator tile
_CACHE_TTL_SEC = 3600
_CACHE_PREFIX = "heatmap:raster:v1:user_"
_GENERATION_PREFIX = "heatmap:generation:user_"
_BEIJING_TZ = timezone(timedelta(hours=8))
_MAX_RAW_SEGMENT_METERS = 500

_COLOR_RAMPS = {
    "orange": ((255, 137, 32), (211, 55, 0)),
    "red": ((255, 72, 112), (193, 17, 68)),
    "purple": ((174, 94, 255), (91, 37, 184)),
    "blue": ((55, 151, 255), (0, 74, 199)),
}


class InvalidHeatmapTile(ValueError):
    """瓦片坐标或显示参数非法。"""


def _get_redis_client():
    from app.queue import redis_conn

    return redis_conn


def _inside_china(coords: np.ndarray) -> np.ndarray:
    """与小程序 coords.js 使用同一范围；境外坐标绝不能套 GCJ-02 偏移。"""
    return (
        (coords[:, 0] >= 72.004)
        & (coords[:, 0] <= 137.8347)
        & (coords[:, 1] >= 0.8293)
        & (coords[:, 1] <= 55.8271)
    )


def _wgs84_to_map_coords(coords: np.ndarray) -> np.ndarray:
    converted = np.array(coords, dtype=np.float64, copy=True)
    inside = _inside_china(converted)
    if np.any(inside):
        converted[inside] = xyconvert.wgs2gcj(converted[inside])
    return converted


def _map_coords_to_wgs84(coords: np.ndarray) -> np.ndarray:
    converted = np.array(coords, dtype=np.float64, copy=True)
    inside = _inside_china(converted)
    if np.any(inside):
        converted[inside] = xyconvert.gcj2wgs(converted[inside])
    return converted


def _tile_bounds_gcj02(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    """返回标准 Web-Mercator 瓦片的 (west, south, east, north)。"""
    tile_count = 1 << zoom
    west = x / tile_count * 360.0 - 180.0
    east = (x + 1) / tile_count * 360.0 - 180.0

    def tile_y_to_lat(tile_y: int) -> float:
        mercator = math.pi * (1 - 2 * tile_y / tile_count)
        return math.degrees(math.atan(math.sinh(mercator)))

    north = tile_y_to_lat(y)
    south = tile_y_to_lat(y + 1)
    return west, south, east, north


def _validate_tile(zoom: int, x: int, y: int, color: str) -> None:
    if not 3 <= zoom <= 18:
        raise InvalidHeatmapTile("invalid heatmap tile zoom")
    tile_count = 1 << zoom
    if not (0 <= x < tile_count and 0 <= y < tile_count):
        raise InvalidHeatmapTile("invalid heatmap tile coordinate")
    if color not in _COLOR_RAMPS:
        raise InvalidHeatmapTile("invalid heatmap color")


def _tile_query_bounds_wgs84(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    """把 GCJ-02 地图瓦片边界转回数据库使用的 WGS-84，并加一圈绘制缓冲。"""
    west, south, east, north = _tile_bounds_gcj02(zoom, x, y)
    lon_buffer = (east - west) * 0.08
    lat_buffer = (north - south) * 0.08
    corners_gcj = np.array(
        [
            [west - lon_buffer, south - lat_buffer],
            [west - lon_buffer, north + lat_buffer],
            [east + lon_buffer, south - lat_buffer],
            [east + lon_buffer, north + lat_buffer],
        ],
        dtype=np.float64,
    )
    corners_wgs = _map_coords_to_wgs84(corners_gcj)
    return (
        float(np.min(corners_wgs[:, 0])),
        float(np.min(corners_wgs[:, 1])),
        float(np.max(corners_wgs[:, 0])),
        float(np.max(corners_wgs[:, 1])),
    )


def _year_window_utc(year: int | None) -> tuple[datetime, datetime] | None:
    if year is None:
        return None
    if not 2000 <= year <= datetime.now(timezone.utc).year:
        raise InvalidHeatmapTile("invalid heatmap year")
    start = datetime(year, 1, 1, tzinfo=_BEIJING_TZ).astimezone(timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=_BEIJING_TZ).astimezone(timezone.utc)
    return start, end


def _activity_filters(user_id: int, year: int | None) -> list:
    filters = [
        Activity.user_id == user_id,
        Activity.status == "completed",
        Activity.duplicate_of.is_(None),
        Activity.activity_type == "cycling",
    ]
    window = _year_window_utc(year)
    if window is not None:
        filters.extend((Activity.started_at >= window[0], Activity.started_at < window[1]))
    return filters


def _append_segment(
    target: dict[int, list[list[tuple[float, float]]]],
    activity_id: int,
    points: list[tuple[float, float]],
) -> None:
    if len(points) >= 2:
        target[activity_id].append(points)


def _raw_points_must_split(
    previous: tuple[float, float] | None,
    current: tuple[float, float],
    previous_timestamp: datetime | None,
    current_timestamp: datetime | None,
) -> bool:
    """原始记录断档或瞬移时不猜路线；宁可留小缺口，也不能画一条不存在的直线。"""
    if previous is None:
        return False
    lon1, lat1 = previous
    lon2, lat2 = current
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    d_lat = lat2_rad - lat1_rad
    d_lon = math.radians(lon2 - lon1)
    haversine = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lon / 2) ** 2
    )
    distance_m = 6371000 * 2 * math.atan2(
        math.sqrt(haversine), math.sqrt(max(0.0, 1 - haversine))
    )
    if distance_m > _MAX_RAW_SEGMENT_METERS:
        return True
    if previous_timestamp is None or current_timestamp is None:
        return False
    elapsed = (current_timestamp - previous_timestamp).total_seconds()
    return elapsed <= 0 or elapsed > 45 or (elapsed > 0 and distance_m / elapsed > 45)


def _load_raw_segments(
    db: Session,
    user_id: int,
    year: int | None,
    zoom: int,
    x: int,
    y: int,
) -> dict[int, list[list[tuple[float, float]]]]:
    """读取瓦片附近的连续原始 GPS 点；seq 有空洞时必须切段，不能跨区连假直线。"""
    west, south, east, north = _tile_query_bounds_wgs84(zoom, x, y)
    envelope = func.ST_MakeEnvelope(west, south, east, north, 4326)
    spatial_filter = or_(
        Trackpoint.geom.op("&&")(envelope),
        and_(
            Trackpoint.geom.is_(None),
            Trackpoint.longitude >= west,
            Trackpoint.longitude <= east,
            Trackpoint.latitude >= south,
            Trackpoint.latitude <= north,
        ),
    )
    rows = (
        db.query(
            Trackpoint.activity_id,
            Trackpoint.seq,
            Trackpoint.longitude,
            Trackpoint.latitude,
            Trackpoint.timestamp,
        )
        .join(Activity, Activity.id == Trackpoint.activity_id)
        .filter(*_activity_filters(user_id, year), spatial_filter)
        .order_by(Trackpoint.activity_id.asc(), Trackpoint.seq.asc())
        .all()
    )

    grouped: dict[int, list[list[tuple[float, float]]]] = defaultdict(list)
    current_activity: int | None = None
    previous_seq: int | None = None
    previous_point: tuple[float, float] | None = None
    previous_timestamp: datetime | None = None
    current: list[tuple[float, float]] = []
    for row in rows:
        activity_id = int(row.activity_id)
        seq = int(row.seq)
        point = (float(row.longitude), float(row.latitude))
        timestamp = row.timestamp
        must_split = (
            current_activity != activity_id
            or previous_seq is None
            or seq != previous_seq + 1
            or _raw_points_must_split(previous_point, point, previous_timestamp, timestamp)
        )
        if must_split:
            if current_activity is not None:
                _append_segment(grouped, current_activity, current)
            current_activity = activity_id
            current = []
            previous_point = None
            previous_timestamp = None
        current.append(point)
        previous_seq = seq
        previous_point = point
        previous_timestamp = timestamp
    if current_activity is not None:
        _append_segment(grouped, current_activity, current)
    return grouped


def _load_overview_segments(
    db: Session,
    user_id: int,
    year: int | None,
) -> dict[int, list[list[tuple[float, float]]]]:
    """低缩放只需城市轮廓，复用每条活动约 1500 点的保形源，避免扫全量 GPS。"""
    rows = (
        db.query(Activity.id, Activity.simplified_track)
        .filter(*_activity_filters(user_id, year), Activity.simplified_track.isnot(None))
        .order_by(Activity.id.asc())
        .all()
    )
    grouped: dict[int, list[list[tuple[float, float]]]] = defaultdict(list)
    for row in rows:
        track = row.simplified_track
        if not isinstance(track, list):
            continue
        clean = []
        for point in track:
            if not isinstance(point, dict):
                continue
            try:
                clean.append((float(point["lon"]), float(point["lat"])))
            except (KeyError, TypeError, ValueError):
                continue
        _append_segment(grouped, int(row.id), clean)
    return grouped


def _global_pixel(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    lat = max(-85.05112878, min(85.05112878, lat))
    scale = (1 << zoom) * _TILE_SIZE
    pixel_x = (lon + 180.0) / 360.0 * scale
    sin_lat = math.sin(math.radians(lat))
    pixel_y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale
    return pixel_x, pixel_y


def _segments_to_gcj02(
    segments: dict[int, list[list[tuple[float, float]]]],
) -> dict[int, list[list[tuple[float, float]]]]:
    converted: dict[int, list[list[tuple[float, float]]]] = defaultdict(list)
    for activity_id, activity_segments in segments.items():
        for segment in activity_segments:
            if len(segment) < 2:
                continue
            coords = np.asarray(segment, dtype=np.float64)
            gcj = _wgs84_to_map_coords(coords)
            converted[activity_id].append([
                (float(point[0]), float(point[1])) for point in gcj
            ])
    return converted


def _render_tile_png(
    segments: dict[int, list[list[tuple[float, float]]]],
    zoom: int,
    x: int,
    y: int,
    color: str,
) -> bytes:
    """每条活动每个像素最多计一次，再用对数归一化增强稀疏路线与常骑路线的反差。"""
    heat = np.zeros((_TILE_SIZE, _TILE_SIZE), dtype=np.uint16)
    origin_x = x * _TILE_SIZE
    origin_y = y * _TILE_SIZE
    line_width = 3 if zoom >= 14 else 2

    for activity_segments in _segments_to_gcj02(segments).values():
        mask = Image.new("L", (_TILE_SIZE, _TILE_SIZE), 0)
        draw = ImageDraw.Draw(mask)
        for segment in activity_segments:
            points = []
            previous = None
            for lon, lat in segment:
                global_x, global_y = _global_pixel(lon, lat, zoom)
                point = (global_x - origin_x, global_y - origin_y)
                # 原始 GPS 极端漂点也不能在热图上生成跨城直线。
                if previous is not None and math.hypot(point[0] - previous[0], point[1] - previous[1]) > _TILE_SIZE:
                    if len(points) >= 2:
                        draw.line(points, fill=255, width=line_width, joint="curve")
                    points = []
                points.append(point)
                previous = point
            if len(points) >= 2:
                draw.line(points, fill=255, width=line_width, joint="curve")
        heat += np.asarray(mask, dtype=np.uint16) > 0

    rgba = np.zeros((_TILE_SIZE, _TILE_SIZE, 4), dtype=np.uint8)
    positive = heat > 0
    if np.any(positive):
        values = heat[positive].astype(np.float32)
        ceiling = max(1.0, float(np.percentile(values, 98)))
        strength = np.clip(np.log1p(values) / math.log1p(ceiling), 0.0, 1.0)
        strength = 0.35 + 0.65 * strength
        low, high = _COLOR_RAMPS[color]
        for channel in range(3):
            rgba[:, :, channel][positive] = np.rint(
                low[channel] + (high[channel] - low[channel]) * strength
            ).astype(np.uint8)
        rgba[:, :, 3][positive] = np.rint(175 + 80 * strength).astype(np.uint8)

    output = BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(output, format="PNG", optimize=True)
    return output.getvalue()


def get_user_heatmap_tile(
    db: Session,
    user_id: int,
    zoom: int,
    x: int,
    y: int,
    *,
    year: int | None = None,
    color: str = "orange",
) -> bytes:
    """返回一个用户、年份、配色和地图瓦片唯一对应的透明 PNG。"""
    _validate_tile(zoom, x, y, color)
    _year_window_utc(year)
    redis_client = _get_redis_client()
    try:
        raw_generation = redis_client.get(f"{_GENERATION_PREFIX}{user_id}")
        generation = int(raw_generation or 0)
    except Exception:
        generation = 0
    cache_key = (
        f"{_CACHE_PREFIX}{user_id}:g{generation}:year_{year or 'all'}:"
        f"color_{color}:z{zoom}:{x}:{y}"
    )
    try:
        cached = redis_client.get(cache_key)
        if isinstance(cached, bytes):
            return cached
    except Exception:
        pass

    segments = (
        _load_overview_segments(db, user_id, year)
        if zoom <= 9
        else _load_raw_segments(db, user_id, year, zoom, x, y)
    )
    rendered = _render_tile_png(segments, zoom, x, y, color)
    try:
        redis_client.setex(cache_key, _CACHE_TTL_SEC, rendered)
    except Exception:
        pass
    return rendered
