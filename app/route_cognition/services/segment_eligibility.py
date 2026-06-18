"""Segment 准入服务——唯一安全入口，把审过的正式 segment 放进路线认知白名单。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.route_cognition.geometry_hash import (
    SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
    hash_segment_geometry_wkt,
)
from app.route_cognition.models import JudgmentRun, RouteCognitionSegment, SegmentGeometrySource
from app.segment.models import Segment


ACCEPTED_JUDGMENT_STATES = {"human_accepted", "stable"}
VERIFIED_SOURCE_STATUS = "verified"
ALLOWED_COORDINATE_SYSTEMS = {"wgs84", "gcj02", "unknown"}


class SegmentEligibilityError(ValueError):
    """Segment 准入失败——调用方应把错误展示给内部审核者，而不是绕过 service 写 SQL。"""


@dataclass(frozen=True)
class SegmentGeometrySourceInput:
    """同事务创建几何来源时使用的输入包。"""

    source_type: str
    geometry_hash: str
    normalization_version: str
    quality_status: str = VERIFIED_SOURCE_STATUS
    source_activity_id: int | None = None
    source_file_id: str | None = None
    source_url: str | None = None
    source_start_index: int | None = None
    source_end_index: int | None = None
    source_start_time: datetime | None = None
    source_end_time: datetime | None = None
    original_coordinate_system: str | None = "wgs84"
    source_content_hash: str | None = None
    quality_metrics_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class _SourceSnapshot:
    id: int
    segment_id: int
    source_type: str
    source_file_id: str | None
    source_url: str | None
    source_content_hash: str | None
    geometry_hash: str
    normalization_version: str
    quality_status: str


def admit_legacy_reviewed_segment(
    db: Session,
    *,
    segment_id: int,
    accepted_judgment_run_id: int,
    reviewer_id: int,
    review_note: str | None = None,
    reviewed_at: datetime | None = None,
) -> RouteCognitionSegment:
    """
    把人工审核通过的旧 segment 放进白名单。

    legacy_reviewed 的含义是“旧 segment 已人工看过，可以进入认知系统”，不是伪造 provenance。
    因此它只写 route_cognition_segments，不创建 segment_geometry_sources。
    """
    reference_line_wkt = _load_segment_reference_line(db, segment_id)
    _ensure_segment_not_admitted(db, segment_id)
    _validate_human_review_judgment(db, accepted_judgment_run_id, segment_id)

    row = RouteCognitionSegment(
        segment_id=segment_id,
        primary_geometry_source_id=None,
        review_basis="legacy_reviewed",
        eligibility_status="active",
        geometry_hash=hash_segment_geometry_wkt(reference_line_wkt),
        normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        accepted_judgment_run_id=accepted_judgment_run_id,
        reviewed_by=reviewer_id,
        reviewed_at=reviewed_at or datetime.now(timezone.utc),
        review_note=review_note,
    )
    db.add(row)
    db.flush()
    return row


def admit_provenance_verified_segment(
    db: Session,
    *,
    segment_id: int,
    accepted_judgment_run_id: int,
    reviewer_id: int,
    primary_geometry_source_id: int | None = None,
    source_input: SegmentGeometrySourceInput | None = None,
    review_note: str | None = None,
    reviewed_at: datetime | None = None,
) -> RouteCognitionSegment:
    """
    把有真实 provenance 的 segment 放进白名单。

    source 可以是已有行，也可以由本函数在同一事务内创建。白名单复制 source 的 geometry_hash，
    不重新计算，避免“来源说一条线、白名单认另一条线”。
    """
    _load_segment_reference_line(db, segment_id)
    _ensure_segment_not_admitted(db, segment_id)
    _validate_human_review_judgment(db, accepted_judgment_run_id, segment_id)

    source = _resolve_source(
        db,
        segment_id=segment_id,
        reviewer_id=reviewer_id,
        primary_geometry_source_id=primary_geometry_source_id,
        source_input=source_input,
    )
    _validate_source_for_provenance(source, segment_id)

    row = RouteCognitionSegment(
        segment_id=segment_id,
        primary_geometry_source_id=source.id,
        review_basis="provenance_verified",
        eligibility_status="active",
        geometry_hash=source.geometry_hash,
        normalization_version=source.normalization_version,
        accepted_judgment_run_id=accepted_judgment_run_id,
        reviewed_by=reviewer_id,
        reviewed_at=reviewed_at or datetime.now(timezone.utc),
        review_note=review_note,
    )
    db.add(row)
    db.flush()
    return row


def _load_segment_reference_line(db: Session, segment_id: int) -> str:
    row = (
        db.query(
            Segment.id.label("id"),
            func.ST_AsText(Segment.reference_line).label("reference_line_wkt"),
        )
        .filter(Segment.id == segment_id)
        .first()
    )
    if row is None:
        raise SegmentEligibilityError(f"segment {segment_id} does not exist")
    if not row.reference_line_wkt:
        raise SegmentEligibilityError(f"segment {segment_id} has no reference_line")
    return row.reference_line_wkt


def _ensure_segment_not_admitted(db: Session, segment_id: int) -> None:
    exists = (
        db.query(RouteCognitionSegment.segment_id)
        .filter(RouteCognitionSegment.segment_id == segment_id)
        .first()
    )
    if exists is not None:
        raise SegmentEligibilityError(f"segment {segment_id} is already admitted")


def _validate_human_review_judgment(
    db: Session,
    accepted_judgment_run_id: int,
    segment_id: int,
) -> None:
    judgment = (
        db.query(
            JudgmentRun.id,
            JudgmentRun.run_type,
            JudgmentRun.status,
            JudgmentRun.confidence_state,
            JudgmentRun.segment_id,
        )
        .filter(JudgmentRun.id == accepted_judgment_run_id)
        .first()
    )
    if judgment is None:
        raise SegmentEligibilityError(f"judgment_run {accepted_judgment_run_id} does not exist")
    if judgment.run_type != "human_review":
        raise SegmentEligibilityError("accepted judgment_run must be human_review")
    if judgment.status != "succeeded":
        raise SegmentEligibilityError("accepted judgment_run status must be succeeded")
    if judgment.confidence_state not in ACCEPTED_JUDGMENT_STATES:
        raise SegmentEligibilityError("accepted judgment_run confidence_state must be human_accepted or stable")
    if judgment.segment_id is not None and judgment.segment_id != segment_id:
        raise SegmentEligibilityError("accepted judgment_run segment_id must match target segment_id")


def _resolve_source(
    db: Session,
    *,
    segment_id: int,
    reviewer_id: int,
    primary_geometry_source_id: int | None,
    source_input: SegmentGeometrySourceInput | None,
) -> _SourceSnapshot:
    if (primary_geometry_source_id is None) == (source_input is None):
        raise SegmentEligibilityError("provide exactly one of primary_geometry_source_id or source_input")

    if source_input is not None:
        _validate_input_source_for_creation(source_input)
        source = SegmentGeometrySource(
            segment_id=segment_id,
            source_type=source_input.source_type,
            source_activity_id=source_input.source_activity_id,
            source_file_id=source_input.source_file_id,
            source_url=source_input.source_url,
            source_start_index=source_input.source_start_index,
            source_end_index=source_input.source_end_index,
            source_start_time=source_input.source_start_time,
            source_end_time=source_input.source_end_time,
            original_coordinate_system=source_input.original_coordinate_system,
            geometry_hash=source_input.geometry_hash,
            source_content_hash=source_input.source_content_hash,
            normalization_version=source_input.normalization_version,
            quality_status=source_input.quality_status,
            quality_metrics_json=source_input.quality_metrics_json,
            created_by=reviewer_id,
        )
        db.add(source)
        db.flush()
        return _SourceSnapshot(
            id=source.id,
            segment_id=source.segment_id,
            source_type=source.source_type,
            source_file_id=source.source_file_id,
            source_url=source.source_url,
            source_content_hash=source.source_content_hash,
            geometry_hash=source.geometry_hash,
            normalization_version=source.normalization_version,
            quality_status=source.quality_status,
        )

    source_row = (
        db.query(
            SegmentGeometrySource.id,
            SegmentGeometrySource.segment_id,
            SegmentGeometrySource.source_type,
            SegmentGeometrySource.source_file_id,
            SegmentGeometrySource.source_url,
            SegmentGeometrySource.source_content_hash,
            SegmentGeometrySource.geometry_hash,
            SegmentGeometrySource.normalization_version,
            SegmentGeometrySource.quality_status,
        )
        .filter(SegmentGeometrySource.id == primary_geometry_source_id)
        .first()
    )
    if source_row is None:
        raise SegmentEligibilityError(f"segment_geometry_source {primary_geometry_source_id} does not exist")
    return _SourceSnapshot(
        id=source_row.id,
        segment_id=source_row.segment_id,
        source_type=source_row.source_type,
        source_file_id=source_row.source_file_id,
        source_url=source_row.source_url,
        source_content_hash=source_row.source_content_hash,
        geometry_hash=source_row.geometry_hash,
        normalization_version=source_row.normalization_version,
        quality_status=source_row.quality_status,
    )


def _validate_input_source_for_creation(source_input: SegmentGeometrySourceInput) -> None:
    if (
        source_input.original_coordinate_system is not None
        and source_input.original_coordinate_system not in ALLOWED_COORDINATE_SYSTEMS
    ):
        raise SegmentEligibilityError("segment_geometry_source original_coordinate_system is invalid")
    if (
        source_input.source_start_index is not None
        and source_input.source_end_index is not None
        and source_input.source_start_index >= source_input.source_end_index
    ):
        raise SegmentEligibilityError("segment_geometry_source source_start_index must be less than source_end_index")
    _validate_source_values(
        source_type=source_input.source_type,
        source_file_id=source_input.source_file_id,
        source_url=source_input.source_url,
        source_content_hash=source_input.source_content_hash,
        geometry_hash=source_input.geometry_hash,
        normalization_version=source_input.normalization_version,
        quality_status=source_input.quality_status,
    )


def _validate_source_for_provenance(source: _SourceSnapshot, segment_id: int) -> None:
    if source.segment_id != segment_id:
        raise SegmentEligibilityError("source.segment_id must match target segment_id")
    _validate_source_values(
        source_type=source.source_type,
        source_file_id=source.source_file_id,
        source_url=source.source_url,
        source_content_hash=source.source_content_hash,
        geometry_hash=source.geometry_hash,
        normalization_version=source.normalization_version,
        quality_status=source.quality_status,
    )


def _validate_source_values(
    *,
    source_type: str,
    source_file_id: str | None,
    source_url: str | None,
    source_content_hash: str | None,
    geometry_hash: str,
    normalization_version: str,
    quality_status: str,
) -> None:
    if quality_status != VERIFIED_SOURCE_STATUS:
        raise SegmentEligibilityError("segment_geometry_source quality_status must be verified")
    if not geometry_hash:
        raise SegmentEligibilityError("segment_geometry_source geometry_hash is required")
    if not normalization_version:
        raise SegmentEligibilityError("segment_geometry_source normalization_version is required")
    _validate_durable_material_pointer(
        source_type=source_type,
        source_file_id=source_file_id,
        source_url=source_url,
        source_content_hash=source_content_hash,
    )


def _validate_durable_material_pointer(
    *,
    source_type: str,
    source_file_id: str | None,
    source_url: str | None,
    source_content_hash: str | None,
) -> None:
    if source_type == "activity_clip":
        if source_content_hash:
            return
        raise SegmentEligibilityError("activity_clip source requires source_content_hash")
    if source_type in {"gpx_upload", "fit_upload", "admin_import"}:
        if source_file_id or source_url or source_content_hash:
            return
        raise SegmentEligibilityError("source requires a durable material pointer")
    raise SegmentEligibilityError(f"unsupported segment_geometry_source source_type: {source_type}")
