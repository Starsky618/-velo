"""路线认知 v1.1 remaining step A 测试——只给语义概念建“概念身份证”。"""

from __future__ import annotations

from pathlib import Path

import pytest
from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError


MIGRATION = Path("migrations/versions/20260618_concept_nodes.py")


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


def test_step_a_model_declares_concept_nodes_table_contract():
    from app.route_cognition.models import ConceptNode

    table = ConceptNode.__table__
    assert ConceptNode.__tablename__ == "concept_nodes"
    assert {
        "id",
        "name",
        "slug",
        "node_type",
        "scope_type",
        "scope_value",
        "city",
        "region",
        "visibility",
        "publish_status",
        "summary",
        "description_md",
        "cover_url",
        "geom",
        "center_lat",
        "center_lon",
        "source",
        "source_ref",
        "confidence",
        "metadata_json",
        "source_judgment_run_id",
        "created_by",
        "created_at",
        "updated_at",
    } <= set(table.c.keys())
    assert table.c.name.nullable is False
    assert table.c.slug.nullable is False
    assert table.c.node_type.nullable is False
    assert table.c.scope_type.nullable is False
    assert table.c.scope_value.nullable is False
    assert table.c.scope_value.server_default.arg == "global"
    assert table.c.visibility.server_default.arg == "private"
    assert table.c.publish_status.server_default.arg == "draft"
    assert table.c.source.server_default.arg == "manual"
    assert isinstance(table.c.metadata_json.type, JSONB)
    assert isinstance(table.c.geom.type, Geometry)
    assert table.c.geom.type.geometry_type == "GEOMETRY"
    assert table.c.geom.type.srid == 4326
    assert table.c.geom.type.spatial_index is False


def test_step_a_model_declares_checks_fks_unique_and_indexes():
    from app.route_cognition.models import ConceptNode

    table = ConceptNode.__table__

    node_type_sql = _check_sql(table, "ck_concept_nodes_node_type")
    for value in (
        "practice_type",
        "landmark",
        "road_condition",
        "safety_risk",
        "event",
        "local_term",
        "place",
        "training_theme",
        "other",
    ):
        assert value in node_type_sql
    for forbidden in ("route_collection", "route_family", "area_system", "training_corridor"):
        assert forbidden not in node_type_sql

    scope_sql = _check_sql(table, "ck_concept_nodes_scope_rule")
    assert "scope_type = 'global'" in scope_sql
    assert "scope_value = 'global'" in scope_sql
    assert "scope_type = 'city'" in scope_sql
    assert "scope_type = 'region'" in scope_sql

    source_sql = _check_sql(table, "ck_concept_nodes_source")
    assert "manual" in source_sql
    assert "imported" in source_sql
    assert "agent" not in source_sql

    slug_sql = _check_sql(table, "ck_concept_nodes_slug_format")
    assert "slug" in slug_sql
    assert "~" in slug_sql

    publication_sql = _check_sql(table, "ck_concept_nodes_publication_state")
    assert "visibility <> 'public'" in publication_sql
    assert "publish_status = 'published'" in publication_sql

    judgment_sql = _check_sql(table, "ck_concept_nodes_published_judgment")
    assert "publish_status <> 'published'" in judgment_sql
    assert "source_judgment_run_id IS NOT NULL" in judgment_sql

    import_sql = _check_sql(table, "ck_concept_nodes_import_source_ref")
    assert "source <> 'imported'" in import_sql
    assert "source_ref IS NOT NULL" in import_sql

    geom_sql = _check_sql(table, "ck_concept_nodes_geom_valid_type")
    for value in ("POINT", "MULTIPOINT", "LINESTRING", "MULTILINESTRING", "POLYGON", "MULTIPOLYGON"):
        assert value in geom_sql
    assert "GEOMETRYCOLLECTION" not in geom_sql

    judgment_fk = _foreign_key(table, "fk_concept_nodes_source_judgment_run")
    assert {element.parent.name for element in judgment_fk.elements} == {"source_judgment_run_id"}
    assert judgment_fk.ondelete is None

    created_by_fk = _foreign_key(table, "fk_concept_nodes_created_by")
    assert {element.parent.name for element in created_by_fk.elements} == {"created_by"}
    assert created_by_fk.ondelete == "SET NULL"

    assert _unique_constraint_columns(
        table,
        "uq_concept_nodes_scope_type_scope_value_node_type_slug",
    ) == ["scope_type", "scope_value", "node_type", "slug"]
    assert _index(table, "idx_concept_nodes_geom").dialect_options["postgresql"]["using"] == "gist"


