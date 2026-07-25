"""
手画路线贴路预览——把用户刚画的草稿线临时贴到道路上。

干啥用：route-draw 页面松手后调用本模块，先返回一条可预览的贴路线；用户确认保存前绝不写数据库。
操作注意事项：输入点是小程序地图的 GCJ-02 `[lon, lat]`；这里只返回 GCJ-02 给地图展示，正式入库由保存接口转 WGS-84。
输入输出：输入一小段手画点 → 校验、抽稀、分段调用腾讯骑行路线 → 输出预览点与短 receipt；
完整腾讯几何和 steps 只留在服务端 Redis，正式保存时再按 receipt 重建。
"""

from __future__ import annotations

import math
from typing import Any

from app.parsing.geo_math import haversine
from app.route_book.routing_evidence import build_tencent_evidence, store_snap_receipt
from app.route_book.tencent_direction import TencentMapError, plan_tencent_bicycling_route


MAX_RAW_POINTS = 120
MAX_ANCHOR_POINTS = 11
MAX_SEGMENTS = 10
SNAP_PREVIEW_TOTAL_TIMEOUT_SEC = 12.0
SNAP_PREVIEW_MAX_SINGLE_TIMEOUT_SEC = 3.0
SIMPLIFY_TOLERANCE_M = 30.0
MIN_PREVIEW_DISTANCE_M = 5.0
MAX_PROVIDER_JOIN_GAP_M = 20.0


class DrawSnapSegmentError(ValueError):
    """某一段腾讯贴路失败；router 用它告诉前端哪一段该重画。"""

    def __init__(self, segment_index: int, reason: str):
        self.segment_index = segment_index
        self.reason = reason
        super().__init__("这段没有贴上路，换短一点再试。")


def build_snap_preview(
    *,
    current_user_id: int,
    mode: str,
    coordinate_system: str,
    points: list[tuple[float, float]],
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
            "raw_points": raw_points,
            "anchor_points": raw_points,
            "raw_distance_m": raw_distance_m,
            "distance_m": raw_distance_m,
            "segment_count": len(raw_points) - 1,
            "warnings": [],
            "failed_segment": None,
            "routing_receipt": None,
        }
    if mode != "snap":
        raise ValueError("mode 只支持 snap 或 freehand")

    anchor_points = _simplify_anchor_points(raw_points)
    segment_count = len(anchor_points) - 1
    if len(anchor_points) > MAX_ANCHOR_POINTS or segment_count > MAX_SEGMENTS:
        raise ValueError("这一段太长了，分几段画更稳")

    timeout_sec = _timeout_per_segment(segment_count)
    snapped_points: list[list[float]] = []
    distance_m = 0.0
    durations: list[float] = []
    ferry_counts: list[int] = []
    routing_steps: list[dict[str, Any]] = []
    provider_calls: list[dict[str, Any]] = []
    unverified_join_gaps: list[dict[str, Any]] = []
    request_ids: list[str] = []
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

        join_gap_m = (
            haversine(
                snapped_points[-1][1],
                snapped_points[-1][0],
                segment_points[0][1],
                segment_points[0][0],
            )
            if snapped_points
            else 0.0
        )
        if snapped_points and join_gap_m > MAX_PROVIDER_JOIN_GAP_M:
            raise DrawSnapSegmentError(index, "相邻腾讯子路线没有接上")
        joins_previous = bool(snapped_points and _same_point(snapped_points[-1], segment_points[0]))
        global_point_offset = len(snapped_points) - 1 if joins_previous else len(snapped_points)
        if snapped_points and not joins_previous:
            unverified_join_gaps.append(
                {
                    "after_provider_call_index": index - 1,
                    "before_provider_call_index": index,
                    "provider_point_start": len(snapped_points) - 1,
                    "provider_point_end": len(snapped_points),
                    "distance_m": round(join_gap_m, 3),
                }
            )
        for step in planned.get("steps") or []:
            normalized_step = dict(step)
            normalized_step["point_start"] = int(step["point_start"]) + global_point_offset
            normalized_step["point_end"] = int(step["point_end"]) + global_point_offset
            normalized_step["provider_call_index"] = index
            routing_steps.append(normalized_step)

        request_id = planned.get("request_id")
        if isinstance(request_id, str) and request_id:
            request_ids.append(request_id)
        call_duration = _finite_float(planned.get("duration"))
        if call_duration is not None and call_duration >= 0:
            durations.append(call_duration)
        call_ferry_count = planned.get("ferry_count")
        if isinstance(call_ferry_count, int) and call_ferry_count >= 0:
            ferry_counts.append(call_ferry_count)
        provider_calls.append(
            {
                "call_index": index,
                "request_id": request_id,
                "distance_m": _finite_float(planned.get("distance")),
                "duration_min": call_duration,
                "ferry_count": call_ferry_count,
                "mode": planned.get("mode"),
                "direction": planned.get("direction"),
                "provider_point_start": global_point_offset,
                "provider_point_end": global_point_offset + len(segment_points) - 1,
            }
        )
        if joins_previous:
            segment_points = segment_points[1:]
        snapped_points.extend(segment_points)
        distance_m += _finite_float(planned.get("distance")) or _distance_m(segment_points)

    if len(snapped_points) < 2:
        raise TencentMapError("腾讯地图没有返回可用路线")

    warnings: list[str] = []
    if unverified_join_gaps:
        warnings.append("相邻贴路线之间有未验证连接，请放大检查后再保存。")
    if raw_distance_m > 0 and distance_m > max(raw_distance_m * 1.8, raw_distance_m + 1000):
        warnings.append("系统贴出的路线可能偏离你的手画线，请检查后再保存。")

    routing_receipt = store_snap_receipt(
        build_tencent_evidence(
            {
                "distance": distance_m,
                "duration": sum(durations) if len(durations) == segment_count else None,
                "mode": "BICYCLING",
                "direction": None,
                "ferry_count": sum(ferry_counts) if len(ferry_counts) == segment_count else None,
                "request_ids": request_ids,
                "provider_calls": provider_calls,
                "unverified_join_gaps": unverified_join_gaps,
                "steps": routing_steps,
            },
            snapped_points,
        ),
        current_user_id=current_user_id,
    )

    return {
        "mode": mode,
        "coordinate_system": coordinate_system,
        "snapped_points": snapped_points,
        "raw_points": raw_points,
        "anchor_points": anchor_points,
        "raw_distance_m": raw_distance_m,
        "distance_m": distance_m,
        "segment_count": segment_count,
        "warnings": warnings,
        "failed_segment": None,
        "routing_receipt": routing_receipt,
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


def _rdp_indices(points: list[list[float]], start: int, end: int, tolerance_m: float) -> list[int]:
    max_distance = -1.0
    max_index = start
    for index in range(start + 1, end):
        distance = _perpendicular_distance_m(points[index], points[start], points[end])
        if distance > max_distance:
            max_distance = distance
            max_index = index

    if max_distance > tolerance_m:
        left = _rdp_indices(points, start, max_index, tolerance_m)
        right = _rdp_indices(points, max_index, end, tolerance_m)
        return left[:-1] + right
    return [start, end]


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
