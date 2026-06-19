"""路线认知内部演示快照——像展厅讲解员，只读数据库，把已审核关系讲成一段可看的故事。

操作注意事项：这个文件只能做内部 demo 查询，不能写库、不能 commit、不能变成 public API 或 admin UI。
输入输出：输入是数据库 session 和两个 collection slug；输出是一段文本 snapshot，给内部 dry-run/验收测试使用。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.route_book.models import RouteBook
from app.route_cognition.models import (
    CollectionConceptLink,
    CollectionRoute,
    CollectionSegment,
    ConceptNode,
    RouteCollection,
    RouteConceptLink,
    RouteSegment,
    SegmentConceptLink,
)
from app.segment.models import Segment


DEFAULT_XISHAN_COLLECTION_SLUG = "xishan-training-system"
DEFAULT_EVENT_COLLECTION_SLUG = "tour-of-taiyuan-route-family"


class DemoSnapshotError(ValueError):
    """内部演示快照读不到必要对象——调用方应先补齐 dry-run 数据，而不是降级成空文案。"""


@dataclass(frozen=True)
class _CollectionRef:
    id: int
    name: str


@dataclass(frozen=True)
class _RouteMemberRef:
    route_book_id: int
    route_version_id: int
    route_name: str


@dataclass(frozen=True)
class _SegmentMemberRef:
    segment_id: int
    segment_name: str


@dataclass(frozen=True)
class _CompositionRow:
    seq: int
    component_type: str
    segment_name: str | None


def build_first_visible_slice_demo_snapshot(
    db: Session,
    *,
    xishan_collection_slug: str = DEFAULT_XISHAN_COLLECTION_SLUG,
    event_collection_slug: str = DEFAULT_EVENT_COLLECTION_SLUG,
) -> str:
    """读取 First Visible Slice 的内部演示结构，并渲染成固定文本。"""

    xishan_collection = _collection_by_slug(db, xishan_collection_slug)
    event_collection = _collection_by_slug(db, event_collection_slug)
    route_member = _first_active_route_member(db, xishan_collection.id)
    segment_member = _first_active_segment_member(db, xishan_collection.id)
    route_concepts = _active_route_concept_names(
        db,
        route_book_id=route_member.route_book_id,
        route_version_id=route_member.route_version_id,
    )
    segment_concepts = _active_segment_concept_names(db, segment_id=segment_member.segment_id)
    xishan_collection_concepts = _active_collection_concept_names(db, collection_id=xishan_collection.id)
    event_collection_concepts = _active_collection_concept_names(db, collection_id=event_collection.id)
    composition_lines = _route_composition_lines(
        db,
        route_book_id=route_member.route_book_id,
        route_version_id=route_member.route_version_id,
    )

    return "\n".join(
        (
            xishan_collection.name,
            f"- route: {route_member.route_name}",
            f"- segment: {segment_member.segment_name}",
            f"- route concepts: {_join_names(route_concepts, label='route concepts')}",
            f"- segment concepts: {_join_names(segment_concepts, label='segment concepts')}",
            f"- collection concepts: {_join_names(xishan_collection_concepts, label='xishan collection concepts')}",
            "- route composition:",
            *composition_lines,
            "",
            event_collection.name,
            f"- collection concepts: {_join_names(event_collection_concepts, label='event collection concepts')}",
        )
    )


def _collection_by_slug(db: Session, slug: str) -> _CollectionRef:
    row = (
        db.query(RouteCollection.id, RouteCollection.name)
        .filter(RouteCollection.slug == slug)
        .first()
    )
    if row is None:
        raise DemoSnapshotError(f"route_collection slug {slug!r} does not exist")
    return _CollectionRef(id=row.id, name=row.name)


def _first_active_route_member(db: Session, collection_id: int) -> _RouteMemberRef:
    row = (
        db.query(
            CollectionRoute.route_book_id,
            CollectionRoute.reviewed_route_version_id,
            RouteBook.name.label("route_name"),
        )
        .join(RouteBook, RouteBook.id == CollectionRoute.route_book_id)
        .filter(
            CollectionRoute.collection_id == collection_id,
            CollectionRoute.membership_status == "active",
        )
        .order_by(CollectionRoute.seq.is_(None), CollectionRoute.seq, CollectionRoute.id)
        .first()
    )
    if row is None:
        raise DemoSnapshotError("xishan collection has no active route member")
    return _RouteMemberRef(
        route_book_id=row.route_book_id,
        route_version_id=row.reviewed_route_version_id,
        route_name=row.route_name,
    )


def _first_active_segment_member(db: Session, collection_id: int) -> _SegmentMemberRef:
    row = (
        db.query(
            CollectionSegment.segment_id,
            Segment.name.label("segment_name"),
        )
        .join(Segment, Segment.id == CollectionSegment.segment_id)
        .filter(
            CollectionSegment.collection_id == collection_id,
            CollectionSegment.membership_status == "active",
        )
        .order_by(CollectionSegment.seq.is_(None), CollectionSegment.seq, CollectionSegment.id)
        .first()
    )
    if row is None:
        raise DemoSnapshotError("xishan collection has no active segment member")
    return _SegmentMemberRef(segment_id=row.segment_id, segment_name=row.segment_name)


def _active_route_concept_names(db: Session, *, route_book_id: int, route_version_id: int) -> list[str]:
    rows = (
        db.query(ConceptNode.name)
        .join(RouteConceptLink, RouteConceptLink.concept_node_id == ConceptNode.id)
        .filter(
            RouteConceptLink.route_book_id == route_book_id,
            RouteConceptLink.route_version_id == route_version_id,
            RouteConceptLink.link_status == "active",
        )
        .order_by(RouteConceptLink.display_priority.is_(None), RouteConceptLink.display_priority, ConceptNode.name)
        .all()
    )
    return [row.name for row in rows]


def _active_segment_concept_names(db: Session, *, segment_id: int) -> list[str]:
    relation_order = case(
        (SegmentConceptLink.relation_type == "suitable_for", 1),
        (SegmentConceptLink.relation_type == "has_risk", 2),
        else_=99,
    )
    rows = (
        db.query(ConceptNode.name)
        .join(SegmentConceptLink, SegmentConceptLink.concept_node_id == ConceptNode.id)
        .filter(
            SegmentConceptLink.segment_id == segment_id,
            SegmentConceptLink.link_status == "active",
        )
        .order_by(relation_order, SegmentConceptLink.display_priority.is_(None), SegmentConceptLink.display_priority, ConceptNode.name)
        .all()
    )
    return [row.name for row in rows]


def _active_collection_concept_names(db: Session, *, collection_id: int) -> list[str]:
    rows = (
        db.query(ConceptNode.name)
        .join(CollectionConceptLink, CollectionConceptLink.concept_node_id == ConceptNode.id)
        .filter(
            CollectionConceptLink.collection_id == collection_id,
            CollectionConceptLink.link_status == "active",
        )
        .order_by(CollectionConceptLink.display_priority.is_(None), CollectionConceptLink.display_priority, ConceptNode.name)
        .all()
    )
    return [row.name for row in rows]


def _route_composition_lines(db: Session, *, route_book_id: int, route_version_id: int) -> list[str]:
    rows = (
        db.query(
            RouteSegment.seq,
            RouteSegment.component_type,
            Segment.name.label("segment_name"),
        )
        .outerjoin(Segment, Segment.id == RouteSegment.segment_id)
        .filter(
            RouteSegment.route_book_id == route_book_id,
            RouteSegment.route_version_id == route_version_id,
            RouteSegment.membership_status == "active",
        )
        .order_by(RouteSegment.seq)
        .all()
    )
    if not rows:
        raise DemoSnapshotError("route has no active composition rows")

    return [_format_composition_row(_CompositionRow(row.seq, row.component_type, row.segment_name)) for row in rows]


def _format_composition_row(row: _CompositionRow) -> str:
    if row.component_type == "segment_clip":
        if row.segment_name is None:
            raise DemoSnapshotError("segment_clip composition row is missing segment name")
        return f"  {row.seq}. {row.segment_name} {row.component_type}"
    return f"  {row.seq}. {row.component_type}"


def _join_names(names: list[str], *, label: str) -> str:
    if not names:
        raise DemoSnapshotError(f"{label} are missing")
    return " / ".join(names)
