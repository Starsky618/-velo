"""VELO 骑前爬坡规划内核。

这不是 Garmin ClimbPro 的复刻：Garmin 公开了识别门槛和分类公式，但没有公开
完整分段算法。VELO 在同一组公开门槛上，增加确定性的多坡分段、坡型、持续坡度
和骑手功率估时。所有输出都带算法版本与数据置信度，不能冒充实测气压计真值。

输入必须是沿当前 traversal 方向、距离严格递增的成品海拔剖面。反骑一条路线时应
先反转几何/海拔并重新调用本模块；不能把正爬的分类直接复制到反向 traversal。
"""

from __future__ import annotations

from bisect import bisect_left
import hashlib
import json
import math
from typing import Mapping, Sequence


CLIMB_PLAN_ALGORITHM_VERSION = "velo_climb_plan_v1"
CLIMB_CLASSIFICATION_SYSTEM = "garmin_public_2026"
CLIMB_CATEGORY_VERSION = "2026-08-14"
CLIMB_SHAPE_RULE_VERSION = "velo_shape_v1_2026-08-14"

MIN_CLIMB_LENGTH_M = 500.0
MIN_CLIMB_AVERAGE_GRADE_PCT = 3.0
MIN_CLIMB_SCORE = 1_500.0
TURNING_PROMINENCE_M = 15.0
HARD_SPLIT_MINIMUM_SPAN_M = 500.0
HARD_SPLIT_DESCENT_M = 20.0
INTERNAL_GRADE_STEP_M = 100.0
MAX_CLIMB_PROFILE_POINTS = 60

GRADE_BANDS = (
    ("descent", -math.inf, 0.0),
    ("flat", 0.0, 1.0),
    ("relief", 1.0, 3.0),
    ("gentle", 3.0, 6.0),
    ("steep", 6.0, 9.0),
    ("very_steep", 9.0, 12.0),
    ("wall", 12.0, math.inf),
)

SHAPE_LABELS = {
    "long_gentle": "长缓坡",
    "long_sustained": "长持续坡",
    "steady": "稳定坡",
    "short_wall": "短陡墙",
    "early_wall": "前段墙",
    "late_wall": "末段墙",
    "staircase": "阶梯坡",
    "mixed": "混合坡",
}

CATEGORY_RANK = {
    "uncategorized": 0,
    "4": 1,
    "3": 2,
    "2": 3,
    "1": 4,
    "HC": 5,
}


class ClimbPlanInputError(ValueError):
    """海拔剖面不满足确定性爬坡分析合同。"""


def classify_climb_score(score: float) -> str:
    """按 Garmin 公开的严格大于阈值返回 HC / 1..4 / uncategorized。"""
    value = float(score)
    if not math.isfinite(value) or value < 0:
        raise ClimbPlanInputError("climb score must be a finite non-negative number")
    if value > 80_000:
        return "HC"
    if value > 64_000:
        return "1"
    if value > 32_000:
        return "2"
    if value > 16_000:
        return "3"
    if value > 8_000:
        return "4"
    return "uncategorized"


def build_climb_plan(
    distances_m: Sequence[float],
    elevations_m: Sequence[float],
    *,
    source_method: str,
    horizontal_resolution_m: float | None,
    traversal_direction: str = "geometry_order",
    smoothing_variants: Mapping[str, Sequence[float]] | None = None,
    residual_mad_m: float | None = None,
) -> dict:
    """从当前 traversal 的成品海拔剖面生成非重叠、有顺序的爬坡组成。"""
    distances, elevations = _normalize_profile(distances_m, elevations_m)
    sampling_intervals = [
        right - left for left, right in zip(distances, distances[1:])
    ]
    residual_mad = _normalize_residual_mad(residual_mad_m)
    turning_prominence_m = max(TURNING_PROMINENCE_M, 3.0 * residual_mad)
    hard_split_descent_m = max(HARD_SPLIT_DESCENT_M, 3.0 * residual_mad)
    source_confidence = _source_confidence(source_method, horizontal_resolution_m)
    qualifying = _detect_climb_intervals(
        distances,
        elevations,
        turning_prominence_m=turning_prominence_m,
        hard_split_descent_m=hard_split_descent_m,
    )
    variant_profiles = {
        str(name): _normalize_variant(values, expected_count=len(distances))
        for name, values in (smoothing_variants or {}).items()
    }
    variant_intervals = {
        name: _detect_climb_intervals(
            distances,
            values,
            turning_prominence_m=turning_prominence_m,
            hard_split_descent_m=hard_split_descent_m,
        )
        for name, values in variant_profiles.items()
    }

    climbs = [
        _build_climb_occurrence(
            order=index + 1,
            start_index=start,
            end_index=end,
            distances=distances,
            elevations=elevations,
            variant_intervals=variant_intervals,
            variant_profiles=variant_profiles,
            main_interval_count=len(qualifying),
        )
        for index, (start, end) in enumerate(qualifying)
    ]
    if source_confidence != "high":
        for climb in climbs:
            climb["category_status"] = "candidate"
    for index, climb in enumerate(climbs):
        next_start = (
            climbs[index + 1]["start_distance_m"]
            if index + 1 < len(climbs)
            else distances[-1]
        )
        climb["recovery_after_m"] = round(
            max(0.0, next_start - climb["end_distance_m"]),
            1,
        )
        previous_end = (
            climbs[index - 1]["end_distance_m"]
            if index > 0
            else distances[0]
        )
        cumulative_gain, _cumulative_loss = _gain_loss_between(
            distances[0],
            climb["start_distance_m"],
            distances,
            elevations,
        )
        _gap_gain, gap_loss = _gain_loss_between(
            previous_end,
            climb["start_distance_m"],
            distances,
            elevations,
        )
        climb["cumulative_distance_before_m"] = round(
            climb["start_distance_m"] - distances[0],
            1,
        )
        climb["cumulative_ascent_before_m"] = round(cumulative_gain, 1)
        climb["distance_from_previous_climb_m"] = round(
            climb["start_distance_m"] - previous_end,
            1,
        )
        climb["descent_from_previous_climb_m"] = round(gap_loss, 1)

    categorized = [climb for climb in climbs if climb["category"] != "uncategorized"]
    hardest = max(
        climbs,
        key=lambda item: (CATEGORY_RANK[item["category"]], item["score"]),
        default=None,
    )
    counts = {category: 0 for category in ("HC", "1", "2", "3", "4", "uncategorized")}
    for climb in climbs:
        counts[climb["category"]] += 1

    return {
        "algorithm_version": CLIMB_PLAN_ALGORITHM_VERSION,
        "classification_system": CLIMB_CLASSIFICATION_SYSTEM,
        "traversal_direction": traversal_direction,
        "source": {
            "method": str(source_method),
            "horizontal_resolution_m": (
                round(float(horizontal_resolution_m), 1)
                if horizontal_resolution_m is not None
                else None
            ),
            "confidence": source_confidence,
            "sustained_grade_windows_m": [500, 1000],
            "profile_hash": _profile_hash(distances, elevations),
            "residual_mad_m": round(residual_mad, 2),
            "sampling_interval_m": round(
                float(_percentile(sampling_intervals, 0.5)),
                1,
            ),
            "maximum_sampling_interval_m": round(max(sampling_intervals), 1),
            "missing_point_count": 0,
            "duplicate_distance_count": 0,
            "quality_checks": {
                "finite_values": True,
                "strictly_increasing_distance": True,
                "profile_complete_for_route": True,
            },
        },
        "parameters": {
            "minimum_climb_length_m": MIN_CLIMB_LENGTH_M,
            "minimum_average_grade_pct": MIN_CLIMB_AVERAGE_GRADE_PCT,
            "minimum_climb_score": MIN_CLIMB_SCORE,
            "turning_prominence_m": round(turning_prominence_m, 2),
            "hard_split_minimum_span_m": HARD_SPLIT_MINIMUM_SPAN_M,
            "hard_split_descent_m": round(hard_split_descent_m, 2),
            "main_smoothing_m": 100,
            "stability_smoothing_variants_m": [80, 150],
        },
        "route_distance_m": round(distances[-1] - distances[0], 1),
        "climbs": climbs,
        "partition_alternatives": _partition_alternatives(
            distances,
            variant_profiles,
            variant_intervals,
        ),
        "composition": {
            "climb_count": len(climbs),
            "categorized_climb_count": len(categorized),
            "category_counts": counts,
            "total_climbing_distance_m": round(sum(item["length_m"] for item in climbs), 1),
            "total_climb_gain_m": round(sum(item["elevation_gain_m"] for item in climbs), 1),
            "categorized_ascent_m": round(
                sum(
                    item["elevation_gain_m"]
                    for item in climbs
                    if item["category"] != "uncategorized"
                ),
                1,
            ),
            "uncategorized_ascent_m": round(
                sum(
                    item["elevation_gain_m"]
                    for item in climbs
                    if item["category"] == "uncategorized"
                ),
                1,
            ),
            "unobserved_profile_distance_m": 0.0,
            "highest_category": hardest["category"] if hardest else None,
            "hardest_climb_order": hardest["order"] if hardest else None,
            "sequence_label": _sequence_label(climbs),
            "finish_type": _finish_type(climbs, distances, elevations),
            "boundary_status": _route_boundary_status(
                climbs,
                variants_supplied=bool(variant_profiles),
            ),
        },
    }


