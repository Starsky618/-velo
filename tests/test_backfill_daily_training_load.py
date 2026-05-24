"""Sprint 10 task-3：历史训练负荷回填脚本测试。"""

from datetime import datetime, timedelta, timezone
import math

import pytest

from app.training.models import DailyTrainingLoad
from scripts.backfill_daily_training_load import (
    backfill_daily_training_load_for_all_users,
    backfill_daily_training_load_for_user,
    preview_daily_training_load_for_user,
)
from tests.conftest import _activities_table


_BJ_TZ = timezone(timedelta(hours=8))


def _today_bj():
    return datetime.now(_BJ_TZ).date()


def _utc_for_bj_day(day_offset: int, hour: int = 9) -> datetime:
    bj_day = _today_bj() + timedelta(days=day_offset)
    return datetime(
        bj_day.year,
        bj_day.month,
        bj_day.day,
        hour,
        0,
        0,
        tzinfo=_BJ_TZ,
    ).astimezone(timezone.utc)


def _insert_activity(
    db,
    user_id: int,
    *,
    day_offset: int,
    tss: float | None,
    hour: int = 9,
    status: str = "completed",
    activity_type: str = "cycling",
) -> int:
    result = db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            title="训练负荷测试骑行",
            status=status,
            activity_type=activity_type,
            distance=30000.0,
            duration=3600,
            tss=tss,
            started_at=_utc_for_bj_day(day_offset, hour),
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def _rows_for_user(db, user_id: int):
    return (
        db.query(DailyTrainingLoad)
        .filter(DailyTrainingLoad.user_id == user_id)
        .order_by(DailyTrainingLoad.date)
        .all()
    )


def test_preview_returns_rows_without_writing(db, test_user):
    """默认 dry-run 只算旧账本预览，不往 daily_training_load 写任何行。"""
    _insert_activity(db, test_user.id, day_offset=-1, tss=80.0)

    preview = preview_daily_training_load_for_user(db, test_user.id)

    assert len(preview) == 2
    assert preview[0].tss_today == 80.0
    assert db.query(DailyTrainingLoad).count() == 0


def test_backfill_user_writes_daily_rows(db, test_user):
    """apply 单用户会从最早骑行日写到今天。"""
    _insert_activity(db, test_user.id, day_offset=-1, tss=80.0)

    written = backfill_daily_training_load_for_user(db, test_user.id)

    rows = _rows_for_user(db, test_user.id)
    assert written == 2
    assert len(rows) == 2
    assert rows[0].date == _today_bj() - timedelta(days=1)
    assert rows[0].tss_today == 80.0
    assert rows[1].tss_today == 0.0


def test_backfill_user_is_idempotent_by_user_date(db, test_user):
    """复跑同一用户不能插重复行，只能更新同一张日期页。"""
    _insert_activity(db, test_user.id, day_offset=-1, tss=50.0)

    first_count = backfill_daily_training_load_for_user(db, test_user.id)
    db.commit()
    second_count = backfill_daily_training_load_for_user(db, test_user.id)
    db.commit()

    assert first_count == 2
    assert second_count == 2
    assert db.query(DailyTrainingLoad).filter_by(user_id=test_user.id).count() == 2


def test_backfill_user_skips_when_no_completed_cycling_activity(db, test_user):
    """没有完成态骑行时，脚本不写空账本。"""
    _insert_activity(db, test_user.id, day_offset=-1, tss=80.0, status="pending")
    _insert_activity(db, test_user.id, day_offset=-1, tss=80.0, activity_type="running")

    assert backfill_daily_training_load_for_user(db, test_user.id) == 0
    assert db.query(DailyTrainingLoad).count() == 0


def test_same_day_multiple_activities_are_summed(db, test_user):
    """同一天多条活动要合并成一页账本。"""
    _insert_activity(db, test_user.id, day_offset=-1, tss=60.0, hour=9)
    _insert_activity(db, test_user.id, day_offset=-1, tss=40.0, hour=18)

    backfill_daily_training_load_for_user(db, test_user.id)

    rows = _rows_for_user(db, test_user.id)
    assert rows[0].tss_today == 100.0
    assert rows[0].weekly_tss == 100


def test_first_day_ctl_starts_from_zero(db, test_user):
    """首日没有昨天数据，CTL 从 0 起步，只吃当天 TSS 的一小段。"""
    _insert_activity(db, test_user.id, day_offset=0, tss=84.0)

    backfill_daily_training_load_for_user(db, test_user.id)

    row = _rows_for_user(db, test_user.id)[0]
    expected = 84.0 * (1 - math.exp(-1 / 42))
    assert row.ctl == pytest.approx(round(expected, 1))


def test_all_gpx_without_tss_still_creates_zero_curve(db, test_user):
    """全是无 TSS 的 GPX，也要从首日到今天写 0 曲线，避免老用户入口空白。"""
    _insert_activity(db, test_user.id, day_offset=-1, tss=None)

    written = backfill_daily_training_load_for_user(db, test_user.id)

    rows = _rows_for_user(db, test_user.id)
    assert written == 2
    assert [row.tss_today for row in rows] == [0.0, 0.0]
    assert [row.status_band for row in rows] == ["ok", "ok"]


def test_helper_does_not_commit_so_caller_controls_transaction(db, test_user):
    """helper 只 flush，不 commit；Task 6 复用时仍由外层事务决定成败。"""
    _insert_activity(db, test_user.id, day_offset=0, tss=42.0)

    backfill_daily_training_load_for_user(db, test_user.id)
    assert db.query(DailyTrainingLoad).count() == 1

    db.rollback()

    assert db.query(DailyTrainingLoad).count() == 0


def test_backfill_acquires_same_user_lock_before_preview(db, test_user, monkeypatch):
    """历史回填要先锁住用户训练账本，再 preview 和 upsert，避免覆盖新活动 hook。"""
    import scripts.backfill_daily_training_load as backfill_module

    _insert_activity(db, test_user.id, day_offset=0, tss=42.0)
    calls = []

    monkeypatch.setattr(
        backfill_module,
        "_acquire_user_daily_load_lock",
        lambda db_arg, user_id: calls.append(("lock", user_id)),
    )
    original_preview = backfill_module.preview_daily_training_load_for_user

    def _record_preview(db_arg, user_id):
        calls.append(("preview", user_id))
        return original_preview(db_arg, user_id)

    monkeypatch.setattr(backfill_module, "preview_daily_training_load_for_user", _record_preview)

    backfill_module.backfill_daily_training_load_for_user(db, test_user.id)

    assert calls[:2] == [
        ("lock", test_user.id),
        ("preview", test_user.id),
    ]


def test_backfill_all_users_writes_each_user(db, test_user):
    """--all-users 路径要扫到两个用户，各自写入自己的训练负荷账本。"""
    from app.user.models import User

    other = User(openid="other_user")
    db.add(other)
    db.commit()
    db.refresh(other)
    _insert_activity(db, test_user.id, day_offset=0, tss=50.0)
    _insert_activity(db, other.id, day_offset=0, tss=70.0)

    result = backfill_daily_training_load_for_all_users(db)

    assert result[test_user.id] == 1
    assert result[other.id] == 1
    assert db.query(DailyTrainingLoad).filter_by(user_id=test_user.id).count() == 1
    assert db.query(DailyTrainingLoad).filter_by(user_id=other.id).count() == 1
