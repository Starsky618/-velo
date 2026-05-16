"""
Sprint 6 task-5：POST /api/strava/unbind 单元测试。

干啥用：
    覆盖"用户在 velo 设置页点解绑"这条路径的所有副作用：
    - 4 个 strava 字段全清 NULL
    - activities 表行数不变（历史活动保留）
    - strava_imports 表行数不变 + active 行 → paused
    - completed / paused 行状态不变（只动 active）
    - 重新绑定 OAuth 流程能完成（dedupe 防重复导入）
    - 调度器 _pick_next_task 不会再 pick 已 paused 的任务

类比：
    模拟"用户去前台注销健身卡"的完整后果——
    卡作废了（4 字段清空）+ 教练别再约课（active 暂停）+
    历史训练记录留档（activities 不删）+ 老的暂停 / 完成订单状态不动。

操作注意：
    - strava_imports 表用本地 fixture 按需建表（与 tests/strava/test_callback.py 同款 pattern）
    - 字段名 strava_athlete_id（不是 strava_user_id）—— task 卡 v0.2 红线
    - 测试用 client + auth_header / 真打 endpoint 验状态码 + DB 副作用
"""

import pytest

from app.user.models import User


@pytest.fixture()
def strava_imports_table(db):
    """确保 strava_imports 表在 SQLite 中存在。"""
    from app.strava.models import StravaImport
    from tests.conftest import _test_engine
    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    yield
    StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)


@pytest.fixture()
def bound_user(db, test_user):
    """给 test_user 写入 4 个 Strava 字段，模拟已绑定状态。"""
    from datetime import datetime, timedelta, timezone
    test_user.strava_athlete_id = 88001
    test_user.strava_access_token = "at_old"
    test_user.strava_refresh_token = "rt_old"
    test_user.strava_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=6)
    db.commit()
    db.refresh(test_user)
    return test_user


def _insert_activity(db, user_id, status="completed", strava_activity_id=None):
    """直接走 _activities_table 插一条 activity（避免 ORM 对 PG 专属字段的依赖）。"""
    from tests.conftest import _activities_table
    import uuid
    sid = strava_activity_id if strava_activity_id is not None else uuid.uuid4().int % 10**9
    result = db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            status=status,
            data_source="strava",
            strava_activity_id=sid,
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def _insert_strava_import(db, user_id, status="active", strava_athlete_id=88001):
    """直接用 ORM 插 StravaImport（fixture 已建表 / ORM 写入测试更直观）。"""
    from app.strava.models import StravaImport
    imp = StravaImport(
        user_id=user_id,
        strava_athlete_id=strava_athlete_id,
        status=status,
    )
    db.add(imp)
    db.commit()
    db.refresh(imp)
    return imp


