"""
v5 task-1.A.2：真 PostgreSQL 并发测试。

这里不用 SQLite，因为 advisory lock 和 PostGIS 都是 PostgreSQL 能力。
测试会在 dev stack 数据库里自建带唯一前缀的数据，跑完后清理，避免依赖旧种子状态。
"""

import os
from datetime import datetime, timedelta, timezone
from queue import Queue
from threading import Barrier, Thread

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.activity.models import Activity, Trackpoint
from app.segment.exceptions import SegmentOverlapError
from app.segment.models import Segment, SegmentEffort
from app.segment.service import create_segment_from_activity, get_my_effort_with_compare
from app.user.models import User


_PREFIX = "[task-1.A.2 codex]"


def _db_url() -> str:
    """
    连接 dev stack 数据库。

    在 api 容器内优先用 DATABASE_URL；在宿主机手动跑时退回 localhost:5435。
    类比同一把钥匙在屋内和屋外开不同的门：容器内主机名是 db，宿主机是 localhost。
    """
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
    """按测试前缀清理数据，像擦掉白板上的本轮演算，不碰其他开发数据。"""
    db.execute(text(
        "DELETE FROM segment_efforts WHERE segment_id IN "
        "(SELECT id FROM segments WHERE name LIKE :prefix)"
    ), {"prefix": f"{_PREFIX}%"})
    db.execute(text(
        "DELETE FROM segment_efforts WHERE activity_id IN "
        "(SELECT id FROM activities WHERE title LIKE :prefix)"
    ), {"prefix": f"{_PREFIX}%"})
    db.execute(text("DELETE FROM segments WHERE name LIKE :prefix"), {"prefix": f"{_PREFIX}%"})
    db.execute(text(
        "DELETE FROM trackpoints WHERE activity_id IN "
        "(SELECT id FROM activities WHERE title LIKE :prefix)"
    ), {"prefix": f"{_PREFIX}%"})
    db.execute(text("DELETE FROM activities WHERE title LIKE :prefix"), {"prefix": f"{_PREFIX}%"})
    db.execute(text("DELETE FROM users WHERE openid LIKE :prefix"), {"prefix": "task_1a2_codex_%"})
    db.commit()


def _make_user(db, suffix: str, is_admin: bool = False) -> User:
    user = User(
        openid=f"task_1a2_codex_{suffix}",
        nickname=f"task-1.A.2 {suffix}",
        is_admin=is_admin,
    )
    db.add(user)
    db.flush()
    return user


def _make_activity_with_trackpoints(db, user: User, suffix: str) -> Activity:
    """构造一条超过 1km 的直线轨迹，供 from-activity 裁剪。"""
    started = datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc)
    activity = Activity(
        user_id=user.id,
        title=f"{_PREFIX} activity {suffix}",
        status="completed",
        distance=5000.0,
        duration=1500,
        elevation_gain=80.0,
        started_at=started,
        finished_at=started + timedelta(seconds=1500),
        data_source="gpx",
        activity_type="cycling",
    )
    db.add(activity)
    db.flush()

    for i in range(30):
        lat = 35.0 + i * 0.001
        lon = 110.0 + i * 0.001
        db.add(Trackpoint(
            activity_id=activity.id,
            seq=i,
            latitude=lat,
            longitude=lon,
            elevation=100.0 + i,
            timestamp=started + timedelta(seconds=i * 30),
            distance=i * 150.0,
            geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
        ))
    db.flush()
    return activity