def build_rider_climb_plan(
    climb_plan: Mapping,
    *,
    ftp_w: float | None,
    rider_mass_kg: float | None,
    bike_type: str | None = None,
    power_curve_w: Mapping[str | int, float] | None = None,
) -> dict:
    """为当前骑手生成三档骑前爬坡策略；缺输入时返回可行动的缺口而非假估时。"""
    missing = []
    if ftp_w is None or not math.isfinite(float(ftp_w)) or float(ftp_w) <= 0:
        missing.append("ftp")
    if rider_mass_kg is None or not math.isfinite(float(rider_mass_kg)) or float(rider_mass_kg) <= 0:
        missing.append("weight")
    if missing:
        return {
            "status": "needs_profile",
            "missing_fields": missing,
            "confidence": "unavailable",
            "basis": "route_only",
            "physiology_model": "unavailable",
            "ftp_w_per_kg": None,
            "power_curve_coverage": {
                "minimum_duration_s": None,
                "maximum_duration_s": None,
                "evaluated_climb_scenarios": 0,
                "covered_climb_scenarios": 0,
                "coverage_fraction": 0.0,
            },
            "confidence_dimensions": {
                "profile_quality": str((climb_plan.get("source") or {}).get("confidence") or "unknown"),
                "boundary_quality": str((climb_plan.get("composition") or {}).get("boundary_status") or "unknown"),
                "physiology_quality": "unavailable",
                "environment_quality": "unavailable",
            },
            "multi_climb_context": {
                "status": "unavailable_missing_profile",
                "ordered_climb_count": len(climb_plan.get("climbs") or []),
                "recovery_credit_modeled": False,
                "cp_wprime_used": False,
            },
            "assumptions": [],
            "scenarios": [],
            "climbs": [],
        }

    ftp = float(ftp_w)
    rider_mass = float(rider_mass_kg)
    bike_mass = _bike_mass_assumption(bike_type)
    curve = _normalize_power_curve(power_curve_w)
    curve_attempts = 0
    curve_covered = 0
    scenarios = []
    scenario_specs = (
        ("finish", "稳稳骑完", 0.78, 0.88),
        ("steady", "持续推进", 0.88, 0.94),
        ("hard", "接近全力", 0.98, 1.00),
    )
    physics_scenarios = {
        "low": {
            "bike_mass_kg": max(5.0, bike_mass - 1.0),
            "rolling_coefficient": 0.003,
            "air_density": 1.10,
            "drag_area": 0.28,
            "headwind_mps": 0.0,
        },
        "base": {
            "bike_mass_kg": bike_mass,
            "rolling_coefficient": 0.004,
            "air_density": 1.18,
            "drag_area": 0.32,
            "headwind_mps": 0.0,
        },
        "high": {
            "bike_mass_kg": bike_mass + 2.0,
            "rolling_coefficient": 0.006,
            "air_density": 1.25,
            "drag_area": 0.38,
            "headwind_mps": 2.0,
        },
    }

    climbs = list(climb_plan.get("climbs") or [])
    for key, label, ftp_fraction, curve_fraction in scenario_specs:
        nominal_target = ftp * ftp_fraction
        total_seconds = {key: 0.0 for key in physics_scenarios}
        per_climb = []
        cumulative_climbing_seconds = 0.0
        for climb in climbs:
            nominal_duration = _estimate_climb_seconds(
                climb,
                target_power_w=nominal_target,
                rider_mass_kg=rider_mass,
                **physics_scenarios["base"],
            )
            if curve:
                curve_attempts += 1
                target_for_climb, duration, effective_duration, covered = (
                    _solve_pdc_limited_target(
                        climb,
                        nominal_target_w=nominal_target,
                        curve_fraction=curve_fraction,
                        power_curve=curve,
                        cumulative_climbing_seconds=cumulative_climbing_seconds,
                        rider_mass_kg=rider_mass,
                        base_physics=physics_scenarios["base"],
                    )
                )
                if covered:
                    curve_covered += 1
            else:
                target_for_climb = nominal_target
                duration = nominal_duration
                effective_duration = duration + cumulative_climbing_seconds
            durations = {
                physics_key: _estimate_climb_seconds(
                    climb,
                    target_power_w=target_for_climb,
                    rider_mass_kg=rider_mass,
                    **physics,
                )
                for physics_key, physics in physics_scenarios.items()
            }
            for physics_key, seconds in durations.items():
                total_seconds[physics_key] += seconds
            per_climb.append(
                {
                    "order": int(climb["order"]),
                    "target_power_w": round(target_for_climb),
                    "target_w_per_kg": round(target_for_climb / rider_mass, 2),
                    "estimated_time_min": round(duration / 60.0, 1),
                    "estimated_time_range_min": [
                        round(durations["low"] / 60.0, 1),
                        round(durations["high"] / 60.0, 1),
                    ],
                    "cumulative_climbing_time_before_min": round(
                        cumulative_climbing_seconds / 60.0,
                        1,
                    ),
                    "pdc_effective_duration_min": round(
                        effective_duration / 60.0,
                        1,
                    ),
                    "recovery_credit_status": (
                        "not_modeled_without_cp_wprime"
                        if len(climbs) > 1
                        else "not_applicable_single_climb"
                    ),
                }
            )
            cumulative_climbing_seconds += duration
        target_values = [item["target_power_w"] for item in per_climb]
        target_low = min(target_values, default=round(nominal_target))
        target_high = max(target_values, default=round(nominal_target))
        scenarios.append(
            {
                "key": key,
                "label": label,
                "target_power_w": target_low,
                "target_w_per_kg": round(target_low / rider_mass, 2),
                "target_power_range_w": [target_low, target_high],
                "target_w_per_kg_range": [
                    round(target_low / rider_mass, 2),
                    round(target_high / rider_mass, 2),
                ],
                "estimated_climbing_time_min": round(total_seconds["base"] / 60.0, 1),
                "estimated_climbing_time_range_min": [
                    round(total_seconds["low"] / 60.0, 1),
                    round(total_seconds["high"] / 60.0, 1),
                ],
                "climbs": per_climb,
            }
        )

    coverage_fraction = curve_covered / curve_attempts if curve_attempts else 0.0
    uses_power_curve = curve_covered > 0
    physiology_quality = (
        "power_duration_curve"
        if coverage_fraction == 1.0
        else "partial_power_duration_curve"
        if uses_power_curve
        else "ftp_only"
    )
    return {
        "status": "estimated",
        "missing_fields": [],
        "confidence": "medium" if uses_power_curve else "low",
        "basis": "ftp_weight_power_curve" if uses_power_curve else "ftp_weight",
        "physiology_model": "pdc_only" if uses_power_curve else "ftp_only",
        "ftp_w_per_kg": round(ftp / rider_mass, 2),
        "power_curve_coverage": {
            "minimum_duration_s": round(curve[0][0]) if curve else None,
            "maximum_duration_s": round(curve[-1][0]) if curve else None,
            "evaluated_climb_scenarios": curve_attempts,
            "covered_climb_scenarios": curve_covered,
            "coverage_fraction": round(coverage_fraction, 3),
        },
        "confidence_dimensions": {
            "profile_quality": str((climb_plan.get("source") or {}).get("confidence") or "unknown"),
            "boundary_quality": str((climb_plan.get("composition") or {}).get("boundary_status") or "unknown"),
            "physiology_quality": physiology_quality,
            "environment_quality": "scenario_defaults",
        },
        "multi_climb_context": {
            "status": (
                "pdc_cumulative_duration_no_recovery_credit"
                if len(climbs) > 1 and uses_power_curve
                else "pending_without_cp_wprime"
                if len(climbs) > 1
                else "not_applicable_single_climb"
            ),
            "ordered_climb_count": len(climbs),
            "recovery_credit_modeled": False,
            "cp_wprime_used": False,
        },
        "assumptions": [
            f"{bike_mass:.0f}kg 整车与随身装备估值",
            "无风、干燥铺装、CdA 0.32、Crr 0.004",
            "耗时范围用轻装低滚阻到逆风高滚阻情景计算，不是统计置信区间",
            "功率曲线只约束其实际覆盖的预计耗时，超出区间退回 FTP 低置信度计划",
            "多坡 PDC 按累计爬坡时长保守限功；没有可信 CP/W′ 时不模拟坡间恢复",
            "只估已识别爬坡时间，不是整条路线到达时间",
        ],
        "scenarios": scenarios,
        "climbs": [
            {
                "order": int(climb["order"]),
                "category": climb["category"],
                "shape": climb["shape"],
                "shape_label": climb["shape_label"],
            }
            for climb in climbs
        ],
    }


