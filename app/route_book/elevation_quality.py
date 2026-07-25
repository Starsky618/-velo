"""路线海拔质量检查——导出到码表前确认每个轨迹点都有可信海拔。"""

from __future__ import annotations

import json
import math

from app.elevation.dem_client import (
    GLO30_DATASET_ID,
    GLO30_GRID_REGISTRATION,
    GLO30_HORIZONTAL_RESOLUTION_M,
    GLO30_LICENSE_ID,
    GLO30_SOURCE_NAME,
    GLO30_VERTICAL_DATUM,
    GLO30_VERTICAL_ACCURACY_M,
)
from app.elevation.route_elevation import (
    ASCENT_MINIMUM_SPAN_M,
    ASCENT_PROMINENCE_M,
    MEDIAN_FILTER_POINTS,
    MAX_PROCESSING_DISTANCE_M,
    MAX_PROCESSING_POINTS,
    PROCESSING_GRID_M,
    ROUTE_ELEVATION_METHOD,
    SMOOTHING_SIGMA_M,
)

MIN_REASONABLE_ELEVATION_M = -500.0
MAX_REASONABLE_ELEVATION_M = 9000.0
TRUSTED_ROUTE_ELEVATION_METHOD = ROUTE_ELEVATION_METHOD
TRUSTED_ROUTE_ELEVATION_METHODS = frozenset(
    {
        TRUSTED_ROUTE_ELEVATION_METHOD,
        "authorized_point_elevation_csv_v1",
    }
)


def parse_complete_elevation_snapshot(
    value: str | None,
    *,
    expected_count: int,
) -> list[list[float]] | None:
    """
    解析逐点海拔底片。

    导出给码表的 GPX/TCX 不能再退回二维线：iGPSPORT 真机会采用 `<ele>`，
    缺海拔时会自行补算并可能显著偏离。所以这里要求点数一一对应，且每个点
    都有有限、物理范围合理的海拔值。
    """
    if not value or expected_count < 2:
        return None
    try:
        raw_points = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(raw_points, list) or len(raw_points) != expected_count:
        return None

    points: list[list[float]] = []
    for raw in raw_points:
        if not isinstance(raw, list) or len(raw) < 3:
            return None
        lon = _finite_float(raw[0])
        lat = _finite_float(raw[1])
        ele = _finite_float(raw[2])
        if lon is None or lat is None or ele is None:
            return None
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return None
        if not (MIN_REASONABLE_ELEVATION_M <= ele <= MAX_REASONABLE_ELEVATION_M):
            return None
        points.append([lon, lat, ele])
    return points


def parse_complete_elevation_grid(
    value: str | None,
    *,
    expected_line_hash: str,
    expected_distance_m: float,
    metadata_json: str | None,
) -> list[list[float]] | None:
    """解析绑定参考线的 canonical 距离-海拔网格；网格自身不携带经纬度。"""
    if (
        not value
        or not expected_line_hash
        or not math.isfinite(expected_distance_m)
        or expected_distance_m <= 0
    ):
        return None
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != "distance_elevation_v1":
        return None
    if payload.get("line_hash") != expected_line_hash:
        return None
    raw_points = payload.get("points")
    expected_grid_count = max(1, math.ceil(expected_distance_m / PROCESSING_GRID_M)) + 1
    if (
        not isinstance(raw_points, list)
        or len(raw_points) != expected_grid_count
        or len(raw_points) > MAX_PROCESSING_POINTS
        or not _matches_elevation_grid_metadata(metadata_json, expected_grid_count)
    ):
        return None

    points: list[list[float]] = []
    previous_distance: float | None = None
    for raw in raw_points:
        if not isinstance(raw, list) or len(raw) != 2:
            return None
        distance = _finite_float(raw[0])
        elevation = _finite_float(raw[1])
        if distance is None or elevation is None:
            return None
        if distance < 0 or (previous_distance is not None and distance <= previous_distance):
            return None
        if not (MIN_REASONABLE_ELEVATION_M <= elevation <= MAX_REASONABLE_ELEVATION_M):
            return None
        points.append([distance, elevation])
        previous_distance = distance

    tolerance = max(1.0, expected_distance_m * 1e-5)
    if abs(points[0][0]) > 0.001:
        return None
    if abs(points[-1][0] - expected_distance_m) > tolerance:
        return None
    interval_count = expected_grid_count - 1
    if any(
        abs(point[0] - expected_distance_m * index / interval_count) > 0.002
        for index, point in enumerate(points)
    ):
        return None
    return points


