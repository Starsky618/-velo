"""个人热图栅格瓦片。

热图不是“把几百条活动各自压成一条折线”——那种做法会在点数预算下把山路弯道
拉成直线。本模块按地图缩放级别读取当前瓦片附近的连续 GPS 点，先在服务端聚合成
透明 PNG，再交给小程序贴到腾讯底图上。客户端只下载当前视野需要的少量图片。
"""

from __future__ import annotations

from collections.abc import Callable
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
import heapq
from io import BytesIO
import json
import math
from threading import RLock
from time import monotonic, sleep, time_ns
from weakref import WeakValueDictionary
import zlib

import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import and_, func, or_, text
from sqlalchemy.orm import Session
import xyconvert

from app.activity.models import Activity, Trackpoint
from app.common.geo import infer_city_from_coords
from app.user.service_social import (
    HeatmapSnapshotChanged,
    _RedisBuildLease,
    _acquire_redis_build_lease,
    _heatmap_activity_fingerprint,
    _heatmap_cache_version,
    _public_activity_filter,
    _public_heatmap_privacy_fingerprint,
)


_TILE_SIZE = 512  # 2x retina tile；地图上仍覆盖一个标准 Web-Mercator tile
_CACHE_TTL_SEC = 86400
_CACHE_PREFIX = "heatmap:raster:v2:user_"
_GENERATION_PREFIX = "heatmap:generation:user_"
_BEIJING_TZ = timezone(timedelta(hours=8))
_RAW_POINT_QUERY_BUFFER_METERS = 1_000
_RAW_UNTIMED_GAP_METERS = 500
_OVERVIEW_POINTS_PER_SEGMENT = 1_000
_OVERVIEW_SOURCE_CACHE_TTL_SEC = 60
_OVERVIEW_SOURCE_CACHE_MAX_ITEMS = 8
_OVERVIEW_REDIS_SOURCE_TTL_SEC = 7 * 86400
_OVERVIEW_REDIS_SOURCE_PREFIX = "heatmap:raster:v2:source:user_"
_OVERVIEW_SOURCE_BUILD_LOCK_TTL_SEC = 30
_OVERVIEW_SOURCE_BUILD_WAIT_SEC = 60
_OVERVIEW_SOURCE_BUILD_POLL_SEC = 0.05
_DETAIL_SOURCE_REDIS_PREFIX = "heatmap:detail:v1:user_"
_DETAIL_SOURCE_ZOOM = 12
_DETAIL_SOURCE_REDIS_TTL_SEC = 7 * 86400
_DETAIL_SOURCE_MEMORY_TTL_SEC = 60
_DETAIL_SOURCE_MEMORY_MAX_ITEMS = 128
_VECTOR_CACHE_TTL_SEC = 900
_VECTOR_CACHE_PREFIX = "heatmap:vector:v3:user_"
_VECTOR_LRU_PREFIX = "heatmap:vector:lru:v1:user_"
_VECTOR_MAX_CACHE_KEYS = 16
_AVAILABLE_YEARS_REDIS_PREFIX = "heatmap:years:v1:user_"
_AVAILABLE_YEARS_REDIS_TTL_SEC = 7 * 86400
_VECTOR_TOTAL_POINT_BUDGET = 14_000
_VECTOR_POINTS_PER_SEGMENT = 320
_DERIVED_BUILD_LOCK_TTL_SEC = 30
_DERIVED_BUILD_WAIT_SEC = 60
_DERIVED_BUILD_POLL_SEC = 0.05
_OVERVIEW_SOURCE_CACHE: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_OVERVIEW_MAP_CACHE: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_DETAIL_SOURCE_CHUNK_CACHE: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_OVERVIEW_SOURCE_CACHE_LOCK = RLock()
_OVERVIEW_BUILD_LOCKS: WeakValueDictionary[tuple, RLock] = WeakValueDictionary()

_COLOR_RAMPS = {
    # 默认色从高亮橙过渡到深红，和腾讯底图的浅橙道路保持足够区分。
    "orange": ((255, 94, 0), (187, 0, 59)),
    "red": ((255, 72, 112), (193, 17, 68)),
    "purple": ((174, 94, 255), (91, 37, 184)),
    "blue": ((55, 151, 255), (0, 74, 199)),
}


class InvalidHeatmapTile(ValueError):
    """瓦片坐标或显示参数非法。"""


def _claim_derived_cache_build(
    redis_client,
    cache_key: str,
    decoder: Callable[[bytes], object],
) -> tuple[_RedisBuildLease | None, object | None]:
    """同一视野/瓦片只让一个请求计算；其余请求等待 Redis 结果。"""
    lock_key = f"{cache_key}:build"
    try:
        lease = _acquire_redis_build_lease(
            redis_client,
            lock_key,
            _DERIVED_BUILD_LOCK_TTL_SEC,
        )
        if lease is not None:
            lease.start()
            return lease, None
    except Exception:
        return None, None

    deadline = monotonic() + _DERIVED_BUILD_WAIT_SEC
    while monotonic() < deadline:
        try:
            cached = redis_client.get(cache_key)
            if isinstance(cached, bytes):
                try:
                    return None, decoder(cached)
                except Exception:
                    # 损坏缓存不能交给调用方；等租约到期后由一个请求重建。
                    pass
            lease = _acquire_redis_build_lease(
                redis_client,
                lock_key,
                _DERIVED_BUILD_LOCK_TTL_SEC,
            )
            if lease is not None:
                lease.start()
                return lease, None
        except Exception:
            return None, None
        sleep(_DERIVED_BUILD_POLL_SEC)
    # Redis/构建者持续异常时降级直算，避免用户永久打不开地图。
    return None, None


def _release_derived_cache_build(lease: _RedisBuildLease | None) -> None:
    if lease is None:
        return
    lease.release()


def _get_redis_client():
    from app.queue import heatmap_redis_conn

    return heatmap_redis_conn


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
    middle_lat = (south + north) / 2
    # zoom 18 的 8% 只有约 10 米，命中一个点时会把跨瓦片边界的连续线整段丢掉。
    # 至少外扩一个“允许的原始点间距”，保证能同时拿到边界两侧的前后点。
    min_lat_buffer = _RAW_POINT_QUERY_BUFFER_METERS / 111_320
    min_lon_buffer = _RAW_POINT_QUERY_BUFFER_METERS / (
        111_320 * max(0.05, abs(math.cos(math.radians(middle_lat))))
    )
    lon_buffer = max((east - west) * 0.08, min_lon_buffer)
    lat_buffer = max((north - south) * 0.08, min_lat_buffer)
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


def _activity_filters(
    user_id: int,
    year: int | None,
    include_private: bool,
) -> list:
    filters = [
        Activity.user_id == user_id,
        Activity.status == "completed",
        Activity.duplicate_of.is_(None),
        Activity.activity_type == "cycling",
    ]
    window = _year_window_utc(year)
    if window is not None:
        filters.extend((Activity.started_at >= window[0], Activity.started_at < window[1]))
    if not include_private:
        filters.append(_public_activity_filter())
    return filters


def _append_segment(
    target: dict[int, list[list[tuple[float, float]]]],
    activity_id: int,
    points: list[tuple[float, float]],
) -> None:
    if len(points) >= 2:
        target[activity_id].append(points)


def _distance_meters(
    previous: tuple[float, float], current: tuple[float, float]
) -> float:
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
    return 6371000 * 2 * math.atan2(
        math.sqrt(haversine), math.sqrt(max(0.0, 1 - haversine))
    )


def _raw_points_must_split(
    previous: tuple[float, float] | None,
    current: tuple[float, float],
    previous_timestamp: datetime | None,
    current_timestamp: datetime | None,
) -> bool:
    """原始记录断档或瞬移时不猜路线；宁可留小缺口，也不能画一条不存在的直线。"""
    if previous is None:
        return False
    distance_m = _distance_meters(previous, current)
    if previous_timestamp is None or current_timestamp is None:
        return distance_m > _RAW_UNTIMED_GAP_METERS
    elapsed = (current_timestamp - previous_timestamp).total_seconds()
    return elapsed <= 0 or elapsed > 45 or (elapsed > 0 and distance_m / elapsed > 45)


