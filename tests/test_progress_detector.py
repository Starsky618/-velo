"""
v5 task-2.A.1：5min 功率进步检测器测试。

走真 PG（不走 SQLite）：
- 用 PG 部分唯一索引验证幂等
- Activity.started_at / Notification.expires_at 用 tz-aware datetime（SQLite 时区不全）
- payload JSONB 用 PG 原生类型

测试构造：每个 case 自带前缀 _PREFIX 用户/活动，跑完清理。
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.activity.models import Activity, Trackpoint
from app.notification.models import Notification
from app.notification.progress_detector import detect_5min_power_progress
from app.user.models import User


_PREFIX = "[task-2.A.1 detector]"
_BJ_TZ = timezone(timedelta(hours=8))


def _db_url() -> str:
    return (
        os.getenv("VELO_TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql://velo:velo@localhost:5435/velo"
    )


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(_db_url(), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        pytest.skip(f"dev stack PostgreSQL 不可用: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)


def _cleanup(db):
    """按前缀清理：notifications → trackpoints → activities → users。"""
    db.execute(text(
        "DELETE FROM notifications WHERE user_id IN "
        "(SELECT id FROM users WHERE openid LIKE :prefix)"
    ), {"prefix": "task_2a1_%"})
    db.execute(text(
        "DELETE FROM trackpoints WHERE activity_id IN "
        "(SELECT id FROM activities WHERE title LIKE :prefix)"
    ), {"prefix": f"{_PREFIX}%"})
    db.execute(text("DELETE FROM activities WHERE title LIKE :prefix"), {"prefix": f"{_PREFIX}%"})
    db.execute(text("DELETE FROM users WHERE openid LIKE :prefix"), {"prefix": "task_2a1_%"})
    db.commit()


def _make_user(db, suffix: str, mute: bool = False) -> User:
    user = User(
        openid=f"task_2a1_{suffix}",
        nickname=f"task-2.A.1 {suffix}",
        mute_notifications=mute,
    )
    db.add(user)
    db.flush()
    return user


def _make_activity_with_powers(
    db,
    user: User,
    suffix: str,
    started_at: datetime,
    powers: list[int | None],
) -> Activity:
    """构造一个 activity + 对应 trackpoints 序列（功率值由 powers 控制）。"""
    activity = Activity(
        user_id=user.id,
        title=f"{_PREFIX} {suffix}",
        status="completed",
        distance=1000.0,
        duration=len(powers),
        elevation_gain=10.0,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=len(powers)),
        data_source="gpx",
        activity_type="cycling",
    )
    db.add(activity)
    db.flush()

    for i, power in enumerate(powers):
        db.add(Trackpoint(
            activity_id=activity.id,
            seq=i,
            latitude=35.0 + i * 0.0001,
            longitude=110.0 + i * 0.0001,
            elevation=100.0,
            timestamp=started_at + timedelta(seconds=i),
            distance=float(i),
            power=power,
            geom=WKTElement(f"POINT({110.0 + i * 0.0001} {35.0 + i * 0.0001})", srid=4326),
        ))
    db.flush()
    return activity


def _last_month_start_utc() -> datetime:
    """上月某一天 UTC 时间（构造 baseline activity 的 started_at 用）。"""
    now_bj = datetime.now(timezone.utc).astimezone(_BJ_TZ)
    first_this_bj = now_bj.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if first_this_bj.month == 1:
        last_bj = first_this_bj.replace(year=first_this_bj.year - 1, month=12, day=15)
    else:
        last_bj = first_this_bj.replace(month=first_this_bj.month - 1, day=15)
    return last_bj.astimezone(timezone.utc)


def _this_month_start_utc() -> datetime:
    """本月某一天 UTC（构造 current activity）。"""
    now_bj = datetime.now(timezone.utc).astimezone(_BJ_TZ)
    return now_bj.replace(day=15, hour=10, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


# ───────────────────────────────────────────────────────────────────────


def test_no_baseline_returns_none(pg_session_factory):
    """上月无 activity → 直接返 None。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "no_baseline")
        # 只造 current activity，没有上月
        cur = _make_activity_with_powers(
            db, user, "current",
            started_at=_this_month_start_utc(),
            powers=[200] * 600,
        )
        db.commit()

        result = detect_5min_power_progress(db, user.id, cur.id)
        assert result is None
    finally:
        _cleanup(db)
        db.close()


