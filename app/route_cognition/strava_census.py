"""Strava 区域赛段的确定性枚举和来源观测解析。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from typing import Callable


RequestHook = Callable[[], None]


@dataclass(frozen=True)
class Bounds:
    south: float
    west: float
    north: float
    east: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.south, self.west, self.north, self.east)

    def key(self, depth: int) -> str:
        values = ",".join(f"{value:.7f}" for value in self.as_tuple())
        return f"d{depth}:{values}"

    def split(self) -> tuple["Bounds", "Bounds", "Bounds", "Bounds"]:
        middle_lat = (self.south + self.north) / 2
        middle_lon = (self.west + self.east) / 2
        return (
            Bounds(self.south, self.west, middle_lat, middle_lon),
            Bounds(self.south, middle_lon, middle_lat, self.east),
            Bounds(middle_lat, self.west, self.north, middle_lon),
            Bounds(middle_lat, middle_lon, self.north, self.east),
        )


@dataclass
class EnumerationPassResult:
    segment_summaries: dict[int, dict] = field(default_factory=dict)
    seen_cells: dict[int, list[str]] = field(default_factory=dict)
    cells: list[dict] = field(default_factory=list)
    saturated_cells: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    request_count: int = 0

    @property
    def segment_ids(self) -> set[int]:
        return set(self.segment_summaries)

    def audit_summary(self) -> dict:
        return {
            "request_count": self.request_count,
            "unique_segment_count": len(self.segment_summaries),
            "cell_count": len(self.cells),
            "saturated_cells": self.saturated_cells,
            "errors": self.errors,
            "cells": self.cells,
        }


def enumerate_source_visible_segments(
    client,
    root_bounds: Bounds,
    *,
    max_depth: int,
    before_request: RequestHook = lambda: None,
) -> EnumerationPassResult:
    """递归细分所有返回 10 条的单元；仍饱和的叶子显式记为不完整。"""
    if max_depth < 0:
        raise ValueError("max_depth 不能小于 0")
    result = EnumerationPassResult()

    def visit(bounds: Bounds, depth: int) -> None:
        cell_key = bounds.key(depth)
        try:
            before_request()
            result.request_count += 1
            payload = client.explore_segments(bounds.as_tuple())
            segments = payload.get("segments") if isinstance(payload, dict) else None
            if not isinstance(segments, list):
                raise ValueError("Strava explore 响应缺少 segments 数组")
        except Exception as exc:  # 网络/API 错误属于批次证据，不伪装为空结果
            result.errors.append({"cell": cell_key, "error": _bounded_error(exc)})
            result.cells.append(
                {"cell": cell_key, "depth": depth, "status": "error"}
            )
            return

        ids: list[int] = []
        for summary in segments:
            try:
                segment_id = int(summary["id"])
            except (KeyError, TypeError, ValueError):
                result.errors.append(
                    {"cell": cell_key, "error": "invalid_segment_id"}
                )
                continue
            ids.append(segment_id)
            result.segment_summaries[segment_id] = summary
            result.seen_cells.setdefault(segment_id, []).append(cell_key)

        returned_count = len(segments)
        status = "leaf" if returned_count < 10 else "split"
        if returned_count == 10 and depth >= max_depth:
            status = "saturated"
            result.saturated_cells.append(cell_key)
        result.cells.append(
            {
                "cell": cell_key,
                "depth": depth,
                "returned_count": returned_count,
                "status": status,
            }
        )
        if returned_count == 10 and depth < max_depth:
            for child in bounds.split():
                visit(child, depth + 1)

    visit(root_bounds, 0)
    return result


def compare_passes(first: EnumerationPassResult, second: EnumerationPassResult) -> dict:
    first_ids = first.segment_ids
    second_ids = second.segment_ids
    return {
        "identical": first_ids == second_ids,
        "only_in_pass_1": sorted(first_ids - second_ids),
        "only_in_pass_2": sorted(second_ids - first_ids),
    }


def parse_duration_seconds(value: object) -> int | None:
    """解析 Strava 的 H:MM:SS / M:SS；未知值保持为空。"""
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?::\d{1,2}){1,2}", value):
        return None
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds if seconds < 60 else None
    hours, minutes, seconds = parts
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def fetch_segment_observation(
    client,
    segment_id: int,
    summary: dict,
    *,
    seen_passes: dict[str, list[str]],
    root_bounds: Bounds,
    region_polygon: tuple[tuple[float, float], ...],
    before_request: RequestHook = lambda: None,
    observed_at: datetime,
) -> dict:
    """抓详情和原始经纬度流，并压成数据库所需的最小事实。"""
    failures: dict[str, str] = {}
    try:
        before_request()
        detail = client.get_segment_detail(segment_id)
        if not isinstance(detail, dict) or int(detail.get("id", 0)) != segment_id:
            raise ValueError("segment detail id 不一致")
        detail_status = "complete"
    except Exception as exc:
        detail = {}
        detail_status = "failed"
        failures["detail"] = _bounded_error(exc)

    try:
        before_request()
        stream_payload = client.get_segment_latlng_stream(segment_id)
        latlng = stream_payload.get("latlng") if isinstance(stream_payload, dict) else None
        if not isinstance(latlng, dict) or not isinstance(latlng.get("data"), list):
            raise ValueError("segment stream 缺少 latlng.data")
        points = [_valid_point(point) for point in latlng["data"]]
        if len(points) < 2:
            raise ValueError("segment stream 少于两个有效点")
        original_size = int(latlng.get("original_size", 0))
        if original_size != len(points):
            raise ValueError("segment stream 不是完整 high-resolution 几何")
        geometry_status = "complete"
    except Exception as exc:
        latlng = {}
        points = []
        original_size = None
        geometry_status = "failed"
        failures["geometry"] = _bounded_error(exc)

    source = detail or summary
    activity_type = source.get("activity_type", summary.get("activity_type", "Ride"))
    if activity_type != "Ride":
        failures["activity_type"] = f"unexpected:{activity_type}"
        detail_status = "failed"

    xoms = detail.get("xoms") if isinstance(detail.get("xoms"), dict) else {}
    start_latlng = source.get("start_latlng") or []
    end_latlng = source.get("end_latlng") or []
    return {
        "source_platform": "strava",
        "source_segment_id": str(segment_id),
        "source_url": f"https://www.strava.com/segments/{segment_id}",
        "source_name": str(source.get("name") or summary.get("name") or segment_id)[:255],
        "observed_at": observed_at,
        "source_created_at": _parse_datetime(detail.get("created_at")),
        "source_updated_at": _parse_datetime(detail.get("updated_at")),
        "activity_type": "Ride",
        "city": _text_or_none(source.get("city")),
        "state": _text_or_none(source.get("state")),
        "country": _text_or_none(source.get("country")),
        "is_private": _bool_or_none(detail.get("private")),
        "is_hazardous": _bool_or_none(detail.get("hazardous")),
        "climb_category": _int_or_none(source.get("climb_category")),
        "distance_m": _float_or_none(source.get("distance")),
        "average_gradient_pct": _float_or_none(source.get("average_grade")),
        "maximum_gradient_pct": _float_or_none(detail.get("maximum_grade")),
        "elevation_gain_m": _float_or_none(source.get("elevation_difference")),
        "elevation_high_m": _float_or_none(detail.get("elevation_high")),
        "elevation_low_m": _float_or_none(detail.get("elevation_low")),
        "athlete_count": _int_or_none(detail.get("athlete_count")),
        "effort_count": _int_or_none(detail.get("effort_count")),
        "star_count": _int_or_none(detail.get("star_count")),
        "kom_time_s": parse_duration_seconds(xoms.get("kom")),
        "qom_time_s": parse_duration_seconds(xoms.get("qom")),
        "overall_best_time_s": parse_duration_seconds(xoms.get("overall")),
        "start_lat": _coordinate(start_latlng, 0),
        "start_lon": _coordinate(start_latlng, 1),
        "end_lat": _coordinate(end_latlng, 0),
        "end_lon": _coordinate(end_latlng, 1),
        "source_line_wkt": _line_wkt(points) if points else None,
        "geometry_point_count": len(points) if points else None,
        "geometry_original_size": original_size,
        "geometry_resolution": _text_or_none(latlng.get("resolution")),
        "query_bounds_relation": _bounds_relation(points, root_bounds),
        "region_membership": _polygon_relation(points, region_polygon),
        "seen_passes_json": seen_passes,
        "detail_status": detail_status,
        "geometry_status": geometry_status,
        "leaderboard_status": "not_collected",
        "failure_json": failures or None,
    }


def _valid_point(value: object) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("latlng 点格式无效")
    lat, lon = float(value[0]), float(value[1])
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("latlng 点不是有限数")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("latlng 点越界")
    return lat, lon


def _line_wkt(points: list[tuple[float, float]]) -> str:
    coordinates = ", ".join(f"{lon:.7f} {lat:.7f}" for lat, lon in points)
    return f"LINESTRING ({coordinates})"


def _bounds_relation(points: list[tuple[float, float]], bounds: Bounds) -> str:
    if not points:
        return "unknown"
    inside = [
        bounds.south <= lat <= bounds.north and bounds.west <= lon <= bounds.east
        for lat, lon in points
    ]
    if all(inside):
        return "inside"
    if any(inside):
        return "crosses"
    return "outside"


def _polygon_relation(
    points: list[tuple[float, float]],
    polygon_lon_lat: tuple[tuple[float, float], ...],
) -> str:
    if not points:
        return "unknown"
    polygon = tuple((lat, lon) for lon, lat in polygon_lon_lat)
    inside = [_point_in_polygon(point, polygon) for point in points]
    if all(inside):
        return "inside"
    if any(inside) or _polyline_crosses_polygon(points, polygon):
        return "crosses"
    return "outside"


def _point_in_polygon(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    y, x = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        y1, x1 = previous
        y2, x2 = current
        if _point_on_segment(point, previous, current):
            return True
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x <= crossing_x:
                inside = not inside
        previous = current
    return inside


def _polyline_crosses_polygon(
    points: list[tuple[float, float]],
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    polygon_edges = list(zip(polygon, (*polygon[1:], polygon[0])))
    for line_start, line_end in zip(points, points[1:]):
        if any(
            _segments_intersect(line_start, line_end, edge_start, edge_end)
            for edge_start, edge_end in polygon_edges
        ):
            return True
    return False


def _point_on_segment(point, start, end, epsilon: float = 1e-10) -> bool:
    py, px = point
    sy, sx = start
    ey, ex = end
    cross = (px - sx) * (ey - sy) - (py - sy) * (ex - sx)
    if abs(cross) > epsilon:
        return False
    return (
        min(sx, ex) - epsilon <= px <= max(sx, ex) + epsilon
        and min(sy, ey) - epsilon <= py <= max(sy, ey) + epsilon
    )


def _segments_intersect(a, b, c, d) -> bool:
    def orientation(p, q, r):
        py, px = p
        qy, qx = q
        ry, rx = r
        value = (qx - px) * (ry - py) - (qy - py) * (rx - px)
        if abs(value) <= 1e-10:
            return 0
        return 1 if value > 0 else -1

    orientations = (
        orientation(a, b, c),
        orientation(a, b, d),
        orientation(c, d, a),
        orientation(c, d, b),
    )
    if orientations[0] != orientations[1] and orientations[2] != orientations[3]:
        return True
    return any(
        turn == 0 and _point_on_segment(point, start, end)
        for turn, point, start, end in (
            (orientations[0], c, a, b),
            (orientations[1], d, a, b),
            (orientations[2], a, c, d),
            (orientations[3], b, c, d),
        )
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coordinate(value: object, index: int) -> float | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        result = float(value[index])
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _text_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        result = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return result if result is None or math.isfinite(result) else None


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _bounded_error(exc: Exception) -> str:
    return f"{type(exc).__name__}:{str(exc)[:160]}"
