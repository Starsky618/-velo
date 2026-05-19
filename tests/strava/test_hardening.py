"""
task-7.6：Strava 现有函数加固（I7 / I8 / I9 / I10）的单测。

覆盖 4 个 Important 修复：
- I7：ensure_valid_token 401 分支 → pause 该用户 active 导入任务
- I8：ensure_valid_token 入口加 SELECT FOR UPDATE 行锁（回归保障）
- I9：_run_tier1 连续 2 次空才判完成（防 Strava 偶发空返回）
- I10：handle_manual_sync 循环后同步更新 tier1_completed
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import uuid

import pytest

from app.strava import service
from app.strava.exceptions import UnboundStravaError
from app.strava.import_scheduler import _run_tier1
from app.strava.models import StravaImport
from app.user.models import User


# ==================== 辅助 fixture ====================


@pytest.fixture()
def strava_imports_table(db):
    """确保 strava_imports 表在 SQLite 中存在。"""
    from tests.conftest import _test_engine
    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    yield
    StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)


@pytest.fixture()
def redis_mock():
    """MagicMock 版 Redis 客户端——用于 I9 / I10 测试中的 redis 行为断言。

    ⚠️ 陷阱提示：MagicMock 默认 return_value 是 MagicMock 对象，与真实 redis-py
    返回值类型（int / bytes / None）不一致。使用前**必须显式 set 各方法的
    return_value**——例：`redis_mock.incr.return_value = 1`、
    `redis_mock.set.return_value = True`。否则被测代码 `int(r.incr(...))` 等会
    因 `int(MagicMock)` 抛 TypeError。
    """
    return MagicMock()


def _make_user(db, strava_athlete_id=99001, access_token="at",
               refresh_token="rt", expires_at=None):
    """手工创建 User；openid 随机避免 UNIQUE 冲突。"""
    user = User(
        openid=f"openid_{uuid.uuid4().hex[:12]}",
        is_admin=False,
        strava_athlete_id=strava_athlete_id,
        strava_access_token=access_token,
        strava_refresh_token=refresh_token,
        strava_token_expires_at=expires_at,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ==================== I7：401 → pause imports ====================


@patch("app.strava.service_token.httpx.post")
def test_token_refresh_401_pauses_active_imports(
    mock_post, db, strava_imports_table
):
    """401 分支应把该用户 active 导入任务置 paused。"""
    user = _make_user(
        db,
        strava_athlete_id=99001,
        access_token="old_at",
        refresh_token="old_rt",
        expires_at=None,  # None 时走刷新分支（绕开 SQLite naive-vs-aware 比较）
    )
    db.add(StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
    ))
    db.commit()

    # mock Strava 返回 401
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_post.return_value = mock_resp

    with pytest.raises(ValueError):
        # force=True 绕过 expires_at 检查，直接进入刷新→401 分支
        # v5 task-0.2：传 user_id（不再传 user 对象）
        service.ensure_valid_token(db, user.id, force=True)

    # 验证 import 被置 paused
    imp = db.query(StravaImport).filter_by(user_id=user.id).first()
    assert imp.status == "paused"

    # 验证 user 的 strava 字段被清空（行锁版 user 在函数内更新了 DB）
    db.refresh(user)
    assert user.strava_athlete_id is None
    assert user.strava_access_token is None


# ==================== I8：refresh 行锁（回归保障） ====================


def test_ensure_valid_token_uses_row_lock(db, strava_imports_table):
    """入口行锁回归：用 mock Query spy 直接验证 `with_for_update()` 被调用过。

    之前的版本只验证"用户不存在 → ValueError"路径，被代码审查指为假通过——
    那条路径即使去掉 `.with_for_update()` 也通过，无法证明行锁调用存在。
    v4 加强：mock db.query().filter().with_for_update()，断言该链条被调用。
    SQLite 本身不支持行锁，真正并发行为由生产 PostgreSQL 保证，本地只验证
    SQL 构造链条存在（缺一环就失效）。
    """
    from unittest.mock import MagicMock

    # 构造 mock session，精确断言 with_for_update + populate_existing 都被调用
    mock_db = MagicMock()
    # query() → filter() → with_for_update() → populate_existing() → first() 链
    mock_filter = MagicMock()
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_filter
    mock_lock_result = MagicMock()
    mock_filter.with_for_update.return_value = mock_lock_result
    # v5 task-0.2 fix：链里多了 populate_existing（codex 异源审抓的 Important）
    mock_populated = MagicMock()
    mock_lock_result.populate_existing.return_value = mock_populated
    mock_populated.first.return_value = None  # 模拟查不到用户
    mock_db.query.return_value = mock_query

    # v5 task-0.2：传 user_id（int）替代 user 对象；错误消息含 user_id
    with pytest.raises(ValueError, match=r"user_id=9999"):
        service.ensure_valid_token(mock_db, 9999)

    # 核心断言：with_for_update() + populate_existing() 都被调用过——
    # 缺任何一环，task-0.2 "返回锁后最新 user" 的契约就失效
    mock_filter.with_for_update.assert_called_once()
    mock_lock_result.populate_existing.assert_called_once()
    mock_populated.first.assert_called_once()


# ==================== v5 task-0.2：返回 (User, token) 元组 ====================


@patch("app.strava.service_token.httpx.post")
def test_ensure_valid_token_returns_locked_user_instance(
    mock_post, db, strava_imports_table
):
    """v5 task-0.2：成功刷新后返回 (User, token)，user 实例字段已被新 token 写回。

    验证两点：
    1. 返回值是 (User, str) 元组（不是单 str）
    2. 返回的 user 实例已带新 access_token（不是缓存的旧值）
    """
    user = _make_user(
        db,
        strava_athlete_id=99001,
        access_token="old_at",
        refresh_token="old_rt",
        expires_at=None,  # None → 走刷新分支（绕开 SQLite naive vs aware 比较）
    )

    # mock Strava 返回新 token
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "new_at",
        "refresh_token": "new_rt",
        "expires_at": int(
            (datetime.now(timezone.utc) + timedelta(hours=6)).timestamp()
        ),
    }
    mock_post.return_value = mock_resp

    # 调用——传 user_id，不传 user 对象
    result = service.ensure_valid_token(db, user.id, force=True)

    # 断言 1：返回元组
    assert isinstance(result, tuple) and len(result) == 2
    locked_user, token = result

    # 断言 2：返回的 user 是 User 实例 + 字段已刷新
    assert isinstance(locked_user, User)
    assert locked_user.id == user.id
    assert locked_user.strava_access_token == "new_at"
    assert token == "new_at"


def test_ensure_valid_token_not_expired_returns_tuple():
    """v5 task-0.2：未过期分支也返回 (User, token) 元组——堵单值回归。

    若未来有人误把"未过期早 return"路径改回 `return token`（单值），
    本测试立即失败；否则只能依赖集成测在解构时炸 unpack error，定位慢。

    用 mock session 而非真实 SQLite——SQLite 反序列化 aware datetime 会丢
    时区，触发 task-0.1 修过的 naive vs aware 比较错（测试环境边角，
    与 task-0.2 改造无关）。Mock 让 expires_at 比较两边都是纯 Python aware。
    """
    fake_user = User(
        id=42,
        openid="mock",
        strava_access_token="still_valid",
        strava_refresh_token="rt",
        strava_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )

    mock_db = MagicMock()
    # v5 task-0.2 fix：链里多一环 populate_existing（codex 异源审抓的 Important）
    (
        mock_db.query.return_value
        .filter.return_value
        .with_for_update.return_value
        .populate_existing.return_value
        .first.return_value
    ) = fake_user

    result = service.ensure_valid_token(mock_db, 42)

    # 关键断言：早 return 分支也返回元组（不是单 str）
    assert isinstance(result, tuple) and len(result) == 2
    locked_user, token = result
    assert locked_user is fake_user
    assert token == "still_valid"


# ==================== v5 task-0.3：未绑定路径明确化 ====================


def test_ensure_valid_token_unbound_raises_unbound_error(db, strava_imports_table):
    """未绑定 Strava（refresh_token IS NULL）→ 抛 UnboundStravaError。

    避免函数继续走到 refresh API 误报"NULL refresh_token"等底层错误。
    深度防御：即使 caller（如 handle_manual_sync）已用 strava_athlete_id
    拦截了一道，本函数也要自完备校验。
    """
    user = _make_user(
        db,
        strava_athlete_id=None,
        access_token=None,
        refresh_token=None,  # 关键：未绑定
        expires_at=None,
    )

    with pytest.raises(UnboundStravaError, match=r"user_id=\d+ 未绑定 Strava"):
        service.ensure_valid_token(db, user.id)


def test_router_sync_translates_unbound_error_to_400(monkeypatch):
    """router /sync 应把 UnboundStravaError 翻译成 400 + 友好 detail。

    用 monkeypatch 直接让 service.handle_manual_sync 抛 UnboundStravaError，
    验证 router 层的 except 翻译路径——不依赖真实 user / refresh_token 状态，
    单测 router 行为本身。
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.strava import router as strava_router
    from app.dependencies import get_current_user

    # 让 handle_manual_sync 直接抛 UnboundStravaError
    def fake_handle(db, user_id):
        raise UnboundStravaError(f"user_id={user_id} 未绑定 Strava")

    monkeypatch.setattr(strava_router.service, "handle_manual_sync", fake_handle)

    # 绕过 JWT：直接 override get_current_user 依赖
    app.dependency_overrides[get_current_user] = lambda: 1
    try:
        client = TestClient(app)
        resp = client.post("/api/strava/sync")

        assert resp.status_code == 400
        # 关键断言：翻译为友好 detail，而非透传底层错误
        detail = resp.json()["detail"]
        assert "未绑定" in detail
        assert "设置页" in detail
        # 堵"懒人 caller 把 e.args[0] 透传"的回归——detail 不含内部 user_id
        assert "user_id=" not in detail
    finally:
        app.dependency_overrides.clear()


