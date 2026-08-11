#!/usr/bin/env python3
"""预检或原子修正两条已看图确认的太原赛段标准线。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from geoalchemy2 import WKTElement
from sqlalchemy import func, text


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 独立脚本必须注册本次写入链涉及的 ORM 表。
from app.activity.models import Activity  # noqa: E402,F401
from app.database import SessionLocal  # noqa: E402
from app.route_book.models import RouteBook, RouteVersion  # noqa: E402,F401
from app.route_cognition.geometry_hash import (  # noqa: E402
    SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
    hash_segment_geometry_wkt,
)
from app.route_cognition.models import (  # noqa: E402
    CollectionSegment,
    JudgmentRun,
    RouteCognitionSegment,
    RouteSegment,
    SegmentConceptLink,
    SegmentGeometrySource,
)
from app.elevation.route_elevation import ROUTE_ELEVATION_METHOD  # noqa: E402
from app.segment.geometry_rebuild import PreparedSegmentGeometry, prepare_segment_geometry  # noqa: E402
from app.segment.models import Segment, SegmentEffort, SegmentGeometryRevision  # noqa: E402
from app.segment.reviewed_boundary_corrections import (  # noqa: E402
    CORRECTION_SPECS,
    BoundaryCorrectionCandidate,
    build_boundary_correction_candidate,
    polyline_distance_m,
)
from app.strava.client import StravaClient  # noqa: E402
from app.user.models import User  # noqa: E402


TARGET_SEGMENT_IDS = (30, 39)


class ReviewedTaiyuanRepairError(RuntimeError):
    """生产现状与已确认纠偏前提不一致。"""


@dataclass(frozen=True)
class PreparedCorrection:
    candidate: BoundaryCorrectionCandidate
    prepared: PreparedSegmentGeometry


def _load_source_candidates(source_user_id: int) -> dict[int, BoundaryCorrectionCandidate]:
    db = SessionLocal()
    try:
        user = db.get(User, source_user_id)
        if user is None or user.strava_refresh_token is None:
            raise ReviewedTaiyuanRepairError("指定用户没有可用的 Strava 绑定")
        client = StravaClient(db, user)
        return {
            segment_id: build_boundary_correction_candidate(
                segment_id,
                client.get_segment_detail(CORRECTION_SPECS[segment_id].source_segment_id),
            )
            for segment_id in TARGET_SEGMENT_IDS
        }
    finally:
        db.close()


def _prepare_corrections(
    candidates: dict[int, BoundaryCorrectionCandidate],
) -> dict[int, PreparedCorrection]:
    prepared: dict[int, PreparedCorrection] = {}
    for segment_id, candidate in candidates.items():
        candidate_distance_m = polyline_distance_m(candidate.points)
        geometry = prepare_segment_geometry(
            [{"lat": lat, "lon": lon} for lat, lon in candidate.points],
            coordinate_system="wgs84",
            # 已确认的候选线可能有意裁掉 Strava 原线中的折返。这里仅让现有函数
            # 校验折线自洽；外部来源距离仍单独保存在 candidate.metrics 中。
            source_distance_m=candidate_distance_m,
        )
        prepared[segment_id] = PreparedCorrection(candidate=candidate, prepared=geometry)
    return prepared


def _active_relation_counts(db, segment_id: int) -> dict[str, int]:
    return {
        "route_links": db.query(RouteSegment.id).filter(
            RouteSegment.segment_id == segment_id,
            RouteSegment.membership_status == "active",
        ).count(),
        "collection_links": db.query(CollectionSegment.id).filter(
            CollectionSegment.segment_id == segment_id,
            CollectionSegment.membership_status == "active",
        ).count(),
        "concept_links": db.query(SegmentConceptLink.id).filter(
            SegmentConceptLink.segment_id == segment_id,
            SegmentConceptLink.link_status == "active",
        ).count(),
    }


def _preflight_locked_segment(db, segment_id: int) -> tuple[Segment, str, RouteCognitionSegment]:
    row = (
        db.query(Segment, func.ST_AsText(Segment.reference_line).label("reference_line_wkt"))
        .filter(Segment.id == segment_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if row is None:
        raise ReviewedTaiyuanRepairError(f"segment {segment_id} 不存在")
    segment, current_wkt = row
    spec = CORRECTION_SPECS[segment_id]
    if segment.name != spec.segment_name:
        raise ReviewedTaiyuanRepairError(f"segment {segment_id} 名称已变化")
    effort_count = db.query(SegmentEffort.id).filter_by(segment_id=segment_id).count()
    if effort_count:
        raise ReviewedTaiyuanRepairError(
            f"segment {segment_id} 出现 {effort_count} 条 VELO 成绩，停止直接纠偏"
        )
    pending_revision = db.query(SegmentGeometryRevision.id).filter(
        SegmentGeometryRevision.segment_id == segment_id,
        SegmentGeometryRevision.status.in_(("staged", "processing")),
    ).first()
    if pending_revision is not None:
        raise ReviewedTaiyuanRepairError(f"segment {segment_id} 有正在处理的几何 revision")
    relation_counts = _active_relation_counts(db, segment_id)
    if any(relation_counts.values()):
        raise ReviewedTaiyuanRepairError(
            f"segment {segment_id} 已有 active 路线关系，停止直接纠偏：{relation_counts}"
        )
    cognition = db.get(RouteCognitionSegment, segment_id)
    if cognition is None:
        raise ReviewedTaiyuanRepairError(f"segment {segment_id} 缺少路线认知白名单记录")
    return segment, current_wkt, cognition


def _canonical_wkt(db, value: str) -> str:
    if db.bind.dialect.name != "postgresql":
        return value
    return db.execute(
        text("SELECT ST_AsText(ST_GeomFromText(:value, 4326))"),
        {"value": value},
    ).scalar_one()


def _apply_one(
    db,
    *,
    correction: PreparedCorrection,
    reviewer_user_id: int,
    reviewed_at: datetime,
) -> dict:
    segment_id = correction.candidate.spec.segment_id
    segment, current_wkt, cognition = _preflight_locked_segment(db, segment_id)
    candidate_wkt = _canonical_wkt(db, correction.prepared.reference_line_wkt)
    current_geometry_id = hash_segment_geometry_wkt(current_wkt)
    candidate_geometry_id = hash_segment_geometry_wkt(candidate_wkt)
    if current_geometry_id == candidate_geometry_id:
        raise ReviewedTaiyuanRepairError(f"segment {segment_id} 已经是候选几何")
    if cognition.geometry_hash != current_geometry_id:
        raise ReviewedTaiyuanRepairError(
            f"segment {segment_id} 的路线认知几何与当前标准线不一致"
        )
    old_distance_m = float(segment.distance or 0.0)

    old_sources = db.query(SegmentGeometrySource).filter(
        SegmentGeometrySource.segment_id == segment_id,
        SegmentGeometrySource.geometry_hash == current_geometry_id,
        SegmentGeometrySource.quality_status != "rejected",
    ).all()
    for source in old_sources:
        source.quality_status = "deprecated"

    source_url = f"https://www.strava.com/segments/{correction.candidate.spec.source_segment_id}"
    source = SegmentGeometrySource(
        segment_id=segment_id,
        source_type="map_reconstruction",
        source_url=source_url,
        original_coordinate_system="wgs84",
        geometry_hash=candidate_geometry_id,
        normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        quality_status="verified",
        quality_metrics_json={
            **correction.candidate.metrics,
            "elevation_method": ROUTE_ELEVATION_METHOD,
        },
        created_by=reviewer_user_id,
    )
    db.add(source)
    db.flush()

    judgment = JudgmentRun(
        run_type="human_review",
        status="succeeded",
        trigger_type="taiyuan_segment_geometry_correction",
        segment_id=segment_id,
        engine_name="reviewed_route_geometry",
        engine_version="v1",
        confidence=1.0,
        confidence_method="human_map_review",
        confidence_state="human_accepted",
        result_summary_json=correction.candidate.metrics,
        created_by_user_id=reviewer_user_id,
        created_by_service="repair_reviewed_taiyuan_segments",
        started_at=reviewed_at,
        finished_at=reviewed_at,
    )
    db.add(judgment)
    db.flush()

    prepared = correction.prepared
    segment.reference_line = WKTElement(candidate_wkt, srid=4326)
    segment.distance = prepared.distance
    segment.elevation_gain = prepared.elevation_gain
    segment.elevation_loss = prepared.elevation_loss
    segment.avg_gradient = prepared.avg_gradient
    segment.elevation_profile = prepared.elevation_profile_json
    segment.max_gradient = prepared.max_gradient
    segment.difficulty = prepared.difficulty
    segment.city = prepared.city
    segment.start_lat = prepared.start_lat
    segment.start_lon = prepared.start_lon
    segment.end_lat = prepared.end_lat
    segment.end_lon = prepared.end_lon

    cognition.primary_geometry_source_id = source.id
    cognition.review_basis = "provenance_verified"
    cognition.eligibility_status = "active"
    cognition.geometry_hash = candidate_geometry_id
    cognition.normalization_version = SEGMENT_GEOMETRY_NORMALIZATION_VERSION
    cognition.accepted_judgment_run_id = judgment.id
    cognition.reviewed_by = reviewer_user_id
    cognition.reviewed_at = reviewed_at
    note = "2026-08-11 按 Strava 原轨迹与骑手看图决定修正标准线"
    cognition.review_note = f"{cognition.review_note}\n{note}" if cognition.review_note else note

    return {
        "segment_id": segment_id,
        "name": segment.name,
        "old_distance_m": round(old_distance_m, 1),
        "new_distance_m": round(prepared.distance, 1),
        "elevation_gain_m": round(prepared.elevation_gain, 1),
        "elevation_loss_m": round(prepared.elevation_loss, 1),
        "start": [round(prepared.start_lat, 6), round(prepared.start_lon, 6)],
        "end": [round(prepared.end_lat, 6), round(prepared.end_lon, 6)],
        "operation": correction.candidate.metrics["operation"],
    }


def _preview(db, corrections: dict[int, PreparedCorrection]) -> list[dict]:
    results = []
    for segment_id in TARGET_SEGMENT_IDS:
        segment, _current_wkt, _cognition = _preflight_locked_segment(db, segment_id)
        prepared = corrections[segment_id].prepared
        results.append(
            {
                "segment_id": segment_id,
                "name": segment.name,
                "old_distance_m": round(float(segment.distance), 1),
                "new_distance_m": round(prepared.distance, 1),
                "elevation_gain_m": round(prepared.elevation_gain, 1),
                "elevation_loss_m": round(prepared.elevation_loss, 1),
                "start": [round(prepared.start_lat, 6), round(prepared.start_lon, 6)],
                "end": [round(prepared.end_lat, 6), round(prepared.end_lon, 6)],
                **corrections[segment_id].candidate.metrics,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-user-id", type=int, required=True)
    parser.add_argument("--reviewer-user-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.source_user_id <= 0 or args.reviewer_user_id <= 0:
        parser.error("user id 必须是正整数")

    candidates = _load_source_candidates(args.source_user_id)
    corrections = _prepare_corrections(candidates)
    db = SessionLocal()
    try:
        reviewer = db.get(User, args.reviewer_user_id)
        if reviewer is None:
            raise ReviewedTaiyuanRepairError("reviewer 用户不存在")
        if not args.apply:
            items = _preview(db, corrections)
            db.rollback()
            print(json.dumps({"status": "preflight_passed", "items": items}, ensure_ascii=False))
            return 0

        reviewed_at = datetime.now(timezone.utc)
        items = [
            _apply_one(
                db,
                correction=corrections[segment_id],
                reviewer_user_id=args.reviewer_user_id,
                reviewed_at=reviewed_at,
            )
            for segment_id in TARGET_SEGMENT_IDS
        ]
        db.commit()
        print(json.dumps({"status": "committed", "items": items}, ensure_ascii=False))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