def test_baseline_zero_returns_none(pg_session_factory):
    """上月有 activity 但全无功率（baseline=0）→ 守卫拦截，不假阳性。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "baseline_zero")
        # 上月：500 个 None power（无功率计）
        _make_activity_with_powers(
            db, user, "last_no_power",
            started_at=_last_month_start_utc(),
            powers=[None] * 500,
        )
        # 当前：500 个 200W
        cur = _make_activity_with_powers(
            db, user, "current",
            started_at=_this_month_start_utc(),
            powers=[200] * 500,
        )
        db.commit()

        result = detect_5min_power_progress(db, user.id, cur.id)
        # baseline_5min=0 → 守卫拦截，不应推送"涨 200W"假阳性
        assert result is None
    finally:
        _cleanup(db)
        db.close()


def test_current_zero_returns_none(pg_session_factory):
    """当前 activity 无功率 → 不检测。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "cur_zero")
        _make_activity_with_powers(
            db, user, "last",
            started_at=_last_month_start_utc(),
            powers=[200] * 500,
        )
        cur = _make_activity_with_powers(
            db, user, "current",
            started_at=_this_month_start_utc(),
            powers=[None] * 500,
        )
        db.commit()

        assert detect_5min_power_progress(db, user.id, cur.id) is None
    finally:
        _cleanup(db)
        db.close()


def test_delta_below_threshold_returns_none(pg_session_factory):
    """涨幅 < 5W（涨 4W）→ 不推送。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "delta_4w")
        _make_activity_with_powers(
            db, user, "last",
            started_at=_last_month_start_utc(),
            powers=[200] * 500,
        )
        cur = _make_activity_with_powers(
            db, user, "current",
            started_at=_this_month_start_utc(),
            powers=[204] * 500,  # 涨 4W
        )
        db.commit()

        assert detect_5min_power_progress(db, user.id, cur.id) is None
    finally:
        _cleanup(db)
        db.close()


def test_delta_meets_threshold_creates_notification(pg_session_factory):
    """涨幅 ≥ 5W → 创建 progress_5min_power 通知 + payload 字段齐全。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "delta_15w")
        _make_activity_with_powers(
            db, user, "last",
            started_at=_last_month_start_utc(),
            powers=[200] * 500,
        )
        cur = _make_activity_with_powers(
            db, user, "current",
            started_at=_this_month_start_utc(),
            powers=[215] * 500,  # 涨 15W
        )
        db.commit()

        result = detect_5min_power_progress(db, user.id, cur.id)
        # detector 用 SAVEPOINT 后还需 worker commit 才持久化；测试里手工 commit 模拟 worker
        db.commit()

        assert result is not None
        assert result.event_type == "progress_5min_power"
        assert result.activity_id == cur.id
        assert result.user_id == user.id
        # payload 字段齐全
        assert result.payload["window_sec"] == 300
        assert result.payload["baseline_period"] == "last_month"
        assert result.payload["current_value"] == 215.0
        assert result.payload["prev_value"] == 200.0
        assert result.payload["delta"] == 15.0
        # expires_at 大约 60 天后（误差 1 分钟）
        delta_to_expires = result.expires_at - datetime.now(timezone.utc)
        assert timedelta(days=59, hours=23, minutes=58) < delta_to_expires < timedelta(days=60, minutes=2)
    finally:
        _cleanup(db)
        db.close()


def test_delta_negative_returns_none(pg_session_factory):
    """退步（current < baseline）→ 不推送。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "neg_delta")
        _make_activity_with_powers(
            db, user, "last",
            started_at=_last_month_start_utc(),
            powers=[250] * 500,
        )
        cur = _make_activity_with_powers(
            db, user, "current",
            started_at=_this_month_start_utc(),
            powers=[200] * 500,  # 退步 50W
        )
        db.commit()

        assert detect_5min_power_progress(db, user.id, cur.id) is None
    finally:
        _cleanup(db)
        db.close()


def test_mute_user_returns_none(pg_session_factory):
    """静音用户跳过推送（即使涨幅达标）。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "mute", mute=True)
        _make_activity_with_powers(
            db, user, "last",
            started_at=_last_month_start_utc(),
            powers=[200] * 500,
        )
        cur = _make_activity_with_powers(
            db, user, "current",
            started_at=_this_month_start_utc(),
            powers=[220] * 500,  # 涨 20W 达标
        )
        db.commit()

        assert detect_5min_power_progress(db, user.id, cur.id) is None
    finally:
        _cleanup(db)
        db.close()


