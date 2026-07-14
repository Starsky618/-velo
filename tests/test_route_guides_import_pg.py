"""路线百科 Batch 1 的真 PostGIS 防回退测试。

这个文件像一间独立考场：只在 PostgreSQL/PostGIS 里跑，且每个测试创建自己的临时 schema。
这样可以验证 SQLite 模拟不出来的 Geometry、CHECK、迁移回填行为，又不会擦到开发库里的真实表。
"""

from __future__ import annotations

import importlib
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.activity.models import Activity
from app.database import Base
from app.route_cognition.models import JudgmentRun
from app.route_book.models import RouteBook, RouteGuide, RouteVersion
from app.segment.models import Segment
from app.user.models import User


FIXTURE_ROUTES = Path(__file__).parent / "fixtures" / "routes"
FAKE_GLO_ELEVATION_M = 1234.5


def _flat_glo_elevations(coords):
    """返回和 fixture GPX 原始 800/830/820m 明显不同的 GLO 成品输入。"""
    assert coords[0] == pytest.approx((37.8, 112.5))
    assert coords[-1] == pytest.approx((37.82, 112.52))
    return [FAKE_GLO_ELEVATION_M for _coord in coords]


def _assert_strict_glo_product(book, version, guide) -> None:
    from app.elevation.dem_client import (
        GLO30_HORIZONTAL_RESOLUTION_M,
        GLO30_LICENSE_ID,
        GLO30_SOURCE_NAME,
        GLO30_VERTICAL_ACCURACY_M,
    )
    from app.elevation.route_elevation import ROUTE_ELEVATION_METHOD, route_elevation_metadata
    from app.route_book.elevation_quality import has_trusted_route_elevation

    snapshot = json.loads(version.elevation_points_snapshot)
    assert snapshot == [
        [112.5, 37.8, FAKE_GLO_ELEVATION_M],
        [112.51, 37.81, FAKE_GLO_ELEVATION_M],
        [112.52, 37.82, FAKE_GLO_ELEVATION_M],
    ]
    assert [point[2] for point in snapshot] != [800.0, 830.0, 820.0]
    assert version.point_count == 3
    assert version.climb == book.climb == 0.0
    assert version.elevation_profile == book.elevation_profile == guide.elevation_profile
    assert all(point[1] == FAKE_GLO_ELEVATION_M for point in json.loads(version.elevation_profile))

    elevation_metadata = json.loads(version.navigation_metadata_json)["elevation"]
    generated_at = elevation_metadata.get("generated_at")
    assert generated_at is not None
    assert datetime.fromisoformat(generated_at).tzinfo is not None
    assert elevation_metadata == {
        "source_name": GLO30_SOURCE_NAME,
        "license_id": GLO30_LICENSE_ID,
        "accuracy_m": GLO30_VERTICAL_ACCURACY_M,
        "point_count": 3,
        "method": ROUTE_ELEVATION_METHOD,
        "horizontal_resolution_m": GLO30_HORIZONTAL_RESOLUTION_M,
        **route_elevation_metadata(),
        "generated_at": generated_at,
    }
    assert has_trusted_route_elevation(
        version.elevation_points_snapshot,
        metadata_json=version.navigation_metadata_json,
        expected_count=version.point_count,
    )


def _db_url() -> str:
    """读取真 PG 测试库地址；必须显式配置，避免误碰开发或生产库。"""
    url = os.getenv("VELO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 VELO_TEST_DATABASE_URL 后才运行 route_books Batch 1 真 PG 测试")
    return url


@pytest.fixture()
def pg_engine():
    """给每个测试开一个独立 schema，像临时铺一张白纸，测完整张扔掉。"""
    base_engine = create_engine(_db_url(), pool_pre_ping=True)
    schema_name = f"route_batch1_{uuid.uuid4().hex}"
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


def _create_import_tables(pg_engine) -> None:
    """在随机 schema 强制创建最小表集，不复用 search_path 可见的 public 表。"""
    tables = (
        User.__table__,
        Activity.__table__,
        Segment.__table__,
        RouteBook.__table__,
        RouteVersion.__table__,
        JudgmentRun.__table__,
        RouteGuide.__table__,
    )
    Base.metadata.create_all(bind=pg_engine, tables=tables, checkfirst=False)

    expected = {table.name for table in tables}
    with pg_engine.connect() as conn:
        schema_name = conn.execute(text("SELECT current_schema()")).scalar_one()
        actual = set(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                )
            ).scalars()
        )
    assert schema_name.startswith("route_batch1_")
    assert expected <= actual