def _sample_overview_segment(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Visvalingam 几何简化：优先删近共线点，保住发卡弯等高曲率拐点。"""
    return _sample_segment_to_limit(points, _OVERVIEW_POINTS_PER_SEGMENT)


def _sample_segment_to_limit(
    points: list[tuple[float, float]],
    limit: int,
) -> list[tuple[float, float]]:
    """按几何重要性压到指定点数；不能再用等距抽样把连续弯道拉直。"""
    if len(points) <= limit:
        return points

    projected = []
    for lon, lat in points:
        limited_lat = max(-85.05112878, min(85.05112878, lat))
        projected.append((
            lon,
            math.log(math.tan(math.pi / 4 + math.radians(limited_lat) / 2)),
        ))

    previous = [index - 1 for index in range(len(points))]
    following = [index + 1 for index in range(len(points))]
    following[-1] = -1
    active = [True] * len(points)
    heap: list[tuple[float, int, int, int]] = []

    def push(index: int) -> None:
        left = previous[index]
        right = following[index]
        if left < 0 or right < 0:
            return
        ax, ay = projected[left]
        bx, by = projected[index]
        cx, cy = projected[right]
        area = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
        heapq.heappush(heap, (area, index, left, right))

    for index in range(1, len(points) - 1):
        push(index)

    remaining = len(points)
    while remaining > limit and heap:
        _, index, left, right = heapq.heappop(heap)
        if (
            not active[index]
            or previous[index] != left
            or following[index] != right
        ):
            continue
        active[index] = False
        following[left] = right
        previous[right] = left
        remaining -= 1
        push(left)
        push(right)

    return [point for index, point in enumerate(points) if active[index]]


def _simplify_segment_for_zoom(
    points: list[tuple[float, float]],
    zoom: int,
    latitude: float,
) -> list[tuple[float, float]]:
    """Douglas-Peucker 屏幕空间 LOD：城市总览减量，放大后恢复真实拐弯。"""
    if len(points) <= 2:
        return points
    meters_per_pixel = (
        156543.03392
        * max(0.05, abs(math.cos(math.radians(latitude))))
        / (1 << zoom)
    )
    tolerance_m = max(0.6, meters_per_pixel * 0.28)
    origin_lon, origin_lat = points[0]
    lon_scale = 111_320 * max(0.05, abs(math.cos(math.radians(latitude))))
    projected = [
        ((lon - origin_lon) * lon_scale, (lat - origin_lat) * 111_320)
        for lon, lat in points
    ]
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        ax, ay = projected[start]
        bx, by = projected[end]
        dx = bx - ax
        dy = by - ay
        length_sq = dx * dx + dy * dy
        farthest_index = -1
        farthest_distance = -1.0
        for index in range(start + 1, end):
            px, py = projected[index]
            if length_sq <= 1e-12:
                distance = math.hypot(px - ax, py - ay)
            else:
                ratio = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
                distance = math.hypot(px - (ax + ratio * dx), py - (ay + ratio * dy))
            if distance > farthest_distance:
                farthest_distance = distance
                farthest_index = index
        if farthest_index >= 0 and farthest_distance > tolerance_m:
            keep.add(farthest_index)
            stack.append((start, farthest_index))
            stack.append((farthest_index, end))
    return [points[index] for index in sorted(keep)]


def _load_raw_segments(
    db: Session,
    user_id: int,
    year: int | None,
    zoom: int,
    x: int,
    y: int,
    include_private: bool,
) -> dict[int, list[list[tuple[float, float]]]]:
    """读取瓦片附近的连续原始 GPS 点；seq 有空洞时必须切段，不能跨区连假直线。"""
    west, south, east, north = _tile_query_bounds_wgs84(zoom, x, y)
    return _load_raw_segments_for_bounds(
        db,
        user_id,
        year,
        west,
        south,
        east,
        north,
        include_private,
    )


def _load_raw_segments_for_bounds(
    db: Session,
    user_id: int,
    year: int | None,
    west: float,
    south: float,
    east: float,
    north: float,
    include_private: bool,
) -> dict[int, list[list[tuple[float, float]]]]:
    """按 WGS-84 范围读取连续原始点；供瓦片和图片图层失败后的矢量降级共用。"""
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
        .filter(*_activity_filters(user_id, year, include_private), spatial_filter)
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


def _load_segmented_segments(
    db: Session,
    user_id: int,
    year: int | None,
    include_private: bool,
    *,
    simplify_tolerance: float | None,
    point_limit: int | None,
) -> dict[int, list[list[tuple[float, float]]]]:
    """从原始点切出真实连续段，再按派生层精度做一次离线简化。"""
    year_window = _year_window_utc(year)
    year_clause = ""
    params: dict[str, object] = {"user_id": user_id}
    if year_window is not None:
        year_clause = "AND a.started_at >= :year_start AND a.started_at < :year_end"
        params.update({"year_start": year_window[0], "year_end": year_window[1]})
    privacy_clause = ""
    if not include_private:
        privacy_clause = "AND (ap.activity_id IS NULL OR ap.visibility = 'public')"
    line_expression = "ST_MakeLine(geom ORDER BY seq)"
    if simplify_tolerance is not None:
        line_expression = f"ST_Simplify({line_expression}, :simplify_tolerance)"

    rows = db.execute(
        text(f"""
            WITH ordered AS (
                SELECT
                    tp.activity_id,
                    tp.seq,
                    tp.timestamp,
                    COALESCE(
                        tp.geom,
                        ST_SetSRID(ST_MakePoint(tp.longitude, tp.latitude), 4326)
                    ) AS geom,
                    LAG(tp.seq) OVER activity_order AS previous_seq,
                    LAG(tp.timestamp) OVER activity_order AS previous_timestamp,
                    LAG(COALESCE(
                        tp.geom,
                        ST_SetSRID(ST_MakePoint(tp.longitude, tp.latitude), 4326)
                    )) OVER activity_order AS previous_geom
                FROM trackpoints tp
                JOIN activities a ON a.id = tp.activity_id
                LEFT JOIN activity_privacy ap ON ap.activity_id = a.id
                WHERE a.user_id = :user_id
                  AND a.status = 'completed'
                  AND a.duplicate_of IS NULL
                  AND a.activity_type = 'cycling'
                  {year_clause}
                  {privacy_clause}
                WINDOW activity_order AS (
                    PARTITION BY tp.activity_id ORDER BY tp.seq
                )
            ),
            measured AS (
                SELECT
                    *,
                    CASE
                        WHEN previous_geom IS NULL THEN NULL
                        ELSE ST_DistanceSphere(geom, previous_geom)
                    END AS distance_m,
                    CASE
                        WHEN previous_timestamp IS NULL OR timestamp IS NULL THEN NULL
                        ELSE EXTRACT(EPOCH FROM timestamp - previous_timestamp)
                    END AS elapsed_s
                FROM ordered
            ),
            marked AS (
                SELECT
                    *,
                    CASE
                        WHEN previous_seq IS NULL THEN 0
                        WHEN seq <> previous_seq + 1 THEN 1
                        WHEN elapsed_s IS NULL AND distance_m > :untimed_gap_m THEN 1
                        WHEN elapsed_s <= 0 OR elapsed_s > :max_elapsed_s THEN 1
                        WHEN distance_m / NULLIF(elapsed_s, 0) > :max_speed_mps THEN 1
                        ELSE 0
                    END AS starts_segment
                FROM measured
            ),
            segmented AS (
                SELECT
                    *,
                    SUM(starts_segment) OVER (
                        PARTITION BY activity_id ORDER BY seq
                        ROWS UNBOUNDED PRECEDING
                    ) AS segment_id
                FROM marked
            ),
            lines AS (
                SELECT
                    activity_id,
                    segment_id,
                    {line_expression} AS line_geom
                FROM segmented
                GROUP BY activity_id, segment_id
                HAVING COUNT(*) >= 2
            )
            SELECT
                activity_id,
                segment_id,
                (dumped).path[1] AS point_order,
                ST_X((dumped).geom) AS longitude,
                ST_Y((dumped).geom) AS latitude
            FROM lines
            CROSS JOIN LATERAL ST_DumpPoints(line_geom) AS dumped
            ORDER BY activity_id, segment_id, point_order
        """),
        {
            **params,
            "untimed_gap_m": _RAW_UNTIMED_GAP_METERS,
            "max_elapsed_s": 45,
            "max_speed_mps": 45,
            "simplify_tolerance": simplify_tolerance or 0.0,
        },
    ).all()

    grouped: dict[int, list[list[tuple[float, float]]]] = defaultdict(list)
    current_key: tuple[int, int] | None = None
    current: list[tuple[float, float]] = []
    for row in rows:
        key = (int(row.activity_id), int(row.segment_id))
        if current_key is not None and key != current_key:
            prepared = (
                _sample_segment_to_limit(current, point_limit)
                if point_limit is not None
                else current
            )
            _append_segment(
                grouped,
                current_key[0],
                prepared,
            )
            current = []
        current_key = key
        current.append((float(row.longitude), float(row.latitude)))
    if current_key is not None:
        prepared = (
            _sample_segment_to_limit(current, point_limit)
            if point_limit is not None
            else current
        )
        _append_segment(grouped, current_key[0], prepared)
    return grouped


def _load_overview_segments(
    db: Session,
    user_id: int,
    year: int | None,
    include_private: bool,
) -> dict[int, list[list[tuple[float, float]]]]:
    """城市总览源：约 2 米保弯精度，每段最多 1000 点。"""
    return _load_segmented_segments(
        db,
        user_id,
        year,
        include_private,
        simplify_tolerance=0.00002,
        point_limit=_OVERVIEW_POINTS_PER_SEGMENT,
    )


def _load_detail_segments(
    db: Session,
    user_id: int,
    year: int | None,
    include_private: bool,
) -> dict[int, list[list[tuple[float, float]]]]:
    """高倍率派生源：保留连续段全部原始几何点，只做无损压缩和空间分块。"""
    return _load_segmented_segments(
        db,
        user_id,
        year,
        include_private,
        simplify_tolerance=None,
        point_limit=None,
    )


def _decode_overview_segments(encoded: bytes):
    payload = json.loads(zlib.decompress(encoded).decode())
    restored: dict[int, list[list[tuple[float, float]]]] = defaultdict(list)
    for activity_id, activity_segments in payload:
        for segment in activity_segments:
            clean = [
                (float(point[0]), float(point[1]))
                for point in segment
                if isinstance(point, list) and len(point) == 2
            ]
            _append_segment(restored, int(activity_id), clean)
    return restored


def _encode_segment_chunks(
    segments: dict[int, list[list[tuple[float, float]]]],
) -> bytes:
    payload = [
        [activity_id, activity_segments]
        for activity_id, activity_segments in segments.items()
    ]
    return zlib.compress(
        json.dumps(payload, separators=(",", ":")).encode(),
        level=6,
    )


def _source_tile_for_point(
    longitude: float,
    latitude: float,
    zoom: int = _DETAIL_SOURCE_ZOOM,
) -> tuple[int, int]:
    count = 1 << zoom
    x = int((longitude + 180.0) / 360.0 * count)
    limited = max(-85.05112878, min(85.05112878, latitude))
    radians = math.radians(limited)
    y = int((1 - math.asinh(math.tan(radians)) / math.pi) / 2 * count)
    return (
        max(0, min(count - 1, x)),
        max(0, min(count - 1, y)),
    )


def _detail_source_base_key(
    user_id: int,
    generation: int,
    activity_fingerprint: str,
    year: int | None,
    include_private: bool,
    privacy_fingerprint: str | None,
) -> str:
    key = (
        f"{_DETAIL_SOURCE_REDIS_PREFIX}{user_id}:g{generation}:"
        f"data_{activity_fingerprint}:year_{year or 'all'}:"
        f"audience_{'owner' if include_private else 'public'}"
    )
    if privacy_fingerprint is not None:
        key += f":privacy_{privacy_fingerprint}"
    return key


def _partition_detail_segments(
    segments: dict[int, list[list[tuple[float, float]]]],
    zoom: int = _DETAIL_SOURCE_ZOOM,
) -> dict[tuple[int, int], dict[int, list[list[tuple[float, float]]]]]:
    """把连续高精度轨迹切成粗粒度 source tiles，拖图时只解码邻近块。

    source tile 不是最终 PNG；它相当于 Strava Meridian 文中预编码的矢量数据层。
    每条相邻点线段按中点归入唯一 tile，同时保留两个端点。读取时会多取一圈邻块
    再按真实视野精确裁剪，因此不会重复绘制，也不会在分块边缘制造断线或跨路直线。
    """
    chunks: dict[
        tuple[int, int],
        dict[int, list[list[tuple[float, float]]]],
    ] = defaultdict(lambda: defaultdict(list))
    for activity_id, activity_segments in segments.items():
        for segment in activity_segments:
            active: dict[tuple[int, int], list[tuple[float, float]]] = {}
            for start, end in zip(segment, segment[1:]):
                touched = {
                    _source_tile_for_point(
                        (start[0] + end[0]) / 2,
                        (start[1] + end[1]) / 2,
                        zoom,
                    )
                }
                for tile in list(active):
                    if tile not in touched:
                        _append_segment(chunks[tile], activity_id, active.pop(tile))
                for tile in touched:
                    current = active.get(tile)
                    if current is None:
                        active[tile] = [start, end]
                    elif current[-1] == start:
                        current.append(end)
                    else:
                        _append_segment(chunks[tile], activity_id, current)
                        active[tile] = [start, end]
            for tile, current in active.items():
                _append_segment(chunks[tile], activity_id, current)
    return chunks


def _detail_source_memory_get(cache_key: str):
    now = monotonic()
    with _OVERVIEW_SOURCE_CACHE_LOCK:
        cached = _DETAIL_SOURCE_CHUNK_CACHE.get(cache_key)
        if cached is not None and now - cached[0] <= _DETAIL_SOURCE_MEMORY_TTL_SEC:
            _DETAIL_SOURCE_CHUNK_CACHE.move_to_end(cache_key)
            return cached[1]
        if cached is not None:
            del _DETAIL_SOURCE_CHUNK_CACHE[cache_key]
    return None


def _detail_source_memory_store(cache_key: str, segments: dict) -> None:
    with _OVERVIEW_SOURCE_CACHE_LOCK:
        _DETAIL_SOURCE_CHUNK_CACHE[cache_key] = (monotonic(), segments)
        while len(_DETAIL_SOURCE_CHUNK_CACHE) > _DETAIL_SOURCE_MEMORY_MAX_ITEMS:
            _DETAIL_SOURCE_CHUNK_CACHE.popitem(last=False)


def _join_detail_source_segment(
    merged: dict[int, list[list[tuple[float, float]]]],
    activity_id: int,
    segment: list[tuple[float, float]],
) -> None:
    """把 source-tile 边界切开的相邻片段重新接回；只按完全相同端点连接。"""
    if len(segment) < 2:
        return
    pending = list(segment)
    candidates = merged[activity_id]
    index = 0
    while index < len(candidates):
        current = candidates[index]
        if current[-1] == pending[0]:
            pending = current + pending[1:]
            candidates.pop(index)
            index = 0
            continue
        if pending[-1] == current[0]:
            pending = pending + current[1:]
            candidates.pop(index)
            index = 0
            continue
        index += 1
    candidates.append(pending)


def _detail_source_tile_range(
    west: float,
    south: float,
    east: float,
    north: float,
    zoom: int = _DETAIL_SOURCE_ZOOM,
) -> list[tuple[int, int]]:
    min_x, max_y = _source_tile_for_point(west, south, zoom)
    max_x, min_y = _source_tile_for_point(east, north, zoom)
    count = 1 << zoom
    first_x = max(0, min(min_x, max_x) - 1)
    last_x = min(count - 1, max(min_x, max_x) + 1)
    first_y = max(0, min(min_y, max_y) - 1)
    last_y = min(count - 1, max(min_y, max_y) + 1)
    return [
        (x, y)
        for x in range(first_x, last_x + 1)
        for y in range(first_y, last_y + 1)
    ]


def build_user_heatmap_detail_source(
    db: Session,
    user_id: int,
    *,
    year: int | None = None,
    include_private: bool = True,
    generation: int,
    activity_fingerprint: str,
    privacy_fingerprint: str | None = None,
    redis_client=None,
) -> dict[str, int]:
    """RQ 预生成高精度分块源；manifest 最后写入，半成品绝不对请求可见。"""
    if redis_client is None:
        redis_client = _get_redis_client()
    segments = _load_detail_segments(db, user_id, year, include_private)
    chunks = _partition_detail_segments(segments)
    base_key = _detail_source_base_key(
        user_id,
        generation,
        activity_fingerprint,
        year,
        include_private,
        privacy_fingerprint,
    )
    encoded_chunks: list[tuple[str, bytes]] = []
    point_count = 0
    for (x, y), chunk in sorted(chunks.items()):
        encoded = _encode_segment_chunks(chunk)
        encoded_chunks.append((f"{base_key}:z{_DETAIL_SOURCE_ZOOM}:{x}:{y}", encoded))
        point_count += sum(
            len(segment)
            for activity_segments in chunk.values()
            for segment in activity_segments
        )
    manifest = zlib.compress(
        json.dumps(
            {
                "zoom": _DETAIL_SOURCE_ZOOM,
                "tiles": [[x, y] for x, y in sorted(chunks)],
                "point_count": point_count,
            },
            separators=(",", ":"),
        ).encode(),
        level=6,
    )
    pipeline = redis_client.pipeline(transaction=False)
    for key, encoded in encoded_chunks:
        pipeline.setex(key, _DETAIL_SOURCE_REDIS_TTL_SEC, encoded)
    pipeline.setex(
        f"{base_key}:manifest",
        _DETAIL_SOURCE_REDIS_TTL_SEC,
        manifest,
    )
    pipeline.execute()
    written_keys = [key for key, _ in encoded_chunks] + [f"{base_key}:manifest"]
    try:
        current_generation = int(
            redis_client.get(f"{_GENERATION_PREFIX}{user_id}") or 0
        )
        if current_generation != generation:
            redis_client.delete(*written_keys)
    except Exception:
        # generation 仍编码在每个 key 中；即使回收失败，新请求也不会读到旧代。
        pass
    return {
        "tile_count": len(encoded_chunks),
        "point_count": point_count,
        "compressed_bytes": sum(len(encoded) for _, encoded in encoded_chunks),
    }


def _get_detail_segments_cached_for_bounds(
    redis_client,
    user_id: int,
    generation: int,
    activity_fingerprint: str,
    year: int | None,
    include_private: bool,
    privacy_fingerprint: str | None,
    west: float,
    south: float,
    east: float,
    north: float,
) -> dict[int, list[list[tuple[float, float]]]] | None:
    """读取预生成 source tiles；None 表示尚未预热，调用方可降级查当前 PG 视野。"""
    base_key = _detail_source_base_key(
        user_id,
        generation,
        activity_fingerprint,
        year,
        include_private,
        privacy_fingerprint,
    )
    try:
        raw_manifest = redis_client.get(f"{base_key}:manifest")
        if not isinstance(raw_manifest, bytes):
            return None
        manifest = json.loads(zlib.decompress(raw_manifest).decode())
        if int(manifest.get("zoom", -1)) != _DETAIL_SOURCE_ZOOM:
            return None
        occupied = {
            (int(tile[0]), int(tile[1]))
            for tile in manifest.get("tiles", [])
            if isinstance(tile, list) and len(tile) == 2
        }
    except Exception:
        return None

    wanted = [
        tile
        for tile in _detail_source_tile_range(west, south, east, north)
        if tile in occupied
    ]
    if not wanted:
        return {}
    keys = [
        f"{base_key}:z{_DETAIL_SOURCE_ZOOM}:{x}:{y}"
        for x, y in wanted
    ]
    missing_keys = [key for key in keys if _detail_source_memory_get(key) is None]
    if missing_keys:
        try:
            encoded_chunks = redis_client.mget(missing_keys)
        except Exception:
            return None
        if len(encoded_chunks) != len(missing_keys) or any(
            not isinstance(encoded, bytes) for encoded in encoded_chunks
        ):
            return None
        try:
            for key, encoded in zip(missing_keys, encoded_chunks):
                _detail_source_memory_store(key, _decode_overview_segments(encoded))
        except Exception:
            return None

    merged: dict[int, list[list[tuple[float, float]]]] = defaultdict(list)
    for key in keys:
        chunk = _detail_source_memory_get(key)
        if chunk is None:
            return None
        for activity_id, activity_segments in chunk.items():
            for segment in activity_segments:
                _join_detail_source_segment(merged, activity_id, segment)
    return _clip_vector_segments_to_bounds(merged, west, south, east, north)


def _enqueue_detail_source_prewarm_if_needed(
    user_id: int,
    generation: int,
    year: int | None,
    include_private: bool,
) -> None:
    """旧 owner/all-year 没有 v3 source 时补入队；当前请求仍走 PG 故障降级。"""
    if not include_private or year is not None:
        return
    from app.user.service_social import enqueue_heatmap_cache_prewarm

    enqueue_heatmap_cache_prewarm(user_id, generation)


def _overview_memory_get(key: tuple):
    now = monotonic()
    with _OVERVIEW_SOURCE_CACHE_LOCK:
        cached = _OVERVIEW_SOURCE_CACHE.get(key)
        if cached is not None and now - cached[0] <= _OVERVIEW_SOURCE_CACHE_TTL_SEC:
            _OVERVIEW_SOURCE_CACHE.move_to_end(key)
            return cached[1]
        if cached is not None:
            del _OVERVIEW_SOURCE_CACHE[key]
    return None


def _overview_memory_store(key: tuple, segments: dict) -> None:
    with _OVERVIEW_SOURCE_CACHE_LOCK:
        _OVERVIEW_SOURCE_CACHE[key] = (monotonic(), segments)
        while len(_OVERVIEW_SOURCE_CACHE) > _OVERVIEW_SOURCE_CACHE_MAX_ITEMS:
            _OVERVIEW_SOURCE_CACHE.popitem(last=False)


def _overview_build_lock(key: tuple) -> RLock:
    """只串行同一用户/年份/generation；弱引用避免按用户永久积累锁对象。"""
    with _OVERVIEW_SOURCE_CACHE_LOCK:
        lock = _OVERVIEW_BUILD_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _OVERVIEW_BUILD_LOCKS[key] = lock
        return lock


def _get_overview_segments_cached(
    db: Session,
    user_id: int,
    year: int | None,
    include_private: bool,
    generation: int,
    privacy_fingerprint: str | None,
    redis_client,
    activity_fingerprint: str | None = None,
) -> dict[int, list[list[tuple[float, float]]]]:
    """三层总览源：进程 LRU → Redis WGS-84 源 → PostgreSQL 原始 Trackpoint。

    同一 generation 的跨进程冷启动使用 Redis 租约锁，只允许一个请求扫描
    PostgreSQL；其他请求等待源层完成后复用。Redis 源必须保存 WGS-84，矢量响应
    直接使用，只有栅格渲染时才转换成腾讯地图坐标。
    """
    if activity_fingerprint is None:
        activity_fingerprint = _heatmap_activity_fingerprint(
            db,
            user_id,
            include_private,
        )
    key = (
        user_id,
        year,
        include_private,
        generation,
        privacy_fingerprint,
        activity_fingerprint,
    )
    redis_key = (
        f"{_OVERVIEW_REDIS_SOURCE_PREFIX}{user_id}:g{generation}:"
        f"data_{activity_fingerprint}:year_{year or 'all'}:"
        f"audience_{'owner' if include_private else 'public'}"
    )
    if privacy_fingerprint is not None:
        redis_key += f":privacy_{privacy_fingerprint}"
    cached = _overview_memory_get(key)
    if cached is not None:
        return cached

    # Redis I/O、等待和 PG 扫描绝不能占用全局 LRU 锁；这里只串行同一 source key。
    with _overview_build_lock(key):
        cached = _overview_memory_get(key)
        if cached is not None:
            return cached
        try:
            encoded = redis_client.get(redis_key)
            if isinstance(encoded, bytes):
                restored = _decode_overview_segments(encoded)
                _overview_memory_store(key, restored)
                return restored
        except Exception:
            # 损坏或旧格式缓存直接重建；不能让一张坏 source 卡死全部低缩放瓦片。
            pass

        lock_key = f"{redis_key}:build"
        build_lease = None
        owns_lock = False
        redis_available = True
        try:
            build_lease = _acquire_redis_build_lease(
                redis_client,
                lock_key,
                _OVERVIEW_SOURCE_BUILD_LOCK_TTL_SEC,
            )
            owns_lock = build_lease is not None
            if build_lease is not None:
                build_lease.start()
        except Exception:
            redis_available = False
            owns_lock = True

        if redis_available and not owns_lock:
            deadline = monotonic() + _OVERVIEW_SOURCE_BUILD_WAIT_SEC
            while monotonic() < deadline:
                try:
                    encoded = redis_client.get(redis_key)
                    if isinstance(encoded, bytes):
                        restored = _decode_overview_segments(encoded)
                        _overview_memory_store(key, restored)
                        return restored
                    build_lease = _acquire_redis_build_lease(
                        redis_client,
                        lock_key,
                        _OVERVIEW_SOURCE_BUILD_LOCK_TTL_SEC,
                    )
                    owns_lock = build_lease is not None
                    if owns_lock:
                        build_lease.start()
                        break
                except Exception:
                    owns_lock = True
                    break
                sleep(_OVERVIEW_SOURCE_BUILD_POLL_SEC)

        try:
            # Redis 不可用或等待 60 秒仍无结果时故障降级直算，不能永久卡死地图。
            segments = _load_overview_segments(db, user_id, year, include_private)
            try:
                payload = [
                    [activity_id, activity_segments]
                    for activity_id, activity_segments in segments.items()
                ]
                redis_client.setex(
                    redis_key,
                    _OVERVIEW_REDIS_SOURCE_TTL_SEC,
                    zlib.compress(
                        json.dumps(payload, separators=(",", ":")).encode(),
                        level=6,
                    ),
                )
            except Exception:
                # Redis 只是加速层；PostGIS 真值仍可生成当前请求。
                pass
            _overview_memory_store(key, segments)
            return segments
        finally:
            if redis_available and build_lease is not None:
                build_lease.release()


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


def _get_overview_map_segments_cached(
    segments: dict[int, list[list[tuple[float, float]]]],
    user_id: int,
    year: int | None,
    include_private: bool,
    generation: int,
    privacy_fingerprint: str | None,
    activity_fingerprint: str,
) -> dict[int, list[list[tuple[float, float]]]]:
    """同一进程每代只做一次 WGS-84 → 腾讯地图坐标转换，供多块瓦片复用。"""
    key = (
        user_id,
        year,
        include_private,
        generation,
        privacy_fingerprint,
        activity_fingerprint,
    )
    now = monotonic()
    with _OVERVIEW_SOURCE_CACHE_LOCK:
        cached = _OVERVIEW_MAP_CACHE.get(key)
        if cached is not None and now - cached[0] <= _OVERVIEW_SOURCE_CACHE_TTL_SEC:
            _OVERVIEW_MAP_CACHE.move_to_end(key)
            return cached[1]
        if cached is not None:
            del _OVERVIEW_MAP_CACHE[key]
        converted = _segments_to_gcj02(segments)
        _OVERVIEW_MAP_CACHE[key] = (now, converted)
        while len(_OVERVIEW_MAP_CACHE) > _OVERVIEW_SOURCE_CACHE_MAX_ITEMS:
            _OVERVIEW_MAP_CACHE.popitem(last=False)
        return converted


def _render_tile_png(
    segments: dict[int, list[list[tuple[float, float]]]],
    zoom: int,
    x: int,
    y: int,
    color: str,
    *,
    coordinates_are_map: bool = False,
) -> bytes:
    """每条活动每个像素最多计一次，再用对数归一化增强稀疏路线与常骑路线的反差。"""
    heat = np.zeros((_TILE_SIZE, _TILE_SIZE), dtype=np.uint16)
    origin_x = x * _TILE_SIZE
    origin_y = y * _TILE_SIZE
    line_width = 3 if zoom >= 14 else 2

    map_segments = segments if coordinates_are_map else _segments_to_gcj02(segments)
    west, south, east, north = _tile_bounds_gcj02(zoom, x, y)
    lon_margin = (east - west) * 0.02
    lat_margin = (north - south) * 0.02

    for activity_segments in map_segments.values():
        mask = Image.new("L", (_TILE_SIZE, _TILE_SIZE), 0)
        draw = ImageDraw.Draw(mask)
        for segment in activity_segments:
            longitudes = [point[0] for point in segment]
            latitudes = [point[1] for point in segment]
            if (
                max(longitudes) < west - lon_margin
                or min(longitudes) > east + lon_margin
                or max(latitudes) < south - lat_margin
                or min(latitudes) > north + lat_margin
            ):
                continue

            pixel_points = []
            for lon, lat in segment:
                global_x, global_y = _global_pixel(lon, lat, zoom)
                pixel_points.append((global_x - origin_x, global_y - origin_y))

            points = []
            for start, end in zip(pixel_points, pixel_points[1:]):
                intersects = not (
                    max(start[0], end[0]) < -line_width
                    or min(start[0], end[0]) > _TILE_SIZE + line_width
                    or max(start[1], end[1]) < -line_width
                    or min(start[1], end[1]) > _TILE_SIZE + line_width
                )
                if intersects:
                    if not points:
                        points.append(start)
                    elif points[-1] != start:
                        if len(points) >= 2:
                            draw.line(points, fill=255, width=line_width, joint="curve")
                        points = [start]
                    points.append(end)
                elif points:
                    if len(points) >= 2:
                        draw.line(points, fill=255, width=line_width, joint="curve")
                    points = []
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
        rgba[:, :, 3][positive] = np.rint(210 + 45 * strength).astype(np.uint8)

    output = BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(output, format="PNG", optimize=True)
    return output.getvalue()


def _limit_vector_segments(
    segments: dict[int, list[list[tuple[float, float]]]],
    zoom: int,
    latitude: float,
    *,
    total_point_budget: int = _VECTOR_TOTAL_POINT_BUDGET,
    points_per_segment: int = _VECTOR_POINTS_PER_SEGMENT,
) -> list[tuple[int, list[tuple[float, float]]]]:
    """把当前视野压到小程序可流畅渲染的预算，同时按曲率保留弯道。"""
    prepared: list[tuple[int, list[tuple[float, float]]]] = []
    for activity_id, activity_segments in segments.items():
        for segment in activity_segments:
            reduced = _simplify_segment_for_zoom(segment, zoom, latitude)
            reduced = _sample_segment_to_limit(reduced, points_per_segment)
            if len(reduced) >= 2:
                prepared.append((activity_id, reduced))
    if not prepared:
        return []

    if len(prepared) * 2 > total_point_budget:
        # 极端碎片数据先保每个 activity 最长的一段，再按长度补齐，避免少数脏活动霸屏。
        longest_by_activity: dict[int, tuple[int, list[tuple[float, float]]]] = {}
        for item in prepared:
            previous = longest_by_activity.get(item[0])
            if previous is None or len(item[1]) > len(previous[1]):
                longest_by_activity[item[0]] = item
        selected = list(longest_by_activity.values())
        selected_ids = {id(item[1]) for item in selected}
        remaining = sorted(
            (item for item in prepared if id(item[1]) not in selected_ids),
            key=lambda item: len(item[1]),
            reverse=True,
        )
        prepared = (selected + remaining)[: total_point_budget // 2]

    total = sum(len(points) for _, points in prepared)
    if total <= total_point_budget:
        return prepared

    base = len(prepared) * 2
    extra_budget = max(0, total_point_budget - base)
    total_weight = sum(max(0, len(points) - 2) for _, points in prepared)
    limits = []
    remainders = []
    for _, points in prepared:
        weight = max(0, len(points) - 2)
        exact = extra_budget * weight / total_weight if total_weight else 0.0
        limits.append(min(len(points), 2 + int(math.floor(exact))))
        remainders.append(exact - math.floor(exact))
    used = sum(limits)
    for index in sorted(range(len(prepared)), key=lambda item: remainders[item], reverse=True):
        if used >= total_point_budget:
            break
        if limits[index] < len(prepared[index][1]):
            limits[index] += 1
            used += 1

    return [
        (activity_id, _sample_segment_to_limit(points, limits[index]))
        for index, (activity_id, points) in enumerate(prepared)
    ]


def _vector_point_budget_for_zoom(zoom: int) -> int:
    """开发者工具的矢量预览预算；真机仍使用 PNG 瓦片。

    293 次真实骑行实测中，20k 点会在微信渲染层膨胀成约 1.4 MB setData；
    因此城市预览锁在 12k。z14 以上视野已经足够小，允许 14k，
    避免山路和连续拐弯被二次抽稀。
    """
    if zoom <= 13:
        return 12_000
    return _VECTOR_TOTAL_POINT_BUDGET


def _vector_segment_intersects_bounds(
    start: tuple[float, float],
    end: tuple[float, float],
    west: float,
    south: float,
    east: float,
    north: float,
) -> bool:
    """Liang-Barsky 判断线段是否穿过视野，端点都在屏外时也不能漏线。"""
    x1, y1 = start
    dx = end[0] - x1
    dy = end[1] - y1
    t_min = 0.0
    t_max = 1.0
    for p, q in (
        (-dx, x1 - west),
        (dx, east - x1),
        (-dy, y1 - south),
        (dy, north - y1),
    ):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            if ratio > t_max:
                return False
            t_min = max(t_min, ratio)
        else:
            if ratio < t_min:
                return False
            t_max = min(t_max, ratio)
    return True


def _clip_vector_segments_to_bounds(
    segments: dict[int, list[list[tuple[float, float]]]],
    west: float,
    south: float,
    east: float,
    north: float,
) -> dict[int, list[list[tuple[float, float]]]]:
    """从长期缓存的总览源裁出当前帧，保留进出边界的相邻点。"""
    clipped: dict[int, list[list[tuple[float, float]]]] = defaultdict(list)
    for activity_id, activity_segments in segments.items():
        for segment in activity_segments:
            current: list[tuple[float, float]] = []
            for start, end in zip(segment, segment[1:]):
                if _vector_segment_intersects_bounds(
                    start,
                    end,
                    west,
                    south,
                    east,
                    north,
                ):
                    if not current:
                        current = [start]
                    elif current[-1] != start:
                        _append_segment(clipped, activity_id, current)
                        current = [start]
                    if current[-1] != end:
                        current.append(end)
                elif current:
                    _append_segment(clipped, activity_id, current)
                    current = []
            _append_segment(clipped, activity_id, current)
    return clipped


def _heatmap_bounds_from_segments(
    segments: dict[int, list[list[tuple[float, float]]]],
) -> tuple[list[list[float]], list[list[float]]]:
    """从原始点派生的连续段计算全局和常骑区域范围，不读取压缩轨迹。"""
    all_bounds = [math.inf, math.inf, -math.inf, -math.inf]
    buckets: dict[tuple[int, int], list[float]] = {}
    for activity_segments in segments.values():
        for segment in activity_segments:
            for lon, lat in segment:
                all_bounds[0] = min(all_bounds[0], lon)
                all_bounds[1] = min(all_bounds[1], lat)
                all_bounds[2] = max(all_bounds[2], lon)
                all_bounds[3] = max(all_bounds[3], lat)
                key = (math.floor(lat * 2), math.floor(lon * 2))
                bucket = buckets.setdefault(
                    key,
                    [0.0, math.inf, math.inf, -math.inf, -math.inf],
                )
                bucket[0] += 1
                bucket[1] = min(bucket[1], lon)
                bucket[2] = min(bucket[2], lat)
                bucket[3] = max(bucket[3], lon)
                bucket[4] = max(bucket[4], lat)

    if not buckets:
        return [], []

    best_key = max(buckets, key=lambda key: buckets[key][0])
    focus_bounds = [math.inf, math.inf, -math.inf, -math.inf]
    for key, bucket in buckets.items():
        if abs(key[0] - best_key[0]) > 1 or abs(key[1] - best_key[1]) > 1:
            continue
        focus_bounds[0] = min(focus_bounds[0], bucket[1])
        focus_bounds[1] = min(focus_bounds[1], bucket[2])
        focus_bounds[2] = max(focus_bounds[2], bucket[3])
        focus_bounds[3] = max(focus_bounds[3], bucket[4])

    def as_points(bounds: list[float]) -> list[list[float]]:
        return [
            [round(bounds[0], 6), round(bounds[1], 6)],
            [round(bounds[2], 6), round(bounds[3], 6)],
        ]

    return as_points(focus_bounds), as_points(all_bounds)


def _available_heatmap_years(
    db: Session,
    user_id: int,
    include_private: bool,
    activity_ids: set[int] | None,
) -> list[int]:
    if activity_ids == set():
        return []
    filters = _activity_filters(user_id, None, include_private)
    if activity_ids is not None:
        filters.append(Activity.id.in_(activity_ids))
    rows = (
        db.query(Activity.started_at)
        .join(Trackpoint, Trackpoint.activity_id == Activity.id)
        .filter(*filters)
        .distinct()
        .all()
    )
    return sorted(
        {
            started_at.astimezone(_BEIJING_TZ).year
            for (started_at,) in rows
            if isinstance(started_at, datetime)
        },
        reverse=True,
    )


def _available_heatmap_years_cached(
    db: Session,
    user_id: int,
    include_private: bool,
    generation: int,
    activity_fingerprint: str,
    privacy_fingerprint: str | None,
    redis_client,
) -> list[int]:
    """按数据代缓存年份，固定块视野请求不能各自重复扫描 Trackpoint。"""
    key = (
        f"{_AVAILABLE_YEARS_REDIS_PREFIX}{user_id}:g{generation}:"
        f"data_{activity_fingerprint}:"
        f"audience_{'owner' if include_private else 'public'}"
    )
    if privacy_fingerprint is not None:
        key += f":privacy_{privacy_fingerprint}"
    try:
        cached = redis_client.get(key)
        if isinstance(cached, bytes):
            decoded = json.loads(cached.decode())
            if isinstance(decoded, list):
                return [int(year) for year in decoded]
    except Exception:
        pass
    years = _available_heatmap_years(db, user_id, include_private, None)
    try:
        redis_client.setex(
            key,
            _AVAILABLE_YEARS_REDIS_TTL_SEC,
            json.dumps(years, separators=(",", ":")).encode(),
        )
    except Exception:
        pass
    return years


def _heatmap_activity_ids_for_city(
    db: Session,
    user_id: int,
    include_private: bool,
    city: str | None,
) -> set[int] | None:
    """城市筛选优先用 Activity.city；历史 NULL 行从首个原始 Trackpoint 重新推断。"""
    if city is None:
        return None
    first_seq = (
        db.query(
            Trackpoint.activity_id.label("activity_id"),
            func.min(Trackpoint.seq).label("first_seq"),
        )
        .join(Activity, Activity.id == Trackpoint.activity_id)
        .filter(*_activity_filters(user_id, None, include_private))
        .group_by(Trackpoint.activity_id)
        .subquery()
    )
    rows = (
        db.query(
            Activity.id,
            Activity.city,
            Trackpoint.latitude,
            Trackpoint.longitude,
        )
        .join(first_seq, first_seq.c.activity_id == Activity.id)
        .join(
            Trackpoint,
            and_(
                Trackpoint.activity_id == first_seq.c.activity_id,
                Trackpoint.seq == first_seq.c.first_seq,
            ),
        )
        .filter(*_activity_filters(user_id, None, include_private))
        .all()
    )
    selected = set()
    for activity_id, stored_city, latitude, longitude in rows:
        resolved_city = stored_city
        if resolved_city is None:
            resolved_city = infer_city_from_coords(latitude, longitude)
        if resolved_city == city:
            selected.add(int(activity_id))
    return selected


def _load_heatmap_meta_bounds(
    db: Session,
    user_id: int,
    year: int | None,
    include_private: bool,
    activity_ids: set[int] | None,
) -> tuple[int, list[list[float]], list[list[float]]]:
    """直接在 PostgreSQL 聚合原始连续段范围；meta 不必构造并回传整批折线。"""
    if activity_ids == set():
        return 0, [], []
    params: dict[str, object] = {
        "user_id": user_id,
        "untimed_gap_m": _RAW_UNTIMED_GAP_METERS,
        "max_elapsed_s": 45,
        "max_speed_mps": 45,
    }
    year_window = _year_window_utc(year)
    year_clause = ""
    if year_window is not None:
        year_clause = "AND a.started_at >= :year_start AND a.started_at < :year_end"
        params.update({"year_start": year_window[0], "year_end": year_window[1]})
    privacy_clause = ""
    if not include_private:
        privacy_clause = "AND (ap.activity_id IS NULL OR ap.visibility = 'public')"
    activity_clause = ""
    if activity_ids is not None:
        activity_clause = "AND a.id = ANY(CAST(:activity_ids AS integer[]))"
        params["activity_ids"] = sorted(activity_ids)

    row = db.execute(
        text(f"""
            WITH ordered AS (
                SELECT
                    tp.activity_id,
                    tp.seq,
                    tp.timestamp,
                    tp.longitude,
                    tp.latitude,
                    COALESCE(
                        tp.geom,
                        ST_SetSRID(ST_MakePoint(tp.longitude, tp.latitude), 4326)
                    ) AS geom,
                    LAG(tp.seq) OVER activity_order AS previous_seq,
                    LAG(tp.timestamp) OVER activity_order AS previous_timestamp,
                    LAG(COALESCE(
                        tp.geom,
                        ST_SetSRID(ST_MakePoint(tp.longitude, tp.latitude), 4326)
                    )) OVER activity_order AS previous_geom
                FROM trackpoints tp
                JOIN activities a ON a.id = tp.activity_id
                LEFT JOIN activity_privacy ap ON ap.activity_id = a.id
                WHERE a.user_id = :user_id
                  AND a.status = 'completed'
                  AND a.duplicate_of IS NULL
                  AND a.activity_type = 'cycling'
                  {year_clause}
                  {activity_clause}
                  {privacy_clause}
                WINDOW activity_order AS (
                    PARTITION BY tp.activity_id ORDER BY tp.seq
                )
            ),
            measured AS (
                SELECT
                    *,
                    CASE
                        WHEN previous_geom IS NULL THEN NULL
                        ELSE ST_DistanceSphere(geom, previous_geom)
                    END AS distance_m,
                    CASE
                        WHEN previous_timestamp IS NULL OR timestamp IS NULL THEN NULL
                        ELSE EXTRACT(EPOCH FROM timestamp - previous_timestamp)
                    END AS elapsed_s
                FROM ordered
            ),
            marked AS (
                SELECT
                    *,
                    CASE
                        WHEN previous_seq IS NULL THEN 0
                        WHEN seq <> previous_seq + 1 THEN 1
                        WHEN elapsed_s IS NULL AND distance_m > :untimed_gap_m THEN 1
                        WHEN elapsed_s <= 0 OR elapsed_s > :max_elapsed_s THEN 1
                        WHEN distance_m / NULLIF(elapsed_s, 0) > :max_speed_mps THEN 1
                        ELSE 0
                    END AS starts_segment
                FROM measured
            ),
            segmented AS (
                SELECT
                    *,
                    SUM(starts_segment) OVER (
                        PARTITION BY activity_id ORDER BY seq
                        ROWS UNBOUNDED PRECEDING
                    ) AS segment_id
                FROM marked
            ),
            valid_segments AS (
                SELECT activity_id, segment_id
                FROM segmented
                GROUP BY activity_id, segment_id
                HAVING COUNT(*) >= 2
            ),
            valid_points AS (
                SELECT
                    segmented.activity_id,
                    segmented.longitude,
                    segmented.latitude,
                    FLOOR(segmented.latitude * 2)::integer AS lat_bucket,
                    FLOOR(segmented.longitude * 2)::integer AS lon_bucket
                FROM segmented
                JOIN valid_segments USING (activity_id, segment_id)
            ),
            bucket_counts AS (
                SELECT lat_bucket, lon_bucket, COUNT(*) AS point_count
                FROM valid_points
                GROUP BY lat_bucket, lon_bucket
            ),
            best_bucket AS (
                SELECT lat_bucket, lon_bucket
                FROM bucket_counts
                ORDER BY point_count DESC, lat_bucket, lon_bucket
                LIMIT 1
            )
            SELECT
                COUNT(DISTINCT valid_points.activity_id) AS activity_count,
                MIN(valid_points.longitude) AS all_west,
                MIN(valid_points.latitude) AS all_south,
                MAX(valid_points.longitude) AS all_east,
                MAX(valid_points.latitude) AS all_north,
                MIN(valid_points.longitude) FILTER (
                    WHERE ABS(valid_points.lat_bucket - (SELECT lat_bucket FROM best_bucket)) <= 1
                      AND ABS(valid_points.lon_bucket - (SELECT lon_bucket FROM best_bucket)) <= 1
                ) AS focus_west,
                MIN(valid_points.latitude) FILTER (
                    WHERE ABS(valid_points.lat_bucket - (SELECT lat_bucket FROM best_bucket)) <= 1
                      AND ABS(valid_points.lon_bucket - (SELECT lon_bucket FROM best_bucket)) <= 1
                ) AS focus_south,
                MAX(valid_points.longitude) FILTER (
                    WHERE ABS(valid_points.lat_bucket - (SELECT lat_bucket FROM best_bucket)) <= 1
                      AND ABS(valid_points.lon_bucket - (SELECT lon_bucket FROM best_bucket)) <= 1
                ) AS focus_east,
                MAX(valid_points.latitude) FILTER (
                    WHERE ABS(valid_points.lat_bucket - (SELECT lat_bucket FROM best_bucket)) <= 1
                      AND ABS(valid_points.lon_bucket - (SELECT lon_bucket FROM best_bucket)) <= 1
                ) AS focus_north
            FROM valid_points
        """),
        params,
    ).one()
    activity_count = int(row.activity_count or 0)
    if activity_count == 0:
        return 0, [], []

    def as_points(west, south, east, north) -> list[list[float]]:
        return [
            [round(float(west), 6), round(float(south), 6)],
            [round(float(east), 6), round(float(north), 6)],
        ]

    return (
        activity_count,
        as_points(row.focus_west, row.focus_south, row.focus_east, row.focus_north),
        as_points(row.all_west, row.all_south, row.all_east, row.all_north),
    )


def get_user_heatmap_overview(
    db: Session,
    user_id: int,
    *,
    year: int | None = None,
    detail: str = "full",
    include_private: bool = True,
    city: str | None = None,
    generation: int | None = None,
    privacy_fingerprint: str | None = None,
    activity_fingerprint: str | None = None,
    redis_client=None,
) -> dict:
    """用共享原始轨迹源生成 meta/card/full；兼容路径也不能复活坏压缩轨迹。"""
    if detail not in {"meta", "card", "full"}:
        raise InvalidHeatmapTile("invalid heatmap overview detail")
    _year_window_utc(year)
    activity_ids = _heatmap_activity_ids_for_city(
        db,
        user_id,
        include_private,
        city,
    )
    if redis_client is None:
        redis_client = _get_redis_client()
    if generation is None:
        try:
            generation = int(
                redis_client.get(f"{_GENERATION_PREFIX}{user_id}") or 0
            )
        except Exception:
            generation = 0
    if not include_private and privacy_fingerprint is None:
        privacy_fingerprint = _public_heatmap_privacy_fingerprint(db, user_id)
    if activity_fingerprint is None:
        activity_fingerprint = _heatmap_activity_fingerprint(
            db,
            user_id,
            include_private,
        )
    available_years = (
        _available_heatmap_years_cached(
            db,
            user_id,
            include_private,
            generation,
            activity_fingerprint,
            privacy_fingerprint,
            redis_client,
        )
        if activity_ids is None
        else _available_heatmap_years(
            db,
            user_id,
            include_private,
            activity_ids,
        )
    )
    cache_version = _heatmap_cache_version(generation, activity_fingerprint)

    segments = _get_overview_segments_cached(
        db,
        user_id,
        year,
        include_private,
        generation,
        privacy_fingerprint,
        redis_client,
        activity_fingerprint,
    )
    if activity_ids is not None:
        segments = {
            activity_id: activity_segments
            for activity_id, activity_segments in segments.items()
            if activity_id in activity_ids
        }
    focus_points, all_points = _heatmap_bounds_from_segments(segments)
    activity_count = len(segments)
    tracks: list[list[list[float]]] = []
    if detail != "meta" and all_points:
        latitude = (all_points[0][1] + all_points[1][1]) / 2
        prepared = _limit_vector_segments(
            segments,
            9 if detail == "card" else 10,
            latitude,
            total_point_budget=4_000 if detail == "card" else 9_000,
        )
        tracks = [
            [[round(lon, 6), round(lat, 6)] for lon, lat in points]
            for _, points in prepared
        ]
    return {
        "city": city,
        "tracks": tracks,
        "activity_count": activity_count,
        "generation": generation,
        "cache_version": cache_version,
        "available_years": available_years,
        "selected_year": year,
        "focus_points": focus_points if detail == "meta" else [],
        "all_points": all_points if detail == "meta" else [],
    }


def _touch_vector_cache(redis_client, user_id: int, cache_key: str) -> None:
    lru_key = f"{_VECTOR_LRU_PREFIX}{user_id}"
    redis_client.expire(cache_key, _VECTOR_CACHE_TTL_SEC)
    redis_client.zadd(lru_key, {cache_key: time_ns()})
    redis_client.expire(lru_key, _VECTOR_CACHE_TTL_SEC)


def _trim_vector_cache(redis_client, user_id: int, current_key: str) -> None:
    """按最近使用淘汰矢量视野帧，防止预取随机删掉刚访问的高密度块。"""
    try:
        keys = [
            key
            for key in redis_client.scan_iter(match=f"{_VECTOR_CACHE_PREFIX}{user_id}:*")
            if not (
                key.decode() if isinstance(key, bytes) else str(key)
            ).endswith(":build")
        ]
        _touch_vector_cache(redis_client, user_id, current_key)
        lru_key = f"{_VECTOR_LRU_PREFIX}{user_id}"
        actual = {
            key.decode() if isinstance(key, bytes) else str(key): key
            for key in keys
        }
        missing = {
            key: 0
            for key in actual
            if redis_client.zscore(lru_key, key) is None
        }
        if missing:
            redis_client.zadd(lru_key, missing)
        members = redis_client.zrange(lru_key, 0, -1)
        member_names = [
            item.decode() if isinstance(item, bytes) else str(item)
            for item in members
        ]
        stale = [item for item in member_names if item not in actual]
        if stale:
            redis_client.zrem(lru_key, *stale)
        if len(keys) <= _VECTOR_MAX_CACHE_KEYS:
            return
        overflow = len(keys) - _VECTOR_MAX_CACHE_KEYS
        victims = [
            actual[name]
            for name in member_names
            if name in actual and name != current_key
        ][:overflow]
        if victims:
            redis_client.delete(*victims)
            redis_client.zrem(
                lru_key,
                *[
                    key.decode() if isinstance(key, bytes) else str(key)
                    for key in victims
                ],
            )
    except Exception:
        pass


def get_user_heatmap_viewport(
    db: Session,
    user_id: int,
    viewport: tuple[float, float, float, float, int],
    *,
    year: int | None = None,
    include_private: bool = True,
    activity_fingerprint: str | None = None,
    _consistency_retry: int = 0,
) -> dict:
    """返回当前视野的原始连续轨迹 LOD；只作为图片图层真实失败时的降级。"""
    west, south, east, north, zoom = viewport
    _year_window_utc(year)
    if not (
        -180 <= west < east <= 180
        and -90 <= south < north <= 90
        and 3 <= zoom <= 20
    ):
        raise InvalidHeatmapTile("invalid heatmap viewport")

    redis_client = _get_redis_client()
    try:
        raw_generation = redis_client.get(f"{_GENERATION_PREFIX}{user_id}")
        generation = int(raw_generation or 0)
    except Exception:
        generation = 0
    privacy_fingerprint = (
        None
        if include_private
        else _public_heatmap_privacy_fingerprint(db, user_id)
    )
    if activity_fingerprint is None:
        activity_fingerprint = _heatmap_activity_fingerprint(
            db,
            user_id,
            include_private,
        )
    cache_version = _heatmap_cache_version(generation, activity_fingerprint)

    def activity_snapshot_changed() -> bool:
        current_fingerprint = _heatmap_activity_fingerprint(
            db,
            user_id,
            include_private,
        )
        return current_fingerprint != activity_fingerprint

    def retry_after_activity_snapshot_change() -> dict:
        if _consistency_retry >= 2:
            raise HeatmapSnapshotChanged(
                "heatmap activity snapshot changed during render"
            )
        return get_user_heatmap_viewport(
            db,
            user_id,
            viewport,
            year=year,
            include_private=include_private,
            _consistency_retry=_consistency_retry + 1,
        )

    bounds_key = ":".join(
        str(value).replace("-", "m").replace(".", "p")
        for value in (west, south, east, north, zoom)
    )
    cache_key = (
        f"{_VECTOR_CACHE_PREFIX}{user_id}:g{generation}:data_{activity_fingerprint}:"
        f"year_{year or 'all'}:"
        f"audience_{'owner' if include_private else 'public'}:{bounds_key}"
    )
    if privacy_fingerprint is not None:
        cache_key += f":privacy_{privacy_fingerprint}"
    cached_result = None
    try:
        cached = redis_client.get(cache_key)
        if isinstance(cached, bytes):
            cached_result = json.loads(zlib.decompress(cached).decode())
    except Exception:
        pass
    if cached_result is not None:
        try:
            _touch_vector_cache(redis_client, user_id, cache_key)
        except Exception:
            pass
        if activity_snapshot_changed():
            return retry_after_activity_snapshot_change()
        return cached_result

    lock, waited_result = _claim_derived_cache_build(
        redis_client,
        cache_key,
        lambda raw: json.loads(zlib.decompress(raw).decode()),
    )
    if isinstance(waited_result, dict):
        if activity_snapshot_changed():
            return retry_after_activity_snapshot_change()
        return waited_result

    try:
        if zoom <= 13:
            # 城市总览复用 7 天 Redis 原始派生源：第一次从 PG 构建，之后换区域只做
            # 内存裁切，不再为每次拖图重新扫描 40 万级 Trackpoint。该源先按
            # seq/time/speed 切段，再以约 2 米容差保曲率，不读取 simplified_track。
            overview_segments = _get_overview_segments_cached(
                db,
                user_id,
                year,
                include_private,
                generation,
                privacy_fingerprint,
                redis_client,
                activity_fingerprint,
            )
            segments = _clip_vector_segments_to_bounds(
                overview_segments,
                west,
                south,
                east,
                north,
            )
        else:
            # z14 以上从导入后异步生成的高精度 source tiles 读取；分块保留全部原始
            # 几何点且不做固定点数截断，保持已经验收的山路/拐弯细节。旧用户或预热
            # 失败时才降级查当前范围 PG，不能因为性能层缺失让热图打不开。
            segments = _get_detail_segments_cached_for_bounds(
                redis_client,
                user_id,
                generation,
                activity_fingerprint,
                year,
                include_private,
                privacy_fingerprint,
                west,
                south,
                east,
                north,
            )
            if segments is None:
                _enqueue_detail_source_prewarm_if_needed(
                    user_id, generation, year, include_private
                )
                segments = _load_raw_segments_for_bounds(
                    db,
                    user_id,
                    year,
                    west,
                    south,
                    east,
                    north,
                    include_private,
                )
        prepared = _limit_vector_segments(
            segments,
            zoom,
            (south + north) / 2,
            total_point_budget=_vector_point_budget_for_zoom(zoom),
        )
        available_years = _available_heatmap_years_cached(
            db,
            user_id,
            include_private,
            generation,
            activity_fingerprint,
            privacy_fingerprint,
            redis_client,
        )
        result = {
            "city": None,
            "tracks": [
                [[round(lon, 6), round(lat, 6)] for lon, lat in points]
                for _, points in prepared
            ],
            "activity_count": len({activity_id for activity_id, _ in prepared}),
            "generation": generation,
            "cache_version": cache_version,
            "available_years": available_years,
            "selected_year": year,
            "focus_points": [],
            "all_points": [],
        }
        if activity_snapshot_changed():
            _release_derived_cache_build(lock)
            lock = None
            return retry_after_activity_snapshot_change()
        try:
            redis_client.setex(
                cache_key,
                _VECTOR_CACHE_TTL_SEC,
                zlib.compress(
                    json.dumps(result, separators=(",", ":")).encode(),
                    level=6,
                ),
            )
            _trim_vector_cache(redis_client, user_id, cache_key)
        except Exception:
            pass
        return result
    finally:
        _release_derived_cache_build(lock)


def get_user_heatmap_tile(
    db: Session,
    user_id: int,
    zoom: int,
    x: int,
    y: int,
    *,
    year: int | None = None,
    color: str = "orange",
    include_private: bool = True,
    activity_fingerprint: str | None = None,
    _consistency_retry: int = 0,
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
    privacy_fingerprint = (
        None
        if include_private
        else _public_heatmap_privacy_fingerprint(db, user_id)
    )
    if activity_fingerprint is None:
        activity_fingerprint = _heatmap_activity_fingerprint(
            db,
            user_id,
            include_private,
        )

    def activity_snapshot_changed() -> bool:
        current_fingerprint = _heatmap_activity_fingerprint(
            db,
            user_id,
            include_private,
        )
        return current_fingerprint != activity_fingerprint

    def retry_after_activity_snapshot_change() -> bytes:
        if _consistency_retry >= 2:
            raise HeatmapSnapshotChanged(
                "heatmap activity snapshot changed during render"
            )
        return get_user_heatmap_tile(
            db,
            user_id,
            zoom,
            x,
            y,
            year=year,
            color=color,
            include_private=include_private,
            _consistency_retry=_consistency_retry + 1,
        )

    cache_key = (
        f"{_CACHE_PREFIX}{user_id}:g{generation}:data_{activity_fingerprint}:"
        f"year_{year or 'all'}:"
        f"audience_{'owner' if include_private else 'public'}:"
        f"color_{color}:z{zoom}:{x}:{y}"
    )
    if privacy_fingerprint is not None:
        cache_key += f":privacy_{privacy_fingerprint}"
    cached_png = None
    try:
        cached = redis_client.get(cache_key)
        if isinstance(cached, bytes):
            cached_png = cached
    except Exception:
        pass
    if cached_png is not None:
        if activity_snapshot_changed():
            return retry_after_activity_snapshot_change()
        return cached_png

    lock, waited_png = _claim_derived_cache_build(
        redis_client,
        cache_key,
        lambda raw: raw,
    )
    if isinstance(waited_png, bytes):
        if activity_snapshot_changed():
            return retry_after_activity_snapshot_change()
        return waited_png

    try:
        overview = zoom <= 13
        if overview:
            segments = _get_overview_segments_cached(
                db,
                user_id,
                year,
                include_private,
                generation,
                privacy_fingerprint,
                redis_client,
                activity_fingerprint,
            )
        else:
            west, south, east, north = _tile_query_bounds_wgs84(zoom, x, y)
            segments = _get_detail_segments_cached_for_bounds(
                redis_client,
                user_id,
                generation,
                activity_fingerprint,
                year,
                include_private,
                privacy_fingerprint,
                west,
                south,
                east,
                north,
            )
            if segments is None:
                _enqueue_detail_source_prewarm_if_needed(
                    user_id, generation, year, include_private
                )
                segments = _load_raw_segments(
                    db,
                    user_id,
                    year,
                    zoom,
                    x,
                    y,
                    include_private,
                )
        if overview:
            segments = _get_overview_map_segments_cached(
                segments,
                user_id,
                year,
                include_private,
                generation,
                privacy_fingerprint,
                activity_fingerprint,
            )
        rendered = _render_tile_png(
            segments,
            zoom,
            x,
            y,
            color,
            coordinates_are_map=overview,
        )
        if activity_snapshot_changed():
            _release_derived_cache_build(lock)
            lock = None
            return retry_after_activity_snapshot_change()
        try:
            redis_client.setex(cache_key, _CACHE_TTL_SEC, rendered)
        except Exception:
            pass
        return rendered
    finally:
        _release_derived_cache_build(lock)
