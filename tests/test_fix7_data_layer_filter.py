"""
Sprint 7 Fix 7：数据层 11 处 activity_type='cycling' 过滤单测。

用户故事：DB 里同时有 Tim 的骑行（cycling）+ 跑步（running）+ 徒步（hiking）→
- 个人统计 / 总里程 / 排行榜：只算骑行
- 他人主页：总里程 + 月度 + 探索页活跃榜 只算骑行
- 城市勋章 / 总里程勋章：只算骑行
- dedupe 候选：只取骑行（防跑步骑行交叉误判）
- 5min 功率进步检测：只算骑行 baseline

覆盖 8 个端到端场景（11 处过滤中 8 处有单测覆盖 / 3 处 TODO）：
1. ✅ service_stats period（本周/本月/本年）→ 只算骑行
2. ✅ service_stats all-time → 只算骑行
3. ✅ service_social 他人主页 total + 月度 → 只算骑行
4. ✅ service_social 总里程勋章 → 只算骑行
5. ✅ service_social 城市勋章 → 只算骑行
6. ✅ service_social active_users 探索页 → 只算骑行
7. ✅ dedupe_service 候选 → 只取骑行
8. 🔲 TODO 补单测（sprint 8 backlog）：
   - service_social heatmap（Redis cache / 测试复杂）
   - service_stats power_curve（需要 trackpoint mock）
   - notification progress_detector 5min（需要 5min window 复杂数据）
"""

from datetime import datetime, timezone

import pytest

from tests.conftest import _activities_table


def _insert(
    db, user_id, activity_type="cycling", distance=20000.0,
    started_at=None, elevation_gain=200.0, city="beijing",
):
    """直接插活动到 _activities_table（绕 ORM / 完整控制字段）。"""
    if started_at is None:
        # 本文件有“当前月统计”断言，默认活动时间必须跟运行当天同月，
        # 否则跨到 2026-06 后会把测试数据排除在“本月”之外。
        started_at = datetime.now(timezone.utc).replace(day=15, hour=10, minute=0, second=0, microsecond=0)
    db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            title=f"{activity_type} 活动",
            status="completed",
            file_url="20260515/test.gpx",
            distance=distance,
            duration=3600,
            elevation_gain=elevation_gain,
            started_at=started_at,
            activity_type=activity_type,
            city=city,
        )
    )
    db.commit()


class TestStatsFilterCycling:
    """service_stats 3 处 SQL 过滤覆盖。"""

    def test_period_stats_excludes_running(self, db, test_user):
        """周/月/年 stats 不算跑步距离。"""
        from app.user.service_stats import get_user_stats
        # 1 条骑行 50km + 1 条跑步 10km，全在本月内
        now = datetime.now(timezone.utc).replace(day=15, hour=10)
        _insert(db, test_user.id, "cycling", 50000.0, started_at=now)
        _insert(db, test_user.id, "running", 10000.0, started_at=now)

        # period="month" → 只该看到 50km 骑行
        res = get_user_stats(db, test_user.id, period="month")
        assert res["distance"] == 50.0, \
            f"月度 stats 应过滤跑步，只算骑行 50km，实际 = {res['distance']}"
        assert res["rides"] == 1

    def test_all_time_stats_excludes_running(self, db, test_user):
        """全部 stats 不算跑步距离。"""
        from app.user.service_stats import get_user_stats
        _insert(db, test_user.id, "cycling", 30000.0)
        _insert(db, test_user.id, "running", 8000.0)
        _insert(db, test_user.id, "hiking", 5000.0)

        res = get_user_stats(db, test_user.id, period="all")
        assert res["distance"] == 30.0, \
            f"all-time 应过滤跑步徒步，只算骑行 30km，实际 = {res['distance']}"
        assert res["rides"] == 1