def _copy_fixture(tmp_path: Path, *route_names: str) -> Path:
    target = tmp_path / "routes"
    target.mkdir()
    for route_name in route_names:
        shutil.copytree(FIXTURE_ROUTES / route_name, target / route_name)
    return target


def test_imports_gpx_route_and_creates_public_official_route_book_on_postgis(
    pg_engine,
    pg_session_factory,
    tmp_path,
    monkeypatch,
):
    """导入官方 GPX 路线后，route_book 必须 public/published 且挂上 v1 route_version。"""
    from scripts import import_route_guides as script

    _create_import_tables(pg_engine)
    db = pg_session_factory()
    try:
        content_dir = _copy_fixture(tmp_path, "test-gpx-route")
        monkeypatch.setattr(script, "SessionLocal", lambda: db)
        monkeypatch.setattr(script, "query_elevations", _flat_glo_elevations)

        script.main(["--content-dir", str(content_dir)])

        guide = db.query(RouteGuide).filter_by(name="测试 GPX 路线").one()
        book = db.query(RouteBook).filter_by(id=guide.route_book_id).one()
        version = db.query(RouteVersion).filter_by(route_book_id=book.id).one()
        profile = json.loads(guide.elevation_profile)

        assert guide.city == "太原"
        assert json.loads(guide.highlights) == ["起点清晰", "终点清晰"]
        assert guide.cover_url == "https://example.com/test-gpx.jpg"
        assert book.is_official is True
        assert book.source == "file_upload"
        assert book.file_type == "gpx"
        assert book.file_id
        assert book.city == "taiyuan"
        assert book.visibility == "public"
        assert book.publish_status == "published"
        assert book.current_version_id is not None
        assert version.id == book.current_version_id
        assert guide.source_route_version_id == book.current_version_id
        assert version.version_no == 1
        assert version.status == "current"
        assert version.navigation_status == "ready"
        assert version.geometry_source == "file_upload"
        _assert_strict_glo_product(book, version, guide)
        assert db.execute(
            text(
                """
                SELECT
                    ST_SRID(reference_line) = 4326 AS book_srid_ok,
                    ST_NPoints(reference_line) >= 2 AS book_points_ok,
                    ST_IsValid(reference_line) AS book_valid
                FROM route_books
                WHERE id = :route_book_id
                """
            ),
            {"route_book_id": book.id},
        ).one() == (True, True, True)
        assert db.execute(
            text(
                """
                SELECT
                    ST_SRID(reference_line_snapshot) = 4326 AS version_srid_ok,
                    ST_NPoints(reference_line_snapshot) >= 2 AS version_points_ok,
                    ST_IsValid(reference_line_snapshot) AS version_valid
                FROM route_versions
                WHERE id = :route_version_id
                """
            ),
            {"route_version_id": version.id},
        ).one() == (True, True, True)
        assert len(profile) <= 100
        assert profile
        assert profile[0][0] == 0
        assert profile[-1][0] > profile[0][0]
        assert all(curr[0] >= prev[0] for prev, curr in zip(profile, profile[1:]))
    finally:
        db.close()


def test_idempotent_rerun_updates_existing_guide_and_book_on_postgis(
    pg_engine,
    pg_session_factory,
    tmp_path,
    monkeypatch,
):
    """重复导入只更新原记录，不复制 route_book 或 route_version。"""
    from scripts import import_route_guides as script

    _create_import_tables(pg_engine)
    db = pg_session_factory()
    try:
        content_dir = _copy_fixture(tmp_path, "test-gpx-route")
        monkeypatch.setattr(script, "SessionLocal", lambda: db)
        monkeypatch.setattr(script, "query_elevations", _flat_glo_elevations)

        script.main(["--content-dir", str(content_dir)])
        first_guide = db.query(RouteGuide).filter_by(name="测试 GPX 路线").one()
        first_book_id = first_guide.route_book_id
        (content_dir / "test-gpx-route" / "guide.md").write_text(
            "# 测试 GPX 路线\n\n第二版介绍。\n",
            encoding="utf-8",
        )

        script.main(["--content-dir", str(content_dir)])

        guide = db.query(RouteGuide).filter_by(name="测试 GPX 路线").one()
        assert db.query(RouteGuide).count() == 1
        assert db.query(RouteBook).count() == 1
        assert db.query(RouteVersion).count() == 1
        assert guide.route_book_id == first_book_id
        assert guide.content_md.endswith("第二版介绍。\n")
        book = db.query(RouteBook).filter_by(id=guide.route_book_id).one()
        version = db.query(RouteVersion).filter_by(route_book_id=book.id).one()
        _assert_strict_glo_product(book, version, guide)
    finally:
        db.close()