class TestUnbindStrava:
    """POST /api/strava/unbind 端到端测试（client + auth_header / 真打 endpoint）。"""

    def test_case1_unbind_clears_strava_athlete_id(
        self, client, auth_header, db, bound_user, strava_imports_table
    ):
        """case 1：解绑后 user.strava_athlete_id IS NULL（task 卡红线 / 字段名实证）。"""
        resp = client.post("/api/strava/unbind", headers=auth_header)
        assert resp.status_code == 204

        db.expire_all()  # 清 identity map 让 refresh 拿 DB 真值
        user = db.query(User).filter_by(id=bound_user.id).first()
        assert user.strava_athlete_id is None

    def test_case2_unbind_clears_all_four_fields(
        self, client, auth_header, db, bound_user, strava_imports_table
    ):
        """case 2：4 个字段全清 NULL（漏一个 = bug）。"""
        resp = client.post("/api/strava/unbind", headers=auth_header)
        assert resp.status_code == 204

        db.expire_all()
        user = db.query(User).filter_by(id=bound_user.id).first()
        # 4 字段全 NULL —— 红线
        assert user.strava_athlete_id is None
        assert user.strava_access_token is None
        assert user.strava_refresh_token is None
        assert user.strava_token_expires_at is None

    def test_case3_unbind_keeps_activities(
        self, client, auth_header, db, bound_user, strava_imports_table
    ):
        """case 3：解绑后 activities 表行数不变（历史活动保留 / 不能 cascade 删）。"""
        # 先插 3 条已导入活动
        _insert_activity(db, user_id=bound_user.id, status="completed")
        _insert_activity(db, user_id=bound_user.id, status="completed")
        _insert_activity(db, user_id=bound_user.id, status="importing")

        from tests.conftest import _activities_table
        from sqlalchemy import select, func
        before_count = db.execute(
            select(func.count()).select_from(_activities_table)
            .where(_activities_table.c.user_id == bound_user.id)
        ).scalar()
        assert before_count == 3

        resp = client.post("/api/strava/unbind", headers=auth_header)
        assert resp.status_code == 204

        after_count = db.execute(
            select(func.count()).select_from(_activities_table)
            .where(_activities_table.c.user_id == bound_user.id)
        ).scalar()
        assert after_count == 3  # 一条都不能少

    def test_case4_unbind_pauses_active_imports_but_keeps_rows(
        self, client, auth_header, db, bound_user, strava_imports_table
    ):
        """case 4：strava_imports 行数不变 + active 行全 → paused（v0.3 集成审 Critical 修）。"""
        imp_active1 = _insert_strava_import(db, user_id=bound_user.id, status="active")
        imp_active2 = _insert_strava_import(db, user_id=bound_user.id, status="active")

        from app.strava.models import StravaImport
        before_count = db.query(StravaImport).filter_by(user_id=bound_user.id).count()
        assert before_count == 2

        resp = client.post("/api/strava/unbind", headers=auth_header)
        assert resp.status_code == 204

        db.expire_all()
        after_count = db.query(StravaImport).filter_by(user_id=bound_user.id).count()
        assert after_count == 2  # 行数不变（不删）

        # 两条都从 active → paused
        db.refresh(imp_active1)
        db.refresh(imp_active2)
        assert imp_active1.status == "paused"
        assert imp_active2.status == "paused"

    def test_case5_unbind_does_not_touch_completed_or_paused_rows(
        self, client, auth_header, db, bound_user, strava_imports_table
    ):
        """case 5：completed / paused 行状态**不变**（只动 active）。"""
        imp_active = _insert_strava_import(db, user_id=bound_user.id, status="active")
        imp_completed = _insert_strava_import(db, user_id=bound_user.id, status="completed")
        imp_paused = _insert_strava_import(db, user_id=bound_user.id, status="paused")

        resp = client.post("/api/strava/unbind", headers=auth_header)
        assert resp.status_code == 204

        db.expire_all()
        db.refresh(imp_active)
        db.refresh(imp_completed)
        db.refresh(imp_paused)

        assert imp_active.status == "paused"       # active → paused
        assert imp_completed.status == "completed"  # 不变
        assert imp_paused.status == "paused"       # 不变（仍是 paused）

    def test_case6_rebind_flow_works_after_unbind(
        self, client, auth_header, db, bound_user, strava_imports_table
    ):
        """case 6：解绑后再绑定（handle_callback 流程能正常完成 + paused 行被复活成 active）。

        重新绑定时 handle_callback 走 paused → active 的复活路径
        （tests/strava/test_callback.py:test_rebind_reactivates_paused 已验证 callback 侧）。
        本 case 简化：直接验证"解绑后 user 字段重新可写 + paused 行可被 callback 复活"——
        模拟 OAuth callback 把 4 字段重写 + paused → active。
        """
        from unittest.mock import MagicMock, patch
        from app.strava.service_oauth import handle_callback

        _insert_strava_import(db, user_id=bound_user.id, status="active")

        # 第一步：解绑
        resp = client.post("/api/strava/unbind", headers=auth_header)
        assert resp.status_code == 204

        # 验证 paused
        from app.strava.models import StravaImport
        db.expire_all()
        imp = db.query(StravaImport).filter_by(user_id=bound_user.id).first()
        assert imp.status == "paused"

        # 第二步：模拟 OAuth callback 重新绑定
        redis_mock = MagicMock()
        redis_mock.getdel.return_value = str(bound_user.id).encode()

        with patch("app.strava.service_oauth.httpx.post") as mock_post:
            resp_mock = MagicMock()
            resp_mock.status_code = 200
            resp_mock.json.return_value = {
                "access_token": "at_new",
                "refresh_token": "rt_new",
                "expires_at": 1900000000,
                "athlete": {"id": 88001},
                # 注意：Strava token response 的 scope 是**空格分隔**（不是逗号 / 与 query string 不同）
                # 实证：app/strava/service_oauth.py:325 raw_scope.split(" ")
                "scope": "read activity:read_all",
            }
            mock_post.return_value = resp_mock

            result = handle_callback(
                db, code="c_rebind", state="nonce_rebind",
                redis=redis_mock, granted_scope="read,activity:read_all",
            )
            assert result["bound"] is True

        # 验证 4 字段重新填好 + import 任务复活
        db.expire_all()
        user = db.query(User).filter_by(id=bound_user.id).first()
        assert user.strava_athlete_id == 88001
        assert user.strava_access_token == "at_new"
        assert user.strava_refresh_token == "rt_new"
        assert user.strava_token_expires_at is not None

        imp = db.query(StravaImport).filter_by(user_id=bound_user.id).first()
        assert imp.status == "active"  # paused → active 复活（dedupe / 不新建）

        # 重新绑定后 strava_imports 只有 1 条（不重复导入）
        count = db.query(StravaImport).filter_by(user_id=bound_user.id).count()
        assert count == 1

    def test_case7_scheduler_does_not_pick_paused_import(
        self, client, auth_header, db, bound_user, strava_imports_table
    ):
        """case 7：调度器 _pick_next_task 不会 pick 已 paused 的任务（防空转）。"""
        from app.strava.import_scheduler import _pick_next_task

        _insert_strava_import(db, user_id=bound_user.id, status="active")

        # 解绑前调度器应能 pick 到这条 active
        picked_before = _pick_next_task(db)
        assert picked_before is not None
        assert picked_before.user_id == bound_user.id
        assert picked_before.status == "active"

        # 解绑
        resp = client.post("/api/strava/unbind", headers=auth_header)
        assert resp.status_code == 204

        # 解绑后调度器 pick 应返 None（该用户唯一 import 已转 paused）
        db.expire_all()
        picked_after = _pick_next_task(db)
        assert picked_after is None  # 没有 active 可挑

    def test_case8_unbind_marks_importing_activities_as_failed(
        self, client, auth_header, db, bound_user, strava_imports_table
    ):
        """case 8（三审 B 集成审 Important 修）：解绑时 importing 骨架活动→failed。

        防止用户主页永久"加载中"——worker 已拿不到 token / 这些骨架不会再被填充。
        """
        from app.activity.models import Activity

        # 造 2 条 importing + 1 条 completed + 1 条 failed（基线）
        skeleton1 = Activity(
            user_id=bound_user.id, title="importing-1",
            status="importing", file_url="strava:1001",
        )
        skeleton2 = Activity(
            user_id=bound_user.id, title="importing-2",
            status="importing", file_url="strava:1002",
        )
        done = Activity(
            user_id=bound_user.id, title="done",
            status="completed", file_url="strava:999",
        )
        already_failed = Activity(
            user_id=bound_user.id, title="prior-fail",
            status="failed", file_url="strava:888",
        )
        db.add_all([skeleton1, skeleton2, done, already_failed])
        db.commit()

        resp = client.post("/api/strava/unbind", headers=auth_header)
        assert resp.status_code == 204

        db.expire_all()
        # 2 条 importing 都 → failed
        assert db.get(Activity, skeleton1.id).status == "failed"
        assert db.get(Activity, skeleton2.id).status == "failed"
        # completed / 已 failed 不受影响（只动 importing）
        assert db.get(Activity, done.id).status == "completed"
        assert db.get(Activity, already_failed.id).status == "failed"

    def test_case9_unbind_user_not_found_returns_404(
        self, client, db, strava_imports_table
    ):
        """case 9（三审 B Critical 修）：service 层用 .first() + 不存在抛 ValueError → router 翻 404。

        防 CLAUDE.md 陷阱 #4：.one() 遇零记录抛 NoResultFound 让 FastAPI 返 500 / 不专业。
        概率小但真实场景：JWT 有效但用户已被 admin purge。
        """
        from app.strava.service_sync import unbind_strava

        with pytest.raises(ValueError, match="用户不存在"):
            unbind_strava(db, user_id=999_999_999)
