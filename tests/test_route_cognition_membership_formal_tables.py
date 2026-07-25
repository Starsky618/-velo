"""路线认知 Step D 测试——路线和集合成员关系只能作为人工审过的正式档案进入系统。

这些表像“目录索引卡”：它们说明某条路线包含哪些 segment、某个 collection 收哪些路线
或 segment；但它们不改路线本身的图纸，路线几何真相仍在 route_versions。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError


MIGRATION = Path("migrations/versions/20260618_membership_formal.py")


def _check_sql(table, name: str) -> str:
    checks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == name
    ]
    assert checks
    return str(checks[0].sqltext)


def _foreign_key(table, name: str) -> ForeignKeyConstraint:
    fks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name == name
    ]
    assert fks
    return fks[0]


def _unique_columns(table, name: str) -> list[str]:
    uniques = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name == name
    ]
    assert uniques
    return [column.name for column in uniques[0].columns]


def _index(table, name: str) -> Index:
    indexes = [index for index in table.indexes if index.name == name]
    assert indexes
    return indexes[0]


def test_step_d_models_declare_membership_tables_and_hard_gates():
    from app.route_cognition.models import (
        CollectionRoute,
        CollectionSegment,
        RouteCognitionSegment,
        RouteSegment,
    )

    assert _unique_columns(
        RouteCognitionSegment.__table__,
        "uq_route_cognition_segments_segment_geometry_hash",
    ) == ["segment_id", "geometry_hash"]

    route_table = RouteSegment.__table__
    assert {
        "route_book_id",
        "route_version_id",
        "route_line_hash",
        "seq",
        "component_type",
        "segment_id",
        "segment_geometry_hash",
        "component_geometry",
        "component_geometry_hash",
        "direction",
        "start_fraction",
        "end_fraction",
        "membership_status",
        "source_kind",
        "source_ref",
        "accepted_judgment_run_id",
        "accepted_judgment_run_type",
        "display_priority",
        "reason_summary",
        "metadata_json",
        "created_by",
    } <= set(route_table.c.keys())
    assert isinstance(route_table.c.metadata_json.type, JSONB)
    assert "candidate_accepted" not in _check_sql(route_table, "ck_route_segments_source_kind")
    assert "legacy_import" in _check_sql(route_table, "ck_route_segments_legacy_source")
    assert "segment_clip" in _check_sql(route_table, "ck_route_segments_component_contract")
    assert "custom_geometry" in _check_sql(route_table, "ck_route_segments_component_contract")
    assert "start_fraction < end_fraction" in _check_sql(route_table, "ck_route_segments_fraction_range")
    assert "ST_IsValid" in _check_sql(route_table, "ck_route_segments_component_geometry_valid_type")
    assert _foreign_key(route_table, "fk_route_segments_segment").elements[0].column.table.name == "route_cognition_segments"
    assert [element.parent.name for element in _foreign_key(route_table, "fk_route_segments_segment_hash").elements] == [
        "segment_id",
        "segment_geometry_hash",
    ]
    assert _foreign_key(route_table, "fk_route_segments_created_by").ondelete == "SET NULL"
    assert str(_index(route_table, "uq_route_segments_active_seq").dialect_options["postgresql"]["where"]) == (
        "membership_status = 'active'"
    )
    assert _index(route_table, "idx_route_segments_geom").dialect_options["postgresql"]["using"] == "gist"

    collection_route_table = CollectionRoute.__table__
    assert {
        "collection_id",
        "route_book_id",
        "reviewed_route_version_id",
        "reviewed_route_line_hash",
        "role",
        "seq",
        "importance",
        "membership_status",
        "source_kind",
        "source_ref",
        "accepted_judgment_run_id",
        "accepted_judgment_run_type",
        "display_priority",
        "reason_summary",
        "metadata_json",
        "created_by",
    } <= set(collection_route_table.c.keys())
    assert _foreign_key(collection_route_table, "fk_collection_routes_collection").elements[0].column.table.name == "route_collections"
    assert _foreign_key(collection_route_table, "fk_collection_routes_route_book").elements[0].column.table.name == "route_books"
    assert "candidate_accepted" not in _check_sql(collection_route_table, "ck_collection_routes_source_kind")
    assert str(_index(collection_route_table, "uq_collection_routes_active_route").dialect_options["postgresql"]["where"]) == (
        "membership_status = 'active'"
    )
    assert "seq IS NOT NULL" in str(
        _index(collection_route_table, "uq_collection_routes_active_seq").dialect_options["postgresql"]["where"]
    )

    collection_segment_table = CollectionSegment.__table__
    assert _foreign_key(collection_segment_table, "fk_collection_segments_segment").elements[0].column.table.name == (
        "route_cognition_segments"
    )
    assert [element.parent.name for element in _foreign_key(collection_segment_table, "fk_collection_segments_segment_hash").elements] == [
        "segment_id",
        "segment_geometry_hash",
    ]
    assert "core" in _check_sql(collection_segment_table, "ck_collection_segments_role")
    assert "candidate_accepted" not in _check_sql(collection_segment_table, "ck_collection_segments_source_kind")
    assert str(_index(collection_segment_table, "uq_collection_segments_active_segment").dialect_options["postgresql"]["where"]) == (
        "membership_status = 'active'"
    )


def test_step_d_migration_declares_only_formal_membership_tables():
    assert MIGRATION.exists()
    migration_text = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "20260618_membership_formal"' in migration_text
    assert 'down_revision = "20260618_concept_formal_links"' in migration_text
    assert "uq_route_cognition_segments_segment_geometry_hash" in migration_text
    assert '"route_segments"' in migration_text
    assert '"collection_routes"' in migration_text
    assert '"collection_segments"' in migration_text
    assert "candidate_accepted" not in migration_text
    for forbidden in (
        "route_segment_candidates",
        "collection_route_candidates",
        "collection_segment_candidates",
        "segment_submissions",
        "APIRouter",
        "app/admin",
        "admin/router",
        "content/routes",
    ):
        assert forbidden not in migration_text

    module = _load_migration_module()
    assert hasattr(module, "upgrade")
    assert hasattr(module, "downgrade")


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("membership_formal_migration", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def membership_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_membership_tables(db)
    _create_membership_contract_tables(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_membership_tables(db)


def test_route_segments_segment_clip_requires_component_geometry(db, membership_sqlite_tables):
    _seed_membership_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_segment(db, component_geometry=None)


def test_route_segments_segment_clip_rejects_wrong_segment_hash(db, membership_sqlite_tables):
    _seed_membership_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_segment(db, segment_geometry_hash="wrong-segment-hash")


def test_route_segments_custom_geometry_forbids_segment_id(db, membership_sqlite_tables):
    _seed_membership_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_segment(
            db,
            component_type="custom_geometry",
            segment_id=1,
            segment_geometry_hash=None,
            direction=None,
        )


def test_route_segments_custom_geometry_requires_geometry(db, membership_sqlite_tables):
    _seed_membership_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_segment(
            db,
            component_type="custom_geometry",
            segment_id=None,
            segment_geometry_hash=None,
            component_geometry=None,
            direction=None,
        )


def test_route_segments_invalid_geometry_type_point_fails(db, membership_sqlite_tables):
    _seed_membership_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_segment(db, component_geometry="POINT(0 0)")


def test_route_segments_route_version_book_mismatch_fails(db, membership_sqlite_tables):
    _seed_membership_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_segment(db, route_book_id=2, route_version_id=1)


def test_route_segments_active_duplicate_seq_fails(db, membership_sqlite_tables):
    _seed_membership_base(db)
    _insert_route_segment(db, id=1)

    with pytest.raises(IntegrityError):
        _insert_route_segment(db, id=2)


def test_route_segments_deprecated_history_allows_new_active(db, membership_sqlite_tables):
    _seed_membership_base(db)
    _insert_route_segment(db, id=1, membership_status="deprecated")
    _insert_route_segment(db, id=2, membership_status="active")

    assert db.execute(text("SELECT count(*) FROM route_segments")).scalar_one() == 2


def test_collection_routes_valid_insert(db, membership_sqlite_tables):
    _seed_membership_base(db)
    _insert_collection_route(db)

    assert db.execute(text("SELECT count(*) FROM collection_routes")).scalar_one() == 1


def test_collection_routes_active_duplicate_route_fails(db, membership_sqlite_tables):
    _seed_membership_base(db)
    _insert_collection_route(db, id=1)

    with pytest.raises(IntegrityError):
        _insert_collection_route(db, id=2, seq=2)


def test_collection_routes_active_duplicate_seq_fails(db, membership_sqlite_tables):
    _seed_membership_base(db)
    _insert_collection_route(db, id=1)

    with pytest.raises(IntegrityError):
        _insert_collection_route(db, id=2, route_book_id=2, reviewed_route_version_id=2, reviewed_route_line_hash="route-hash-b")


def test_collection_segments_valid_insert(db, membership_sqlite_tables):
    _seed_membership_base(db)
    _insert_collection_segment(db)

    assert db.execute(text("SELECT count(*) FROM collection_segments")).scalar_one() == 1


def test_collection_segments_raw_segment_fails(db, membership_sqlite_tables):
    _seed_membership_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection_segment(db, segment_id=2, segment_geometry_hash="raw-segment-hash")


def test_collection_segments_wrong_segment_hash_fails(db, membership_sqlite_tables):
    _seed_membership_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection_segment(db, segment_geometry_hash="wrong-segment-hash")


def test_collection_segments_active_duplicate_segment_fails(db, membership_sqlite_tables):
    _seed_membership_base(db)
    _insert_collection_segment(db, id=1)

    with pytest.raises(IntegrityError):
        _insert_collection_segment(db, id=2, seq=2)


@pytest.mark.parametrize(
    "insert_fn",
    [
        "_insert_route_segment",
        "_insert_collection_route",
        "_insert_collection_segment",
    ],
)
def test_non_human_judgment_fails_for_all_three(db, membership_sqlite_tables, insert_fn):
    _seed_membership_base(db)

    with pytest.raises(IntegrityError):
        globals()[insert_fn](db, accepted_judgment_run_id=2)


@pytest.mark.parametrize(
    "insert_fn",
    [
        "_insert_route_segment",
        "_insert_collection_route",
        "_insert_collection_segment",
    ],
)
def test_legacy_import_without_source_ref_or_reason_summary_fails(db, membership_sqlite_tables, insert_fn):
    _seed_membership_base(db)

    with pytest.raises(IntegrityError):
        globals()[insert_fn](db, source_kind="legacy_import", source_ref=None, reason_summary=None)


def test_no_candidate_tables_or_forbidden_surfaces_added_by_step_d_sqlite_contract(db, membership_sqlite_tables):
    for table_name in (
        "route_segment_candidates",
        "collection_route_candidates",
        "collection_segment_candidates",
        "segment_submissions",
    ):
        row = db.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
            {"table_name": table_name},
        ).first()
        assert row is None


def _create_membership_contract_tables(db) -> None:
    db.execute(text("CREATE TABLE judgment_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_type TEXT NOT NULL)"))
    db.execute(text("CREATE UNIQUE INDEX uq_judgment_runs_id_run_type ON judgment_runs(id, run_type)"))
    db.execute(text("CREATE TABLE route_collections (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(
        text(
            """
            CREATE TABLE route_cognition_segments (
                segment_id INTEGER PRIMARY KEY,
                geometry_hash TEXT NOT NULL,
                UNIQUE(segment_id, geometry_hash),
                FOREIGN KEY(segment_id) REFERENCES segments(id)
            )
            """
        )
    )
    _create_route_segments_sqlite_table(db)
    _create_collection_routes_sqlite_table(db)
    _create_collection_segments_sqlite_table(db)


def _common_membership_columns_sql() -> str:
    return """
        membership_status TEXT NOT NULL DEFAULT 'active',
        source_kind TEXT NOT NULL,
        source_ref TEXT,
        accepted_judgment_run_id INTEGER NOT NULL,
        accepted_judgment_run_type TEXT NOT NULL DEFAULT 'human_review',
        display_priority INTEGER,
        reason_summary TEXT,
        metadata_json TEXT,
        created_by INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CHECK (membership_status IN ('active', 'deprecated', 'superseded')),
        CHECK (source_kind IN ('manual_curated', 'legacy_import')),
        CHECK (accepted_judgment_run_type = 'human_review'),
        CHECK (
            source_kind <> 'legacy_import'
            OR source_ref IS NOT NULL
            OR reason_summary IS NOT NULL
        ),
        CHECK (display_priority IS NULL OR (display_priority >= 0 AND display_priority <= 100)),
        FOREIGN KEY(accepted_judgment_run_id, accepted_judgment_run_type)
            REFERENCES judgment_runs(id, run_type),
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    """


def _create_route_segments_sqlite_table(db) -> None:
    db.execute(
        text(
            f"""
            CREATE TABLE route_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_book_id INTEGER NOT NULL,
                route_version_id INTEGER NOT NULL,
                route_line_hash TEXT NOT NULL,
                seq INTEGER NOT NULL,
                component_type TEXT NOT NULL,
                segment_id INTEGER,
                segment_geometry_hash TEXT,
                component_geometry TEXT,
                component_geometry_hash TEXT NOT NULL,
                direction TEXT,
                start_fraction REAL,
                end_fraction REAL,
                {_common_membership_columns_sql()},
                CHECK (seq >= 1),
                CHECK (component_type IN ('segment_clip', 'custom_geometry')),
                CHECK (
                    (
                        component_type = 'segment_clip'
                        AND segment_id IS NOT NULL
                        AND segment_geometry_hash IS NOT NULL
                        AND component_geometry IS NOT NULL
                        AND component_geometry_hash IS NOT NULL
                        AND direction IN ('forward', 'reverse')
                    )
                    OR
                    (
                        component_type = 'custom_geometry'
                        AND segment_id IS NULL
                        AND segment_geometry_hash IS NULL
                        AND component_geometry IS NOT NULL
                        AND component_geometry_hash IS NOT NULL
                        AND direction IS NULL
                    )
                ),
                CHECK (
                    (start_fraction IS NULL AND end_fraction IS NULL)
                    OR (
                        component_type = 'segment_clip'
                        AND start_fraction IS NOT NULL
                        AND end_fraction IS NOT NULL
                        AND start_fraction >= 0
                        AND end_fraction <= 1
                        AND start_fraction < end_fraction
                    )
                ),
                CHECK (
                    component_geometry LIKE 'LINESTRING%'
                    OR component_geometry LIKE 'MULTILINESTRING%'
                ),
                FOREIGN KEY(route_book_id) REFERENCES route_books(id),
                FOREIGN KEY(route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id),
                FOREIGN KEY(segment_id) REFERENCES route_cognition_segments(segment_id),
                FOREIGN KEY(segment_id, segment_geometry_hash)
                    REFERENCES route_cognition_segments(segment_id, geometry_hash)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_route_segments_active_seq
            ON route_segments(route_book_id, route_version_id, seq)
            WHERE membership_status = 'active'
            """
        )
    )


def _create_collection_routes_sqlite_table(db) -> None:
    db.execute(
        text(
            f"""
            CREATE TABLE collection_routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                route_book_id INTEGER NOT NULL,
                reviewed_route_version_id INTEGER NOT NULL,
                reviewed_route_line_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                seq INTEGER,
                importance INTEGER,
                {_common_membership_columns_sql()},
                CHECK (role IN ('primary', 'featured', 'alternate', 'connector', 'reference', 'supporting')),
                CHECK (seq IS NULL OR seq >= 1),
                CHECK (importance IS NULL OR (importance >= 0 AND importance <= 100)),
                FOREIGN KEY(collection_id) REFERENCES route_collections(id),
                FOREIGN KEY(route_book_id) REFERENCES route_books(id),
                FOREIGN KEY(reviewed_route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_collection_routes_active_route
            ON collection_routes(collection_id, route_book_id)
            WHERE membership_status = 'active'
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_collection_routes_active_seq
            ON collection_routes(collection_id, seq)
            WHERE membership_status = 'active' AND seq IS NOT NULL
            """
        )
    )


def _create_collection_segments_sqlite_table(db) -> None:
    db.execute(
        text(
            f"""
            CREATE TABLE collection_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                segment_geometry_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                seq INTEGER,
                importance INTEGER,
                {_common_membership_columns_sql()},
                CHECK (role IN ('core', 'connector', 'landmark', 'risk_area', 'training_interval', 'supporting')),
                CHECK (seq IS NULL OR seq >= 1),
                CHECK (importance IS NULL OR (importance >= 0 AND importance <= 100)),
                FOREIGN KEY(collection_id) REFERENCES route_collections(id),
                FOREIGN KEY(segment_id) REFERENCES route_cognition_segments(segment_id),
                FOREIGN KEY(segment_id, segment_geometry_hash)
                    REFERENCES route_cognition_segments(segment_id, geometry_hash)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_collection_segments_active_segment
            ON collection_segments(collection_id, segment_id)
            WHERE membership_status = 'active'
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_collection_segments_active_seq
            ON collection_segments(collection_id, seq)
            WHERE membership_status = 'active' AND seq IS NOT NULL
            """
        )
    )


def _seed_membership_base(db) -> None:
    db.execute(text("INSERT INTO users (id, openid, is_admin) VALUES (1, 'membership_user', 1)"))
    db.execute(text("INSERT INTO judgment_runs (id, run_type) VALUES (1, 'human_review'), (2, 'semantic_agent')"))
    db.execute(
        text(
            """
            INSERT INTO route_books (id, name, distance, reference_line, source, city)
            VALUES
              (1, 'Route A', 10000.0, 'LINESTRING(0 0, 1 1)', 'manual_drawn', 'taiyuan'),
              (2, 'Route B', 12000.0, 'LINESTRING(0 0, 2 2)', 'manual_drawn', 'taiyuan')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_versions (
                id, route_book_id, version_no, geometry_source, reference_line_snapshot,
                line_hash, distance
            )
            VALUES
              (1, 1, 1, 'manual_drawn', 'LINESTRING(0 0, 1 1)', 'route-hash-a', 10000.0),
              (2, 2, 1, 'manual_drawn', 'LINESTRING(0 0, 2 2)', 'route-hash-b', 12000.0)
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO segments (id, name, distance, start_lat, start_lon, end_lat, end_lon, reference_line)
            VALUES
              (1, 'Whitelisted Segment A', 1000.0, 37.8, 112.5, 37.9, 112.6, 'LINESTRING(0 0, 1 1)'),
              (2, 'Raw Segment', 1000.0, 37.8, 112.5, 37.9, 112.6, 'LINESTRING(0 0, 1 1)'),
              (3, 'Whitelisted Segment B', 1200.0, 37.8, 112.5, 37.9, 112.6, 'LINESTRING(0 0, 2 2)')
            """
        )
    )
    db.execute(text("INSERT INTO route_cognition_segments (segment_id, geometry_hash) VALUES (1, 'segment-hash-a'), (3, 'segment-hash-b')"))
    db.execute(text("INSERT INTO route_collections (id) VALUES (1), (2)"))


def _insert_route_segment(
    db,
    *,
    id: int = 1,
    route_book_id: int = 1,
    route_version_id: int = 1,
    route_line_hash: str = "route-hash-a",
    seq: int = 1,
    component_type: str = "segment_clip",
    segment_id: int | None = 1,
    segment_geometry_hash: str | None = "segment-hash-a",
    component_geometry: str | None = "LINESTRING(0 0, 1 1)",
    component_geometry_hash: str | None = "component-hash-a",
    direction: str | None = "forward",
    start_fraction: float | None = 0.0,
    end_fraction: float | None = 1.0,
    membership_status: str = "active",
    source_kind: str = "manual_curated",
    source_ref: str | None = None,
    accepted_judgment_run_id: int = 1,
    reason_summary: str | None = "Reviewed by schema-owner workflow.",
) -> None:
    db.execute(
        text(
            """
            INSERT INTO route_segments (
                id, route_book_id, route_version_id, route_line_hash, seq, component_type,
                segment_id, segment_geometry_hash, component_geometry, component_geometry_hash,
                direction, start_fraction, end_fraction, membership_status, source_kind,
                source_ref, accepted_judgment_run_id, reason_summary
            )
            VALUES (
                :id, :route_book_id, :route_version_id, :route_line_hash, :seq, :component_type,
                :segment_id, :segment_geometry_hash, :component_geometry, :component_geometry_hash,
                :direction, :start_fraction, :end_fraction, :membership_status, :source_kind,
                :source_ref, :accepted_judgment_run_id, :reason_summary
            )
            """
        ),
        locals() | {"db": None},
    )


def _insert_collection_route(
    db,
    *,
    id: int = 1,
    collection_id: int = 1,
    route_book_id: int = 1,
    reviewed_route_version_id: int = 1,
    reviewed_route_line_hash: str = "route-hash-a",
    role: str = "primary",
    seq: int | None = 1,
    importance: int | None = 80,
    membership_status: str = "active",
    source_kind: str = "manual_curated",
    source_ref: str | None = None,
    accepted_judgment_run_id: int = 1,
    reason_summary: str | None = "Reviewed by schema-owner workflow.",
) -> None:
    db.execute(
        text(
            """
            INSERT INTO collection_routes (
                id, collection_id, route_book_id, reviewed_route_version_id, reviewed_route_line_hash,
                role, seq, importance, membership_status, source_kind, source_ref,
                accepted_judgment_run_id, reason_summary
            )
            VALUES (
                :id, :collection_id, :route_book_id, :reviewed_route_version_id, :reviewed_route_line_hash,
                :role, :seq, :importance, :membership_status, :source_kind, :source_ref,
                :accepted_judgment_run_id, :reason_summary
            )
            """
        ),
        locals() | {"db": None},
    )


def _insert_collection_segment(
    db,
    *,
    id: int = 1,
    collection_id: int = 1,
    segment_id: int = 1,
    segment_geometry_hash: str = "segment-hash-a",
    role: str = "core",
    seq: int | None = 1,
    importance: int | None = 80,
    membership_status: str = "active",
    source_kind: str = "manual_curated",
    source_ref: str | None = None,
    accepted_judgment_run_id: int = 1,
    reason_summary: str | None = "Reviewed by schema-owner workflow.",
) -> None:
    db.execute(
        text(
            """
            INSERT INTO collection_segments (
                id, collection_id, segment_id, segment_geometry_hash, role, seq, importance,
                membership_status, source_kind, source_ref, accepted_judgment_run_id, reason_summary
            )
            VALUES (
                :id, :collection_id, :segment_id, :segment_geometry_hash, :role, :seq, :importance,
                :membership_status, :source_kind, :source_ref, :accepted_judgment_run_id, :reason_summary
            )
            """
        ),
        locals() | {"db": None},
    )


def _drop_membership_tables(db) -> None:
    for table_name in (
        "collection_segments",
        "collection_routes",
        "route_segments",
        "route_cognition_segments",
        "route_collections",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
