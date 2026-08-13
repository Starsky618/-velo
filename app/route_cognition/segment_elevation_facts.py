"""从冻结的 Strava 来源线生成单赛段 GLO-30 派生事实。"""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from types import SimpleNamespace
from typing import Callable

from app.common.geometry_hash import (
    STRAVA_SOURCE_GEOMETRY_NORMALIZATION_VERSION,
    canonical_strava_source_line_wkt,
    strava_source_geometry_hash,
)
from app.elevation.route_elevation import (
    ROUTE_ELEVATION_METHOD,
    RouteElevationResult,
    build_route_elevation_result,
    route_elevation_metadata,
)
from app.parsing.geo_math import haversine
from app.segment.algorithms import calculate_max_gradient


SOURCE_GEOMETRY_NORMALIZATION_VERSION = (
    STRAVA_SOURCE_GEOMETRY_NORMALIZATION_VERSION
)
SOURCE_DISTANCE_ANOMALY_THRESHOLD_PCT = 5.0
MAXIMUM_GRADIENT_REQUESTED_WINDOW_M = 500.0
ElevationBuilder = Callable[[list[list[float]]], RouteElevationResult]


def points_from_linestring_wkt(value: str) -> list[list[float]]:
    """只接受二维 LINESTRING，并保留来源点顺序和方向。"""
    match = re.fullmatch(r"\s*LINESTRING\s*\((.+)\)\s*", value, re.IGNORECASE)
    if not match:
        raise ValueError("来源几何不是二维 LINESTRING")
    points: list[list[float]] = []
    for pair in match.group(1).split(","):
        parts = pair.strip().split()
        if len(parts) != 2:
            raise ValueError("来源几何点必须恰好包含经度和纬度")
        lon = float(parts[0])
        lat = float(parts[1])
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError("来源几何包含非有限坐标")
        if not (-180.0 <= lon < 180.0 and -90.0 < lat < 90.0):
            raise ValueError("来源几何坐标越界")
        points.append([lon, lat])
    if len(points) < 2:
        raise ValueError("来源几何少于两个点")
    return points


def canonical_source_line_wkt(points: list[list[float]]) -> str:
    """固定到 census 已保存精度，避免 PostGIS 文本格式差异改变 hash。"""
    return canonical_strava_source_line_wkt(points)


def source_geometry_hash(points: list[list[float]]) -> str:
    return strava_source_geometry_hash(points)


def validated_source_geometry(
    source_line_wkt: str,
    source_point_count: int,
) -> tuple[list[list[float]], str, float]:
    """一次完成来源几何资格校验，供分账和事实构建共用。"""
    points = points_from_linestring_wkt(source_line_wkt)
    if len(points) != source_point_count:
        raise ValueError("来源几何点数与观测账不一致")
    geometry_hash = source_geometry_hash(points)
    derived_distance_m = _route_distance_m(points)
    return points, geometry_hash, derived_distance_m


