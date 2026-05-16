"""
v5 task-2.C.1：User.city 字段防回退测试。

字段本身在 task-1.A.1 加 ORM Column / task-0.6 加 DB 列 + CheckConstraint。
本测试不是"新加字段"，而是**防回退**——
未来 user/models.py 改动若误删 city 字段或 CheckConstraint，本测试会立即报警。

走真 PG（不走 SQLite）：CheckConstraint 是 PG 层约束，SQLite 不模拟 → 必须真触达 DB。
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.user.models import User


_PREFIX = "task_2c1_city"


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
    db.execute(text("DELETE FROM users WHERE openid LIKE :prefix"), {"prefix": f"{_PREFIX}_%"})
    db.commit()


def test_user_city_column_exists():
    """ORM 声明：city 字段存在 + 类型 String(64) + nullable=True。

    Sprint 6 task-4 hotfix（Tim 2026-05-17）：city 放宽到 String(64) 任意中文标签
    （picker 选省+市拼 / ≤ 32 字符 schema 校验 / DB 留 64 字节冗余）。
    """
    col = User.__table__.columns["city"]
    assert col.type.length == 64
    assert col.nullable is True


def test_user_city_check_constraint_removed():
    """ORM 声明：ck_users_city CheckConstraint 已删（user.city 改任意中文）。

    Sprint 6 task-4 hotfix（Tim 2026-05-17）：放宽用户家乡标签 / 删 6 城 CHECK。
    activities.city 的 ck_activities_city 不动 / 仍限 6 城+unknown。
    """
    constraints = {c.name for c in User.__table__.constraints}
    assert "ck_users_city" not in constraints


def test_user_city_null_allowed(pg_session_factory):
    """DB 实测：city=NULL 允许（用户未填写状态）。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = User(openid=f"{_PREFIX}_null", nickname="task-2.C.1 null")
        db.add(user)
        db.commit()  # 不应抛
        # 验证写入成功
        loaded = db.query(User).filter(User.openid == f"{_PREFIX}_null").first()
        assert loaded is not None
        assert loaded.city is None
    finally:
        _cleanup(db)
        db.close()


def test_user_city_six_cities_plus_unknown_allowed(pg_session_factory):
    """DB 实测：6 主城 + 'unknown' 7 个值都允许（与 segments.city 枚举一致）。"""
    valid_cities = ["beijing", "shanghai", "hangzhou", "shenzhen", "chengdu", "taiyuan", "unknown"]
    db = pg_session_factory()
    try:
        _cleanup(db)
        for i, city in enumerate(valid_cities):
            user = User(openid=f"{_PREFIX}_{city}", nickname=f"task-2.C.1 {city}", city=city)
            db.add(user)
        db.commit()  # 7 条全部应该写入成功

        count = db.query(User).filter(User.openid.like(f"{_PREFIX}_%")).count()
        assert count == 7
    finally:
        _cleanup(db)
        db.close()


def test_user_city_invalid_value_rejected(pg_session_factory):
    """DB 实测：CheckConstraint 拒非法值（防脏数据进热图聚合）。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        # 'guangzhou' 不在 6 主城枚举里 → CheckConstraint 应抛 IntegrityError
        user = User(openid=f"{_PREFIX}_guangzhou", nickname="task-2.C.1 invalid", city="guangzhou")
        db.add(user)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        # 验证非法值确实没写入
        loaded = db.query(User).filter(User.openid == f"{_PREFIX}_guangzhou").first()
        assert loaded is None
    finally:
        _cleanup(db)
        db.close()
