"""路线认知 Step C 测试——正式 concept 关系只允许从审过的候选或人工审查进入。

正式关系表像“盖章后的档案柜”：candidate 可以由算法或 agent 提出，但进柜必须有人类
review judgment 盖章；并且路线、segment、collection、concept、关系类型都不能在转正时抄错。
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError


MIGRATION = Path("migrations/versions/20260618_concept_formal_links.py")

FORMAL_LINK_TABLES = (
    "route_concept_links",
    "segment_concept_links",
    "collection_concept_links",
)

RELATION_TYPES = (
    "suitable_for",
    "passes_near",
    "has_feature",
    "has_risk",
    "part_of_event",
    "story_reference",
    "training_theme",
    "local_name",
    "associated_with",
)


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


def _assert_common_formal_link_contract(table, source_column: str) -> None:
    assert {
        "id",
        "relation_type",
        "link_status",
        "source_kind",
        "accepted_judgment_run_id",
        "accepted_judgment_run_type",
        source_column,
        "display_priority",
        "reason_summary",
        "metadata_json",
        "created_by",
        "created_at",
        "updated_at",
    } <= set(table.c.keys())
    assert table.c.accepted_judgment_run_id.nullable is False
    assert table.c.accepted_judgment_run_type.nullable is False
    assert isinstance(table.c.metadata_json.type, JSONB)

    relation_sql = _check_sql(table, f"ck_{table.name}_relation_type")
    for value in RELATION_TYPES:
        assert value in relation_sql
    assert "related_to" not in relation_sql

    assert "active" in _check_sql(table, f"ck_{table.name}_link_status")
    assert "deprecated" in _check_sql(table, f"ck_{table.name}_link_status")
    assert "superseded" in _check_sql(table, f"ck_{table.name}_link_status")
    assert "needs_review" not in _check_sql(table, f"ck_{table.name}_link_status")
    assert "rejected" not in _check_sql(table, f"ck_{table.name}_link_status")

    source_sql = _check_sql(table, f"ck_{table.name}_source_kind")
    for value in ("candidate_accepted", "manual_curated", "legacy_import"):
        assert value in source_sql

    gate_sql = _check_sql(table, f"ck_{table.name}_source_gate")
    assert "source_kind = 'candidate_accepted'" in gate_sql
    assert f"{source_column} IS NOT NULL" in gate_sql
    assert "source_kind IN ('manual_curated', 'legacy_import')" in gate_sql
    assert f"{source_column} IS NULL" in gate_sql

    judgment_type_sql = _check_sql(table, f"ck_{table.name}_accepted_judgment_run_type")
    assert "accepted_judgment_run_type = 'human_review'" in judgment_type_sql

    judgment_fk = _foreign_key(table, f"fk_{table.name}_accepted_judgment_run")
    assert [element.parent.name for element in judgment_fk.elements] == [
        "accepted_judgment_run_id",
        "accepted_judgment_run_type",
    ]
    assert [element.column.table.name for element in judgment_fk.elements] == ["judgment_runs", "judgment_runs"]
    assert judgment_fk.ondelete is None

    assert _foreign_key(table, f"fk_{table.name}_created_by").ondelete == "SET NULL"
    assert _unique_columns(table, f"uq_{table.name}_source_candidate") == [source_column]


def test_step_c_models_declare_formal_link_tables_and_hard_gates():
    from app.route_cognition.models import (
        CollectionConceptCandidate,
        CollectionConceptLink,
        JudgmentRun,
        RouteConceptCandidate,
        RouteConceptLink,
        SegmentConceptCandidate,
        SegmentConceptLink,
    )

    assert _unique_columns(JudgmentRun.__table__, "uq_judgment_runs_id_run_type") == ["id", "run_type"]

    route_table = RouteConceptLink.__table__
    segment_table = SegmentConceptLink.__table__
    collection_table = CollectionConceptLink.__table__

    _assert_common_formal_link_contract(route_table, "source_route_concept_candidate_id")
    _assert_common_formal_link_contract(segment_table, "source_segment_concept_candidate_id")
    _assert_common_formal_link_contract(collection_table, "source_collection_concept_candidate_id")

    route_candidate_table = RouteConceptCandidate.__table__
    assert _unique_columns(route_candidate_table, "uq_route_concept_candidates_wide_formal_gate") == [
        "id",
        "accepted_by_judgment_run_id",
        "route_book_id",
        "route_version_id",
        "route_line_hash",
        "concept_node_id",
        "relation_type",
    ]
    segment_candidate_table = SegmentConceptCandidate.__table__
    assert _unique_columns(segment_candidate_table, "uq_segment_concept_candidates_wide_formal_gate") == [
        "id",
        "accepted_by_judgment_run_id",
        "segment_id",
        "segment_geometry_hash",
        "concept_node_id",
        "relation_type",
    ]
    collection_candidate_table = CollectionConceptCandidate.__table__
    assert _unique_columns(collection_candidate_table, "uq_collection_concept_candidates_wide_formal_gate") == [
        "id",
        "accepted_by_judgment_run_id",
        "collection_id",
        "concept_node_id",
        "relation_type",
    ]

    route_candidate_fk = _foreign_key(route_table, "fk_route_concept_links_source_candidate_wide")
    assert [element.parent.name for element in route_candidate_fk.elements] == [
        "source_route_concept_candidate_id",
        "accepted_judgment_run_id",
        "route_book_id",
        "route_version_id",
        "route_line_hash",
        "concept_node_id",
        "relation_type",
    ]
    assert route_candidate_fk.ondelete is None

    segment_candidate_fk = _foreign_key(segment_table, "fk_segment_concept_links_source_candidate_wide")
    assert [element.parent.name for element in segment_candidate_fk.elements] == [
        "source_segment_concept_candidate_id",
        "accepted_judgment_run_id",
        "segment_id",
        "segment_geometry_hash",
        "concept_node_id",
        "relation_type",
    ]
    assert segment_candidate_fk.ondelete is None

    collection_candidate_fk = _foreign_key(collection_table, "fk_collection_concept_links_source_candidate_wide")
    assert [element.parent.name for element in collection_candidate_fk.elements] == [
        "source_collection_concept_candidate_id",
        "accepted_judgment_run_id",
        "collection_id",
        "concept_node_id",
        "relation_type",
    ]
    assert collection_candidate_fk.ondelete is None

    assert [element.column.table.name for element in _foreign_key(segment_table, "fk_segment_concept_links_segment").elements] == [
        "route_cognition_segments"
    ]

    assert str(_index(route_table, "uq_route_concept_links_active").dialect_options["postgresql"]["where"]) == (
        "link_status = 'active'"
    )
    assert str(_index(segment_table, "uq_segment_concept_links_active").dialect_options["postgresql"]["where"]) == (
        "link_status = 'active'"
    )
    assert str(_index(collection_table, "uq_collection_concept_links_active").dialect_options["postgresql"]["where"]) == (
        "link_status = 'active'"
    )


def test_step_c_migration_declares_only_formal_concept_links():
    assert MIGRATION.exists()
    migration_text = MIGRATION.read_text(encoding="utf-8")
    migration_module = _load_migration_module()

    assert 'revision = "20260618_concept_formal_links"' in migration_text
    assert 'down_revision = "20260618_concept_rel_candidates"' in migration_text
    assert "uq_judgment_runs_id_run_type" in migration_text
    assert "uq_route_concept_candidates_wide_formal_gate" in migration_text
    assert "uq_segment_concept_candidates_wide_formal_gate" in migration_text
    assert "uq_collection_concept_candidates_wide_formal_gate" in migration_text
    for table_name in FORMAL_LINK_TABLES:
        assert f'"{table_name}"' in migration_text
        common_constraints = {constraint.name for constraint in migration_module._common_formal_constraints(table_name)}
        assert f"ck_{table_name}_accepted_judgment_run_type" in common_constraints
        assert f"ck_{table_name}_link_status" in common_constraints
        assert f"ck_{table_name}_source_kind" in common_constraints

    for forbidden in (
        "route_segments",
        "collection_routes",
        "collection_segments",
        "segment_submissions",
        "APIRouter",
        "app/admin",
        "admin/router",
    ):
        assert forbidden not in migration_text


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("concept_formal_links_migration", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def formal_link_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_step_c_tables(db)
    _create_step_c_sqlite_tables(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_step_c_tables(db)


@pytest.mark.parametrize(
    ("kind", "insert_fn"),
    [
        ("route", "_insert_route_link"),
        ("segment", "_insert_segment_link"),
        ("collection", "_insert_collection_link"),
    ],
)
def test_candidate_accepted_formal_link_succeeds_for_all_targets(db, formal_link_sqlite_tables, kind, insert_fn):
    _seed_step_c_base(db)
    globals()[insert_fn](db)

    assert db.execute(text(f"SELECT count(*) FROM {kind}_concept_links")).scalar_one() == 1


@pytest.mark.parametrize(
    ("insert_fn", "source_column"),
    [
        ("_insert_route_link", "source_route_concept_candidate_id"),
        ("_insert_segment_link", "source_segment_concept_candidate_id"),
        ("_insert_collection_link", "source_collection_concept_candidate_id"),
    ],
)
def test_candidate_accepted_requires_source_candidate(db, formal_link_sqlite_tables, insert_fn, source_column):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        globals()[insert_fn](db, **{source_column: None})


@pytest.mark.parametrize("source_kind", ["manual_curated", "legacy_import"])
def test_manual_and_legacy_links_cannot_keep_source_candidate(db, formal_link_sqlite_tables, source_kind):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_link(db, source_kind=source_kind, source_route_concept_candidate_id=1)


def test_formal_link_requires_accepted_judgment_run(db, formal_link_sqlite_tables):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_link(db, accepted_judgment_run_id=None)


def test_formal_link_requires_human_review_judgment(db, formal_link_sqlite_tables):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_link(db, accepted_judgment_run_id=2)


def test_candidate_accepted_link_rejects_candidate_that_is_not_accepted(db, formal_link_sqlite_tables):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_link(db, id=2, source_route_concept_candidate_id=2)


@pytest.mark.parametrize(
    "override",
    [
        {"concept_node_id": 2},
        {"relation_type": "has_risk"},
        {"route_book_id": 2, "route_version_id": 2, "route_line_hash": "route-hash-b"},
        {"route_line_hash": "wrong-route-hash"},
    ],
)
def test_route_candidate_accepted_link_rejects_target_or_projection_mismatch(
    db, formal_link_sqlite_tables, override
):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_link(db, **override)


@pytest.mark.parametrize(
    "override",
    [
        {"concept_node_id": 2},
        {"relation_type": "has_risk"},
        {"segment_id": 3, "segment_geometry_hash": "segment-hash-b"},
        {"segment_geometry_hash": "wrong-segment-hash"},
    ],
)
def test_segment_candidate_accepted_link_rejects_target_or_projection_mismatch(
    db, formal_link_sqlite_tables, override
):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        _insert_segment_link(db, **override)


@pytest.mark.parametrize(
    "override",
    [
        {"concept_node_id": 2},
        {"relation_type": "has_risk"},
        {"collection_id": 2},
    ],
)
def test_collection_candidate_accepted_link_rejects_target_mismatch(db, formal_link_sqlite_tables, override):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        _insert_collection_link(db, **override)


def test_same_source_candidate_cannot_create_two_formal_links(db, formal_link_sqlite_tables):
    _seed_step_c_base(db)
    _insert_route_link(db, id=1)

    with pytest.raises(IntegrityError):
        _insert_route_link(db, id=2)


def test_active_duplicate_formal_link_is_rejected(db, formal_link_sqlite_tables):
    _seed_step_c_base(db)
    _insert_route_link(db, id=1)

    with pytest.raises(IntegrityError):
        _insert_route_link(
            db,
            id=2,
            source_kind="manual_curated",
            source_route_concept_candidate_id=None,
            accepted_judgment_run_id=3,
        )


def test_deprecated_history_does_not_block_new_active_link(db, formal_link_sqlite_tables):
    _seed_step_c_base(db)
    _insert_route_link(
        db,
        id=1,
        link_status="deprecated",
        source_kind="manual_curated",
        source_route_concept_candidate_id=None,
        accepted_judgment_run_id=3,
    )
    _insert_route_link(
        db,
        id=2,
        link_status="active",
        source_kind="manual_curated",
        source_route_concept_candidate_id=None,
        accepted_judgment_run_id=1,
    )

    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 2


def test_segment_link_cannot_target_raw_segments(db, formal_link_sqlite_tables):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        _insert_segment_link(
            db,
            source_kind="manual_curated",
            source_segment_concept_candidate_id=None,
            segment_id=2,
            segment_geometry_hash="raw-segment-hash",
            accepted_judgment_run_id=3,
        )


@pytest.mark.parametrize("relation_type", ["related_to", "generic", "bad_relation"])
def test_invalid_relation_type_is_rejected(db, formal_link_sqlite_tables, relation_type):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_link(db, relation_type=relation_type)


@pytest.mark.parametrize("link_status", ["proposed", "needs_review", "rejected"])
def test_invalid_link_status_is_rejected(db, formal_link_sqlite_tables, link_status):
    _seed_step_c_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_link(db, link_status=link_status)


def test_no_forbidden_tables_are_created_by_step_c_sqlite_contract(db, formal_link_sqlite_tables):
    for table_name in ("route_segments", "collection_routes", "collection_segments", "segment_submissions"):
        row = db.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
            {"table_name": table_name},
        ).first()
        assert row is None


def test_step_c_git_diff_stays_inside_allowed_files():
    result = subprocess.run(["git", "diff", "--name-only"], check=True, capture_output=True, text=True)
    changed_files = {line for line in result.stdout.splitlines() if line}

    allowed_files = {
        "app/route_cognition/models.py",
        "migrations/versions/20260618_concept_formal_links.py",
        "tests/test_route_cognition_concept_formal_links.py",
        "docs/research/route_cognition_v1_1_status.md",
    }
    assert changed_files <= allowed_files
    assert not any(path.startswith("content/routes/") for path in changed_files)
    assert "guide.md" not in changed_files
    assert "app/admin/router.py" not in changed_files


def _seed_step_c_base(db) -> None:
    db.execute(text("INSERT INTO users (id, openid, is_admin) VALUES (1, 'formal_link_user', 1)"))
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (id, run_type)
            VALUES (1, 'human_review'), (2, 'semantic_agent'), (3, 'human_review')
            """
        )
    )
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
    db.execute(
        text(
            """
            INSERT INTO route_cognition_segments (segment_id, geometry_hash)
            VALUES (1, 'segment-hash-a'), (3, 'segment-hash-b')
            """
        )
    )
    db.execute(text("INSERT INTO concept_nodes (id) VALUES (1), (2)"))
    db.execute(text("INSERT INTO route_collections (id) VALUES (1), (2)"))
    _insert_route_candidate(db)
    _insert_route_candidate(db, id=2, candidate_status="proposed", accepted_by_judgment_run_id=None)
    _insert_segment_candidate(db)
    _insert_collection_candidate(db)


