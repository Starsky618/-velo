"""route_segments writer 真 PostGIS 测试——像把装配单拿到真实仓库里扫一遍条码。"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.activity.models import Activity
from app.route_book.models import RouteBook, RouteVersion
from app.route_cognition.geometry_hash import (
    SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
    hash_segment_geometry_wkt,
)
from app.route_cognition.models import (
    JudgmentRun,
    RouteCognitionSegment,
    RouteSegment,
    SegmentGeometrySource,
)
from app.route_cognition.services.route_segment_writer import (
    add_route_custom_geometry,
    add_route_segment_clip,
)
from app.segment.models import Segment
from app.user.models import User


def _db_url() -> str:
    """读取真 PG 测试库地址；不猜生产库，必须由环境显式提供。"""
    url = os.getenv("VELO_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("设置 VELO_TEST_DATABASE_URL 或 DATABASE_URL 后才运行 route_segments writer 真 PG 测试")
    return url


@pytest.fixture()
def pg_engine():
    """每个测试单独建临时 schema；像铺一张一次性桌布，测完整张丢掉。"""
    base_engine = create_engine(_db_url(), pool_pre_ping=True)
    schema_name = f"route_segment_writer_{uuid.uuid4().hex}"
    try:
        with base_engine.begin() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.execute(text(f"CREATE SCHEMA {schema_name}"))
    except SQLAlchemyError as exc:
        base_engine.dispose()
        pytest.skip(f"dev stack PostgreSQL/PostGIS 不可用: {exc}")

    engine = create_engine(
        _db_url(),
        connect_args={"options": f"-csearch_path={schema_name},public"},
        pool_pre_ping=True,
    )
    try:
        yield engine
    finally:
        engine.dispose()
        try:
            with base_engine.begin() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
        finally:
            base_engine.dispose()


@pytest.fixture()
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)


def test_route_segment_writer_persists_valid_components_on_postgis(pg_engine, pg_session_factory):
    _create_route_segment_writer_tables(pg_engine)
    db = pg_session_factory()
    try:
        seed = _seed_route_segment_writer_objects(db)
        db.flush()
        route_book_wkt_before = _geometry_text(db, "route_books", "reference_line", seed["route_book_id"])
        route_version_wkt_before = _geometry_text(
            db,
            "route_versions",
            "reference_line_snapshot",
            seed["route_version_id"],
        )
        segment_wkt_before = _geometry_text(db, "segments", "reference_line", seed["segment_id"])
        before_count = db.execute(text("SELECT count(*) FROM route_segments")).scalar_one()

        segment_clip = add_route_segment_clip(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=1,
            segment_id=seed["segment_id"],
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="forward",
            accepted_judgment_run_id=seed["route_judgment_id"],
        )
        custom_geometry = add_route_custom_geometry(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=2,
            component_geometry="MULTILINESTRING((1 1, 2 2), (2 2, 3 3))",
            accepted_judgment_run_id=seed["route_judgment_id"],
        )

        assert db.execute(text("SELECT count(*) FROM route_segments")).scalar_one() == before_count + 2
        _assert_segment_clip_row(
            db,
            route_segment_id=segment_clip.id,
            segment_id=seed["segment_id"],
            expected_segment_geometry_hash=seed["segment_geometry_hash"],
        )
        _assert_custom_geometry_row(db, route_segment_id=custom_geometry.id)
        _assert_route_segment_geometry_is_valid(db, route_segment_id=segment_clip.id)
        _assert_route_segment_geometry_is_valid(db, route_segment_id=custom_geometry.id)
        assert _geometry_text(db, "route_books", "reference_line", seed["route_book_id"]) == route_book_wkt_before
        assert (
            _geometry_text(db, "route_versions", "reference_line_snapshot", seed["route_version_id"])
            == route_version_wkt_before
        )
        assert _geometry_text(db, "segments", "reference_line", seed["segment_id"]) == segment_wkt_before
    finally:
        db.rollback()
        db.close()


def test_route_segment_writer_does_not_accept_caller_provided_hashes(pg_session_factory):
    db = pg_session_factory()
    try:
        base_kwargs = {
            "route_book_id": 1,
            "route_version_id": 1,
            "seq": 1,
            "segment_id": 1,
            "component_geometry": "LINESTRING(0 0, 1 1)",
            "direction": "forward",
            "accepted_judgment_run_id": 1,
        }
        with pytest.raises(TypeError):
            add_route_segment_clip(db, **base_kwargs, route_line_hash="fake")
        with pytest.raises(TypeError):
            add_route_segment_clip(db, **base_kwargs, segment_geometry_hash="fake")
        with pytest.raises(TypeError):
            add_route_segment_clip(db, **base_kwargs, component_geometry_hash="fake")
        with pytest.raises(TypeError):
            add_route_custom_geometry(
                db,
                route_book_id=1,
                route_version_id=1,
                seq=1,
                component_geometry="LINESTRING(0 0, 1 1)",
                accepted_judgment_run_id=1,
                component_geometry_hash="fake",
            )
    finally:
        db.rollback()
        db.close()


def _create_route_segment_writer_tables(pg_engine) -> None:
    """创建 writer 需要的最小真实表集合。"""
    User.__table__.create(bind=pg_engine, checkfirst=False)
    Activity.__table__.create(bind=pg_engine, checkfirst=False)
    Segment.__table__.create(bind=pg_engine, checkfirst=False)
    RouteBook.__table__.create(bind=pg_engine, checkfirst=False)
    RouteVersion.__table__.create(bind=pg_engine, checkfirst=False)
    JudgmentRun.__table__.create(bind=pg_engine, checkfirst=False)
    SegmentGeometrySource.__table__.create(bind=pg_engine, checkfirst=False)
    RouteCognitionSegment.__table__.create(bind=pg_engine, checkfirst=False)
    RouteSegment.__table__.create(bind=pg_engine, checkfirst=False)


def _seed_route_segment_writer_objects(db) -> dict[str, int | str]:
    user = User(openid=f"route_segment_writer_pg_{uuid.uuid4().hex}", nickname="route segment writer pg")
    db.add(user)
    db.flush()

    route_wkt = "LINESTRING(0 0, 1 1, 2 2)"
    route = RouteBook(
        creator_id=user.id,
        name="PG route segment writer route",
        distance=3000.0,
        reference_line=WKTElement(route_wkt, srid=4326),
        source="manual_drawn",
        city="taiyuan",
        visibility="private",
        publish_status="draft",
    )
    db.add(route)
    db.flush()

    version = RouteVersion(
        route_book_id=route.id,
        version_no=1,
        geometry_source="manual_drawn",
        reference_line_snapshot=WKTElement(route_wkt, srid=4326),
        line_hash=hash_segment_geometry_wkt(route_wkt),
        distance=3000.0,
    )
    db.add(version)
    db.flush()

    segment_wkt = "LINESTRING(0 0, 1 1)"
    segment = Segment(
        name="PG route segment writer segment",
        distance=1000.0,
        start_lat=0.0,
        start_lon=0.0,
        end_lat=1.0,
        end_lon=1.0,
        reference_line=WKTElement(segment_wkt, srid=4326),
        city="taiyuan",
    )
    db.add(segment)
    db.flush()

    route_judgment = JudgmentRun(
        run_type="human_review",
        status="succeeded",
        trigger_type="test",
        route_book_id=route.id,
        route_version_id=version.id,
        confidence_state="human_accepted",
        created_by_user_id=user.id,
    )
    segment_judgment = JudgmentRun(
        run_type="human_review",
        status="succeeded",
        trigger_type="test",
        segment_id=segment.id,
        confidence_state="stable",
        created_by_user_id=user.id,
    )
    db.add_all([route_judgment, segment_judgment])
    db.flush()

    segment_geometry_hash = hash_segment_geometry_wkt(segment_wkt)
    cognition_segment = RouteCognitionSegment(
        segment_id=segment.id,
        primary_geometry_source_id=None,
        review_basis="legacy_reviewed",
        eligibility_status="active",
        geometry_hash=segment_geometry_hash,
        normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        accepted_judgment_run_id=segment_judgment.id,
        reviewed_by=user.id,
        reviewed_at=datetime.now(timezone.utc),
    )
    db.add(cognition_segment)
    db.flush()

    return {
        "route_book_id": route.id,
        "route_version_id": version.id,
        "segment_id": segment.id,
        "route_judgment_id": route_judgment.id,
        "segment_geometry_hash": segment_geometry_hash,
    }


def _assert_segment_clip_row(
    db,
    *,
    route_segment_id: int,
    segment_id: int,
    expected_segment_geometry_hash: str,
) -> None:
    row = db.execute(
        text(
            """
            SELECT
                component_type,
                segment_id,
                segment_geometry_hash,
                component_geometry IS NOT NULL AS has_geometry,
                component_geometry_hash IS NOT NULL AS has_geometry_hash,
                direction
            FROM route_segments
            WHERE id = :route_segment_id
            """
        ),
        {"route_segment_id": route_segment_id},
    ).one()

    assert row.component_type == "segment_clip"
    assert row.segment_id == segment_id
    assert row.segment_geometry_hash == expected_segment_geometry_hash
    assert row.has_geometry is True
    assert row.has_geometry_hash is True
    assert row.direction in {"forward", "reverse"}


def _assert_custom_geometry_row(db, *, route_segment_id: int) -> None:
    row = db.execute(
        text(
            """
            SELECT
                component_type,
                segment_id,
                segment_geometry_hash,
                direction,
                start_fraction,
                end_fraction,
                component_geometry IS NOT NULL AS has_geometry,
                component_geometry_hash IS NOT NULL AS has_geometry_hash
            FROM route_segments
            WHERE id = :route_segment_id
            """
        ),
        {"route_segment_id": route_segment_id},
    ).one()

    assert row.component_type == "custom_geometry"
    assert row.segment_id is None
    assert row.segment_geometry_hash is None
    assert row.direction is None
    assert row.start_fraction is None
    assert row.end_fraction is None
    assert row.has_geometry is True
    assert row.has_geometry_hash is True


def _assert_route_segment_geometry_is_valid(db, *, route_segment_id: int) -> None:
    row = db.execute(
        text(
            """
            SELECT
                ST_SRID(component_geometry) = 4326 AS srid_ok,
                upper(replace(GeometryType(component_geometry), 'ST_', '')) IN
                    ('LINESTRING', 'MULTILINESTRING') AS type_ok,
                ST_IsValid(component_geometry) AS valid_ok
            FROM route_segments
            WHERE id = :route_segment_id
            """
        ),
        {"route_segment_id": route_segment_id},
    ).one()

    assert row == (True, True, True)


def _geometry_text(db, table_name: str, column_name: str, row_id: int) -> str:
    return db.execute(
        text(f"SELECT ST_AsText({column_name}) FROM {table_name} WHERE id = :row_id"),
        {"row_id": row_id},
    ).scalar_one()
