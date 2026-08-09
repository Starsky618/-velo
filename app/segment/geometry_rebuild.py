"""赛段标准几何替换与历史成绩重建核心。

本模块只负责 segment 自己的状态：准备候选几何、重新匹配活动、原子替换
segments/segment_efforts。路线认知的失效和来源登记由 admin 编排层调用下游
route_cognition hook，避免 segment 反向依赖路线认知。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import hashlib
import math
import re
from types import SimpleNamespace

from geoalchemy2 import WKTElement
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.common.geo import infer_city_from_coords
from app.common.geometry_hash import SEGMENT_GEOMETRY_NORMALIZATION_VERSION, stable_line_hash
from app.segment._geo_utils import _haversine, _sample_elevation_profile
from app.segment.algorithms import calculate_difficulty, calculate_max_gradient
from app.segment.coord_convert import convert_points_to_wgs84
from app.segment.models import (
    Segment,
    SegmentEffort,
    SegmentGeometryRevision,
    SegmentRoutingCandidate,
)
from app.segment.routing_candidates import (
    SegmentRoutingCandidateIntegrityError,
    validate_routing_candidate_record,
)
from app.segment.service_create import _build_segment_elevation_result
from app.segment.source_observations import (
    SegmentSourceObservationError,
    parse_strava_segment_id,
    resolve_source_observation,
)


SEGMENT_MATCH_LOCK_NAMESPACE = 92811
SEGMENT_GEOMETRY_EPOCH_LOCK_NAMESPACE = 92812
SEGMENT_GEOMETRY_EPOCH_LOCK_KEY = 0
SEGMENT_GEOMETRY_GATE_VERSION = "segment_geometry_gate_v1"
MAX_SOURCE_DISTANCE_DELTA_RATIO = 0.03
MAX_CURRENT_DISTANCE_DELTA_RATIO = 0.05
MAX_ENDPOINT_SHIFT_M = 100.0
MAX_HAUSDORFF_DISTANCE_M = 50.0
MAX_DIRECTED_P95_DISTANCE_M = 25.0
MAX_DISCRETE_FRECHET_DISTANCE_M = 50.0
SHAPE_SAMPLE_SPACING_M = 20.0
MAX_SHAPE_ANALYSIS_DISTANCE_M = 30_000.0


class SegmentGeometryRevisionError(ValueError):
    """候选几何无法安全暂存或激活。"""


class SegmentGeometryGateError(SegmentGeometryRevisionError):
    """确定性门禁拒绝候选；Agent 不能用文字解释覆盖。"""

    def __init__(self, *, gate: str, violations: list[dict], metrics: dict):
        self.gate = gate
        self.violations = violations
        self.metrics = metrics
        codes = ", ".join(item["code"] for item in violations)
        super().__init__(f"赛段几何{gate}门未通过：{codes}")

    def as_detail(self) -> dict:
        return {
            "code": "segment_geometry_gate_failed",
            "gate": self.gate,
            "message": str(self),
            "violations": self.violations,
            "metrics": self.metrics,
        }


class ObsoleteSegmentGeometryAttempt(SegmentGeometryRevisionError):
    """旧 RQ attempt 已被新的 job_id 取代，必须只读退出。"""


@dataclass(frozen=True)
class PreparedSegmentGeometry:
    reference_line_wkt: str
    geometry_hash: str
    distance: float
    elevation_gain: float
    elevation_loss: float
    avg_gradient: float
    elevation_profile_json: str
    max_gradient: float | None
    difficulty: str
    city: str
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float


@dataclass(frozen=True)
class SegmentGeometryGateMetrics:
    validation_version: str
    source_segment_id: str
    source_distance_m: float
    candidate_distance_m: float
    source_distance_delta_ratio: float
    current_distance_m: float
    current_distance_delta_ratio: float
    start_shift_m: float
    end_shift_m: float
    hausdorff_m: float
    previous_to_candidate_p95_m: float
    candidate_to_previous_p95_m: float
    discrete_frechet_m: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EffortCandidate:
    activity_id: int
    user_id: int
    elapsed_time: int
    avg_speed: float
    avg_power: float | None
    start_index: int
    end_index: int


@dataclass(frozen=True)
class ActivationSummary:
    segment_id: int
    revision_id: int
    matched_efforts: int
    inserted_efforts: int
    updated_efforts: int
    deleted_efforts: int


def parse_linestring_wkt(wkt: str) -> list[tuple[float, float]]:
    """把 WKT (lon lat) 转成 matcher 使用的 (lat, lon)。"""
    match = re.search(r"LINESTRING\s*\((.+)\)", wkt, re.IGNORECASE)
    if not match:
        return []
    coordinates: list[tuple[float, float]] = []
    for pair in match.group(1).split(","):
        values = pair.strip().split()
        if len(values) != 2:
            return []
        try:
            lon, lat = (float(value) for value in values)
        except ValueError:
            return []
        if not math.isfinite(lat) or not math.isfinite(lon):
            return []
        coordinates.append((lat, lon))
    return coordinates


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return math.inf
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _project_local_m(
    coordinates: list[tuple[float, float]],
    *,
    origin_lat: float,
    origin_lon: float,
) -> list[tuple[float, float]]:
    radius_m = 6_371_000.0
    lon_scale = math.cos(math.radians(origin_lat))
    return [
        (
            math.radians(lon - origin_lon) * radius_m * lon_scale,
            math.radians(lat - origin_lat) * radius_m,
        )
        for lat, lon in coordinates
    ]


def _point_to_segment_distance_m(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    denominator = dx * dx + dy * dy
    if denominator == 0:
        return math.hypot(px - sx, py - sy)
    ratio = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / denominator))
    return math.hypot(px - (sx + ratio * dx), py - (sy + ratio * dy))


def _directed_polyline_distances_m(
    source: list[tuple[float, float]],
    target: list[tuple[float, float]],
) -> list[float]:
    if len(source) < 2 or len(target) < 2:
        return [math.inf]
    return [
        min(
            _point_to_segment_distance_m(point, target[index - 1], target[index])
            for index in range(1, len(target))
        )
        for point in source
    ]


def _densify_polyline_m(
    coordinates: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if len(coordinates) < 2:
        return coordinates
    segment_lengths = [
        math.dist(coordinates[index - 1], coordinates[index])
        for index in range(1, len(coordinates))
    ]
    total_length = sum(segment_lengths)
    if total_length <= 0:
        return [coordinates[0], coordinates[-1]]
    spacing = SHAPE_SAMPLE_SPACING_M
    targets = [index * spacing for index in range(int(total_length // spacing) + 1)]
    if not targets or targets[-1] < total_length:
        targets.append(total_length)

    densified = []
    segment_index = 0
    distance_before_segment = 0.0
    for target_distance in targets:
        while (
            segment_index < len(segment_lengths) - 1
            and distance_before_segment + segment_lengths[segment_index] < target_distance
        ):
            distance_before_segment += segment_lengths[segment_index]
            segment_index += 1
        segment_length = segment_lengths[segment_index]
        if segment_length <= 0:
            densified.append(coordinates[segment_index + 1])
            continue
        ratio = min(
            1.0,
            max(0.0, (target_distance - distance_before_segment) / segment_length),
        )
        start = coordinates[segment_index]
        end = coordinates[segment_index + 1]
        densified.append(
            (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
        )
    return densified


def _discrete_frechet_distance_m(
    previous: list[tuple[float, float]],
    candidate: list[tuple[float, float]],
) -> float:
    """顺序敏感的离散 Fréchet；错连、回头或乱序不能靠同顶点集合绕过。"""
    if not previous or not candidate:
        return math.inf
    prior_row = [math.inf] * len(candidate)
    for previous_index, previous_point in enumerate(previous):
        current_row = [math.inf] * len(candidate)
        for candidate_index, candidate_point in enumerate(candidate):
            point_distance = math.dist(previous_point, candidate_point)
            if previous_index == 0 and candidate_index == 0:
                coupling = point_distance
            elif previous_index == 0:
                coupling = max(current_row[candidate_index - 1], point_distance)
            elif candidate_index == 0:
                coupling = max(prior_row[candidate_index], point_distance)
            else:
                coupling = max(
                    min(
                        prior_row[candidate_index],
                        prior_row[candidate_index - 1],
                        current_row[candidate_index - 1],
                    ),
                    point_distance,
                )
            current_row[candidate_index] = coupling
        prior_row = current_row
    return prior_row[-1]


def _polyline_shape_metrics(
    previous_coordinates: list[tuple[float, float]],
    candidate_coordinates: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    if len(previous_coordinates) < 2 or len(candidate_coordinates) < 2:
        return math.inf, math.inf, math.inf, math.inf
    combined = previous_coordinates + candidate_coordinates
    origin_lat = sum(point[0] for point in combined) / len(combined)
    origin_lon = sum(point[1] for point in combined) / len(combined)
    previous_xy = _project_local_m(
        previous_coordinates,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
    )
    candidate_xy = _project_local_m(
        candidate_coordinates,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
    )
    previous_length_m = sum(
        math.dist(previous_xy[index - 1], previous_xy[index])
        for index in range(1, len(previous_xy))
    )
    candidate_length_m = sum(
        math.dist(candidate_xy[index - 1], candidate_xy[index])
        for index in range(1, len(candidate_xy))
    )
    if max(previous_length_m, candidate_length_m) > MAX_SHAPE_ANALYSIS_DISTANCE_M:
        raise SegmentGeometryGateError(
            gate="geometry",
            violations=[
                {
                    "code": "shape_analysis_distance_limit",
                    "actual": max(previous_length_m, candidate_length_m),
                    "limit": MAX_SHAPE_ANALYSIS_DISTANCE_M,
                }
            ],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    previous_dense = _densify_polyline_m(previous_xy)
    candidate_dense = _densify_polyline_m(candidate_xy)
    previous_to_candidate = _directed_polyline_distances_m(
        previous_dense,
        candidate_dense,
    )
    candidate_to_previous = _directed_polyline_distances_m(
        candidate_dense,
        previous_dense,
    )
    return (
        max(max(previous_to_candidate), max(candidate_to_previous)),
        _percentile(previous_to_candidate, 0.95),
        _percentile(candidate_to_previous, 0.95),
        _discrete_frechet_distance_m(previous_dense, candidate_dense),
    )


def _validate_prepared_geometry_integrity(
    prepared: PreparedSegmentGeometry,
    *,
    gate: str,
) -> tuple[list[tuple[float, float]], float]:
    """让折线本体决定 hash、距离和端点，拒绝旁路字段与本体分叉。"""
    coordinates = parse_linestring_wkt(prepared.reference_line_wkt)
    if len(coordinates) < 2:
        raise SegmentGeometryGateError(
            gate=gate,
            violations=[{"code": "invalid_candidate_linestring"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )

    scalar_values = {
        "distance": prepared.distance,
        "elevation_gain": prepared.elevation_gain,
        "elevation_loss": prepared.elevation_loss,
        "avg_gradient": prepared.avg_gradient,
        "start_lat": prepared.start_lat,
        "start_lon": prepared.start_lon,
        "end_lat": prepared.end_lat,
        "end_lon": prepared.end_lon,
    }
    if prepared.max_gradient is not None:
        scalar_values["max_gradient"] = prepared.max_gradient
    non_finite_fields = [
        field for field, value in scalar_values.items() if not math.isfinite(value)
    ]
    try:
        elevation_profile = json.loads(prepared.elevation_profile_json)
    except (TypeError, json.JSONDecodeError):
        elevation_profile = None
    if (
        not isinstance(elevation_profile, list)
        or not elevation_profile
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in elevation_profile
        )
    ):
        non_finite_fields.append("elevation_profile")
    if non_finite_fields:
        raise SegmentGeometryGateError(
            gate=gate,
            violations=[
                {
                    "code": "non_finite_or_invalid_candidate_fields",
                    "fields": sorted(non_finite_fields),
                }
            ],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )

    actual_hash = stable_line_hash(prepared.reference_line_wkt)
    actual_distance_m = sum(
        _haversine(
            coordinates[index - 1][0],
            coordinates[index - 1][1],
            coordinates[index][0],
            coordinates[index][1],
        )
        for index in range(1, len(coordinates))
    )
    start_shift_m = _haversine(
        coordinates[0][0],
        coordinates[0][1],
        prepared.start_lat,
        prepared.start_lon,
    )
    end_shift_m = _haversine(
        coordinates[-1][0],
        coordinates[-1][1],
        prepared.end_lat,
        prepared.end_lon,
    )
    violations = []
    if actual_hash != prepared.geometry_hash:
        violations.append(
            {
                "code": "candidate_geometry_hash_changed",
                "expected": prepared.geometry_hash,
                "actual": actual_hash,
            }
        )
    distance_tolerance_m = max(1.0, actual_distance_m * 0.001)
    if abs(actual_distance_m - prepared.distance) > distance_tolerance_m:
        violations.append(
            {
                "code": "candidate_distance_field_mismatch",
                "actual": prepared.distance,
                "derived": actual_distance_m,
                "limit": distance_tolerance_m,
            }
        )
    if start_shift_m > 1.0:
        violations.append(
            {
                "code": "candidate_start_field_mismatch",
                "actual": start_shift_m,
                "limit": 1.0,
            }
        )
    if end_shift_m > 1.0:
        violations.append(
            {
                "code": "candidate_end_field_mismatch",
                "actual": end_shift_m,
                "limit": 1.0,
            }
        )
    if violations:
        raise SegmentGeometryGateError(
            gate=gate,
            violations=violations,
            metrics={
                "validation_version": SEGMENT_GEOMETRY_GATE_VERSION,
                "candidate_distance_m": actual_distance_m,
            },
        )
    return coordinates, actual_distance_m


def candidate_payload_hash(prepared: PreparedSegmentGeometry) -> str:
    """绑定最终会写入 Segment 的几何、海拔和全部派生字段。"""
    _validate_prepared_geometry_integrity(prepared, gate="write")
    payload = {
        "reference_line_wkt": prepared.reference_line_wkt,
        "geometry_hash": prepared.geometry_hash,
        "distance": prepared.distance,
        "elevation_gain": prepared.elevation_gain,
        "elevation_loss": prepared.elevation_loss,
        "avg_gradient": prepared.avg_gradient,
        "elevation_profile": json.loads(prepared.elevation_profile_json),
        "max_gradient": prepared.max_gradient,
        "difficulty": prepared.difficulty,
        "city": prepared.city,
        "start_lat": prepared.start_lat,
        "start_lon": prepared.start_lon,
        "end_lat": prepared.end_lat,
        "end_lon": prepared.end_lon,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def enforce_segment_geometry_gate_metrics(metrics: SegmentGeometryGateMetrics) -> None:
    """三门共用的固定阈值；不能由请求、Skill 或 Agent 临时放宽。"""
    numeric_metrics = {
        key: value
        for key, value in metrics.as_dict().items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    non_finite_metrics = [
        key for key, value in numeric_metrics.items() if not math.isfinite(value)
    ]
    if non_finite_metrics:
        raise SegmentGeometryGateError(
            gate="geometry",
            violations=[
                {
                    "code": "non_finite_gate_metrics",
                    "fields": sorted(non_finite_metrics),
                }
            ],
            metrics=metrics.as_dict(),
        )

    source_violations = []
    if metrics.source_distance_delta_ratio > MAX_SOURCE_DISTANCE_DELTA_RATIO:
        source_violations.append(
            {
                "code": "source_distance_mismatch",
                "actual": metrics.source_distance_delta_ratio,
                "limit": MAX_SOURCE_DISTANCE_DELTA_RATIO,
            }
        )
    if source_violations:
        raise SegmentGeometryGateError(
            gate="source",
            violations=source_violations,
            metrics=metrics.as_dict(),
        )

    geometry_violations = []
    checks = (
        (
            "current_distance_mismatch",
            metrics.current_distance_delta_ratio,
            MAX_CURRENT_DISTANCE_DELTA_RATIO,
        ),
        ("start_endpoint_shift", metrics.start_shift_m, MAX_ENDPOINT_SHIFT_M),
        ("end_endpoint_shift", metrics.end_shift_m, MAX_ENDPOINT_SHIFT_M),
        ("hausdorff_distance", metrics.hausdorff_m, MAX_HAUSDORFF_DISTANCE_M),
        (
            "previous_to_candidate_p95",
            metrics.previous_to_candidate_p95_m,
            MAX_DIRECTED_P95_DISTANCE_M,
        ),
        (
            "candidate_to_previous_p95",
            metrics.candidate_to_previous_p95_m,
            MAX_DIRECTED_P95_DISTANCE_M,
        ),
        (
            "discrete_frechet_distance",
            metrics.discrete_frechet_m,
            MAX_DISCRETE_FRECHET_DISTANCE_M,
        ),
    )
    for code, actual, limit in checks:
        if actual > limit:
            geometry_violations.append({"code": code, "actual": actual, "limit": limit})
    if geometry_violations:
        raise SegmentGeometryGateError(
            gate="geometry",
            violations=geometry_violations,
            metrics=metrics.as_dict(),
        )


def build_segment_geometry_gate_metrics(
    *,
    previous_wkt: str,
    current_distance_m: float,
    current_start_lat: float,
    current_start_lon: float,
    current_end_lat: float,
    current_end_lon: float,
    prepared: PreparedSegmentGeometry,
    source_url: str,
    source_distance_m: float,
    integrity_gate: str = "geometry",
) -> SegmentGeometryGateMetrics:
    try:
        source_segment_id = parse_strava_segment_id(source_url)
    except SegmentSourceObservationError as exc:
        raise SegmentGeometryGateError(
            gate="source",
            violations=[{"code": "invalid_strava_segment_url"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        ) from exc
    if not math.isfinite(source_distance_m) or source_distance_m <= 0:
        raise SegmentGeometryGateError(
            gate="source",
            violations=[{"code": "invalid_source_distance"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    if not math.isfinite(current_distance_m) or current_distance_m <= 0:
        raise SegmentGeometryGateError(
            gate="geometry",
            violations=[{"code": "invalid_current_distance"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    candidate_coordinates, candidate_distance_m = _validate_prepared_geometry_integrity(
        prepared,
        gate=integrity_gate,
    )
    previous_coordinates = parse_linestring_wkt(previous_wkt)
    if len(previous_coordinates) < 2:
        raise SegmentGeometryGateError(
            gate="geometry",
            violations=[{"code": "invalid_current_linestring"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    hausdorff_m, previous_p95_m, candidate_p95_m, frechet_m = _polyline_shape_metrics(
        previous_coordinates,
        candidate_coordinates,
    )
    return SegmentGeometryGateMetrics(
        validation_version=SEGMENT_GEOMETRY_GATE_VERSION,
        source_segment_id=source_segment_id,
        source_distance_m=float(source_distance_m),
        candidate_distance_m=candidate_distance_m,
        source_distance_delta_ratio=abs(candidate_distance_m - source_distance_m)
        / source_distance_m,
        current_distance_m=float(current_distance_m),
        current_distance_delta_ratio=abs(candidate_distance_m - current_distance_m)
        / current_distance_m,
        start_shift_m=_haversine(
            current_start_lat,
            current_start_lon,
            candidate_coordinates[0][0],
            candidate_coordinates[0][1],
        ),
        end_shift_m=_haversine(
            current_end_lat,
            current_end_lon,
            candidate_coordinates[-1][0],
            candidate_coordinates[-1][1],
        ),
        hausdorff_m=hausdorff_m,
        previous_to_candidate_p95_m=previous_p95_m,
        candidate_to_previous_p95_m=candidate_p95_m,
        discrete_frechet_m=frechet_m,
    )


def prepare_segment_geometry(
    reference_points: list[dict],
    *,
    coordinate_system: str,
    source_distance_m: float,
) -> PreparedSegmentGeometry:
    """把腾讯驾车折线变成可激活的 WGS84 标准几何和 GLO-30 派生数据。"""
    points = [dict(point) for point in reference_points]
    points = convert_points_to_wgs84(points, coordinate_system)
    if len(points) < 3:
        raise SegmentGeometryRevisionError("标准几何必须是腾讯驾车返回的完整折线，至少需要 3 个点")

    distance = sum(
        _haversine(
            points[index - 1]["lat"],
            points[index - 1]["lon"],
            points[index]["lat"],
            points[index]["lon"],
        )
        for index in range(1, len(points))
    )
    if not math.isfinite(distance) or distance < 1.0:
        raise SegmentGeometryRevisionError("标准几何距离过短")

    # 最便宜的来源门放在 GLO-30 之前：公开距离对不上时，不浪费海拔查询，
    # 也不允许后续用“来源口径不同”解释放行。stage/activate 仍会再次全量校验。
    if not math.isfinite(source_distance_m) or source_distance_m <= 0:
        raise SegmentGeometryGateError(
            gate="source",
            violations=[{"code": "invalid_source_distance"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    source_delta_ratio = abs(distance - source_distance_m) / source_distance_m
    if source_delta_ratio > MAX_SOURCE_DISTANCE_DELTA_RATIO:
        raise SegmentGeometryGateError(
            gate="source",
            violations=[
                {
                    "code": "source_distance_mismatch",
                    "actual": source_delta_ratio,
                    "limit": MAX_SOURCE_DISTANCE_DELTA_RATIO,
                }
            ],
            metrics={
                "validation_version": SEGMENT_GEOMETRY_GATE_VERSION,
                "source_distance_m": float(source_distance_m),
                "candidate_distance_m": distance,
                "source_distance_delta_ratio": source_delta_ratio,
            },
        )

    elevation_result = _build_segment_elevation_result(points)
    elevations = [float(point[2]) for point in elevation_result.snapshot]
    if len(elevations) != len(points) or any(
        not math.isfinite(elevation) for elevation in elevations
    ):
        raise SegmentGeometryRevisionError("GLO-30 海拔点数与标准几何不一致")

    elevated_points = [
        SimpleNamespace(
            latitude=point["lat"],
            longitude=point["lon"],
            elevation=elevations[index],
        )
        for index, point in enumerate(points)
    ]
    max_gradient = calculate_max_gradient(elevated_points)
    elevation_gain = float(elevation_result.climb)
    elevation_loss = float(elevation_result.descent)
    avg_gradient = round((elevations[-1] - elevations[0]) / distance * 100, 1)
    difficulty = calculate_difficulty(distance, elevation_gain, max_gradient)
    city = infer_city_from_coords(points[0]["lat"], points[0]["lon"])
    elevation_profile = _sample_elevation_profile(
        [{"ele": point[1]} for point in elevation_result.profile],
        target_count=80,
    )
    wkt = "LINESTRING(" + ",".join(
        f"{point['lon']} {point['lat']}" for point in points
    ) + ")"
    prepared = PreparedSegmentGeometry(
        reference_line_wkt=wkt,
        geometry_hash=stable_line_hash(wkt),
        distance=distance,
        elevation_gain=elevation_gain,
        elevation_loss=elevation_loss,
        avg_gradient=avg_gradient,
        elevation_profile_json=json.dumps(elevation_profile),
        max_gradient=max_gradient,
        difficulty=difficulty,
        city=city,
        start_lat=points[0]["lat"],
        start_lon=points[0]["lon"],
        end_lat=points[-1]["lat"],
        end_lon=points[-1]["lon"],
    )
    _validate_prepared_geometry_integrity(prepared, gate="geometry")
    return prepared


def _resolve_bound_source_observation(
    *,
    observation_id: str,
    segment: Segment,
    current_wkt: str,
):
    try:
        return resolve_source_observation(
            observation_id,
            segment_id=segment.id,
            segment_name=segment.name,
            current_wkt=current_wkt,
            current_start_lat=segment.start_lat,
            current_start_lon=segment.start_lon,
            current_end_lat=segment.end_lat,
            current_end_lon=segment.end_lon,
        )
    except SegmentSourceObservationError as exc:
        raise SegmentGeometryGateError(
            gate="source",
            violations=[{"code": "untrusted_or_mismatched_source_observation"}],
            metrics={
                "validation_version": SEGMENT_GEOMETRY_GATE_VERSION,
                "source_observation_id": observation_id,
            },
        ) from exc


def prepare_segment_geometry_from_evidence(
    db: Session,
    *,
    segment_id: int,
    source_observation_id: str,
    routing_candidate_id: int,
) -> PreparedSegmentGeometry:
    """只从只读来源目录和服务端腾讯候选准备派生数据。"""
    row = (
        db.query(Segment, func.ST_AsText(Segment.reference_line).label("reference_line_wkt"))
        .filter(Segment.id == segment_id)
        .first()
    )
    if row is None:
        raise SegmentGeometryRevisionError("赛段不存在")
    segment, current_wkt = row
    observation = _resolve_bound_source_observation(
        observation_id=source_observation_id,
        segment=segment,
        current_wkt=current_wkt,
    )
    candidate = db.get(SegmentRoutingCandidate, routing_candidate_id)
    if candidate is None:
        raise SegmentGeometryGateError(
            gate="source",
            violations=[{"code": "routing_candidate_not_found"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    try:
        validate_routing_candidate_record(
            candidate,
            expected_segment_id=segment_id,
            require_ready=True,
        )
    except SegmentRoutingCandidateIntegrityError as exc:
        raise SegmentGeometryGateError(
            gate="source",
            violations=[{"code": "untrusted_routing_candidate"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        ) from exc
    coordinates = parse_linestring_wkt(candidate.reference_line_wkt)
    return prepare_segment_geometry(
        [{"lat": lat, "lon": lon} for lat, lon in coordinates],
        coordinate_system="wgs84",
        source_distance_m=observation.observed_distance_m,
    )


def stage_geometry_revision(
    db: Session,
    *,
    segment_id: int,
    prepared: PreparedSegmentGeometry,
    source_observation_id: str,
    routing_candidate_id: int,
    created_by: int,
) -> SegmentGeometryRevision:
    """暂存候选几何；不修改标准线和成绩。事务由调用方提交。"""
    # 先锁稳定的 segment 父行，再查 pending，避免两个并发请求都通过“无任务”检查，
    # 最后只靠 partial unique 抛出难以解释的 IntegrityError。
    row = (
        db.query(Segment, func.ST_AsText(Segment.reference_line).label("reference_line_wkt"))
        .filter(Segment.id == segment_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if row is None:
        raise SegmentGeometryRevisionError("赛段不存在")
    segment, previous_wkt = row
    pending = (
        db.query(SegmentGeometryRevision.id)
        .filter(
            SegmentGeometryRevision.segment_id == segment_id,
            SegmentGeometryRevision.status.in_(("staged", "processing")),
        )
        .first()
    )
    if pending is not None:
        raise SegmentGeometryRevisionError("该赛段已有正在处理的标准几何替换")
    if not previous_wkt:
        raise SegmentGeometryRevisionError("赛段缺少现有标准几何")

    observation = _resolve_bound_source_observation(
        observation_id=source_observation_id,
        segment=segment,
        current_wkt=previous_wkt,
    )
    routing_candidate = (
        db.query(SegmentRoutingCandidate)
        .filter(SegmentRoutingCandidate.id == routing_candidate_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if routing_candidate is None:
        raise SegmentGeometryGateError(
            gate="source",
            violations=[{"code": "routing_candidate_not_found"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    try:
        validate_routing_candidate_record(
            routing_candidate,
            expected_segment_id=segment_id,
            require_ready=True,
        )
    except SegmentRoutingCandidateIntegrityError as exc:
        raise SegmentGeometryGateError(
            gate="source",
            violations=[{"code": "untrusted_routing_candidate"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        ) from exc
    if prepared.geometry_hash != routing_candidate.geometry_hash:
        raise SegmentGeometryGateError(
            gate="source",
            violations=[{"code": "prepared_geometry_not_from_routing_candidate"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )

    current_distance = float(segment.distance or 0.0)
    gate_metrics = build_segment_geometry_gate_metrics(
        previous_wkt=previous_wkt,
        current_distance_m=current_distance,
        current_start_lat=segment.start_lat,
        current_start_lon=segment.start_lon,
        current_end_lat=segment.end_lat,
        current_end_lon=segment.end_lon,
        prepared=prepared,
        source_url=observation.source_url,
        source_distance_m=observation.observed_distance_m,
    )
    enforce_segment_geometry_gate_metrics(gate_metrics)
    candidate_wkt = prepared.reference_line_wkt
    if db.bind.dialect.name == "postgresql":
        candidate_wkt = db.execute(
            text("SELECT ST_AsText(ST_GeomFromText(:candidate_wkt, 4326))"),
            {"candidate_wkt": candidate_wkt},
        ).scalar_one()
    candidate_hash = stable_line_hash(candidate_wkt)
    previous_hash = stable_line_hash(previous_wkt)
    if previous_hash == candidate_hash:
        raise SegmentGeometryRevisionError("候选几何与当前标准几何相同")

    previous_snapshot = {
        "distance": segment.distance,
        "elevation_gain": segment.elevation_gain,
        "elevation_loss": segment.elevation_loss,
        "avg_gradient": segment.avg_gradient,
        "elevation_profile": segment.elevation_profile,
        "max_gradient": segment.max_gradient,
        "difficulty": segment.difficulty,
        "city": segment.city,
        "start_lat": segment.start_lat,
        "start_lon": segment.start_lon,
        "end_lat": segment.end_lat,
        "end_lon": segment.end_lon,
    }
    revision = SegmentGeometryRevision(
        segment_id=segment_id,
        status="staged",
        previous_geometry_hash=previous_hash,
        candidate_geometry_hash=candidate_hash,
        previous_reference_line_wkt=previous_wkt,
        candidate_reference_line_wkt=candidate_wkt,
        previous_snapshot_json=json.dumps(previous_snapshot, ensure_ascii=False),
        distance=prepared.distance,
        elevation_gain=prepared.elevation_gain,
        elevation_loss=prepared.elevation_loss,
        avg_gradient=prepared.avg_gradient,
        elevation_profile=prepared.elevation_profile_json,
        max_gradient=prepared.max_gradient,
        difficulty=prepared.difficulty,
        city=prepared.city,
        start_lat=prepared.start_lat,
        start_lon=prepared.start_lon,
        end_lat=prepared.end_lat,
        end_lon=prepared.end_lon,
        match_tolerance=segment.match_tolerance if segment.match_tolerance is not None else 50.0,
        min_match_ratio=segment.min_match_ratio if segment.min_match_ratio is not None else 0.8,
        source_url=observation.source_url,
        source_segment_id=gate_metrics.source_segment_id,
        source_distance_m=gate_metrics.source_distance_m,
        source_observation_id=observation.observation_id,
        routing_candidate_id=routing_candidate.id,
        candidate_payload_hash=candidate_payload_hash(
            replace(
                prepared,
                reference_line_wkt=candidate_wkt,
                geometry_hash=candidate_hash,
            )
        ),
        validation_version=gate_metrics.validation_version,
        validation_metrics_json=json.dumps(gate_metrics.as_dict(), ensure_ascii=False),
        routing_provider="tencent",
        routing_mode="driving",
        original_coordinate_system="wgs84",
        normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        created_by=created_by,
    )
    db.add(revision)
    db.flush()
    routing_candidate.status = "consumed"
    return revision


def mark_revision_processing(
    db: Session,
    revision_id: int,
    attempt_job_id: str,
) -> SegmentGeometryRevision:
    revision = (
        db.query(SegmentGeometryRevision)
        .filter(SegmentGeometryRevision.id == revision_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if revision is None:
        raise SegmentGeometryRevisionError("标准几何替换任务不存在")
    if revision.job_id != attempt_job_id:
        raise ObsoleteSegmentGeometryAttempt("RQ attempt 已过期，不能修改当前任务")
    if revision.status == "active":
        return revision
    if revision.status not in {"staged", "processing"}:
        raise SegmentGeometryRevisionError(f"标准几何替换任务不可执行：{revision.status}")
    revision.status = "processing"
    revision.started_at = revision.started_at or datetime.now(timezone.utc)
    revision.error_message = None
    db.flush()
    return revision


def collect_effort_candidates(
    db: Session,
    revision: SegmentGeometryRevision,
) -> dict[int, EffortCandidate]:
    """对旧成绩和新线附近活动重新跑完整 matcher。"""
    activity_ids = candidate_activity_ids(
        db,
        segment_id=revision.segment_id,
        candidate_wkt=revision.candidate_reference_line_wkt,
    )
    results: dict[int, EffortCandidate] = {}
    for activity_id in activity_ids:
        effort = match_activity_to_revision(db, activity_id, revision)
        if effort is not None:
            results[activity_id] = effort
    return results


def candidate_activity_ids(db: Session, *, segment_id: int, candidate_wkt: str) -> list[int]:
    """候选集 = 旧成绩活动 + 新标准线 100m 内的已完成骑行。"""
    existing_ids = {
        row[0]
        for row in db.query(SegmentEffort.activity_id)
        .filter(SegmentEffort.segment_id == segment_id)
        .all()
    }
    if db.bind.dialect.name != "postgresql":
        return sorted(existing_ids)

    nearby_ids = set(
        db.execute(
            text(
                """
                SELECT DISTINCT tp.activity_id
                FROM trackpoints AS tp
                JOIN activities AS a ON a.id = tp.activity_id
                WHERE tp.geom IS NOT NULL
                  AND a.status = 'completed'
                  AND a.activity_type = 'cycling'
                  AND a.duplicate_of IS NULL
                  AND ST_DWithin(
                        tp.geom::geography,
                        ST_GeomFromText(:candidate_wkt, 4326)::geography,
                        100
                  )
                """
            ),
            {"candidate_wkt": candidate_wkt},
        ).scalars()
    )
    return sorted(existing_ids | nearby_ids)


def match_activity_to_revision(
    db: Session,
    activity_id: int,
    revision: SegmentGeometryRevision,
) -> EffortCandidate | None:
    from app.segment.matcher import match_segment

    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if activity is None or activity.status != "completed":
        return None
    if activity.activity_type != "cycling" or activity.duplicate_of is not None:
        return None
    trackpoints = (
        db.query(Trackpoint)
        .filter(Trackpoint.activity_id == activity_id)
        .order_by(Trackpoint.seq)
        .all()
    )
    if len(trackpoints) < 2:
        return None

    reference_coords = parse_linestring_wkt(revision.candidate_reference_line_wkt)
    if len(reference_coords) < 2:
        raise SegmentGeometryRevisionError("候选标准几何不是有效 LINESTRING")
    result = match_segment(
        trackpoints=[
            {
                "lat": point.latitude,
                "lon": point.longitude,
                "time": point.timestamp,
                "seq": point.seq,
            }
            for point in trackpoints
        ],
        segment_start=(revision.start_lat, revision.start_lon),
        segment_end=(revision.end_lat, revision.end_lon),
        reference_coords=reference_coords,
        match_tolerance=revision.match_tolerance,
        min_match_ratio=revision.min_match_ratio,
    )
    if not result["matched"] or result["elapsed_time"] <= 0:
        return None

    start_index = result["start_index"]
    end_index = result["end_index"]
    powers = [
        point.power
        for point in trackpoints
        if start_index <= point.seq <= end_index and point.power is not None
    ]
    elapsed_time = result["elapsed_time"]
    return EffortCandidate(
        activity_id=activity.id,
        user_id=activity.user_id,
        elapsed_time=elapsed_time,
        avg_speed=round((revision.distance / elapsed_time) * 3.6, 1),
        avg_power=round(sum(powers) / len(powers), 1) if powers else None,
        start_index=start_index,
        end_index=end_index,
    )


def acquire_segment_match_lock(db: Session, segment_id: int) -> None:
    """让实时匹配和几何切换按 segment 串行，关闭旧线成绩晚写入竞态。"""
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :segment_id)"),
            {"namespace": SEGMENT_MATCH_LOCK_NAMESPACE, "segment_id": segment_id},
        )


def acquire_geometry_match_read_lock(db: Session) -> None:
    """活动匹配从粗筛到成绩提交持有共享锁，避免跨几何版本漏匹配。"""
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock_shared(:namespace, :lock_key)"),
            {
                "namespace": SEGMENT_GEOMETRY_EPOCH_LOCK_NAMESPACE,
                "lock_key": SEGMENT_GEOMETRY_EPOCH_LOCK_KEY,
            },
        )


def acquire_geometry_activation_lock(db: Session) -> None:
    """几何最终追扫和切换持有排他锁，与所有实时活动粗筛形成读写屏障。"""
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :lock_key)"),
            {
                "namespace": SEGMENT_GEOMETRY_EPOCH_LOCK_NAMESPACE,
                "lock_key": SEGMENT_GEOMETRY_EPOCH_LOCK_KEY,
            },
        )


def activate_revision_core(
    db: Session,
    *,
    revision_id: int,
    attempt_job_id: str,
    precomputed_efforts: dict[int, EffortCandidate],
) -> ActivationSummary:
    """在调用方事务中原子替换标准线和成绩；不 commit。"""
    revision_ref = (
        db.query(
            SegmentGeometryRevision.id,
            SegmentGeometryRevision.segment_id,
            SegmentGeometryRevision.status,
            SegmentGeometryRevision.job_id,
        )
        .filter(SegmentGeometryRevision.id == revision_id)
        .first()
    )
    if revision_ref is None:
        raise SegmentGeometryRevisionError("标准几何替换任务不存在")
    if revision_ref.job_id != attempt_job_id:
        raise ObsoleteSegmentGeometryAttempt("RQ attempt 已过期，不能激活当前任务")
    if revision_ref.status == "active":
        existing_count = db.query(SegmentEffort.id).filter_by(
            segment_id=revision_ref.segment_id
        ).count()
        return ActivationSummary(
            revision_ref.segment_id, revision_ref.id, existing_count, 0, 0, 0
        )
    if revision_ref.status != "processing":
        raise SegmentGeometryRevisionError(
            f"标准几何替换任务不可激活：{revision_ref.status}"
        )

    # 必须在最终候选追扫之前拿全局排他屏障。活动导入已先提交 Activity，随后
    # auto_match 从粗筛到 effort commit 持共享锁：要么旧版匹配先完成、这里能看到
    # 活动并重算；要么这里先切换完成、auto_match 之后按新版几何粗筛。
    acquire_geometry_activation_lock(db)
    acquire_segment_match_lock(db, revision_ref.segment_id)
    row = (
        db.query(Segment, func.ST_AsText(Segment.reference_line).label("reference_line_wkt"))
        .filter(Segment.id == revision_ref.segment_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if row is None:
        raise SegmentGeometryRevisionError("赛段不存在")
    segment, current_wkt = row
    # 全链路锁序统一为 epoch -> Segment -> revision。retry/stage 不拿 epoch，
    # 但同样先 Segment 后 revision，因此旧 worker 与 Admin 恢复不会形成等待环。
    revision = (
        db.query(SegmentGeometryRevision)
        .filter(SegmentGeometryRevision.id == revision_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if revision is None:
        raise SegmentGeometryRevisionError("标准几何替换任务不存在")
    if revision.job_id != attempt_job_id:
        raise ObsoleteSegmentGeometryAttempt("RQ attempt 已过期，不能激活当前任务")
    if revision.status == "active":
        existing_count = db.query(SegmentEffort.id).filter_by(
            segment_id=revision.segment_id
        ).count()
        return ActivationSummary(revision.segment_id, revision.id, existing_count, 0, 0, 0)
    if revision.status != "processing":
        raise SegmentGeometryRevisionError(f"标准几何替换任务不可激活：{revision.status}")
    if stable_line_hash(current_wkt) != revision.previous_geometry_hash:
        raise SegmentGeometryRevisionError("标准几何已被其他任务修改，本任务已过期")

    # 写入门：即使 revision 行被旧代码、手工 SQL 或错误重试污染，最终事务也要
    # 用当前标准线重新执行同一组确定性校验。门禁失败时整个激活事务回滚，公开
    # segment 与成绩都保持原样，只由外层把 revision 标成 failed。
    if (
        revision.source_segment_id is None
        or revision.source_distance_m is None
        or revision.source_observation_id is None
        or revision.routing_candidate_id is None
        or revision.candidate_payload_hash is None
        or revision.validation_version != SEGMENT_GEOMETRY_GATE_VERSION
    ):
        raise SegmentGeometryGateError(
            gate="write",
            violations=[{"code": "missing_current_gate_evidence"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    activation_prepared = PreparedSegmentGeometry(
        reference_line_wkt=revision.candidate_reference_line_wkt,
        geometry_hash=revision.candidate_geometry_hash,
        distance=revision.distance,
        elevation_gain=revision.elevation_gain,
        elevation_loss=revision.elevation_loss,
        avg_gradient=revision.avg_gradient,
        elevation_profile_json=revision.elevation_profile,
        max_gradient=revision.max_gradient,
        difficulty=revision.difficulty,
        city=revision.city,
        start_lat=revision.start_lat,
        start_lon=revision.start_lon,
        end_lat=revision.end_lat,
        end_lon=revision.end_lon,
    )
    if candidate_payload_hash(activation_prepared) != revision.candidate_payload_hash:
        raise SegmentGeometryGateError(
            gate="write",
            violations=[{"code": "candidate_payload_changed"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    observation = _resolve_bound_source_observation(
        observation_id=revision.source_observation_id,
        segment=segment,
        current_wkt=current_wkt,
    )
    if (
        observation.source_segment_id != revision.source_segment_id
        or observation.source_url != revision.source_url
        or observation.observed_distance_m != revision.source_distance_m
    ):
        raise SegmentGeometryGateError(
            gate="write",
            violations=[{"code": "source_observation_changed"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    routing_candidate = (
        db.query(SegmentRoutingCandidate)
        .filter(SegmentRoutingCandidate.id == revision.routing_candidate_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if routing_candidate is None:
        raise SegmentGeometryGateError(
            gate="write",
            violations=[{"code": "routing_candidate_missing"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    try:
        validate_routing_candidate_record(
            routing_candidate,
            expected_segment_id=segment.id,
            require_ready=False,
        )
    except SegmentRoutingCandidateIntegrityError as exc:
        raise SegmentGeometryGateError(
            gate="write",
            violations=[{"code": "routing_candidate_changed"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        ) from exc
    if routing_candidate.status != "consumed":
        raise SegmentGeometryGateError(
            gate="write",
            violations=[{"code": "routing_candidate_not_consumed"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    if routing_candidate.geometry_hash != revision.candidate_geometry_hash:
        raise SegmentGeometryGateError(
            gate="write",
            violations=[{"code": "routing_candidate_geometry_changed"}],
            metrics={"validation_version": SEGMENT_GEOMETRY_GATE_VERSION},
        )
    activation_metrics = build_segment_geometry_gate_metrics(
        previous_wkt=current_wkt,
        current_distance_m=float(segment.distance or 0.0),
        current_start_lat=segment.start_lat,
        current_start_lon=segment.start_lon,
        current_end_lat=segment.end_lat,
        current_end_lon=segment.end_lon,
        prepared=activation_prepared,
        source_url=observation.source_url,
        source_distance_m=observation.observed_distance_m,
        integrity_gate="write",
    )
    if activation_metrics.source_segment_id != revision.source_segment_id:
        raise SegmentGeometryGateError(
            gate="write",
            violations=[{"code": "source_segment_identity_changed"}],
            metrics=activation_metrics.as_dict(),
        )
    enforce_segment_geometry_gate_metrics(activation_metrics)
    revision.validation_metrics_json = json.dumps(
        activation_metrics.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    # 再扫一次候选集，补上首轮计算后刚导入的活动。实时 matcher 会拿同一把锁，
    # 因此最终提交后不会再把旧线结果写回来。
    effort_results = dict(precomputed_efforts)
    for activity_id in candidate_activity_ids(
        db,
        segment_id=revision.segment_id,
        candidate_wkt=revision.candidate_reference_line_wkt,
    ):
        if activity_id not in effort_results:
            effort = match_activity_to_revision(db, activity_id, revision)
            if effort is not None:
                effort_results[activity_id] = effort

    existing_efforts = {
        effort.activity_id: effort
        for effort in db.query(SegmentEffort)
        .filter(SegmentEffort.segment_id == revision.segment_id)
        .all()
    }
    inserted = 0
    updated = 0
    for activity_id, candidate in effort_results.items():
        effort = existing_efforts.pop(activity_id, None)
        if effort is None:
            effort = SegmentEffort(segment_id=revision.segment_id, activity_id=activity_id)
            db.add(effort)
            inserted += 1
        else:
            updated += 1
        effort.user_id = candidate.user_id
        effort.elapsed_time = candidate.elapsed_time
        effort.avg_speed = candidate.avg_speed
        effort.avg_power = candidate.avg_power
        effort.start_index = candidate.start_index
        effort.end_index = candidate.end_index

    deleted = len(existing_efforts)
    for effort in existing_efforts.values():
        db.delete(effort)

    segment.reference_line = WKTElement(revision.candidate_reference_line_wkt, srid=4326)
    segment.distance = revision.distance
    segment.elevation_gain = revision.elevation_gain
    segment.elevation_loss = revision.elevation_loss
    segment.avg_gradient = revision.avg_gradient
    segment.elevation_profile = revision.elevation_profile
    segment.max_gradient = revision.max_gradient
    segment.difficulty = revision.difficulty
    segment.city = revision.city
    segment.start_lat = revision.start_lat
    segment.start_lon = revision.start_lon
    segment.end_lat = revision.end_lat
    segment.end_lon = revision.end_lon

    db.query(SegmentGeometryRevision).filter(
        SegmentGeometryRevision.segment_id == revision.segment_id,
        SegmentGeometryRevision.id != revision.id,
        SegmentGeometryRevision.status == "active",
    ).update({SegmentGeometryRevision.status: "superseded"}, synchronize_session=False)
    revision.status = "active"
    revision.activated_at = datetime.now(timezone.utc)
    revision.error_message = None
    db.flush()
    return ActivationSummary(
        segment_id=revision.segment_id,
        revision_id=revision.id,
        matched_efforts=len(effort_results),
        inserted_efforts=inserted,
        updated_efforts=updated,
        deleted_efforts=deleted,
    )


def mark_revision_failed(
    db: Session,
    revision_id: int,
    error_message: str,
    *,
    attempt_job_id: str,
) -> None:
    # 条件 UPDATE 会在等待并发激活事务后重新判断 status，避免另一个重复任务已把
    # 几何切成 active，本任务的迟到异常却再把审计状态覆盖成 failed。
    db.query(SegmentGeometryRevision).filter(
        SegmentGeometryRevision.id == revision_id,
        SegmentGeometryRevision.job_id == attempt_job_id,
        SegmentGeometryRevision.status.in_(("staged", "processing")),
    ).update(
        {
            SegmentGeometryRevision.status: "failed",
            SegmentGeometryRevision.error_message: error_message[:2000],
        },
        synchronize_session=False,
    )
    db.commit()