def test_advisory_lock_serializes_concurrent_creates(pg_session_factory):
    """两个线程同时从同一段轨迹建赛段，第二个应在锁后被 Hausdorff 查重挡住。"""
    setup_db = pg_session_factory()
    try:
        _cleanup(setup_db)
        admin = _make_user(setup_db, "admin", is_admin=True)
        activity = _make_activity_with_trackpoints(setup_db, admin, "concurrency")
        activity_id = activity.id
        setup_db.commit()
    finally:
        setup_db.close()

    barrier = Barrier(2)
    results = Queue()

    def _worker(idx: int):
        db = pg_session_factory()
        try:
            barrier.wait(timeout=10)
            segment = create_segment_from_activity(
                db,
                activity_id=activity_id,
                name=f"{_PREFIX} concurrent {idx}",
                start_index=0,
                end_index=20,
            )
            db.commit()
            results.put(("ok", segment.id))
        except SegmentOverlapError:
            db.rollback()
            results.put(("overlap", None))
        except Exception as exc:  # pragma: no cover - 失败时把异常类型带回主线程断言
            db.rollback()
            results.put(("error", repr(exc)))
        finally:
            db.close()

    threads = [Thread(target=_worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    seen = [results.get(timeout=1) for _ in range(2)]
    assert sorted(kind for kind, _ in seen) == ["ok", "overlap"]

    cleanup_db = pg_session_factory()
    try:
        _cleanup(cleanup_db)
    finally:
        cleanup_db.close()


def test_get_my_effort_ordering_with_real_db(pg_session_factory):
    """真 DB 验证 my_latest 按 Activity.started_at，晚骑的 1100s 应被选中。"""
    db = pg_session_factory()
    try:
        _cleanup(db)
        rider = _make_user(db, "rider")
        other = _make_user(db, "other")
        segment = Segment(
            name=f"{_PREFIX} ordering segment",
            distance=2200.0,
            elevation_gain=50.0,
            start_lat=37.0,
            start_lon=112.0,
            end_lat=37.02,
            end_lon=112.02,
            reference_line=WKTElement("LINESTRING(112.0 37.0, 112.02 37.02)", srid=4326),
            difficulty="hard",
            city="taiyuan",
        )
        db.add(segment)
        db.flush()

        early_started = datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc)
        late_started = datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)
        early_activity = Activity(
            user_id=rider.id,
            title=f"{_PREFIX} early",
            status="completed",
            distance=3000.0,
            duration=1300,
            started_at=early_started,
            finished_at=early_started + timedelta(seconds=1300),
            data_source="gpx",
            activity_type="cycling",
        )
        late_activity = Activity(
            user_id=rider.id,
            title=f"{_PREFIX} late",
            status="completed",
            distance=3000.0,
            duration=1100,
            started_at=late_started,
            finished_at=late_started + timedelta(seconds=1100),
            data_source="gpx",
            activity_type="cycling",
        )
        other_activity = Activity(
            user_id=other.id,
            title=f"{_PREFIX} other",
            status="completed",
            distance=3000.0,
            duration=1000,
            started_at=late_started,
            finished_at=late_started + timedelta(seconds=1000),
            data_source="gpx",
            activity_type="cycling",
        )
        db.add_all([early_activity, late_activity, other_activity])
        db.flush()

        db.add_all([
            SegmentEffort(
                segment_id=segment.id,
                activity_id=early_activity.id,
                user_id=rider.id,
                elapsed_time=1300,
                start_index=0,
                end_index=10,
            ),
            SegmentEffort(
                segment_id=segment.id,
                activity_id=late_activity.id,
                user_id=rider.id,
                elapsed_time=1100,
                start_index=0,
                end_index=10,
            ),
            SegmentEffort(
                segment_id=segment.id,
                activity_id=other_activity.id,
                user_id=other.id,
                elapsed_time=1000,
                start_index=0,
                end_index=10,
            ),
        ])
        db.commit()

        result = get_my_effort_with_compare(db, segment.id, rider.id)

        assert result["my_best"]["elapsed_time"] == 1100
        assert result["my_latest"]["elapsed_time"] == 1100
        assert result["my_latest"]["activity_started_at"] == late_started
        assert result["rank"] == 2
        assert result["total_riders"] == 2
    finally:
        _cleanup(db)
        db.close()
