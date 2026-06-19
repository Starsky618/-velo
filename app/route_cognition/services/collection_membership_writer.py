"""collection 成员写入服务——像给专题目录夹插卡片，只准插已人审的路线/赛段成员。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.route_book.models import RouteBook, RouteVersion
from app.route_cognition.models import (
    CollectionRoute,
    CollectionSegment,
    JudgmentRun,
    RouteCognitionSegment,
    RouteCollection,
)
from app.route_cognition.services.write_guard import (
    WriteGuardError,
    assert_human_review_judgment,
    assert_metadata_has_no_relationship_truth,
)


ALLOWED_ROUTE_ROLES = {"primary", "featured", "alternate", "connector", "reference", "supporting"}
ALLOWED_SEGMENT_ROLES = {"core", "connector", "landmark", "risk_area", "training_interval", "supporting"}
ALLOWED_MEMBERSHIP_STATUSES = {"active", "deprecated", "superseded"}
ALLOWED_SOURCE_KINDS = {"manual_curated", "legacy_import"}

FORBIDDEN_MEMBERSHIP_METADATA_KEYS = {
    "candidate",
    "candidate_id",
    "candidate_ids",
    "candidates",
    "collection",
    "collection_id",
    "collection_ids",
    "collections",
    "concept",
    "concept_id",
    "concept_ids",
    "concepts",
    "member",
    "member_id",
    "member_ids",
    "members",
    "ordering",
    "relation_type",
    "reviewed_route_line_hash",
    "role",
    "roles",
    "route",
    "route_book",
    "route_book_id",
    "route_book_ids",
    "route_books",
    "route_id",
    "route_ids",
    "routes",
    "segment",
    "segment_geometry_hash",
    "segment_id",
    "segment_ids",
    "segments",
    "source_candidate_id",
}


class CollectionMembershipWriterError(ValueError):
    """collection 成员写入失败——调用方应停下审核流程，而不是绕过 writer 直写表。"""


@dataclass(frozen=True)
class _JudgmentTarget:
    route_book_id: int | None
    route_version_id: int | None
    segment_id: int | None


def add_collection_route(
    db: Session,
    *,
    collection_id: int,
    route_book_id: int,
    reviewed_route_version_id: int,
    role: str,
    seq: int | None = None,
    importance: int | None = None,
    membership_status: str = "active",
    source_kind: str = "manual_curated",
    source_ref: str | None = None,
    accepted_judgment_run_id: int,
    display_priority: int | None = None,
    reason_summary: str | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    created_by: int | None = None,
) -> CollectionRoute:
    """把一条 route_book 收进 collection；hash 只从 route_version 复制，不接收外部传值。"""

    _validate_common_membership_fields(
        role=role,
        allowed_roles=ALLOWED_ROUTE_ROLES,
        seq=seq,
        importance=importance,
        display_priority=display_priority,
        membership_status=membership_status,
        source_kind=source_kind,
        source_ref=source_ref,
        reason_summary=reason_summary,
        metadata_json=metadata_json,
    )
    judgment_target = _human_review_judgment_target(db, accepted_judgment_run_id)
    _assert_collection_exists(db, collection_id)
    _assert_route_book_exists(db, route_book_id)
    route_version = _route_version_for_book(
        db,
        route_book_id=route_book_id,
        reviewed_route_version_id=reviewed_route_version_id,
    )
    _assert_judgment_targets_route(
        judgment_target,
        route_book_id=route_book_id,
        reviewed_route_version_id=reviewed_route_version_id,
    )
    if membership_status == "active":
        _assert_no_active_collection_route(db, collection_id=collection_id, route_book_id=route_book_id)
        _assert_no_active_seq(db, table="collection_routes", collection_id=collection_id, seq=seq)

    membership = CollectionRoute(
        collection_id=collection_id,
        route_book_id=route_book_id,
        reviewed_route_version_id=reviewed_route_version_id,
        reviewed_route_line_hash=route_version.line_hash,
        role=role,
        seq=seq,
        importance=importance,
        membership_status=membership_status,
        source_kind=source_kind,
        source_ref=source_ref,
        accepted_judgment_run_id=accepted_judgment_run_id,
        accepted_judgment_run_type="human_review",
        display_priority=display_priority,
        reason_summary=reason_summary,
        metadata_json=dict(metadata_json) if metadata_json is not None else None,
        created_by=created_by,
    )
    db.add(membership)
    db.flush()
    return membership


def add_collection_segment(
    db: Session,
    *,
    collection_id: int,
    segment_id: int,
    role: str,
    seq: int | None = None,
    importance: int | None = None,
    membership_status: str = "active",
    source_kind: str = "manual_curated",
    source_ref: str | None = None,
    accepted_judgment_run_id: int,
    display_priority: int | None = None,
    reason_summary: str | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    created_by: int | None = None,
) -> CollectionSegment:
    """把一个白名单 segment 收进 collection；裸 segments.id 不能进入专题成员表。"""

    _validate_common_membership_fields(
        role=role,
        allowed_roles=ALLOWED_SEGMENT_ROLES,
        seq=seq,
        importance=importance,
        display_priority=display_priority,
        membership_status=membership_status,
        source_kind=source_kind,
        source_ref=source_ref,
        reason_summary=reason_summary,
        metadata_json=metadata_json,
    )
    judgment_target = _human_review_judgment_target(db, accepted_judgment_run_id)
    _assert_collection_exists(db, collection_id)
    cognition_segment = _route_cognition_segment(db, segment_id)
    _assert_judgment_targets_segment(judgment_target, segment_id=segment_id)
    if membership_status == "active":
        _assert_no_active_collection_segment(db, collection_id=collection_id, segment_id=segment_id)
        _assert_no_active_seq(db, table="collection_segments", collection_id=collection_id, seq=seq)

    membership = CollectionSegment(
        collection_id=collection_id,
        segment_id=segment_id,
        segment_geometry_hash=cognition_segment.geometry_hash,
        role=role,
        seq=seq,
        importance=importance,
        membership_status=membership_status,
        source_kind=source_kind,
        source_ref=source_ref,
        accepted_judgment_run_id=accepted_judgment_run_id,
        accepted_judgment_run_type="human_review",
        display_priority=display_priority,
        reason_summary=reason_summary,
        metadata_json=dict(metadata_json) if metadata_json is not None else None,
        created_by=created_by,
    )
    db.add(membership)
    db.flush()
    return membership


def _validate_common_membership_fields(
    *,
    role: str,
    allowed_roles: set[str],
    seq: int | None,
    importance: int | None,
    display_priority: int | None,
    membership_status: str,
    source_kind: str,
    source_ref: str | None,
    reason_summary: str | None,
    metadata_json: Mapping[str, Any] | None,
) -> None:
    if role not in allowed_roles:
        raise CollectionMembershipWriterError("role is not allowed")
    if membership_status not in ALLOWED_MEMBERSHIP_STATUSES:
        raise CollectionMembershipWriterError("membership_status is not allowed")
    if source_kind not in ALLOWED_SOURCE_KINDS:
        raise CollectionMembershipWriterError("source_kind is not allowed")
    if source_kind == "legacy_import" and not _has_text(source_ref) and not _has_text(reason_summary):
        raise CollectionMembershipWriterError("legacy_import requires source_ref or reason_summary")
    if seq is not None and seq < 1:
        raise CollectionMembershipWriterError("seq must be positive")
    if importance is not None and not 0 <= importance <= 100:
        raise CollectionMembershipWriterError("importance must be between 0 and 100")
    if display_priority is not None and not 0 <= display_priority <= 100:
        raise CollectionMembershipWriterError("display_priority must be between 0 and 100")
    _assert_metadata_has_no_membership_truth(metadata_json)


def _human_review_judgment_target(db: Session, accepted_judgment_run_id: int) -> _JudgmentTarget:
    try:
        assert_human_review_judgment(db, accepted_judgment_run_id)
    except WriteGuardError as error:
        raise CollectionMembershipWriterError(str(error)) from error

    judgment = (
        db.query(JudgmentRun.route_book_id, JudgmentRun.route_version_id, JudgmentRun.segment_id)
        .filter(JudgmentRun.id == accepted_judgment_run_id)
        .first()
    )
    if judgment is None:
        raise CollectionMembershipWriterError("accepted_judgment_run_id does not exist")
    return _JudgmentTarget(
        route_book_id=judgment.route_book_id,
        route_version_id=judgment.route_version_id,
        segment_id=judgment.segment_id,
    )


def _assert_judgment_targets_route(
    judgment_target: _JudgmentTarget,
    *,
    route_book_id: int,
    reviewed_route_version_id: int,
) -> None:
    if judgment_target.segment_id is not None:
        raise CollectionMembershipWriterError("judgment target must not be a segment for collection route membership")
    if judgment_target.route_book_id is not None and judgment_target.route_book_id != route_book_id:
        raise CollectionMembershipWriterError("judgment route_book_id does not match collection route membership")
    if judgment_target.route_version_id is not None and judgment_target.route_version_id != reviewed_route_version_id:
        raise CollectionMembershipWriterError("judgment route_version_id does not match collection route membership")


def _assert_judgment_targets_segment(judgment_target: _JudgmentTarget, *, segment_id: int) -> None:
    if judgment_target.route_book_id is not None or judgment_target.route_version_id is not None:
        raise CollectionMembershipWriterError("judgment target must not be a route for collection segment membership")
    if judgment_target.segment_id is not None and judgment_target.segment_id != segment_id:
        raise CollectionMembershipWriterError("judgment segment_id does not match collection segment membership")


def _assert_metadata_has_no_membership_truth(metadata_json: Mapping[str, Any] | None) -> None:
    try:
        assert_metadata_has_no_relationship_truth(metadata_json)
    except WriteGuardError as error:
        raise CollectionMembershipWriterError(str(error)) from error

    forbidden_key = _find_forbidden_membership_metadata_key(metadata_json)
    if forbidden_key is not None:
        raise CollectionMembershipWriterError(f"metadata_json contains forbidden key: {forbidden_key}")


def _assert_collection_exists(db: Session, collection_id: int) -> None:
    collection = db.query(RouteCollection.id).filter(RouteCollection.id == collection_id).first()
    if collection is None:
        raise CollectionMembershipWriterError("collection does not exist")


def _assert_route_book_exists(db: Session, route_book_id: int) -> None:
    route_book = db.query(RouteBook.id).filter(RouteBook.id == route_book_id).first()
    if route_book is None:
        raise CollectionMembershipWriterError("route_book does not exist")


def _route_version_for_book(db: Session, *, route_book_id: int, reviewed_route_version_id: int):
    route_version = (
        db.query(RouteVersion.id, RouteVersion.route_book_id, RouteVersion.line_hash)
        .filter(RouteVersion.id == reviewed_route_version_id)
        .first()
    )
    if route_version is None:
        raise CollectionMembershipWriterError("reviewed_route_version_id does not exist")
    if route_version.route_book_id != route_book_id:
        raise CollectionMembershipWriterError("reviewed_route_version_id must belong to route_book_id")
    if not _has_text(route_version.line_hash):
        raise CollectionMembershipWriterError("reviewed route_version line_hash must not be empty")
    return route_version


def _route_cognition_segment(db: Session, segment_id: int):
    cognition_segment = (
        db.query(RouteCognitionSegment.segment_id, RouteCognitionSegment.geometry_hash)
        .filter(RouteCognitionSegment.segment_id == segment_id)
        .first()
    )
    if cognition_segment is None:
        raise CollectionMembershipWriterError("segment_id must exist in route_cognition_segments")
    if not _has_text(cognition_segment.geometry_hash):
        raise CollectionMembershipWriterError("route_cognition_segments.geometry_hash must not be empty")
    return cognition_segment


def _assert_no_active_collection_route(db: Session, *, collection_id: int, route_book_id: int) -> None:
    existing = (
        db.query(CollectionRoute.id)
        .filter(
            CollectionRoute.collection_id == collection_id,
            CollectionRoute.route_book_id == route_book_id,
            CollectionRoute.membership_status == "active",
        )
        .first()
    )
    if existing is not None:
        raise CollectionMembershipWriterError("active route membership already exists")


def _assert_no_active_collection_segment(db: Session, *, collection_id: int, segment_id: int) -> None:
    existing = (
        db.query(CollectionSegment.id)
        .filter(
            CollectionSegment.collection_id == collection_id,
            CollectionSegment.segment_id == segment_id,
            CollectionSegment.membership_status == "active",
        )
        .first()
    )
    if existing is not None:
        raise CollectionMembershipWriterError("active segment membership already exists")


def _assert_no_active_seq(db: Session, *, table: str, collection_id: int, seq: int | None) -> None:
    if seq is None:
        return
    if table == "collection_routes":
        existing = (
            db.query(CollectionRoute.id)
            .filter(
                CollectionRoute.collection_id == collection_id,
                CollectionRoute.seq == seq,
                CollectionRoute.membership_status == "active",
            )
            .first()
        )
    else:
        existing = (
            db.query(CollectionSegment.id)
            .filter(
                CollectionSegment.collection_id == collection_id,
                CollectionSegment.seq == seq,
                CollectionSegment.membership_status == "active",
            )
            .first()
        )
    if existing is not None:
        raise CollectionMembershipWriterError("active seq already exists")


def _find_forbidden_membership_metadata_key(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise CollectionMembershipWriterError("metadata_json must be an object")

    for key, child in value.items():
        if isinstance(key, str) and key.lower() in FORBIDDEN_MEMBERSHIP_METADATA_KEYS:
            return key
        nested_key = _find_forbidden_membership_metadata_key_in_child(child)
        if nested_key is not None:
            return nested_key
    return None


def _find_forbidden_membership_metadata_key_in_child(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _find_forbidden_membership_metadata_key(value)
    if isinstance(value, (list, tuple)):
        for item in value:
            nested_key = _find_forbidden_membership_metadata_key_in_child(item)
            if nested_key is not None:
                return nested_key
    return None


def _has_text(value: str | None) -> bool:
    return value is not None and value.strip() != ""
