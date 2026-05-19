"""
Sprint 7 Fix 4：scheduler 周期重启 idle import_task 单测。

用户故事：Tim 在 Strava 上传新骑行 → 之前的导入早就 status='completed' →
没人主动唤醒就永远不会再拉新活动。_reactivate_idle_imports 是闹钟，
每 10 分钟把"已完成"的导入任务重新扔回 active 队列，tier1 重扫 Strava 列表。

覆盖 5 个场景：
1. completed + updated_at >10min 前 → 重启（4 字段全重置）
2. completed + updated_at <10min 前 → 不动（防过度抢配额）
3. 同 user 多条 completed → 只重启最新一条
4. active 任务 → 不动（防扰乱进行中的导入）
5. paused 任务 → 不动（暂停态由僵尸扫描/人工恢复管）
"""

from datetime import datetime, timezone, timedelta

import pytest

from app.strava.import_scheduler import _reactivate_idle_imports
from app.strava.models import StravaImport
from tests.conftest import _test_engine


@pytest.fixture()
def strava_imports_table(db):
    """确保 strava_imports 表在 SQLite 中存在。"""
    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    yield
    StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)


def _set_updated_at(db, import_id, when):
    """手动改 updated_at（绕开 ORM 的 onupdate）。"""
    db.execute(
        StravaImport.__table__.update()
        .where(StravaImport.id == import_id)
        .values(updated_at=when)
    )
    db.commit()


class TestReactivateIdleImports:
    """_reactivate_idle_imports 5 场景覆盖。"""

    def test_completed_idle_gets_reactivated(
        self, db, test_user, strava_imports_table
    ):
        """completed + updated_at >10min 前 → 4 字段全重置为 active 初始态。"""
        imp = StravaImport(
            user_id=test_user.id,
            strava_athlete_id=99001,
            status="completed",
            total_activities=50,
            tier1_completed=50,
            tier2_completed=50,
            cursor_before=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        db.add(imp)
        db.commit()
        # 改 updated_at 到 15 分钟前
        _set_updated_at(db, imp.id, datetime.now(timezone.utc) - timedelta(minutes=15))

        _reactivate_idle_imports(db)
        db.refresh(imp)

        assert imp.status == "active"
        assert imp.cursor_before is None
        assert imp.total_activities is None
        assert imp.tier1_completed == 0
        # tier2_completed 不重置（保留历史成绩用于前端展示）
        assert imp.tier2_completed == 50

    def test_completed_recent_not_touched(
        self, db, test_user, strava_imports_table
    ):
        """completed + updated_at <10min 前 → 不动（防过度抢配额）。"""
        imp = StravaImport(
            user_id=test_user.id,
            strava_athlete_id=99001,
            status="completed",
            total_activities=50,
            tier1_completed=50,
        )
        db.add(imp)
        db.commit()
        # 改 updated_at 到 5 分钟前（cutoff 之内）
        _set_updated_at(db, imp.id, datetime.now(timezone.utc) - timedelta(minutes=5))

        _reactivate_idle_imports(db)
        db.refresh(imp)

        assert imp.status == "completed"
        assert imp.total_activities == 50
        assert imp.tier1_completed == 50

    def test_multiple_completed_same_user_only_latest(
        self, db, test_user, strava_imports_table
    ):
        """同 user 多条 completed（迁移残留场景）→ 只重启最新一条，旧的保持 completed。"""
        old = StravaImport(
            user_id=test_user.id,
            strava_athlete_id=99001,
            status="completed",
            total_activities=10,
            tier1_completed=10,
        )
        new = StravaImport(
            user_id=test_user.id,
            strava_athlete_id=99001,
            status="completed",
            total_activities=50,
            tier1_completed=50,
        )
        db.add_all([old, new])
        db.commit()
        # 都 15 分钟前 / new 比 old 晚 1 分钟
        _set_updated_at(db, old.id, datetime.now(timezone.utc) - timedelta(minutes=16))
        _set_updated_at(db, new.id, datetime.now(timezone.utc) - timedelta(minutes=15))

        _reactivate_idle_imports(db)
        db.refresh(old)
        db.refresh(new)

        # 最新一条被重启
        assert new.status == "active"
        assert new.total_activities is None
        # 旧的不动
        assert old.status == "completed"
        assert old.total_activities == 10

    def test_active_not_touched(self, db, test_user, strava_imports_table):
        """active 任务即使 updated_at 很久前也不动（由僵尸扫描管）。"""
        imp = StravaImport(
            user_id=test_user.id,
            strava_athlete_id=99001,
            status="active",
            total_activities=100,
            tier1_completed=20,
        )
        db.add(imp)
        db.commit()
        _set_updated_at(db, imp.id, datetime.now(timezone.utc) - timedelta(minutes=30))

        _reactivate_idle_imports(db)
        db.refresh(imp)

        assert imp.status == "active"
        assert imp.total_activities == 100
        assert imp.tier1_completed == 20

    def test_paused_not_touched(self, db, test_user, strava_imports_table):
        """paused 任务不动（暂停态由人工/恢复流程管）。"""
        imp = StravaImport(
            user_id=test_user.id,
            strava_athlete_id=99001,
            status="paused",
            total_activities=30,
            tier1_completed=10,
        )
        db.add(imp)
        db.commit()
        _set_updated_at(db, imp.id, datetime.now(timezone.utc) - timedelta(minutes=60))

        _reactivate_idle_imports(db)
        db.refresh(imp)

        assert imp.status == "paused"
        assert imp.total_activities == 30