def test_scheduler_pauses_import_on_unbound_error(
    db, strava_imports_table, redis_mock
):
    """v5 task-0.3 兜底：scheduler 遇 UnboundStravaError 应把 import 置 paused。

    场景：DB 出现不一致行（athlete_id 在 + refresh_token NULL，非常态但可能
    因运维手工介入），_run_tier1/_run_tier2 内部触发 ensure_valid_token 抛
    UnboundStravaError——scheduler 必须 catch 后 paused，避免反复捞同一条
    卡住其他用户的导入轮转。
    """
    from unittest.mock import patch
    from app.strava import import_scheduler

    user = _make_user(
        db,
        strava_athlete_id=99001,  # athlete_id 在
        access_token="stale",
        refresh_token=None,  # 但 refresh_token NULL（不一致行）
        expires_at=None,
    )
    imp = StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
    )
    db.add(imp)
    db.commit()

    # mock StravaClient 让 _run_tier1 抛 UnboundStravaError
    with patch("app.strava.import_scheduler.StravaClient") as MockClient:
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        mock_instance.get_athlete_activities.side_effect = UnboundStravaError(
            f"user_id={user.id} 未绑定 Strava"
        )

        import_scheduler._do_tick(db)

    # 关键断言：import 被标 paused（不会被反复捞）
    db.refresh(imp)
    assert imp.status == "paused"


