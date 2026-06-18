"""概念写入服务——只给路线认知创建概念身份证，不写任何关系真相。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.route_cognition.models import ConceptNode
from app.route_cognition.services.write_guard import (
    WriteGuardError,
    assert_human_review_judgment,
    assert_imported_has_source,
    assert_metadata_has_no_relationship_truth,
    assert_not_public_without_published,
    assert_published_has_judgment,
)


ALLOWED_NODE_TYPES = {
    "practice_type",
    "landmark",
    "road_condition",
    "safety_risk",
    "event",
    "local_term",
    "place",
    "training_theme",
    "other",
}
ALLOWED_SCOPE_TYPES = {"global", "city", "region"}
ALLOWED_VISIBILITIES = {"private", "unlisted", "public"}
ALLOWED_PUBLISH_STATUSES = {"draft", "published", "archived"}
ALLOWED_SOURCES = {"manual", "imported"}
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,127}$")


class ConceptWriterError(ValueError):
    """概念写入失败——调用方应把原因交给内部审核者处理。"""


def create_concept_node(
    db: Session,
    *,
    name: str,
    slug: str,
    node_type: str,
    scope_type: str = "global",
    scope_value: str = "global",
    city: str | None = None,
    region: str | None = None,
    visibility: str = "private",
    publish_status: str = "draft",
    summary: str | None = None,
    description_md: str | None = None,
    cover_url: str | None = None,
    center_lat: float | None = None,
    center_lon: float | None = None,
    source: str = "manual",
    source_ref: str | None = None,
    confidence: float | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    source_judgment_run_id: int | None = None,
    created_by: int | None = None,
) -> ConceptNode:
    """
    创建一个概念节点。

    这里故意不接 evidence 入参：概念说明必须由调用方显式传入，不能从证据自动拼出对外文案。
    """

    _validate_identity_fields(
        name=name,
        slug=slug,
        node_type=node_type,
        scope_type=scope_type,
        scope_value=scope_value,
        visibility=visibility,
        publish_status=publish_status,
        source=source,
    )
    _validate_optional_geo(center_lat=center_lat, center_lon=center_lon)
    _validate_confidence(confidence)
    _run_shared_guards(
        db,
        visibility=visibility,
        publish_status=publish_status,
        source=source,
        source_ref=source_ref,
        source_judgment_run_id=source_judgment_run_id,
        metadata_json=metadata_json,
    )

    node = ConceptNode(
        name=name,
        slug=slug,
        node_type=node_type,
        scope_type=scope_type,
        scope_value=scope_value,
        city=city,
        region=region,
        visibility=visibility,
        publish_status=publish_status,
        summary=summary,
        description_md=description_md,
        cover_url=cover_url,
        center_lat=center_lat,
        center_lon=center_lon,
        source=source,
        source_ref=source_ref,
        confidence=confidence,
        metadata_json=dict(metadata_json) if metadata_json is not None else None,
        source_judgment_run_id=source_judgment_run_id,
        created_by=created_by,
    )
    db.add(node)
    db.flush()
    return node


def _validate_identity_fields(
    *,
    name: str,
    slug: str,
    node_type: str,
    scope_type: str,
    scope_value: str,
    visibility: str,
    publish_status: str,
    source: str,
) -> None:
    if not name.strip():
        raise ConceptWriterError("name must not be empty")
    if not SLUG_PATTERN.fullmatch(slug):
        raise ConceptWriterError("slug must match lowercase alnum, underscore, or hyphen format")
    if node_type not in ALLOWED_NODE_TYPES:
        raise ConceptWriterError("node_type is not allowed")
    if scope_type not in ALLOWED_SCOPE_TYPES:
        raise ConceptWriterError("scope_type is not allowed")
    if scope_type == "global" and scope_value != "global":
        raise ConceptWriterError("global scope_type requires scope_value global")
    if scope_type in {"city", "region"} and (not scope_value.strip() or scope_value == "global"):
        raise ConceptWriterError("local scope_type requires a non-global scope_value")
    if visibility not in ALLOWED_VISIBILITIES:
        raise ConceptWriterError("visibility is not allowed")
    if publish_status not in ALLOWED_PUBLISH_STATUSES:
        raise ConceptWriterError("publish_status is not allowed")
    if source not in ALLOWED_SOURCES:
        raise ConceptWriterError("source is not allowed")


def _validate_optional_geo(center_lat: float | None, center_lon: float | None) -> None:
    if (center_lat is None) != (center_lon is None):
        raise ConceptWriterError("center_lat and center_lon must be provided together")
    if center_lat is not None and not -90 <= center_lat <= 90:
        raise ConceptWriterError("center_lat must be between -90 and 90")
    if center_lon is not None and not -180 <= center_lon <= 180:
        raise ConceptWriterError("center_lon must be between -180 and 180")


def _validate_confidence(confidence: float | None) -> None:
    if confidence is not None and not 0 <= confidence <= 1:
        raise ConceptWriterError("confidence must be between 0 and 1")


def _run_shared_guards(
    db: Session,
    *,
    visibility: str,
    publish_status: str,
    source: str,
    source_ref: str | None,
    source_judgment_run_id: int | None,
    metadata_json: Mapping[str, Any] | None,
) -> None:
    try:
        assert_not_public_without_published(visibility, publish_status)
        assert_published_has_judgment(publish_status, source_judgment_run_id)
        assert_imported_has_source(source, source_ref, source_judgment_run_id)
        assert_metadata_has_no_relationship_truth(metadata_json)
        if source_judgment_run_id is not None:
            assert_human_review_judgment(db, source_judgment_run_id)
    except WriteGuardError as error:
        raise ConceptWriterError(str(error)) from error
