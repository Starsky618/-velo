"""route composition dry-run 测试——像把环西山正骑的三段装配单先在测试仓库里排练。"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
    RouteSegmentWriterError,
    add_route_custom_geometry,
    add_route_segment_clip,
)
from app.segment.models import Segment
from app.user.models import User


FORBIDDEN_EMPTY_TABLES = (
    "route_concept_candidates",
    "segment_concept_candidates",
    "collection_concept_candidates",
    "route_collection_candidates",
    "segment_collection_candidates",
    "route_segment_candidates",
    "collection_route_candidates",
    "collection_segment_candidates",
    "evidence_items",
    "segment_submissions",
)

ROUTE_WKT = "LINESTRING(112.45 37.75, 112.40 37.78, 112.35 37.82, 112.42 37.86)"
ENTRY_WKT = "LINESTRING(112.45 37.75, 112.40 37.78)"
HENGLING_WKT = "LINESTRING(112.40 37.78, 112.35 37.82)"
EXIT_WKT = "LINESTRING(112.35 37.82, 112.42 37.86)"


def _db_url() -> str:
    """读取明确传入的测试库地址；没有地址就跳过，避免误碰真实库。"""
    url = os.getenv("VELO_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("设置 VELO_TEST_DATABASE_URL 或 DATABASE_URL 后才运行 route composition PG dry-run")
    return url


@pytest.fixture()
def pg_engine():
    """每个测试单独建临时 schema；测完整层丢掉，不把 dry-run 数据留在库里。"""
    base_engine = create_engine(_db_url(), pool_pre_ping=True)
    schema_name = f"route_segment_seed_{uuid.uuid4().hex}"
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
    _create_route_composition_tables(pg_engine)
    return sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)


@pytest.fixture()
def route_composition_db(pg_session_factory):
    db = pg_session_factory()
    try:
        seed = _seed_route_composition_objects(db)
        db.flush()
        yield db, seed
    finally:
        db.rollback()
        db.close()


def test_xishan_route_composition_seed_dry_run_creates_only_overlay_rows(
    route_composition_db, monkeypatch
):
    db, seed = route_composition_db

    def fail_commit():
        raise AssertionError("route_segment_writer must not commit")

    monkeypatch.setattr(db, "commit", fail_commit)
    route_book_before = _geometry_text(db, "route_books", "reference_line", seed["route_book_id"])
    route_version_before = _geometry_text(
        db,
        "route_versions",
        "reference_line_snapshot",
        seed["route_version_id"],
    )
    segment_before = _geometry_text(db, "segments", "reference_line", seed["segment_id"])
    segment_efforts_before = _table_snapshot(db, "segment_efforts")
    guide_before = _route_guides_snapshot(db)
    content_routes_before = _content_routes_snapshot()

    entry = add_route_custom_geometry(
        db,
        route_book_id=seed["route_book_id"],
        route_version_id=seed["route_version_id"],
        seq=1,
        component_geometry=ENTRY_WKT,
        source_kind="manual_curated",
        membership_status="active",
        accepted_judgment_run_id=seed["route_judgment_id"],
    )
    hengling = add_route_segment_clip(
        db,
        route_book_id=seed["route_book_id"],
        route_version_id=seed["route_version_id"],
        seq=2,
        segment_id=seed["segment_id"],
        component_geometry=HENGLING_WKT,
        direction="forward",
        start_fraction=None,
        end_fraction=None,
        source_kind="manual_curated",
        membership_status="active",
        accepted_judgment_run_id=seed["route_judgment_id"],
    )
    exit_ = add_route_custom_geometry(
        db,
        route_book_id=seed["route_book_id"],
        route_version_id=seed["route_version_id"],
        seq=3,
        component_geometry=EXIT_WKT,
        source_kind="manual_curated",
        membership_status="active",
        accepted_judgment_run_id=seed["route_judgment_id"],
    )

    assert [entry.seq, hengling.seq, exit_.seq] == [1, 2, 3]
    rows = _route_segment_rows(db, route_version_id=seed["route_version_id"])
    assert [(row.seq, row.component_type) for row in rows] == [
        (1, "custom_geometry"),
        (2, "segment_clip"),
        (3, "custom_geometry"),
    ]
    assert all(row.route_line_hash == seed["route_line_hash"] for row in rows)
    assert rows[1].segment_id == seed["segment_id"]
    assert rows[1].segment_geometry_hash == seed["segment_geometry_hash"]
    assert all(row.component_geometry_hash for row in rows)
    assert all(row.source_kind == "manual_curated" for row in rows)
    assert all(row.membership_status == "active" for row in rows)
    assert all(row.srid_ok is True for row in rows)
    assert all(row.type_ok is True for row in rows)
    assert all(row.valid_ok is True for row in rows)

    assert _geometry_text(db, "route_books", "reference_line", seed["route_book_id"]) == route_book_before
    assert (
        _geometry_text(db, "route_versions", "reference_line_snapshot", seed["route_version_id"])
        == route_version_before
    )
    assert _geometry_text(db, "segments", "reference_line", seed["segment_id"]) == segment_before
    assert _table_snapshot(db, "segment_efforts") == segment_efforts_before
    assert _route_guides_snapshot(db) == guide_before
    assert _content_routes_snapshot() == content_routes_before
    _assert_forbidden_tables_empty(db)


def test_route_composition_seed_rejects_duplicate_active_seq(route_composition_db):
    db, seed = route_composition_db
    add_route_custom_geometry(
        db,
        route_book_id=seed["route_book_id"],
        route_version_id=seed["route_version_id"],
        seq=1,
        component_geometry=ENTRY_WKT,
        accepted_judgment_run_id=seed["route_judgment_id"],
    )

    with pytest.raises(RouteSegmentWriterError, match="active seq"):
        add_route_custom_geometry(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=1,
            component_geometry=EXIT_WKT,
            accepted_judgment_run_id=seed["route_judgment_id"],
        )


@pytest.mark.parametrize("history_status", ["deprecated", "superseded"])
def test_route_composition_seed_allows_history_before_new_active_seq(
    route_composition_db, history_status
):
    db, seed = route_composition_db
    add_route_custom_geometry(
        db,
        route_book_id=seed["route_book_id"],
        route_version_id=seed["route_version_id"],
        seq=5,
        component_geometry=ENTRY_WKT,
        membership_status=history_status,
        accepted_judgment_run_id=seed["route_judgment_id"],
    )
    active = add_route_custom_geometry(
        db,
        route_book_id=seed["route_book_id"],
        route_version_id=seed["route_version_id"],
        seq=5,
        component_geometry=EXIT_WKT,
        membership_status="active",
        accepted_judgment_run_id=seed["route_judgment_id"],
    )

    rows = _route_segment_rows(db, route_version_id=seed["route_version_id"])
    assert [(row.seq, row.membership_status) for row in rows] == [(5, history_status), (5, "active")]
    assert active.membership_status == "active"


def test_route_composition_seed_rejects_raw_segment(route_composition_db):
    db, seed = route_composition_db
    with pytest.raises(RouteSegmentWriterError, match="route_cognition_segments"):
        add_route_segment_clip(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=2,
            segment_id=seed["raw_segment_id"],
            component_geometry=HENGLING_WKT,
            direction="forward",
            accepted_judgment_run_id=seed["route_judgment_id"],
        )


def test_route_composition_seed_rejects_custom_geometry_with_segment_id(route_composition_db):
    db, seed = route_composition_db
    with pytest.raises(RouteSegmentWriterError, match="segment_id"):
        add_route_custom_geometry(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=1,
            component_geometry=ENTRY_WKT,
            segment_id=seed["segment_id"],
            accepted_judgment_run_id=seed["route_judgment_id"],
        )


def test_route_composition_seed_rejects_segment_clip_without_component_geometry(route_composition_db):
    db, seed = route_composition_db
    with pytest.raises(RouteSegmentWriterError, match="component_geometry"):
        add_route_segment_clip(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=2,
            segment_id=seed["segment_id"],
            component_geometry=None,
            direction="forward",
            accepted_judgment_run_id=seed["route_judgment_id"],
        )


def test_route_composition_seed_rejects_custom_geometry_without_component_geometry(route_composition_db):
    db, seed = route_composition_db
    with pytest.raises(RouteSegmentWriterError, match="component_geometry"):
        add_route_custom_geometry(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=1,
            component_geometry="",
            accepted_judgment_run_id=seed["route_judgment_id"],
        )


def test_route_composition_seed_rejects_point_geometry(route_composition_db):
    db, seed = route_composition_db
    with pytest.raises(RouteSegmentWriterError, match="line"):
        add_route_custom_geometry(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=1,
            component_geometry="POINT(112.40 37.78)",
            accepted_judgment_run_id=seed["route_judgment_id"],
        )


def test_route_composition_seed_rejects_non_human_judgment(route_composition_db):
    db, seed = route_composition_db
    with pytest.raises(RouteSegmentWriterError):
        add_route_custom_geometry(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=1,
            component_geometry=ENTRY_WKT,
            accepted_judgment_run_id=seed["agent_judgment_id"],
        )


def test_route_composition_seed_rejects_candidate_accepted_source_kind(route_composition_db):
    db, seed = route_composition_db
    with pytest.raises(RouteSegmentWriterError, match="source_kind"):
        add_route_custom_geometry(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=1,
            component_geometry=ENTRY_WKT,
            source_kind="candidate_accepted",
            accepted_judgment_run_id=seed["route_judgment_id"],
        )


def test_route_composition_seed_rejects_legacy_import_without_source(route_composition_db):
    db, seed = route_composition_db
    with pytest.raises(RouteSegmentWriterError, match="legacy_import"):
        add_route_custom_geometry(
            db,
            route_book_id=seed["route_book_id"],
            route_version_id=seed["route_version_id"],
            seq=1,
            component_geometry=ENTRY_WKT,
            source_kind="legacy_import",
            accepted_judgment_run_id=seed["route_judgment_id"],
        )


def _create_route_composition_tables(pg_engine) -> None:
    User.__table__.create(bind=pg_engine, checkfirst=False)
    Activity.__table__.create(bind=pg_engine, checkfirst=False)
    Segment.__table__.create(bind=pg_engine, checkfirst=False)
    RouteBook.__table__.create(bind=pg_engine, checkfirst=False)
    RouteVersion.__table__.create(bind=pg_engine, checkfirst=False)
    JudgmentRun.__table__.create(bind=pg_engine, checkfirst=False)
    SegmentGeometrySource.__table__.create(bind=pg_engine, checkfirst=False)
    RouteCognitionSegment.__table__.create(bind=pg_engine, checkfirst=False)
    RouteSegment.__table__.create(bind=pg_engine, checkfirst=False)
    with pg_engine.begin() as conn:
        conn.execute(text("CREATE TABLE route_guides (id SERIAL PRIMARY KEY, content_md TEXT NOT NULL)"))
        conn.execute(text("CREATE TABLE segment_efforts (id SERIAL PRIMARY KEY, segment_id INTEGER NOT NULL)"))
        for table_name in FORBIDDEN_EMPTY_TABLES:
            conn.execute(text(f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY)"))


def _seed_route_composition_objects(db) -> dict[str, int | str]:
    user = User(openid=f"route_segment_seed_{uuid.uuid4().hex}", nickname="route segment seed")
    db.add(user)
    db.flush()

    route_book = RouteBook(
        creator_id=user.id,
        name="环西山正骑",
        distance=25000.0,
        reference_line=WKTElement(ROUTE_WKT, srid=4326),
        source="manual_drawn",
        city="taiyuan",
        visibility="private",
        publish_status="draft",
    )
    db.add(route_book)
    db.flush()

    route_line_hash = hash_segment_geometry_wkt(ROUTE_WKT)
    route_version = RouteVersion(
        route_book_id=route_book.id,
        version_no=1,
        geometry_source="manual_drawn",
        reference_line_snapshot=WKTElement(ROUTE_WKT, srid=4326),
        line_hash=route_line_hash,
        distance=25000.0,
    )
    db.add(route_version)
    db.flush()

    hengling = Segment(
        name="横岭",
        distance=4200.0,
        start_lat=37.78,
        start_lon=112.40,
        end_lat=37.82,
        end_lon=112.35,
        reference_line=WKTElement(HENGLING_WKT, srid=4326),
        city="taiyuan",
    )
    raw_segment = Segment(
        name="未白名单裸 segment",
        distance=900.0,
        start_lat=37.70,
        start_lon=112.50,
        end_lat=37.71,
        end_lon=112.51,
        reference_line=WKTElement("LINESTRING(112.50 37.70, 112.51 37.71)", srid=4326),
        city="taiyuan",
    )
    db.add_all([hengling, raw_segment])
    db.flush()

    route_judgment = JudgmentRun(
        run_type="human_review",
        status="succeeded",
        trigger_type="test",
        route_book_id=route_book.id,
        route_version_id=route_version.id,
        confidence_state="human_accepted",
        created_by_user_id=user.id,
    )
    segment_judgment = JudgmentRun(
        run_type="human_review",
        status="succeeded",
        trigger_type="test",
        segment_id=hengling.id,
        confidence_state="stable",
        created_by_user_id=user.id,
    )
    agent_judgment = JudgmentRun(
        run_type="semantic_agent",
        status="succeeded",
        trigger_type="test",
        route_book_id=route_book.id,
        route_version_id=route_version.id,
        confidence_state="stable",
        created_by_user_id=user.id,
    )
    db.add_all([route_judgment, segment_judgment, agent_judgment])
    db.flush()

    segment_geometry_hash = hash_segment_geometry_wkt(HENGLING_WKT)
    db.add(
        RouteCognitionSegment(
            segment_id=hengling.id,
            primary_geometry_source_id=None,
            review_basis="legacy_reviewed",
            eligibility_status="active",
            geometry_hash=segment_geometry_hash,
            normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
            accepted_judgment_run_id=segment_judgment.id,
            reviewed_by=user.id,
            reviewed_at=datetime.now(timezone.utc),
        )
    )
    db.execute(text("INSERT INTO route_guides (content_md) VALUES ('original guide')"))
    db.execute(text("INSERT INTO segment_efforts (segment_id) VALUES (:segment_id)"), {"segment_id": hengling.id})
    db.flush()

    return {
        "route_book_id": route_book.id,
        "route_version_id": route_version.id,
        "route_line_hash": route_line_hash,
        "segment_id": hengling.id,
        "raw_segment_id": raw_segment.id,
        "segment_geometry_hash": segment_geometry_hash,
        "route_judgment_id": route_judgment.id,
        "agent_judgment_id": agent_judgment.id,
    }


def _route_segment_rows(db, *, route_version_id: int):
    return db.execute(
        text(
            """
            SELECT
                seq,
                component_type,
                segment_id,
                segment_geometry_hash,
                component_geometry_hash,
                route_line_hash,
                source_kind,
                membership_status,
                ST_SRID(component_geometry) = 4326 AS srid_ok,
                upper(replace(GeometryType(component_geometry), 'ST_', '')) IN
                    ('LINESTRING', 'MULTILINESTRING') AS type_ok,
                ST_IsValid(component_geometry) AS valid_ok
            FROM route_segments
            WHERE route_version_id = :route_version_id
            ORDER BY seq, id
            """
        ),
        {"route_version_id": route_version_id},
    ).all()


def _geometry_text(db, table_name: str, column_name: str, row_id: int) -> str:
    return db.execute(
        text(f"SELECT ST_AsText({column_name}) FROM {table_name} WHERE id = :row_id"),
        {"row_id": row_id},
    ).scalar_one()


def _table_snapshot(db, table_name: str) -> list[tuple]:
    return [tuple(row) for row in db.execute(text(f"SELECT * FROM {table_name} ORDER BY id")).all()]


def _route_guides_snapshot(db) -> list[tuple[int, str]]:
    return [
        (row.id, row.content_md)
        for row in db.execute(text("SELECT id, content_md FROM route_guides ORDER BY id")).all()
    ]


def _content_routes_snapshot() -> set[str]:
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in Path("content/routes").glob("**/*")
        if path.is_file()
    }


def _assert_forbidden_tables_empty(db) -> None:
    for table_name in FORBIDDEN_EMPTY_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0
