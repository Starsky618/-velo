"""GLO 赛段回填与约骑快照的一致性测试。"""

from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import text

from app.meetup.models import Meetup
from app.segment.models import Segment


def _segment(db) -> Segment:
    segment = Segment(
        name="测试山路",
        distance=1000.0,
        elevation_gain=80.0,
        elevation_loss=20.0,
        avg_gradient=6.0,
        elevation_profile=json.dumps([700.0, 780.0]),
        start_lat=37.8,
        start_lon=112.5,
        end_lat=37.9,
        end_lon=112.6,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        difficulty="medium",
        max_gradient=8.0,
        city="taiyuan",
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _segment_meetup(db, segment_id, *, status, start_time, snapshot_climb=999.0):
    meetup = Meetup(
        status=status,
        segment_id=segment_id,
        snapshot_route_name="旧赛段快照",
        snapshot_distance=1000.0,
        snapshot_climb=snapshot_climb,
        snapshot_city="taiyuan",
        start_time=start_time,
        estimated_end_time=start_time + timedelta(hours=3),
        meeting_point="集合点",
        pace_level="cruise",
        max_participants=6,
    )
    db.add(meetup)
    return meetup


def _new_values(*, climb=123.4):
    return {
        "elevation_profile": [700.0, 823.4],
        "elevation_gain": climb,
        "elevation_loss": 0.0,
        "avg_gradient": 12.3,
        "max_gradient": 12.3,
        "difficulty": "hard",
    }


def test_recompute_all_refreshes_all_product_visible_segment_meetups(db, monkeypatch):
    from scripts import recompute_segment_stats as script

    segment = _segment(db)
    now = datetime.now(timezone.utc)
    linked_meetups = [
        _segment_meetup(
            db,
            segment.id,
            status="DRAFT",
            start_time=now - timedelta(days=1),
        ),
        _segment_meetup(
            db,
            segment.id,
            status="OPEN",
            start_time=now + timedelta(days=1),
        ),
        _segment_meetup(
            db,
            segment.id,
            status="OPEN",
            start_time=now - timedelta(hours=1),
        ),
        _segment_meetup(
            db,
            segment.id,
            status="COMPLETED",
            start_time=now - timedelta(days=1),
        ),
        _segment_meetup(
            db,
            segment.id,
            status="CANCELLED",
            start_time=now + timedelta(days=1),
        ),
    ]
    db.commit()
    meetup_ids = [meetup.id for meetup in linked_meetups]
    monkeypatch.setattr(script, "recompute_one_segment", lambda *_args, **_kwargs: _new_values())

    stats = script.recompute_all(db, apply_changes=True)

    db.expire_all()
    refreshed = db.query(Meetup).filter(Meetup.id.in_(meetup_ids)).all()
    assert stats["updated"] == 1
    assert stats["failed"] == 0
    assert {meetup.snapshot_climb for meetup in refreshed} == {123.4}


def test_recompute_all_repairs_snapshot_when_segment_values_are_unchanged(
    db,
    monkeypatch,
):
    from scripts import recompute_segment_stats as script

    segment = _segment(db)
    future_meetup = _segment_meetup(
        db,
        segment.id,
        status="OPEN",
        start_time=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.commit()
    meetup_id = future_meetup.id
    unchanged_values = {
        "elevation_profile": [700.0, 780.0],
        "elevation_gain": 80.0,
        "elevation_loss": 20.0,
        "avg_gradient": 6.0,
        "max_gradient": 8.0,
        "difficulty": "medium",
    }
    monkeypatch.setattr(
        script,
        "recompute_one_segment",
        lambda *_args, **_kwargs: unchanged_values,
    )

    stats = script.recompute_all(db, apply_changes=True)

    stored_meetup = db.query(Meetup).filter(Meetup.id == meetup_id).one()
    assert stats["unchanged"] == 1
    assert stats["updated"] == 0
    assert stored_meetup.snapshot_climb == 80.0


def test_recompute_all_tolerates_database_without_meetups_table(db, monkeypatch):
    from scripts import recompute_segment_stats as script

    _segment(db)
    db.execute(text("DROP TABLE meetups"))
    db.commit()
    monkeypatch.setattr(script, "recompute_one_segment", lambda *_args, **_kwargs: _new_values())

    stats = script.recompute_all(db, apply_changes=True)

    assert stats["updated"] == 1
    assert stats["failed"] == 0
