"""手画路线保存幂等性的真 PostgreSQL 并发测试。

本地只在显式提供隔离数据库时运行；GitHub CI 严格要求取得真 PG 证据。
"""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.route_book import service
from app.route_book.models import RouteBook, RouteBookSaveRequest, RouteVersion
from app.user.models import User


@pytest.fixture(scope="module")
def pg_session_factory():
    database_url = os.getenv("VELO_TEST_DATABASE_URL")
    required = os.getenv("VELO_REQUIRE_POSTGRES_TESTS") == "1"
    if not database_url:
        if required:
            pytest.fail("CI 必须提供 VELO_TEST_DATABASE_URL", pytrace=False)
        pytest.skip("仅在显式隔离的 VELO_TEST_DATABASE_URL 上运行")
    engine = None
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, ImportError) as exc:
        if engine is not None:
            engine.dispose()
        if required:
            pytest.fail(f"CI 隔离 PostgreSQL 不可用: {exc}", pytrace=False)
        pytest.skip(f"隔离 PostgreSQL 不可用: {exc}")
    try:
        yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    finally:
        engine.dispose()


def _cleanup(db, user_id: int) -> None:
    route_ids = [
        row[0]
        for row in db.query(RouteBook.id).filter(RouteBook.creator_id == user_id).all()
    ]
    if route_ids:
        db.query(RouteBook).filter(RouteBook.id.in_(route_ids)).update(
            {RouteBook.current_version_id: None}, synchronize_session=False
        )
        db.query(RouteVersion).filter(RouteVersion.route_book_id.in_(route_ids)).delete(
            synchronize_session=False
        )
        db.query(RouteBook).filter(RouteBook.id.in_(route_ids)).delete(
            synchronize_session=False
        )
    db.query(RouteBookSaveRequest).filter(
        RouteBookSaveRequest.creator_id == user_id
    ).delete(synchronize_session=False)
    db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
    db.commit()


def test_concurrent_same_manual_draw_request_returns_one_route(
    pg_session_factory, monkeypatch
):
    setup = pg_session_factory()
    user = User(
        openid=f"route_draw_idem_{uuid.uuid4().hex}",
        nickname="route draw idempotency",
    )
    setup.add(user)
    setup.commit()
    setup.refresh(user)
    user_id = user.id
    setup.close()

    barrier = Barrier(2)

    def synchronized_elevation(coords):
        barrier.wait(timeout=10)
        return [700.0 for _coord in coords]

    monkeypatch.setattr(service, "query_elevations", synchronized_elevation)
    request_id = "pg-concurrent-manual-draw-request"

    def create_once() -> int:
        db = pg_session_factory()
        try:
            route = service.create_route_book_from_manual_drawn(
                db=db,
                current_user_id=user_id,
                name="并发保存路线",
                client_request_id=request_id,
                points=[(112.5, 37.8), (112.6, 37.9)],
            )
            return route.id
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            route_ids = list(executor.map(lambda _index: create_once(), range(2)))

        assert route_ids[0] == route_ids[1]
        verify = pg_session_factory()
        try:
            save_request = (
                verify.query(RouteBookSaveRequest)
                .filter(
                    RouteBookSaveRequest.creator_id == user_id,
                    RouteBookSaveRequest.client_request_id == request_id,
                )
                .one()
            )
            routes = verify.query(RouteBook).filter(RouteBook.id == save_request.route_book_id).all()
            assert [route.id for route in routes] == [route_ids[0]]
            assert (
                verify.query(RouteVersion)
                .filter(RouteVersion.route_book_id == route_ids[0])
                .count()
                == 1
            )
        finally:
            verify.close()
    finally:
        cleanup = pg_session_factory()
        try:
            _cleanup(cleanup, user_id)
        finally:
            cleanup.close()


def test_deleted_manual_route_leaves_tombstone_and_replay_is_gone(
    pg_session_factory, monkeypatch
):
    db = pg_session_factory()
    user = User(
        openid=f"route_draw_tombstone_{uuid.uuid4().hex}",
        nickname="route draw tombstone",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    request_id = "pg-deleted-manual-draw-request"
    monkeypatch.setattr(service, "query_elevations", lambda coords: [700.0 for _coord in coords])

    try:
        route = service.create_route_book_from_manual_drawn(
            db=db,
            current_user_id=user_id,
            name="删除后不得复活",
            client_request_id=request_id,
            points=[(112.5, 37.8), (112.6, 37.9)],
        )
        route_id = route.id
        service.delete_route_book(db, route_id, user_id)

        save_request = (
            db.query(RouteBookSaveRequest)
            .filter(
                RouteBookSaveRequest.creator_id == user_id,
                RouteBookSaveRequest.client_request_id == request_id,
            )
            .one()
        )
        assert save_request.route_book_id is None
        assert db.query(RouteBook).filter(RouteBook.id == route_id).count() == 0
        assert db.query(RouteVersion).filter(RouteVersion.route_book_id == route_id).count() == 0

        with pytest.raises(service.ManualDrawIdempotencyGoneError, match="已删除"):
            service.create_route_book_from_manual_drawn(
                db=db,
                current_user_id=user_id,
                name="删除后不得复活",
                client_request_id=request_id,
                points=[(112.5, 37.8), (112.6, 37.9)],
            )

        assert db.query(RouteBook).filter(RouteBook.creator_id == user_id).count() == 0
    finally:
        _cleanup(db, user_id)
        db.close()


def test_concurrent_same_key_different_payload_returns_conflict(
    pg_session_factory, monkeypatch
):
    setup = pg_session_factory()
    user = User(
        openid=f"route_draw_conflict_{uuid.uuid4().hex}",
        nickname="route draw conflict",
    )
    setup.add(user)
    setup.commit()
    setup.refresh(user)
    user_id = user.id
    setup.close()

    barrier = Barrier(2)

    def synchronized_elevation(coords):
        barrier.wait(timeout=10)
        return [700.0 for _coord in coords]

    monkeypatch.setattr(service, "query_elevations", synchronized_elevation)
    request_id = "pg-concurrent-different-payload"

    def create_once(name: str):
        db = pg_session_factory()
        try:
            route = service.create_route_book_from_manual_drawn(
                db=db,
                current_user_id=user_id,
                name=name,
                client_request_id=request_id,
                points=[(112.5, 37.8), (112.6, 37.9)],
            )
            return ("created", route.id)
        except service.ManualDrawIdempotencyConflictError:
            return ("conflict", None)
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create_once, ["并发路线甲", "并发路线乙"]))

        assert sorted(result[0] for result in results) == ["conflict", "created"]
        route_id = next(result[1] for result in results if result[0] == "created")
        verify = pg_session_factory()
        try:
            assert verify.query(RouteBook).filter(RouteBook.creator_id == user_id).count() == 1
            assert (
                verify.query(RouteVersion)
                .filter(RouteVersion.route_book_id == route_id)
                .count()
                == 1
            )
            assert (
                verify.query(RouteBookSaveRequest)
                .filter(
                    RouteBookSaveRequest.creator_id == user_id,
                    RouteBookSaveRequest.client_request_id == request_id,
                )
                .count()
                == 1
            )
        finally:
            verify.close()
    finally:
        cleanup = pg_session_factory()
        try:
            _cleanup(cleanup, user_id)
        finally:
            cleanup.close()
