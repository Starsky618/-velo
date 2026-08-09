"""route_segments 写入服务——像路线装配单登记员，只记录组件，不改路线图纸。"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session

from app.route_book.models import RouteBook, RouteVersion
from app.route_cognition.geometry_hash import hash_segment_geometry_wkt
from app.route_cognition.models import JudgmentRun, RouteCognitionSegment, RouteSegment
from app.route_cognition.services.write_guard import (
    WriteGuardError,
    assert_human_review_judgment,
    assert_metadata_has_no_relationship_truth,
)


ALLOWED_DIRECTIONS = {"forward", "reverse"}
ALLOWED_MEMBERSHIP_STATUSES = {"active", "deprecated", "superseded"}
ALLOWED_SOURCE_KINDS = {"manual_curated", "legacy_import"}

FORBIDDEN_ROUTE_SEGMENT_METADATA_KEYS = {
    "candidate",
    "candidate_id",
    "candidate_ids",
    "candidates",
    "collection",
    "collection_id",
    "collection_ids",
    "collections",
    "component_geometry",
    "component_geometry_hash",
    "component_type",
    "concept",
    "concept_id",
    "concept_ids",
    "concepts",
    "coordinates",
    "coords",
    "direction",
    "end_fraction",
    "geom",
    "geometry",
    "line_hash",
    "member",
    "member_id",
    "member_ids",
    "members",
    "ordering",
    "polyline",
    "relation_type",
    "reference_line",
    "reference_line_snapshot",
    "role",
    "roles",
    "route",
    "route_book",
    "route_book_id",
    "route_book_ids",
    "route_books",
    "route_id",
    "route_ids",
    "route_line_hash",
    "route_segment",
    "route_segments",
    "route_version",
    "route_version_id",
    "route_version_ids",
    "route_versions",
    "routes",
    "segment",
    "segment_geometry_hash",
    "segment_id",
    "segment_ids",
    "segments",
    "seq",
    "sequence",
    "source_candidate_id",
    "start_fraction",
    "wkt",
}


class RouteSegmentWriterError(ValueError):
    """route_segments 写入失败——调用方应停下复核，而不是绕过 writer 直写表。"""


@dataclass(frozen=True)
class _JudgmentTarget:
    route_book_id: int | None
    route_version_id: int | None
    segment_id: int | None


def add_route_segment_clip(
    db: Session,
    *,
    route_book_id: int,
    route_version_id: int,
    seq: int,
    segment_id: int,
    component_geometry: str | None,
    direction: str,
    start_fraction: float | None = None,
    end_fraction: float | None = None,
    membership_status: str = "active",
    source_kind: str = "manual_curated",
    source_ref: str | None = None,
    accepted_judgment_run_id: int,
    display_priority: int | None = None,
    reason_summary: str | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    created_by: int | None = None,
) -> RouteSegment:
    """登记一段来自白名单 segment 的路线组件；hash 只从可信表复制或现场计算。"""

    _validate_common_fields(
        seq=seq,
        membership_status=membership_status,
        source_kind=source_kind,
        source_ref=source_ref,
        display_priority=display_priority,
        reason_summary=reason_summary,
        metadata_json=metadata_json,
    )
    if direction not in ALLOWED_DIRECTIONS:
        raise RouteSegmentWriterError("direction is not allowed")
    _validate_fraction_pair(start_fraction=start_fraction, end_fraction=end_fraction)
    normalized_geometry = _validate_line_component_geometry(component_geometry)

    judgment_target = _human_review_judgment_target(db, accepted_judgment_run_id)
    _assert_route_book_exists(db, route_book_id)
    route_version = _route_version_for_book(db, route_book_id=route_book_id, route_version_id=route_version_id)
    cognition_segment = _route_cognition_segment(db, segment_id)
    _assert_judgment_targets_component(
        judgment_target,
        route_book_id=route_book_id,
        route_version_id=route_version_id,
        segment_id=segment_id,
    )
    if membership_status == "active":
        _assert_no_active_seq(db, route_book_id=route_book_id, route_version_id=route_version_id, seq=seq)

    route_segment = RouteSegment(
        route_book_id=route_book_id,
        route_version_id=route_version_id,
        route_line_hash=route_version.line_hash,
        seq=seq,
        component_type="segment_clip",
        segment_id=segment_id,
        segment_geometry_hash=cognition_segment.geometry_hash,
        component_geometry=WKTElement(normalized_geometry, srid=4326),
        component_geometry_hash=_component_geometry_hash(normalized_geometry),
        direction=direction,
        start_fraction=start_fraction,
        end_fraction=end_fraction,
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
    db.add(route_segment)
    db.flush()
    return route_segment


def add_route_custom_geometry(
    db: Session,
    *,
    route_book_id: int,
    route_version_id: int,
    seq: int,
    component_geometry: str | None,
    segment_id: int | None = None,
    direction: str | None = None,
    start_fraction: float | None = None,
    end_fraction: float | None = None,
    membership_status: str = "active",
    source_kind: str = "manual_curated",
    source_ref: str | None = None,
    accepted_judgment_run_id: int,
    display_priority: int | None = None,
    reason_summary: str | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    created_by: int | None = None,
) -> RouteSegment:
    """登记一段人工线；它只属于这版路线，不假装自己是正式 segment。"""

    if segment_id is not None:
        raise RouteSegmentWriterError("custom_geometry must not set segment_id")
    if direction is not None:
        raise RouteSegmentWriterError("custom_geometry must not set direction")
    if start_fraction is not None or end_fraction is not None:
        raise RouteSegmentWriterError("custom_geometry must not set fractions")

    _validate_common_fields(
        seq=seq,
        membership_status=membership_status,
        source_kind=source_kind,
        source_ref=source_ref,
        display_priority=display_priority,
        reason_summary=reason_summary,
        metadata_json=metadata_json,
    )
    normalized_geometry = _validate_line_component_geometry(component_geometry)

    judgment_target = _human_review_judgment_target(db, accepted_judgment_run_id)
    _assert_route_book_exists(db, route_book_id)
    route_version = _route_version_for_book(db, route_book_id=route_book_id, route_version_id=route_version_id)
    _assert_judgment_targets_component(
        judgment_target,
        route_book_id=route_book_id,
        route_version_id=route_version_id,
        segment_id=None,
    )
    if membership_status == "active":
        _assert_no_active_seq(db, route_book_id=route_book_id, route_version_id=route_version_id, seq=seq)

    route_segment = RouteSegment(
        route_book_id=route_book_id,
        route_version_id=route_version_id,
        route_line_hash=route_version.line_hash,
        seq=seq,
        component_type="custom_geometry",
        segment_id=None,
        segment_geometry_hash=None,
        component_geometry=WKTElement(normalized_geometry, srid=4326),
        component_geometry_hash=_component_geometry_hash(normalized_geometry),
        direction=None,
        start_fraction=None,
        end_fraction=None,
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
    db.add(route_segment)
    db.flush()
    return route_segment


def _validate_common_fields(
    *,
    seq: int,
    membership_status: str,
    source_kind: str,
    source_ref: str | None,
    display_priority: int | None,
    reason_summary: str | None,
    metadata_json: Mapping[str, Any] | None,
) -> None:
    if seq is None or seq < 1:
        raise RouteSegmentWriterError("seq must be positive")
    if membership_status not in ALLOWED_MEMBERSHIP_STATUSES:
        raise RouteSegmentWriterError("membership_status is not allowed")
    if source_kind not in ALLOWED_SOURCE_KINDS:
        raise RouteSegmentWriterError("source_kind is not allowed")
    if source_kind == "legacy_import" and not _has_text(source_ref) and not _has_text(reason_summary):
        raise RouteSegmentWriterError("legacy_import requires source_ref or reason_summary")
    if display_priority is not None and not 0 <= display_priority <= 100:
        raise RouteSegmentWriterError("display_priority must be between 0 and 100")
    _assert_metadata_has_no_route_segment_truth(metadata_json)


def _validate_fraction_pair(*, start_fraction: float | None, end_fraction: float | None) -> None:
    if start_fraction is None and end_fraction is None:
        return
    if start_fraction is None or end_fraction is None:
        raise RouteSegmentWriterError("start_fraction and end_fraction must be provided together")
    try:
        start_value = float(start_fraction)
        end_value = float(end_fraction)
    except (TypeError, ValueError) as error:
        raise RouteSegmentWriterError("fractions must be numeric") from error
    if (
        not math.isfinite(start_value)
        or not math.isfinite(end_value)
        or start_value < 0
        or end_value > 1
        or start_value >= end_value
    ):
        raise RouteSegmentWriterError("fractions must satisfy 0 <= start_fraction < end_fraction <= 1")


def _validate_line_component_geometry(component_geometry: str | None) -> str:
    if not _has_text(component_geometry):
        raise RouteSegmentWriterError("component_geometry is required")
    normalized = _strip_supported_srid(component_geometry.strip())
    geometry_type = _geometry_type(normalized)
    if geometry_type == "LINESTRING":
        _assert_linestring_body_is_valid(_geometry_body(normalized))
    elif geometry_type == "MULTILINESTRING":
        bodies = _multilinestring_bodies(_geometry_body(normalized))
        if not bodies:
            raise RouteSegmentWriterError("component_geometry must contain at least one line")
        for body in bodies:
            _assert_linestring_body_is_valid(body)
    else:
        raise RouteSegmentWriterError("component_geometry must be a line geometry")
    return normalized


def _strip_supported_srid(component_geometry: str) -> str:
    match = re.match(r"^SRID=(\d+);\s*(.+)$", component_geometry, flags=re.IGNORECASE)
    if match is None:
        return component_geometry
    if match.group(1) != "4326":
        raise RouteSegmentWriterError("component_geometry SRID must be 4326")
    return match.group(2).strip()


def _geometry_type(component_geometry: str) -> str:
    match = re.match(r"^(?:SRID=\d+;)?\s*([A-Za-z]+)\s*\(", component_geometry)
    if match is None:
        raise RouteSegmentWriterError("component_geometry must be valid WKT")
    return match.group(1).upper()


def _geometry_body(component_geometry: str) -> str:
    start = component_geometry.find("(")
    end = component_geometry.rfind(")")
    if start < 0 or end <= start or component_geometry[end + 1 :].strip():
        raise RouteSegmentWriterError("component_geometry must be valid WKT")
    return component_geometry[start + 1 : end].strip()


def _multilinestring_bodies(body: str) -> list[str]:
    bodies: list[str] = []
    index = 0
    length = len(body)
    while index < length:
        index = _skip_whitespace(body, index)
        if index >= length or body[index] != "(":
            raise RouteSegmentWriterError("component_geometry must be valid WKT")

        index += 1
        current: list[str] = []
        while index < length and body[index] != ")":
            if body[index] == "(":
                raise RouteSegmentWriterError("component_geometry must be valid WKT")
            current.append(body[index])
            index += 1
        if index >= length:
            raise RouteSegmentWriterError("component_geometry must be valid WKT")
        bodies.append("".join(current).strip())
        index += 1

        index = _skip_whitespace(body, index)
        if index >= length:
            break
        if body[index] != ",":
            raise RouteSegmentWriterError("component_geometry must be valid WKT")
        index += 1
        index = _skip_whitespace(body, index)
        if index >= length or body[index] == ",":
            raise RouteSegmentWriterError("component_geometry must be valid WKT")
    return bodies


def _skip_whitespace(value: str, index: int) -> int:
    while index < len(value) and value[index] in {" ", "\t", "\n", "\r"}:
        index += 1
    return index


def _assert_linestring_body_is_valid(body: str) -> None:
    raw_pairs = body.split(",")
    if any(pair.strip() == "" for pair in raw_pairs):
        raise RouteSegmentWriterError("component_geometry coordinates must not be empty")
    pairs = [pair.strip() for pair in raw_pairs]
    if len(pairs) < 2:
        raise RouteSegmentWriterError("component_geometry line must contain at least two points")
    for pair in pairs:
        parts = pair.split()
        if len(parts) != 2:
            raise RouteSegmentWriterError("component_geometry coordinates must include exactly lon and lat")
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError as error:
            raise RouteSegmentWriterError("component_geometry coordinates must be numeric") from error
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise RouteSegmentWriterError("component_geometry coordinates must be finite")


def _component_geometry_hash(component_geometry: str) -> str:
    return hash_segment_geometry_wkt(component_geometry)


def _human_review_judgment_target(db: Session, accepted_judgment_run_id: int) -> _JudgmentTarget:
    try:
        assert_human_review_judgment(db, accepted_judgment_run_id)
    except WriteGuardError as error:
        raise RouteSegmentWriterError(str(error)) from error

    judgment = (
        db.query(JudgmentRun.route_book_id, JudgmentRun.route_version_id, JudgmentRun.segment_id)
        .filter(JudgmentRun.id == accepted_judgment_run_id)
        .first()
    )
    if judgment is None:
        raise RouteSegmentWriterError("accepted_judgment_run_id does not exist")
    return _JudgmentTarget(
        route_book_id=judgment.route_book_id,
        route_version_id=judgment.route_version_id,
        segment_id=judgment.segment_id,
    )


def _assert_judgment_targets_component(
    judgment_target: _JudgmentTarget,
    *,
    route_book_id: int,
    route_version_id: int,
    segment_id: int | None,
) -> None:
    if judgment_target.route_book_id is not None and judgment_target.route_book_id != route_book_id:
        raise RouteSegmentWriterError("judgment route_book_id does not match route segment")
    if judgment_target.route_version_id is not None and judgment_target.route_version_id != route_version_id:
        raise RouteSegmentWriterError("judgment route_version_id does not match route segment")
    if judgment_target.segment_id is not None and judgment_target.segment_id != segment_id:
        raise RouteSegmentWriterError("judgment segment_id does not match route segment")


def _assert_metadata_has_no_route_segment_truth(metadata_json: Mapping[str, Any] | None) -> None:
    try:
        assert_metadata_has_no_relationship_truth(metadata_json)
    except WriteGuardError as error:
        raise RouteSegmentWriterError(str(error)) from error

    forbidden_key = _find_forbidden_route_segment_metadata_key(metadata_json)
    if forbidden_key is not None:
        raise RouteSegmentWriterError(f"metadata_json contains forbidden key: {forbidden_key}")


def _assert_route_book_exists(db: Session, route_book_id: int) -> None:
    route_book = db.query(RouteBook.id).filter(RouteBook.id == route_book_id).first()
    if route_book is None:
        raise RouteSegmentWriterError("route_book does not exist")


def _route_version_for_book(db: Session, *, route_book_id: int, route_version_id: int):
    route_version = (
        db.query(RouteVersion.id, RouteVersion.route_book_id, RouteVersion.line_hash)
        .filter(RouteVersion.id == route_version_id)
        .first()
    )
    if route_version is None:
        raise RouteSegmentWriterError("route_version_id does not exist")
    if route_version.route_book_id != route_book_id:
        raise RouteSegmentWriterError("route_version_id must belong to route_book_id")
    if not _has_text(route_version.line_hash):
        raise RouteSegmentWriterError("route_version line_hash must not be empty")
    return route_version


def _route_cognition_segment(db: Session, segment_id: int):
    cognition_segment = (
        db.query(
            RouteCognitionSegment.segment_id,
            RouteCognitionSegment.geometry_hash,
            RouteCognitionSegment.eligibility_status,
        )
        .filter(RouteCognitionSegment.segment_id == segment_id)
        .first()
    )
    if cognition_segment is None:
        raise RouteSegmentWriterError("segment_id must exist in route_cognition_segments")
    if cognition_segment.eligibility_status != "active":
        raise RouteSegmentWriterError("route_cognition_segment must be active")
    if not _has_text(cognition_segment.geometry_hash):
        raise RouteSegmentWriterError("route_cognition_segments.geometry_hash must not be empty")
    return cognition_segment


def _assert_no_active_seq(
    db: Session,
    *,
    route_book_id: int,
    route_version_id: int,
    seq: int,
) -> None:
    existing = (
        db.query(RouteSegment.id)
        .filter(
            RouteSegment.route_book_id == route_book_id,
            RouteSegment.route_version_id == route_version_id,
            RouteSegment.seq == seq,
            RouteSegment.membership_status == "active",
        )
        .first()
    )
    if existing is not None:
        raise RouteSegmentWriterError("active seq already exists")


def _find_forbidden_route_segment_metadata_key(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RouteSegmentWriterError("metadata_json must be an object")

    for key, child in value.items():
        if isinstance(key, str) and key.lower() in FORBIDDEN_ROUTE_SEGMENT_METADATA_KEYS:
            return key
        nested_key = _find_forbidden_route_segment_metadata_key_in_child(child)
        if nested_key is not None:
            return nested_key
    return None


def _find_forbidden_route_segment_metadata_key_in_child(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _find_forbidden_route_segment_metadata_key(value)
    if isinstance(value, (list, tuple)):
        for item in value:
            nested_key = _find_forbidden_route_segment_metadata_key_in_child(item)
            if nested_key is not None:
                return nested_key
    return None


def _has_text(value: str | None) -> bool:
    return value is not None and value.strip() != ""
