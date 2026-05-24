"""Sprint 10 task-6：新活动完成后自动更新每日训练负荷。"""

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path

import pytest

from app.activity.models import Activity
from app.strava.models import StravaImport
from app.training.models import DailyTrainingLoad
from app.training.training_load import calculate_daily_atl, calculate_daily_ctl
from tests.conftest import _activities_table, _test_engine


ROOT = Path(__file__).resolve().parents[1]
_BJ_TZ = timezone(timedelta(hours=8))
_DEFAULT_STARTED_AT = object()


def _helper():
    from app.training.service import update_daily_load_for_activity

    return update_daily_load_for_activity


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
    day_offset: int = 0,
    tss: float | None,
    started_at=_DEFAULT_STARTED_AT,
    status: str = "completed",
    activity_type: str = "cycling",
) -> Activity:
    result = db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            title="训练负荷 hook 测试骑行",
            status=status,
            activity_type=activity_type,
            distance=30000.0,
            duration=3600,
            tss=tss,
            started_at=(
                _utc_for_bj_day(day_offset)
                if started_at is _DEFAULT_STARTED_AT
                else started_at
            ),
        )
    )
    db.commit()
    return db.get(Activity, result.inserted_primary_key[0])


def _daily_row(db, user_id: int, day):
    return db.query(DailyTrainingLoad).filter_by(user_id=user_id, date=day).one()


def test_update_daily_load_for_activity_writes_today_row(db, test_user):
    """GPX / Strava 单活动完成后，要能给当天写一页训练负荷账本。"""
    activity = _insert_activity(db, test_user.id, tss=84.0)

    written = _helper()(db, test_user, activity)

    row = _daily_row(db, test_user.id, _today_bj())
    assert written == 1
    assert row.tss_today == 84.0
    assert row.ctl == pytest.approx(round(calculate_daily_ctl(None, 84.0), 1))
    assert row.atl == pytest.approx(round(calculate_daily_atl(None, 84.0), 1))
    assert row.weekly_tss == 84


def test_activity_without_tss_uses_same_day_other_completed_rides(db, test_user):
    """当前 GPX 没有 TSS 时，当天账本仍要汇总同日其他有 TSS 的骑行。"""
    _insert_activity(db, test_user.id, tss=55.0)
    activity = _insert_activity(db, test_user.id, tss=None)

    _helper()(db, test_user, activity)

    row = _daily_row(db, test_user.id, _today_bj())
    assert row.tss_today == 55.0


def test_started_at_null_is_skipped_with_warning(db, test_user, caplog):
    """脏数据没有 started_at 时，helper 跳过并写日志，不影响主流程。"""
    activity = _insert_activity(db, test_user.id, tss=42.0, started_at=None)

    written = _helper()(db, test_user, activity)

    assert written == 0
    assert db.query(DailyTrainingLoad).count() == 0
    assert "started_at is NULL" in caplog.text


def test_existing_daily_row_is_updated_not_duplicated(db, test_user):
    """当天已有账本时要更新同一行，不能插出重复日期。"""
    day = _today_bj()
    existing = DailyTrainingLoad(
        user_id=test_user.id,
        date=day,
        ctl=1.0,
        atl=1.0,
        tsb=0.0,
        tss_today=1.0,
        weekly_tss=1,
        status_band="ok",
    )
    db.add(existing)
    db.commit()
    existing_id = existing.id
    activity = _insert_activity(db, test_user.id, tss=100.0)

    _helper()(db, test_user, activity)

    row = _daily_row(db, test_user.id, day)
    assert row.id == existing_id
    assert row.tss_today == 100.0
    assert db.query(DailyTrainingLoad).filter_by(user_id=test_user.id, date=day).count() == 1