def test_track_pending_guide_upgrades_in_place_on_postgis(
    pg_engine,
    pg_session_factory,
    tmp_path,
    monkeypatch,
):
    """先导入无轨迹介绍，补 GPX 后原 guide 原地升级且只创建一套路线。"""
    from scripts import import_route_guides as script

    _create_import_tables(pg_engine)
    db = pg_session_factory()
    try:
        content_dir = _copy_fixture(tmp_path, "test-no-track")
        monkeypatch.setattr(script, "SessionLocal", lambda: db)
        monkeypatch.setattr(script, "query_elevations", _flat_glo_elevations)

        script.main(["--content-dir", str(content_dir)])
        pending = db.query(RouteGuide).filter_by(name="测试无轨迹路线").one()
        pending_id = pending.id
        assert pending.route_book_id is None
        assert db.query(RouteBook).count() == 0

        shutil.copy(
            FIXTURE_ROUTES / "test-gpx-route" / "track.gpx",
            content_dir / "test-no-track" / "track.gpx",
        )
        script.main(["--content-dir", str(content_dir)])

        upgraded = db.query(RouteGuide).filter_by(name="测试无轨迹路线").one()
        assert upgraded.id == pending_id
        assert upgraded.route_book_id is not None
        assert upgraded.elevation_profile is not None
        version = db.query(RouteVersion).filter_by(route_book_id=upgraded.route_book_id).one()
        book = db.query(RouteBook).filter_by(id=upgraded.route_book_id).one()
        _assert_strict_glo_product(book, version, upgraded)
        assert db.query(RouteGuide).count() == 1
        assert db.query(RouteBook).count() == 1
        assert db.query(RouteVersion).count() == 1
    finally:
        db.close()

def _create_legacy_route_books(conn) -> None:
    """造一张 Batch 1 前的旧 route_books，用来验证真实 migration 回填。"""
    conn.execute(text("CREATE TABLE users (id SERIAL PRIMARY KEY)"))
    conn.execute(text("CREATE TABLE activities (id SERIAL PRIMARY KEY)"))
    conn.execute(text(
        """
        CREATE TABLE route_books (
            id SERIAL PRIMARY KEY,
            creator_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            name VARCHAR(128) NOT NULL,
            distance DOUBLE PRECISION NOT NULL,
            climb DOUBLE PRECISION,
            reference_line geometry(LINESTRING, 4326),
            file_id VARCHAR(512),
            file_type VARCHAR(8),
            source VARCHAR(32) NOT NULL,
            source_activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL,
            city VARCHAR(32) NOT NULL DEFAULT 'unknown',
            is_official BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
        """
    ))
    conn.execute(text(
        "ALTER TABLE route_books ADD CONSTRAINT ck_route_books_source "
        "CHECK (source IN ('file_upload', 'activity_derived', 'tencent_direction'))"
    ))
    conn.execute(text(
        """
        ALTER TABLE route_books ADD CONSTRAINT ck_route_books_file_type_source CHECK (
            (source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL
                AND source_activity_id IS NULL) OR
            (source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL) OR
            (source = 'tencent_direction' AND file_type IS NULL AND file_id IS NULL
                AND source_activity_id IS NULL)
        )
        """
    ))
    conn.execute(text("INSERT INTO users DEFAULT VALUES"))
    conn.execute(text(
        """
        INSERT INTO route_books (
            creator_id, name, distance, climb, reference_line,
            file_id, file_type, source, city, is_official
        )
        VALUES
        (
            1, 'official with line', 1000, 10,
            ST_SetSRID(ST_MakeLine(ST_MakePoint(112, 37), ST_MakePoint(112.01, 37.01)), 4326),
            'official.gpx', 'gpx', 'file_upload', 'taiyuan', true
        ),
        (
            1, 'private with line', 2000, 20,
            ST_SetSRID(ST_MakeLine(ST_MakePoint(113, 38), ST_MakePoint(113.01, 38.01)), 4326),
            'private.gpx', 'gpx', 'file_upload', 'taiyuan', false
        ),
        (
            1, 'official without line', 3000, 30,
            NULL,
            'null.gpx', 'gpx', 'file_upload', 'taiyuan', true
        )
        """
    ))


