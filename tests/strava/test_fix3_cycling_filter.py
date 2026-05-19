"""
Sprint 7 Fix 3：tier1 / tier2 _is_cycling 守卫 + 短距离走完整流程 单测。

用户故事：
- Tim 在 Strava 上传 5-14 跑步 + 5-18 骑行 → tier1 list 拉到两条 →
  Fix 3 守卫拦住跑步活动不建骨架 → 只有骑行进 velo 数据库
- Tim 骑 3km 通勤 → tier1 守卫放行 → tier2 走完整流程拉详情+轨迹+赛段
  （v5+ 修订 / Tim 拍：取消 _MIN_DISTANCE_METERS 距离阈值）

覆盖 7 个场景：
1. _is_cycling 双字段 5 case（type / sport_type 组合）
2. tier1 混合 list（Ride + Run + Hike + EBikeRide）→ 只建骑行骨架
3. tier1 无 type 字段 → 保守拦截
4. tier2 短距离骑行（3km）→ 走完整流程 / 调 get_activity_detail（防回归）
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


# ==================== tier2 短距离走完整流程测试（v5+ 修订防回归）====================


class TestTier2ShortDistanceFullFlow:
    """tier2 短距离活动走完整流程——不再跳过详情拉取。

    v5+ 修订（Tim 拍 / 2026-05-19）：取消 _MIN_DISTANCE_METERS = 5000 距离阈值。
    所有骑行（含 3km 通勤）走完整 tier2 流程拉详情+轨迹+赛段。原 5km 跳过是
    过早优化（velo 1 用户量级 Strava 配额用不完 90%），让短骑行有完整数据更重要。

    本测试防回归——未来若有人重新加 _MIN_DISTANCE_METERS / 短距离跳过 detail，
    本测试会立刻 fail 阻止合入。
    """

    def test_short_distance_calls_detail_api(self, strava_db, strava_user):
        """3km 短距离活动 → tier2 调用 get_activity_detail（不被跳过）。"""
        import_task = StravaImport(
            user_id=strava_user.id,
            strava_athlete_id=88888,
            status="active",
            total_activities=1,
            tier1_completed=1,
        )
        short_act = Activity(
            user_id=strava_user.id,
            status="importing",
            data_source="strava",
            strava_activity_id=8001,
            distance=3000,  # 3km 短距离通勤
        )
        strava_db.add_all([import_task, short_act])
        strava_db.commit()

        # mock client：detail 抛 ValueError 让 tier2 在拉 detail 后立刻进 failed 分支
        # （避免走完整 streams + adapter 链的复杂 mock，但能证明 detail 被调到）
        fake_client = MagicMock()
        fake_client.get_activity_detail.side_effect = ValueError("mocked stop")

        _run_tier2(strava_db, fake_client, import_task, strava_user)

        # 关键断言：get_activity_detail 必须被调用（防"短距离被跳过详情"回归）
        fake_client.get_activity_detail.assert_called_once_with(8001)

        # 活动状态：拉详情失败 → status='failed'（已通过短距离跳过分支 / 进了拉详情逻辑）
        strava_db.refresh(short_act)
        assert short_act.status == "failed", \
            f"应走完整 tier2 流程进 failed 分支（mock 异常），实际 = {short_act.status}"
        assert "mocked stop" in (short_act.error_message or "")
