"""两条经人工看图确认的太原赛段边界纠偏规则。

这里不做通用的“自动猜路线”。Strava 只提供原始有向折线，代码只执行两种已经
明确确认的机械操作：原线采用、删除一段首尾回到同一点的折返。任何来源赛段、
端点或折线结构变化都会让预检失败。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from app.segment._geo_utils import _haversine


@dataclass(frozen=True)
class BoundaryCorrectionSpec:
    segment_id: int
    segment_name: str
    source_segment_id: int
    source_name_fragment: str
    expected_source_distance_m: float
    expected_source_start: tuple[float, float]
    expected_source_end: tuple[float, float]
    operation: str


@dataclass(frozen=True)
class BoundaryCorrectionCandidate:
    spec: BoundaryCorrectionSpec
    source_name: str
    source_distance_m: float
    source_points: tuple[tuple[float, float], ...]
    points: tuple[tuple[float, float], ...]
    metrics: dict[str, Any]


BOUNDARY_CORRECTION_REVIEW_BASIS = "tim_map_review_2026_08_11"


CORRECTION_SPECS = {
    30: BoundaryCorrectionSpec(
        segment_id=30,
        segment_name="南内环桥-中北福源阁-南内环桥",
        source_segment_id=38785617,
        source_name_fragment="南内环桥",
        expected_source_distance_m=43690.0,
        expected_source_start=(37.83847, 112.52983),
        expected_source_end=(37.83853, 112.53472),
        operation="remove_northern_out_and_back",
    ),
    39: BoundaryCorrectionSpec(
        segment_id=39,
        segment_name="潇河南岸单程",
        source_segment_id=37160997,
        source_name_fragment="潇河南岸",
        expected_source_distance_m=16716.5,
        expected_source_start=(37.65317, 112.75826),
        expected_source_end=(37.60109, 112.59692),
        operation="use_source_polyline",
    ),
}


def decode_strava_polyline(value: str) -> tuple[tuple[float, float], ...]:
    """解码 Strava/Google encoded polyline，返回 ``(lat, lon)``。"""
    if not isinstance(value, str) or not value:
        raise ValueError("Strava 赛段缺少完整 polyline")
    points: list[tuple[float, float]] = []
    index = latitude = longitude = 0
    try:
        while index < len(value):
            deltas = []
            for _ in range(2):
                result = shift = 0
                while True:
                    byte = ord(value[index]) - 63
                    index += 1
                    result |= (byte & 0x1F) << shift
                    shift += 5
                    if byte < 0x20:
                        break
                deltas.append(~(result >> 1) if result & 1 else result >> 1)
            latitude += deltas[0]
            longitude += deltas[1]
            points.append((latitude / 1e5, longitude / 1e5))
    except (IndexError, TypeError) as exc:
        raise ValueError("Strava polyline 编码不完整") from exc
    if len(points) < 2:
        raise ValueError("Strava polyline 点数不足")
    return tuple(points)


def polyline_distance_m(points: tuple[tuple[float, float], ...]) -> float:
    return sum(_haversine(*left, *right) for left, right in zip(points, points[1:]))


def build_boundary_correction_candidate(
    segment_id: int,
    detail: dict[str, Any],
) -> BoundaryCorrectionCandidate:
    """把 Strava 详情机械转换为已确认的候选线，并给出可读预检指标。"""
    spec = CORRECTION_SPECS.get(segment_id)
    if spec is None:
        raise ValueError(f"没有 segment {segment_id} 的人工纠偏规则")
    if int(detail.get("id") or 0) != spec.source_segment_id:
        raise ValueError(f"segment {segment_id} 的 Strava 来源 ID 不匹配")
    source_name = str(detail.get("name") or "").strip()
    if spec.source_name_fragment not in source_name:
        raise ValueError(f"segment {segment_id} 的 Strava 来源名称不匹配")
    try:
        source_distance_m = float(detail["distance"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"segment {segment_id} 的 Strava 距离无效") from exc
    if not math.isfinite(source_distance_m) or source_distance_m <= 0:
        raise ValueError(f"segment {segment_id} 的 Strava 距离无效")
    if abs(source_distance_m - spec.expected_source_distance_m) > 200.0:
        raise ValueError(f"segment {segment_id} 的 Strava 来源距离已变化")

    map_value = detail.get("map") or {}
    source_points = decode_strava_polyline(map_value.get("polyline"))
    _assert_near(source_points[0], spec.expected_source_start, 50.0, "来源起点")
    _assert_near(source_points[-1], spec.expected_source_end, 50.0, "来源终点")
    measured_source_distance_m = polyline_distance_m(source_points)
    if abs(measured_source_distance_m - source_distance_m) > max(200.0, source_distance_m * 0.02):
        raise ValueError(f"segment {segment_id} 的 Strava 折线与报告距离不一致")

    operation_metrics: dict[str, Any]
    if spec.operation == "use_source_polyline":
        points = source_points
        operation_metrics = {"operation": spec.operation}
    elif spec.operation == "remove_northern_out_and_back":
        start_index = 352
        end_index = 428
        if len(source_points) <= end_index:
            raise ValueError("南内环 Strava 折线点数已变化，不能按旧边界裁剪")
        northern_index = max(range(len(source_points)), key=lambda item: source_points[item][0])
        if not start_index < northern_index < end_index:
            raise ValueError("南内环最北折返不再位于已确认的索引范围")
        join_gap_m = _haversine(*source_points[start_index], *source_points[end_index])
        removed_path_m = polyline_distance_m(source_points[start_index : end_index + 1])
        if join_gap_m > 15.0 or removed_path_m < 2000.0:
            raise ValueError("南内环最北折返的回接结构已变化")
        points = source_points[: start_index + 1] + source_points[end_index:]
        operation_metrics = {
            "operation": spec.operation,
            "removed_start_index": start_index,
            "removed_end_index": end_index,
            "removed_path_m": round(removed_path_m, 1),
            "join_gap_m": round(join_gap_m, 1),
        }
    else:
        raise ValueError(f"不支持的纠偏操作：{spec.operation}")

    candidate_distance_m = polyline_distance_m(points)
    metrics = {
        "review_basis": BOUNDARY_CORRECTION_REVIEW_BASIS,
        "segment_id": spec.segment_id,
        "source_segment_id": str(spec.source_segment_id),
        "source_name": source_name,
        "source_point_count": len(source_points),
        "source_measured_distance_m": round(measured_source_distance_m, 1),
        "candidate_point_count": len(points),
        "candidate_distance_m": round(candidate_distance_m, 1),
        "candidate_start": [points[0][0], points[0][1]],
        "candidate_end": [points[-1][0], points[-1][1]],
        **operation_metrics,
    }
    return BoundaryCorrectionCandidate(
        spec=spec,
        source_name=source_name,
        source_distance_m=source_distance_m,
        source_points=source_points,
        points=points,
        metrics=metrics,
    )


def validate_boundary_correction_metrics(
    metrics: object,
    *,
    segment_id: int,
    source_segment_id: str,
    candidate_points: list[tuple[float, float]],
    candidate_distance_m: float,
) -> dict[str, Any]:
    """在暂存和最终激活时重新核对纠偏证据与候选线本体。"""
    if not isinstance(metrics, dict):
        raise ValueError("人工边界纠偏指标必须是对象")
    if metrics.get("review_basis") != BOUNDARY_CORRECTION_REVIEW_BASIS:
        raise ValueError("人工边界纠偏缺少本轮看图决定")
    if metrics.get("segment_id") != segment_id:
        raise ValueError("人工边界纠偏 segment_id 不一致")
    if metrics.get("source_segment_id") != source_segment_id:
        raise ValueError("人工边界纠偏来源 ID 不一致")
    if metrics.get("operation") not in {
        "use_source_polyline",
        "remove_northern_out_and_back",
    }:
        raise ValueError("人工边界纠偏操作无效")
    if metrics.get("candidate_point_count") != len(candidate_points):
        raise ValueError("人工边界纠偏点数与候选线不一致")
    try:
        recorded_distance_m = float(metrics["candidate_distance_m"])
        recorded_start = tuple(float(value) for value in metrics["candidate_start"])
        recorded_end = tuple(float(value) for value in metrics["candidate_end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("人工边界纠偏候选指标无效") from exc
    if abs(recorded_distance_m - candidate_distance_m) > 1.0:
        raise ValueError("人工边界纠偏距离与候选线不一致")
    _assert_near(recorded_start, candidate_points[0], 1.0, "候选起点")
    _assert_near(recorded_end, candidate_points[-1], 1.0, "候选终点")
    return metrics


def _assert_near(
    actual: tuple[float, float],
    expected: tuple[float, float],
    tolerance_m: float,
    label: str,
) -> None:
    if len(actual) != 2 or len(expected) != 2:
        raise ValueError(f"{label}格式无效")
    distance_m = _haversine(*actual, *expected)
    if not math.isfinite(distance_m) or distance_m > tolerance_m:
        raise ValueError(f"{label}偏移 {distance_m:.1f}m，超过 {tolerance_m:.1f}m")
