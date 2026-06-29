"""路线海拔回填的真 PostGIS 测试——专门补 SQLite 模拟不出来的几何读写。"""

from __future__ import annotations

import json
import os
import uuid

from geoalchemy2 import WKTElement
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.activity.models import Activity
from app.route_book.models import RouteBook, RouteVersion
from app.route_book.service import _line_hash
from app.user.models import User
from scripts.backfill_route_elevation import apply_elevation_backfill


def _db_url() -> str:
    url = os.getenv("VELO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 VELO_TEST_DATABASE_URL 后才运行 route elevation backfill 真 PG 测试")
    return url


@pytest.fixture()
def pg_engine():
    base_engine = create_engine(_db_url(), pool_pre_ping=True)
    schema_name = f"route_elev_backfill_{uuid.uuid4().hex}"
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


def test_backfill_reads_and_recreates_route_geometry_on_postgis(pg_engine, pg_session_factory):
    User.__table__.create(bind=pg_engine, checkfirst=True)
    Activity.__table__.create(bind=pg_engine, checkfirst=True)
    RouteBook.__table__.create(bind=pg_engine, checkfirst=True)
    RouteVersion.__table__.create(bind=pg_engine, checkfirst=True)

    db = pg_session_factory()
    try:
        reference_line = "SRID=4326;LINESTRING(112.5 37.8, 112.55 37.85, 112.6 37.9)"
        route = RouteBook(
            name="PostGIS 回填测试路线",
            distance=1000.0,
            climb=None,
            reference_line=WKTElement(reference_line, srid=4326),
            file_id="source.gpx",
            file_type="gpx",
            source="file_upload",
            city="taiyuan",
            visibility="public",
            publish_status="published",
            line_hash=_line_hash(reference_line),
        )
        db.add(route)
        db.flush()
        old_version = RouteVersion(
            route_book_id=route.id,
            version_no=1,
            status="current",
            geometry_source="file_upload",
            navigation_status="ready",
            reference_line_snapshot=WKTElement(reference_line, srid=4326),
            line_hash=_line_hash(reference_line),
            distance=1000.0,
            climb=None,
            elevation_profile=None,
            elevation_points_snapshot=None,
            point_count=3,
        )
        db.add(old_version)
        db.flush()
        route.current_version_id = old_version.id
        db.commit()

        result = apply_elevation_backfill(
            db,
            route_book_id=route.id,
            source_points=[
                [112.50001, 37.80001, 701.2],
                [112.55001, 37.85001, 720.2],
                [112.60001, 37.90001, 735.8],
            ],
            max_distance_m=5,
            commit=True,
            source_license_note="pytest fixture: user-owned precise GPX",
        )
        db.commit()

        db.refresh(route)
        new_version = db.query(RouteVersion).filter_by(route_book_id=route.id, status="current").one()
        archived = db.query(RouteVersion).filter_by(id=old_version.id).one()
        same_geometry = db.execute(
            text(
                """
                SELECT ST_Equals(
                    (SELECT reference_line_snapshot FROM route_versions WHERE id = :old_id),
                    (SELECT reference_line_snapshot FROM route_versions WHERE id = :new_id)
                )
                """
            ),
            {"old_id": old_version.id, "new_id": new_version.id},
        ).scalar()

        assert result.changed is True
        assert route.current_version_id == new_version.id
        assert archived.status == "archived"
        assert new_version.version_no == 2
        assert same_geometry is True
        assert json.loads(new_version.elevation_points_snapshot)[1] == [112.55, 37.85, 720.2]
    finally:
        db.close()
