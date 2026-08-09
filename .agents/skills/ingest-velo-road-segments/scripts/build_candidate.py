#!/usr/bin/env python3
"""从公开赛段观察生成腾讯轨迹 + VELO 海拔候选；不访问 Strava API，不写数据库。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import urlparse


SUPPORTED_TENCENT_ROUTING_PROFILES = {"bicycling", "driving"}


class CandidateInputError(ValueError):
    """输入观察不完整或互相矛盾。"""


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "app").is_dir() and (parent / "AGENTS.md").is_file():
            return parent
    raise RuntimeError("找不到 VELO 仓库根目录")


def _supported_cities() -> set[str]:
    repo = _repo_root()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from app.user.cities import ALL_CITY_CODES_WITH_UNKNOWN

    return set(ALL_CITY_CODES_WITH_UNKNOWN)


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CandidateInputError(f"{label} 必须是对象")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateInputError(f"{label} 不能为空")
    return value.strip()


def _coordinate(value: object, label: str) -> dict[str, Any]:
    item = _require_mapping(value, label)
    try:
        lat = float(item["lat"])
        lon = float(item["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CandidateInputError(f"{label} 缺少有效 lat/lon") from exc
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise CandidateInputError(f"{label} 坐标不是有限数字")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise CandidateInputError(f"{label} 坐标越界")
    return {"lat": lat, "lon": lon, "name": str(item.get("name") or "").strip() or None}


def _parse_observed_at(value: object) -> str:
    text = _require_text(value, "discovery.observed_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateInputError("discovery.observed_at 必须是 ISO-8601 时间") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateInputError("discovery.observed_at 必须带时区")
    return parsed.isoformat()


def _strava_page_url(value: object, label: str) -> str:
    source_url = _require_text(value, label)
    parsed_url = urlparse(source_url)
    host = (parsed_url.hostname or "").lower()
    if parsed_url.scheme not in {"http", "https"} or not (
        host == "strava.com" or host.endswith(".strava.com")
    ):
        raise CandidateInputError(f"{label} 必须是 Strava 页面 URL")
    if "/api/" in parsed_url.path.lower() or host.startswith("api."):
        raise CandidateInputError("本流程不接受 Strava API URL")
    if re.search(r"/(?:segments)/\d+(?:/|$)", parsed_url.path) is None:
        raise CandidateInputError(f"{label} 必须指向具体 Strava 赛段页面")
    return source_url


def _positive_number(value: object, label: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise CandidateInputError(f"{label} 必须是数字")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateInputError(f"{label} 必须是数字") from exc
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        qualifier = "非负" if allow_zero else "正"
        raise CandidateInputError(f"{label} 必须是{qualifier}有限数字")
    return number


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    return _positive_number(value, label, allow_zero=True)


def _optional_finite_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise CandidateInputError(f"{label} 必须是数字")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateInputError(f"{label} 必须是数字") from exc
    if not math.isfinite(number):
        raise CandidateInputError(f"{label} 必须是有限数字")
    return number


def _text_list(value: object, label: str, *, maximum: int = 20) -> list[str]:
    if not isinstance(value, list) or not value:
        raise CandidateInputError(f"{label} 必须是非空数组")
    if len(value) > maximum:
        raise CandidateInputError(f"{label} 最多 {maximum} 项")
    return [_require_text(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _target_definition(value: object) -> dict[str, Any]:
    target = _require_mapping(value, "target_definition")
    distance_range = _require_mapping(
        target.get("expected_distance_range_m"),
        "target_definition.expected_distance_range_m",
    )
    minimum = _positive_number(
        distance_range.get("min"), "target_definition.expected_distance_range_m.min"
    )
    maximum = _positive_number(
        distance_range.get("max"), "target_definition.expected_distance_range_m.max"
    )
    if maximum < minimum:
        raise CandidateInputError("target_definition 预期距离上限不能小于下限")

    start_raw = target.get("expected_start_wgs84")
    end_raw = target.get("expected_end_wgs84")
    if (start_raw is None) != (end_raw is None):
        raise CandidateInputError("target_definition 预期起终点必须同时提供或同时省略")
    expected_start = _coordinate(start_raw, "target_definition.expected_start_wgs84") if start_raw is not None else None
    expected_end = _coordinate(end_raw, "target_definition.expected_end_wgs84") if end_raw is not None else None
    endpoint_tolerance_m = None
    if expected_start is not None:
        endpoint_tolerance_m = _positive_number(
            target.get("endpoint_tolerance_m"), "target_definition.endpoint_tolerance_m"
        )

    sources_raw = target.get("acceptance_sources")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise CandidateInputError("target_definition.acceptance_sources 必须是非空数组")
    if len(sources_raw) > 10:
        raise CandidateInputError("target_definition.acceptance_sources 最多 10 项")
    sources: list[dict[str, str]] = []
    for index, raw in enumerate(sources_raw):
        label = f"target_definition.acceptance_sources[{index}]"
        source = _require_mapping(raw, label)
        sources.append(
            {
                "type": _require_text(source.get("type"), f"{label}.type"),
                "reference": _require_text(source.get("reference"), f"{label}.reference"),
                "note": _require_text(source.get("note"), f"{label}.note"),
            }
        )

    return {
        "physical_role": _require_text(target.get("physical_role"), "target_definition.physical_role"),
        "expected_direction": _require_text(
            target.get("expected_direction"), "target_definition.expected_direction"
        ),
        "expected_distance_range_m": {"min": minimum, "max": maximum},
        "expected_start_wgs84": expected_start,
        "expected_end_wgs84": expected_end,
        "endpoint_tolerance_m": endpoint_tolerance_m,
        "required_shape_features": _text_list(
            target.get("required_shape_features"), "target_definition.required_shape_features"
        ),
        "acceptance_sources": sources,
    }


def _selection(value: object, *, selected_url: str) -> dict[str, Any]:
    selection = _require_mapping(value, "selection")
    check = _require_mapping(selection.get("identity_check"), "selection.identity_check")
    check_result: dict[str, str] = {}
    for key in ("boundary_match", "direction_match", "distance_match", "shape_match"):
        raw = check.get(key)
        if raw != "yes":
            raise CandidateInputError(f"selection.identity_check.{key} 未通过，禁止进入腾讯算路")
        check_result[key] = "yes"
    check_result["checked_against"] = _require_text(
        check.get("checked_against"), "selection.identity_check.checked_against"
    )
    check_result["selection_basis"] = _require_text(
        check.get("selection_basis"), "selection.identity_check.selection_basis"
    )

    rejected_raw = selection.get("rejected_candidates", [])
    if not isinstance(rejected_raw, list):
        raise CandidateInputError("selection.rejected_candidates 必须是数组")
    if len(rejected_raw) > 50:
        raise CandidateInputError("selection.rejected_candidates 最多 50 项")
    rejected: list[dict[str, str]] = []
    seen_urls = {selected_url}
    for index, raw in enumerate(rejected_raw):
        label = f"selection.rejected_candidates[{index}]"
        candidate = _require_mapping(raw, label)
        url = _strava_page_url(candidate.get("source_url"), f"{label}.source_url")
        if url in seen_urls:
            raise CandidateInputError(f"{label}.source_url 与已选择或已拒绝候选重复")
        seen_urls.add(url)
        rejected.append(
            {
                "name": _require_text(candidate.get("name"), f"{label}.name"),
                "source_url": url,
                "rejection_reason": _require_text(
                    candidate.get("rejection_reason"), f"{label}.rejection_reason"
                ),
            }
        )
    return {
        "source_segment_name": _require_text(
            selection.get("source_segment_name"), "selection.source_segment_name"
        ),
        "identity_check": check_result,
        "rejected_candidates": rejected,
    }


def _reconstruction(value: object) -> dict[str, str]:
    reconstruction = _require_mapping(value, "reconstruction")
    profile = _require_text(
        reconstruction.get("tencent_routing_profile"),
        "reconstruction.tencent_routing_profile",
    )
    if profile not in SUPPORTED_TENCENT_ROUTING_PROFILES:
        choices = ", ".join(sorted(SUPPORTED_TENCENT_ROUTING_PROFILES))
        raise CandidateInputError(
            f"reconstruction.tencent_routing_profile 只支持：{choices}"
        )
    return {
        "tencent_routing_profile": profile,
        "profile_selection_reason": _require_text(
            reconstruction.get("profile_selection_reason"),
            "reconstruction.profile_selection_reason",
        ),
    }


def _observed_metrics(value: object) -> dict[str, float | None]:
    item = _require_mapping(value, "discovery.observed_metrics")
    result = {
        "distance_m": _positive_number(item.get("distance_m"), "discovery.observed_metrics.distance_m"),
        "elevation_gain_m": _optional_number(
            item.get("elevation_gain_m"), "discovery.observed_metrics.elevation_gain_m"
        ),
        "average_gradient_pct": _optional_finite_number(
            item.get("average_gradient_pct"), "discovery.observed_metrics.average_gradient_pct"
        ),
        "minimum_elevation_m": _optional_finite_number(
            item.get("minimum_elevation_m"), "discovery.observed_metrics.minimum_elevation_m"
        ),
        "maximum_elevation_m": _optional_finite_number(
            item.get("maximum_elevation_m"), "discovery.observed_metrics.maximum_elevation_m"
        ),
    }
    if (
        result["minimum_elevation_m"] is not None
        and result["maximum_elevation_m"] is not None
        and result["minimum_elevation_m"] > result["maximum_elevation_m"]
    ):
        raise CandidateInputError("discovery.observed_metrics 最低海拔不能高于最高海拔")
    return result


def _coordinate_observation(value: object) -> dict[str, Any]:
    observation = _require_mapping(value, "discovery.coordinate_observation")
    acquisition_mode = observation.get("acquisition_mode")
    supported_modes = {
        "strava_visible_markers_aligned_to_tencent_map",
        "legacy_verified_geometry_regression",
    }
    if acquisition_mode not in supported_modes:
        raise CandidateInputError(
            "discovery.coordinate_observation.acquisition_mode 只支持 "
            + "、".join(sorted(supported_modes))
        )
    if observation.get("strava_start_marker_seen") is not True:
        raise CandidateInputError("必须在公开页面看到 Strava 起点标记")
    if observation.get("strava_end_marker_seen") is not True:
        raise CandidateInputError("必须在公开页面看到 Strava 终点标记")
    legacy_geometry_used = observation.get("legacy_geometry_used")
    if not isinstance(legacy_geometry_used, bool):
        raise CandidateInputError(
            "discovery.coordinate_observation.legacy_geometry_used 必须是布尔值"
        )
    if (
        acquisition_mode == "strava_visible_markers_aligned_to_tencent_map"
        and legacy_geometry_used
    ):
        raise CandidateInputError("新收录模式不能把旧 GPX 或旧轨迹当作坐标来源")
    if (
        acquisition_mode == "legacy_verified_geometry_regression"
        and not legacy_geometry_used
    ):
        raise CandidateInputError("历史回归模式必须如实标明使用了旧轨迹定位坐标")
    return {
        "acquisition_mode": acquisition_mode,
        "strava_start_marker_seen": True,
        "strava_end_marker_seen": True,
        "alignment_method": _require_text(
            observation.get("alignment_method"),
            "discovery.coordinate_observation.alignment_method",
        ),
        "estimated_accuracy_m": _positive_number(
            observation.get("estimated_accuracy_m"),
            "discovery.coordinate_observation.estimated_accuracy_m",
        ),
        "legacy_geometry_used": legacy_geometry_used,
        "note": _require_text(
            observation.get("note"),
            "discovery.coordinate_observation.note",
        ),
    }


def _popularity(value: object, label: str = "discovery.popularity") -> dict[str, int | None]:
    item = _require_mapping(value, label)
    result: dict[str, int | None] = {}
    for key in ("athlete_count", "effort_count", "star_count"):
        raw = item.get(key)
        if raw is None:
            result[key] = None
            continue
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise CandidateInputError(f"{label}.{key} 必须是非负整数或 null")
        result[key] = raw
    return result


def _nearby_comparisons(discovery: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    raw = discovery.get("nearby_comparisons", [])
    if not isinstance(raw, list):
        raise CandidateInputError("discovery.nearby_comparisons 必须是数组")
    if len(raw) > 50:
        raise CandidateInputError("单次观察最多比较 50 条邻近赛段")
    scope_raw = discovery.get("comparison_scope")
    scope = str(scope_raw or "").strip() or None
    if raw and scope is None:
        raise CandidateInputError("有 nearby_comparisons 时必须说明 comparison_scope")
    result: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for index, value in enumerate(raw):
        label = f"discovery.nearby_comparisons[{index}]"
        item = _require_mapping(value, label)
        source_url = _strava_page_url(item.get("source_url"), f"{label}.source_url")
        if source_url in seen_urls:
            raise CandidateInputError(f"{label}.source_url 与前面的比较项重复")
        seen_urls.add(source_url)
        result.append(
            {
                "name": _require_text(item.get("name"), f"{label}.name"),
                "source_url": source_url,
                "relation": _require_text(item.get("relation"), f"{label}.relation"),
                **_popularity(item.get("popularity", {}), f"{label}.popularity"),
            }
        )
    return scope, result


def validate_manifest(value: object) -> dict[str, Any]:
    root = _require_mapping(value, "root")
    if root.get("schema_version") != 1:
        raise CandidateInputError("schema_version 当前只支持 1")
    segment = _require_mapping(root.get("segment"), "segment")
    discovery = _require_mapping(root.get("discovery"), "discovery")
    if discovery.get("source_type") != "strava_public_page":
        raise CandidateInputError("discovery.source_type 必须是 strava_public_page")

    source_url = _strava_page_url(discovery.get("source_url"), "discovery.source_url")
    target_definition = _target_definition(root.get("target_definition"))
    selection = _selection(root.get("selection"), selected_url=source_url)
    reconstruction = _reconstruction(root.get("reconstruction"))
    observed_metrics = _observed_metrics(discovery.get("observed_metrics"))
    expected_range = target_definition["expected_distance_range_m"]
    if not expected_range["min"] <= observed_metrics["distance_m"] <= expected_range["max"]:
        raise CandidateInputError(
            "公开页面距离不在 target_definition 预期范围内，候选身份不成立"
        )
    city = _require_text(segment.get("city"), "segment.city")
    if city not in _supported_cities():
        raise CandidateInputError(f"segment.city 不在当前城市枚举中：{city}")
    comparison_scope, nearby_comparisons = _nearby_comparisons(discovery)
    coordinate_observation = _coordinate_observation(
        discovery.get("coordinate_observation")
    )

    start = _coordinate(discovery.get("start_wgs84"), "discovery.start_wgs84")
    end = _coordinate(discovery.get("end_wgs84"), "discovery.end_wgs84")
    anchors_raw = discovery.get("anchors_wgs84", [])
    if not isinstance(anchors_raw, list):
        raise CandidateInputError("discovery.anchors_wgs84 必须是数组")
    if len(anchors_raw) > 20:
        raise CandidateInputError("单条候选最多支持 20 个锚点，请拆分路段")
    anchors = [_coordinate(item, f"discovery.anchors_wgs84[{index}]") for index, item in enumerate(anchors_raw)]
    ordered = [start, *anchors, end]
    for index, (left, right) in enumerate(zip(ordered, ordered[1:])):
        if _haversine_m(left["lat"], left["lon"], right["lat"], right["lon"]) < 1.0:
            raise CandidateInputError(f"第 {index + 1}、{index + 2} 个路由点重复或相距不足 1 米")

    expected_start = target_definition["expected_start_wgs84"]
    expected_end = target_definition["expected_end_wgs84"]
    tolerance = target_definition["endpoint_tolerance_m"]
    if expected_start is not None and tolerance is not None:
        if _haversine_m(start["lat"], start["lon"], expected_start["lat"], expected_start["lon"]) > tolerance:
            raise CandidateInputError("公开页面起点超出 target_definition 允许偏差")
        if _haversine_m(end["lat"], end["lon"], expected_end["lat"], expected_end["lon"]) > tolerance:
            raise CandidateInputError("公开页面终点超出 target_definition 允许偏差")

    return {
        "schema_version": 1,
        "target_definition": target_definition,
        "selection": selection,
        "reconstruction": reconstruction,
        "segment": {
            "name": _require_text(segment.get("name"), "segment.name"),
            "city": city,
            "direction": _require_text(segment.get("direction"), "segment.direction"),
        },
        "discovery": {
            "source_type": "strava_public_page",
            "source_url": source_url,
            "observed_at": _parse_observed_at(discovery.get("observed_at")),
            "coordinate_observation": coordinate_observation,
            "start_wgs84": start,
            "end_wgs84": end,
            "anchors_wgs84": anchors,
            "route_shape_notes": str(discovery.get("route_shape_notes") or "").strip() or None,
            "observed_metrics": observed_metrics,
            "popularity": _popularity(discovery.get("popularity", {})),
            "comparison_scope": comparison_scope,
            "nearby_comparisons": nearby_comparisons,
        },
    }


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))


def _distance_m(points: list[list[float]]) -> float:
    return sum(
        _haversine_m(left[1], left[0], right[1], right[0])
        for left, right in zip(points, points[1:])
    )


def _default_runtime(
    routing_profile: str,
) -> tuple[Callable[..., dict[str, Any]], Callable[..., Any], Callable[[list[list[float]]], list[list[float]]], Callable[[list[list[float]]], list[list[float]]], str, dict[str, Any], Callable[[str], str], str]:
    repo = _repo_root()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    import numpy as np
    import xyconvert
    from app.elevation.route_elevation import (
        ROUTE_ELEVATION_METHOD,
        build_route_elevation_result,
        route_elevation_metadata,
    )
    from app.route_book.tencent_direction import plan_tencent_bicycling_route, plan_tencent_driving_route
    from app.route_cognition.geometry_hash import (
        SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        hash_segment_geometry_wkt,
    )
    from app.segment.coord_convert import convert_points_to_wgs84

    def wgs_to_gcj(points: list[list[float]]) -> list[list[float]]:
        converted = xyconvert.wgs2gcj(np.asarray(points, dtype=float))
        return [[float(lon), float(lat)] for lon, lat in converted]

    def gcj_to_wgs(points: list[list[float]]) -> list[list[float]]:
        payload = [{"lon": lon, "lat": lat} for lon, lat in points]
        converted = convert_points_to_wgs84(payload, "gcj02")
        return [[float(point["lon"]), float(point["lat"])] for point in converted]

    planners = {
        "bicycling": plan_tencent_bicycling_route,
        "driving": plan_tencent_driving_route,
    }
    return (
        planners[routing_profile],
        build_route_elevation_result,
        wgs_to_gcj,
        gcj_to_wgs,
        ROUTE_ELEVATION_METHOD,
        route_elevation_metadata(),
        hash_segment_geometry_wkt,
        SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
    )


def _geometry_wkt(points: list[list[float]]) -> str:
    pairs = ", ".join(f"{lon:.8f} {lat:.8f}" for lon, lat in points)
    return f"LINESTRING({pairs})"


def _max_gradient(snapshot: list[list[float]], window_m: float = 500.0) -> float:
    if len(snapshot) < 2:
        return 0.0
    cumulative = [0.0]
    for left, right in zip(snapshot, snapshot[1:]):
        cumulative.append(cumulative[-1] + _haversine_m(left[1], left[0], right[1], right[0]))
    total = cumulative[-1]
    if total <= 0:
        return 0.0
    target = min(window_m, total / 4.0) if window_m > total / 2.0 else window_m
    maximum = 0.0
    right_index = 0
    for left_index in range(len(snapshot)):
        right_index = max(right_index, left_index + 1)
        while right_index < len(snapshot) and cumulative[right_index] - cumulative[left_index] < target:
            right_index += 1
        if right_index >= len(snapshot):
            break
        distance = cumulative[right_index] - cumulative[left_index]
        maximum = max(maximum, abs(snapshot[right_index][2] - snapshot[left_index][2]) / distance * 100)
    return round(min(maximum, 25.0), 2)


def _input_digest(manifest: dict[str, Any]) -> str:
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_candidate(
    manifest: dict[str, Any],
    *,
    planner: Callable[..., dict[str, Any]] | None = None,
    elevation_builder: Callable[..., Any] | None = None,
    wgs_to_gcj: Callable[[list[list[float]]], list[list[float]]] | None = None,
    gcj_to_wgs: Callable[[list[list[float]]], list[list[float]]] | None = None,
    elevation_method: str | None = None,
    elevation_metadata: dict[str, Any] | None = None,
    geometry_hasher: Callable[[str], str] | None = None,
    geometry_normalization_version: str | None = None,
    delay_sec: float = 1.5,
    sleep_func: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
) -> dict[str, Any]:
    manifest = validate_manifest(manifest)
    runtime = None
    if any(
        item is None
        for item in (
            planner,
            elevation_builder,
            wgs_to_gcj,
            gcj_to_wgs,
            elevation_method,
            geometry_hasher,
            geometry_normalization_version,
        )
    ):
        runtime = _default_runtime(manifest["reconstruction"]["tencent_routing_profile"])
        planner = planner or runtime[0]
        elevation_builder = elevation_builder or runtime[1]
        wgs_to_gcj = wgs_to_gcj or runtime[2]
        gcj_to_wgs = gcj_to_wgs or runtime[3]
        elevation_method = elevation_method or runtime[4]
        geometry_hasher = geometry_hasher or runtime[6]
        geometry_normalization_version = geometry_normalization_version or runtime[7]
    if elevation_metadata is None:
        elevation_metadata = runtime[5] if runtime is not None else {}

    discovery = manifest["discovery"]
    ordered = [discovery["start_wgs84"], *discovery["anchors_wgs84"], discovery["end_wgs84"]]
    routing_wgs = [[point["lon"], point["lat"]] for point in ordered]
    routing_gcj = wgs_to_gcj(routing_wgs)
    if len(routing_gcj) != len(routing_wgs):
        raise RuntimeError("WGS-84 -> GCJ-02 坐标转换数量不一致")

    combined_gcj: list[list[float]] = []
    provider_distance_m = 0.0
    leg_diagnostics: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, (start, end) in enumerate(zip(routing_gcj, routing_gcj[1:])):
        if index and delay_sec > 0:
            sleep_func(delay_sec)
        planned = planner((start[1], start[0]), (end[1], end[0]))
        raw_points = planned.get("points") or []
        leg_points = [[float(point["lon"]), float(point["lat"])] for point in raw_points]
        if len(leg_points) < 2:
            raise RuntimeError(f"腾讯第 {index + 1} 段没有返回有效点串")
        if combined_gcj and _distance_m([combined_gcj[-1], leg_points[0]]) < 1.0:
            leg_points = leg_points[1:]
        combined_gcj.extend(leg_points)
        leg_provider_distance = float(planned.get("distance") or _distance_m(leg_points))
        provider_distance_m += leg_provider_distance
        leg_diagnostics.append(
            {
                "leg_number": index + 1,
                "start_wgs84": ordered[index],
                "end_wgs84": ordered[index + 1],
                "provider_distance_m": round(leg_provider_distance, 2),
                "provider_duration_raw": planned.get("duration"),
                "provider_point_count": len(raw_points),
            }
        )
        direct_distance = _haversine_m(ordered[index]["lat"], ordered[index]["lon"], ordered[index + 1]["lat"], ordered[index + 1]["lon"])
        if direct_distance <= 500 and leg_provider_distance >= direct_distance * 3 and leg_provider_distance - direct_distance >= 1000:
            warnings.append(f"第 {index + 1} 段出现明显绕行，必须人工核对")

    points_wgs = gcj_to_wgs(combined_gcj)
    if len(points_wgs) < 2:
        raise RuntimeError("腾讯点串转 WGS-84 后不足 2 点")
    measured_distance_m = _distance_m(points_wgs)
    if measured_distance_m <= 0:
        raise RuntimeError("腾讯候选几何距离为 0")
    expected_range = manifest["target_definition"]["expected_distance_range_m"]
    if not expected_range["min"] <= measured_distance_m <= expected_range["max"]:
        raise RuntimeError(
            "腾讯路线距离不在目标预期范围，调整 routing profile 或锚点后重跑；"
            f"实测 {measured_distance_m:.2f} 米，预期 {expected_range['min']:.2f}–{expected_range['max']:.2f} 米"
        )
    elevation = elevation_builder(points_wgs)
    snapshot = [[float(lon), float(lat), float(ele)] for lon, lat, ele in elevation.snapshot]
    if len(snapshot) != len(points_wgs):
        raise RuntimeError("VELO 海拔快照与腾讯几何点数不一致")
    wkt = _geometry_wkt(points_wgs)
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    avg_gradient = (snapshot[-1][2] - snapshot[0][2]) / measured_distance_m * 100

    return {
        "schema_version": 1,
        "candidate_id": hashlib.sha256(f"{manifest['segment']['name']}:{_input_digest(manifest)}".encode("utf-8")).hexdigest()[:24],
        "status": "needs_review",
        "generated_at": generated_at,
        "segment": manifest["segment"],
        "identity_evidence": {
            "target_definition": manifest["target_definition"],
            "selection": manifest["selection"],
            "source_observation": {
                "source_segment_name": manifest["selection"]["source_segment_name"],
                "source_url": discovery["source_url"],
                "observed_at": discovery["observed_at"],
                "metrics": discovery["observed_metrics"],
                "coordinate_observation": discovery["coordinate_observation"],
            },
        },
        "hard_knowledge": {
            "geometry": {
                "source": "tencent_directions",
                "routing_profile": manifest["reconstruction"]["tencent_routing_profile"],
                "coordinate_system": "wgs84",
                "normalization_version": geometry_normalization_version,
                "geometry_hash": geometry_hasher(wkt),
                "wkt": wkt,
                "points": points_wgs,
                "point_count": len(points_wgs),
                "routing_anchor_count": len(routing_wgs),
            },
            "metrics": {
                "distance_m": round(measured_distance_m, 2),
                "provider_distance_m": round(provider_distance_m, 2),
                "elevation_gain_m": round(float(elevation.climb), 2),
                "elevation_loss_m": round(float(elevation.descent), 2),
                "average_gradient_pct": round(avg_gradient, 2),
                "maximum_gradient_pct": _max_gradient(snapshot),
            },
            "elevation": {
                "method": elevation_method,
                "metadata": elevation_metadata,
                "snapshot": snapshot,
                "profile": elevation.profile,
                "point_count": int(elevation.point_count),
            },
        },
        "popularity_observation": {
            "source_type": discovery["source_type"],
            "source_url": discovery["source_url"],
            "observed_at": discovery["observed_at"],
            **discovery["popularity"],
            "comparison_scope": discovery["comparison_scope"],
            "nearby_comparisons": discovery["nearby_comparisons"],
        },
        "derived_judgments": [],
        "provenance": {
            "strava_access_mode": "human_visible_public_page",
            "strava_api_used": False,
            "route_shape_notes": discovery["route_shape_notes"],
            "input_sha256": _input_digest(manifest),
            "routing_points_wgs84": ordered,
            "routing_points_gcj02": [
                {"lon": float(point[0]), "lat": float(point[1])}
                for point in routing_gcj
            ],
            "tencent_routing_profile": manifest["reconstruction"]["tencent_routing_profile"],
            "routing_profile_selection_reason": manifest["reconstruction"]["profile_selection_reason"],
            "tencent_leg_diagnostics": leg_diagnostics,
        },
        "quality_gates": {
            "target_identity_match": "passed",
            "gpx_independent_coordinates": (
                "passed"
                if discovery["coordinate_observation"]["acquisition_mode"]
                == "strava_visible_markers_aligned_to_tencent_map"
                else "regression_only"
            ),
            "tencent_route_generated": "passed",
            "tencent_distance_match": "passed",
            "elevation_complete": "passed",
            "endpoint_match": "pending",
            "direction_match": "pending",
            "shape_match": "pending",
            "warnings_reviewed": "pending",
        },
        "warnings": warnings,
        "review": None,
    }


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CandidateInputError(f"输入文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise CandidateInputError(f"输入不是有效 JSON：{exc}") from exc


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    repo = _repo_root()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from app.elevation.dem_client import DEMServiceError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--delay-sec", type=float, default=1.5)
    args = parser.parse_args()
    try:
        manifest = validate_manifest(_read_json(args.input))
        if args.validate_only:
            print(json.dumps({"valid": True, "name": manifest["segment"]["name"], "routing_point_count": 2 + len(manifest["discovery"]["anchors_wgs84"])}, ensure_ascii=False))
            return 0
        if args.output is None:
            raise CandidateInputError("生成候选时必须提供 --output")
        if args.delay_sec < 0 or not math.isfinite(args.delay_sec):
            raise CandidateInputError("--delay-sec 必须是非负有限数字")
        os.environ.setdefault(
            "GLO30_CACHE_DIR",
            str(Path(tempfile.gettempdir()) / "velo-road-segment-glo30-cache"),
        )
        candidate = build_candidate(manifest, delay_sec=args.delay_sec)
        _write_json(args.output, candidate)
        print(json.dumps({"status": candidate["status"], "candidate_id": candidate["candidate_id"], "output": str(args.output), "warning_count": len(candidate["warnings"])}, ensure_ascii=False))
        return 0
    except (CandidateInputError, DEMServiceError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
