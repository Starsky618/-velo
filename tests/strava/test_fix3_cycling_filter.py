"""
Sprint 7 Fix 3：tier1 / tier2 _is_cycling 守卫 + 短距离 activity_type 回填 单测。

用户故事：Tim 在 Strava 上传 5-14 跑步 + 5-18 骑行 → tier1 list 拉到两条 →
Fix 3 守卫拦住跑步活动不建骨架 → 只有骑行进 velo 数据库 →
未来跑步永不污染 velo 骑行列表。

覆盖 6 个场景：
1. _is_cycling 双字段 5 case（type / sport_type 组合）
2. tier1 混合 list（Ride + Run + Hike）→ 只建 Ride 骨架
3. tier2 短距离骑行 → activity_type='other' 兜底
"""

from unittest.mock import MagicMock, patch

import pytest

from app.strava.import_scheduler import _is_cycling, _do_tick, _run_tier2
from app.activity.models import Activity
from app.strava.models import StravaImport
from app.user.models import User
from tests.conftest import _test_engine


# ==================== fixture ====================


@pytest.fixture()
def strava_db(db):
    """扩展 db fixture，额外建 strava_imports 表。"""
    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    yield db
    StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)


@pytest.fixture()
def strava_user(db):
    """创建一个绑定 Strava 的测试用户。"""
    user = User(
        openid="fix3_test_user",
        is_admin=False,
        strava_athlete_id=88888,
        strava_access_token="fake_access_token",
        strava_refresh_token="fake_refresh_token",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ==================== _is_cycling 双字段 helper 测试 ====================


class TestIsCycling:
    """_is_cycling 双字段（type + sport_type）守卫覆盖。"""

    def test_type_ride_true(self):
        """type='Ride' → True（最常见骑行）。"""
        assert _is_cycling({"type": "Ride"}) is True

    def test_type_run_false(self):
        """type='Run' → False（Bug B 拦截点）。"""
        assert _is_cycling({"type": "Run"}) is False

    def test_sport_type_only_true(self):
        """type 缺失 + sport_type='VirtualRide' → True（Strava 2022 后新字段命中）。"""
        assert _is_cycling({"sport_type": "VirtualRide"}) is True

    def test_both_fields_empty_false(self):
        """type + sport_type 都缺失 → False（保守拦截 / 不放过未知）。"""
        assert _is_cycling({}) is False

    def test_either_field_match(self):
        """type 不在集合但 sport_type 在集合 → True（任一字段命中即骑行）。"""
        assert _is_cycling({"type": "Workout", "sport_type": "EBikeRide"}) is True


# ==================== tier1 守卫集成测试 ====================


class TestTier1CyclingGuard:
    """tier1 拉 Strava list 后只为骑行建骨架。"""

    @patch("app.strava.import_scheduler.StravaClient")
    def test_tier1_filters_run_and_hike(
        self, MockClient, strava_db, strava_user
    ):
        """混合 list（Ride + Run + Hike + EBikeRide）→ 只建 Ride 和 EBikeRide 骨架。"""
        import_task = StravaImport(
            user_id=strava_user.id,
            strava_athlete_id=88888,
            status="active",
        )
        strava_db.add(import_task)
        strava_db.commit()

        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        mock_instance.get_athlete_activities.return_value = [
            {"id": 9001, "name": "Morning Run", "type": "Run",
             "distance": 5000, "start_date": "2026-05-14T08:00:00Z"},
            {"id": 9002, "name": "Evening Ride", "type": "Ride",
             "distance": 55000, "start_date": "2026-05-18T19:29:00Z"},
            {"id": 9003, "name": "Weekend Hike", "type": "Hike",
             "distance": 8000, "start_date": "2026-05-17T10:00:00Z"},
            {"id": 9004, "name": "E-Bike", "type": "EBikeRide",
             "distance": 30000, "start_date": "2026-05-16T15:00:00Z"},
        ]

        _do_tick(strava_db)

        # 只有 Ride + EBikeRide 进 velo / Run + Hike 被拦
        activities = strava_db.query(Activity).filter_by(
            user_id=strava_user.id, status="importing"
        ).all()
        strava_ids = {a.strava_activity_id for a in activities}
        assert strava_ids == {9002, 9004}, \
            f"应只建骑行骨架，实际建了：{strava_ids}"

        # tier1_completed 也只算建了的 2 条
        strava_db.refresh(import_task)
        assert import_task.tier1_completed == 2

    @patch("app.strava.import_scheduler.StravaClient")
    def test_tier1_missing_type_filtered_out(
        self, MockClient, strava_db, strava_user
    ):
        """无 type / sport_type 字段的活动 → 也被拦（保守防御）。"""
        import_task = StravaImport(
            user_id=strava_user.id,
            strava_athlete_id=88888,
            status="active",
        )
        strava_db.add(import_task)
        strava_db.commit()

        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        # 两条都没 type 字段（异常 Strava 响应）
        mock_instance.get_athlete_activities.return_value = [
            {"id": 7001, "name": "Mystery 1", "distance": 10000,
             "start_date": "2026-05-01T08:00:00Z"},
            {"id": 7002, "name": "Mystery 2", "distance": 20000,
             "start_date": "2026-05-02T08:00:00Z"},
        ]

        _do_tick(strava_db)

        activities = strava_db.query(Activity).filter_by(
            user_id=strava_user.id, status="importing"
        ).all()
        assert len(activities) == 0, "无 type 字段的活动也应被拦截"


# ==================== tier2 短距离回填测试 ====================


class TestTier2ShortDistanceBackfill:
    """tier2 短距离分支补 activity_type='other' 回填。"""

    def test_short_distance_sets_other_type(self, strava_db, strava_user):
        """活动距离 < 5km → status='completed' + activity_type='other'。"""
        import_task = StravaImport(
            user_id=strava_user.id,
            strava_athlete_id=88888,
            status="active",
            total_activities=1,
            tier1_completed=1,
        )
        # 一条 3km 短距离 importing 活动（tier1 已建骨架）
        short_act = Activity(
            user_id=strava_user.id,
            status="importing",
            data_source="strava",
            strava_activity_id=8001,
            distance=3000,  # < 5km
        )
        strava_db.add_all([import_task, short_act])
        strava_db.commit()

        # 用 fake client（不会被调到，tier2 短距离分支直接 return）
        fake_client = MagicMock()

        _run_tier2(strava_db, fake_client, import_task, strava_user)

        strava_db.refresh(short_act)
        assert short_act.status == "completed"
        assert short_act.activity_type == "other", \
            f"短距离应回填 'other'，实际 = {short_act.activity_type}"

        # tier2_skipped 累加 / 防进度卡片漂移
        strava_db.refresh(import_task)
        assert import_task.tier2_skipped == 1

        # detail API 不应被调（短距离在拉 detail 前 return）
        fake_client.get_activity_detail.assert_not_called()
