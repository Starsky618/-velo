"""
Sprint 7 Fix 5：列表 endpoint 双重过滤单测。

用户故事：Tim 打开 velo 首页活动列表 →
- 只看到骑行 + 完整数据的活动
- 跑步 / 徒步 / 半成品（importing/processing/failed）不显示
- 即使数据库里还有 5-14 Morning Run 等历史脏数据也被列表层挡住

覆盖 4 个场景：
1. 单条骑行 + completed → 显示
2. 跑步活动（activity_type='running'）→ 不显示
3. 半成品（status='importing' 或 'failed'）→ 不显示
4. 混合 4 条 → total + items 都只算骑行 completed
"""

from datetime import datetime, timezone

import pytest

from tests.conftest import _activities_table


def _insert_activity(
    db, user_id, title="测试", activity_type="cycling",
    status="completed", strava_activity_id=None,
):
    """直接 insert _activities_table（不经过 helper / 完整控制字段）。"""
    db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            title=title,
            status=status,
            file_url="20260519/test.gpx",
            distance=20000.0,
            duration=3600,
            elevation_gain=200.0,
            started_at=datetime(2026, 5, 18, 19, 29, 0, tzinfo=timezone.utc),
            activity_type=activity_type,
            strava_activity_id=strava_activity_id,
        )
    )
    db.commit()


class TestListFilterCycling:
    """列表 endpoint Fix 5 双重过滤覆盖。"""

    def test_cycling_completed_shows(self, client, auth_header, db, test_user):
        """单条骑行 + completed → 列表显示。"""
        _insert_activity(db, test_user.id, "骑行 50km", "cycling", "completed")

        resp = client.get("/api/activities?page=1&page_size=10", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_running_filtered_out(self, client, auth_header, db, test_user):
        """跑步活动 → 列表不显示（Fix 5 activity_type filter）。"""
        _insert_activity(db, test_user.id, "Morning Run", "running", "completed")

        resp = client.get("/api/activities?page=1&page_size=10", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_importing_filtered_out(self, client, auth_header, db, test_user):
        """半成品 status='importing' → 列表不显示（Fix 5 status filter）。"""
        _insert_activity(
            db, test_user.id, "导入中", "cycling", "importing",
            strava_activity_id=99001,
        )

        resp = client.get("/api/activities?page=1&page_size=10", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_failed_filtered_out(self, client, auth_header, db, test_user):
        """半成品 status='failed' → 列表不显示。"""
        _insert_activity(db, test_user.id, "失败骑行", "cycling", "failed")

        resp = client.get("/api/activities?page=1&page_size=10", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_cross_user_isolation(self, client, auth_header, db, test_user):
        """跨用户隔离：用户 A 不应看到用户 B 的骑行 + completed 活动。

        Fix 5 新增 filter 链不应破坏 filter_by(user_id) 的隔离保证。
        """
        # 用户 B 的骑行完整活动（test_user.id + 999 模拟另一个用户）
        other_user_id = test_user.id + 999
        _insert_activity(
            db, other_user_id, "他人的骑行", "cycling", "completed",
        )

        # test_user 拉自己列表 → 应看不到他人活动
        resp = client.get("/api/activities?page=1&page_size=10", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0, f"跨用户隔离失效 / 用户看到他人活动 total={data['total']}"
        assert data["items"] == []

    def test_mixed_only_cycling_completed_shows(
        self, client, auth_header, db, test_user
    ):
        """混合 4 条（骑行 completed + 跑步 + importing 骑行 + failed 骑行）→ total=1 + items=1。

        关键：total 是过滤后 count（集成审 Important-5 / 分页页码正确）。
        """
        _insert_activity(db, test_user.id, "Evening Ride", "cycling", "completed")
        _insert_activity(db, test_user.id, "Morning Run", "running", "completed")
        _insert_activity(
            db, test_user.id, "Importing Ride", "cycling", "importing",
            strava_activity_id=99002,
        )
        _insert_activity(db, test_user.id, "Failed Ride", "cycling", "failed")

        resp = client.get("/api/activities?page=1&page_size=10", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1, f"过滤后应只剩 1 条骑行 completed，实际 total={data['total']}"
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "Evening Ride"