# ==================== I9：tier1 连续 2 次空 ====================


def test_tier1_empty_once_not_completed(db, strava_imports_table, redis_mock):
    """第 1 次空返回：不判完成，保持 active。"""
    user = _make_user(db, strava_athlete_id=99001)
    imp = StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
        total_activities=None, tier1_completed=30,
    )
    db.add(imp)
    db.commit()

    client = MagicMock()
    client.get_athlete_activities.return_value = []  # 空

    redis_mock.incr.return_value = 1  # 第 1 次

    # v5 task-0.8：被测代码改用 `from app.queue import redis_conn as r`，
    # 不再走 redis.Redis.from_url——patch target 改为模块级单例
    with patch("app.queue.redis_conn", redis_mock):
        _run_tier1(db, client, imp)

    # 不应判完成——函数在 empty_count<2 分支直接 return，未碰 total_activities
    # 注意：conftest 用 autoflush=False，不能 db.refresh（会丢掉 Python 端修改），
    # 这里直接断言内存里的对象属性
    assert imp.total_activities is None  # 没被设定
    assert imp.status == "active"  # 保持


def test_tier1_empty_twice_completes(db, strava_imports_table, redis_mock):
    """第 2 次空返回：判完成。"""
    user = _make_user(db, strava_athlete_id=99001)
    imp = StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
        total_activities=None, tier1_completed=30,
    )
    db.add(imp)
    db.commit()

    client = MagicMock()
    client.get_athlete_activities.return_value = []

    redis_mock.incr.return_value = 2  # 第 2 次达到阈值

    # v5 task-0.8：patch app.queue 模块级单例（同上）
    with patch("app.queue.redis_conn", redis_mock):
        _run_tier1(db, client, imp)

    # 函数内设置了 total_activities = tier1_completed（未 commit）
    # conftest autoflush=False，不能 refresh，直接读 Python 属性
    assert imp.total_activities == 30  # 设定为 tier1_completed