def _normalize_profile(
    distances_m: Sequence[float], elevations_m: Sequence[float]
) -> tuple[list[float], list[float]]:
    if len(distances_m) != len(elevations_m) or len(distances_m) < 2:
        raise ClimbPlanInputError("climb profile requires matching distance/elevation arrays")
    distances = [float(value) for value in distances_m]
    elevations = [float(value) for value in elevations_m]
    if not all(math.isfinite(value) for value in distances + elevations):
        raise ClimbPlanInputError("climb profile values must be finite")
    if any(right <= left for left, right in zip(distances, distances[1:])):
        raise ClimbPlanInputError("climb profile distances must be strictly increasing")
    if distances[-1] - distances[0] <= 0:
        raise ClimbPlanInputError("climb profile distance must be positive")
    return distances, elevations


def _normalize_variant(values: Sequence[float], *, expected_count: int) -> list[float]:
    normalized = [float(value) for value in values]
    if len(normalized) != expected_count:
        raise ClimbPlanInputError("smoothing variant point count does not match profile")
    if not all(math.isfinite(value) for value in normalized):
        raise ClimbPlanInputError("smoothing variant values must be finite")
    return normalized


def _normalize_residual_mad(value: float | None) -> float:
    if value is None:
        return 0.0
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ClimbPlanInputError("residual MAD must be a finite non-negative number")
    return result


