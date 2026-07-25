"""路线认知 Batch 7 测试——只给 route_collections 建一张“路线专题身份证”。"""

from __future__ import annotations

from pathlib import Path

import pytest
from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError


MIGRATION = Path("migrations/versions/20260618_route_collections.py")


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


def _unique_constraint_columns(table, name: str) -> list[str]:
    uniques = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name == name
    ]
    assert uniques
    return [column.name for column in uniques[0].columns]


def _index(table, name: str):
    indexes = [index for index in table.indexes if index.name == name]
    assert indexes
    return indexes[0]


def test_batch7_model_declares_route_collection_table_contract():
    from app.route_cognition.models import RouteCollection

    table = RouteCollection.__table__
    assert RouteCollection.__tablename__ == "route_collections"
    assert {
        "id",
        "name",
        "slug",
        "collection_type",
        "city",
        "visibility",
        "publish_status",
        "description_md",
        "cover_url",
        "geom",
        "center_lat",
        "center_lon",
        "source",
        "source_ref",
        "confidence",
        "stats_json",
        "metadata_json",
        "source_judgment_run_id",
        "created_by",
        "created_at",
        "updated_at",
    } <= set(table.c.keys())
    assert table.c.name.nullable is False
    assert table.c.slug.nullable is False
    assert table.c.city.nullable is False
    assert table.c.city.server_default.arg == "unknown"
    assert isinstance(table.c.stats_json.type, JSONB)
    assert isinstance(table.c.metadata_json.type, JSONB)
    assert isinstance(table.c.geom.type, Geometry)
    assert table.c.geom.type.geometry_type == "GEOMETRY"
    assert table.c.geom.type.srid == 4326
    assert table.c.geom.type.spatial_index is False


def test_batch7_model_declares_checks_fks_unique_and_indexes():
    from app.route_cognition.models import RouteCollection

    table = RouteCollection.__table__

    collection_type_sql = _check_sql(table, "ck_route_collections_collection_type")
    for value in (
        "area_system",
        "route_family",
        "race_route_family",
        "training_corridor",
        "theme_pack",
        "other",
    ):
        assert value in collection_type_sql

    visibility_sql = _check_sql(table, "ck_route_collections_visibility")
    assert "private" in visibility_sql
    assert "unlisted" in visibility_sql
    assert "public" in visibility_sql

    publish_status_sql = _check_sql(table, "ck_route_collections_publish_status")
    assert "draft" in publish_status_sql
    assert "published" in publish_status_sql
    assert "archived" in publish_status_sql

    source_sql = _check_sql(table, "ck_route_collections_source")
    assert "manual" in source_sql
    assert "imported" in source_sql
    assert "agent" not in source_sql

    slug_sql = _check_sql(table, "ck_route_collections_slug_format")
    assert "slug" in slug_sql
    assert "~" in slug_sql

    publication_sql = _check_sql(table, "ck_route_collections_publication_state")
    assert "visibility <> 'public'" in publication_sql
    assert "publish_status = 'published'" in publication_sql

    judgment_sql = _check_sql(table, "ck_route_collections_published_judgment")
    assert "publish_status <> 'published'" in judgment_sql
    assert "source_judgment_run_id IS NOT NULL" in judgment_sql

    import_sql = _check_sql(table, "ck_route_collections_import_source_ref")
    assert "source <> 'imported'" in import_sql
    assert "source_ref IS NOT NULL" in import_sql

    geom_sql = _check_sql(table, "ck_route_collections_geom_valid_type")
    assert "ST_IsValid" in geom_sql
    assert "GeometryType" in geom_sql
    assert "POINT" not in geom_sql

    judgment_fk = _foreign_key(table, "fk_route_collections_source_judgment_run")
    assert {element.parent.name for element in judgment_fk.elements} == {"source_judgment_run_id"}
    assert judgment_fk.ondelete is None

    created_by_fk = _foreign_key(table, "fk_route_collections_created_by")
    assert {element.parent.name for element in created_by_fk.elements} == {"created_by"}
    assert created_by_fk.ondelete == "SET NULL"

    assert _unique_constraint_columns(table, "uq_route_collections_city_slug") == ["city", "slug"]
    assert _index(table, "idx_route_collections_geom").dialect_options["postgresql"]["using"] == "gist"


def test_batch7_migration_creates_only_route_collections_foundation():
    migration_text = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "20260618_route_collections"' in migration_text
    assert 'down_revision = "20260618_route_cognition_batch5"' in migration_text
    assert '"route_collections"' in migration_text
    assert "Geometry(geometry_type=\"GEOMETRY\", srid=4326, spatial_index=False)" in migration_text
    assert "postgresql_using=\"gist\"" in migration_text
    assert "ck_route_collections_geom_valid_type" in migration_text

    for forbidden in (
        "collection_routes",
        "collection_segments",
        "collection_concept_links",
        "concept_nodes",
        "segment_submissions",
        "formal_relationship",
        "candidate",
        "APIRouter",
    ):
        assert forbidden not in migration_text


