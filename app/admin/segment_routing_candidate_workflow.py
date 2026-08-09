"""服务端腾讯 driving 候选生成；请求方只能选控制点，不能上传结果折线。"""

from __future__ import annotations

import json
import math

from sqlalchemy.orm import Session

from app.route_book.tencent_direction import plan_tencent_driving_route
from app.segment._geo_utils import _haversine
from app.segment.coord_convert import convert_points_to_wgs84, wgs84_to_gcj02
from app.segment.models import Segment, SegmentRoutingCandidate
from app.segment.routing_candidates import routing_candidate_record_hash
from app.common.geometry_hash import stable_line_hash


class SegmentRoutingCandidateError(ValueError):
    """控制点或腾讯 driving 结果无法形成可信候选。"""


MAX_ROUTING_LEG_JUNCTION_GAP_M = 2.0


def create_segment_routing_candidate(
    db: Session,
    *,
    segment_id: int,
    control_points: list[dict],
    coordinate_system: str,
    admin_id: int,
) -> SegmentRoutingCandidate:
    if db.get(Segment, segment_id) is None:
        raise SegmentRoutingCandidateError("赛段不存在")
    if coordinate_system not in {"gcj02", "wgs84"}:
        raise SegmentRoutingCandidateError("控制点坐标系不受支持")

    gcj02_points = []
    for point in control_points:
        lat = float(point["lat"])
        lon = float(point["lon"])
        if coordinate_system == "wgs84":
            lat, lon = wgs84_to_gcj02(lat, lon)
        gcj02_points.append({"lat": lat, "lon": lon})

    route_points_gcj02: list[dict] = []
    provider_distance_m = 0.0
    for index in range(1, len(gcj02_points)):
        start = gcj02_points[index - 1]
        end = gcj02_points[index]
        planned = plan_tencent_driving_route(
            (start["lat"], start["lon"]),
            (end["lat"], end["lon"]),
        )
        leg_distance = float(planned.get("distance") or 0.0)
        leg_points = planned.get("points") or []
        if not math.isfinite(leg_distance) or leg_distance <= 0 or len(leg_points) < 2:
            raise SegmentRoutingCandidateError("腾讯 driving 返回的分段路线无效")
        provider_distance_m += leg_distance
        if route_points_gcj02 and leg_points:
            first = leg_points[0]
            previous = route_points_gcj02[-1]
            junction_gap_m = _haversine(
                float(previous["lat"]),
                float(previous["lon"]),
                float(first["lat"]),
                float(first["lon"]),
            )
            if junction_gap_m > MAX_ROUTING_LEG_JUNCTION_GAP_M:
                raise SegmentRoutingCandidateError(
                    "腾讯 driving 分段路线在控制点处不连续，拒绝拼接人工直线"
                )
            # 两腿都包含控制点。小于 2m 的 snapping 差只保留上一腿末点，避免
            # WKT 中出现一条腾讯从未返回的“末点 -> 下一腿首点”人工连接线。
            leg_points = leg_points[1:]
        route_points_gcj02.extend(leg_points)

    route_points_wgs84 = convert_points_to_wgs84(route_points_gcj02, "gcj02")
    if len(route_points_wgs84) < 3:
        raise SegmentRoutingCandidateError("腾讯 driving 完整折线点数不足")
    measured_distance_m = sum(
        _haversine(
            route_points_wgs84[index - 1]["lat"],
            route_points_wgs84[index - 1]["lon"],
            route_points_wgs84[index]["lat"],
            route_points_wgs84[index]["lon"],
        )
        for index in range(1, len(route_points_wgs84))
    )
    if not math.isfinite(measured_distance_m) or measured_distance_m <= 0:
        raise SegmentRoutingCandidateError("腾讯 driving 折线实测距离无效")
    reference_line_wkt = "LINESTRING(" + ",".join(
        f"{point['lon']} {point['lat']}" for point in route_points_wgs84
    ) + ")"
    geometry_hash = stable_line_hash(reference_line_wkt)
    control_points_json = json.dumps(
        gcj02_points,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    candidate = SegmentRoutingCandidate(
        segment_id=segment_id,
        status="ready",
        routing_provider="tencent",
        routing_mode="driving",
        control_points_json=control_points_json,
        reference_line_wkt=reference_line_wkt,
        geometry_hash=geometry_hash,
        provider_distance_m=provider_distance_m,
        measured_distance_m=measured_distance_m,
        record_hash="pending",
        created_by=admin_id,
    )
    candidate.record_hash = routing_candidate_record_hash(candidate)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate
