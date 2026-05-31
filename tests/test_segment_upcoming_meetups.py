"""约骑模块 Task 8：赛段详情 upcoming-meetups endpoint 测试。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.meetup import service
from app.meetup.models import MeetupParticipant
from app.segment.models import Segment
from app.user.models import User


ROOT = Path(__file__).resolve().parents[1]


def _segment(db, name):
    segment = Segment(
        name=name,
        distance=10000.0,
        elevation_gain=200.0,
        start_lat=37.8,
        start_lon=112.5,
        end_lat=37.9,
        end_lon=112.6,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        city="taiyuan",
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _user(db, openid):
    user = User(openid=openid, is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _open_meetup(db, user_id, segment_id, days=2):
    start = datetime.now(timezone.utc) + timedelta(days=days)
    meetup = service.create_meetup(
        db,
        user_id,
        segment_id,
        None,
        start,
        start + timedelta(hours=2),
        "集合点",
        "cruise",
        4,
        "一起骑",
    )
    return service.publish_meetup(db, meetup.id, user_id)


def test_segment_upcoming_meetups_returns_public_open_future_items(client, db, test_user):
    segment = _segment(db, "太山爬坡")
    other = _segment(db, "晋阳湖")
    target = _open_meetup(db, test_user.id, segment.id, days=2)
    _open_meetup(db, test_user.id, other.id, days=2)
    past = _open_meetup(db, test_user.id, segment.id, days=-2)
    cancelled = _open_meetup(db, test_user.id, segment.id, days=3)
    service.cancel_meetup(db, cancelled.id, test_user.id)

    res = client.get(f"/api/segments/{segment.id}/upcoming-meetups")

    assert res.status_code == 200
    body = res.json()
    ids = [item["id"] for item in body["items"]]
    assert ids == [target.id]
    assert past.id not in ids
    assert cancelled.id not in ids
    item = body["items"][0]
    assert item["snapshot_route_name"] == "太山爬坡"
    # 卡片要能显示"几点到几点"，结束时间必须返回且晚于开始时间（ISO 字符串同格式可直接比较）
    assert item["estimated_end_time"] > item["start_time"]


def test_segment_upcoming_endpoint_is_public_and_counts_participants(client, db, test_user):
    segment = _segment(db, "公开路线")
    meetup = _open_meetup(db, test_user.id, segment.id, days=2)
    rider = _user(db, "segment-upcoming-rider")
    db.add(MeetupParticipant(meetup_id=meetup.id, user_id=rider.id, is_creator=False))
    db.commit()

    res = client.get(f"/api/segments/{segment.id}/upcoming-meetups")

    assert res.status_code == 200
    assert res.json()["items"][0]["participants_count"] == 2


def test_segment_upcoming_meetups_returns_404_for_missing_segment(client):
    res = client.get("/api/segments/999999/upcoming-meetups")

    assert res.status_code == 404


def test_segment_reverse_hook_is_exactly_one_endpoint():
    router = (ROOT / "app" / "segment" / "router.py").read_text(encoding="utf-8")

    assert "@router.get(\"/{segment_id}/upcoming-meetups\"" in router
    assert "from app.meetup.models import Meetup" in router
    assert "from app.route_book" not in router
