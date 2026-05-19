"""
Sprint 7 Fix 7+：segment_query.py 2 处赛段查询加 cycling filter 单测。

用户故事：DB 里同时存在跑步活动的赛段成绩 + 骑行活动的赛段成绩 →
- 赛段排行榜：只显示骑行 effort
- 我的赛段历史成绩：只显示骑行 effort

Codex 异源审抓的 spec 漏点（Claude 双审没抓到 / Tim 拍 spec 扩展加上）。

覆盖 2 个场景：
1. leaderboard 子查询过滤非骑行 effort
2. get_my_efforts_on_segment 过滤非骑行 effort
"""

from datetime import datetime, timezone

import pytest

from tests.conftest import _activities_table, _segment_efforts_table


def _insert_activity_typed(db, user_id, title, activity_type="cycling"):
    """插活动并指定 activity_type（既有 helper 不支持 activity_type 参数）。"""
    db.execute(_activities_table.insert().values(
        user_id=user_id,
        title=title,
        status="completed",
        file_url="test.gpx",
        distance=50000.0,
        started_at=datetime(2026, 4, 1, 8, 0, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        activity_type=activity_type,
    ))
    db.commit()
    result = db.execute(_activities_table.select().where(
        _activities_table.c.title == title
    )).first()
    return result.id


def _insert_segment_local(db, name="测试赛段"):
    """插赛段——复用 test_segment.py 的 _segments_table fixture 字段集。"""
    from tests.conftest import _segments_table
    db.execute(_segments_table.insert().values(
        name=name,
        distance=1000.0,
        elevation_gain=10.0,
        start_lat=37.87,
        start_lon=112.55,
        end_lat=37.875,
        end_lon=112.55,
        match_tolerance=50.0,
        min_match_ratio=0.8,
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    ))
    db.commit()
    result = db.execute(_segments_table.select().where(
        _segments_table.c.name == name
    )).first()
    return result.id


def _insert_effort_local(db, segment_id, activity_id, user_id, elapsed_time=100):
    """插赛段 effort——复用 test_segment.py _segment_efforts_table 真字段。"""
    db.execute(_segment_efforts_table.insert().values(
        segment_id=segment_id,
        activity_id=activity_id,
        user_id=user_id,
        elapsed_time=elapsed_time,
        avg_speed=10.0,
        avg_power=200.0,
        start_index=1,
        end_index=6,
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    ))
    db.commit()


class TestSegmentLeaderboardCyclingFilter:
    """leaderboard 排行榜过滤非骑行 effort。"""

    def test_leaderboard_excludes_non_cycling_effort(
        self, client, db, test_user
    ):
        """同一用户同一赛段：跑步 effort + 骑行 effort → 排行榜只显示骑行那条。"""
        seg_id = _insert_segment_local(db, "Fix7+ 测试赛段")

        # 用户 A：跑步活动（理论上 worker 守卫拦不让进 effort / 但脏数据模拟）
        run_act = _insert_activity_typed(db, test_user.id, "Morning Run", "running")
        _insert_effort_local(db, seg_id, run_act, test_user.id, elapsed_time=50)

        # 用户 A 在同赛段：骑行活动 effort
        ride_act = _insert_activity_typed(db, test_user.id, "Evening Ride", "cycling")
        _insert_effort_local(db, seg_id, ride_act, test_user.id, elapsed_time=200)

        resp = client.get(f"/api/segments/{seg_id}/leaderboard")
        assert resp.status_code == 200
        data = resp.json()

        # 排行榜应只显示骑行那条 / 跑步 effort 被过滤
        assert data["total"] == 1, f"应过滤跑步 effort / 实际 total={data['total']}"
        # 显示的是骑行 effort（elapsed_time=200）/ 不是跑步（更快的 50）
        assert data["items"][0]["elapsed_time"] == 200, \
            f"应显示骑行 effort 200s 不是跑步 50s / 实际 = {data['items'][0]['elapsed_time']}"
        assert data["items"][0]["activity_id"] == ride_act


class TestMyEffortsCyclingFilter:
    """get_my_efforts_on_segment 我的赛段历史只显示骑行 effort。"""

    def test_my_efforts_excludes_non_cycling(
        self, client, db, test_user, auth_header
    ):
        """我的赛段历史：混合骑行 + 跑步 effort → 只显示骑行。"""
        seg_id = _insert_segment_local(db, "Fix7+ 我的成绩测试")

        # 我的骑行 effort
        ride_act = _insert_activity_typed(db, test_user.id, "我的骑行", "cycling")
        _insert_effort_local(db, seg_id, ride_act, test_user.id, elapsed_time=180)

        # 我的跑步 effort（模拟脏数据）
        run_act = _insert_activity_typed(db, test_user.id, "我的跑步", "running")
        _insert_effort_local(db, seg_id, run_act, test_user.id, elapsed_time=120)

        resp = client.get(
            f"/api/segments/{seg_id}/my-efforts", headers=auth_header
        )
        assert resp.status_code == 200
        # response 包了 {"items": [...]} 不是裸 list
        data = resp.json()
        items = data["items"]

        # 只该看到骑行那条
        assert len(items) == 1, f"应只显示骑行 effort / 实际 count={len(items)}"
        assert items[0]["activity_id"] == ride_act, \
            f"应显示骑行 effort / 实际 activity_id={items[0]['activity_id']}"
