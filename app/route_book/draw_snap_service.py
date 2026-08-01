"""
手画路线贴路预览——把用户刚画的草稿线临时贴到道路上。

干啥用：route-draw 页面松手后调用本模块，先返回一条可预览的贴路线；用户确认保存前绝不写数据库。
操作注意事项：输入点是小程序地图的 GCJ-02 `[lon, lat]`；这里只返回 GCJ-02 给地图展示，正式入库由保存接口转 WGS-84。
输入输出：输入一小段手画点 → 校验、抽稀、分段调用腾讯骑行路线 → 输出 raw/snapped/anchor 三组点和距离。
"""

from __future__ import annotations

import heapq
import math
from typing import Any

from app.parsing.geo_math import haversine
from app.route_book.tencent_direction import TencentMapError, plan_tencent_bicycling_route


MAX_RAW_POINTS = 120
MAX_ANCHOR_POINTS = 11
MAX_SEGMENTS = 10
MAX_SNAPPED_PREVIEW_POINTS = 300
MAX_CANONICAL_POINTS = 5000
MAX_CANONICAL_SIMPLIFICATION_ERROR_M = 1.0
SNAP_PREVIEW_TOTAL_TIMEOUT_SEC = 12.0
SNAP_PREVIEW_MAX_SINGLE_TIMEOUT_SEC = 3.0
SIMPLIFY_TOLERANCE_M = 30.0
MIN_PREVIEW_DISTANCE_M = 5.0
DETOUR_RATIO_THRESHOLD = 1.8
DETOUR_EXTRA_DISTANCE_M = 1000.0
DETOUR_RATIO_MIN_EXTRA_M = 100.0


class DrawSnapSegmentError(ValueError):
    """某一段腾讯贴路失败；router 用它告诉前端哪一段该重画。"""

    def __init__(self, segment_index: int, reason: str):
        self.segment_index = segment_index
        self.reason = reason
        super().__init__("这段没有贴上路，换短一点再试。")


def build_snap_preview(
    *,
    mode: str,
    coordinate_system: str,
    points: list[tuple[float, float]],
    supports_detour_confirmation: bool = False,
) -> dict[str, Any]:
    if coordinate_system != "gcj02":
        raise ValueError("coordinate_system 只支持 gcj02")

    raw_points = _normalize_points(points)
    raw_distance_m = _distance_m(raw_points)
    if raw_distance_m < MIN_PREVIEW_DISTANCE_M:
        raise ValueError("再多画一点路线")

    if mode == "freehand":
        return {
            "mode": mode,
            "coordinate_system": coordinate_system,
            "snapped_points": raw_points,
            "display_points": raw_points,
            "raw_points": raw_points,
            "anchor_points": raw_points,
            "raw_distance_m": raw_distance_m,
            "distance_m": raw_distance_m,
            "provider_distance_m": raw_distance_m,
            "segment_count": len(raw_points) - 1,
            "provider_point_count": len(raw_points),
            "requires_confirmation": False,
            "warnings": [],
            "failed_segment": None,
        }
    if mode != "snap":
        raise ValueError("mode 只支持 snap 或 freehand")

    anchor_points = _simplify_anchor_points(raw_points)
    segment_count = len(anchor_points) - 1
    if len(anchor_points) > MAX_ANCHOR_POINTS or segment_count > MAX_SEGMENTS:
        raise ValueError("这一段太长了，分几段画更稳")

    timeout_sec = _timeout_per_segment(segment_count)
    snapped_points: list[list[float]] = []
    provider_distance_m = 0.0
    for index, (start, end) in enumerate(zip(anchor_points, anchor_points[1:])):
        try:
            planned = plan_tencent_bicycling_route(
                (start[1], start[0]),
                (end[1], end[0]),
                timeout_sec=timeout_sec,
            )
            segment_points = _planned_points_to_lonlat(planned.get("points") or [])
        except TencentMapError as exc:
            raise DrawSnapSegmentError(index, str(exc)) from exc

        if snapped_points and segment_points and _same_point(snapped_points[-1], segment_points[0]):
            segment_points = segment_points[1:]
        snapped_points.extend(segment_points)
        provider_distance_m += _finite_float(planned.get("distance")) or _distance_m(segment_points)

    if len(snapped_points) < 2:
        raise TencentMapError("腾讯地图没有返回可用路线")

    provider_point_count = len(snapped_points)
    detour_extra_m = provider_distance_m - raw_distance_m
    requires_confirmation = raw_distance_m > 0 and (
        detour_extra_m > DETOUR_EXTRA_DISTANCE_M
        or (
            provider_distance_m > raw_distance_m * DETOUR_RATIO_THRESHOLD
            and detour_extra_m > DETOUR_RATIO_MIN_EXTRA_M
        )
    )
    warnings: list[str] = []
    if requires_confirmation:
        if not supports_detour_confirmation:
            raise ValueError("这段绕行明显，请更新后改用手绘或确认绕行")
        warnings.append("系统贴出的路线可能偏离你的手画线，请检查后再保存。")
    snapped_points, display_points = _simplify_preview_points(snapped_points)
    preview_distance_m = _distance_m(snapped_points)

    return {
        "mode": mode,
        "coordinate_system": coordinate_system,
        "snapped_points": snapped_points,
        "display_points": display_points,
        "raw_points": raw_points,
        "anchor_points": anchor_points,
        "raw_distance_m": raw_distance_m,
        "distance_m": preview_distance_m,
        "provider_distance_m": provider_distance_m,
        "segment_count": segment_count,
        "provider_point_count": provider_point_count,
        "requires_confirmation": requires_confirmation,
        "warnings": warnings,
        "failed_segment": None,
    }


