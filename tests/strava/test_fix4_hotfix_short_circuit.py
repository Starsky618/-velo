"""
Sprint 7 hotfix（Fix 4 真用回归暴露设计 bug / 2026-05-19）：
tier1 加 all_exists 短路——拉一批 30 条全部已存在 → 等同空 list / 立刻 tier1 完成。

用户故事：Tim 在 Strava 上传新骑行 → Fix 4 周期重启 idle import_task → tier1 拉最新批 →
- 有新骑行 → created=N → cursor 推进 → 下次拉更老批 → 直到 1 批 all_exists → tier1 完成
- 无新骑行 → 第 1 批就 all_exists → tier1 立刻完成 → tier2 检查 importing 活动 → 完成
不再有"重启后从头扫几百条历史 / tier2 永远不跑"的死锁。

覆盖 2 个场景：
1. all_exists 短路：本批全已存在 → tier1.total_activities = tier1_completed → 完成
2. 部分已存在 + 部分新：created > 0 → 不短路 / 继续 cursor 推进（既有行为不破坏）
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.strava.import_scheduler import _run_tier1
from app.activity.models import Activity
from app.strava.models import StravaImport
from app.user.models import User
from tests.conftest import _test_engine


@pytest.fixture()
def strava_imports_table(db):
    """确保 strava_imports 表在 SQLite 中存在。"""
    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    yield
    StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)


@pytest.fixture()
def strava_user(db):
    """创建一个绑定 Strava 的测试用户。"""
    user = User(
        openid="fix4_hotfix_user",
        is_admin=False,
        strava_athlete_id=77777,
        strava_access_token="at",
        strava_refresh_token="rt",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestTier1AllExistsShortCircuit:
    """tier1 all_exists 短路完成覆盖。"""

    def test_all_exists_triggers_completion(
        self, db, strava_imports_table, strava_user
    ):
        """拉 3 条全已存在 → tier1 短路完成 / total_activities 被设。"""
        import_task = StravaImport(
            user_id=strava_user.id,
            strava_athlete_id=77777,
            status="active",
            total_activities=None,
            tier1_completed=0,
        )
        db.add(import_task)
        db.commit()

        # 预先插入 3 条已存在的 Strava activity（模拟之前导入过）
        for sid in [3001, 3002, 3003]:
            db.add(Activity(
                user_id=strava_user.id,
                status="completed",
                data_source="strava",
                strava_activity_id=sid,
                distance=20000.0,
            ))
        db.commit()

        # mock client 返回这 3 条（全部已存在）
        fake_client = MagicMock()
        fake_client.get_athlete_activities.return_value = [
            {"id": 3001, "name": "Ride 1", "type": "Ride",
             "distance": 20000, "start_date": "2026-05-15T08:00:00Z"},
            {"id": 3002, "name": "Ride 2", "type": "Ride",
             "distance": 25000, "start_date": "2026-05-14T08:00:00Z"},
            {"id": 3003, "name": "Ride 3", "type": "Ride",
             "distance": 30000, "start_date": "2026-05-13T08:00:00Z"},
        ]

        _run_tier1(db, fake_client, import_task)

        db.refresh(import_task)
        # 短路完成：total_activities 被设为 tier1_completed
        assert import_task.total_activities == 0, \
            f"tier1 应短路完成 / total = tier1_completed=0 / 实际 = {import_task.total_activities}"

    def test_mixed_new_and_existing_no_short_circuit(
        self, db, strava_imports_table, strava_user
    ):
        """拉 3 条 / 1 条新 + 2 条已存在 → created=1 / 不短路 / 继续拉。"""
        import_task = StravaImport(
            user_id=strava_user.id,
            strava_athlete_id=77777,
            status="active",
            total_activities=None,
            tier1_completed=0,
        )
        db.add(import_task)
        db.commit()

        # 预先插入 2 条已存在
        for sid in [4001, 4002]:
            db.add(Activity(
                user_id=strava_user.id,
                status="completed",
                data_source="strava",
                strava_activity_id=sid,
                distance=20000.0,
            ))
        db.commit()

        # mock client 返回 3 条 / 1 条新（4003）+ 2 条已存在（4001/4002）
        fake_client = MagicMock()
        fake_client.get_athlete_activities.return_value = [
            {"id": 4003, "name": "New Ride", "type": "Ride",
             "distance": 30000, "start_date": "2026-05-18T08:00:00Z"},
            {"id": 4001, "name": "Old Ride 1", "type": "Ride",
             "distance": 20000, "start_date": "2026-05-15T08:00:00Z"},
            {"id": 4002, "name": "Old Ride 2", "type": "Ride",
             "distance": 25000, "start_date": "2026-05-14T08:00:00Z"},
        ]

        _run_tier1(db, fake_client, import_task)

        db.refresh(import_task)
        # 有新活动 → 不短路 → total_activities 保持 None 等真完成
        assert import_task.total_activities is None, \
            f"有新活动 created>0 / 不应短路 / total 仍 None / 实际 = {import_task.total_activities}"
        # tier1_completed 累加 1（新活动）
        assert import_task.tier1_completed == 1
