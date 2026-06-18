"""路线认知写入门禁——像检票口一样，先验票再允许内部 writer 入库。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.route_cognition.models import JudgmentRun


ACCEPTED_HUMAN_REVIEW_CONFIDENCE_STATES = {"human_accepted", "stable"}

FORBIDDEN_METADATA_KEYS = {
    "accepted_by_judgment_run_id",
    "accepted_judgment_run_id",
    "accepted_judgment_run_type",
    "candidate_status",
    "collection_route",
    "collection_routes",
    "collection_segment",
    "collection_segments",
    "route_id",
    "route_ids",
    "route_book_id",
    "route_book_ids",
    "route_line_hash",
    "route_segment",
    "route_segments",
    "route_version_id",
    "route_version_ids",
    "segment_id",
    "segment_ids",
    "segment_geometry_hash",
    "collection_id",
    "collection_ids",
    "concept_node_id",
    "component_geometry",
    "component_geometry_hash",
    "component_type",
    "route_concept_link",
    "route_concept_links",
    "segment_concept_link",
    "segment_concept_links",
    "collection_concept_link",
    "collection_concept_links",
    "route_concept_candidate",
    "route_concept_candidates",
    "segment_concept_candidate",
    "segment_concept_candidates",
    "collection_concept_candidate",
    "collection_concept_candidates",
    "reviewed_route_line_hash",
    "reviewed_route_version_id",
    "relation_type",
    "formal_relationship",
    "formal_relationships",
    "formal_relationship_truth",
    "source_collection_concept_candidate_id",
    "source_kind",
    "source_route_concept_candidate_id",
    "source_segment_concept_candidate_id",
    "relationship_truth",
    "candidate_truth",
}


class WriteGuardError(ValueError):
    """路线认知写入门禁失败——调用方应停止写入，而不是绕过 service 直写表。"""


def assert_human_review_judgment(db: Session, judgment_run_id: int) -> None:
    """确认 judgment_run 是已经成功的人审结果。"""

    judgment = (
        db.query(
            JudgmentRun.id,
            JudgmentRun.run_type,
            JudgmentRun.status,
            JudgmentRun.confidence_state,
        )
        .filter(JudgmentRun.id == judgment_run_id)
        .first()
    )
    if judgment is None:
        raise WriteGuardError(f"judgment_run {judgment_run_id} does not exist")
    if judgment.run_type != "human_review":
        raise WriteGuardError("source_judgment_run_id must point to a human_review judgment_run")
    if judgment.status != "succeeded":
        raise WriteGuardError("source_judgment_run_id judgment_run status must be succeeded")
    if judgment.confidence_state not in ACCEPTED_HUMAN_REVIEW_CONFIDENCE_STATES:
        raise WriteGuardError(
            "source_judgment_run_id judgment_run confidence_state must be human_accepted or stable"
        )


def assert_not_public_without_published(visibility: str, publish_status: str) -> None:
    """公开可见就必须已经发布，避免草稿被用户看到。"""

    if visibility == "public" and publish_status != "published":
        raise WriteGuardError("visibility public requires publish_status published")


def assert_published_has_judgment(
    publish_status: str,
    source_judgment_run_id: int | None,
) -> None:
    """发布状态必须带人审来源编号。"""

    if publish_status == "published" and source_judgment_run_id is None:
        raise WriteGuardError("publish_status published requires source_judgment_run_id")


def assert_imported_has_source(
    source: str,
    source_ref: str | None,
    source_judgment_run_id: int | None,
) -> None:
    """导入数据必须留下外部来源或人审来源。"""

    if source == "imported" and not _has_text(source_ref) and source_judgment_run_id is None:
        raise WriteGuardError("source imported requires source_ref or source_judgment_run_id")


def assert_metadata_has_no_relationship_truth(metadata_json: Mapping[str, Any] | None) -> None:
    """metadata_json 只能做补充说明，不能偷偷存路线/赛段/集合关系真相。"""

    if metadata_json is None:
        return
    if not isinstance(metadata_json, Mapping):
        raise WriteGuardError("metadata_json must be an object")

    forbidden_key = _find_forbidden_metadata_key(metadata_json)
    if forbidden_key is not None:
        raise WriteGuardError(f"metadata_json contains forbidden key: {forbidden_key}")


def _has_text(value: str | None) -> bool:
    return value is not None and value.strip() != ""


def _find_forbidden_metadata_key(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and key in FORBIDDEN_METADATA_KEYS:
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
