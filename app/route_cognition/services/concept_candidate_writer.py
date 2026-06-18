"""概念候选写入服务——只把判断放进待审队列，不把候选盖成正式关系。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.route_book.models import RouteBook, RouteVersion
from app.route_cognition.models import (
    CollectionConceptCandidate,
    ConceptNode,
    JudgmentRun,
    RouteCognitionSegment,
    RouteCollection,
    RouteConceptCandidate,
    SegmentConceptCandidate,
)
from app.route_cognition.services.write_guard import (
    WriteGuardError,
    assert_metadata_has_no_relationship_truth,
)


ALLOWED_RELATION_TYPES = {
    "suitable_for",
    "passes_near",
    "has_feature",
    "has_risk",
    "part_of_event",
    "story_reference",
    "training_theme",
    "local_name",
    "associated_with",
}
ALLOWED_PROPOSER_KINDS = {"algorithm", "agent", "human", "imported"}
ALLOWED_CREATE_STATUSES = {"proposed", "needs_review"}
ALLOWED_CONFIDENCE_STATES = {
    "raw",
    "proposed",
    "challenged",
    "stable",
    "human_accepted",
    "stale",
    "inconclusive",
}
ALLOWED_JUDGMENT_RUN_TYPES = {
    "spatial_algorithm",
    "semantic_agent",
    "adversarial_agent",
    "human_review",
    "research_synthesis",
    "hybrid",
}

FORBIDDEN_CANDIDATE_METADATA_KEYS = {
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
    "concept_node_id",
    "formal_link",
    "formal_link_id",
    "formal_link_ids",
    "formal_links",
    "member",
    "member_id",
    "member_ids",
    "members",
    "membership",
    "membership_id",
    "membership_ids",
    "memberships",
    "ordering",
    "relation_type",
    "role",
    "roles",
    "route",
    "route_book",
    "route_book_id",
    "route_book_ids",
    "route_books",
    "route_id",
    "route_ids",
    "route_version",
    "route_version_id",
    "route_version_ids",
    "route_versions",
    "routes",
    "segment",
    "segment_id",
    "segment_ids",
    "segments",
    "source_candidate_id",
    "source_candidate_ids",
}
RELATIONSHIP_KEY_PREFIXES = (
    "candidate",
    "collection",
    "concept",
    "formal_link",
    "member",
    "membership",
    "route",
    "route_book",
    "route_concept",
    "route_version",
    "segment",
    "segment_concept",
)
RELATIONSHIP_KEY_SUFFIXES = (
    "hash",
    "hashes",
    "id",
    "ids",
    "name",
    "names",
    "order",
    "ordering",
    "ref",
    "refs",
    "role",
    "roles",
    "slug",
    "slugs",
    "status",
    "statuses",
)
ENTITY_DISCRIMINATOR_KEYS = {
    "entity_type",
    "kind",
    "member_type",
    "object_type",
    "source_type",
    "target_type",
    "type",
}
RELATIONSHIP_ENTITY_VALUES = {
    "candidate",
    "candidates",
    "collection",
    "collections",
    "concept",
    "concepts",
    "member",
    "members",
    "membership",
    "memberships",
    "route",
    "route_book",
    "route_books",
    "route_concept_candidate",
    "route_concept_candidates",
    "route_version",
    "route_versions",
    "routes",
    "segment",
    "segment_concept_candidate",
    "segment_concept_candidates",
    "segments",
}


class ConceptCandidateWriterError(ValueError):
    """概念候选写入失败——调用方应停在待审队列外，而不是绕过 writer 直写表。"""


@dataclass(frozen=True)
class _JudgmentSnapshot:
    id: int
    run_type: str
    status: str
    route_book_id: int | None
    route_version_id: int | None
    segment_id: int | None
    confidence: float | None
    confidence_state: str
    result_summary_json: Any
    missing_data_json: Any
    contradiction_json: Any


@dataclass(frozen=True)
class _CandidateProjection:
    latest_judgment_run_id: int
    latest_confidence: float | None
    latest_confidence_state: str
    latest_evidence_summary_json: Any
    latest_missing_data_summary_json: Any
    latest_contradiction_summary_json: Any


def propose_route_concept_candidate(
    db: Session,
    *,
    route_book_id: int,
    route_version_id: int,
    concept_node_id: int,
    relation_type: str,
    proposer_kind: str,
    created_by_judgment_run_id: int | None,
    latest_judgment_run_id: int | None = None,
    candidate_status: str = "proposed",
    latest_confidence: float | None = None,
    latest_confidence_state: str | None = None,
    latest_evidence_summary_json: Mapping[str, Any] | None = None,
    latest_missing_data_summary_json: Mapping[str, Any] | None = None,
    latest_contradiction_summary_json: Mapping[str, Any] | None = None,
    reason_summary: str | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    created_by: int | None = None,
) -> RouteConceptCandidate:
    """提出 route-concept 候选；route_line_hash 只能从 route_versions 复制。"""

    projection = _validate_common_candidate_inputs(
        db,
        relation_type=relation_type,
        proposer_kind=proposer_kind,
        candidate_status=candidate_status,
        created_by_judgment_run_id=created_by_judgment_run_id,
        latest_judgment_run_id=latest_judgment_run_id,
        latest_confidence=latest_confidence,
        latest_confidence_state=latest_confidence_state,
        latest_evidence_summary_json=latest_evidence_summary_json,
        latest_missing_data_summary_json=latest_missing_data_summary_json,
        latest_contradiction_summary_json=latest_contradiction_summary_json,
        metadata_json=metadata_json,
        route_book_id=route_book_id,
        route_version_id=route_version_id,
    )
    _assert_concept_node_exists(db, concept_node_id)
    route_line_hash = _route_line_hash_for_version(
        db,
        route_book_id=route_book_id,
        route_version_id=route_version_id,
    )

    candidate = RouteConceptCandidate(
        route_book_id=route_book_id,
        route_version_id=route_version_id,
        route_line_hash=route_line_hash,
        concept_node_id=concept_node_id,
        relation_type=relation_type,
        proposer_kind=proposer_kind,
        candidate_status=candidate_status,
        created_by_judgment_run_id=created_by_judgment_run_id,
        latest_judgment_run_id=projection.latest_judgment_run_id,
        accepted_by_judgment_run_id=None,
        latest_confidence=projection.latest_confidence,
        latest_confidence_state=projection.latest_confidence_state,
        latest_evidence_summary_json=_json_copy(projection.latest_evidence_summary_json),
        latest_missing_data_summary_json=_json_copy(projection.latest_missing_data_summary_json),
        latest_contradiction_summary_json=_json_copy(projection.latest_contradiction_summary_json),
        reason_summary=reason_summary,
        metadata_json=_json_copy(metadata_json),
        created_by=created_by,
    )
    db.add(candidate)
    db.flush()
    return candidate


def propose_segment_concept_candidate(
    db: Session,
    *,
    segment_id: int,
    concept_node_id: int,
    relation_type: str,
    proposer_kind: str,
    created_by_judgment_run_id: int | None,
    latest_judgment_run_id: int | None = None,
    candidate_status: str = "proposed",
    latest_confidence: float | None = None,
    latest_confidence_state: str | None = None,
    latest_evidence_summary_json: Mapping[str, Any] | None = None,
    latest_missing_data_summary_json: Mapping[str, Any] | None = None,
    latest_contradiction_summary_json: Mapping[str, Any] | None = None,
    reason_summary: str | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    created_by: int | None = None,
) -> SegmentConceptCandidate:
    """提出 segment-concept 候选；segment 必须先进入 route_cognition_segments 白名单。"""

    projection = _validate_common_candidate_inputs(
        db,
        relation_type=relation_type,
        proposer_kind=proposer_kind,
        candidate_status=candidate_status,
        created_by_judgment_run_id=created_by_judgment_run_id,
        latest_judgment_run_id=latest_judgment_run_id,
        latest_confidence=latest_confidence,
        latest_confidence_state=latest_confidence_state,
        latest_evidence_summary_json=latest_evidence_summary_json,
        latest_missing_data_summary_json=latest_missing_data_summary_json,
        latest_contradiction_summary_json=latest_contradiction_summary_json,
        metadata_json=metadata_json,
        segment_id=segment_id,
    )
    _assert_concept_node_exists(db, concept_node_id)
    segment_geometry_hash = _segment_geometry_hash(db, segment_id)

    candidate = SegmentConceptCandidate(
        segment_id=segment_id,
        segment_geometry_hash=segment_geometry_hash,
        concept_node_id=concept_node_id,
        relation_type=relation_type,
        proposer_kind=proposer_kind,
        candidate_status=candidate_status,
        created_by_judgment_run_id=created_by_judgment_run_id,
        latest_judgment_run_id=projection.latest_judgment_run_id,
        accepted_by_judgment_run_id=None,
        latest_confidence=projection.latest_confidence,
        latest_confidence_state=projection.latest_confidence_state,
        latest_evidence_summary_json=_json_copy(projection.latest_evidence_summary_json),
        latest_missing_data_summary_json=_json_copy(projection.latest_missing_data_summary_json),
        latest_contradiction_summary_json=_json_copy(projection.latest_contradiction_summary_json),
        reason_summary=reason_summary,
        metadata_json=_json_copy(metadata_json),
        created_by=created_by,
    )
    db.add(candidate)
    db.flush()
    return candidate


def propose_collection_concept_candidate(
    db: Session,
    *,
    collection_id: int,
    concept_node_id: int,
    relation_type: str,
    proposer_kind: str,
    created_by_judgment_run_id: int | None,
    latest_judgment_run_id: int | None = None,
    candidate_status: str = "proposed",
    latest_confidence: float | None = None,
    latest_confidence_state: str | None = None,
    latest_evidence_summary_json: Mapping[str, Any] | None = None,
    latest_missing_data_summary_json: Mapping[str, Any] | None = None,
    latest_contradiction_summary_json: Mapping[str, Any] | None = None,
    reason_summary: str | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    created_by: int | None = None,
) -> CollectionConceptCandidate:
    """提出 collection-concept 候选；不写 collection 成员关系。"""

    projection = _validate_common_candidate_inputs(
        db,
        relation_type=relation_type,
        proposer_kind=proposer_kind,
        candidate_status=candidate_status,
        created_by_judgment_run_id=created_by_judgment_run_id,
        latest_judgment_run_id=latest_judgment_run_id,
        latest_confidence=latest_confidence,
        latest_confidence_state=latest_confidence_state,
        latest_evidence_summary_json=latest_evidence_summary_json,
        latest_missing_data_summary_json=latest_missing_data_summary_json,
        latest_contradiction_summary_json=latest_contradiction_summary_json,
        metadata_json=metadata_json,
    )
    _assert_concept_node_exists(db, concept_node_id)
    _assert_collection_exists(db, collection_id)

    candidate = CollectionConceptCandidate(
        collection_id=collection_id,
        concept_node_id=concept_node_id,
        relation_type=relation_type,
        proposer_kind=proposer_kind,
        candidate_status=candidate_status,
        created_by_judgment_run_id=created_by_judgment_run_id,
        latest_judgment_run_id=projection.latest_judgment_run_id,
        accepted_by_judgment_run_id=None,
        latest_confidence=projection.latest_confidence,
        latest_confidence_state=projection.latest_confidence_state,
        latest_evidence_summary_json=_json_copy(projection.latest_evidence_summary_json),
        latest_missing_data_summary_json=_json_copy(projection.latest_missing_data_summary_json),
        latest_contradiction_summary_json=_json_copy(projection.latest_contradiction_summary_json),
        reason_summary=reason_summary,
        metadata_json=_json_copy(metadata_json),
        created_by=created_by,
    )
    db.add(candidate)
    db.flush()
    return candidate


def _validate_common_candidate_inputs(
    db: Session,
    *,
    relation_type: str,
    proposer_kind: str,
    candidate_status: str,
    created_by_judgment_run_id: int | None,
    latest_judgment_run_id: int | None,
    latest_confidence: float | None,
    latest_confidence_state: str | None,
    latest_evidence_summary_json: Mapping[str, Any] | None,
    latest_missing_data_summary_json: Mapping[str, Any] | None,
    latest_contradiction_summary_json: Mapping[str, Any] | None,
    metadata_json: Mapping[str, Any] | None,
    route_book_id: int | None = None,
    route_version_id: int | None = None,
    segment_id: int | None = None,
) -> _CandidateProjection:
    if created_by_judgment_run_id is None:
        raise ConceptCandidateWriterError("created_by_judgment_run_id is required")
    if latest_judgment_run_id is None:
        latest_judgment_run_id = created_by_judgment_run_id

    if relation_type not in ALLOWED_RELATION_TYPES:
        raise ConceptCandidateWriterError("relation_type is not allowed")
    if proposer_kind not in ALLOWED_PROPOSER_KINDS:
        raise ConceptCandidateWriterError("proposer_kind is not allowed")
    if candidate_status not in ALLOWED_CREATE_STATUSES:
        raise ConceptCandidateWriterError("candidate_status is not allowed for candidate proposal")
    if latest_confidence is not None and not 0 <= latest_confidence <= 1:
        raise ConceptCandidateWriterError("latest_confidence must be between 0 and 1")
    if latest_confidence_state is not None and latest_confidence_state not in ALLOWED_CONFIDENCE_STATES:
        raise ConceptCandidateWriterError("latest_confidence_state is not allowed")

    created_judgment = _succeeded_judgment(
        db,
        created_by_judgment_run_id,
        field_name="created_by_judgment_run_id",
    )
    latest_judgment = _succeeded_judgment(
        db,
        latest_judgment_run_id,
        field_name="latest_judgment_run_id",
    )
    _assert_judgment_target_matches(
        created_judgment,
        field_name="created_by_judgment_run_id",
        route_book_id=route_book_id,
        route_version_id=route_version_id,
        segment_id=segment_id,
    )
    _assert_judgment_target_matches(
        latest_judgment,
        field_name="latest_judgment_run_id",
        route_book_id=route_book_id,
        route_version_id=route_version_id,
        segment_id=segment_id,
    )
    _assert_candidate_metadata_safe(metadata_json)
    return _project_candidate_from_latest_judgment(
        latest_judgment,
        latest_confidence=latest_confidence,
        latest_confidence_state=latest_confidence_state,
        latest_evidence_summary_json=latest_evidence_summary_json,
        latest_missing_data_summary_json=latest_missing_data_summary_json,
        latest_contradiction_summary_json=latest_contradiction_summary_json,
    )


def _succeeded_judgment(db: Session, judgment_run_id: int, *, field_name: str) -> _JudgmentSnapshot:
    judgment = (
        db.query(
            JudgmentRun.id,
            JudgmentRun.run_type,
            JudgmentRun.status,
            JudgmentRun.route_book_id,
            JudgmentRun.route_version_id,
            JudgmentRun.segment_id,
            JudgmentRun.confidence,
            JudgmentRun.confidence_state,
            JudgmentRun.result_summary_json,
            JudgmentRun.missing_data_json,
            JudgmentRun.contradiction_json,
        )
        .filter(JudgmentRun.id == judgment_run_id)
        .first()
    )
    if judgment is None:
        raise ConceptCandidateWriterError(f"{field_name} judgment_run does not exist")
    if judgment.run_type not in ALLOWED_JUDGMENT_RUN_TYPES:
        raise ConceptCandidateWriterError(f"{field_name} judgment_run run_type is not allowed")
    if judgment.status != "succeeded":
        raise ConceptCandidateWriterError(f"{field_name} judgment_run status must be succeeded")
    return _JudgmentSnapshot(
        id=judgment.id,
        run_type=judgment.run_type,
        status=judgment.status,
        route_book_id=judgment.route_book_id,
        route_version_id=judgment.route_version_id,
        segment_id=judgment.segment_id,
        confidence=_confidence_to_float(judgment.confidence),
        confidence_state=judgment.confidence_state,
        result_summary_json=judgment.result_summary_json,
        missing_data_json=judgment.missing_data_json,
        contradiction_json=judgment.contradiction_json,
    )


def _assert_judgment_target_matches(
    judgment: _JudgmentSnapshot,
    *,
    field_name: str,
    route_book_id: int | None,
    route_version_id: int | None,
    segment_id: int | None,
) -> None:
    if route_book_id is not None and judgment.route_book_id is not None and judgment.route_book_id != route_book_id:
        raise ConceptCandidateWriterError(f"{field_name} judgment_run route_book_id must match target")
    if (
        route_version_id is not None
        and judgment.route_version_id is not None
        and judgment.route_version_id != route_version_id
    ):
        raise ConceptCandidateWriterError(f"{field_name} judgment_run route_version_id must match target")
    if segment_id is not None and judgment.segment_id is not None and judgment.segment_id != segment_id:
        raise ConceptCandidateWriterError(f"{field_name} judgment_run segment_id must match target")


def _project_candidate_from_latest_judgment(
    judgment: _JudgmentSnapshot,
    *,
    latest_confidence: float | None,
    latest_confidence_state: str | None,
    latest_evidence_summary_json: Mapping[str, Any] | None,
    latest_missing_data_summary_json: Mapping[str, Any] | None,
    latest_contradiction_summary_json: Mapping[str, Any] | None,
) -> _CandidateProjection:
    _assert_optional_projection_matches(
        "latest_confidence",
        latest_confidence,
        judgment.confidence,
    )
    _assert_optional_projection_matches(
        "latest_confidence_state",
        latest_confidence_state,
        judgment.confidence_state,
    )
    _assert_optional_projection_matches(
        "latest_evidence_summary_json",
        latest_evidence_summary_json,
        judgment.result_summary_json,
    )
    _assert_optional_projection_matches(
        "latest_missing_data_summary_json",
        latest_missing_data_summary_json,
        judgment.missing_data_json,
    )
    _assert_optional_projection_matches(
        "latest_contradiction_summary_json",
        latest_contradiction_summary_json,
        judgment.contradiction_json,
    )
    return _CandidateProjection(
        latest_judgment_run_id=judgment.id,
        latest_confidence=judgment.confidence,
        latest_confidence_state=judgment.confidence_state,
        latest_evidence_summary_json=judgment.result_summary_json,
        latest_missing_data_summary_json=judgment.missing_data_json,
        latest_contradiction_summary_json=judgment.contradiction_json,
    )


def _assert_optional_projection_matches(field_name: str, supplied: Any, projected: Any) -> None:
    if supplied is None:
        return
    if supplied != projected:
        raise ConceptCandidateWriterError(f"{field_name} must match latest_judgment_run projection")


def _assert_concept_node_exists(db: Session, concept_node_id: int) -> None:
    exists = db.query(ConceptNode.id).filter(ConceptNode.id == concept_node_id).first()
    if exists is None:
        raise ConceptCandidateWriterError("concept_node does not exist")


def _assert_collection_exists(db: Session, collection_id: int) -> None:
    exists = db.query(RouteCollection.id).filter(RouteCollection.id == collection_id).first()
    if exists is None:
        raise ConceptCandidateWriterError("collection does not exist")


def _route_line_hash_for_version(db: Session, *, route_book_id: int, route_version_id: int) -> str:
    route_book = db.query(RouteBook.id).filter(RouteBook.id == route_book_id).first()
    if route_book is None:
        raise ConceptCandidateWriterError("route_book does not exist")

    route_version = (
        db.query(RouteVersion.id, RouteVersion.route_book_id, RouteVersion.line_hash)
        .filter(RouteVersion.id == route_version_id)
        .first()
    )
    if route_version is None or route_version.route_book_id != route_book_id:
        raise ConceptCandidateWriterError("route_version does not belong to route_book")
    return route_version.line_hash


def _segment_geometry_hash(db: Session, segment_id: int) -> str:
    segment = (
        db.query(RouteCognitionSegment.segment_id, RouteCognitionSegment.geometry_hash)
        .filter(RouteCognitionSegment.segment_id == segment_id)
        .first()
    )
    if segment is None:
        raise ConceptCandidateWriterError("segment_id must exist in route_cognition_segments")
    return segment.geometry_hash


def _assert_candidate_metadata_safe(metadata_json: Mapping[str, Any] | None) -> None:
    try:
        assert_metadata_has_no_relationship_truth(metadata_json)
    except WriteGuardError as error:
        raise ConceptCandidateWriterError(str(error)) from error

    forbidden_key = _find_forbidden_metadata_key(metadata_json)
    if forbidden_key is not None:
        raise ConceptCandidateWriterError(f"metadata_json contains forbidden key: {forbidden_key}")


def _find_forbidden_metadata_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                if _is_forbidden_key(key):
                    return key
                if _is_relationship_entity_descriptor(key, child):
                    return key
            nested_key = _find_forbidden_metadata_key(child)
            if nested_key is not None:
                return nested_key
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            nested_key = _find_forbidden_metadata_key(item)
            if nested_key is not None:
                return nested_key
    return None


def _is_forbidden_key(key: str) -> bool:
    normalized_key = _normalize_metadata_key(key)
    if normalized_key in FORBIDDEN_CANDIDATE_METADATA_KEYS:
        return True
    for prefix in RELATIONSHIP_KEY_PREFIXES:
        if not normalized_key.startswith(f"{prefix}_"):
            continue
        suffix = normalized_key.removeprefix(f"{prefix}_")
        if suffix in RELATIONSHIP_KEY_SUFFIXES:
            return True
    return False


def _is_relationship_entity_descriptor(key: str, value: Any) -> bool:
    if _normalize_metadata_key(key) not in ENTITY_DISCRIMINATOR_KEYS:
        return False
    if not isinstance(value, str):
        return False
    normalized_value = value.strip().lower().replace("-", "_")
    return normalized_value in RELATIONSHIP_ENTITY_VALUES


def _normalize_metadata_key(key: str) -> str:
    snake_key = re.sub(r"(?<!^)(?=[A-Z])", "_", key)
    snake_key = snake_key.replace("-", "_").replace(" ", "_").lower()
    return re.sub(r"_+", "_", snake_key).strip("_")


def _confidence_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _json_copy(value: Any) -> Any:
    return deepcopy(value) if value is not None else None