def test_step_a_migration_creates_only_concept_nodes_foundation():
    migration_text = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "20260618_concept_nodes"' in migration_text
    assert 'down_revision = "20260618_route_collections"' in migration_text
    assert '"concept_nodes"' in migration_text
    assert "Geometry(geometry_type=\"GEOMETRY\", srid=4326, spatial_index=False)" in migration_text
    assert "postgresql_using=\"gist\"" in migration_text
    assert "ck_concept_nodes_geom_valid_type" in migration_text

    for forbidden in (
        "route_concept_links",
        "segment_concept_links",
        "collection_concept_links",
        "route_concept_candidates",
        "segment_concept_candidates",
        "collection_concept_candidates",
        "route_segments",
        "collection_routes",
        "collection_segments",
        "segment_submissions",
        "formal_relationship",
        "APIRouter",
    ):
        assert forbidden not in migration_text


def test_step_a_status_doc_records_foundation_boundaries():
    status_text = Path("docs/research/route_cognition_v1_1_status.md").read_text(encoding="utf-8")

    assert "v1.1 remaining step A: concept_nodes foundation" in status_text
    assert "Batch 8" not in status_text
    assert "`concept_nodes` is not `route_collections`" in status_text
    assert "`concept_nodes` has no links yet" in status_text
    assert "Concept candidates are not implemented" in status_text
    assert "Formal concept links are not implemented" in status_text
    assert "Concept hierarchy is not implemented" in status_text
    assert "metadata_json is not relationship truth" in status_text
    assert "evidence_items are not a public content source" in status_text
    assert "No public API." in status_text
    assert "No admin UI." in status_text


@pytest.fixture()
def concept_nodes_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_step_a_tables(db)
    _create_step_a_sqlite_tables(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_step_a_tables(db)


def test_valid_private_draft_manual_global_concept_inserts(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)
    _insert_concept(db)

    assert db.execute(text("SELECT count(*) FROM concept_nodes")).scalar_one() == 1


def test_valid_city_scoped_concept_inserts(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)
    _insert_concept(db, scope_type="city", scope_value="taiyuan", city="taiyuan")

    row = db.execute(text("SELECT scope_type, scope_value, city FROM concept_nodes")).one()
    assert row.scope_type == "city"
    assert row.scope_value == "taiyuan"
    assert row.city == "taiyuan"


def test_valid_region_scoped_concept_inserts(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)
    _insert_concept(db, scope_type="region", scope_value="taiyuan-west-hills", region="west-hills")

    row = db.execute(text("SELECT scope_type, scope_value, region FROM concept_nodes")).one()
    assert row.scope_type == "region"
    assert row.scope_value == "taiyuan-west-hills"
    assert row.region == "west-hills"


def test_duplicate_scope_type_value_node_type_slug_is_rejected(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)
    _insert_concept(db, id=1, scope_type="city", scope_value="taiyuan", node_type="landmark", slug="wanghong-bridge")

    with pytest.raises(IntegrityError):
        _insert_concept(db, id=2, scope_type="city", scope_value="taiyuan", node_type="landmark", slug="wanghong-bridge")


def test_same_slug_and_type_in_different_scope_is_allowed(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)
    _insert_concept(db, id=1, scope_type="city", scope_value="taiyuan", node_type="landmark", slug="wanghong-bridge")
    _insert_concept(db, id=2, scope_type="city", scope_value="chengdu", node_type="landmark", slug="wanghong-bridge")

    assert db.execute(text("SELECT count(*) FROM concept_nodes")).scalar_one() == 2


@pytest.mark.parametrize("node_type", ["route_collection", "route_family", "area_system", "training_corridor", "bad_type"])
def test_invalid_node_type_is_rejected(db, concept_nodes_sqlite_tables, node_type):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, node_type=node_type)


@pytest.mark.parametrize("scope_type", ["district", "local", "bad_scope"])
def test_invalid_scope_type_is_rejected(db, concept_nodes_sqlite_tables, scope_type):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, scope_type=scope_type)


def test_global_scope_requires_global_scope_value(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, scope_type="global", scope_value="taiyuan")


@pytest.mark.parametrize("scope_type", ["city", "region"])
def test_local_scope_cannot_use_global_scope_value(db, concept_nodes_sqlite_tables, scope_type):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, scope_type=scope_type, scope_value="global")


def test_public_draft_concept_is_rejected(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, visibility="public", publish_status="draft")


def test_published_concept_requires_source_judgment_run(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, visibility="public", publish_status="published", source_judgment_run_id=None)


def test_imported_concept_requires_source_ref_or_judgment(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, source="imported", source_ref=None, source_judgment_run_id=None)


def test_imported_concept_can_use_source_ref_without_judgment(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)
    _insert_concept(db, source="imported", source_ref="manual-seed-2026-06-18")

    assert db.execute(text("SELECT source FROM concept_nodes")).scalar_one() == "imported"


@pytest.mark.parametrize("source", ["agent", "ai", "algorithm", "generated"])
def test_agent_or_algorithm_source_is_rejected(db, concept_nodes_sqlite_tables, source):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, source=source)


