"""
task-7.5：import-progress stalled + Redis 限速 的单测。

覆盖 7 个场景：
- 5 个 service.get_import_progress 场景（view_status 的 5 种状态）
- 2 个 router 限速场景（第二次 429 + Redis 挂降级放行）

依赖现有 conftest 的 db / client / test_user / auth_header fixture。
strava_imports 表用独立 fixture 按需建表。
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from app.strava import service
from app.strava.models import StravaImport
from tests.conftest import _test_engine


# ==================== 辅助 fixture ====================


@pytest.fixture()
def strava_imports_table(db):
    """确保 strava_imports 表在 SQLite 中存在。"""
    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    yield
    StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)


# ==================== service.get_import_progress 单测 ====================


class TestGetImportProgress:
    """service.get_import_progress 的 view_status 派生态测试。"""

    def test_view_status_none_when_no_import(self, db, test_user, strava_imports_table):
        """用户从未发起过导入 → view_status='none'。"""
        res = service.get_import_progress(db, test_user.id)
        assert res["view_status"] == "none"
        assert res["db_status"] is None
        assert res["total"] == 0
        assert res["completed"] == 0
        assert res["tier1_completed"] == 0

    def test_view_status_active_when_recently_updated(
        self, db, test_user, strava_imports_table
    ):
        """active 且 updated_at 是刚刚 → view_status='active'。"""
        imp = StravaImport(
            user_id=test_user.id,
            strava_athlete_id=99001,
            status="active",
            total_activities=100,
            tier1_completed=20,
            tier2_completed=5,
        )
        # 新建记录 updated_at=NOW()，staleness 接近 0
        db.add(imp)
        db.commit()

        res = service.get_import_progress(db, test_user.id)
        assert res["view_status"] == "active"
        assert res["db_status"] == "active"
        assert res["total"] == 100
        assert res["completed"] == 5
        assert res["tier1_completed"] == 20

    def test_view_status_stalled_when_updated_at_5min_ago(
        self, db, test_user, strava_imports_table
    ):
        """active 但 updated_at 超过 5 分钟 → view_status='stalled'（db_status 不变）。"""
        imp = StravaImport(
            user_id=test_user.id,
            strava_athlete_id=99001,
            status="active",
            total_activities=100,
        )
        db.add(imp)
        db.commit()

        # 手动改 updated_at 到 6 分钟前（绕开 ORM 的 onupdate）
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=6)
        db.execute(
            StravaImport.__table__.update()
            .where(StravaImport.id == imp.id)
            .values(updated_at=stale_time)
        )
        db.commit()

        res = service.get_import_progress(db, test_user.id)
        assert res["view_status"] == "stalled"
        assert res["db_status"] == "active"  # 数据库态不变，视图态派生

    def test_view_status_completed_passthrough(
        self, db, test_user, strava_imports_table
    ):
        """db_status='completed' 直接透传为 view_status='completed'。"""
        db.add(StravaImport(
            user_id=test_user.id,
            strava_athlete_id=99001,
            status="completed",
            total_activities=50,
            tier2_completed=50,
        ))
        db.commit()

        res = service.get_import_progress(db, test_user.id)
        assert res["view_status"] == "completed"
        assert res["db_status"] == "completed"
        assert res["total"] == 50
        assert res["completed"] == 50

    def test_view_status_paused_passthrough(
        self, db, test_user, strava_imports_table
    ):
        """db_status='paused' 直接透传为 view_status='paused'（不做 stalled 判定）。"""
        db.add(StravaImport(
            user_id=test_user.id,
            strava_athlete_id=99001,
            status="paused",
        ))
        db.commit()

        res = service.get_import_progress(db, test_user.id)
        assert res["view_status"] == "paused"
        assert res["db_status"] == "paused"


# ==================== router 限速单测 ====================


class TestImportProgressRateLimit:
    """GET /api/strava/import-progress 的 Redis 1s/user 限速测试。"""

    def test_rate_limit_blocks_second_call_within_1s(
        self, client, auth_header, db, test_user, strava_imports_table, monkeypatch
    ):
        """第一次放行，第二次（1 秒内）被 429。"""
        from app.strava import router as strava_router

        redis_mock = MagicMock()
        # 第一次 set nx 返 True（放行），第二次返 None/False（限速）
        redis_mock.set.side_effect = [True, None]
        monkeypatch.setattr(strava_router, "_redis", redis_mock)

        resp1 = client.get("/api/strava/import-progress", headers=auth_header)
        assert resp1.status_code == 200

        resp2 = client.get("/api/strava/import-progress", headers=auth_header)
        assert resp2.status_code == 429

    def test_rate_limit_degrades_when_redis_down(
        self, client, auth_header, db, test_user, strava_imports_table, monkeypatch
    ):
        """Redis 抛异常 → 降级放行（不阻断用户）。"""
        from app.strava import router as strava_router

        redis_mock = MagicMock()
        redis_mock.set.side_effect = Exception("redis down")
        monkeypatch.setattr(strava_router, "_redis", redis_mock)

        resp = client.get("/api/strava/import-progress", headers=auth_header)
        assert resp.status_code == 200