def _profile_hash(distances: Sequence[float], elevations: Sequence[float]) -> str:
    payload = [
        [round(float(distance), 3), round(float(elevation), 3)]
        for distance, elevation in zip(distances, elevations)
    ]
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _detect_climb_intervals(
    distances: Sequence[float],
    elevations: Sequence[float],
    *,
    turning_prominence_m: float,
    hard_split_descent_m: float,
) -> list[tuple[int, int]]:
    raw_events = _ascent_events(
        distances,
        elevations,
        turning_prominence_m=turning_prominence_m,
    )
    merged_events = _merge_ascent_events(
        raw_events,
        distances,
        elevations,
        hard_split_descent_m=hard_split_descent_m,
    )
    return [
        event
        for event in merged_events
        if _qualifies_as_climb(event[0], event[1], distances, elevations)
    ]


def _ascent_events(
    distances: Sequence[float],
    elevations: Sequence[float],
    *,
    turning_prominence_m: float,
) -> list[tuple[int, int]]:
    valley_index = 0
    peak_index = 0
    climbing = False
    events: list[tuple[int, int]] = []
    for index in range(1, len(elevations)):
        value = elevations[index]
        if not climbing:
            if value <= elevations[valley_index]:
                valley_index = index
                peak_index = index
            elif value - elevations[valley_index] >= turning_prominence_m:
                climbing = True
                peak_index = index
            continue
        if value >= elevations[peak_index]:
            peak_index = index
        elif elevations[peak_index] - value >= turning_prominence_m:
            if peak_index > valley_index:
                events.append((valley_index, peak_index))
            climbing = False
            valley_index = index
            peak_index = index
    if climbing and peak_index > valley_index:
        events.append((valley_index, peak_index))
    return events


def _merge_ascent_events(
    events: Sequence[tuple[int, int]],
    distances: Sequence[float],
    elevations: Sequence[float],
    *,
    hard_split_descent_m: float,
) -> list[tuple[int, int]]:
    if not events:
        return []
    merged: list[tuple[int, int]] = []
    current_start, current_end = events[0]
    for next_start, next_end in events[1:]:
        gap_m = distances[next_start] - distances[current_end]
        gap_descent_m = max(0.0, elevations[current_end] - elevations[next_start])
        combined_length = distances[next_end] - distances[current_start]
        combined_gain = elevations[next_end] - elevations[current_start]
        combined_grade = combined_gain / combined_length * 100.0 if combined_length > 0 else -math.inf
        hard_split = (
            gap_m >= HARD_SPLIT_MINIMUM_SPAN_M
            and gap_descent_m > hard_split_descent_m
        )
        should_merge = not hard_split and combined_grade >= MIN_CLIMB_AVERAGE_GRADE_PCT
        if should_merge:
            current_end = next_end
        else:
            merged.append((current_start, current_end))
            current_start, current_end = next_start, next_end
    merged.append((current_start, current_end))
    return merged