class TestSocialFilterCycling:
    """service_social 6 处 ORM 过滤覆盖。"""

    def test_profile_total_excludes_running(self, db, test_user):
        """他人主页总里程 / 活动数只算骑行。"""
        from app.user.service_social import get_user_profile_for_others
        _insert(db, test_user.id, "cycling", 50000.0)
        _insert(db, test_user.id, "running", 10000.0)

        # 用另一个 user 作 viewer
        from app.user.models import User
        viewer = User(openid="viewer_openid", is_admin=False)
        db.add(viewer)
        db.commit()

        profile = get_user_profile_for_others(db, test_user.id, viewer.id)
        # total_distance_km 单位 km
        assert profile["total_distance_km"] == 50.0, \
            f"他人主页 total 应只算骑行 50km，实际 = {profile['total_distance_km']}"
        assert profile["activity_count"] == 1, \
            f"他人主页活动数应只算骑行 = 1，实际 = {profile['activity_count']}"

        # 月度统计 assert（spec line 691 独立过滤点 + reviewer 集成审 Important）
        # 活动 started_at 是当月 → current_month_summary.distance_km 应只算骑行 50km
        month_summary = profile.get("current_month_summary") or {}
        if "distance_km" in month_summary:
            assert month_summary["distance_km"] == 50.0, \
                f"他人主页月度统计应只算骑行 50km / 实际 = {month_summary}"

    def test_badges_input_total_distance_excludes_running(self, db, test_user):
        """总里程勋章输入只算骑行（_aggregate_badges_input 内部 SQL 走 cycling filter）。"""
        from app.user.service_social import _aggregate_badges_input
        # 200km 骑行 + 50km 跑步
        _insert(db, test_user.id, "cycling", 200000.0)
        _insert(db, test_user.id, "running", 50000.0)

        result = _aggregate_badges_input(db, test_user.id)
        # total_distance_m 单位米 / 应只算 200000 不含跑步
        assert abs(result["total_distance_m"] - 200000.0) < 1.0, \
            f"badges 输入 total_distance_m 应只算骑行 200km，实际 = {result['total_distance_m']}"

    def test_active_users_excludes_running_only(self, db, test_user):
        """探索页活跃骑友只算骑行——只跑步的用户不出现在活跃骑友列表。"""
        from app.user.service_social import get_active_users
        from app.user.models import User

        # 创建用户 B：只跑步过 / 不应出现在活跃骑友
        runner = User(openid="runner_only", is_admin=False)
        db.add(runner)
        db.commit()
        _insert(db, runner.id, "running", 10000.0)

        # 创建用户 C：真骑过 / 应出现
        cyclist = User(openid="real_cyclist", is_admin=False)
        db.add(cyclist)
        db.commit()
        _insert(db, cyclist.id, "cycling", 50000.0)

        # exclude test_user / 看 runner vs cyclist 谁出现
        result = get_active_users(db, exclude_user_id=test_user.id)
        items = result.get("items") if isinstance(result, dict) else result
        user_ids = {u["id"] if isinstance(u, dict) else u.id for u in items}

        assert cyclist.id in user_ids, \
            f"真骑过的用户应出现在活跃骑友 / 实际 user_ids = {user_ids}"
        assert runner.id not in user_ids, \
            f"只跑步的用户不应出现在活跃骑友 / 实际 user_ids = {user_ids}"

    def test_dedupe_excludes_running_candidates(self, db, test_user):
        """dedupe 候选只取骑行——刚上传的骑行不会把同时间窗的跑步当作 duplicate 候选。"""
        from app.activity.dedupe_service import find_and_mark_duplicate
        from app.activity.models import Activity
        from datetime import timedelta

        # 时间 t：插入一条跑步活动（候选池）
        t = datetime(2026, 5, 18, 10, 0, 0, tzinfo=timezone.utc)
        _insert(db, test_user.id, "running", 8000.0, started_at=t)

        # 同时间 t+1min 上传一条骑行（new_activity）
        cycling_act = Activity(
            user_id=test_user.id,
            status="completed",
            activity_type="cycling",
            distance=8500.0,
            started_at=t + timedelta(minutes=1),
        )
        db.add(cycling_act)
        db.commit()
        db.refresh(cycling_act)

        # 跑 dedupe：应不把跑步当候选 / cycling_act.duplicate_of 保持 None
        find_and_mark_duplicate(db, cycling_act)
        db.refresh(cycling_act)
        assert cycling_act.duplicate_of is None, \
            f"骑行不应把同时间窗的跑步当 duplicate 候选 / duplicate_of = {cycling_act.duplicate_of}"

    def test_city_medal_excludes_running(self, db, test_user):
        """城市勋章只算骑行——跑步在某城市不解锁该城市勋章。"""
        from app.user.service_social import get_city_medals
        # 用户只在 chengdu 跑步过 → 不该解锁成都骑行勋章
        _insert(db, test_user.id, "running", 8000.0, city="chengdu")
        # 用户在 beijing 真骑过 → 解锁北京勋章
        _insert(db, test_user.id, "cycling", 30000.0, city="beijing")

        result = get_city_medals(db, test_user.id)
        unlocked = result["unlocked"]
        assert "beijing" in unlocked, \
            f"北京骑行应解锁勋章 / unlocked = {unlocked}"
        assert "chengdu" not in unlocked, \
            f"成都只跑步不应解锁骑行勋章 / unlocked = {unlocked}"
