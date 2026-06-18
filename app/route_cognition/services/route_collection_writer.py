"""路线专题写入服务——只给 route_collections 发“专题身份证”，不装任何成员关系。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.route_cognition.models import RouteCollection
from app.route_cognition.services.write_guard import (
    WriteGuardError,
    assert_human_review_judgment,
    assert_imported_has_source,
    assert_metadata_has_no_relationship_truth,
    assert_not_public_without_published,
    assert_published_has_judgment,
)


ALLOWED_COLLECTION_TYPES = {
    "area_system",
    "route_family",
    "race_route_family",
    "training_corridor",
    "theme_pack",
    "other",
}
ALLOWED_VISIBILITIES = {"private", "unlisted", "public"}
ALLOWED_PUBLISH_STATUSES = {"draft", "published", "archived"}
ALLOWED_SOURCES = {"manual", "imported"}
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,127}$")

ROUTE_COLLECTION_FORBIDDEN_MEMBERSHIP_KEYS = {
    "candidate_id",
    "candidate_ids",
    "candidate",
    "candidates",
    "concept_id",
    "concept_ids",
    "concept",
    "concepts",
    "collection",
    "collections",
    "member",
    "member_id",
    "member_ids",
    "members",
    "membership",
    "membership_id",
    "membership_ids",
    "memberships",
    "route",
    "routes",
    "route_book",
    "route_books",
    "route_version",
    "route_versions",
    "segment",
    "segments",
}
ROUTE_COLLECTION_FORBIDDEN_STATS_KEYS = ROUTE_COLLECTION_FORBIDDEN_MEMBERSHIP_KEYS | {
    "display_priority",
    "importance",
    "order",
    "ordering",
    "role",
    "roles",
    "seq",
    "sequence",
}
ROUTE_COLLECTION_RELATIONSHIP_KEY_PREFIXES = (
    "candidate",
    "collection_route",
    "collection_segment",
    "concept",
    "member",
    "membership",
    "route",
    "route_book",
    "route_version",
    "segment",
)
ROUTE_COLLECTION_RELATIONSHIP_KEY_SUFFIXES = (
    "display_priority",
    "hash",
    "hashes",
    "id",
    "ids",
    "importance",
    "name",
    "names",
    "order",
    "ordering",
    "ref",
    "refs",
    "role",
    "roles",
    "seq",
    "sequence",
    "slug",
    "slugs",
    "status",
    "statuses",
)
ROUTE_COLLECTION_ENTITY_DISCRIMINATOR_KEYS = {
    "entity_type",
    "kind",
    "member_type",
    "object_type",
    "source_type",
    "target_type",
    "type",
}
ROUTE_COLLECTION_RELATIONSHIP_ENTITY_VALUES = {
    "candidate",
    "candidates",
    "collection",
    "collection_route",
    "collection_routes",
    "collection_segment",
    "collection_segments",
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
    "route_version",
    "route_versions",
    "routes",
    "segment",
    "segments",
}


class RouteCollectionWriterError(ValueError):
    """路线专题写入失败——调用方应停止写入，并把原因交给内部审核者处理。"""


def create_route_collection(
    db: Session,
    *,
    name: str,
    slug: str,
    collection_type: str,
    city: str = "unknown",
    visibility: str = "private",
    publish_status: str = "draft",
    description_md: str | None = None,
    cover_url: str | None = None,
    center_lat: float | None = None,
    center_lon: float | None = None,
    source: str = "manual",
    source_ref: str | None = None,
    confidence: float | None = None,
    stats_json: Mapping[str, Any] | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    source_judgment_run_id: int | None = None,
    created_by: int | None = None,
) -> RouteCollection:
    """创建路线专题本体；路线、赛段、概念成员必须走后续独立 writer。"""

    _validate_identity_fields(
        name=name,
        slug=slug,
        collection_type=collection_type,
        city=city,
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
        stats_json=stats_json,
    )

    collection = RouteCollection(
        name=name,
        slug=slug,
        collection_type=collection_type,
        city=city,
        visibility=visibility,
        publish_status=publish_status,
        description_md=description_md,
        cover_url=cover_url,
        center_lat=center_lat,
        center_lon=center_lon,
        source=source,
        source_ref=source_ref,
        confidence=confidence,
        stats_json=dict(stats_json) if stats_json is not None else None,
        metadata_json=dict(metadata_json) if metadata_json is not None else None,
        source_judgment_run_id=source_judgment_run_id,
        created_by=created_by,
    )
    db.add(collection)
    db.flush()
    return collection


def _validate_identity_fields(
    *,
    name: str,
    slug: str,
    collection_type: str,
    city: str,
    visibility: str,
    publish_status: str,
    source: str,
) -> None:
    if not _has_text(name):
        raise RouteCollectionWriterError("name must not be empty")
    if not SLUG_PATTERN.fullmatch(slug):
        raise RouteCollectionWriterError("slug must match lowercase alnum, underscore, or hyphen format")
    if collection_type not in ALLOWED_COLLECTION_TYPES:
        raise RouteCollectionWriterError("collection_type is not allowed")
    if not _has_text(city):
        raise RouteCollectionWriterError("city must not be empty")
    if visibility not in ALLOWED_VISIBILITIES:
        raise RouteCollectionWriterError("visibility is not allowed")
    if publish_status not in ALLOWED_PUBLISH_STATUSES:
        raise RouteCollectionWriterError("publish_status is not allowed")
    if source not in ALLOWED_SOURCES:
        raise RouteCollectionWriterError("source is not allowed")


def _validate_optional_geo(center_lat: float | None, center_lon: float | None) -> None:
    if (center_lat is None) != (center_lon is None):
        raise RouteCollectionWriterError("center_lat and center_lon must be provided together")
    if center_lat is not None and not -90 <= center_lat <= 90:
        raise RouteCollectionWriterError("center_lat must be between -90 and 90")
    if center_lon is not None and not -180 <= center_lon <= 180:
        raise RouteCollectionWriterError("center_lon must be between -180 and 180")


def _validate_confidence(confidence: float | None) -> None:
    if confidence is not None and not 0 <= confidence <= 1:
        raise RouteCollectionWriterError("confidence must be between 0 and 1")


def _run_shared_guards(
    db: Session,
    *,
    visibility: str,
    publish_status: str,
    source: str,
    source_ref: str | None,
    source_judgment_run_id: int | None,
    metadata_json: Mapping[str, Any] | None,
    stats_json: Mapping[str, Any] | None,
) -> None:
    try:
        assert_not_public_without_published(visibility, publish_status)
        assert_published_has_judgment(publish_status, source_judgment_run_id)
        assert_imported_has_source(source, source_ref, source_judgment_run_id)
        assert_metadata_has_no_relationship_truth(metadata_json)
        if source_judgment_run_id is not None:
            assert_human_review_judgment(db, source_judgment_run_id)
    except WriteGuardError as error:
        raise RouteCollectionWriterError(str(error)) from error

    _assert_mapping_has_no_forbidden_keys(
        metadata_json,
        field_name="metadata_json",
        forbidden_keys=ROUTE_COLLECTION_FORBIDDEN_MEMBERSHIP_KEYS,
    )
    _assert_mapping_has_no_forbidden_keys(
        stats_json,
        field_name="stats_json",
        forbidden_keys=ROUTE_COLLECTION_FORBIDDEN_STATS_KEYS,
    )
    try:
        assert_metadata_has_no_relationship_truth(stats_json)
    except WriteGuardError as error:
        raise RouteCollectionWriterError(str(error).replace("metadata_json", "stats_json")) from error


def _assert_mapping_has_no_forbidden_keys(
    value: Mapping[str, Any] | None,
    *,
    field_name: str,
    forbidden_keys: set[str],
) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise RouteCollectionWriterError(f"{field_name} must be an object")

    forbidden_key = _find_forbidden_key(value, forbidden_keys)
    if forbidden_key is not None:
        raise RouteCollectionWriterError(f"{field_name} contains forbidden key: {forbidden_key}")


def _find_forbidden_key(value: Any, forbidden_keys: set[str]) -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                if _is_forbidden_key(key, forbidden_keys):
                    return key
                if _is_relationship_entity_descriptor(key, child):
                    return key
            nested_key = _find_forbidden_key(child, forbidden_keys)
            if nested_key is not None:
                return nested_key
        return None

    if isinstance(value, (list, tuple)):
        for item in value:
            nested_key = _find_forbidden_key(item, forbidden_keys)
            if nested_key is not None:
                return nested_key

    return None


def _is_forbidden_key(key: str, forbidden_keys: set[str]) -> bool:
    normalized_key = key.lower()
    if normalized_key in forbidden_keys:
        return True

    for prefix in ROUTE_COLLECTION_RELATIONSHIP_KEY_PREFIXES:
        if not normalized_key.startswith(f"{prefix}_"):
            continue
        suffix = normalized_key.removeprefix(f"{prefix}_")
        if suffix in ROUTE_COLLECTION_RELATIONSHIP_KEY_SUFFIXES:
            return True

    return False


def _is_relationship_entity_descriptor(key: str, value: Any) -> bool:
    if key.lower() not in ROUTE_COLLECTION_ENTITY_DISCRIMINATOR_KEYS:
        return False
    if not isinstance(value, str):
        return False

    normalized_value = value.strip().lower().replace("-", "_")
    return normalized_value in ROUTE_COLLECTION_RELATIONSHIP_ENTITY_VALUES


def _has_text(value: str) -> bool:
    return value.strip() != ""
