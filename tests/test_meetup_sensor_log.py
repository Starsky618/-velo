"""约骑详情埋点测试——像在门口放计数器，确认谁从哪条路进来看过约骑。

操作注意事项：这里只打 HTTP 接口并读取日志，不绕过 router 调 service，避免测不到真正的请求参数和门禁顺序。
输入/输出数据流：输入是 TestClient 请求；输出是 caplog 捕获到的 SENSOR view 日志。
"""

from datetime import datetime, timedelta, timezone
import logging

from app.meetup import service
# 显式 import ORM 模型（陷阱 #16 同族）：现在靠 service 的传递 import 也能加载，
# 但服务边界一重构就可能"could not find table"——显式写出来不赌加载顺序。
from app.meetup.models import Meetup, MeetupParticipant  # noqa: F401
from app.segment.models import Segment
from app.user.models import User
from app.user.service import create_token


def _segment(db):
    segment = Segment(
        name="晋阳湖绕圈",
        distance=28000.0,
        elevation_gain=120.0,
        start_lat=37.7,
        start_lon=112.4,
        end_lat=37.8,
        end_lon=112.5,
        reference_line="SRID=4326;LINESTRING(112.4 37.7, 112.5 37.8)",
        city="taiyuan",
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _open_meetup(db, owner_id: int, visibility: str = "public"):
    segment = _segment(db)
    start = datetime.now(timezone.utc) + timedelta(days=3)
    meetup = service.create_meetup(
        db,
        current_user_id=owner_id,
        segment_id=segment.id,
        route_book_id=None,
        start_time=start,
        estimated_end_time=start + timedelta(hours=3),
        meeting_point="晋阳湖东门",
        pace_level="cruise",
        max_participants=6,
        description="均速 28 左右",
        visibility=visibility,
    )
    return service.publish_meetup(db, meetup.id, owner_id)


def _auth_header_for(db, openid: str):
    user = User(openid=openid, is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, {"Authorization": f"Bearer {create_token(user.id)}"}


def _sensor_lines(caplog):
    return [record.getMessage() for record in caplog.records if "SENSOR view" in record.getMessage()]


def test_public_detail_logs_anon_view_with_direct_source(client, db, test_user, caplog):
    meetup = _open_meetup(db, test_user.id)
    caplog.set_level(logging.INFO, logger="app.meetup.router")

    res = client.get(f"/api/meetups/{meetup.id}")

    assert res.status_code == 200
    assert _sensor_lines(caplog) == [
        f"SENSOR view meetup_id={meetup.id} viewer=anon token_present=False source=direct"
    ]


def test_participant_share_card_view_logs_participant_source(client, db, test_user, auth_header, caplog):
    meetup = _open_meetup(db, test_user.id)
    caplog.set_level(logging.INFO, logger="app.meetup.router")

    res = client.get(f"/api/meetups/{meetup.id}?source=share_card", headers=auth_header)

    assert res.status_code == 200
    assert _sensor_lines(caplog) == [
        f"SENSOR view meetup_id={meetup.id} viewer=participant token_present=False source=share_card"
    ]


def test_logged_in_non_participant_logs_guest_view(client, db, test_user, caplog):
    meetup = _open_meetup(db, test_user.id)
    _, guest_header = _auth_header_for(db, "meetup-sensor-guest")
    caplog.set_level(logging.INFO, logger="app.meetup.router")

    res = client.get(f"/api/meetups/{meetup.id}?source=share_card", headers=guest_header)

    assert res.status_code == 200
    assert _sensor_lines(caplog) == [
        f"SENSOR view meetup_id={meetup.id} viewer=guest token_present=False source=share_card"
    ]


def test_invite_only_without_token_returns_404_and_logs_no_sensor(client, db, test_user, caplog):
    meetup = _open_meetup(db, test_user.id, visibility="invite_only")
    caplog.set_level(logging.INFO, logger="app.meetup.router")

    res = client.get(f"/api/meetups/{meetup.id}?source=share_card")

    assert res.status_code == 404
    assert _sensor_lines(caplog) == []


def test_invite_token_is_never_written_to_sensor_log(client, db, test_user, caplog):
    meetup = _open_meetup(db, test_user.id, visibility="invite_only")
    caplog.set_level(logging.INFO, logger="app.meetup.router")

    res = client.get(f"/api/meetups/{meetup.id}?token={meetup.share_token}&source=share_card")

    assert res.status_code == 200
    assert meetup.share_token not in "\n".join(_sensor_lines(caplog))
    assert _sensor_lines(caplog) == [
        f"SENSOR view meetup_id={meetup.id} viewer=anon token_present=True source=share_card"
    ]


def test_detail_without_source_keeps_direct_default(client, db, test_user, caplog):
    meetup = _open_meetup(db, test_user.id)
    _, guest_header = _auth_header_for(db, "meetup-sensor-default")
    caplog.set_level(logging.INFO, logger="app.meetup.router")

    res = client.get(f"/api/meetups/{meetup.id}", headers=guest_header)

    assert res.status_code == 200
    assert _sensor_lines(caplog) == [
        f"SENSOR view meetup_id={meetup.id} viewer=guest token_present=False source=direct"
    ]