def test_batch7_status_doc_records_foundation_boundaries():
    status_text = Path("docs/research/route_cognition_v1_1_status.md").read_text(encoding="utf-8")

    assert "Batch 7: route_collections foundation" in status_text
    assert "`route_collections` is not `concept_nodes`" in status_text
    assert "`route_collections` has no members yet" in status_text
    assert "stats_json is projection only" in status_text
    assert "metadata_json is not relationship truth" in status_text
    assert "No public API." in status_text
    assert "No admin UI." in status_text


@pytest.fixture()
def batch7_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_batch7_tables(db)
    _create_batch7_sqlite_tables(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_batch7_tables(db)


def test_valid_private_draft_manual_collection_inserts(db, batch7_sqlite_tables):
    _seed_batch7_base(db)
    _insert_collection(db)

    assert db.execute(text("SELECT count(*) FROM route_collections")).scalar_one() == 1


def test_public_draft_collection_is_rejected(db, batch7_sqlite_tables):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, visibility="public", publish_status="draft")


def test_published_collection_requires_source_judgment_run(db, batch7_sqlite_tables):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(
            db,
            visibility="public",
            publish_status="published",
            source_judgment_run_id=None,
        )


def test_imported_collection_requires_source_ref_or_judgment(db, batch7_sqlite_tables):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, source="imported", source_ref=None, source_judgment_run_id=None)


def test_imported_collection_can_use_source_ref_without_judgment(db, batch7_sqlite_tables):
    _seed_batch7_base(db)
    _insert_collection(db, source="imported", source_ref="manual-import-2026-06-18")

    assert db.execute(text("SELECT source FROM route_collections")).scalar_one() == "imported"


@pytest.mark.parametrize("source", ["agent", "semantic_agent"])
def test_agent_source_is_rejected(db, batch7_sqlite_tables, source):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, source=source)


@pytest.mark.parametrize("collection_type", ["concept", "candidate", "bad_type"])
def test_invalid_collection_type_is_rejected(db, batch7_sqlite_tables, collection_type):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, collection_type=collection_type)


@pytest.mark.parametrize("visibility", ["shared", "discoverable"])
def test_invalid_visibility_is_rejected(db, batch7_sqlite_tables, visibility):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, visibility=visibility)


@pytest.mark.parametrize("publish_status", ["live", "deleted"])
def test_invalid_publish_status_is_rejected(db, batch7_sqlite_tables, publish_status):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, publish_status=publish_status)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_outside_zero_to_one_is_rejected(db, batch7_sqlite_tables, confidence):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, confidence=confidence)


@pytest.mark.parametrize("slug", ["Taiyuan-west", "taiyuan west", "taiyuan.west"])
def test_invalid_slug_format_is_rejected(db, batch7_sqlite_tables, slug):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, slug=slug)


@pytest.mark.parametrize("slug", ["-taiyuan-west", "_taiyuan-west", "a"])
def test_slug_must_start_with_alnum_and_have_minimum_length(db, batch7_sqlite_tables, slug):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, slug=slug)


def test_duplicate_city_slug_is_rejected(db, batch7_sqlite_tables):
    _seed_batch7_base(db)
    _insert_collection(db, id=1, city="taiyuan", slug="west-hills")

    with pytest.raises(IntegrityError):
        _insert_collection(db, id=2, city="taiyuan", slug="west-hills")


def test_same_slug_different_city_is_allowed(db, batch7_sqlite_tables):
    _seed_batch7_base(db)
    _insert_collection(db, id=1, city="taiyuan", slug="west-hills")
    _insert_collection(db, id=2, city="chengdu", slug="west-hills")

    assert db.execute(text("SELECT count(*) FROM route_collections")).scalar_one() == 2


def test_center_lat_without_center_lon_is_rejected(db, batch7_sqlite_tables):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, center_lat=37.8, center_lon=None)


def test_center_lon_without_center_lat_is_rejected(db, batch7_sqlite_tables):
    _seed_batch7_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection(db, center_lat=None, center_lon=112.5)


def test_deleting_source_judgment_run_is_restricted(db, batch7_sqlite_tables):
    _seed_batch7_base(db)
    _insert_collection(db, visibility="public", publish_status="published", source_judgment_run_id=1)
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM judgment_runs WHERE id = 1"))
    db.rollback()

    assert db.execute(text("SELECT count(*) FROM route_collections")).scalar_one() == 1


