"""把二维路线加工成可展示、可导出、可统计的 GLO-30 海拔结果。

生产算法来自 VELO 2026-07 的 V3.1/V4 实验，而不是旧的相邻正差累加：

1. 沿路线建立约 20m 的固定物理网格；
2. 三点中值去毛刺，再做 100m Gaussian 平滑；
3. 只累计抬升至少 3m、水平跨度至少 100m 的上升事件；
4. 将同一条成品剖面用于页面、总爬升和逐点导出。

GLO-30 是线上主底座；ALOS、FIT 与获授权的 Strava 赛段数据用于离线校准、拟合
和回归，不在请求时按固定权重混入路线曲线。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Sequence

import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter

from app.elevation.dem_client import (
    GLO30_DATASET_ID,
    GLO30_GRID_REGISTRATION,
    GLO30_VERTICAL_DATUM,
    query_elevations,
)
from app.parsing.geo_math import haversine


PROFILE_LIMIT = 100
MIN_REASONABLE_ELEVATION_M = -500.0
MAX_REASONABLE_ELEVATION_M = 9000.0
PROCESSING_GRID_M = 20.0
SMOOTHING_SIGMA_M = 100.0
MEDIAN_FILTER_POINTS = 3
ASCENT_PROMINENCE_M = 3.0
ASCENT_MINIMUM_SPAN_M = 100.0
MAX_PROCESSING_DISTANCE_M = 1_000_000.0
MAX_PROCESSING_POINTS = 50_001
ROUTE_ELEVATION_METHOD = "glo30_meaningful_ascent_v1"
ElevationQuery = Callable[[list[tuple[float, float]]], list[float | None]]


class RouteElevationInputError(ValueError):
    """路线几何本身不适合本次同步计算，应向调用方返回 4xx。"""


@dataclass(frozen=True)
class RouteElevationResult:
    snapshot: list[list[float]]
    profile: list[list[float]]
    climb: float
    point_count: int
    descent: float = 0.0


def route_elevation_metadata() -> dict[str, float | str]:
    """返回随 RouteVersion 保存、用于审计本次估算的底座与算法参数。"""
    return {
        "processing_grid_m": PROCESSING_GRID_M,
        "median_filter_points": MEDIAN_FILTER_POINTS,
        "smoothing_sigma_m": SMOOTHING_SIGMA_M,
        "ascent_prominence_m": ASCENT_PROMINENCE_M,
        "ascent_minimum_span_m": ASCENT_MINIMUM_SPAN_M,
        "maximum_processing_distance_m": MAX_PROCESSING_DISTANCE_M,
        "dataset_id": GLO30_DATASET_ID,
        "vertical_datum": GLO30_VERTICAL_DATUM,
        "grid_registration": GLO30_GRID_REGISTRATION,
        "calibration_role": "ALOS+FIT+authorized_Strava_offline_evidence",
    }


def build_route_elevation_result(
    points: Sequence[Sequence[float]],
    *,
    query_func: ElevationQuery = query_elevations,
) -> RouteElevationResult:
    """查询 GLO-30，并从固定物理网格生成唯一成品剖面。"""
    normalized = _normalize_points(points)
    original_distances = np.asarray(_cumulative_distances(normalized), dtype=float)
    grid, sampled_points = _resample_route(normalized, original_distances)
    query_points = [(lat, lon) for lon, lat in sampled_points]
    elevations = query_func(query_points)
    if len(elevations) != len(sampled_points):
        raise ValueError("海拔查询结果数量和路线采样点数量不一致")

    raw = np.asarray(_require_complete_elevations(elevations), dtype=float)
    shaped = _shape_profile(raw, grid)
    snapshot_values = np.interp(original_distances, grid, shaped)
    snapshot = [
        [round(lon, 7), round(lat, 7), round(float(ele), 1)]
        for (lon, lat), ele in zip(normalized, snapshot_values)
    ]
    return RouteElevationResult(
        snapshot=snapshot,
        profile=_downsample_profile(grid, shaped),
        climb=round(_meaningful_ascent(shaped, grid), 1),
        point_count=len(snapshot),
        descent=round(_meaningful_ascent(-shaped, grid), 1),
    )


def build_route_elevation_result_from_values(
    points: Sequence[Sequence[float]],
    elevations: Sequence[float],
) -> RouteElevationResult:
    """导入已授权逐点高度；保留原值导出，统一算法只用于图表和预计爬升。"""
    normalized = _normalize_points(points)
    clean = _require_complete_elevations(elevations)
    if len(clean) != len(normalized):
        raise ValueError("海拔数量和路线点数量不一致")

    original_distances = np.asarray(_cumulative_distances(normalized), dtype=float)
    source_distances, source_values = _strictly_increasing_values(
        original_distances,
        np.asarray(clean, dtype=float),
    )
    grid, _sampled_points = _resample_route(normalized, original_distances)
    sampled = np.interp(grid, source_distances, source_values)
    shaped = _shape_profile(sampled, grid)
    snapshot = [
        [round(lon, 7), round(lat, 7), round(float(ele), 1)]
        for (lon, lat), ele in zip(normalized, clean)
    ]
    return RouteElevationResult(
        snapshot=snapshot,
        profile=_downsample_profile(grid, shaped),
        climb=round(_meaningful_ascent(shaped, grid), 1),
        point_count=len(snapshot),
        descent=round(_meaningful_ascent(-shaped, grid), 1),
    )


def _normalize_points(points: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    normalized: list[tuple[float, float]] = []
    for point in points:
        if len(point) < 2:
            raise RouteElevationInputError("路线点必须包含经度和纬度")
        lon = float(point[0])
        lat = float(point[1])
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise RouteElevationInputError("路线点经纬度必须是有限数字")
        if not (-180.0 <= lon < 180.0 and -90.0 < lat < 90.0):
            raise RouteElevationInputError("路线点超出经纬度范围")
        normalized.append((lon, lat))
    if len(normalized) < 2:
        raise RouteElevationInputError("路线至少需要 2 个点才能生成海拔")
    if _cumulative_distances(normalized)[-1] <= 0.01:
        raise RouteElevationInputError("路线长度必须大于 0")
    if any(abs(current[0] - previous[0]) > 180.0 for previous, current in zip(normalized, normalized[1:])):
        raise RouteElevationInputError("当前中国区路线不支持跨越日期变更线")
    return normalized


def _require_complete_elevations(elevations: Sequence[float | None]) -> list[float]:
    missing = [index for index, ele in enumerate(elevations) if ele is None]
    if missing:
        raise ValueError(f"路线海拔查询缺失点位：{missing[:5]}")
    clean: list[float] = []
    invalid: list[int] = []
    for index, ele in enumerate(elevations):
        number = float(ele)
        if not math.isfinite(number) or not (
            MIN_REASONABLE_ELEVATION_M <= number <= MAX_REASONABLE_ELEVATION_M
        ):
            invalid.append(index)
            continue
        clean.append(number)
    if invalid:
        raise ValueError(f"路线海拔查询返回异常高度：{invalid[:5]}")
    return clean


def _resample_route(
    points: Sequence[tuple[float, float]],
    original_distances: np.ndarray,
) -> tuple[np.ndarray, list[tuple[float, float]]]:
    source_distances, source_indexes = _strictly_increasing_indexes(original_distances)
    total = float(source_distances[-1])
    if total > MAX_PROCESSING_DISTANCE_M:
        raise RouteElevationInputError("单条路线暂不支持超过 1000 公里的同步海拔计算")
    interval_count = max(1, int(math.ceil(total / PROCESSING_GRID_M)))
    if interval_count + 1 > MAX_PROCESSING_POINTS:
        raise RouteElevationInputError("路线海拔采样点超过同步处理上限")
    grid = np.linspace(0.0, total, interval_count + 1)
    source_lon = np.asarray([points[index][0] for index in source_indexes], dtype=float)
    source_lat = np.asarray([points[index][1] for index in source_indexes], dtype=float)
    sampled_lon = np.interp(grid, source_distances, source_lon)
    sampled_lat = np.interp(grid, source_distances, source_lat)
    return grid, list(zip(sampled_lon.tolist(), sampled_lat.tolist()))


def _strictly_increasing_indexes(distances: np.ndarray) -> tuple[np.ndarray, list[int]]:
    indexes = [0]
    for index in range(1, len(distances)):
        if distances[index] - distances[indexes[-1]] > 0.01:
            indexes.append(index)
    if indexes[-1] != len(distances) - 1:
        indexes[-1] = len(distances) - 1
    values = distances[indexes]
    if len(values) < 2 or values[-1] <= values[0]:
        raise RouteElevationInputError("路线没有可用的连续距离")
    return values, indexes


def _strictly_increasing_values(
    distances: np.ndarray,
    values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    source_distances, indexes = _strictly_increasing_indexes(distances)
    return source_distances, values[indexes]


def _shape_profile(values: np.ndarray, distances: np.ndarray) -> np.ndarray:
    if not np.isfinite(values).all():
        raise ValueError("路线海拔包含缺失值")
    spacing = float(distances[-1] / max(len(distances) - 1, 1))
    cleaned = median_filter(values, size=MEDIAN_FILTER_POINTS, mode="nearest")
    return gaussian_filter1d(
        cleaned,
        sigma=max(SMOOTHING_SIGMA_M / spacing, 0.01),
        mode="nearest",
        truncate=2.0,
    )


def _meaningful_ascent(values: np.ndarray, distances: np.ndarray) -> float:
    """V4 ``local_100_3_100``：累计满足 prominence/span 的完整上升。"""
    valley = float(values[0])
    valley_index = 0
    peak = valley
    peak_index = 0
    climbing = False
    total = 0.0
    for index, raw in enumerate(values[1:], start=1):
        value = float(raw)
        if not climbing:
            if value < valley:
                valley = value
                valley_index = index
            elif value - valley >= ASCENT_PROMINENCE_M:
                climbing = True
                peak = value
                peak_index = index
            continue
        if value > peak:
            peak = value
            peak_index = index
        elif peak - value >= ASCENT_PROMINENCE_M:
            if distances[peak_index] - distances[valley_index] >= ASCENT_MINIMUM_SPAN_M:
                total += peak - valley
            climbing = False
            valley = value
            valley_index = index
            peak = value
            peak_index = index
    if climbing and distances[peak_index] - distances[valley_index] >= ASCENT_MINIMUM_SPAN_M:
        total += peak - valley
    return float(total)


def _downsample_profile(distances: np.ndarray, elevations: np.ndarray) -> list[list[float]]:
    if len(distances) <= PROFILE_LIMIT:
        targets = distances
        values = elevations
    else:
        targets = np.linspace(0.0, float(distances[-1]), PROFILE_LIMIT)
        values = np.interp(targets, distances, elevations)
    return [
        [round(float(distance) / 1000.0, 3), round(float(ele), 1)]
        for distance, ele in zip(targets, values)
    ]


def _cumulative_distances(points: Sequence[tuple[float, float]]) -> list[float]:
    distances = [0.0]
    total = 0.0
    for previous, current in zip(points, points[1:]):
        total += haversine(previous[1], previous[0], current[1], current[0])
        distances.append(total)
    return distances