def _create_step_c_sqlite_tables(db) -> None:
    db.execute(text("CREATE TABLE judgment_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_type TEXT NOT NULL)"))
    db.execute(text("CREATE UNIQUE INDEX uq_judgment_runs_id_run_type ON judgment_runs(id, run_type)"))
    db.execute(text("CREATE TABLE concept_nodes (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE route_collections (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(
        text(
            """
            CREATE TABLE route_cognition_segments (
                segment_id INTEGER PRIMARY KEY,
                geometry_hash TEXT NOT NULL,
                FOREIGN KEY(segment_id) REFERENCES segments(id)
            )
            """
        )
    )
    _create_candidate_sqlite_tables(db)
    _create_formal_link_sqlite_tables(db)


def _create_candidate_sqlite_tables(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE route_concept_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_book_id INTEGER NOT NULL,
                route_version_id INTEGER NOT NULL,
                route_line_hash TEXT NOT NULL,
                concept_node_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                candidate_status TEXT NOT NULL,
                accepted_by_judgment_run_id INTEGER,
                reviewed_at DATETIME,
                CHECK (
                    (
                        candidate_status = 'accepted'
                        AND accepted_by_judgment_run_id IS NOT NULL
                        AND reviewed_at IS NOT NULL
                    )
                    OR
                    (
                        candidate_status <> 'accepted'
                        AND accepted_by_judgment_run_id IS NULL
                    )
                ),
                UNIQUE(
                    id,
                    accepted_by_judgment_run_id,
                    route_book_id,
                    route_version_id,
                    route_line_hash,
                    concept_node_id,
                    relation_type
                ),
                FOREIGN KEY(route_book_id) REFERENCES route_books(id),
                FOREIGN KEY(route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id),
                FOREIGN KEY(concept_node_id) REFERENCES concept_nodes(id),
                FOREIGN KEY(accepted_by_judgment_run_id) REFERENCES judgment_runs(id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE segment_concept_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id INTEGER NOT NULL,
                segment_geometry_hash TEXT NOT NULL,
                concept_node_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                candidate_status TEXT NOT NULL,
                accepted_by_judgment_run_id INTEGER,
                reviewed_at DATETIME,
                CHECK (
                    (
                        candidate_status = 'accepted'
                        AND accepted_by_judgment_run_id IS NOT NULL
                        AND reviewed_at IS NOT NULL
                    )
                    OR
                    (
                        candidate_status <> 'accepted'
                        AND accepted_by_judgment_run_id IS NULL
                    )
                ),
                UNIQUE(
                    id,
                    accepted_by_judgment_run_id,
                    segment_id,
                    segment_geometry_hash,
                    concept_node_id,
                    relation_type
                ),
                FOREIGN KEY(segment_id) REFERENCES route_cognition_segments(segment_id),
                FOREIGN KEY(concept_node_id) REFERENCES concept_nodes(id),
                FOREIGN KEY(accepted_by_judgment_run_id) REFERENCES judgment_runs(id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE collection_concept_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                concept_node_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                candidate_status TEXT NOT NULL,
                accepted_by_judgment_run_id INTEGER,
                reviewed_at DATETIME,
                CHECK (
                    (
                        candidate_status = 'accepted'
                        AND accepted_by_judgment_run_id IS NOT NULL
                        AND reviewed_at IS NOT NULL
                    )
                    OR
                    (
                        candidate_status <> 'accepted'
                        AND accepted_by_judgment_run_id IS NULL
                    )
                ),
                UNIQUE(
                    id,
                    accepted_by_judgment_run_id,
                    collection_id,
                    concept_node_id,
                    relation_type
                ),
                FOREIGN KEY(collection_id) REFERENCES route_collections(id),
                FOREIGN KEY(concept_node_id) REFERENCES concept_nodes(id),
                FOREIGN KEY(accepted_by_judgment_run_id) REFERENCES judgment_runs(id)
            )
            """
        )
    )


def _create_formal_link_sqlite_tables(db) -> None:
    _create_route_link_sqlite_table(db)
    _create_segment_link_sqlite_table(db)
    _create_collection_link_sqlite_table(db)


def _common_formal_columns_sql(source_column: str) -> str:
    return f"""
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        relation_type TEXT NOT NULL,
        link_status TEXT NOT NULL,
        source_kind TEXT NOT NULL,
        accepted_judgment_run_id INTEGER NOT NULL,
        accepted_judgment_run_type TEXT NOT NULL DEFAULT 'human_review',
        {source_column} INTEGER,
        display_priority INTEGER,
        reason_summary TEXT,
        metadata_json TEXT,
        created_by INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CHECK (
            relation_type IN (
                'suitable_for',
                'passes_near',
                'has_feature',
                'has_risk',
                'part_of_event',
                'story_reference',
                'training_theme',
                'local_name',
                'associated_with'
            )
        ),
        CHECK (link_status IN ('active', 'deprecated', 'superseded')),
        CHECK (source_kind IN ('candidate_accepted', 'manual_curated', 'legacy_import')),
        CHECK (accepted_judgment_run_type = 'human_review'),
        CHECK (
            (
                source_kind = 'candidate_accepted'
                AND {source_column} IS NOT NULL
            )
            OR
            (
                source_kind IN ('manual_curated', 'legacy_import')
                AND {source_column} IS NULL
            )
        ),
        UNIQUE({source_column}),
        FOREIGN KEY(accepted_judgment_run_id, accepted_judgment_run_type)
            REFERENCES judgment_runs(id, run_type),
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    """


def _create_route_link_sqlite_table(db) -> None:
    db.execute(
        text(
            f"""
            CREATE TABLE route_concept_links (
                route_book_id INTEGER NOT NULL,
                route_version_id INTEGER NOT NULL,
                route_line_hash TEXT NOT NULL,
                concept_node_id INTEGER NOT NULL,
                {_common_formal_columns_sql("source_route_concept_candidate_id")},
                FOREIGN KEY(route_book_id) REFERENCES route_books(id),
                FOREIGN KEY(route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id),
                FOREIGN KEY(concept_node_id) REFERENCES concept_nodes(id),
                FOREIGN KEY(
                    source_route_concept_candidate_id,
                    accepted_judgment_run_id,
                    route_book_id,
                    route_version_id,
                    route_line_hash,
                    concept_node_id,
                    relation_type
                )
                REFERENCES route_concept_candidates(
                    id,
                    accepted_by_judgment_run_id,
                    route_book_id,
                    route_version_id,
                    route_line_hash,
                    concept_node_id,
                    relation_type
                )
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_route_concept_links_active
            ON route_concept_links(route_book_id, route_version_id, concept_node_id, relation_type)
            WHERE link_status = 'active'
            """
        )
    )


def _create_segment_link_sqlite_table(db) -> None:
    db.execute(
        text(
            f"""
            CREATE TABLE segment_concept_links (
                segment_id INTEGER NOT NULL,
                segment_geometry_hash TEXT NOT NULL,
                concept_node_id INTEGER NOT NULL,
                {_common_formal_columns_sql("source_segment_concept_candidate_id")},
                FOREIGN KEY(segment_id) REFERENCES route_cognition_segments(segment_id),
                FOREIGN KEY(concept_node_id) REFERENCES concept_nodes(id),
                FOREIGN KEY(
                    source_segment_concept_candidate_id,
                    accepted_judgment_run_id,
                    segment_id,
                    segment_geometry_hash,
                    concept_node_id,
                    relation_type
                )
                REFERENCES segment_concept_candidates(
                    id,
                    accepted_by_judgment_run_id,
                    segment_id,
                    segment_geometry_hash,
                    concept_node_id,
                    relation_type
                )
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_segment_concept_links_active
            ON segment_concept_links(segment_id, concept_node_id, relation_type)
            WHERE link_status = 'active'
            """
        )
    )


def _create_collection_link_sqlite_table(db) -> None:
    db.execute(
        text(
            f"""
            CREATE TABLE collection_concept_links (
                collection_id INTEGER NOT NULL,
                concept_node_id INTEGER NOT NULL,
                {_common_formal_columns_sql("source_collection_concept_candidate_id")},
                FOREIGN KEY(collection_id) REFERENCES route_collections(id),
                FOREIGN KEY(concept_node_id) REFERENCES concept_nodes(id),
                FOREIGN KEY(
                    source_collection_concept_candidate_id,
                    accepted_judgment_run_id,
                    collection_id,
                    concept_node_id,
                    relation_type
                )
                REFERENCES collection_concept_candidates(
                    id,
                    accepted_by_judgment_run_id,
                    collection_id,
                    concept_node_id,
                    relation_type
                )
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_collection_concept_links_active
            ON collection_concept_links(collection_id, concept_node_id, relation_type)
            WHERE link_status = 'active'
            """
        )
    )


def _insert_route_candidate(
    db,
    *,
    id: int = 1,
    route_book_id: int = 1,
    route_version_id: int = 1,
    route_line_hash: str = "route-hash-a",
    concept_node_id: int = 1,
    relation_type: str = "training_theme",
    candidate_status: str = "accepted",
    accepted_by_judgment_run_id: int | None = 1,
    reviewed_at: str | None = "2026-06-18T12:00:00Z",
) -> None:
    db.execute(
        text(
            """
            INSERT INTO route_concept_candidates (
                id, route_book_id, route_version_id, route_line_hash, concept_node_id,
                relation_type, candidate_status, accepted_by_judgment_run_id, reviewed_at
            )
            VALUES (
                :id, :route_book_id, :route_version_id, :route_line_hash, :concept_node_id,
                :relation_type, :candidate_status, :accepted_by_judgment_run_id, :reviewed_at
            )
            """
        ),
        {
            "id": id,
            "route_book_id": route_book_id,
            "route_version_id": route_version_id,
            "route_line_hash": route_line_hash,
            "concept_node_id": concept_node_id,
            "relation_type": relation_type,
            "candidate_status": candidate_status,
            "accepted_by_judgment_run_id": accepted_by_judgment_run_id,
            "reviewed_at": reviewed_at,
        },
    )


def _insert_segment_candidate(
    db,
    *,
    id: int = 1,
    segment_id: int = 1,
    segment_geometry_hash: str = "segment-hash-a",
    concept_node_id: int = 1,
    relation_type: str = "has_feature",
    candidate_status: str = "accepted",
    accepted_by_judgment_run_id: int | None = 1,
    reviewed_at: str | None = "2026-06-18T12:00:00Z",
) -> None:
    db.execute(
        text(
            """
            INSERT INTO segment_concept_candidates (
                id, segment_id, segment_geometry_hash, concept_node_id,
                relation_type, candidate_status, accepted_by_judgment_run_id, reviewed_at
            )
            VALUES (
                :id, :segment_id, :segment_geometry_hash, :concept_node_id,
                :relation_type, :candidate_status, :accepted_by_judgment_run_id, :reviewed_at
            )
            """
        ),
        {
            "id": id,
            "segment_id": segment_id,
            "segment_geometry_hash": segment_geometry_hash,
            "concept_node_id": concept_node_id,
            "relation_type": relation_type,
            "candidate_status": candidate_status,
            "accepted_by_judgment_run_id": accepted_by_judgment_run_id,
            "reviewed_at": reviewed_at,
        },
    )


def _insert_collection_candidate(
    db,
    *,
    id: int = 1,
    collection_id: int = 1,
    concept_node_id: int = 1,
    relation_type: str = "associated_with",
    candidate_status: str = "accepted",
    accepted_by_judgment_run_id: int | None = 1,
    reviewed_at: str | None = "2026-06-18T12:00:00Z",
) -> None:
    db.execute(
        text(
            """
            INSERT INTO collection_concept_candidates (
                id, collection_id, concept_node_id,
                relation_type, candidate_status, accepted_by_judgment_run_id, reviewed_at
            )
            VALUES (
                :id, :collection_id, :concept_node_id,
                :relation_type, :candidate_status, :accepted_by_judgment_run_id, :reviewed_at
            )
            """
        ),
        {
            "id": id,
            "collection_id": collection_id,
            "concept_node_id": concept_node_id,
            "relation_type": relation_type,
            "candidate_status": candidate_status,
            "accepted_by_judgment_run_id": accepted_by_judgment_run_id,
            "reviewed_at": reviewed_at,
        },
    )


def _insert_route_link(
    db,
    *,
    id: int = 1,
    route_book_id: int = 1,
    route_version_id: int = 1,
    route_line_hash: str = "route-hash-a",
    concept_node_id: int = 1,
    relation_type: str = "training_theme",
    link_status: str = "active",
    source_kind: str = "candidate_accepted",
    accepted_judgment_run_id: int | None = 1,
    source_route_concept_candidate_id: int | None = 1,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO route_concept_links (
                id, route_book_id, route_version_id, route_line_hash, concept_node_id,
                relation_type, link_status, source_kind, accepted_judgment_run_id,
                source_route_concept_candidate_id, display_priority, reason_summary, metadata_json, created_by
            )
            VALUES (
                :id, :route_book_id, :route_version_id, :route_line_hash, :concept_node_id,
                :relation_type, :link_status, :source_kind, :accepted_judgment_run_id,
                :source_route_concept_candidate_id, 1, 'formal reason', NULL, 1
            )
            """
        ),
        {
            "id": id,
            "route_book_id": route_book_id,
            "route_version_id": route_version_id,
            "route_line_hash": route_line_hash,
            "concept_node_id": concept_node_id,
            "relation_type": relation_type,
            "link_status": link_status,
            "source_kind": source_kind,
            "accepted_judgment_run_id": accepted_judgment_run_id,
            "source_route_concept_candidate_id": source_route_concept_candidate_id,
        },
    )


def _insert_segment_link(
    db,
    *,
    id: int = 1,
    segment_id: int = 1,
    segment_geometry_hash: str = "segment-hash-a",
    concept_node_id: int = 1,
    relation_type: str = "has_feature",
    link_status: str = "active",
    source_kind: str = "candidate_accepted",
    accepted_judgment_run_id: int | None = 1,
    source_segment_concept_candidate_id: int | None = 1,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO segment_concept_links (
                id, segment_id, segment_geometry_hash, concept_node_id,
                relation_type, link_status, source_kind, accepted_judgment_run_id,
                source_segment_concept_candidate_id, display_priority, reason_summary, metadata_json, created_by
            )
            VALUES (
                :id, :segment_id, :segment_geometry_hash, :concept_node_id,
                :relation_type, :link_status, :source_kind, :accepted_judgment_run_id,
                :source_segment_concept_candidate_id, 1, 'formal reason', NULL, 1
            )
            """
        ),
        {
            "id": id,
            "segment_id": segment_id,
            "segment_geometry_hash": segment_geometry_hash,
            "concept_node_id": concept_node_id,
            "relation_type": relation_type,
            "link_status": link_status,
            "source_kind": source_kind,
            "accepted_judgment_run_id": accepted_judgment_run_id,
            "source_segment_concept_candidate_id": source_segment_concept_candidate_id,
        },
    )


def _insert_collection_link(
    db,
    *,
    id: int = 1,
    collection_id: int = 1,
    concept_node_id: int = 1,
    relation_type: str = "associated_with",
    link_status: str = "active",
    source_kind: str = "candidate_accepted",
    accepted_judgment_run_id: int | None = 1,
    source_collection_concept_candidate_id: int | None = 1,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO collection_concept_links (
                id, collection_id, concept_node_id,
                relation_type, link_status, source_kind, accepted_judgment_run_id,
                source_collection_concept_candidate_id, display_priority, reason_summary, metadata_json, created_by
            )
            VALUES (
                :id, :collection_id, :concept_node_id,
                :relation_type, :link_status, :source_kind, :accepted_judgment_run_id,
                :source_collection_concept_candidate_id, 1, 'formal reason', NULL, 1
            )
            """
        ),
        {
            "id": id,
            "collection_id": collection_id,
            "concept_node_id": concept_node_id,
            "relation_type": relation_type,
            "link_status": link_status,
            "source_kind": source_kind,
            "accepted_judgment_run_id": accepted_judgment_run_id,
            "source_collection_concept_candidate_id": source_collection_concept_candidate_id,
        },
    )


def _drop_step_c_tables(db) -> None:
    for table_name in (
        "collection_concept_links",
        "segment_concept_links",
        "route_concept_links",
        "collection_concept_candidates",
        "segment_concept_candidates",
        "route_concept_candidates",
        "route_cognition_segments",
        "route_collections",
        "concept_nodes",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