def test_idempotent_second_call_returns_none(pg_session_factory):
    """同 activity 第二次调用 → 应用层幂等检查命中，返 None（不重复推送）。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "idempotent")
        _make_activity_with_powers(
            db, user, "last",
            started_at=_last_month_start_utc(),
            powers=[200] * 500,
        )
        cur = _make_activity_with_powers(
            db, user, "current",
            started_at=_this_month_start_utc(),
            powers=[210] * 500,
        )
        db.commit()

        first = detect_5min_power_progress(db, user.id, cur.id)
        db.commit()
        assert first is not None

        second = detect_5min_power_progress(db, user.id, cur.id)
        assert second is None  # 应用层 existing 检查命中

        # DB 中只有 1 条
        count = (
            db.query(Notification)
            .filter(
                Notification.activity_id == cur.id,
                Notification.event_type == "progress_5min_power",
            )
            .count()
        )
        assert count == 1
    finally:
        _cleanup(db)
        db.close()


def test_savepoint_isolates_failure_from_outer_transaction(pg_session_factory):
    """⚠ 关键（SAVEPOINT 隔离 / CLAUDE.md 陷阱 #8）：detector 内部 INSERT 触发 UNIQUE
    → SAVEPOINT 回退 → 外层 worker 在同 session 改的 activity.title 不受影响。

    构造路径：
    1. 先插一条 progress_5min_power 占位（DB 部分唯一索引会拦截后续同 activity_id 的）
    2. 模拟 worker：在 detector 调用前改 activity.title（外层未 commit 的改动）
    3. mock 应用层 existing 查询返 None → 强制走到 db.flush() → DB UNIQUE 抛 IntegrityError
    4. SAVEPOINT 回退 → 验证外层 activity.title 仍在 session 中
    """
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "savepoint")
        _make_activity_with_powers(
            db, user, "last",
            started_at=_last_month_start_utc(),
            powers=[200] * 500,
        )
        cur = _make_activity_with_powers(
            db, user, "current",
            started_at=_this_month_start_utc(),
            powers=[215] * 500,
        )
        # 1. 先占位插一条 progress_5min_power（DB 唯一索引会拦下一条同 activity_id 的）
        existing = Notification(
            user_id=user.id,
            event_type="progress_5min_power",
            activity_id=cur.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=60),
            payload={"current_value": 1.0, "prev_value": 1.0, "delta": 0.0,
                     "window_sec": 300, "baseline_period": "last_month"},
        )
        db.add(existing)
        db.commit()

        # 2. 模拟 worker：改外层字段，未 commit
        cur.title = f"{_PREFIX} savepoint-modified-by-worker"

        # 3. mock 应用层 existing 查询返 None → 强制走 db.flush() 触达 DB UNIQUE
        from app.notification import progress_detector as pd

        original_query = db.query

        def fake_query(*args, **kwargs):
            q = original_query(*args, **kwargs)
            if args and args[0] is pd.Notification:
                # 让应用层 existing 查询返 None
                fake = type("FakeQ", (), {})()
                fake.filter = lambda *a, **kw: fake
                fake.first = lambda: None
                return fake
            return q

        with patch.object(db, "query", side_effect=fake_query):
            result = detect_5min_power_progress(db, user.id, cur.id)

        # 4. SAVEPOINT 路径触发：INSERT → UNIQUE 冲突 → nested.rollback() → 返 None
        assert result is None

        # 关键验证：外层 transaction 改的 cur.title 还在（SAVEPOINT 没把它一起回退）
        assert cur.title == f"{_PREFIX} savepoint-modified-by-worker"
        # 外层未 commit，DB 里 title 还是旧的
        db.commit()
        db.refresh(cur)
        assert cur.title == f"{_PREFIX} savepoint-modified-by-worker"
        # activity.status 也没动
        assert cur.status == "completed"
    finally:
        _cleanup(db)
        db.close()


def test_uses_bj_timezone_for_month_boundary(pg_session_factory):
    """⚠ 关键：用 BJ_TZ 划月，不被 UTC 错归。
    构造一个"BJ 时间在本月 1 号 0:00 之前 8 分钟（即 BJ 上月最后 8 分钟）"的 activity
    UTC 看就是上月最后一天 16 点之前的活动。
    本月划分：> last_month_start_bj，< first_this_month_bj —— 应被划入"上月"。
    """
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "bj_boundary")

        now_bj = datetime.now(timezone.utc).astimezone(_BJ_TZ)
        first_this_bj = now_bj.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # 关键时刻：BJ 上月最后一天 23:52（即 BJ first_this 之前 8 分钟）
        boundary_bj = first_this_bj - timedelta(minutes=8)
        boundary_utc = boundary_bj.astimezone(timezone.utc)

        # 这个时间 UTC 看可能是本月（如 BJ 5/1 00:00 = UTC 4/30 16:00），
        # 但按 BJ 划月，该 activity 是上月最后一天的事 → 应作为 baseline
        _make_activity_with_powers(
            db, user, "last_bj_boundary",
            started_at=boundary_utc,
            powers=[200] * 500,
        )
        cur = _make_activity_with_powers(
            db, user, "current",
            started_at=_this_month_start_utc(),
            powers=[210] * 500,  # 涨 10W
        )
        db.commit()

        result = detect_5min_power_progress(db, user.id, cur.id)
        db.commit()
        # 如果 BJ 时区生效：boundary_utc 是 BJ 上月 → baseline_5min=200 → delta=10 ≥ 5 → 推送
        # 如果 UTC 划月生效（错误）：boundary_utc 可能在"UTC 本月" → baseline_activities=空
        # → 应返回 None
        # 期望：BJ 时区正确划分 → 推送非 None
        assert result is not None
        assert result.payload["delta"] == 10.0
    finally:
        _cleanup(db)
        db.close()
