"""
task-7.3：handle_callback 防重复绑定 + 换号清理的单测。

覆盖 6 个场景：
1. 首次绑定（happy path）
2. 重复绑定（同 athlete，已有 active 任务 → 复用）
3. paused → active 重新激活
4. 换号（athlete_id 变了 → 清旧 importing 活动）
5. UNIQUE 冲突（该 Strava 账号被他人占用 → BoundByOtherUserError）
6. 顺序验证：UNIQUE 检测在 cleanup 之前（v1 bug 修复回归保护）
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.strava.service import (
    BoundByOtherUserError,
    handle_callback,
)
from app.user.models import User


# ==================== 辅助 fixture ====================


@pytest.fixture()
def redis_mock():
    """一个 MagicMock 版的 Redis 客户端——handle_callback 的 state 消费全 mock。"""
    return MagicMock()


def _make_user(db, strava_athlete_id=None) -> User:
    """手工创建一个 User 记录；openid 随机以避免 UNIQUE 冲突。"""
    import uuid
    user = User(
        openid=f"openid_{uuid.uuid4().hex[:12]}",
        is_admin=False,
        strava_athlete_id=strava_athlete_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _insert_activity(db, user_id, status, data_source="strava", strava_activity_id=None):
    """用 table insert 直接写 activities 记录，避开 ORM 对新字段的依赖。"""
    from tests.conftest import _activities_table
    import uuid
    sid = strava_activity_id if strava_activity_id is not None else uuid.uuid4().int % 10**9
    result = db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            status=status,
            data_source=data_source,
            strava_activity_id=sid,
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def _get_activity_status(db, activity_id):
    """读取单条 activity 的 status 字段。"""
    from tests.conftest import _activities_table
    from sqlalchemy import select
    row = db.execute(
        select(_activities_table.c.status).where(_activities_table.c.id == activity_id)
    ).first()
    return row[0] if row else None


def _mock_strava_token_response(mock_post, athlete_id, access_token="at_xxx",
                                refresh_token="rt_yyy", expires_at=1800000000):
    """配置 httpx.post 的 mock 返回 Strava token 响应。"""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "athlete": {"id": athlete_id},
    }
    mock_post.return_value = resp


# ==================== 测试 ====================


@pytest.fixture()
def strava_imports_table(db):
    """确保 strava_imports 表在 SQLite 中存在。"""
    from app.strava.models import StravaImport
    from tests.conftest import _test_engine
    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    yield
    StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)


class TestHandleCallback:
    """handle_callback 的综合测试。"""

    @patch("app.strava.service.httpx.post")
    def test_first_time_bind(self, mock_post, db, redis_mock, strava_imports_table):
        """首次绑定（happy path）：用户未绑定 → 绑定成功 + 创建 active import 任务。"""
        user = _make_user(db, strava_athlete_id=None)
        redis_mock.getdel.return_value = str(user.id).encode()
        _mock_strava_token_response(mock_post, athlete_id=99001,
                                    access_token="at_xxx", refresh_token="rt_yyy")

        result = handle_callback(db, code="c1", state="nonce1", redis=redis_mock)

        assert result["bound"] is True
        assert result["athlete_id"] == 99001

        db.refresh(user)
        assert user.strava_athlete_id == 99001
        assert user.strava_access_token == "at_xxx"

        # 验证新建了 active StravaImport
        from app.strava.models import StravaImport
        imp = db.query(StravaImport).filter_by(user_id=user.id).first()
        assert imp is not None
        assert imp.status == "active"
        assert imp.strava_athlete_id == 99001

    @patch("app.strava.service.httpx.post")
    def test_rebind_reuses_active_task(self, mock_post, db, redis_mock, strava_imports_table):
        """重复绑定：已有 active 任务 → 复用，不新建。"""
        user = _make_user(db, strava_athlete_id=99001)
        from app.strava.models import StravaImport
        existing = StravaImport(
            user_id=user.id, strava_athlete_id=99001, status="active"
        )
        db.add(existing)
        db.commit()
        initial_import_id = existing.id

        redis_mock.getdel.return_value = str(user.id).encode()
        _mock_strava_token_response(mock_post, athlete_id=99001,
                                    access_token="at_new", refresh_token="rt_new")

        handle_callback(db, code="c2", state="nonce2", redis=redis_mock)

        # 应复用已有 import，不新建
        imports = db.query(StravaImport).filter_by(user_id=user.id).all()
        assert len(imports) == 1
        assert imports[0].id == initial_import_id
        assert imports[0].status == "active"

    @patch("app.strava.service.httpx.post")
    def test_rebind_reactivates_paused(self, mock_post, db, redis_mock, strava_imports_table):
        """paused → active：若上次导入因 token 失效被 paused，重新 callback 应自动激活。"""
        user = _make_user(db, strava_athlete_id=99001)
        from app.strava.models import StravaImport
        db.add(StravaImport(
            user_id=user.id, strava_athlete_id=99001, status="paused"
        ))
        db.commit()

        redis_mock.getdel.return_value = str(user.id).encode()
        _mock_strava_token_response(mock_post, athlete_id=99001)

        handle_callback(db, code="c3", state="n3", redis=redis_mock)

        imp = db.query(StravaImport).filter_by(user_id=user.id).first()
        assert imp.status == "active"  # paused → active

    @patch("app.strava.service.httpx.post")
    def test_switch_athlete_cleans_old(self, mock_post, db, redis_mock, strava_imports_table):
        """换号：athlete_id 变了 → 清理旧 athlete 的 importing 活动（completed 不动）。"""
        user = _make_user(db, strava_athlete_id=99001)

        # 老账号的 importing 活动
        old_act_id = _insert_activity(
            db, user_id=user.id, status="importing", data_source="strava"
        )
        # 已完成的活动（不应被动）
        done_act_id = _insert_activity(
            db, user_id=user.id, status="completed", data_source="strava"
        )

        redis_mock.getdel.return_value = str(user.id).encode()
        _mock_strava_token_response(mock_post, athlete_id=99002)  # 新 athlete

        handle_callback(db, code="c4", state="n4", redis=redis_mock)

        assert _get_activity_status(db, old_act_id) == "failed"       # 被清理
        assert _get_activity_status(db, done_act_id) == "completed"   # 不动

    @patch("app.strava.service.httpx.post")
    def test_athlete_owned_by_other_user_rejects(self, mock_post, db, redis_mock,
                                                  strava_imports_table):
        """UNIQUE 冲突：目标 athlete 已被他人绑定 → BoundByOtherUserError，受害者 token 不被写。"""
        attacker = _make_user(db, strava_athlete_id=99001)
        victim = _make_user(db, strava_athlete_id=None)

        redis_mock.getdel.return_value = str(victim.id).encode()
        _mock_strava_token_response(mock_post, athlete_id=99001)  # 想绑已占用的 99001

        with pytest.raises(BoundByOtherUserError):
            handle_callback(db, code="c5", state="n5", redis=redis_mock)

        # 受害者 token 不应被写入
        db.refresh(victim)
        assert victim.strava_athlete_id is None
        assert victim.strava_access_token is None

    @patch("app.strava.service.httpx.post")
    def test_unique_check_before_cleanup(self, mock_post, db, redis_mock,
                                          strava_imports_table):
        """
        顺序验证：UNIQUE 检测必须先于 cleanup。

        场景：user 已绑定 athlete=99001，想改绑 athlete=99002，但 99002 被占用。
        期望：抛 BoundByOtherUserError 且 user 的 importing 活动**不被清理**。
        """
        attacker = _make_user(db, strava_athlete_id=99002)
        user = _make_user(db, strava_athlete_id=99001)

        # user 自己的 importing 活动
        old_act_id = _insert_activity(
            db, user_id=user.id, status="importing", data_source="strava"
        )

        redis_mock.getdel.return_value = str(user.id).encode()
        _mock_strava_token_response(mock_post, athlete_id=99002)  # 想绑已占用的 99002

        with pytest.raises(BoundByOtherUserError):
            handle_callback(db, code="c6", state="n6", redis=redis_mock)

        # 关键断言：importing 活动没被错误清理（v1 bug 修复回归保护）
        assert _get_activity_status(db, old_act_id) == "importing"
