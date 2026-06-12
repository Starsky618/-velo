"""Sprint 13 Task 1：约骑和骑行活动自动关联测试。"""

from datetime import datetime, timedelta, timezone

from app.activity.models import Activity
from app.meetup.models import Meetup, MeetupParticipant
from app.user.models import User


def _user(db, suffix: str) -> User:
    user = User(openid=f"attach-{suffix}", is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _meetup(db, user_id: int, start: datetime, status: str = "OPEN") -> Meetup:
    meetup = Meetup(
        creator_id=user_id,
        status=status,
        snapshot_route_name="天龙山约骑",
        snapshot_distance=42000.0,
        snapshot_climb=900.0,
        snapshot_city="taiyuan",
        start_time=start,
        estimated_end_time=start + timedelta(hours=4),
        meeting_point="集合点",
        pace_level="cruise",
        max_participants=8,
    )
    db.add(meetup)
    db.commit()
    db.refresh(meetup)
    return meetup


def _participant(db, meetup_id: int, user_id: int) -> MeetupParticipant:
    row = MeetupParticipant(meetup_id=meetup_id, user_id=user_id, is_creator=False)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _activity(db, user_id: int, started_at: datetime, status: str = "completed") -> Activity:
    activity = Activity(
        user_id=user_id,
        title="骑行文件",
        status=status,
        started_at=started_at,
        distance=42000.0,
        duration=7200,
        activity_type="cycling",
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def _activity_ids(db, meetup_id: int) -> list[int]:
    from app.meetup.models import MeetupActivity

    rows = (
        db.query(MeetupActivity)
        .filter(MeetupActivity.meetup_id == meetup_id)
        .order_by(MeetupActivity.id.asc())
        .all()
    )
    return [row.activity_id for row in rows]


def test_to_bj_date_handles_aware_utc_aware_bj_and_naive_utc():
    from app.common.bj_time import BJ_TZ, to_bj_date

    assert to_bj_date(datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc)).isoformat() == "2026-06-11"
    assert to_bj_date(datetime(2026, 6, 11, 20, 30, tzinfo=BJ_TZ)).isoformat() == "2026-06-11"
    assert to_bj_date(datetime(2026, 6, 11, 23, 30)).isoformat() == "2026-06-12"


def test_same_day_two_rides_attach_earliest_activity(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup = _meetup(db, test_user.id, start)
    _participant(db, meetup.id, test_user.id)
    early = _activity(db, test_user.id, start + timedelta(minutes=10))
    _activity(db, test_user.id, start + timedelta(hours=1))

    assert attach_meetup_activities(db) == 1

    assert _activity_ids(db, meetup.id) == [early.id]


def test_overlapping_meetups_for_different_users_attach_to_own_meetup(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    other = _user(db, "overlap-other")
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup_a = _meetup(db, test_user.id, start)
    meetup_b = _meetup(db, other.id, start + timedelta(minutes=15))
    _participant(db, meetup_a.id, test_user.id)
    _participant(db, meetup_b.id, other.id)
    activity_a = _activity(db, test_user.id, start + timedelta(minutes=20))
    activity_b = _activity(db, other.id, start + timedelta(minutes=25))

    assert attach_meetup_activities(db) == 2

    assert _activity_ids(db, meetup_a.id) == [activity_a.id]
    assert _activity_ids(db, meetup_b.id) == [activity_b.id]


def test_same_user_can_attach_one_activity_to_two_overlapping_meetups(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup_a = _meetup(db, test_user.id, start)
    meetup_b = _meetup(db, test_user.id, start + timedelta(minutes=10))
    _participant(db, meetup_a.id, test_user.id)
    _participant(db, meetup_b.id, test_user.id)
    activity = _activity(db, test_user.id, start + timedelta(minutes=20))

    assert attach_meetup_activities(db) == 2

    assert _activity_ids(db, meetup_a.id) == [activity.id]
    assert _activity_ids(db, meetup_b.id) == [activity.id]


def test_completed_meetup_with_late_upload_inside_seven_days_still_attaches(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    # 固定到 UTC 04:00（北京时间中午）附近，避免测试在北京时间深夜运行时，
    # “出发后 30 分钟”跨到北京次日，误把同一场约骑判断成不同日。
    start = datetime.now(timezone.utc).replace(hour=4, minute=0, second=0, microsecond=0) - timedelta(days=3)
    meetup = _meetup(db, test_user.id, start, status="COMPLETED")
    _participant(db, meetup.id, test_user.id)
    activity = _activity(db, test_user.id, start + timedelta(minutes=30))

    assert attach_meetup_activities(db) == 1

    assert _activity_ids(db, meetup.id) == [activity.id]


def test_cancelled_meetup_never_attaches(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup = _meetup(db, test_user.id, start, status="CANCELLED")
    _participant(db, meetup.id, test_user.id)
    _activity(db, test_user.id, start + timedelta(minutes=10))

    assert attach_meetup_activities(db) == 0

    assert _activity_ids(db, meetup.id) == []


def test_backfilled_yesterday_file_matches_by_started_at_not_upload_time(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime.now(timezone.utc) - timedelta(days=1)
    meetup = _meetup(db, test_user.id, start)
    _participant(db, meetup.id, test_user.id)
    activity = _activity(db, test_user.id, start + timedelta(minutes=10))

    assert attach_meetup_activities(db) == 1

    assert _activity_ids(db, meetup.id) == [activity.id]


def test_attach_tick_is_idempotent_when_run_twice(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup = _meetup(db, test_user.id, start)
    _participant(db, meetup.id, test_user.id)
    activity = _activity(db, test_user.id, start + timedelta(minutes=10))

    assert attach_meetup_activities(db) == 1
    assert attach_meetup_activities(db) == 0

    assert _activity_ids(db, meetup.id) == [activity.id]


def test_second_upload_for_same_user_same_meetup_keeps_one_cell(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup = _meetup(db, test_user.id, start)
    _participant(db, meetup.id, test_user.id)
    first = _activity(db, test_user.id, start + timedelta(minutes=10))
    _activity(db, test_user.id, start + timedelta(minutes=20))

    assert attach_meetup_activities(db) == 1
    assert attach_meetup_activities(db) == 0

    assert _activity_ids(db, meetup.id) == [first.id]


def test_resume_after_mid_loop_crash_keeps_existing_row_and_fills_rest(db, test_user):
    from app.meetup.cron import attach_meetup_activities
    from app.meetup.models import MeetupActivity

    other = _user(db, "resume-other")
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup = _meetup(db, test_user.id, start)
    _participant(db, meetup.id, test_user.id)
    _participant(db, meetup.id, other.id)
    first = _activity(db, test_user.id, start + timedelta(minutes=10))
    second = _activity(db, other.id, start + timedelta(minutes=20))
    db.add(MeetupActivity(meetup_id=meetup.id, user_id=test_user.id, activity_id=first.id))
    db.commit()

    assert attach_meetup_activities(db) == 1

    assert set(_activity_ids(db, meetup.id)) == {first.id, second.id}


def test_user_who_left_participants_before_upload_does_not_attach(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup = _meetup(db, test_user.id, start)
    row = _participant(db, meetup.id, test_user.id)
    db.delete(row)
    db.commit()
    _activity(db, test_user.id, start + timedelta(minutes=10))

    assert attach_meetup_activities(db) == 0

    assert _activity_ids(db, meetup.id) == []


def test_bj_evening_meetup_matches_same_bj_day_activity(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
    meetup = _meetup(db, test_user.id, start)
    _participant(db, meetup.id, test_user.id)
    activity = _activity(db, test_user.id, datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc))

    assert attach_meetup_activities(db) == 1

    assert _activity_ids(db, meetup.id) == [activity.id]


def test_future_meetup_does_not_match_today_activity(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime.now(timezone.utc) + timedelta(days=1)
    meetup = _meetup(db, test_user.id, start)
    _participant(db, meetup.id, test_user.id)
    _activity(db, test_user.id, datetime.now(timezone.utc))

    assert attach_meetup_activities(db) == 0

    assert _activity_ids(db, meetup.id) == []


def test_activity_started_thirty_one_minutes_before_start_does_not_attach(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup = _meetup(db, test_user.id, start)
    _participant(db, meetup.id, test_user.id)
    _activity(db, test_user.id, start - timedelta(minutes=31))

    assert attach_meetup_activities(db) == 0

    assert _activity_ids(db, meetup.id) == []


def test_processing_activity_does_not_attach(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime.now(timezone.utc) - timedelta(hours=2)
    meetup = _meetup(db, test_user.id, start)
    _participant(db, meetup.id, test_user.id)
    _activity(db, test_user.id, start + timedelta(minutes=10), status="processing")

    assert attach_meetup_activities(db) == 0

    assert _activity_ids(db, meetup.id) == []


def test_early_morning_bj_meetup_does_not_truncate_late_same_bj_day_activity(db, test_user):
    from app.meetup.cron import attach_meetup_activities

    start = datetime(2026, 6, 10, 16, 30, tzinfo=timezone.utc)
    meetup = _meetup(db, test_user.id, start)
    _participant(db, meetup.id, test_user.id)
    activity = _activity(db, test_user.id, datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc))

    assert attach_meetup_activities(db) == 1

    assert _activity_ids(db, meetup.id) == [activity.id]