def test_tier1_non_empty_resets_counter(db, strava_imports_table, redis_mock):
    """非空拉取 → 清 Redis 计数器。"""
    user = _make_user(db, strava_athlete_id=99001)
    imp = StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
    )
    db.add(imp)
    db.commit()

    client = MagicMock()
    client.get_athlete_activities.return_value = [
        {
            "id": 100,
            "name": "Ride 1",
            "type": "Ride",  # Sprint 7 Fix 3：tier1 _is_cycling 守卫要求
            "distance": 15000,
            "start_date": "2026-04-01T08:00:00Z",
        },
    ]

    # v5 task-0.8：patch app.queue 模块级单例（同上）
    with patch("app.queue.redis_conn", redis_mock):
        _run_tier1(db, client, imp)

    # 应调用 delete 清 empty_key
    delete_calls = [c for c in redis_mock.method_calls if c[0] == "delete"]
    assert any(
        f"strava:tier1_empty:{imp.id}" in str(c) for c in delete_calls
    ), f"delete 未被正确调用: {redis_mock.method_calls}"


# ==================== I10：manual_sync 联动 tier1_completed ====================


# v5 task-0.8：handle_manual_sync 内 `from app.queue import redis_conn`
# 局部 import——patch 模块级单例 app.queue.redis_conn 即可拦截
@patch("app.queue.redis_conn")
@patch("app.strava.client.StravaClient")
def test_manual_sync_updates_tier1_completed(
    MockClient, MockRedisConn, db, strava_imports_table
):
    """手动同步新增活动后，active StravaImport.tier1_completed 应累加。"""
    user = _make_user(db, strava_athlete_id=99001)
    imp = StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
        total_activities=None, tier1_completed=5,
    )
    db.add(imp)
    db.commit()

    # 冷却 Redis：set NX 返回 True 放行
    MockRedisConn.set.return_value = True

    client_instance = MockClient.return_value
    client_instance.get_athlete_activities.return_value = [
        {
            "id": 201, "name": "Ride", "type": "Ride",  # Sprint 7 Fix 6 _is_cycling 守卫要求
            "distance": 20000, "start_date": "2026-04-02T08:00:00Z",
        },
        {
            "id": 202, "name": "Ride 2", "type": "Ride",
            "distance": 15000, "start_date": "2026-04-01T08:00:00Z",
        },
    ]

    service.handle_manual_sync(db, user.id)

    # conftest autoflush=False，服务函数内部已 commit，此时 DB 已持久化
    # 用 refresh 读 DB 最新值；也可直接用 Python 属性（已被 commit）
    db.refresh(imp)
    assert imp.tier1_completed == 7  # 5 + 2 新