def _matches_elevation_grid_metadata(metadata_json: str | None, expected_count: int) -> bool:
    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(metadata, dict):
        return False
    elevation = metadata.get("elevation")
    if not isinstance(elevation, dict):
        return False
    return (
        elevation.get("elevation_grid_schema") == "distance_elevation_v1"
        and _finite_float(elevation.get("elevation_grid_point_count")) == expected_count
    )


def declares_elevation_grid(metadata_json: str | None) -> bool:
    """判断该版本是否已经进入 canonical 网格合同；声明过就不能静默退回稀疏导出。"""
    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(metadata, dict):
        return False
    elevation = metadata.get("elevation")
    if not isinstance(elevation, dict):
        return False
    return "elevation_grid_schema" in elevation or "elevation_grid_point_count" in elevation


def has_complete_elevation_snapshot(value: str | None, *, expected_count: int | None = None) -> bool:
    if expected_count is not None:
        return parse_complete_elevation_snapshot(value, expected_count=expected_count) is not None
    if not value:
        return False
    try:
        raw_points = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        return False
    return parse_complete_elevation_snapshot(value, expected_count=len(raw_points)) is not None


def has_trusted_route_elevation(
    value: str | None,
    *,
    metadata_json: str | None,
    expected_count: int,
    methods: frozenset[str] = TRUSTED_ROUTE_ELEVATION_METHODS,
) -> bool:
    """
    判断一条路书能不能把海拔交给码表。

    只看逐点海拔是否完整还不够：旧 GPX 或旧公共底图快照可能仍有完整数值。当前产品
    策略只信任 GLO-30 自研算法或明确授权的逐点导入，因此同时检查点完整和方法版本。
    """
    if parse_complete_elevation_snapshot(value, expected_count=expected_count) is None:
        return False
    return has_elevation_metadata_method(metadata_json, methods=methods, expected_count=expected_count)


def has_elevation_metadata_method(
    metadata_json: str | None,
    *,
    methods: frozenset[str] = TRUSTED_ROUTE_ELEVATION_METHODS,
    expected_count: int | None = None,
) -> bool:
    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(metadata, dict):
        return False
    elevation = metadata.get("elevation")
    if not isinstance(elevation, dict):
        return False
    source_name = elevation.get("source_name")
    license_id = elevation.get("license_id")
    accuracy_m = _finite_float(elevation.get("accuracy_m"))
    point_count = _finite_float(elevation.get("point_count"))
    if not isinstance(source_name, str) or not source_name.strip():
        return False
    if not isinstance(license_id, str) or not license_id.strip():
        return False
    if accuracy_m is None or accuracy_m <= 0:
        return False
    if expected_count is not None and point_count != expected_count:
        return False
    method = elevation.get("method")
    if method not in methods:
        return False
    if method == TRUSTED_ROUTE_ELEVATION_METHOD:
        return _matches_glo30_v1_contract(elevation)
    return True


def _matches_glo30_v1_contract(elevation: dict) -> bool:
    """方法名不能只贴标签；底座、基准面和算法参数也必须完整一致。"""
    expected_strings = {
        "source_name": GLO30_SOURCE_NAME,
        "license_id": GLO30_LICENSE_ID,
        "dataset_id": GLO30_DATASET_ID,
        "vertical_datum": GLO30_VERTICAL_DATUM,
        "grid_registration": GLO30_GRID_REGISTRATION,
    }
    if any(elevation.get(key) != value for key, value in expected_strings.items()):
        return False
    expected_numbers = {
        "accuracy_m": GLO30_VERTICAL_ACCURACY_M,
        "horizontal_resolution_m": GLO30_HORIZONTAL_RESOLUTION_M,
        "processing_grid_m": PROCESSING_GRID_M,
        "median_filter_points": MEDIAN_FILTER_POINTS,
        "smoothing_sigma_m": SMOOTHING_SIGMA_M,
        "ascent_prominence_m": ASCENT_PROMINENCE_M,
        "ascent_minimum_span_m": ASCENT_MINIMUM_SPAN_M,
        "maximum_processing_distance_m": MAX_PROCESSING_DISTANCE_M,
    }
    return all(_finite_float(elevation.get(key)) == float(value) for key, value in expected_numbers.items())


def _finite_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
