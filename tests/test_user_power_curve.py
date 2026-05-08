"""
v5 task-2.C.2 + Sprint 4 task-pre-4.2（power_curve service + invalidate）：
真 PG + 真 Redis 测试。

走真 PG（PostGIS / tz-aware datetime / Activity ↔ Trackpoint 完整链路）+
真 Redis（dev stack 的 redis:16379），不 mock，因为：
- Redis 的 scan_iter / setex / decode 行为在生产和 mock 之间常踩坑（CLAUDE.md 陷阱 #5）
- 跨 activity per-window max 必须真 DB 查询验证

测试内部用前缀清理避免污染开发种子数据。

period 枚举（D16 v0.3 / 滚动窗口型 / Sprint 4 task-pre-4.2 升级）：
last_30_days / last_90_days / last_180_days / last_365_days / all_time。
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.activity.models import Activity, Trackpoint
from app.user.models import User
from app.user.service import (
    get_user_power_curve,
    invalidate_power_curve_cache,
)


_PREFIX = "[task-2.C.2 power]"


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


@pytest.fixture(scope="module")
def real_redis():
    """连 dev stack 的 redis:16379；不可用则跳过。"""
    from app.queue import redis_conn
    try:
        redis_conn.ping()
    except Exception as exc:
        pytest.skip(f"dev stack Redis 不可用: {exc}")
    yield redis_conn


def _cleanup_db(db):
    db.execute(text(
        "DELETE FROM trackpoints WHERE activity_id IN "
        "(SELECT id FROM activities WHERE title LIKE :prefix)"
    ), {"prefix": f"{_PREFIX}%"})
    db.execute(text("DELETE FROM activities WHERE title LIKE :prefix"), {"prefix": f"{_PREFIX}%"})
    db.execute(text("DELETE FROM users WHERE openid LIKE :prefix"), {"prefix": "task_2c2_%"})
    db.commit()


def _cleanup_redis(redis_client, user_id: int):
    pattern = f"power_curve:user_{user_id}:*"
    for key in redis_client.scan_iter(match=pattern):
        redis_client.delete(key)


def _make_user(db, suffix: str) -> User:
    user = User(openid=f"task_2c2_{suffix}", nickname=f"task-2.C.2 {suffix}")
    db.add(user)
    db.flush()
    return user


def _make_activity(
    db,
    user: User,
    suffix: str,
    started_at: datetime,
    powers: list[int | None],
) -> Activity:
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

    for i, p in enumerate(powers):
        db.add(Trackpoint(
            activity_id=activity.id,
            seq=i,
            latitude=35.0 + i * 0.0001,
            longitude=110.0 + i * 0.0001,
            elevation=100.0,
            timestamp=started_at + timedelta(seconds=i),
            distance=float(i),
            power=p,
            geom=WKTElement(f"POINT({110.0 + i * 0.0001} {35.0 + i * 0.0001})", srid=4326),
        ))
    db.flush()
    return activity


def _recent_utc(days_ago: int) -> datetime:
    """返回今天往前数 days_ago 天的 UTC 时间（用于构造测试 activity 的 started_at）。"""
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


# ───────────────────────────────────────────────────────────────────────


def test_no_activities_returns_zeros(pg_session_factory, real_redis):
    """no activity → buckets 全 0。"""
    db = pg_session_factory()
    user_id = None
    try:
        _cleanup_db(db)
        user = _make_user(db, "no_act")
        db.commit()
        user_id = user.id
        _cleanup_redis(real_redis, user_id)

        result = get_user_power_curve(db, user_id, "last_30_days")
        assert result["period"] == "last_30_days"
        # buckets 是 dict[int → float]，json round-trip 后 int key 变 str
        for v in result["buckets"].values():
            assert v == 0.0
    finally:
        if user_id is not None:
            _cleanup_redis(real_redis, user_id)
        _cleanup_db(db)
        db.close()


def test_cache_hit_returns_redis_data(pg_session_factory, real_redis):
    """同 user / period 第二次查 → 命中 Redis 缓存（不再查 DB）。"""
    db = pg_session_factory()
    user_id = None
    try:
        _cleanup_db(db)
        user = _make_user(db, "cache_hit")
        _make_activity(
            db, user, "recent",
            started_at=_recent_utc(15),
            powers=[200] * 600,
        )
        db.commit()
        user_id = user.id
        _cleanup_redis(real_redis, user_id)

        first = get_user_power_curve(db, user_id, "last_30_days")
        # 验证 Redis 有写入
        cached_raw = real_redis.get(f"power_curve:user_{user_id}:period_last_30_days")
        assert cached_raw is not None
        cached = json.loads(cached_raw.decode() if isinstance(cached_raw, bytes) else cached_raw)
        assert cached["period"] == "last_30_days"

        # 第二次查应命中 cache，返回相同结果
        second = get_user_power_curve(db, user_id, "last_30_days")
        assert second == first
    finally:
        if user_id is not None:
            _cleanup_redis(real_redis, user_id)
        _cleanup_db(db)
        db.close()


def test_invalidate_cache_clears_all_periods(pg_session_factory, real_redis):
    """invalidate_power_curve_cache 清掉某 user 的全部 period 缓存。"""
    db = pg_session_factory()
    user_id = None
    try:
        _cleanup_db(db)
        user = _make_user(db, "invalidate")
        _make_activity(db, user, "recent", _recent_utc(15), [200] * 500)
        _make_activity(db, user, "older", _recent_utc(60), [180] * 500)
        db.commit()
        user_id = user.id
        _cleanup_redis(real_redis, user_id)

        # 写两个不同 period 的缓存
        get_user_power_curve(db, user_id, "last_30_days")
        get_user_power_curve(db, user_id, "last_90_days")
        assert real_redis.get(f"power_curve:user_{user_id}:period_last_30_days") is not None
        assert real_redis.get(f"power_curve:user_{user_id}:period_last_90_days") is not None

        # invalidate 清全部
        invalidate_power_curve_cache(user_id)
        assert real_redis.get(f"power_curve:user_{user_id}:period_last_30_days") is None
        assert real_redis.get(f"power_curve:user_{user_id}:period_last_90_days") is None
    finally:
        if user_id is not None:
            _cleanup_redis(real_redis, user_id)
        _cleanup_db(db)
        db.close()


def test_invalidate_does_not_touch_other_users(pg_session_factory, real_redis):
    """⚠ 关键：invalidate user A 不应清掉 user B 的缓存（pattern 必须含 user_id）。"""
    db = pg_session_factory()
    user_a_id = None
    user_b_id = None
    try:
        _cleanup_db(db)
        user_a = _make_user(db, "user_a")
        user_b = _make_user(db, "user_b")
        _make_activity(db, user_a, "a", _recent_utc(15), [200] * 500)
        _make_activity(db, user_b, "b", _recent_utc(15), [220] * 500)
        db.commit()
        user_a_id = user_a.id
        user_b_id = user_b.id
        _cleanup_redis(real_redis, user_a_id)
        _cleanup_redis(real_redis, user_b_id)

        get_user_power_curve(db, user_a_id, "last_30_days")
        get_user_power_curve(db, user_b_id, "last_30_days")

        # 清 A 的缓存，B 不动
        invalidate_power_curve_cache(user_a_id)
        assert real_redis.get(f"power_curve:user_{user_a_id}:period_last_30_days") is None
        assert real_redis.get(f"power_curve:user_{user_b_id}:period_last_30_days") is not None
    finally:
        if user_a_id is not None:
            _cleanup_redis(real_redis, user_a_id)
        if user_b_id is not None:
            _cleanup_redis(real_redis, user_b_id)
        _cleanup_db(db)
        db.close()


def test_period_last_30_days_picks_only_recent_30_days(pg_session_factory, real_redis):
    """last_30_days 只统计 30 天内的 activity，不要把 60 天前的拉进来。"""
    db = pg_session_factory()
    user_id = None
    try:
        _cleanup_db(db)
        user = _make_user(db, "period_30d")
        # 60 天前：高功率 250W（在 last_90_days 内 / 在 last_30_days 外）
        _make_activity(db, user, "older_high", _recent_utc(60), [250] * 500)
        # 15 天前：低功率 100W（在 last_30_days 内）
        _make_activity(db, user, "recent_low", _recent_utc(15), [100] * 500)
        db.commit()
        user_id = user.id
        _cleanup_redis(real_redis, user_id)

        recent_result = get_user_power_curve(db, user_id, "last_30_days")
        # 5min（key=300）应该只反映 15 天前的 100W，不拉到 60 天前的 250W
        assert abs(recent_result["buckets"]["300"] - 100.0) < 0.01

        wider_result = get_user_power_curve(db, user_id, "last_90_days")
        # last_90_days 包含 60 天前的，5min 取最高 250W
        assert abs(wider_result["buckets"]["300"] - 250.0) < 0.01
    finally:
        if user_id is not None:
            _cleanup_redis(real_redis, user_id)
        _cleanup_db(db)
        db.close()


def test_period_all_time_includes_everything(pg_session_factory, real_redis):
    """all_time 涵盖所有 completed activities，per-window 取最高。"""
    db = pg_session_factory()
    user_id = None
    try:
        _cleanup_db(db)
        user = _make_user(db, "all_time")
        _make_activity(db, user, "older", _recent_utc(60), [250] * 500)
        _make_activity(db, user, "recent", _recent_utc(15), [100] * 500)
        db.commit()
        user_id = user.id
        _cleanup_redis(real_redis, user_id)

        result = get_user_power_curve(db, user_id, "all_time")
        # all_time 5min 应该取 60 天前的 250W（>100W）
        assert abs(result["buckets"]["300"] - 250.0) < 0.01
    finally:
        if user_id is not None:
            _cleanup_redis(real_redis, user_id)
        _cleanup_db(db)
        db.close()


def test_unknown_period_raises_value_error(pg_session_factory, real_redis):
    """非枚举 period 抛 ValueError（防 router 传错）。"""
    db = pg_session_factory()
    user_id = None
    try:
        _cleanup_db(db)
        user = _make_user(db, "bad_period")
        db.commit()
        user_id = user.id

        with pytest.raises(ValueError, match="unknown period"):
            get_user_power_curve(db, user_id, "yesterday")
    finally:
        _cleanup_db(db)
        db.close()
