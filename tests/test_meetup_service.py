"""约骑模块 Task 3：service 状态机测试。"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.meetup import service
from app.meetup.models import MeetupParticipant
from app.route_book.models import RouteBook
from app.segment.models import Segment


def _segment(db, name="龙城大道", city="taiyuan"):
    segment = Segment(
        name=name,
        distance=3200.0,
        elevation_gain=80.0,
        start_lat=37.8,
        start_lon=112.5,
        end_lat=37.9,
        end_lon=112.6,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        city=city,
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _route_book(db, user_id, name="汾河路书", city="taiyuan"):
    route = RouteBook(
        creator_id=user_id,
        name=name,
        distance=42000.0,
        climb=520.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city=city,
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


def _start(days=2):
    return datetime.now(timezone.utc) + timedelta(days=days)


def test_create_meetup_from_segment_writes_snapshot(db, test_user):
    segment = _segment(db)

    meetup = service.create_meetup(
        db,
        current_user_id=test_user.id,
        segment_id=segment.id,
        route_book_id=None,
        start_time=_start(),
        estimated_end_time=_start() + timedelta(hours=3),
        meeting_point="龙城公园东门",
        pace_level="cruise",
        max_participants=6,
        description="稳定巡航",
    )

    assert meetup.status == "DRAFT"
    assert meetup.snapshot_route_name == "龙城大道"
    assert meetup.snapshot_distance == 3200.0
    assert meetup.snapshot_city == "taiyuan"


def test_create_meetup_returns_existing_draft_id_when_draft_exists(db, test_user):
    segment = _segment(db)
    existing = service.create_meetup(
        db, test_user.id, segment.id, None, _start(), _start() + timedelta(hours=2), "A", "cruise", 4, None
    )

    with pytest.raises(HTTPException) as exc:
        service.create_meetup(
            db, test_user.id, segment.id, None, _start(), _start() + timedelta(hours=2), "B", "cruise", 4, None
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "draft_exists"
    assert exc.value.detail["existing_draft_id"] == existing.id


def test_update_draft_route_recalculates_snapshot(db, test_user):
    segment = _segment(db, name="旧路线")
    route = _route_book(db, test_user.id, name="新路书")
    meetup = service.create_meetup(
        db, test_user.id, segment.id, None, _start(), _start() + timedelta(hours=2), "A", "relaxed", 4, None
    )

    updated = service.update_meetup(db, meetup.id, test_user.id, route_book_id=route.id, segment_id=None)

    assert updated.route_book_id == route.id
    assert updated.segment_id is None
    assert updated.snapshot_route_name == "新路书"
    assert updated.snapshot_distance == 42000.0


def test_publish_freezes_snapshot_and_adds_creator_participant(db, test_user):
    segment = _segment(db, name="发布前名字")
    meetup = service.create_meetup(
        db, test_user.id, segment.id, None, _start(), _start() + timedelta(hours=2), "A", "training", 2, None
    )

    published = service.publish_meetup(db, meetup.id, test_user.id)
    segment.name = "发布后改名"
    db.commit()
    db.refresh(published)

    participants = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id).all()
    assert published.status == "OPEN"
    assert published.snapshot_route_name == "发布前名字"
    assert len(participants) == 1
    assert participants[0].is_creator is True


def test_cancel_rejects_inside_cutoff(db, test_user):
    segment = _segment(db)
    meetup = service.create_meetup(
        db,
        test_user.id,
        segment.id,
        None,
        datetime.now(timezone.utc) + timedelta(minutes=20),
        datetime.now(timezone.utc) + timedelta(hours=2),
        "A",
        "cruise",
        4,
        None,
    )
    service.publish_meetup(db, meetup.id, test_user.id)

    with pytest.raises(HTTPException) as exc:
        service.cancel_meetup(db, meetup.id, test_user.id)

    assert exc.value.status_code == 410


def test_delete_only_allows_draft(db, test_user):
    segment = _segment(db)
    meetup = service.create_meetup(
        db, test_user.id, segment.id, None, _start(), _start() + timedelta(hours=2), "A", "cruise", 4, None
    )
    service.publish_meetup(db, meetup.id, test_user.id)

    with pytest.raises(HTTPException) as exc:
        service.delete_draft_meetup(db, meetup.id, test_user.id)

    assert exc.value.status_code == 409


def test_load_and_authorize_creator_guard(db, test_user, admin_user):
    segment = _segment(db)
    meetup = service.create_meetup(
        db, test_user.id, segment.id, None, _start(), _start() + timedelta(hours=2), "A", "cruise", 4, None
    )

    with pytest.raises(HTTPException) as exc:
        service._load_and_authorize_meetup(db, meetup.id, admin_user.id, require_creator=True)

    assert exc.value.status_code == 403
