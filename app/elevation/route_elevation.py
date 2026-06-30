"""
路线海拔生成器——把一条二维路线加工成“可导出、可展示、可统计”的海拔结果。

操作注意事项：这里不碰数据库，也不关心赛段还是路书。它像厨房里的中央料理台，
只负责把原料点位做成标准成品；谁要用，谁自己端走写进自己的表。

输入输出：输入 [[lon, lat], ...] 和一个海拔查询函数，输出逐点海拔 snapshot、页面曲线
profile、累计爬升 climb 和点数。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Sequence

from app.elevation.dem_client import query_elevations
from app.parsing.geo_math import haversine


PROFILE_LIMIT = 100
MIN_REASONABLE_ELEVATION_M = -500.0
MAX_REASONABLE_ELEVATION_M = 9000.0
ElevationQuery = Callable[[list[tuple[float, float]]], list[float | None]]


@dataclass(frozen=True)
class RouteElevationResult:
    snapshot: list[list[float]]
    profile: list[list[float]]
    climb: float
    point_count: int


def build_route_elevation_result(
    points: Sequence[Sequence[float]],
    *,
    query_func: ElevationQuery = query_elevations,
) -> RouteElevationResult:
    """
    给路线每个点补海拔，并生成导出和页面都能复用的标准结果。

    points 使用路书系统内部的 [lon, lat] 顺序；DEM 查询函数使用常见的 (lat, lon)
    顺序。这里集中做一次翻译，避免各功能自己翻译时经纬度写反。
    """
    normalized = _normalize_points(points)
    query_points = [(lat, lon) for lon, lat in normalized]
    elevations = query_func(query_points)
    if len(elevations) != len(normalized):
        raise ValueError("海拔查询结果数量和路线点数量不一致")

    clean_elevations = _require_complete_elevations(elevations)
    snapshot = [
        [round(lon, 7), round(lat, 7), round(ele, 1)]
        for (lon, lat), ele in zip(normalized, clean_elevations)
    ]
    profile = _downsample_profile(normalized, clean_elevations)
    climb = _calculate_climb(clean_elevations)
    return RouteElevationResult(
        snapshot=snapshot,
        profile=profile,
        climb=climb,
        point_count=len(snapshot),
    )


def build_route_elevation_result_from_values(
    points: Sequence[Sequence[float]],
    elevations: Sequence[float],
) -> RouteElevationResult:
    """把已经拿到的逐点海拔加工成同一套标准结果，给 CSV 导入等离线路径复用。"""
    normalized = _normalize_points(points)
    clean_elevations = [float(ele) for ele in elevations]
    if len(clean_elevations) != len(normalized):
        raise ValueError("海拔数量和路线点数量不一致")
    snapshot = [
        [round(lon, 7), round(lat, 7), round(ele, 1)]
        for (lon, lat), ele in zip(normalized, clean_elevations)
    ]
    return RouteElevationResult(
        snapshot=snapshot,
        profile=_downsample_profile(normalized, clean_elevations),
        climb=_calculate_climb(clean_elevations),
        point_count=len(snapshot),
    )


def _normalize_points(points: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    normalized: list[tuple[float, float]] = []
    for point in points:
        if len(point) < 2:
            raise ValueError("路线点必须包含经度和纬度")
        lon = float(point[0])
        lat = float(point[1])
        normalized.append((lon, lat))
    if len(normalized) < 2:
        raise ValueError("路线至少需要 2 个点才能生成海拔")
    return normalized


def _require_complete_elevations(elevations: Sequence[float | None]) -> list[float]:
    missing = [index for index, ele in enumerate(elevations) if ele is None]
    if missing:
        raise ValueError(f"路线海拔查询缺失点位：{missing[:5]}")
    clean: list[float] = []
    invalid: list[int] = []
    for index, ele in enumerate(elevations):
        number = float(ele)
        if not math.isfinite(number) or not (MIN_REASONABLE_ELEVATION_M <= number <= MAX_REASONABLE_ELEVATION_M):
            invalid.append(index)
            continue
        clean.append(number)
    if invalid:
        raise ValueError(f"路线海拔查询返回异常高度：{invalid[:5]}")
    return clean


def _calculate_climb(elevations: Sequence[float]) -> float:
    climb = 0.0
    for prev, curr in zip(elevations, elevations[1:]):
        delta = curr - prev
        if delta > 0:
            climb += delta
    return round(climb, 1)


def _downsample_profile(points: Sequence[tuple[float, float]], elevations: Sequence[float]) -> list[list[float]]:
    cumulative = _cumulative_distances(points)
    if len(points) <= PROFILE_LIMIT:
        return [[round(distance / 1000, 3), round(ele, 1)] for distance, ele in zip(cumulative, elevations)]

    total = cumulative[-1]
    selected: list[int] = [0]
    cursor = 1
    for step in range(1, PROFILE_LIMIT - 1):
        target = total * step / (PROFILE_LIMIT - 1)
        while cursor < len(cumulative) - 1 and cumulative[cursor] < target:
            cursor += 1
        before = max(cursor - 1, 0)
        after = cursor
        chosen = before if abs(cumulative[before] - target) <= abs(cumulative[after] - target) else after
        if chosen != selected[-1]:
            selected.append(chosen)
    if selected[-1] != len(points) - 1:
        selected.append(len(points) - 1)
    return [[round(cumulative[index] / 1000, 3), round(elevations[index], 1)] for index in selected]


def _cumulative_distances(points: Sequence[tuple[float, float]]) -> list[float]:
    distances = [0.0]
    total = 0.0
    for prev, curr in zip(points, points[1:]):
        total += haversine(prev[1], prev[0], curr[1], curr[0])
        distances.append(total)
    return distances
