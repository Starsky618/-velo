"""路线海拔质量检查——导出到码表前确认每个轨迹点都有可信海拔。"""

from __future__ import annotations

import json
import math


MIN_REASONABLE_ELEVATION_M = -500.0
MAX_REASONABLE_ELEVATION_M = 9000.0


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


def _finite_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