def test_previous_load_seed_is_latest_record_not_only_recent_7_days(db, test_user):
    """用户两周没骑，今天的 CTL/ATL 要按空训练日逐日自然衰减。"""
    old_day = _today_bj() - timedelta(days=20)
    db.add(DailyTrainingLoad(
        user_id=test_user.id,
        date=old_day,
        ctl=50.0,
        atl=30.0,
        tsb=20.0,
        tss_today=0.0,
        weekly_tss=0,
        status_band="fresh",
    ))
    db.commit()
    activity = _insert_activity(db, test_user.id, tss=0.0)

    _helper()(db, test_user, activity)

    row = _daily_row(db, test_user.id, _today_bj())
    days_elapsed = (_today_bj() - old_day).days
    expected_ctl = 50.0 * math.exp(-days_elapsed / 42)
    expected_atl = 30.0 * math.exp(-days_elapsed / 7)
    assert row.ctl == pytest.approx(round(expected_ctl, 1))
    assert row.atl == pytest.approx(round(expected_atl, 1))


def test_helper_only_flushes_so_caller_controls_transaction(db, test_user):
    """helper 不能自己 commit，外层 worker 回滚时当天账本也应跟着回滚。"""
    activity = _insert_activity(db, test_user.id, tss=42.0)

    _helper()(db, test_user, activity)
    assert db.query(DailyTrainingLoad).count() == 1

    db.rollback()

    assert db.query(DailyTrainingLoad).count() == 0


def test_helper_acquires_user_load_lock_before_reading_daily_state(db, test_user, monkeypatch):
    """新活动和历史回填共用同一把用户账本锁，避免互相覆盖。"""
    from app.training import service as training_service

    activity = _insert_activity(db, test_user.id, tss=42.0)
    calls = []

    monkeypatch.setattr(
        training_service,
        "_acquire_user_daily_load_lock",
        lambda db_arg, user_id: calls.append(("lock", user_id)),
    )
    original_query_latest_before = training_service._query_latest_before

    def _record_query_latest_before(db_arg, user_id, target_day):
        calls.append(("read_previous", user_id, target_day))
        return original_query_latest_before(db_arg, user_id, target_day)

    monkeypatch.setattr(training_service, "_query_latest_before", _record_query_latest_before)

    training_service.update_daily_load_for_activity(db, test_user, activity)

    assert calls[:2] == [
        ("lock", test_user.id),
        ("read_previous", test_user.id, _today_bj()),
    ]


def test_postgres_user_daily_load_lock_uses_transaction_advisory_lock():
    """生产 PostgreSQL 用事务级 advisory lock，锁随外层 commit/rollback 自动释放。"""
    from app.training import service as training_service

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _FakeDb:
        def __init__(self):
            self.calls = []

        def get_bind(self):
            return _Bind()

        def execute(self, statement, params):
            self.calls.append((str(statement), params))

    fake_db = _FakeDb()

    training_service._acquire_user_daily_load_lock(fake_db, 7)

    # namespace 用 hashtext('daily-training-load') 跟项目既有 advisory lock 惯例一致（防裸整数碰撞）
    assert fake_db.calls == [
        (
            "SELECT pg_advisory_xact_lock(hashtext('daily-training-load'), :user_id)",
            {"user_id": 7},
        )
    ]