def build_segment_elevation_fact(
    *,
    source_observation_id: int,
    source_segment_id: str,
    source_line_wkt: str,
    source_point_count: int,
    source_distance_m: float | None,
    elevation_builder: ElevationBuilder = build_route_elevation_result,
    computed_at: datetime | None = None,
) -> dict:
    """返回一条 complete/failed 事实；DEM 失败也保留输入 hash 和失败账。"""
    points, geometry_hash, derived_distance_m = validated_source_geometry(
        source_line_wkt,
        source_point_count,
    )
    distance_difference_pct = _distance_difference_pct(
        source_distance_m,
        derived_distance_m,
    )
    distance_status = _distance_status(distance_difference_pct)
    method_metadata = {
        **route_elevation_metadata(),
        "method": ROUTE_ELEVATION_METHOD,
        "source_geometry_normalization_version": SOURCE_GEOMETRY_NORMALIZATION_VERSION,
        "maximum_gradient_method": "segment_calculate_max_gradient_v2",
        "maximum_gradient_requested_window_m": MAXIMUM_GRADIENT_REQUESTED_WINDOW_M,
        "maximum_gradient_short_segment_fallback": "total_distance_divided_by_4",
    }
    quality_flags = {
        "source_distance_status": distance_status,
        "source_distance_anomaly_threshold_pct": SOURCE_DISTANCE_ANOMALY_THRESHOLD_PCT,
        "absolute_elevation_status": "not_tested_no_absolute_reference",
        "bridge_tunnel_status": "not_screened",
    }
    common = {
        "source_observation_id": source_observation_id,
        "source_segment_id": source_segment_id,
        "source_geometry_hash": geometry_hash,
        "geometry_normalization_version": SOURCE_GEOMETRY_NORMALIZATION_VERSION,
        "algorithm_version": ROUTE_ELEVATION_METHOD,
        "method_metadata_json": method_metadata,
        "source_point_count": source_point_count,
        "source_distance_difference_pct": distance_difference_pct,
        "quality_flags_json": quality_flags,
        "computed_at": computed_at or datetime.now(timezone.utc),
    }
    try:
        result = elevation_builder(points)
        if result.point_count != source_point_count:
            raise ValueError("GLO-30 海拔点数与来源几何点数不一致")
        elevations = [float(point[2]) for point in result.snapshot]
        if len(elevations) != source_point_count:
            raise ValueError("GLO-30 snapshot 与来源几何点数不一致")
        maximum_gradient_window_m = _maximum_gradient_window_m(derived_distance_m)
        maximum_gradient_pct = calculate_max_gradient(
            [
                SimpleNamespace(
                    longitude=point[0],
                    latitude=point[1],
                    elevation=elevation,
                )
                for point, elevation in zip(points, elevations)
            ],
            window_m=MAXIMUM_GRADIENT_REQUESTED_WINDOW_M,
        )
        start_elevation_m = elevations[0]
        end_elevation_m = elevations[-1]
        return {
            **common,
            "fact_status": "complete",
            "elevation_snapshot_json": result.snapshot,
            "elevation_profile_json": result.profile,
            "elevation_point_count": result.point_count,
            "derived_distance_m": round(derived_distance_m, 1),
            "climb_m": float(result.climb),
            "descent_m": float(result.descent),
            "start_elevation_m": start_elevation_m,
            "end_elevation_m": end_elevation_m,
            "minimum_elevation_m": min(elevations),
            "maximum_elevation_m": max(elevations),
            "net_elevation_change_m": round(end_elevation_m - start_elevation_m, 1),
            "average_gradient_pct": round(
                (end_elevation_m - start_elevation_m) / derived_distance_m * 100,
                3,
            ),
            "maximum_gradient_pct": float(maximum_gradient_pct),
            "maximum_gradient_window_m": round(maximum_gradient_window_m, 1),
            "failure_json": None,
        }
    except Exception as exc:
        return {
            **common,
            "fact_status": "failed",
            "elevation_snapshot_json": None,
            "elevation_profile_json": None,
            "elevation_point_count": None,
            "derived_distance_m": None,
            "climb_m": None,
            "descent_m": None,
            "start_elevation_m": None,
            "end_elevation_m": None,
            "minimum_elevation_m": None,
            "maximum_elevation_m": None,
            "net_elevation_change_m": None,
            "average_gradient_pct": None,
            "maximum_gradient_pct": None,
            "maximum_gradient_window_m": None,
            "failure_json": {
                "stage": "glo30_elevation",
                "error": f"{type(exc).__name__}:{str(exc)[:240]}",
            },
        }


def _route_distance_m(points: list[list[float]]) -> float:
    distance = sum(
        haversine(previous[1], previous[0], current[1], current[0])
        for previous, current in zip(points, points[1:])
    )
    if not math.isfinite(distance) or distance <= 0.01:
        raise ValueError("来源几何没有有效长度")
    return distance


def _distance_difference_pct(
    source_distance_m: float | None,
    derived_distance_m: float,
) -> float | None:
    if source_distance_m is None or source_distance_m <= 0:
        return None
    return round(abs(derived_distance_m - source_distance_m) / source_distance_m * 100, 3)


def _distance_status(value: float | None) -> str:
    if value is None:
        return "source_distance_missing"
    if value > SOURCE_DISTANCE_ANOMALY_THRESHOLD_PCT:
        return "anomaly_over_5pct"
    return "within_5pct"


def _maximum_gradient_window_m(derived_distance_m: float) -> float:
    if MAXIMUM_GRADIENT_REQUESTED_WINDOW_M > derived_distance_m / 2.0:
        return derived_distance_m / 4.0
    return MAXIMUM_GRADIENT_REQUESTED_WINDOW_M
