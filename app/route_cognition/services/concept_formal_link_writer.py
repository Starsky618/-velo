"""概念正式关系写入服务——像盖章窗口，只把已审过的候选转进正式档案。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.route_book.models import RouteBook, RouteVersion
from app.route_cognition.models import (
    CollectionConceptCandidate,
    CollectionConceptLink,
    ConceptNode,
    JudgmentRun,
    RouteCognitionSegment,
    RouteCollection,
    RouteConceptCandidate,
    RouteConceptLink,
    SegmentConceptCandidate,
    SegmentConceptLink,
)
from app.route_cognition.services.write_guard import (
    WriteGuardError,
    assert_human_review_judgment,
)


PROMOTABLE_CANDIDATE_STATUSES = {"proposed", "needs_review"}


class ConceptFormalLinkWriterError(ValueError):
    """正式关系转正失败——调用方应停在审核流程外，而不是绕过 writer 直写 link。"""


@dataclass(frozen=True)
class _AcceptedJudgmentProjection:
    id: int
    run_type: str
    route_book_id: int | None
    route_version_id: int | None
    segment_id: int | None
    confidence: float | None
    confidence_state: str
    result_summary_json: Any
    missing_data_json: Any
    contradiction_json: Any


def promote_route_concept_candidate(
    db: Session,
    *,
    candidate_id: int,
    accepted_judgment_run_id: int,
    reviewed_by: int | None = None,
) -> RouteConceptLink:
    """把 route-concept 候选转成正式 link；不创建路线段、不写内容。"""

    accepted_judgment = _accepted_human_review_projection(db, accepted_judgment_run_id)
    with db.begin_nested():
        candidate = _route_candidate(db, candidate_id)
        _assert_candidate_can_be_promoted(candidate)
        _assert_concept_node_exists(db, candidate.concept_node_id)
        _assert_accepted_judgment_target_matches(
            accepted_judgment,
            target_kind="route",
            route_book_id=candidate.route_book_id,
            route_version_id=candidate.route_version_id,
        )
        _assert_route_target_still_matches_candidate(
            db,
            route_book_id=candidate.route_book_id,
            route_version_id=candidate.route_version_id,
            route_line_hash=candidate.route_line_hash,
        )
        _mark_candidate_accepted(
            candidate,
            accepted_judgment=accepted_judgment,
            reviewed_by=reviewed_by,
        )
        db.flush()

        link = RouteConceptLink(
            route_book_id=candidate.route_book_id,
            route_version_id=candidate.route_version_id,
            route_line_hash=candidate.route_line_hash,
            concept_node_id=candidate.concept_node_id,
            relation_type=candidate.relation_type,
            link_status="active",
            source_kind="candidate_accepted",
            accepted_judgment_run_id=accepted_judgment.id,
            accepted_judgment_run_type="human_review",
            source_route_concept_candidate_id=candidate.id,
            reason_summary=candidate.reason_summary,
            metadata_json=None,
            created_by=reviewed_by,
        )
        db.add(link)
        db.flush()
        return link


def promote_segment_concept_candidate(
    db: Session,
    *,
    candidate_id: int,
    accepted_judgment_run_id: int,
    reviewed_by: int | None = None,
) -> SegmentConceptLink:
    """把 segment-concept 候选转成正式 link；segment 必须仍在认知白名单里。"""

    accepted_judgment = _accepted_human_review_projection(db, accepted_judgment_run_id)
    with db.begin_nested():
        candidate = _segment_candidate(db, candidate_id)
        _assert_candidate_can_be_promoted(candidate)
        _assert_concept_node_exists(db, candidate.concept_node_id)
        _assert_accepted_judgment_target_matches(
            accepted_judgment,
            target_kind="segment",
            segment_id=candidate.segment_id,
        )
        _assert_segment_target_still_matches_candidate(
            db,
            segment_id=candidate.segment_id,
            segment_geometry_hash=candidate.segment_geometry_hash,
        )
        _mark_candidate_accepted(
            candidate,
            accepted_judgment=accepted_judgment,
            reviewed_by=reviewed_by,
        )
        db.flush()

        link = SegmentConceptLink(
            segment_id=candidate.segment_id,
            segment_geometry_hash=candidate.segment_geometry_hash,
            concept_node_id=candidate.concept_node_id,
            relation_type=candidate.relation_type,
            link_status="active",
            source_kind="candidate_accepted",
            accepted_judgment_run_id=accepted_judgment.id,
            accepted_judgment_run_type="human_review",
            source_segment_concept_candidate_id=candidate.id,
            reason_summary=candidate.reason_summary,
            metadata_json=None,
            created_by=reviewed_by,
        )
        db.add(link)
        db.flush()
        return link


def promote_collection_concept_candidate(
    db: Session,
    *,
    candidate_id: int,
    accepted_judgment_run_id: int,
    reviewed_by: int | None = None,
) -> CollectionConceptLink:
    """把 collection-concept 候选转成正式 link；不写 collection 成员表。"""

    accepted_judgment = _accepted_human_review_projection(db, accepted_judgment_run_id)
    with db.begin_nested():
        candidate = _collection_candidate(db, candidate_id)
        _assert_candidate_can_be_promoted(candidate)
        _assert_concept_node_exists(db, candidate.concept_node_id)
        _assert_accepted_judgment_target_matches(
            accepted_judgment,
            target_kind="collection",
        )
        _assert_collection_target_still_exists(db, candidate.collection_id)
        _mark_candidate_accepted(
            candidate,
            accepted_judgment=accepted_judgment,
            reviewed_by=reviewed_by,
        )
        db.flush()

        link = CollectionConceptLink(
            collection_id=candidate.collection_id,
            concept_node_id=candidate.concept_node_id,
            relation_type=candidate.relation_type,
            link_status="active",
            source_kind="candidate_accepted",
            accepted_judgment_run_id=accepted_judgment.id,
            accepted_judgment_run_type="human_review",
            source_collection_concept_candidate_id=candidate.id,
            reason_summary=candidate.reason_summary,
            metadata_json=None,
            created_by=reviewed_by,
        )
        db.add(link)
        db.flush()
        return link


def _accepted_human_review_projection(db: Session, judgment_run_id: int) -> _AcceptedJudgmentProjection:
    try:
        assert_human_review_judgment(db, judgment_run_id)
    except WriteGuardError as error:
        raise ConceptFormalLinkWriterError(str(error)) from error

    judgment = (
        db.query(
            JudgmentRun.id,
            JudgmentRun.run_type,
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
        raise ConceptFormalLinkWriterError(f"accepted_judgment_run_id {judgment_run_id} does not exist")

    return _AcceptedJudgmentProjection(
        id=judgment.id,
        run_type=judgment.run_type,
        route_book_id=judgment.route_book_id,
        route_version_id=judgment.route_version_id,
        segment_id=judgment.segment_id,
        confidence=_confidence_to_float(judgment.confidence),
        confidence_state=judgment.confidence_state,
        result_summary_json=deepcopy(judgment.result_summary_json),
        missing_data_json=deepcopy(judgment.missing_data_json),
        contradiction_json=deepcopy(judgment.contradiction_json),
    )


def _route_candidate(db: Session, candidate_id: int) -> RouteConceptCandidate:
    candidate = (
        db.query(RouteConceptCandidate)
        .filter(RouteConceptCandidate.id == candidate_id)
        .with_for_update()
        .first()
    )
    if candidate is None:
        raise ConceptFormalLinkWriterError("route concept candidate does not exist")
    return candidate


def _segment_candidate(db: Session, candidate_id: int) -> SegmentConceptCandidate:
    candidate = (
        db.query(SegmentConceptCandidate)
        .filter(SegmentConceptCandidate.id == candidate_id)
        .with_for_update()
        .first()
    )
    if candidate is None:
        raise ConceptFormalLinkWriterError("segment concept candidate does not exist")
    return candidate


def _collection_candidate(db: Session, candidate_id: int) -> CollectionConceptCandidate:
    candidate = (
        db.query(CollectionConceptCandidate)
        .filter(CollectionConceptCandidate.id == candidate_id)
        .with_for_update()
        .first()
    )
    if candidate is None:
        raise ConceptFormalLinkWriterError("collection concept candidate does not exist")
    return candidate


def _assert_candidate_can_be_promoted(candidate: Any) -> None:
    if candidate.candidate_status not in PROMOTABLE_CANDIDATE_STATUSES:
        raise ConceptFormalLinkWriterError("candidate_status is not promotable")
    if candidate.accepted_by_judgment_run_id is not None:
        raise ConceptFormalLinkWriterError("candidate already has accepted_by_judgment_run_id")


def _mark_candidate_accepted(
    candidate: Any,
    *,
    accepted_judgment: _AcceptedJudgmentProjection,
    reviewed_by: int | None,
) -> None:
    candidate.candidate_status = "accepted"
    candidate.accepted_by_judgment_run_id = accepted_judgment.id
    candidate.latest_judgment_run_id = accepted_judgment.id
    candidate.latest_confidence = accepted_judgment.confidence
    candidate.latest_confidence_state = accepted_judgment.confidence_state
    candidate.latest_evidence_summary_json = deepcopy(accepted_judgment.result_summary_json)
    candidate.latest_missing_data_summary_json = deepcopy(accepted_judgment.missing_data_json)
    candidate.latest_contradiction_summary_json = deepcopy(accepted_judgment.contradiction_json)
    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = datetime.now(UTC)


def _assert_concept_node_exists(db: Session, concept_node_id: int) -> None:
    exists = db.query(ConceptNode.id).filter(ConceptNode.id == concept_node_id).first()
    if exists is None:
        raise ConceptFormalLinkWriterError("concept_node does not exist")


def _assert_accepted_judgment_target_matches(
    accepted_judgment: _AcceptedJudgmentProjection,
    *,
    target_kind: str,
    route_book_id: int | None = None,
    route_version_id: int | None = None,
    segment_id: int | None = None,
) -> None:
    if target_kind == "route" and accepted_judgment.segment_id is not None:
        raise ConceptFormalLinkWriterError("accepted_judgment_run_id segment_id must be empty for route candidate")
    if target_kind == "segment":
        if accepted_judgment.route_book_id is not None:
            raise ConceptFormalLinkWriterError("accepted_judgment_run_id route_book_id must be empty for segment candidate")
        if accepted_judgment.route_version_id is not None:
            raise ConceptFormalLinkWriterError(
                "accepted_judgment_run_id route_version_id must be empty for segment candidate"
            )
    if target_kind == "collection" and (
        accepted_judgment.route_book_id is not None
        or accepted_judgment.route_version_id is not None
        or accepted_judgment.segment_id is not None
    ):
        raise ConceptFormalLinkWriterError(
            "accepted_judgment_run_id target fields must be empty for collection candidate"
        )

    if (
        route_book_id is not None
        and accepted_judgment.route_book_id is not None
        and accepted_judgment.route_book_id != route_book_id
    ):
        raise ConceptFormalLinkWriterError("accepted_judgment_run_id route_book_id must match candidate")
    if (
        route_version_id is not None
        and accepted_judgment.route_version_id is not None
        and accepted_judgment.route_version_id != route_version_id
    ):
        raise ConceptFormalLinkWriterError("accepted_judgment_run_id route_version_id must match candidate")
    if segment_id is not None and accepted_judgment.segment_id is not None and accepted_judgment.segment_id != segment_id:
        raise ConceptFormalLinkWriterError("accepted_judgment_run_id segment_id must match candidate")


def _assert_route_target_still_matches_candidate(
    db: Session,
    *,
    route_book_id: int,
    route_version_id: int,
    route_line_hash: str,
) -> None:
    route_book = db.query(RouteBook.id).filter(RouteBook.id == route_book_id).first()
    if route_book is None:
        raise ConceptFormalLinkWriterError("route_book does not exist")

    route_version = (
        db.query(RouteVersion.id, RouteVersion.route_book_id, RouteVersion.line_hash)
        .filter(RouteVersion.id == route_version_id)
        .first()
    )
    if route_version is None or route_version.route_book_id != route_book_id:
        raise ConceptFormalLinkWriterError("route_version does not belong to route_book")
    if route_version.line_hash != route_line_hash:
        raise ConceptFormalLinkWriterError("route_line_hash no longer matches route_version")


def _assert_segment_target_still_matches_candidate(
    db: Session,
    *,
    segment_id: int,
    segment_geometry_hash: str,
) -> None:
    segment = (
        db.query(RouteCognitionSegment.segment_id, RouteCognitionSegment.geometry_hash)
        .filter(RouteCognitionSegment.segment_id == segment_id)
        .first()
    )
    if segment is None:
        raise ConceptFormalLinkWriterError("segment_id must exist in route_cognition_segments")
    if segment.geometry_hash != segment_geometry_hash:
        raise ConceptFormalLinkWriterError("segment_geometry_hash no longer matches route_cognition_segments")


def _assert_collection_target_still_exists(db: Session, collection_id: int) -> None:
    collection = db.query(RouteCollection.id).filter(RouteCollection.id == collection_id).first()
    if collection is None:
        raise ConceptFormalLinkWriterError("collection does not exist")


def _confidence_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)