def test_strava_webhook_hook_calls_daily_load_helper(db, test_user, monkeypatch):
    """直接跑 Strava webhook hook，确认真实函数会调用 daily load helper。"""
    from app.strava import worker_strava

    activity = _insert_activity(db, test_user.id, tss=42.0)
    calls = []

    monkeypatch.setattr(worker_strava, "detect_5min_power_progress", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(worker_strava, "invalidate_power_curve_cache", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(worker_strava, "invalidate_heatmap_cache", lambda *args, **kwargs: None, raising=False)

    def _fake_update(db_arg, user_arg, activity_arg):
        calls.append((user_arg.id, activity_arg.id))
        return 1

    import app.training.service as training_service

    monkeypatch.setattr(training_service, "update_daily_load_for_activity", _fake_update)

    worker_strava._strava_post_parse_hooks(db, activity)

    assert calls == [(test_user.id, activity.id)]


def test_strava_webhook_hook_rolls_back_daily_load_savepoint(db, test_user, monkeypatch):
    """daily load helper 抛错时，Strava hook 只能回滚自己的 SAVEPOINT。"""
    from app.strava import worker_strava
    import app.training.service as training_service

    activity = _insert_activity(db, test_user.id, tss=42.0)

    monkeypatch.setattr(training_service, "update_daily_load_for_activity", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    worker_strava._strava_post_parse_hooks(db, activity)
    activity.status = "completed"
    db.commit()

    assert db.get(Activity, activity.id).status == "completed"


def test_strava_import_scheduler_completion_backfills_with_savepoint(db, test_user, monkeypatch):
    """tier2 完工：status 设 completed 后用 SAVEPOINT 跑全量 backfill，不提前 db.commit（status+updated_at+backfill 由 caller 统一提交，防僵尸扫描器在回填期间误判）。"""
    from app.strava import import_scheduler
    import scripts.backfill_daily_training_load as backfill_module

    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    import_task = StravaImport(user_id=test_user.id, strava_athlete_id=123, status="active")
    db.add(import_task)
    db.commit()
    calls = []

    original_commit = db.commit

    def _record_commit():
        calls.append(("commit", import_task.status))
        original_commit()

    def _fake_backfill(db_arg, user_id):
        calls.append(("backfill", user_id, import_task.status))
        return 0

    monkeypatch.setattr(db, "commit", _record_commit)
    monkeypatch.setattr(backfill_module, "backfill_daily_training_load_for_user", _fake_backfill)

    import_scheduler._run_tier2(db, client=None, import_task=import_task, user=test_user)

    # _run_tier2 完工分支不调 db.commit（SAVEPOINT release 不算 db.commit）/ status 已设 completed 才跑 backfill
    assert calls == [("backfill", test_user.id, "completed")]
    assert import_task.status == "completed"


def test_strava_import_scheduler_backfill_failure_keeps_completed(db, test_user, monkeypatch):
    """完工 backfill 失败只能记日志，不能把 import_task completed 回滚掉。"""
    from app.strava import import_scheduler
    import scripts.backfill_daily_training_load as backfill_module

    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    import_task = StravaImport(user_id=test_user.id, strava_athlete_id=456, status="active")
    db.add(import_task)
    db.commit()

    monkeypatch.setattr(backfill_module, "backfill_daily_training_load_for_user", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    import_scheduler._run_tier2(db, client=None, import_task=import_task, user=test_user)

    db.expire_all()
    assert db.get(StravaImport, import_task.id).status == "completed"


def test_single_activity_workers_have_savepoint_hooks_before_commit():
    """GPX 与 Strava webhook 两条单活动入口，都要在最终 commit 前跑 SAVEPOINT hook。"""
    worker = (ROOT / "app" / "activity" / "worker.py").read_text(encoding="utf-8")
    strava_worker = (ROOT / "app" / "strava" / "worker_strava.py").read_text(encoding="utf-8")

    gpx_block = worker[worker.index("步骤 10.8"):worker.index("db.commit()", worker.index("步骤 10.8"))]
    assert "步骤 10.9" in gpx_block
    assert "update_daily_load_for_activity" in gpx_block
    assert "db.begin_nested()" in gpx_block

    hooks_block = strava_worker[strava_worker.index("def _strava_post_parse_hooks"):strava_worker.index("def _wipe_activity_derived_data")]
    assert "update_daily_load_for_activity" in hooks_block
    assert "db.begin_nested()" in hooks_block
    hook_call = strava_worker.index("_strava_post_parse_hooks(db, activity)")
    next_commit = strava_worker.index("db.commit()", hook_call)
    assert hook_call < next_commit


def test_strava_import_scheduler_backfills_only_after_tier2_completion():
    """历史导入是倒序处理，不能逐条 hook；只能完工后调 task-3 的正序 backfill。"""
    text = (ROOT / "app" / "strava" / "import_scheduler.py").read_text(encoding="utf-8")
    complete_block = text[text.index("if activity is None:"):text.index("strava_id = activity.strava_activity_id")]
    activity_block = text[text.index("# ---- 适配 + 写入 ----"):text.index("# ---- 赛段匹配")]

    assert "backfill_daily_training_load_for_user" in complete_block
    # status 设 completed 在 backfill 之前 / backfill 用 SAVEPOINT 隔离 / 不提前 db.commit（caller 统一提交）
    assert complete_block.index('import_task.status = "completed"') < complete_block.index("backfill_daily_training_load_for_user")
    assert "db.begin_nested()" in complete_block
    assert "update_daily_load_for_activity" not in activity_block