def _normalize_points(points: list[tuple[float, float]]) -> list[list[float]]:
    if len(points) < 2:
        raise ValueError("再多画一点路线")
    if len(points) > MAX_RAW_POINTS:
        raise ValueError(f"单次预览最多支持 {MAX_RAW_POINTS} 个点")

    normalized: list[list[float]] = []
    for index, (lon, lat) in enumerate(points):
        lon = float(lon)
        lat = float(lat)
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError(f"第 {index + 1} 个路线点不是有效数字")
        if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            raise ValueError(f"第 {index + 1} 个路线点超出经纬度范围")
        normalized.append([lon, lat])
    return normalized


def _distance_m(points: list[list[float]]) -> float:
    total = 0.0
    for prev, curr in zip(points, points[1:]):
        total += haversine(prev[1], prev[0], curr[1], curr[0])
    return total


def _simplify_anchor_points(points: list[list[float]]) -> list[list[float]]:
    if len(points) <= 2:
        return points
    indices = _rdp_indices(points, 0, len(points) - 1, SIMPLIFY_TOLERANCE_M)
    return [points[index] for index in indices]


def _simplify_preview_points(points: list[list[float]]) -> tuple[list[list[float]], list[list[float]]]:
    """展示线固定预算；正式几何只有在误差不超过 1m 时才使用抽稀结果。"""
    if len(points) <= MAX_SNAPPED_PREVIEW_POINTS:
        return points, points
    indices, remaining_error_m = _rdp_budget_indices(
        points,
        MAX_SNAPPED_PREVIEW_POINTS,
        tolerance_m=MAX_CANONICAL_SIMPLIFICATION_ERROR_M,
    )
    display_points = [points[index] for index in indices]
    canonical_points = (
        display_points
        if remaining_error_m <= MAX_CANONICAL_SIMPLIFICATION_ERROR_M
        else points
    )
    if len(canonical_points) > MAX_CANONICAL_POINTS:
        raise ValueError("这段道路细节太多，请缩短一段再点，或改用手绘")
    return canonical_points, display_points


def _rdp_budget_indices(
    points: list[list[float]],
    limit: int,
    *,
    tolerance_m: float,
) -> tuple[list[int], float]:
    """在固定点数预算内优先保留偏差最大的转折，限制最坏扫描次数。"""
    kept = {0, len(points) - 1}
    candidates: list[tuple[float, int, int, int]] = []
    _push_rdp_candidate(candidates, points, 0, len(points) - 1)

    while candidates and len(kept) < limit:
        negative_distance, start, end, index = heapq.heappop(candidates)
        if -negative_distance <= tolerance_m:
            break
        kept.add(index)
        _push_rdp_candidate(candidates, points, start, index)
        _push_rdp_candidate(candidates, points, index, end)
    remaining_error_m = -candidates[0][0] if candidates else 0.0
    return sorted(kept), remaining_error_m


def _push_rdp_candidate(
    candidates: list[tuple[float, int, int, int]],
    points: list[list[float]],
    start: int,
    end: int,
) -> None:
    if end - start <= 1:
        return
    max_distance = -1.0
    max_index = start
    for index in range(start + 1, end):
        distance = _perpendicular_distance_m(points[index], points[start], points[end])
        if distance > max_distance:
            max_distance = distance
            max_index = index
    heapq.heappush(candidates, (-max_distance, start, end, max_index))


def _rdp_indices(points: list[list[float]], start: int, end: int, tolerance_m: float) -> list[int]:
    kept = {start, end}
    pending = [(start, end)]
    while pending:
        segment_start, segment_end = pending.pop()
        max_distance = -1.0
        max_index = segment_start
        for index in range(segment_start + 1, segment_end):
            distance = _perpendicular_distance_m(
                points[index],
                points[segment_start],
                points[segment_end],
            )
            if distance > max_distance:
                max_distance = distance
                max_index = index
        if max_distance > tolerance_m:
            kept.add(max_index)
            pending.append((segment_start, max_index))
            pending.append((max_index, segment_end))
    return sorted(kept)


def _perpendicular_distance_m(point: list[float], start: list[float], end: list[float]) -> float:
    origin_lon = start[0]
    origin_lat = start[1]
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(origin_lat))

    px = (point[0] - origin_lon) * lon_scale
    py = (point[1] - origin_lat) * lat_scale
    sx = 0.0
    sy = 0.0
    ex = (end[0] - origin_lon) * lon_scale
    ey = (end[1] - origin_lat) * lat_scale

    dx = ex - sx
    dy = ey - sy
    if dx == 0 and dy == 0:
        return math.hypot(px - sx, py - sy)

    t = ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    nearest_x = sx + t * dx
    nearest_y = sy + t * dy
    return math.hypot(px - nearest_x, py - nearest_y)


def _timeout_per_segment(segment_count: int) -> float:
    if segment_count <= 0:
        raise ValueError("再多画一点路线")
    return min(SNAP_PREVIEW_MAX_SINGLE_TIMEOUT_SEC, SNAP_PREVIEW_TOTAL_TIMEOUT_SEC / segment_count)


def _planned_points_to_lonlat(points: list[dict[str, float]]) -> list[list[float]]:
    result: list[list[float]] = []
    for index, point in enumerate(points):
        lat = _finite_float(point.get("lat"))
        lon = _finite_float(point.get("lon"))
        if lon is None or lat is None:
            raise TencentMapError(f"腾讯第 {index + 1} 个路线点格式异常")
        if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            raise TencentMapError(f"腾讯第 {index + 1} 个路线点越界")
        result.append([lon, lat])
    if len(result) < 2:
        raise TencentMapError("腾讯地图没有返回可用路线")
    return result


def _finite_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _same_point(a: list[float], b: list[float]) -> bool:
    return abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9