@pytest.mark.parametrize("slug", ["FTP-test", "ftp test", "ftp.test"])
def test_invalid_slug_format_is_rejected(db, concept_nodes_sqlite_tables, slug):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, slug=slug)


@pytest.mark.parametrize("slug", ["-ftp-test", "_ftp-test", "a"])
def test_slug_must_start_with_alnum_and_have_minimum_length(db, concept_nodes_sqlite_tables, slug):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, slug=slug)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_outside_zero_to_one_is_rejected(db, concept_nodes_sqlite_tables, confidence):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, confidence=confidence)


def test_center_lat_without_center_lon_is_rejected(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, center_lat=37.8, center_lon=None)


def test_center_lon_without_center_lat_is_rejected(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)

    with pytest.raises(IntegrityError):
        _insert_concept(db, center_lat=None, center_lon=112.5)


def test_deleting_source_judgment_run_is_restricted(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)
    _insert_concept(db, visibility="public", publish_status="published", source_judgment_run_id=1)
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM judgment_runs WHERE id = 1"))
    db.rollback()

    assert db.execute(text("SELECT count(*) FROM concept_nodes")).scalar_one() == 1


def test_deleting_creator_sets_created_by_to_null(db, concept_nodes_sqlite_tables):
    _seed_step_a_base(db)
    _insert_concept(db, created_by=1)
    db.commit()

    db.execute(text("DELETE FROM users WHERE id = 1"))

    row = db.execute(text("SELECT created_by FROM concept_nodes WHERE id = 1")).one()
    assert row.created_by is None


def test_no_forbidden_tables_are_created_in_sqlite_contract(db, concept_nodes_sqlite_tables):
    forbidden_tables = (
        "route_concept_links",
        "segment_concept_links",
        "collection_concept_links",
        "route_concept_candidates",
        "segment_concept_candidates",
        "collection_concept_candidates",
        "route_segments",
        "collection_routes",
        "collection_segments",
        "segment_submissions",
    )

    for table_name in forbidden_tables:
        row = db.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
            {"table_name": table_name},
        ).first()
        assert row is None


def _seed_step_a_base(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO users (id, openid, is_admin)
            VALUES (1, 'concept_user', 1)
            """
        )
    )
    db.execute(text("INSERT INTO judgment_runs (id) VALUES (1)"))


def _insert_concept(
    db,
    *,
    id: int = 1,
    name: str = "FTP Test",
    slug: str = "ftp-test",
    node_type: str = "practice_type",
    scope_type: str = "global",
    scope_value: str = "global",
    city: str | None = None,
    region: str | None = None,
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
            INSERT INTO concept_nodes (
                id, name, slug, node_type, scope_type, scope_value, city, region,
                visibility, publish_status, summary, description_md, cover_url, geom,
                center_lat, center_lon, source, source_ref, confidence, metadata_json,
                source_judgment_run_id, created_by
            )
            VALUES (
                :id, :name, :slug, :node_type, :scope_type, :scope_value, :city, :region,
                :visibility, :publish_status, NULL, NULL, NULL, NULL,
                :center_lat, :center_lon, :source, :source_ref, :confidence, NULL,
                :source_judgment_run_id, :created_by
            )
            """
        ),
        {
            "id": id,
            "name": name,
            "slug": slug,
            "node_type": node_type,
            "scope_type": scope_type,
            "scope_value": scope_value,
            "city": city,
            "region": region,
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


def _create_step_a_sqlite_tables(db) -> None:
    db.execute(text("CREATE TABLE judgment_runs (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(
        text(
            """
            CREATE TABLE concept_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                node_type TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                scope_value TEXT NOT NULL DEFAULT 'global',
                city TEXT,
                region TEXT,
                visibility TEXT NOT NULL DEFAULT 'private',
                publish_status TEXT NOT NULL DEFAULT 'draft',
                summary TEXT,
                description_md TEXT,
                cover_url TEXT,
                geom TEXT,
                center_lat REAL,
                center_lon REAL,
                source TEXT NOT NULL DEFAULT 'manual',
                source_ref TEXT,
                confidence REAL,
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
                    node_type IN (
                        'practice_type',
                        'landmark',
                        'road_condition',
                        'safety_risk',
                        'event',
                        'local_term',
                        'place',
                        'training_theme',
                        'other'
                    )
                ),
                CHECK (scope_type IN ('global', 'city', 'region')),
                CHECK (
                    (scope_type = 'global' AND scope_value = 'global')
                    OR
                    (scope_type = 'city' AND scope_value <> 'global')
                    OR
                    (scope_type = 'region' AND scope_value <> 'global')
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
                UNIQUE(scope_type, scope_value, node_type, slug),
                FOREIGN KEY(source_judgment_run_id) REFERENCES judgment_runs(id),
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
    )


def _drop_step_a_tables(db) -> None:
    for table_name in ("concept_nodes", "judgment_runs"):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
