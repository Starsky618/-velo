"""标准赛段几何变化后的路线认知失效与来源登记 hook。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.route_cognition.models import (
    CollectionSegment,
    RouteCognitionSegment,
    RouteSegment,
    SegmentConceptCandidate,
    SegmentConceptLink,
    SegmentGeometrySource,
)
from app.segment.models import SegmentGeometryRevision


def record_geometry_change(
    db: Session,
    *,
    revision: SegmentGeometryRevision,
    matched_efforts: int,
) -> SegmentGeometrySource:
    """登记腾讯驾车重建来源，并暂停仍绑定旧 hash 的认知白名单。

    不把旧 hash 偷换成新 hash：路线成员、合集和概念关系都需要重新审核。
    旧关系继续作为历史证据存在，但 suspended segment 不能再被 writer 消费。
    """
    old_sources = (
        db.query(SegmentGeometrySource)
        .filter(
            SegmentGeometrySource.segment_id == revision.segment_id,
            SegmentGeometrySource.geometry_hash == revision.previous_geometry_hash,
            SegmentGeometrySource.quality_status != "rejected",
        )
        .all()
    )
    for source in old_sources:
        source.quality_status = "deprecated"

    quality_metrics = {
        "revision_id": revision.id,
        "routing_provider": revision.routing_provider,
        "routing_mode": revision.routing_mode,
        "matched_efforts": matched_efforts,
        "source_segment_id": revision.source_segment_id,
        "source_distance_m": revision.source_distance_m,
        "source_observation_id": revision.source_observation_id,
        "routing_candidate_id": revision.routing_candidate_id,
        "candidate_payload_hash": revision.candidate_payload_hash,
        "validation_version": revision.validation_version,
        "validation_metrics": (
            json.loads(revision.validation_metrics_json)
            if revision.validation_metrics_json
            else None
        ),
    }

    source = (
        db.query(SegmentGeometrySource)
        .filter(
            SegmentGeometrySource.segment_id == revision.segment_id,
            SegmentGeometrySource.geometry_hash == revision.candidate_geometry_hash,
            SegmentGeometrySource.source_url == revision.source_url,
        )
        .first()
    )
    if source is None:
        source = SegmentGeometrySource(
            segment_id=revision.segment_id,
            source_type="map_reconstruction",
            source_url=revision.source_url,
            original_coordinate_system=revision.original_coordinate_system,
            geometry_hash=revision.candidate_geometry_hash,
            normalization_version=revision.normalization_version,
            quality_status="verified",
            quality_metrics_json=quality_metrics,
            created_by=revision.created_by,
        )
        db.add(source)
    else:
        source.quality_status = "verified"
        source.quality_metrics_json = quality_metrics

    cognition = (
        db.query(RouteCognitionSegment)
        .filter(RouteCognitionSegment.segment_id == revision.segment_id)
        .first()
    )
    if cognition is not None and cognition.geometry_hash != revision.candidate_geometry_hash:
        cognition.eligibility_status = "suspended"
        note = f"标准几何 revision {revision.id} 已激活，旧 hash 等待重新审核"
        cognition.review_note = f"{cognition.review_note}\n{note}" if cognition.review_note else note

        # 旧派生关系仍保留其原始 hash 和人工判断作为历史证据，但从所有 active
        # 消费面撤下；重新审核新线后必须逐条重建，不能把旧判断偷换到新几何。
        db.query(RouteSegment).filter(
            RouteSegment.segment_id == revision.segment_id,
            RouteSegment.membership_status == "active",
        ).update({RouteSegment.membership_status: "deprecated"}, synchronize_session=False)
        db.query(CollectionSegment).filter(
            CollectionSegment.segment_id == revision.segment_id,
            CollectionSegment.membership_status == "active",
        ).update({CollectionSegment.membership_status: "deprecated"}, synchronize_session=False)
        db.query(SegmentConceptLink).filter(
            SegmentConceptLink.segment_id == revision.segment_id,
            SegmentConceptLink.link_status == "active",
        ).update({SegmentConceptLink.link_status: "deprecated"}, synchronize_session=False)
        db.query(SegmentConceptCandidate).filter(
            SegmentConceptCandidate.segment_id == revision.segment_id,
            SegmentConceptCandidate.candidate_status.in_(("proposed", "needs_review")),
        ).update(
            {
                SegmentConceptCandidate.candidate_status: "stale",
                SegmentConceptCandidate.latest_confidence_state: "stale",
            },
            synchronize_session=False,
        )

    db.flush()
    return source