def _qualifies_as_climb(
    start: int,
    end: int,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> bool:
    length = distances[end] - distances[start]
    net_gain = elevations[end] - elevations[start]
    grade = net_gain / length * 100.0 if length > 0 else 0.0
    score = length * grade
    return (
        length >= MIN_CLIMB_LENGTH_M
        and grade >= MIN_CLIMB_AVERAGE_GRADE_PCT
        and score >= MIN_CLIMB_SCORE
    )


def _build_climb_occurrence(
    *,
    order: int,
    start_index: int,
    end_index: int,
    distances: Sequence[float],
    elevations: Sequence[float],
    variant_intervals: Mapping[str, Sequence[tuple[int, int]]],
    variant_profiles: Mapping[str, Sequence[float]],
    main_interval_count: int,
) -> dict:
    start_distance = distances[start_index]
    end_distance = distances[end_index]
    length = end_distance - start_distance
    net_gain = elevations[end_index] - elevations[start_index]
    average_grade = net_gain / length * 100.0
    score = length * average_grade
    gain, loss = _gain_loss(elevations[start_index : end_index + 1])
    grade_bands = _grade_band_distances(
        start_distance,
        end_distance,
        distances,
        elevations,
    )
    max_500_window = _max_sustained_window(
        start_distance, end_distance, 500.0, distances, elevations
    )
    max_1000_window = _max_sustained_window(
        start_distance, end_distance, 1000.0, distances, elevations
    )
    max_500 = max_500_window["grade_pct"] if max_500_window else None
    max_1000 = max_1000_window["grade_pct"] if max_1000_window else None
    rolling_stats_500 = _rolling_grade_stats(
        start_distance,
        end_distance,
        500.0,
        distances,
        elevations,
    )
    rolling_stats_1000 = _rolling_grade_stats(
        start_distance,
        end_distance,
        1000.0,
        distances,
        elevations,
    )
    child_sections = _child_sections(
        start_distance,
        end_distance,
        average_grade,
        distances,
        elevations,
    )
    shape_tags = _classify_shape_tags(
        start_distance=start_distance,
        end_distance=end_distance,
        average_grade=average_grade,
        grade_bands=grade_bands,
        distances=distances,
        elevations=elevations,
        max_500=max_500,
        max_500_position=(
            float(max_500_window["position_fraction"])
            if max_500_window is not None
            else None
        ),
        rolling_stats=rolling_stats_500,
        child_sections=child_sections,
        elevation_gain=gain,
        elevation_loss=loss,
    )
    primary_shape = shape_tags[0] if shape_tags else "mixed"
    stability = _boundary_and_category_stability(
        start_index=start_index,
        end_index=end_index,
        main_category=classify_climb_score(score),
        distances=distances,
        variant_intervals=variant_intervals,
        variant_profiles=variant_profiles,
        main_interval_count=main_interval_count,
    )
    return {
        "order": order,
        "start_distance_m": round(start_distance, 1),
        "end_distance_m": round(end_distance, 1),
        "length_m": round(length, 1),
        "start_elevation_m": round(elevations[start_index], 1),
        "summit_elevation_m": round(elevations[end_index], 1),
        "elevation_gain_m": round(gain, 1),
        "elevation_loss_m": round(loss, 1),
        "net_gain_m": round(net_gain, 1),
        "average_grade_pct": round(average_grade, 2),
        "score": round(score),
        "category": classify_climb_score(score),
        "category_system": CLIMB_CLASSIFICATION_SYSTEM,
        "category_version": CLIMB_CATEGORY_VERSION,
        "category_status": (
            "candidate"
            if stability["boundary_status"] != "stable"
            or stability["category_stability"] < 1.0
            else "classified"
        ),
        "shape": primary_shape,
        "shape_label": SHAPE_LABELS[primary_shape],
        "shape_tags": shape_tags,
        "shape_labels": [SHAPE_LABELS[item] for item in shape_tags],
        "shape_rule_version": CLIMB_SHAPE_RULE_VERSION,
        "max_sustained_grade_pct": {
            "500m": round(max_500, 1) if max_500 is not None else None,
            "1000m": round(max_1000, 1) if max_1000 is not None else None,
        },
        "max_sustained_grade_windows": {
            "500m": max_500_window,
            "1000m": max_1000_window,
        },
        "grade_band_distance_m": {
            key: round(value, 1) for key, value in grade_bands.items()
        },
        "grade_band_share": {
            key: round(value / length, 4) for key, value in grade_bands.items()
        },
        "rolling_grade_500m": rolling_stats_500,
        "rolling_grade_1000m": rolling_stats_1000,
        "child_sections": child_sections,
        **stability,
        "profile": _climb_profile(
            start_distance,
            end_distance,
            distances,
            elevations,
        ),
    }


def _gain_loss(values: Sequence[float]) -> tuple[float, float]:
    gain = 0.0
    loss = 0.0
    for left, right in zip(values, values[1:]):
        delta = right - left
        if delta > 0:
            gain += delta
        elif delta < 0:
            loss -= delta
    return gain, loss


def _gain_loss_between(
    start_distance: float,
    end_distance: float,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> tuple[float, float]:
    if end_distance <= start_distance:
        return 0.0, 0.0
    values = [_interpolate(start_distance, distances, elevations)]
    values.extend(
        elevation
        for distance, elevation in zip(distances, elevations)
        if start_distance < distance < end_distance
    )
    values.append(_interpolate(end_distance, distances, elevations))
    return _gain_loss(values)


def _interpolate(
    target: float,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> float:
    if target <= distances[0]:
        return elevations[0]
    if target >= distances[-1]:
        return elevations[-1]
    right = bisect_left(distances, target)
    if distances[right] == target:
        return elevations[right]
    left = right - 1
    span = distances[right] - distances[left]
    ratio = (target - distances[left]) / span
    return elevations[left] + (elevations[right] - elevations[left]) * ratio


def _max_sustained_window(
    start_distance: float,
    end_distance: float,
    window_m: float,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> dict[str, float] | None:
    if end_distance - start_distance < window_m:
        return None
    step = min(100.0, window_m / 5.0)
    best_grade = -math.inf
    best_start = start_distance
    cursor = start_distance
    targets = []
    while cursor + window_m <= end_distance + 1e-6:
        targets.append(cursor)
        cursor += step
    targets.append(end_distance - window_m)
    for cursor in sorted(set(round(value, 6) for value in targets)):
        left = _interpolate(cursor, distances, elevations)
        right = _interpolate(cursor + window_m, distances, elevations)
        grade = (right - left) / window_m * 100.0
        if grade > best_grade:
            best_grade = grade
            best_start = cursor
    if best_grade == -math.inf:
        return None
    return {
        "grade_pct": round(best_grade, 1),
        "start_distance_m": round(best_start, 1),
        "end_distance_m": round(best_start + window_m, 1),
        "position_fraction": round(
            (best_start + window_m / 2.0 - start_distance)
            / max(end_distance - start_distance, 1.0),
            3,
        ),
    }


def _grade_band_distances(
    start_distance: float,
    end_distance: float,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> dict[str, float]:
    totals = {name: 0.0 for name, _lower, _upper in GRADE_BANDS}
    cursor = start_distance
    while cursor < end_distance - 1e-6:
        right = min(end_distance, cursor + INTERNAL_GRADE_STEP_M)
        grade = (
            _interpolate(right, distances, elevations)
            - _interpolate(cursor, distances, elevations)
        ) / (right - cursor) * 100.0
        for name, lower, upper in GRADE_BANDS:
            if lower <= grade < upper:
                totals[name] += right - cursor
                break
        cursor = right
    return totals


def _classify_shape_tags(
    *,
    start_distance: float,
    end_distance: float,
    average_grade: float,
    grade_bands: Mapping[str, float],
    distances: Sequence[float],
    elevations: Sequence[float],
    max_500: float | None,
    max_500_position: float | None,
    rolling_stats: Mapping[str, float | None],
    child_sections: Sequence[Mapping],
    elevation_gain: float,
    elevation_loss: float,
) -> list[str]:
    length = end_distance - start_distance
    third = length / 3.0
    first_grade = (
        _interpolate(start_distance + third, distances, elevations)
        - _interpolate(start_distance, distances, elevations)
    ) / third * 100.0
    last_grade = (
        _interpolate(end_distance, distances, elevations)
        - _interpolate(end_distance - third, distances, elevations)
    ) / third * 100.0
    spread = float(rolling_stats.get("p90_p10") or 0.0)
    recovery_count = sum(
        1
        for item in child_sections
        if item["section_role"] in {"recovery", "descent_inside_climb"}
    )
    hardest_position = max_500_position
    tags: list[str] = []

    if (
        hardest_position is not None
        and hardest_position >= 0.75
        and max_500 is not None
        and max_500 >= average_grade + 4.0
    ) or (
        last_grade >= max(8.0, average_grade + 4.0)
        and last_grade >= first_grade + 4.0
    ):
        tags.append("late_wall")
    if (
        hardest_position is not None
        and hardest_position <= 0.25
        and max_500 is not None
        and max_500 >= average_grade + 4.0
    ) or (
        first_grade >= max(8.0, average_grade + 4.0)
        and first_grade >= last_grade + 4.0
    ):
        tags.append("early_wall")
    if length <= 4_000 and max_500 is not None and max_500 >= 10.0:
        tags.append("short_wall")
    if recovery_count >= 2:
        tags.append("staircase")
    if length >= 8_000 and 3.0 <= average_grade <= 6.0 and (rolling_stats.get("p90") or 0) < 8.0:
        tags.append("long_gentle")
    elif length >= 8_000:
        tags.append("long_sustained")
    if spread <= 3.0 and elevation_loss / max(elevation_gain, 1.0) < 0.05:
        tags.append("steady")
    if not tags:
        tags.append("mixed")
    return tags

def _rolling_grade_samples(
    start_distance: float,
    end_distance: float,
    window_m: float,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> list[tuple[float, float]]:
    if end_distance - start_distance < window_m:
        return []
    starts = []
    cursor = start_distance
    while cursor + window_m <= end_distance + 1e-6:
        starts.append(cursor)
        cursor += min(100.0, window_m / 5.0)
    starts.append(end_distance - window_m)
    result = []
    for start in sorted(set(round(value, 6) for value in starts)):
        grade = (
            _interpolate(start + window_m, distances, elevations)
            - _interpolate(start, distances, elevations)
        ) / window_m * 100.0
        result.append((start, grade))
    return result


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * percentile
    left = int(math.floor(position))
    right = int(math.ceil(position))
    if left == right:
        return ordered[left]
    ratio = position - left
    return ordered[left] + (ordered[right] - ordered[left]) * ratio


def _rolling_grade_stats(
    start_distance: float,
    end_distance: float,
    window_m: float,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> dict[str, float | None]:
    samples = _rolling_grade_samples(
        start_distance, end_distance, window_m, distances, elevations
    )
    grades = [grade for _start, grade in samples]
    if not grades:
        return {"p10": None, "p50": None, "p90": None, "iqr": None, "p90_p10": None}
    p10 = _percentile(grades, 0.10)
    p25 = _percentile(grades, 0.25)
    p50 = _percentile(grades, 0.50)
    p75 = _percentile(grades, 0.75)
    p90 = _percentile(grades, 0.90)
    return {
        "p10": round(float(p10), 1),
        "p50": round(float(p50), 1),
        "p90": round(float(p90), 1),
        "iqr": round(float(p75 - p25), 1),
        "p90_p10": round(float(p90 - p10), 1),
    }


def _child_sections(
    start_distance: float,
    end_distance: float,
    average_grade: float,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> list[dict]:
    sections: list[dict] = []
    length = end_distance - start_distance
    samples = _rolling_grade_samples(
        start_distance, end_distance, 500.0, distances, elevations
    )
    ramp_threshold = max(10.0, average_grade + 4.0)
    selected: list[tuple[float, float]] = []
    for ramp_start, grade in sorted(samples, key=lambda item: item[1], reverse=True):
        ramp_end = ramp_start + 500.0
        if grade < ramp_threshold:
            break
        if any(min(ramp_end, end) - max(ramp_start, start) > 0 for start, end in selected):
            continue
        selected.append((ramp_start, ramp_end))
        ramp_gain, ramp_loss = _gain_loss_between(
            ramp_start,
            ramp_end,
            distances,
            elevations,
        )
        sections.append(
            {
                "section_role": "ramp",
                "start_distance_m": round(ramp_start, 1),
                "end_distance_m": round(ramp_end, 1),
                "length_m": 500.0,
                "average_grade_pct": round(grade, 1),
                "elevation_gain_m": round(ramp_gain, 1),
                "elevation_loss_m": round(ramp_loss, 1),
                "rolling_grade_500m": round(grade, 1),
                "rolling_grade_1000m": _grade_around_section(
                    ramp_start,
                    ramp_end,
                    parent_start=start_distance,
                    parent_end=end_distance,
                    window_m=1_000.0,
                    distances=distances,
                    elevations=elevations,
                ),
                "position_fraction": round(
                    (ramp_start + 250.0 - start_distance) / max(length, 1.0),
                    3,
                ),
            }
        )
        if len(selected) >= 3:
            break

    recovery_start = None
    cursor = start_distance
    while cursor < end_distance - 1e-6:
        right = min(end_distance, cursor + INTERNAL_GRADE_STEP_M)
        grade = (
            _interpolate(right, distances, elevations)
            - _interpolate(cursor, distances, elevations)
        ) / (right - cursor) * 100.0
        if grade < 1.0 and recovery_start is None:
            recovery_start = cursor
        elif grade >= 1.0 and recovery_start is not None:
            if cursor - recovery_start >= INTERNAL_GRADE_STEP_M:
                sections.append(
                    _recovery_section(
                        recovery_start,
                        cursor,
                        start_distance,
                        length,
                        distances,
                        elevations,
                    )
                )
            recovery_start = None
        cursor = right
    if recovery_start is not None and end_distance - recovery_start >= INTERNAL_GRADE_STEP_M:
        sections.append(
            _recovery_section(
                recovery_start,
                end_distance,
                start_distance,
                length,
                distances,
                elevations,
            )
        )
    return sorted(sections, key=lambda item: (item["start_distance_m"], item["section_role"]))


def _recovery_section(
    start: float,
    end: float,
    climb_start: float,
    climb_length: float,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> dict:
    net_gain = _interpolate(end, distances, elevations) - _interpolate(start, distances, elevations)
    elevation_gain, elevation_loss = _gain_loss_between(
        start,
        end,
        distances,
        elevations,
    )
    return {
        "section_role": "descent_inside_climb" if net_gain < 0 else "recovery",
        "start_distance_m": round(start, 1),
        "end_distance_m": round(end, 1),
        "length_m": round(end - start, 1),
        "average_grade_pct": round(net_gain / (end - start) * 100.0, 1),
        "elevation_gain_m": round(elevation_gain, 1),
        "elevation_loss_m": round(elevation_loss, 1),
        "rolling_grade_500m": _grade_around_section(
            start,
            end,
            parent_start=climb_start,
            parent_end=climb_start + climb_length,
            window_m=500.0,
            distances=distances,
            elevations=elevations,
        ),
        "rolling_grade_1000m": _grade_around_section(
            start,
            end,
            parent_start=climb_start,
            parent_end=climb_start + climb_length,
            window_m=1_000.0,
            distances=distances,
            elevations=elevations,
        ),
        "position_fraction": round((start + end - 2 * climb_start) / (2 * climb_length), 3),
    }


def _grade_around_section(
    start: float,
    end: float,
    *,
    parent_start: float,
    parent_end: float,
    window_m: float,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> float | None:
    if parent_end - parent_start < window_m:
        return None
    center = (start + end) / 2.0
    window_start = min(
        max(center - window_m / 2.0, parent_start),
        parent_end - window_m,
    )
    grade = (
        _interpolate(window_start + window_m, distances, elevations)
        - _interpolate(window_start, distances, elevations)
    ) / window_m * 100.0
    return round(grade, 1)


def _boundary_and_category_stability(
    *,
    start_index: int,
    end_index: int,
    main_category: str,
    distances: Sequence[float],
    variant_intervals: Mapping[str, Sequence[tuple[int, int]]],
    variant_profiles: Mapping[str, Sequence[float]],
    main_interval_count: int,
) -> dict:
    if not variant_intervals:
        return {
            "boundary_status": "not_assessed",
            "boundary_stability": None,
            "boundary_max_drift_m": None,
            "category_stability": 1.0,
        }
    main_start = distances[start_index]
    main_end = distances[end_index]
    ious = []
    drifts = []
    categories = []
    partition_changed = False
    for name, intervals in variant_intervals.items():
        if not intervals:
            partition_changed = True
            continue
        if len(intervals) != main_interval_count:
            partition_changed = True
        best = max(
            intervals,
            key=lambda interval: _interval_iou(
                main_start,
                main_end,
                distances[interval[0]],
                distances[interval[1]],
            ),
        )
        variant_start = distances[best[0]]
        variant_end = distances[best[1]]
        iou = _interval_iou(main_start, main_end, variant_start, variant_end)
        if iou <= 0:
            partition_changed = True
            continue
        ious.append(iou)
        drifts.append(max(abs(main_start - variant_start), abs(main_end - variant_end)))
        length = variant_end - variant_start
        variant_elevations = variant_profiles[name]
        gain = variant_elevations[best[1]] - variant_elevations[best[0]]
        score = 100.0 * gain if length > 0 else 0.0
        categories.append(classify_climb_score(max(0.0, score)))
    boundary_stability = _percentile(ious, 0.5)
    category_stability = (
        sum(1 for category in categories if category == main_category) / len(categories)
        if categories
        else 0.0
    )
    ambiguous = (
        partition_changed
        or boundary_stability is None
        or boundary_stability < 0.8
        or category_stability < 1.0
    )
    return {
        "boundary_status": "ambiguous" if ambiguous else "stable",
        "boundary_stability": (
            round(float(boundary_stability), 3) if boundary_stability is not None else None
        ),
        "boundary_max_drift_m": round(max(drifts), 1) if drifts else None,
        "category_stability": round(category_stability, 3),
    }


def _partition_alternatives(
    distances: Sequence[float],
    variant_profiles: Mapping[str, Sequence[float]],
    variant_intervals: Mapping[str, Sequence[tuple[int, int]]],
) -> dict[str, list[dict]]:
    alternatives: dict[str, list[dict]] = {}
    for name, intervals in variant_intervals.items():
        profile = variant_profiles[name]
        alternatives[name] = []
        for start, end in intervals:
            length = distances[end] - distances[start]
            net_gain = profile[end] - profile[start]
            average_grade = net_gain / length * 100.0
            score = length * average_grade
            alternatives[name].append(
                {
                    "start_distance_m": round(distances[start], 1),
                    "end_distance_m": round(distances[end], 1),
                    "length_m": round(length, 1),
                    "net_gain_m": round(net_gain, 1),
                    "average_grade_pct": round(average_grade, 2),
                    "score": round(score),
                    "category": classify_climb_score(score),
                }
            )
    return alternatives


def _interval_iou(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    intersection = max(0.0, min(left_end, right_end) - max(left_start, right_start))
    union = max(left_end, right_end) - min(left_start, right_start)
    return intersection / union if union > 0 else 0.0


def _climb_profile(
    start_distance: float,
    end_distance: float,
    distances: Sequence[float],
    elevations: Sequence[float],
) -> list[list[float]]:
    length = end_distance - start_distance
    point_count = min(
        MAX_CLIMB_PROFILE_POINTS,
        max(2, int(math.ceil(length / 100.0)) + 1),
    )
    result = []
    for index in range(point_count):
        distance = start_distance + length * index / (point_count - 1)
        result.append(
            [round(distance, 1), round(_interpolate(distance, distances, elevations), 1)]
        )
    return result


def _sequence_label(climbs: Sequence[Mapping]) -> str:
    if not climbs:
        return "无显著爬坡"
    return " + ".join(
        ("未分级" if item["category"] == "uncategorized" else f"Cat {item['category']}")
        for item in climbs
    )


def _route_boundary_status(
    climbs: Sequence[Mapping],
    *,
    variants_supplied: bool,
) -> str:
    if any(item.get("boundary_status") == "ambiguous" for item in climbs):
        return "ambiguous"
    if not variants_supplied or any(
        item.get("boundary_status") == "not_assessed" for item in climbs
    ):
        return "not_assessed"
    return "stable"


def _finish_type(
    climbs: Sequence[Mapping],
    distances: Sequence[float],
    elevations: Sequence[float],
) -> str:
    if climbs:
        last_end = float(climbs[-1]["end_distance_m"])
        if distances[-1] - last_end <= 200.0:
            return "summit"
        post_gain, post_loss = _gain_loss_between(
            last_end,
            distances[-1],
            distances,
            elevations,
        )
        if post_loss >= max(50.0, post_gain + 20.0):
            return "descent"
        if post_gain + post_loss >= 30.0:
            return "rolling"
        return "flat"
    route_gain, route_loss = _gain_loss(elevations)
    if route_loss >= max(50.0, route_gain + 20.0):
        return "descent"
    if route_gain + route_loss >= 30.0:
        return "rolling"
    return "flat"


def _source_confidence(source_method: str, horizontal_resolution_m: float | None) -> str:
    method = str(source_method).lower()
    if "barometric" in method or "verified_fit" in method:
        return "high"
    if (
        "glo30" in method
        or "authorized_point_elevation" in method
        or (horizontal_resolution_m is not None and horizontal_resolution_m <= 30)
    ):
        return "terrain_estimate"
    return "low"


def _bike_mass_assumption(bike_type: str | None) -> float:
    return {"road": 9.0, "gravel": 11.0, "mtb": 13.0}.get(str(bike_type or ""), 10.0)


def _normalize_power_curve(
    value: Mapping[str | int, float] | None,
) -> list[tuple[float, float]]:
    points_by_duration: dict[float, float] = {}
    for duration, power in (value or {}).items():
        try:
            seconds = float(duration)
            watts = float(power)
        except (TypeError, ValueError):
            continue
        if seconds >= 60 and watts > 0 and math.isfinite(seconds) and math.isfinite(watts):
            points_by_duration[seconds] = max(points_by_duration.get(seconds, 0.0), watts)
    envelope = []
    previous_power = math.inf
    for seconds, watts in sorted(points_by_duration.items()):
        previous_power = min(previous_power, watts)
        envelope.append((seconds, previous_power))
    return envelope


def _solve_pdc_limited_target(
    climb: Mapping,
    *,
    nominal_target_w: float,
    curve_fraction: float,
    power_curve: Sequence[tuple[float, float]],
    cumulative_climbing_seconds: float,
    rider_mass_kg: float,
    base_physics: Mapping[str, float],
) -> tuple[float, float, float, bool]:
    """求功率↔耗时固定点；PDC 覆盖外保持 FTP 目标并显式返回未覆盖。"""
    target = nominal_target_w
    duration = _estimate_climb_seconds(
        climb,
        target_power_w=target,
        rider_mass_kg=rider_mass_kg,
        **base_physics,
    )
    effective_duration = duration + cumulative_climbing_seconds
    if not (
        power_curve
        and power_curve[0][0] <= effective_duration <= power_curve[-1][0]
    ):
        return target, duration, effective_duration, False

    for _ in range(12):
        observed = _interpolate_power_curve(power_curve, effective_duration)
        if observed is None or observed <= 0:
            return nominal_target_w, duration, effective_duration, False
        next_target = min(nominal_target_w, observed * curve_fraction)
        next_duration = _estimate_climb_seconds(
            climb,
            target_power_w=next_target,
            rider_mass_kg=rider_mass_kg,
            **base_physics,
        )
        next_effective = next_duration + cumulative_climbing_seconds
        if not (power_curve[0][0] <= next_effective <= power_curve[-1][0]):
            # 一次限功若把预计时长推到曲线证据外，不继续外推。
            return nominal_target_w, duration, effective_duration, False
        converged = (
            abs(next_target - target) < 0.25
            and abs(next_duration - duration) < 1.0
        )
        target = next_target
        duration = next_duration
        effective_duration = next_effective
        if converged:
            break
    return target, duration, effective_duration, True


def _interpolate_power_curve(
    curve: Sequence[tuple[float, float]], duration_sec: float
) -> float | None:
    if not curve:
        return None
    duration = max(1.0, float(duration_sec))
    if duration <= curve[0][0]:
        return curve[0][1]
    if duration >= curve[-1][0]:
        return curve[-1][1]
    for (left_t, left_w), (right_t, right_w) in zip(curve, curve[1:]):
        if left_t <= duration <= right_t:
            ratio = (math.log(duration) - math.log(left_t)) / (
                math.log(right_t) - math.log(left_t)
            )
            return left_w + (right_w - left_w) * ratio
    return None


def _estimate_climb_seconds(
    climb: Mapping,
    *,
    target_power_w: float,
    rider_mass_kg: float,
    bike_mass_kg: float,
    rolling_coefficient: float,
    air_density: float,
    drag_area: float,
    headwind_mps: float,
) -> float:
    profile = list(climb.get("profile") or [])
    if len(profile) < 2:
        length = float(climb.get("length_m") or 0.0)
        gain = float(climb.get("net_gain_m") or 0.0)
        profile = [[0.0, 0.0], [length, gain]]
    total_mass = rider_mass_kg + bike_mass_kg
    seconds = 0.0
    for left, right in zip(profile, profile[1:]):
        distance = float(right[0]) - float(left[0])
        if distance <= 0:
            continue
        grade = (float(right[1]) - float(left[1])) / distance
        speed = _steady_speed_mps(
            target_power_w,
            grade=grade,
            total_mass_kg=total_mass,
            rolling_coefficient=rolling_coefficient,
            air_density=air_density,
            drag_area=drag_area,
            headwind_mps=headwind_mps,
        )
        seconds += distance / speed
    return seconds


def _steady_speed_mps(
    power_w: float,
    *,
    grade: float,
    total_mass_kg: float,
    rolling_coefficient: float,
    air_density: float,
    drag_area: float,
    headwind_mps: float,
) -> float:
    drivetrain_efficiency = 0.97
    gravity = 9.80665
    delivered_power = max(1.0, float(power_w) * drivetrain_efficiency)
    slope = max(-0.20, min(0.30, float(grade)))

    def required(speed: float) -> float:
        gravity_and_rolling = total_mass_kg * gravity * (slope + rolling_coefficient)
        relative_air_speed = max(0.0, speed + headwind_mps)
        aerodynamic = 0.5 * air_density * drag_area * relative_air_speed * relative_air_speed
        return max(0.0, gravity_and_rolling + aerodynamic) * speed

    low = 0.3
    high = 16.67  # 骑前估时不让无风稳态模型在短下坡推到 60km/h 以上。
    if required(high) <= delivered_power:
        return high
    for _ in range(60):
        middle = (low + high) / 2.0
        if required(middle) <= delivered_power:
            low = middle
        else:
            high = middle
    return max(low, 0.3)
