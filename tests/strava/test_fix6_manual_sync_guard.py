"""
Sprint 7 Fix 6：handle_manual_sync 加 _is_cycling 守卫单测。

用户故事：Tim 点小程序"立即同步"按钮 → manual_sync 拉 Strava 最近 30 条 →
跑步/徒步活动一律跳过 / 只有骑行进 velo 数据库。
（manual_sync 是独立路径 / 不走 scheduler tier1 / 必须有自己的守卫）

覆盖 3 个场景：
1. 混合 list（Ride + Run + Hike）→ 只有 Ride 建 importing 骨架
2. 全 Run（极端 case）→ 0 条新增 / DB 干净
3. 复用 Fix 3 抽的 _is_cycling helper（同源 / 不复制粘贴 _CYCLING_TYPES）
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.activity.models import Activity
from app.strava import service
from app.strava.models import StravaImport
from app.user.models import User
from tests.conftest import _test_engine


@pytest.fixture()
def strava_imports_table(db):
    """确保 strava_imports 表在 SQLite 中存在。"""
    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    yield
    StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)


def _make_user(db):
    """手工创建带 Strava 绑定的 User。"""
    user = User(
        openid=f"openid_{uuid.uuid4().hex[:12]}",
        is_admin=False,
        strava_athlete_id=99001,
        strava_access_token="at",
        strava_refresh_token="rt",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestManualSyncCyclingGuard:
    """handle_manual_sync 加 _is_cycling 守卫覆盖。"""

    @patch("app.queue.redis_conn")
    @patch("app.strava.client.StravaClient")
    def test_manual_sync_filters_run_and_hike(
        self, MockClient, MockRedisConn, db, strava_imports_table
    ):
        """混合 list（Ride + Run + Hike + EBikeRide）→ 只建 2 条骑行骨架。"""
        user = _make_user(db)
        imp = StravaImport(
            user_id=user.id, strava_athlete_id=99001, status="active",
            total_activities=None, tier1_completed=0,
        )
        db.add(imp)
        db.commit()

        MockRedisConn.set.return_value = True  # 冷却 set NX 放行

        client_instance = MockClient.return_value
        client_instance.get_athlete_activities.return_value = [
            {"id": 5001, "name": "Morning Run", "type": "Run",
             "distance": 5000, "start_date": "2026-05-14T08:00:00Z"},
            {"id": 5002, "name": "Evening Ride", "type": "Ride",
             "distance": 55000, "start_date": "2026-05-18T19:29:00Z"},
            {"id": 5003, "name": "Weekend Hike", "type": "Hike",
             "distance": 8000, "start_date": "2026-05-17T10:00:00Z"},
            {"id": 5004, "name": "E-Bike Commute", "type": "EBikeRide",
             "distance": 12000, "start_date": "2026-05-16T07:00:00Z"},
        ]

        service.handle_manual_sync(db, user.id)

        # 只有 Ride + EBikeRide 进 velo / Run + Hike 被拦
        activities = db.query(Activity).filter_by(user_id=user.id).all()
        strava_ids = {a.strava_activity_id for a in activities}
        assert strava_ids == {5002, 5004}, \
            f"应只建骑行骨架，实际建了：{strava_ids}"

        # tier1_completed 累加 2（只算骑行）
        db.refresh(imp)
        assert imp.tier1_completed == 2

    @patch("app.queue.redis_conn")
    @patch("app.strava.client.StravaClient")
    def test_manual_sync_all_runs_creates_nothing(
        self, MockClient, MockRedisConn, db, strava_imports_table
    ):
        """全 Run（极端 case）→ 0 条新增 / DB 干净。"""
        user = _make_user(db)

        MockRedisConn.set.return_value = True

        client_instance = MockClient.return_value
        client_instance.get_athlete_activities.return_value = [
            {"id": 6001, "name": "Run 1", "type": "Run",
             "distance": 5000, "start_date": "2026-05-01T08:00:00Z"},
            {"id": 6002, "name": "Run 2", "type": "Run",
             "distance": 8000, "start_date": "2026-05-02T08:00:00Z"},
        ]

        service.handle_manual_sync(db, user.id)

        activities = db.query(Activity).filter_by(user_id=user.id).all()
        assert len(activities) == 0, "全跑步的 list 应不建任何骨架"

    @patch("app.queue.redis_conn")
    @patch("app.strava.client.StravaClient")
    def test_manual_sync_missing_type_filtered(
        self, MockClient, MockRedisConn, db, strava_imports_table
    ):
        """无 type 字段的活动（异常 Strava 响应）→ 保守拦截 / 同 tier1。"""
        user = _make_user(db)

        MockRedisConn.set.return_value = True

        client_instance = MockClient.return_value
        client_instance.get_athlete_activities.return_value = [
            # 无 type 字段（异常响应 / 与 tier1 处理保持一致）
            {"id": 7001, "name": "Mystery",
             "distance": 10000, "start_date": "2026-05-01T08:00:00Z"},
        ]

        service.handle_manual_sync(db, user.id)

        activities = db.query(Activity).filter_by(user_id=user.id).all()
        assert len(activities) == 0, "无 type 字段也应被拦截（保守防御）"
