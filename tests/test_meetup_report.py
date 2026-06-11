"""Sprint 13 Task 4：约骑战报页 API 测试。"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.activity.models import Activity
from app.meetup import schemas, service
from app.meetup.models import Meetup, MeetupActivity, MeetupParticipant
from app.user.models import User
from app.user.service import create_token


def _user(db, suffix: str, nickname: str | None = None, avatar_url: str | None = None) -> User:
    user = User(openid=f"report-{suffix}", nickname=nickname, avatar_url=avatar_url, is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_header(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user.id)}"}


def _meetup(db, creator_id: int, visibility: str = "public", status: str = "OPEN") -> Meetup:
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup = Meetup(
        creator_id=creator_id,
        status=status,
        snapshot_route_name="天龙山西线",
        snapshot_distance=42000.0,
        snapshot_climb=900.0,
        snapshot_city="taiyuan",
        start_time=start,
        estimated_end_time=start + timedelta(hours=4),
        meeting_point="集合点",
        pace_level="cruise",
        max_participants=8,
        visibility=visibility,
        share_token="report-token",
    )
    db.add(meetup)
    db.commit()
    db.refresh(meetup)
    return meetup


def _participant(db, meetup_id: int, user_id: int, is_creator: bool = False) -> MeetupParticipant:
    row = MeetupParticipant(meetup_id=meetup_id, user_id=user_id, is_creator=is_creator)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _activity(db, user_id: int, distance: float, climb: float, avg_speed: float = 25.5) -> Activity:
    activity = Activity(
        user_id=user_id,
        title="交卷骑行",
        status="completed",
        file_url="report.gpx",
        distance=distance,
        duration=7200,
        moving_time=7000,
        elevation_gain=climb,
        avg_speed=avg_speed,
        activity_type="cycling",
        started_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def _submission(db, meetup_id: int, user_id: int, activity: Activity, submitted_at: datetime) -> MeetupActivity:
    row = MeetupActivity(meetup_id=meetup_id, user_id=user_id, activity_id=activity.id, created_at=submitted_at)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _basic_report_fixture(db):
    creator = _user(db, "creator", "组织者", "https://example.com/creator.png")
    early = _user(db, "early", "早交卷", "https://example.com/early.png")
    late = _user(db, "late", "晚交卷", "https://example.com/late.png")
    gray = _user(db, "gray", "未交卷", "https://example.com/gray.png")
    meetup = _meetup(db, creator.id)
    _participant(db, meetup.id, creator.id, is_creator=True)
    _participant(db, meetup.id, early.id)
    _participant(db, meetup.id, late.id)
    _participant(db, meetup.id, gray.id)
    return meetup, creator, early, late, gray


def test_invite_only_non_member_is_rejected_by_detail_gate(client, db):
    creator = _user(db, "private-creator")
    outsider = _user(db, "private-outsider")
    meetup = _meetup(db, creator.id, visibility="invite_only")
    _participant(db, meetup.id, creator.id, is_creator=True)

    res = client.get(f"/api/meetups/{meetup.id}/report", headers=_auth_header(outsider))

    assert res.status_code == 404
    assert res.json()["detail"] == "meetup not found"


def test_member_can_access_report(client, db):
    meetup, _creator, early, _late, _gray = _basic_report_fixture(db)

    res = client.get(f"/api/meetups/{meetup.id}/report", headers=_auth_header(early))

    assert res.status_code == 200
    assert res.json()["meetup_id"] == meetup.id


def test_cells_keep_all_participants_and_put_gray_cells_last(client, db):
    meetup, _creator, early, late, gray = _basic_report_fixture(db)
    base = datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)
    _submission(db, meetup.id, late.id, _activity(db, late.id, 30000.0, 300.0), base + timedelta(minutes=20))
    _submission(db, meetup.id, early.id, _activity(db, early.id, 42000.0, 900.0), base + timedelta(minutes=5))

    res = client.get(f"/api/meetups/{meetup.id}/report")
    cells = res.json()["cells"]

    assert res.status_code == 200
    assert len(cells) == 4
    assert [cell["user_id"] for cell in cells[:2]] == [early.id, late.id]
    assert cells[-1]["user_id"] == gray.id
    assert cells[-1]["submitted"] is False
    assert cells[-1]["distance_km"] is None
    assert cells[-1]["avg_speed"] is None
    assert cells[-1]["climb_m"] is None
    assert cells[-1]["submitted_at"] is None


def test_submitted_at_field_is_serialized(client, db):
    meetup, _creator, early, _late, _gray = _basic_report_fixture(db)
    submitted_at = datetime(2026, 6, 11, 8, 5, tzinfo=timezone.utc)
    _submission(db, meetup.id, early.id, _activity(db, early.id, 42000.0, 900.0), submitted_at)

    body = client.get(f"/api/meetups/{meetup.id}/report").json()

    assert body["cells"][0]["submitted_at"].startswith("2026-06-11T08:05:00")


def test_climb_m_uses_serialization_alias(client, db):
    meetup, _creator, early, _late, _gray = _basic_report_fixture(db)
    _submission(
        db,
        meetup.id,
        early.id,
        _activity(db, early.id, 42195.0, 888.0),
        datetime(2026, 6, 11, 8, 5, tzinfo=timezone.utc),
    )

    cell = client.get(f"/api/meetups/{meetup.id}/report").json()["cells"][0]

    assert cell["climb_m"] == 888.0
    assert "elevation_gain" not in cell


def test_avatar_url_is_in_cells(client, db):
    meetup, _creator, early, _late, _gray = _basic_report_fixture(db)
    _submission(
        db,
        meetup.id,
        early.id,
        _activity(db, early.id, 42000.0, 900.0),
        datetime(2026, 6, 11, 8, 5, tzinfo=timezone.utc),
    )

    cell = client.get(f"/api/meetups/{meetup.id}/report").json()["cells"][0]

    assert cell["avatar_url"] == "https://example.com/early.png"


def test_report_cell_forbids_extra_fields():
    with pytest.raises(ValidationError):
        schemas.MeetupReportCell(user_id=1, submitted=False, leaked_openid="secret")


def test_report_reuses_get_meetup_detail_gate(client, db, monkeypatch):
    meetup, _creator, early, _late, _gray = _basic_report_fixture(db)
    calls = []
    original = service.get_meetup_detail

    def wrapped(db_session, meetup_id, current_user_id=None, token=None):
        calls.append((meetup_id, current_user_id, token))
        return original(db_session, meetup_id, current_user_id=current_user_id, token=token)

    monkeypatch.setattr("app.meetup.service.get_meetup_detail", wrapped)

    res = client.get(f"/api/meetups/{meetup.id}/report?token=report-token", headers=_auth_header(early))

    assert res.status_code == 200
    assert calls == [(meetup.id, early.id, "report-token")]


def test_d9_sorting_uses_submission_time_with_nulls_last(client, db):
    meetup, _creator, early, late, gray = _basic_report_fixture(db)
    base = datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)
    _submission(db, meetup.id, late.id, _activity(db, late.id, 30000.0, 300.0), base + timedelta(minutes=30))
    _submission(db, meetup.id, early.id, _activity(db, early.id, 42000.0, 900.0), base + timedelta(minutes=10))

    cells = client.get(f"/api/meetups/{meetup.id}/report").json()["cells"]

    assert [cell["user_id"] for cell in cells] == [early.id, late.id, _creator.id, gray.id]


def test_totals_sum_submitted_with_km_conversion(client, db):
    """合计求和（卡 §5 #2）：distance 库存米、API 出 km；只算已交卷的，灰格不计入。"""
    meetup, _creator, early, late, _gray = _basic_report_fixture(db)
    base = datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)
    _submission(db, meetup.id, early.id, _activity(db, early.id, 42000.0, 900.0), base)
    _submission(db, meetup.id, late.id, _activity(db, late.id, 30500.0, 300.0), base + timedelta(minutes=5))

    totals = client.get(f"/api/meetups/{meetup.id}/report").json()["totals"]

    assert totals["distance_km"] == 72.5    # (42000 + 30500) 米 → 72.5 km
    assert totals["climb_m"] == 1200        # 900 + 300
    assert totals["rider_count"] == 4
    assert totals["submitted_count"] == 2


def test_zero_submissions_returns_all_gray_cells_and_zero_totals(client, db):
    """0 人交卷（卡 §5 #4）：cells 全灰、totals 全 0、不炸——战报页"永远不空"的底座。"""
    meetup, *_ = _basic_report_fixture(db)

    body = client.get(f"/api/meetups/{meetup.id}/report").json()

    assert body["totals"] == {"distance_km": 0.0, "climb_m": 0, "rider_count": 4, "submitted_count": 0}
    assert len(body["cells"]) == 4
    assert all(cell["submitted"] is False for cell in body["cells"])


def test_invite_only_with_valid_token_returns_200(client, db):
    """门禁对称的另一半（卡 §5 #6）：私圈约骑带对口令 → 非参与者也能看战报（受邀链路）。"""
    creator = _user(db, "tk-creator")
    outsider = _user(db, "tk-outsider")
    meetup = _meetup(db, creator.id, visibility="invite_only")
    _participant(db, meetup.id, creator.id, is_creator=True)

    res = client.get(f"/api/meetups/{meetup.id}/report?token=report-token", headers=_auth_header(outsider))

    assert res.status_code == 200
    assert res.json()["meetup_id"] == meetup.id
