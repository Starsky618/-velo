"""Sprint 6 task-3：Activity.city 字段防回退测试（CHECK 约束层）。

字段在 sprint6_activity_city 迁移加 DB 列 + CHECK 约束 / Activity model 加 ORM Column + CheckConstraint。
本测试不是"新加字段"，而是**防回退**——未来 Activity model / 迁移误删 city 字段或 CHECK 约束，
本测试会立即报警。

走真 PG（不走 SQLite）：CheckConstraint 是 PG 层约束 / SQLite 不模拟 → 必须真触达 DB。
（与 test_user_city_field.py 同 pattern / dev stack PG 不可用时 skip）

测试矩阵：
- ORM 声明层：city 字段类型 / nullable / CheckConstraint 名字
- DB 实测层：6 城 + unknown 7 值允许 / NULL 允许 / 非法 'guangzhou' 拒绝
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.activity.models import Activity
from app.user.models import User


_PREFIX = "task_6_3_act_city"


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
    """清理本测试残留数据（先 activities 后 users / 外键顺序）。"""
    db.execute(
        text("DELETE FROM activities WHERE title LIKE :prefix"),
        {"prefix": f"{_PREFIX}_%"},
    )
    db.execute(
        text("DELETE FROM users WHERE openid LIKE :prefix"),
        {"prefix": f"{_PREFIX}_%"},
    )
    db.commit()


def _make_user(db, suffix: str) -> User:
    user = User(openid=f"{_PREFIX}_{suffix}", nickname=f"act-city {suffix}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_activity_city_column_exists():
    """ORM 声明：city 字段存在 + 类型 String(32) + nullable=True。"""
    col = Activity.__table__.columns["city"]
    assert col.type.length == 32
    assert col.nullable is True


def test_activity_city_check_constraint_exists():
    """ORM 声明：ck_activities_city CheckConstraint 存在（防 model 改动误删）。"""
    constraints = {c.name for c in Activity.__table__.constraints}
    assert "ck_activities_city" in constraints


def test_activity_city_null_allowed(pg_session_factory):
    """DB 实测 case-4：city=NULL 允许（旧数据 / 起点坐标缺失场景）。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "null")
        activity = Activity(
            user_id=user.id,
            title=f"{_PREFIX}_null",
            status="completed",
            city=None,
        )
        db.add(activity)
        db.commit()  # 不应抛

        loaded = (
            db.query(Activity).filter(Activity.title == f"{_PREFIX}_null").first()
        )
        assert loaded is not None
        assert loaded.city is None
    finally:
        _cleanup(db)
        db.close()


def test_activity_city_six_cities_plus_unknown_allowed(pg_session_factory):
    """DB 实测 case-6 (PG)：6 城 + 'unknown' 7 个值都允许（与 users.city CHECK 一致）。"""
    valid_cities = [
        "beijing", "shanghai", "hangzhou", "shenzhen", "chengdu", "taiyuan", "unknown",
    ]
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "valid")
        for city in valid_cities:
            db.add(
                Activity(
                    user_id=user.id,
                    title=f"{_PREFIX}_{city}",
                    status="completed",
                    city=city,
                )
            )
        db.commit()  # 7 条全部应该写入成功

        count = (
            db.query(Activity)
            .filter(Activity.title.like(f"{_PREFIX}_%"))
            .count()
        )
        assert count == 7
    finally:
        _cleanup(db)
        db.close()


def test_activity_city_invalid_value_rejected(pg_session_factory):
    """DB 实测 case-5：CHECK 约束拒非法值 'nanjing'（防脏数据进 city-medals 聚合）。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        user = _make_user(db, "invalid")
        # 'nanjing' 不在 7 枚举内 → CheckConstraint 应抛 IntegrityError
        activity = Activity(
            user_id=user.id,
            title=f"{_PREFIX}_nanjing",
            status="completed",
            city="nanjing",
        )
        db.add(activity)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        # 验证非法值确实没写入
        loaded = (
            db.query(Activity)
            .filter(Activity.title == f"{_PREFIX}_nanjing")
            .first()
        )
        assert loaded is None
    finally:
        _cleanup(db)
        db.close()