def test_route_versions_migration_backfills_official_visibility_and_skips_null_lines(pg_engine):
    """真实跑 Batch 1 migration：官方路线变 public，空 reference_line 不造假版本。"""
    migration = importlib.import_module("migrations.versions.20260618_route_versions")
    with pg_engine.begin() as conn:
        _create_legacy_route_books(conn)
        context = MigrationContext.configure(conn)
        operations = Operations(context)
        with patch.object(migration, "op", operations):
            migration.upgrade()

        rows = conn.execute(text(
            """
            SELECT
                rb.name,
                rb.is_official,
                rb.reference_line IS NOT NULL AS has_line,
                rb.visibility,
                rb.publish_status,
                rb.current_version_id,
                rv.id AS version_id,
                rv.version_no,
                rv.status,
                rv.navigation_status
            FROM route_books rb
            LEFT JOIN route_versions rv ON rv.route_book_id = rb.id
            ORDER BY rb.id
            """
        )).mappings().all()

        assert [row["name"] for row in rows] == [
            "official with line",
            "private with line",
            "official without line",
        ]
        assert rows[0]["visibility"] == "public"
        assert rows[0]["publish_status"] == "published"
        assert rows[0]["current_version_id"] == rows[0]["version_id"]
        assert rows[0]["version_no"] == 1
        assert rows[0]["status"] == "current"
        assert rows[0]["navigation_status"] == "ready"
        assert rows[1]["visibility"] == "private"
        assert rows[1]["publish_status"] == "draft"
        assert rows[1]["current_version_id"] == rows[1]["version_id"]
        assert rows[1]["version_no"] == 1
        assert rows[2]["has_line"] is False
        assert rows[2]["visibility"] == "public"
        assert rows[2]["publish_status"] == "published"
        assert rows[2]["current_version_id"] is None
        assert rows[2]["version_id"] is None

        official_bad_count = conn.execute(text(
            """
            SELECT count(*)
            FROM route_books
            WHERE is_official = true
              AND (visibility <> 'public' OR publish_status <> 'published')
            """
        )).scalar()
        null_line_version_count = conn.execute(text(
            """
            SELECT count(*)
            FROM route_books rb
            JOIN route_versions rv ON rv.route_book_id = rb.id
            WHERE rb.reference_line IS NULL
            """
        )).scalar()
        assert official_bad_count == 0
        assert null_line_version_count == 0
        constraints = {
            row[0]
            for row in conn.execute(text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid IN ('route_books'::regclass, 'route_versions'::regclass)
                """
            ))
        }
        assert {
            "ck_route_books_visibility",
            "ck_route_books_publish_status",
            "ck_route_versions_version_no",
            "ck_route_versions_status",
            "ck_route_versions_navigation_status",
            "ck_route_versions_geometry_source",
            "fk_route_books_current_version_id",
            "route_versions_route_book_id_fkey",
            "uq_route_versions_route_book_version",
            "uq_route_versions_id_route_book",
        } <= constraints


def test_route_guides_provenance_migration_backfills_hash_without_touching_content(pg_engine):
    """真实跑 Batch 2 migration：只补来源标签，不改 guide 正文。"""
    migration = importlib.import_module("migrations.versions.20260618_route_guides_provenance")
    content_md = "# 老路线\n\n这段正文不能被迁移改写。\n"
    with pg_engine.begin() as conn:
        conn.execute(text("CREATE TABLE route_books (id INTEGER PRIMARY KEY, current_version_id INTEGER)"))
        conn.execute(text(
            """
            CREATE TABLE route_versions (
                id INTEGER PRIMARY KEY,
                route_book_id INTEGER NOT NULL,
                UNIQUE(id, route_book_id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE route_guides (
                id INTEGER PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                route_book_id INTEGER,
                content_md TEXT NOT NULL
            )
            """
        ))
        conn.execute(text("INSERT INTO route_books (id, current_version_id) VALUES (1, 10)"))
        conn.execute(text("INSERT INTO route_versions (id, route_book_id) VALUES (10, 1)"))
        conn.execute(
            text("INSERT INTO route_guides (id, name, route_book_id, content_md) VALUES (1, '老路线', 1, :content_md)"),
            {"content_md": content_md},
        )

        context = MigrationContext.configure(conn)
        operations = Operations(context)
        with patch.object(migration, "op", operations):
            migration.upgrade()

        row = conn.execute(text("SELECT * FROM route_guides WHERE id = 1")).mappings().one()
        assert row["content_md"] == content_md
        assert row["content_hash"] == hashlib.sha256(content_md.encode("utf-8")).hexdigest()
        assert row["content_origin"] == "legacy_import"
        assert row["imported_at"] is None
        assert row["source_ref"] is None
        assert row["source_route_version_id"] == 10

        with pytest.raises(SQLAlchemyError):
            # 非法枚举检查放进 SAVEPOINT：失败是预期结果，不能污染外层测试事务。
            with conn.begin_nested():
                conn.execute(text("UPDATE route_guides SET content_origin = 'manual_admin' WHERE id = 1"))