def test_deleting_creator_sets_created_by_to_null(db, batch7_sqlite_tables):
    _seed_batch7_base(db)
    _insert_collection(db, created_by=1)
    db.commit()

    db.execute(text("DELETE FROM users WHERE id = 1"))

    row = db.execute(text("SELECT created_by FROM route_collections WHERE id = 1")).one()
    assert row.created_by is None


def test_no_forbidden_tables_are_created_in_sqlite_contract(db, batch7_sqlite_tables):
    forbidden_tables = (
        "collection_routes",
        "collection_segments",
        "collection_concept_links",
        "concept_nodes",
        "segment_submissions",
    )

    for table_name in forbidden_tables:
        row = db.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
            {"table_name": table_name},
        ).first()
        assert row is None


def _seed_batch7_base(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO users (id, openid, is_admin)
            VALUES (1, 'batch7_user', 1)
            """
        )
    )
    db.execute(text("INSERT INTO judgment_runs (id) VALUES (1)"))


def _insert_collection(
    db,
    *,
    id: int = 1,
    name: str = "Taiyuan West Hills",
    slug: str = "taiyuan-west",
    collection_type: str = "area_system",
    city: str = "taiyuan",
    visibility: str = "private",
    publish_status: str = "draft",
    source: str = "manual",
    source_ref: str | None = None,
    confidence: float | None = 0.8,
    center_lat: float | None = 37.8,
    center_lon: float | None = 112.5,
    source_judgment_run_id: int | None = None,
    created_by: int | None = 1,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO route_collections (
                id, name, slug, collection_type, city, visibility, publish_status,
                description_md, cover_url, geom, center_lat, center_lon, source, source_ref,
                confidence, stats_json, metadata_json, source_judgment_run_id, created_by
            )
            VALUES (
                :id, :name, :slug, :collection_type, :city, :visibility, :publish_status,
                NULL, NULL, NULL, :center_lat, :center_lon, :source, :source_ref,
                :confidence, NULL, NULL, :source_judgment_run_id, :created_by
            )
            """
        ),
        {
            "id": id,
            "name": name,
            "slug": slug,
            "collection_type": collection_type,
            "city": city,
            "visibility": visibility,
            "publish_status": publish_status,
            "center_lat": center_lat,
            "center_lon": center_lon,
            "source": source,
            "source_ref": source_ref,
            "confidence": confidence,
            "source_judgment_run_id": source_judgment_run_id,
            "created_by": created_by,
        },
    )


def _create_batch7_sqlite_tables(db) -> None:
    db.execute(text("CREATE TABLE judgment_runs (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(
        text(
            """
            CREATE TABLE route_collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                collection_type TEXT NOT NULL,
                city TEXT NOT NULL DEFAULT 'unknown',
                visibility TEXT NOT NULL DEFAULT 'private',
                publish_status TEXT NOT NULL DEFAULT 'draft',
                description_md TEXT,
                cover_url TEXT,
                geom TEXT,
                center_lat REAL,
                center_lon REAL,
                source TEXT NOT NULL DEFAULT 'manual',
                source_ref TEXT,
                confidence REAL,
                stats_json TEXT,
                metadata_json TEXT,
                source_judgment_run_id INTEGER,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CHECK (length(trim(name)) > 0),
                CHECK (
                    length(slug) BETWEEN 2 AND 128
                    AND substr(slug, 1, 1) GLOB '[a-z0-9]'
                    AND slug NOT GLOB '*[^a-z0-9_-]*'
                ),
                CHECK (
                    collection_type IN (
                        'area_system',
                        'route_family',
                        'race_route_family',
                        'training_corridor',
                        'theme_pack',
                        'other'
                    )
                ),
                CHECK (visibility IN ('private', 'unlisted', 'public')),
                CHECK (publish_status IN ('draft', 'published', 'archived')),
                CHECK (source IN ('manual', 'imported')),
                CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
                CHECK (center_lat IS NULL OR center_lat BETWEEN -90 AND 90),
                CHECK (center_lon IS NULL OR center_lon BETWEEN -180 AND 180),
                CHECK (
                    (center_lat IS NULL AND center_lon IS NULL)
                    OR
                    (center_lat IS NOT NULL AND center_lon IS NOT NULL)
                ),
                CHECK (visibility <> 'public' OR publish_status = 'published'),
                CHECK (publish_status <> 'published' OR source_judgment_run_id IS NOT NULL),
                CHECK (
                    source <> 'imported'
                    OR source_ref IS NOT NULL
                    OR source_judgment_run_id IS NOT NULL
                ),
                UNIQUE(city, slug),
                FOREIGN KEY(source_judgment_run_id) REFERENCES judgment_runs(id),
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
    )


def _drop_batch7_tables(db) -> None:
    for table_name in ("route_collections", "judgment_runs"):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
