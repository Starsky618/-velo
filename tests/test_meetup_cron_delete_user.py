"""约骑模块 Task 7：cron 完成和删账号 hook 测试。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.meetup import service
from app.meetup.models import Meetup, MeetupMedia
from app.segment.models import Segment
from app.user.models import User


ROOT = Path(__file__).resolve().parents[1]


def _segment(db):
    segment = Segment(
        name="cron路线",
        distance=10000.0,
        elevation_gain=100.0,
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


def _meetup(db, user_id, status="OPEN", start_delta=-3, end_delta=-1):
    segment = _segment(db)
    start = datetime.now(timezone.utc) + timedelta(hours=start_delta)
    meetup = service.create_meetup(
        db,
        user_id,
        segment.id,
        None,
        start,
        datetime.now(timezone.utc) + timedelta(hours=end_delta),
        "集合点",
        "cruise",
        4,
        None,
    )
    if status == "OPEN":
        return service.publish_meetup(db, meetup.id, user_id)
    if status == "CANCELLED":
        service.publish_meetup(db, meetup.id, user_id)
        meetup.status = "CANCELLED"
        meetup.cancelled_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(meetup)
        return meetup
    return meetup


def test_cron_completes_open_meetups_after_estimated_end(db, test_user):
    from app.meetup import cron

    past = _meetup(db, test_user.id, status="OPEN", end_delta=-1)
    future = _meetup(db, test_user.id, status="OPEN", start_delta=1, end_delta=3)
    cancelled = _meetup(db, test_user.id, status="CANCELLED", start_delta=-3, end_delta=-1)

    changed = cron.complete_due_meetups(db)

    db.refresh(past)
    db.refresh(future)
    db.refresh(cancelled)
    assert changed == 1
    assert past.status == "COMPLETED"
    assert past.completed_at is not None
    assert future.status == "OPEN"
    assert cancelled.status == "CANCELLED"


def test_scheduler_has_independent_meetup_tick():
    source = (ROOT / "scheduler.py").read_text(encoding="utf-8")

    assert "from app.meetup.cron import run_meetup_complete_tick" in source
    assert "_meetup_tick_counter" in source
    assert "run_import_tick()" in source
    assert "run_meetup_complete_tick()" in source
    assert source.count("logger.exception") >= 2


def test_delete_user_cancels_open_deletes_draft_and_storage(db, test_user, monkeypatch):
    from app.user.service import delete_user

    user_id = test_user.id
    open_meetup = _meetup(db, user_id, status="OPEN", start_delta=5, end_delta=8)
    draft_meetup = _meetup(db, user_id, status="DRAFT", start_delta=5, end_delta=8)
    open_meetup_id = open_meetup.id
    draft_meetup_id = draft_meetup.id
    db.add(MeetupMedia(meetup_id=draft_meetup_id, uploader_id=user_id, type="image", file_id="202606/draft.jpg", seq=0))
    db.commit()
    deleted_files = []
    monkeypatch.setattr("app.meetup.service._storage.delete", lambda file_id: deleted_files.append(file_id))

    delete_user(db, user_id)

    cancelled = db.query(Meetup).filter(Meetup.id == open_meetup_id).first()
    draft = db.query(Meetup).filter(Meetup.id == draft_meetup_id).first()
    user = db.query(User).filter(User.id == user_id).first()
    media_count = db.query(MeetupMedia).filter(MeetupMedia.meetup_id == draft_meetup_id).count()
    assert cancelled.status == "CANCELLED"
    assert cancelled.cancelled_at is not None
    assert draft is None
    assert user is None
    assert media_count == 0
    assert deleted_files == ["202606/draft.jpg"]


def test_delete_user_uses_single_transaction():
    source = (ROOT / "app" / "user" / "service.py").read_text(encoding="utf-8")
    assert "def delete_user" in source
    block = source[source.index("def delete_user"):]

    assert "with db.begin()" in block
    assert "delete_draft_meetup(" not in block
    assert "db.commit()" not in block
