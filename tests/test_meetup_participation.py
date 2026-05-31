"""约骑模块 Task 5：加入退出和并发合同测试。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.meetup import service
from app.meetup.models import MeetupParticipant
from app.segment.models import Segment
from app.user.models import User
from app.user.service import create_token


ROOT = Path(__file__).resolve().parents[1]


def _segment(db):
    segment = Segment(
        name="太山爬坡",
        distance=5000.0,
        elevation_gain=300.0,
        start_lat=37.8,
        start_lon=112.4,
        end_lat=37.9,
        end_lon=112.5,
        reference_line="SRID=4326;LINESTRING(112.4 37.8, 112.5 37.9)",
        city="taiyuan",
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _open_meetup(db, owner_id, max_participants=2, minutes=180):
    segment = _segment(db)
    start = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    meetup = service.create_meetup(
        db,
        owner_id,
        segment.id,
        None,
        start,
        start + timedelta(hours=2),
        "太山脚下",
        "training",
        max_participants,
        None,
    )
    return service.publish_meetup(db, meetup.id, owner_id)


def _auth_header_for(db, openid):
    user = User(openid=openid, is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, {"Authorization": f"Bearer {create_token(user.id)}"}


def test_join_meetup_adds_participant(client, db, test_user, admin_header, admin_user):
    meetup = _open_meetup(db, test_user.id, max_participants=3)

    res = client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)

    assert res.status_code == 200
    assert res.json()["participants_count"] == 2
    participant = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=admin_user.id).first()
    assert participant is not None


def test_join_full_meetup_returns_409(client, db, test_user, admin_header):
    other_user, other_header = _auth_header_for(db, "meetup-full-other")
    meetup = _open_meetup(db, test_user.id, max_participants=2)

    first = client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)
    res = client.post(f"/api/meetups/{meetup.id}/join", headers=other_header)

    assert first.status_code == 200
    assert res.status_code == 409
    assert res.json()["detail"] == "meetup_full"
    assert db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=other_user.id).first() is None


def test_join_same_user_twice_returns_409(client, db, test_user, admin_header):
    meetup = _open_meetup(db, test_user.id, max_participants=3)

    first = client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)
    second = client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "already_joined"


def test_join_cancelled_meetup_returns_410(client, db, test_user, auth_header, admin_header):
    meetup = _open_meetup(db, test_user.id, max_participants=3)
    client.post(f"/api/meetups/{meetup.id}/cancel", headers=auth_header)

    res = client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)

    assert res.status_code == 410


def test_leave_meetup_removes_participant(client, db, test_user, admin_header, admin_user):
    meetup = _open_meetup(db, test_user.id, max_participants=3)
    client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)

    res = client.delete(f"/api/meetups/{meetup.id}/leave", headers=admin_header)

    assert res.status_code == 200
    assert res.json()["participants_count"] == 1
    participant = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=admin_user.id).first()
    assert participant is None


def test_leave_inside_cutoff_returns_410(db, test_user, admin_user):
    meetup = _open_meetup(db, test_user.id, max_participants=3)
    service.join_meetup(db, meetup.id, admin_user.id)
    meetup.start_time = datetime.now(timezone.utc) + timedelta(minutes=20)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        service.leave_meetup(db, meetup.id, admin_user.id)

    assert exc.value.status_code == 410


def test_join_service_uses_locked_meetup_loader():
    source = (ROOT / "app" / "meetup" / "service.py").read_text(encoding="utf-8")

    assert "def join_meetup" in source
    assert "def leave_meetup" in source
    join_block = source[source.index("def join_meetup"):source.index("def leave_meetup")]
    assert "_load_and_authorize_meetup(" in join_block
    assert "require_status=[\"OPEN\"]" in join_block
    assert "check_time_cutoff=True" in join_block
    assert ".with_for_update()" in source
    assert ".populate_existing()" in source


def test_join_inside_cutoff_returns_410(db, test_user, admin_user):
    # join 和 leave 一样有时间边界：截止线内（start - 30min）不能再加入
    meetup = _open_meetup(db, test_user.id, max_participants=3)
    meetup.start_time = datetime.now(timezone.utc) + timedelta(minutes=20)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        service.join_meetup(db, meetup.id, admin_user.id)

    assert exc.value.status_code == 410


def test_creator_cannot_leave_own_meetup(client, db, test_user, auth_header):
    # 发起人不能退出自己发起的约骑——要退只能取消整个约骑，
    # 否则约骑还挂在他名下、参与列表却没有他 = 没人负责的幽灵约骑（下游 task7/8 会踩）
    meetup = _open_meetup(db, test_user.id, max_participants=3)

    res = client.delete(f"/api/meetups/{meetup.id}/leave", headers=auth_header)

    assert res.status_code == 403
    assert res.json()["detail"] == "creator_cannot_leave"
    # 守卫生效后发起人仍在参与列表
    assert (
        db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=test_user.id).first()
        is not None
    )


def test_delete_cancelled_meetup_returns_409_not_410(client, db, test_user, auth_header):
    # 回归守卫：join/leave 需要的"已取消→410"不能渗透到删除端点。
    # spec 要求删非 DRAFT 约骑返 409，删一个已取消的约骑必须是 409 而不是 410。
    meetup = _open_meetup(db, test_user.id, max_participants=3)
    client.post(f"/api/meetups/{meetup.id}/cancel", headers=auth_header)

    res = client.delete(f"/api/meetups/{meetup.id}", headers=auth_header)

    assert res.status_code == 409
