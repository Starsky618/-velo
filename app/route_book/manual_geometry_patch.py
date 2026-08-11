"""基于 Route Draw freehand 的赛段手绘几何补丁。

用于保留已经可信的路由结果，只用 Strava 来源轨迹或显式手绘线修补局部缺口。
每个几何部件保留独立来源、索引范围、抽稀误差和审核状态；部件之间的
短直线连接也必须显式记录，不能隐式把路由断点冒充成真实道路。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.parsing.geo_math import haversine
from app.route_book.draw_snap_service import MAX_RAW_POINTS, build_snap_preview


ALLOWED_SOURCE_TYPES = {
    "routing_candidate",
    "strava_page_stream",
    "strava_simplified_shape",
    "hand_drawn",
    "manual_straight_connector",
}
ALLOWED_REVIEW_STATUSES = {"source_shape", "needs_review", "human_reviewed"}
REQUIRED_FALLBACK_STAGES = ("tencent", "osm", "freehand")
DEFAULT_MAX_JOIN_GAP_M = 20.0
DEFAULT_SNAP_JOIN_WITHIN_M = 2.0
MAX_STRAIGHT_CONNECTOR_M = 500.0
MAX_OUTPUT_POINTS = 5000
DEFAULT_MAX_SOURCE_GAP_M = 100.0
DEFAULT_MAX_AUTO_SIMPLIFY_ERROR_M = 3.0
AUTO_SIMPLIFY_SEARCH_STEPS = 28


class ManualGeometryPatchError(ValueError):
    """补丁输入不足以安全生成赛段候选几何。"""


@dataclass(frozen=True)
class GeometryPart:
    part_id: str
    source_type: str
    source_name: str
    source_pointer: str
    source_content_sha256: str | None
    review_status: str
    points_wgs84: tuple[tuple[float, float], ...]
    source_material_point_count: int
    normalized_source_point_count: int
    source_point_count: int
    source_start_index: int
    source_end_index: int
    simplify_mode: str
    simplify_tolerance_m: float
    max_source_deviation_m: float
    max_source_gap_m: float
    max_output_gap_m: float
    distance_m: float


@dataclass(frozen=True)
class GeometryJoin:
    from_part_id: str
    to_part_id: str
    gap_m: float
    action: str


def load_patch_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManualGeometryPatchError(f"补丁 manifest 无法读取：{exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ManualGeometryPatchError("补丁 manifest schema_version 必须为 1")
    if not isinstance(payload.get("parts"), list) or not payload["parts"]:
        raise ManualGeometryPatchError("补丁 manifest 至少需要一个 parts 部件")
    return payload


def build_patch_candidate(manifest: dict[str, Any], *, manifest_dir: Path) -> dict[str, Any]:
    segment = manifest.get("segment")
    if not isinstance(segment, dict):
        raise ManualGeometryPatchError("segment 必须是对象")
    segment_id = str(segment.get("source_segment_id") or "").strip()
    segment_name = str(segment.get("source_segment_name") or "").strip()
    if not segment_id or not segment_name:
        raise ManualGeometryPatchError("segment 缺少 source_segment_id/source_segment_name")

    fallback_chain = _validate_fallback_chain(manifest.get("fallback_chain"))
    parts = [
        _load_part(part, manifest_dir=manifest_dir)
        for part in manifest["parts"]
    ]
    policy = manifest.get("join_policy") or {}
    max_join_gap_m = _positive_float(
        policy.get("max_gap_m", DEFAULT_MAX_JOIN_GAP_M),
        "join_policy.max_gap_m",
    )
    snap_join_within_m = _positive_float(
        policy.get("snap_within_m", DEFAULT_SNAP_JOIN_WITHIN_M),
        "join_policy.snap_within_m",
        allow_zero=True,
    )
    if snap_join_within_m > max_join_gap_m:
        raise ManualGeometryPatchError("join_policy.snap_within_m 不能大于 max_gap_m")

    points, joins = compose_geometry_parts(
        parts,
        max_join_gap_m=max_join_gap_m,
        snap_join_within_m=snap_join_within_m,
    )
    geometry_distance_m = _polyline_distance_m(points)
    expected_distance_m = _optional_positive_float(segment.get("observed_distance_m"))
    distance_delta_pct = None
    if expected_distance_m is not None:
        distance_delta_pct = (
            (geometry_distance_m - expected_distance_m) / expected_distance_m * 100.0
        )

    canonical = "\n".join(f"{lon:.8f},{lat:.8f}" for lon, lat in points)
    geometry_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    review_status = _candidate_review_status(parts, joins)
    warnings: list[str] = []
    for join in joins:
        if join.action == "explicit_straight_join":
            warnings.append(
                f"{join.from_part_id}->{join.to_part_id} 包含 {join.gap_m:.1f}m 显式直线连接"
            )
    if distance_delta_pct is not None and abs(distance_delta_pct) > 3.0:
        warnings.append(
            f"候选几何与来源距离相差 {distance_delta_pct:+.2f}%"
        )

    return {
        "schema_version": 1,
        "dataset_type": "manual_geometry_patch_candidate",
        "identity": {
            "source_segment_id": segment_id,
            "source_segment_name": segment_name,
            "source_url": segment.get("source_url"),
        },
        "geometry": {
            "coordinate_system": "wgs84",
            "point_order": "lon_lat",
            "point_count": len(points),
            "points_wgs84": [[lon, lat] for lon, lat in points],
            "distance_m": round(geometry_distance_m, 1),
            "observed_distance_m": expected_distance_m,
            "distance_delta_pct": (
                round(distance_delta_pct, 2) if distance_delta_pct is not None else None
            ),
            "geometry_sha256": geometry_sha256,
        },
        "provenance": {
            "fallback_chain": fallback_chain,
            "parts": [
                {
                    **asdict(part),
                    "points_wgs84": None,
                    "retained_point_count": len(part.points_wgs84),
                }
                for part in parts
            ],
            "joins": [asdict(join) for join in joins],
        },
        "review": {
            "status": review_status,
            "warnings": warnings,
            "use_boundary": (
                "manual_freehand_candidate_needs_review"
                if review_status != "human_reviewed"
                else "human_reviewed_manual_freehand_geometry"
            ),
        },
    }


def compose_geometry_parts(
    parts: list[GeometryPart],
    *,
    max_join_gap_m: float = DEFAULT_MAX_JOIN_GAP_M,
    snap_join_within_m: float = DEFAULT_SNAP_JOIN_WITHIN_M,
) -> tuple[tuple[tuple[float, float], ...], tuple[GeometryJoin, ...]]:
    if not parts:
        raise ManualGeometryPatchError("至少需要一个几何部件")
    output: list[tuple[float, float]] = list(parts[0].points_wgs84)
    joins: list[GeometryJoin] = []
    for previous, current in zip(parts, parts[1:]):
        gap_m = _distance(output[-1], current.points_wgs84[0])
        if gap_m > max_join_gap_m:
            raise ManualGeometryPatchError(
                f"{previous.part_id}->{current.part_id} 端点相差 {gap_m:.1f}m，"
                f"超过 {max_join_gap_m:.1f}m，不允许隐式补直线"
            )
        if gap_m <= snap_join_within_m:
            action = "snap_to_previous_endpoint"
            current_points = (output[-1], *current.points_wgs84[1:])
        else:
            action = "explicit_straight_join"
            current_points = current.points_wgs84
        joins.append(
            GeometryJoin(
                from_part_id=previous.part_id,
                to_part_id=current.part_id,
                gap_m=round(gap_m, 2),
                action=action,
            )
        )
        for point in current_points:
            if _distance(output[-1], point) >= 0.05:
                output.append(point)
    if len(output) > MAX_OUTPUT_POINTS:
        raise ManualGeometryPatchError(
            f"拼接后有 {len(output)} 个点，超过 {MAX_OUTPUT_POINTS} 上限"
        )
    return tuple(output), tuple(joins)


def write_candidate_files(candidate: dict[str, Any], *, json_path: Path, gpx_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    gpx_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    points = candidate["geometry"]["points_wgs84"]
    name = _xml_escape(candidate["identity"]["source_segment_name"])
    track_points = "\n".join(
        f'      <trkpt lat="{lat:.8f}" lon="{lon:.8f}" />'
        for lon, lat in points
    )
    gpx_path.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<gpx version="1.1" creator="VELO manual geometry patch" '
                'xmlns="http://www.topografix.com/GPX/1/1">',
                "  <trk>",
                f"    <name>{name}</name>",
                "    <trkseg>",
                track_points,
                "    </trkseg>",
                "  </trk>",
                "</gpx>",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _load_part(payload: Any, *, manifest_dir: Path) -> GeometryPart:
    if not isinstance(payload, dict):
        raise ManualGeometryPatchError("parts 中的每一项必须是对象")
    part_id = str(payload.get("part_id") or "").strip()
    source_type = str(payload.get("source_type") or "").strip()
    source_name = str(payload.get("source_name") or part_id).strip()
    review_status = str(payload.get("review_status") or "needs_review").strip()
    if not part_id or not source_name:
        raise ManualGeometryPatchError("part_id/source_name 不能为空")
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ManualGeometryPatchError(f"{part_id} source_type 不支持")
    if review_status not in ALLOWED_REVIEW_STATUSES:
        raise ManualGeometryPatchError(f"{part_id} review_status 不支持")

    source_pointer = "inline"
    source_hash = None
    source_material_point_count = 0
    if "source_path" in payload:
        source_path = (manifest_dir / str(payload["source_path"])).resolve()
        try:
            source_bytes = source_path.read_bytes()
            source_data = json.loads(source_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ManualGeometryPatchError(f"{part_id} source_path 无法读取：{exc}") from exc
        source_pointer = str(source_path)
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        source_material_point_count = _source_material_point_count(
            source_data,
            source_type=source_type,
            source_segment_id=str(payload.get("source_segment_id") or "").strip() or None,
        )
        raw_points = _points_from_source(
            source_data,
            source_type=source_type,
            source_segment_id=str(payload.get("source_segment_id") or "").strip() or None,
        )
    else:
        source_material_point_count = len(payload.get("points_wgs84") or [])
        raw_points = _normalize_lonlat_points(payload.get("points_wgs84"), label=part_id)

    normalized_source_point_count = len(raw_points)
    start_index = int(payload.get("source_start_index", 0))
    end_index = int(payload.get("source_end_index", normalized_source_point_count - 1))
    if start_index < 0 or end_index >= normalized_source_point_count or start_index >= end_index:
        raise ManualGeometryPatchError(f"{part_id} 的 source_start_index/source_end_index 无效")
    selected = raw_points[start_index : end_index + 1]
    if payload.get("reverse") is True:
        selected = list(reversed(selected))

    max_source_gap_m = _max_consecutive_gap_m(selected)
    default_allowed_source_gap_m = (
        MAX_STRAIGHT_CONNECTOR_M
        if source_type == "manual_straight_connector"
        else DEFAULT_MAX_SOURCE_GAP_M
    )
    allowed_source_gap_m = _positive_float(
        payload.get("max_source_gap_m", default_allowed_source_gap_m),
        f"{part_id}.max_source_gap_m",
    )
    if (
        source_type != "manual_straight_connector"
        and max_source_gap_m > allowed_source_gap_m
    ):
        raise ManualGeometryPatchError(
            f"{part_id} 来源轨迹最大相邻点间距 {max_source_gap_m:.1f}m，超过 "
            f"{allowed_source_gap_m:.1f}m，不能自动手绘跨过缺口"
        )

    tolerance_value = payload.get("simplify_tolerance_m", 0.0)
    if tolerance_value == "auto":
        simplify_mode = "auto_fit_freehand_budget"
        max_error_m = _positive_float(
            payload.get(
                "max_simplify_error_m",
                DEFAULT_MAX_AUTO_SIMPLIFY_ERROR_M,
            ),
            f"{part_id}.max_simplify_error_m",
        )
        simplified, tolerance_m = simplify_polyline_to_budget(
            selected,
            max_points=MAX_RAW_POINTS,
            max_error_m=max_error_m,
        )
    else:
        simplify_mode = "fixed_tolerance"
        tolerance_m = _positive_float(
            tolerance_value,
            f"{part_id}.simplify_tolerance_m",
            allow_zero=True,
        )
        simplified = simplify_polyline(selected, tolerance_m=tolerance_m)
    if source_type == "manual_straight_connector":
        connector_distance = _polyline_distance_m(simplified)
        if len(simplified) != 2:
            raise ManualGeometryPatchError(
                f"{part_id} manual_straight_connector 必须恰好两个点"
            )
        if connector_distance > MAX_STRAIGHT_CONNECTOR_M:
            raise ManualGeometryPatchError(
                f"{part_id} 直线连接长 {connector_distance:.1f}m，超过 "
                f"{MAX_STRAIGHT_CONNECTOR_M:.0f}m 上限"
            )

    try:
        preview = build_snap_preview(
            mode="freehand",
            coordinate_system="wgs84",
            points=simplified,
        )
    except ValueError as exc:
        raise ManualGeometryPatchError(
            f"{part_id} 未通过 Route Draw freehand 校验：{exc}"
        ) from exc
    preview_points = tuple(
        (float(point[0]), float(point[1]))
        for point in preview["snapped_points"]
    )
    return GeometryPart(
        part_id=part_id,
        source_type=source_type,
        source_name=source_name,
        source_pointer=source_pointer,
        source_content_sha256=source_hash,
        review_status=review_status,
        points_wgs84=preview_points,
        source_material_point_count=source_material_point_count,
        normalized_source_point_count=normalized_source_point_count,
        source_point_count=len(selected),
        source_start_index=start_index,
        source_end_index=end_index,
        simplify_mode=simplify_mode,
        simplify_tolerance_m=tolerance_m,
        max_source_deviation_m=round(
            _max_point_to_polyline_distance_m(selected, list(preview_points)),
            2,
        ),
        max_source_gap_m=round(max_source_gap_m, 2),
        max_output_gap_m=round(_max_consecutive_gap_m(list(preview_points)), 2),
        distance_m=round(float(preview["distance_m"]), 1),
    )


def _points_from_source(
    payload: Any,
    *,
    source_type: str,
    source_segment_id: str | None,
) -> list[tuple[float, float]]:
    if not isinstance(payload, dict):
        raise ManualGeometryPatchError("来源文件必须是 JSON 对象")
    if source_type == "strava_page_stream":
        streams = payload.get("streams")
        if not isinstance(streams, dict):
            raise ManualGeometryPatchError("Strava 来源缺少 streams")
        locations = streams.get("location")
        if not isinstance(locations, list):
            raise ManualGeometryPatchError("Strava 来源缺少 streams.location")
        return _normalize_latlon_points(locations, label="streams.location")
    if source_type == "strava_simplified_shape":
        records = payload.get("records")
        if not isinstance(records, list) or not source_segment_id:
            raise ManualGeometryPatchError(
                "Strava 抽稀来源需要 records 和 source_segment_id"
            )
        matches = [
            record
            for record in records
            if isinstance(record, dict)
            and str(record.get("source_segment_id")) == source_segment_id
        ]
        if len(matches) != 1:
            raise ManualGeometryPatchError(
                f"Strava 抽稀来源中 source_segment_id={source_segment_id} 不唯一"
            )
        return _normalize_mixed_wgs84_points(
            matches[0].get("points_wgs84"),
            label="records.points_wgs84",
        )
    points = payload.get("points_wgs84")
    if points is None and isinstance(payload.get("geometry"), dict):
        points = payload["geometry"].get("points_wgs84")
    return _normalize_mixed_wgs84_points(points, label="points_wgs84")


def _source_material_point_count(
    payload: Any,
    *,
    source_type: str,
    source_segment_id: str | None,
) -> int:
    if not isinstance(payload, dict):
        return 0
    if source_type == "strava_page_stream":
        streams = payload.get("streams")
        locations = streams.get("location") if isinstance(streams, dict) else None
        return len(locations) if isinstance(locations, list) else 0
    if source_type == "strava_simplified_shape":
        records = payload.get("records")
        if not isinstance(records, list) or not source_segment_id:
            return 0
        for record in records:
            if isinstance(record, dict) and str(record.get("source_segment_id")) == source_segment_id:
                count = record.get("source_stream_point_count")
                return int(count) if isinstance(count, int) and count >= 0 else 0
        return 0
    points = payload.get("points_wgs84")
    if points is None and isinstance(payload.get("geometry"), dict):
        points = payload["geometry"].get("points_wgs84")
    return len(points) if isinstance(points, list) else 0


def simplify_polyline(
    points: list[tuple[float, float]],
    *,
    tolerance_m: float,
) -> list[tuple[float, float]]:
    if len(points) < 2:
        raise ManualGeometryPatchError("几何部件至少需要两个点")
    if tolerance_m <= 0 or len(points) == 2:
        return list(points)
    kept = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        start, end = pending.pop()
        max_distance = -1.0
        max_index = start
        for index in range(start + 1, end):
            distance = _point_to_segment_distance_m(points[index], points[start], points[end])
            if distance > max_distance:
                max_distance = distance
                max_index = index
        if max_distance > tolerance_m:
            kept.add(max_index)
            pending.append((start, max_index))
            pending.append((max_index, end))
    return [points[index] for index in sorted(kept)]


def simplify_polyline_to_budget(
    points: list[tuple[float, float]],
    *,
    max_points: int,
    max_error_m: float,
) -> tuple[list[tuple[float, float]], float]:
    """在 freehand 点数预算内选择误差最小的 RDP 阈值。"""
    if max_points < 2:
        raise ManualGeometryPatchError("max_points 至少为 2")
    if len(points) <= max_points:
        return list(points), 0.0

    highest = simplify_polyline(points, tolerance_m=max_error_m)
    if len(highest) > max_points:
        raise ManualGeometryPatchError(
            f"来源轨迹在 {max_error_m:.1f}m 最大误差内仍需 {len(highest)} 个点，"
            f"超过 freehand 单次 {max_points} 点上限；请分段描绘或人工处理"
        )

    low = 0.0
    high = max_error_m
    selected = highest
    for _ in range(AUTO_SIMPLIFY_SEARCH_STEPS):
        middle = (low + high) / 2.0
        candidate = simplify_polyline(points, tolerance_m=middle)
        if len(candidate) <= max_points:
            high = middle
            selected = candidate
        else:
            low = middle
    actual_error_m = _max_point_to_polyline_distance_m(points, selected)
    if actual_error_m > max_error_m + 0.01:
        raise ManualGeometryPatchError(
            f"自动抽稀误差 {actual_error_m:.2f}m 超过 {max_error_m:.2f}m"
        )
    return selected, round(high, 4)


def _max_point_to_polyline_distance_m(
    source: list[tuple[float, float]],
    candidate: list[tuple[float, float]],
) -> float:
    if len(candidate) < 2:
        return math.inf
    return max(
        min(
            _point_to_segment_distance_m(point, start, end)
            for start, end in zip(candidate, candidate[1:])
        )
        for point in source
    )


def _point_to_segment_distance_m(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    origin_lon, origin_lat = start
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(origin_lat))
    px = (point[0] - origin_lon) * lon_scale
    py = (point[1] - origin_lat) * lat_scale
    ex = (end[0] - origin_lon) * lon_scale
    ey = (end[1] - origin_lat) * lat_scale
    denominator = ex * ex + ey * ey
    if denominator == 0:
        return math.hypot(px, py)
    ratio = max(0.0, min(1.0, (px * ex + py * ey) / denominator))
    return math.hypot(px - ratio * ex, py - ratio * ey)


def _normalize_latlon_points(points: Any, *, label: str) -> list[tuple[float, float]]:
    if not isinstance(points, list):
        raise ManualGeometryPatchError(f"{label} 必须是数组")
    lonlat: list[list[Any]] = []
    for index, point in enumerate(points):
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ManualGeometryPatchError(f"{label} 第 {index + 1} 个点无效")
        lonlat.append([point[1], point[0]])
    return _normalize_lonlat_points(lonlat, label=label)


def _normalize_mixed_wgs84_points(points: Any, *, label: str) -> list[tuple[float, float]]:
    if not isinstance(points, list):
        raise ManualGeometryPatchError(f"{label} 必须是数组")
    normalized: list[list[float]] = []
    for point in points:
        if isinstance(point, dict):
            normalized.append([point.get("lon"), point.get("lat")])
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            normalized.append([point[0], point[1]])
        else:
            raise ManualGeometryPatchError(f"{label} 包含无效坐标点")
    return _normalize_lonlat_points(normalized, label=label)


def _normalize_lonlat_points(points: Any, *, label: str) -> list[tuple[float, float]]:
    if not isinstance(points, list) or len(points) < 2:
        raise ManualGeometryPatchError(f"{label} 至少需要两个点")
    normalized: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ManualGeometryPatchError(f"{label} 第 {index + 1} 个点无效")
        try:
            lon = float(point[0])
            lat = float(point[1])
        except (TypeError, ValueError) as exc:
            raise ManualGeometryPatchError(f"{label} 第 {index + 1} 个点不是数字") from exc
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ManualGeometryPatchError(f"{label} 第 {index + 1} 个点不是有限数")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ManualGeometryPatchError(f"{label} 第 {index + 1} 个点越界")
        if not normalized or _distance(normalized[-1], (lon, lat)) >= 0.05:
            normalized.append((lon, lat))
    if len(normalized) < 2:
        raise ManualGeometryPatchError(f"{label} 去重后不足两个点")
    return normalized


def _candidate_review_status(parts: list[GeometryPart], joins: tuple[GeometryJoin, ...]) -> str:
    if all(part.review_status == "human_reviewed" for part in parts) and all(
        join.action == "snap_to_previous_endpoint" for join in joins
    ):
        return "human_reviewed"
    if all(part.review_status in {"source_shape", "human_reviewed"} for part in parts) and not any(
        join.action == "explicit_straight_join" for join in joins
    ):
        return "source_shape"
    return "needs_review"


def _validate_fallback_chain(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, list) or len(payload) != len(REQUIRED_FALLBACK_STAGES):
        raise ManualGeometryPatchError(
            "fallback_chain 必须依次记录腾讯、OSM、freehand 三个阶段"
        )
    normalized: list[dict[str, str]] = []
    for index, expected_stage in enumerate(REQUIRED_FALLBACK_STAGES):
        item = payload[index]
        if not isinstance(item, dict) or item.get("stage") != expected_stage:
            raise ManualGeometryPatchError(
                "fallback_chain 顺序必须是 tencent -> osm -> freehand"
            )
        outcome = str(item.get("outcome") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        expected_outcome = "selected" if expected_stage == "freehand" else "rejected"
        if outcome != expected_outcome:
            raise ManualGeometryPatchError(
                f"fallback_chain.{expected_stage}.outcome 必须为 {expected_outcome}"
            )
        if not evidence:
            raise ManualGeometryPatchError(
                f"fallback_chain.{expected_stage} 必须记录 evidence"
            )
        normalized.append(
            {"stage": expected_stage, "outcome": outcome, "evidence": evidence}
        )
    return normalized


def _max_consecutive_gap_m(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return max(_distance(start, end) for start, end in zip(points, points[1:]))


def _polyline_distance_m(points: Any) -> float:
    return sum(_distance(start, end) for start, end in zip(points, points[1:]))


def _distance(start: tuple[float, float], end: tuple[float, float]) -> float:
    return haversine(start[1], start[0], end[1], end[0])


def _positive_float(value: Any, label: str, *, allow_zero: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ManualGeometryPatchError(f"{label} 必须是数字") from exc
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        qualifier = "大于等于 0" if allow_zero else "大于 0"
        raise ManualGeometryPatchError(f"{label} 必须{qualifier}")
    return number


def _optional_positive_float(value: Any) -> float | None:
    if value is None:
        return None
    return _positive_float(value, "segment.observed_distance_m")


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
