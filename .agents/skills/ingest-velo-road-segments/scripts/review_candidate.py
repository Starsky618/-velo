#!/usr/bin/env python3
"""把 needs_review 候选冻结为 verified 或 rejected；不覆盖原文件，不写数据库。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any


class ReviewError(ValueError):
    """复核输入缺失或候选合同不成立。"""


def _check_status(value: str | None) -> str:
    if value == "yes":
        return "passed"
    if value == "no":
        return "failed"
    return "not_checked"


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewError(f"candidate 缺少 {label}")
    return value


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewError(f"candidate 缺少 {label}")
    return value.strip()


def _finite_number(value: object, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise ReviewError(f"candidate.{label} 必须是数字")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ReviewError(f"candidate.{label} 必须是数字") from exc
    if not math.isfinite(number) or (nonnegative and number < 0):
        qualifier = "非负有限数字" if nonnegative else "有限数字"
        raise ReviewError(f"candidate.{label} 必须是{qualifier}")
    return number


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "app").is_dir() and (parent / "AGENTS.md").is_file():
            return parent
    raise ReviewError("找不到 VELO 仓库根目录")


def _canonical_wkt(points: list[object]) -> str:
    pairs: list[str] = []
    for index, point in enumerate(points):
        if not isinstance(point, list) or len(point) < 2:
            raise ReviewError(f"candidate 第 {index + 1} 个 geometry point 格式错误")
        lon = _finite_number(point[0], f"hard_knowledge.geometry.points[{index}][0]")
        lat = _finite_number(point[1], f"hard_knowledge.geometry.points[{index}][1]")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ReviewError(f"candidate 第 {index + 1} 个 geometry point 坐标越界")
        pairs.append(f"{lon:.8f} {lat:.8f}")
    return f"LINESTRING({', '.join(pairs)})"


def _validate_candidate_contract(candidate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate_id = _nonempty_text(candidate.get("candidate_id"), "candidate_id")
    if candidate.get("review") is not None:
        raise ReviewError("candidate 在进入复核前 review 必须为空")
    hard = _mapping(candidate.get("hard_knowledge"), "hard_knowledge")
    geometry = _mapping(hard.get("geometry"), "hard_knowledge.geometry")
    profile = geometry.get("routing_profile")
    if (
        geometry.get("source") != "tencent_directions"
        or profile not in {"bicycling", "driving"}
        or geometry.get("coordinate_system") != "wgs84"
    ):
        raise ReviewError("candidate 几何必须来自腾讯且为 WGS-84")
    wkt = _nonempty_text(geometry.get("wkt"), "hard_knowledge.geometry.wkt")
    geometry_hash = _nonempty_text(
        geometry.get("geometry_hash"), "hard_knowledge.geometry.geometry_hash"
    )
    normalization_version = _nonempty_text(
        geometry.get("normalization_version"),
        "hard_knowledge.geometry.normalization_version",
    )
    points = geometry.get("points")
    point_count = geometry.get("point_count")
    if (
        not isinstance(points, list)
        or len(points) < 2
        or isinstance(point_count, bool)
        or point_count != len(points)
    ):
        raise ReviewError("candidate 腾讯 geometry points/point_count 不完整")

    repo = _repo_root()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from app.route_cognition.geometry_hash import (
        SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        hash_segment_geometry_wkt,
    )

    if normalization_version != SEGMENT_GEOMETRY_NORMALIZATION_VERSION:
        raise ReviewError("candidate geometry normalization_version 与当前代码不一致")
    if wkt != _canonical_wkt(points):
        raise ReviewError("candidate WKT 与腾讯 geometry.points 不一致")
    if hash_segment_geometry_wkt(wkt) != geometry_hash:
        raise ReviewError("candidate geometry_hash 与 WKT 不一致")

    metrics = _mapping(hard.get("metrics"), "hard_knowledge.metrics")
    distance_m = _finite_number(
        metrics.get("distance_m"),
        "hard_knowledge.metrics.distance_m",
        nonnegative=True,
    )
    provider_distance_m = _finite_number(
        metrics.get("provider_distance_m"),
        "hard_knowledge.metrics.provider_distance_m",
        nonnegative=True,
    )
    if distance_m <= 0 or provider_distance_m <= 0:
        raise ReviewError("candidate 距离必须大于 0")
    _finite_number(
        metrics.get("elevation_gain_m"),
        "hard_knowledge.metrics.elevation_gain_m",
        nonnegative=True,
    )
    _finite_number(
        metrics.get("elevation_loss_m"),
        "hard_knowledge.metrics.elevation_loss_m",
        nonnegative=True,
    )
    _finite_number(metrics.get("average_gradient_pct"), "hard_knowledge.metrics.average_gradient_pct")
    _finite_number(metrics.get("maximum_gradient_pct"), "hard_knowledge.metrics.maximum_gradient_pct")

    elevation = _mapping(hard.get("elevation"), "hard_knowledge.elevation")
    _nonempty_text(elevation.get("method"), "hard_knowledge.elevation.method")
    if not isinstance(elevation.get("metadata"), dict) or not elevation["metadata"]:
        raise ReviewError("candidate 缺少 hard_knowledge.elevation.metadata")
    snapshot = elevation.get("snapshot")
    if (
        not isinstance(snapshot, list)
        or elevation.get("point_count") != point_count
        or len(snapshot) != point_count
    ):
        raise ReviewError("candidate elevation snapshot/point_count 与 geometry 不一致")
    if not isinstance(elevation.get("profile"), list) or not elevation["profile"]:
        raise ReviewError("candidate 缺少 hard_knowledge.elevation.profile")
    for index, (point, elevated) in enumerate(zip(points, snapshot)):
        if (
            not isinstance(point, list)
            or len(point) < 2
            or not isinstance(elevated, list)
            or len(elevated) < 3
        ):
            raise ReviewError(f"candidate 第 {index + 1} 个 geometry/elevation 点格式错误")
        point_lon = float(point[0])
        point_lat = float(point[1])
        lon = _finite_number(elevated[0], f"hard_knowledge.elevation.snapshot[{index}][0]")
        lat = _finite_number(elevated[1], f"hard_knowledge.elevation.snapshot[{index}][1]")
        _finite_number(elevated[2], f"hard_knowledge.elevation.snapshot[{index}][2]")
        if abs(lon - point_lon) > 1e-5 or abs(lat - point_lat) > 1e-5:
            raise ReviewError("candidate elevation snapshot 坐标与腾讯 geometry 不一致")

    popularity = _mapping(candidate.get("popularity_observation"), "popularity_observation")
    _nonempty_text(popularity.get("observed_at"), "popularity_observation.observed_at")
    if popularity.get("source_type") != "strava_public_page":
        raise ReviewError("candidate popularity_observation 来源不正确")

    identity = _mapping(candidate.get("identity_evidence"), "identity_evidence")
    source_observation = _mapping(
        identity.get("source_observation"), "identity_evidence.source_observation"
    )
    coordinate_observation = _mapping(
        source_observation.get("coordinate_observation"),
        "identity_evidence.source_observation.coordinate_observation",
    )
    mode = coordinate_observation.get("acquisition_mode")
    legacy_used = coordinate_observation.get("legacy_geometry_used")
    if coordinate_observation.get("strava_start_marker_seen") is not True or coordinate_observation.get("strava_end_marker_seen") is not True:
        raise ReviewError("candidate 缺少 Strava 起终点 marker 观察")
    if mode == "strava_visible_markers_aligned_to_tencent_map" and legacy_used is False:
        expected_coordinate_gate = "passed"
    elif mode == "legacy_verified_geometry_regression" and legacy_used is True:
        expected_coordinate_gate = "regression_only"
    else:
        raise ReviewError("candidate 起终点来源声明互相矛盾")

    provenance = _mapping(candidate.get("provenance"), "provenance")
    if provenance.get("strava_api_used") is not False:
        raise ReviewError("candidate 必须明确未调用 Strava API")
    if provenance.get("tencent_routing_profile") != profile:
        raise ReviewError("candidate 腾讯 routing profile 在 geometry/provenance 中不一致")
    input_sha256 = _nonempty_text(provenance.get("input_sha256"), "provenance.input_sha256")
    segment = _mapping(candidate.get("segment"), "segment")
    segment_name = _nonempty_text(segment.get("name"), "segment.name")
    expected_candidate_id = hashlib.sha256(
        f"{segment_name}:{input_sha256}".encode("utf-8")
    ).hexdigest()[:24]
    if candidate_id != expected_candidate_id:
        raise ReviewError("candidate_id 与 segment/input digest 不一致")
    routing_wgs = provenance.get("routing_points_wgs84")
    routing_gcj = provenance.get("routing_points_gcj02")
    legs = provenance.get("tencent_leg_diagnostics")
    if (
        not isinstance(routing_wgs, list)
        or len(routing_wgs) < 2
        or not isinstance(routing_gcj, list)
        or len(routing_gcj) != len(routing_wgs)
        or not isinstance(legs, list)
        or len(legs) != len(routing_wgs) - 1
    ):
        raise ReviewError("candidate 腾讯 routing points/leg diagnostics 不完整")
    if geometry.get("routing_anchor_count") != len(routing_wgs):
        raise ReviewError("candidate geometry routing_anchor_count 与 provenance 不一致")
    _nonempty_text(
        provenance.get("routing_profile_selection_reason"),
        "provenance.routing_profile_selection_reason",
    )

    gates = _mapping(candidate.get("quality_gates"), "quality_gates")
    for gate in (
        "target_identity_match",
        "tencent_route_generated",
        "tencent_distance_match",
        "elevation_complete",
    ):
        if gates.get(gate) != "passed":
            raise ReviewError(f"candidate {gate} 未通过，不能进入几何复核")
    if gates.get("gpx_independent_coordinates") != expected_coordinate_gate:
        raise ReviewError("candidate 起终点来源门槛与原始 observation 不一致")
    return geometry, gates


def review_candidate(
    candidate: object,
    *,
    verdict: str,
    reviewer: str,
    note: str,
    endpoint_match: str | None = None,
    direction_match: str | None = None,
    shape_match: str | None = None,
    warnings_reviewed: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ReviewError("candidate 必须是对象")
    if candidate.get("schema_version") != 1 or candidate.get("status") != "needs_review":
        raise ReviewError("只接受 schema_version=1 且 status=needs_review 的候选")
    geometry, gates = _validate_candidate_contract(candidate)
    if not reviewer.strip() or not note.strip():
        raise ReviewError("reviewer 和 note 不能为空")
    if verdict not in {"accept", "reject"}:
        raise ReviewError("verdict 只支持 accept 或 reject")

    result = deepcopy(candidate)
    reviewed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    check_inputs = {
        "endpoint_match": endpoint_match,
        "direction_match": direction_match,
        "shape_match": shape_match,
        "warnings_reviewed": warnings_reviewed,
    }
    check_statuses = {key: _check_status(value) for key, value in check_inputs.items()}
    if verdict == "accept" and not all(status == "passed" for status in check_statuses.values()):
        missing = [key for key, status in check_statuses.items() if status != "passed"]
        raise ReviewError("接受候选前必须明确通过：" + ", ".join(missing))

    coordinate_gate = gates.get("gpx_independent_coordinates")
    if coordinate_gate not in {"passed", "regression_only"}:
        raise ReviewError("candidate 缺少有效的起终点来源门槛")
    if verdict == "accept":
        result["status"] = (
            "verified" if coordinate_gate == "passed" else "verified_regression"
        )
    else:
        result["status"] = "rejected"
    result["publication_eligible"] = result["status"] == "verified"
    result["review"] = {
        "verdict": verdict,
        "reviewer": reviewer.strip(),
        "reviewed_at": reviewed_at,
        "note": note.strip(),
        **check_inputs,
        "reviewed_geometry_hash": geometry.get("geometry_hash"),
    }
    for key, status in check_statuses.items():
        result["quality_gates"][key] = status
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--verdict", required=True, choices=("accept", "reject"))
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--endpoint-match", choices=("yes", "no"))
    parser.add_argument("--direction-match", choices=("yes", "no"))
    parser.add_argument("--shape-match", choices=("yes", "no"))
    parser.add_argument("--warnings-reviewed", choices=("yes", "no"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.candidate.resolve() == args.output.resolve():
            raise ReviewError("复核输出不能覆盖原候选文件")
        candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
        result = review_candidate(
            candidate,
            verdict=args.verdict,
            reviewer=args.reviewer,
            note=args.note,
            endpoint_match=args.endpoint_match,
            direction_match=args.direction_match,
            shape_match=args.shape_match,
            warnings_reviewed=args.warnings_reviewed,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "candidate_id": result["candidate_id"], "output": str(args.output)}, ensure_ascii=False))
        return 0
    except (OSError, json.JSONDecodeError, ReviewError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
