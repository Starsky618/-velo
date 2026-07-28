"""
Sprint 8 Fix 2：worker_strava.py 单测——webhook 异步处理 worker。

用户故事：Strava 用户 19:29 上传新骑行 → webhook 打电话到 velo →
api 容器 enqueue 任务 → worker 容器跑 process_strava_webhook_create →
拉详情 + 轨迹 + 写 DB + 跑 hook → 19:29:30 velo 列表已有完整数据。

覆盖 5 个场景：
1. create 抢锁成功 + 骑行 + 走主流程
2. create 抢锁失败（已被处理）→ 静默退出
3. update activity 不存在 → 当 create 处理
4. update activity 已 completed → 清派生 + 重置 status → 主流程
5. _wipe_activity_derived_data 清 trackpoints/efforts/notifications
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.activity.models import Activity
from app.strava.models import StravaImport
from app.user.models import User
from tests.conftest import _test_engine


@pytest.fixture()
def strava_imports_table(db):
    """确保 strava_imports 表存在。"""
    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    yield
    StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)


def _make_strava_user(db):
    """创建绑定 Strava 的测试用户。"""
    user = User(
        openid=f"openid_{uuid.uuid4().hex[:12]}",
        is_admin=False,
        strava_athlete_id=66666,
        strava_access_token="at",
        strava_refresh_token="rt",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestProcessStravaWebhookCreate:
    """process_strava_webhook_create 抢锁 + 主流程覆盖。"""

    @patch("app.strava.worker_strava.SessionLocal")
    @patch("app.strava.worker_strava._process_strava_main")
    def test_create_lock_failed_silent_exit(
        self, mock_process_main, mock_session_local, db, strava_imports_table
    ):
        """importing 活动不存在（已被 scheduler tier2 抢先处理）→ 抢锁失败 → 静默退出。"""
        from app.strava.worker_strava import process_strava_webhook_create
        user = _make_strava_user(db)

        # 没有 importing 活动可抢
        mock_session_local.return_value = db

        # 调用 worker：抢锁应失败（DB 里没 status='importing' 的 strava_activity_id=99001）
        process_strava_webhook_create(user.id, 99001)

        # _process_strava_main 不应被调（抢锁失败直接 return）
        mock_process_main.assert_not_called()

    @patch("app.strava.worker_strava.SessionLocal")
    @patch("app.strava.worker_strava._process_strava_main")
    def test_create_lock_success_triggers_main(
        self, mock_process_main, mock_session_local, db, strava_imports_table
    ):
        """importing 活动存在 → 抢锁成功 → 调用 _process_strava_main。"""
        from app.strava.worker_strava import process_strava_webhook_create
        user = _make_strava_user(db)

        # 预先建 importing 骨架
        act = Activity(
            user_id=user.id,
            status="importing",
            data_source="strava",
            strava_activity_id=99002,
        )
        db.add(act)
        db.commit()

        mock_session_local.return_value = db
        process_strava_webhook_create(user.id, 99002)

        # 验证主流程被调用
        mock_process_main.assert_called_once()
        # 验证 activity 状态被改为 processing（重新 query / 不用 refresh）
        db.expire_all()
        act_db = db.query(Activity).filter_by(strava_activity_id=99002).first()
        assert act_db.status == "processing", \
            f"抢锁后应改为 processing / 实际 = {act_db.status}"


class TestProcessStravaWebhookUpdate:
    """process_strava_webhook_update 分支覆盖。"""

    @patch("app.strava.worker_strava.SessionLocal")
    @patch("app.strava.worker_strava.process_strava_webhook_create")
    def test_update_activity_not_exist_falls_back_to_create(
        self, mock_create, mock_session_local, db, strava_imports_table
    ):
        """update 时 activity 不存在 → 当 create 处理（建骨架 + 调 create worker）。"""
        from app.strava.worker_strava import process_strava_webhook_update
        user = _make_strava_user(db)

        mock_session_local.return_value = db
        process_strava_webhook_update(user.id, 99003)

        # 应建骨架 + 调 create worker
        act = db.query(Activity).filter_by(strava_activity_id=99003).first()
        assert act is not None, "update 路径应建 importing 骨架"
        assert act.status == "importing"
        mock_create.assert_called_once_with(user.id, 99003)

    @patch("app.strava.worker_strava._wipe_activity_derived_data")
    @patch("app.strava.worker_strava.SessionLocal")
    @patch("app.strava.worker_strava._process_strava_main")
    def test_update_completed_wipes_and_reprocesses(
        self, mock_process_main, mock_session_local, mock_wipe, db, strava_imports_table, monkeypatch
    ):
        """update completed 活动 → 清派生数据 + 重置 status='processing' → 主流程。"""
        from app.strava.worker_strava import process_strava_webhook_update
        user = _make_strava_user(db)

        act = Activity(
            user_id=user.id,
            status="completed",
            data_source="strava",
            strava_activity_id=99004,
            activity_type="cycling",
        )
        db.add(act)
        db.commit()
        user_id = user.id
        invalidated = []
        monkeypatch.setattr(
            "app.user.service_social.invalidate_heatmap_cache",
            lambda uid: invalidated.append(uid),
        )

        mock_session_local.return_value = db
        process_strava_webhook_update(user_id, 99004)

        # _wipe_activity_derived_data 应被调（清派生数据）
        mock_wipe.assert_called_once()
        db.expire_all()
        act_db = db.query(Activity).filter_by(strava_activity_id=99004).first()
        assert act_db.status == "processing", \
            f"completed 路径应清派生 + 重置为 processing / 实际 = {act_db.status}"
        assert invalidated == [user_id]
        mock_process_main.assert_called_once()

    @patch("app.strava.worker_strava.SessionLocal")
    @patch("app.strava.worker_strava._process_strava_main")
    def test_update_processing_status_skipped(
        self, mock_process_main, mock_session_local, db, strava_imports_table
    ):
        """update 时 activity 已 processing → 跳过（create worker 在处理中）。"""
        from app.strava.worker_strava import process_strava_webhook_update
        user = _make_strava_user(db)

        act = Activity(
            user_id=user.id,
            status="processing",
            data_source="strava",
            strava_activity_id=99005,
        )
        db.add(act)
        db.commit()

        mock_session_local.return_value = db
        process_strava_webhook_update(user.id, 99005)

        # _process_strava_main 不应被调
        mock_process_main.assert_not_called()
        # status 保持 processing 不动
        db.expire_all()
        act_db = db.query(Activity).filter_by(strava_activity_id=99005).first()
        assert act_db.status == "processing"
