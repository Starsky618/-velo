"""路线认知 Step B 测试——只建 concept 关系候选的三间“待审室”。

候选表像审核队列：算法、agent 或人工只能先把判断放进这里，不能直接写正式关系。
本文件同时守住三条边界：候选必须是 typed tables，segment 必须走白名单，正式 link 表仍不存在。
"""

from __future__ import annotations

import subprocess
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError


MIGRATION = Path("migrations/versions/20260618_concept_relationship_candidates.py")

CANDIDATE_TABLES = (
    "route_concept_candidates",
    "segment_concept_candidates",
    "collection_concept_candidates",
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


def _unique_constraint_columns(table, name: str) -> list[str]:
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


def _assert_common_candidate_contract(table) -> None:
    assert {
        "id",
        "relation_type",
        "proposer_kind",
        "candidate_status",
        "created_by_judgment_run_id",
        "latest_judgment_run_id",
        "accepted_by_judgment_run_id",
        "latest_confidence",
        "latest_confidence_state",
        "latest_evidence_summary_json",
        "latest_missing_data_summary_json",
        "latest_contradiction_summary_json",
        "reason_summary",
        "metadata_json",
        "created_by",
        "reviewed_by",
        "reviewed_at",
        "created_at",
        "updated_at",
    } <= set(table.c.keys())
    assert table.c.created_by_judgment_run_id.nullable is False
    assert table.c.latest_judgment_run_id.nullable is False
    assert table.c.accepted_by_judgment_run_id.nullable is True
    assert isinstance(table.c.latest_evidence_summary_json.type, JSONB)
    assert isinstance(table.c.latest_missing_data_summary_json.type, JSONB)
    assert isinstance(table.c.latest_contradiction_summary_json.type, JSONB)
    assert isinstance(table.c.metadata_json.type, JSONB)


def test_step_b_models_declare_three_typed_candidate_tables():
    from app.route_cognition.models import (
        CollectionConceptCandidate,
        RouteConceptCandidate,
        SegmentConceptCandidate,
    )

    assert RouteConceptCandidate.__tablename__ == "route_concept_candidates"
    assert SegmentConceptCandidate.__tablename__ == "segment_concept_candidates"
    assert CollectionConceptCandidate.__tablename__ == "collection_concept_candidates"

    route_table = RouteConceptCandidate.__table__
    segment_table = SegmentConceptCandidate.__table__
    collection_table = CollectionConceptCandidate.__table__

    _assert_common_candidate_contract(route_table)
    _assert_common_candidate_contract(segment_table)
    _assert_common_candidate_contract(collection_table)

    assert {"route_book_id", "route_version_id", "route_line_hash", "concept_node_id"} <= set(route_table.c.keys())
    assert route_table.c.route_book_id.nullable is False
    assert route_table.c.route_version_id.nullable is False
    assert route_table.c.route_line_hash.nullable is False

    assert {"segment_id", "segment_geometry_hash", "concept_node_id"} <= set(segment_table.c.keys())
    assert segment_table.c.segment_id.nullable is False
    assert segment_table.c.segment_geometry_hash.nullable is False

    assert {"collection_id", "concept_node_id"} <= set(collection_table.c.keys())
    assert collection_table.c.collection_id.nullable is False


def test_step_b_models_declare_checks_fks_uniques_and_indexes():
    from app.route_cognition.models import (
        CollectionConceptCandidate,
        RouteConceptCandidate,
        SegmentConceptCandidate,
    )

    for table in (
        RouteConceptCandidate.__table__,
        SegmentConceptCandidate.__table__,
        CollectionConceptCandidate.__table__,
    ):
        relation_sql = _check_sql(table, f"ck_{table.name}_relation_type")
        for value in (
            "suitable_for",
            "passes_near",
            "has_feature",
            "has_risk",
            "part_of_event",
            "story_reference",
            "training_theme",
            "local_name",
            "associated_with",
        ):
            assert value in relation_sql
        assert "related_to" not in relation_sql

        status_sql = _check_sql(table, f"ck_{table.name}_candidate_status")
        for value in (
            "proposed",
            "needs_review",
            "accepted",
            "rejected",
            "withdrawn",
            "superseded",
            "stale",
            "inconclusive",
        ):
            assert value in status_sql

        proposer_sql = _check_sql(table, f"ck_{table.name}_proposer_kind")
        for value in ("algorithm", "agent", "human", "imported"):
            assert value in proposer_sql

        confidence_state_sql = _check_sql(table, f"ck_{table.name}_latest_confidence_state")
        for value in ("raw", "proposed", "challenged", "stable", "human_accepted", "stale", "inconclusive"):
            assert value in confidence_state_sql

        acceptance_sql = _check_sql(table, f"ck_{table.name}_acceptance_gate")
        assert "candidate_status = 'accepted'" in acceptance_sql
        assert "accepted_by_judgment_run_id IS NOT NULL" in acceptance_sql
        assert "reviewed_at IS NOT NULL" in acceptance_sql
        assert "candidate_status <> 'accepted'" in acceptance_sql
        assert "accepted_by_judgment_run_id IS NULL" in acceptance_sql

        assert _foreign_key(table, f"fk_{table.name}_created_by_judgment_run").ondelete is None
        assert _foreign_key(table, f"fk_{table.name}_latest_judgment_run").ondelete is None
        assert _foreign_key(table, f"fk_{table.name}_accepted_by_judgment_run").ondelete is None
        assert _foreign_key(table, f"fk_{table.name}_created_by").ondelete == "SET NULL"
        assert _foreign_key(table, f"fk_{table.name}_reviewed_by").ondelete == "SET NULL"
        assert _unique_constraint_columns(table, f"uq_{table.name}_formal_gate") == [
            "id",
            "accepted_by_judgment_run_id",
        ]
        open_index = _index(table, f"uq_{table.name}_open_candidate")
        assert str(open_index.dialect_options["postgresql"]["where"]) == (
            "candidate_status IN ('proposed', 'needs_review')"
        )

    route_table = RouteConceptCandidate.__table__
    route_version_fk = _foreign_key(route_table, "fk_route_concept_candidates_route_version_book")
    assert [element.parent.name for element in route_version_fk.elements] == ["route_version_id", "route_book_id"]
    assert [element.column.table.name for element in route_version_fk.elements] == ["route_versions", "route_versions"]
    assert route_version_fk.ondelete is None
    assert _unique_constraint_columns(route_table, "uq_route_concept_candidates_idempotency") == [
        "route_book_id",
        "route_version_id",
        "concept_node_id",
        "relation_type",
        "created_by_judgment_run_id",
    ]

    segment_table = SegmentConceptCandidate.__table__
    segment_fk = _foreign_key(segment_table, "fk_segment_concept_candidates_segment")
    assert [element.parent.name for element in segment_fk.elements] == ["segment_id"]
    assert [element.column.table.name for element in segment_fk.elements] == ["route_cognition_segments"]
    assert segment_fk.ondelete is None

    collection_table = CollectionConceptCandidate.__table__
    collection_fk = _foreign_key(collection_table, "fk_collection_concept_candidates_collection")
    assert [element.parent.name for element in collection_fk.elements] == ["collection_id"]
    assert [element.column.table.name for element in collection_fk.elements] == ["route_collections"]
    assert collection_fk.ondelete is None


def test_step_b_migration_creates_only_typed_concept_relationship_candidates():
    migration_text = MIGRATION.read_text(encoding="utf-8")
    migration_module = _load_migration_module()

    assert 'revision = "20260618_concept_rel_candidates"' in migration_text
    assert len("20260618_concept_rel_candidates") <= 32
    assert 'down_revision = "20260618_concept_nodes"' in migration_text
    for table_name in CANDIDATE_TABLES:
        assert f'"{table_name}"' in migration_text
        constraint_names = {constraint.name for constraint in migration_module._common_constraints(table_name)}
        assert f"ck_{table_name}_acceptance_gate" in constraint_names
        assert f"uq_{table_name}_formal_gate" in constraint_names
        assert "postgresql_where=sa.text(\"candidate_status IN ('proposed', 'needs_review')\")" in migration_text
        assert f'"{table_name}",' in migration_text
        assert 'f"uq_{table_name}_open_candidate"' in migration_text

    for forbidden in (
        "route_concept_links",
        "segment_concept_links",
        "collection_concept_links",
        "route_segments",
        "collection_routes",
        "collection_segments",
        "segment_submissions",
        "entity_type",
        "entity_id",
        "APIRouter",
    ):
        assert forbidden not in migration_text


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("concept_relationship_candidates_migration", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_step_b_status_doc_records_candidate_boundaries():
    status_text = Path("docs/research/route_cognition_v1_1_status.md").read_text(encoding="utf-8")

    assert "v1.1 remaining step B: typed concept relationship candidate tables" in status_text
    assert "Concept formal links are not implemented" in status_text
    assert "route/segment/collection membership formal tables are not implemented" in status_text
    assert "other candidate tables are not implemented" in status_text
    assert "segment_submissions are not implemented" in status_text
    assert "No public API." in status_text
    assert "No admin UI." in status_text
    assert "external search worker is not implemented" in status_text


@pytest.fixture()
def concept_candidate_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_step_b_tables(db)
    _create_step_b_sqlite_tables(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_step_b_tables(db)


def test_valid_candidate_inserts_for_all_three_tables(db, concept_candidate_sqlite_tables):
    _seed_step_b_base(db)
    _insert_route_candidate(db)
    _insert_segment_candidate(db)
    _insert_collection_candidate(db)

    assert db.execute(text("SELECT count(*) FROM route_concept_candidates")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM segment_concept_candidates")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM collection_concept_candidates")).scalar_one() == 1


@pytest.mark.parametrize("table_kind", ["route", "segment", "collection"])
def test_missing_created_by_judgment_run_is_rejected(db, concept_candidate_sqlite_tables, table_kind):
    _seed_step_b_base(db)

    with pytest.raises(IntegrityError):
        _insert_candidate_for_kind(db, table_kind, created_by_judgment_run_id=None)


@pytest.mark.parametrize("table_kind", ["route", "segment", "collection"])
def test_missing_latest_judgment_run_is_rejected(db, concept_candidate_sqlite_tables, table_kind):
    _seed_step_b_base(db)

    with pytest.raises(IntegrityError):
        _insert_candidate_for_kind(db, table_kind, latest_judgment_run_id=None)


@pytest.mark.parametrize("table_kind", ["route", "segment", "collection"])
def test_accepted_candidate_requires_accepted_judgment_run(db, concept_candidate_sqlite_tables, table_kind):
    _seed_step_b_base(db)

    with pytest.raises(IntegrityError):
        _insert_candidate_for_kind(
            db,
            table_kind,
            candidate_status="accepted",
            accepted_by_judgment_run_id=None,
            reviewed_at="2026-06-18T12:00:00Z",
        )


@pytest.mark.parametrize("table_kind", ["route", "segment", "collection"])
def test_accepted_candidate_requires_reviewed_at(db, concept_candidate_sqlite_tables, table_kind):
    _seed_step_b_base(db)

    with pytest.raises(IntegrityError):
        _insert_candidate_for_kind(
            db,
            table_kind,
            candidate_status="accepted",
            accepted_by_judgment_run_id=3,
            reviewed_at=None,
        )


@pytest.mark.parametrize("table_kind", ["route", "segment", "collection"])
def test_non_accepted_candidate_cannot_keep_accepted_judgment_run(db, concept_candidate_sqlite_tables, table_kind):
    _seed_step_b_base(db)

    with pytest.raises(IntegrityError):
        _insert_candidate_for_kind(
            db,
            table_kind,
            candidate_status="rejected",
            accepted_by_judgment_run_id=3,
        )


@pytest.mark.parametrize("relation_type", ["related_to", "generic", "bad_relation"])
def test_invalid_relation_type_is_rejected(db, concept_candidate_sqlite_tables, relation_type):
    _seed_step_b_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_candidate(db, relation_type=relation_type)


@pytest.mark.parametrize("candidate_status", ["pending", "approved", "bad_status"])
def test_invalid_candidate_status_is_rejected(db, concept_candidate_sqlite_tables, candidate_status):
    _seed_step_b_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_candidate(db, candidate_status=candidate_status)


@pytest.mark.parametrize("latest_confidence_state", ["accepted", "unknown", "bad_state"])
def test_invalid_latest_confidence_state_is_rejected(
    db, concept_candidate_sqlite_tables, latest_confidence_state
):
    _seed_step_b_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_candidate(db, latest_confidence_state=latest_confidence_state)


@pytest.mark.parametrize("candidate_status", ["stale", "inconclusive"])
def test_stale_and_inconclusive_candidates_are_allowed(db, concept_candidate_sqlite_tables, candidate_status):
    _seed_step_b_base(db)
    _insert_route_candidate(db, candidate_status=candidate_status)

    assert db.execute(text("SELECT candidate_status FROM route_concept_candidates")).scalar_one() == candidate_status


def test_route_version_book_mismatch_is_rejected(db, concept_candidate_sqlite_tables):
    _seed_step_b_base(db)

    with pytest.raises(IntegrityError):
        _insert_route_candidate(db, route_book_id=2, route_version_id=1)


def test_segment_candidate_cannot_target_raw_segment(db, concept_candidate_sqlite_tables):
    _seed_step_b_base(db)

    with pytest.raises(IntegrityError):
        _insert_segment_candidate(db, segment_id=2, segment_geometry_hash="raw-segment-hash")


def test_partial_unique_open_candidate_rejects_duplicate_open_candidate(db, concept_candidate_sqlite_tables):
    _seed_step_b_base(db)
    _insert_route_candidate(db, id=1, candidate_status="proposed", created_by_judgment_run_id=1)

    with pytest.raises(IntegrityError):
        _insert_route_candidate(db, id=2, candidate_status="needs_review", created_by_judgment_run_id=2)


def test_rejected_history_does_not_block_new_proposed_candidate(db, concept_candidate_sqlite_tables):
    _seed_step_b_base(db)
    _insert_route_candidate(db, id=1, candidate_status="rejected", created_by_judgment_run_id=1)
    _insert_route_candidate(db, id=2, candidate_status="proposed", created_by_judgment_run_id=2)

    assert db.execute(text("SELECT count(*) FROM route_concept_candidates")).scalar_one() == 2


def test_no_forbidden_tables_are_created_in_sqlite_contract(db, concept_candidate_sqlite_tables):
    forbidden_tables = (
        "route_concept_links",
        "segment_concept_links",
        "collection_concept_links",
        "route_segments",
        "collection_routes",
        "collection_segments",
        "segment_submissions",
        "generic_candidates",
        "concept_candidates",
    )

    for table_name in forbidden_tables:
        row = db.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
            {"table_name": table_name},
        ).first()
        assert row is None


def test_step_b_git_diff_stays_inside_allowed_files():
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    )
    changed_files = {line for line in result.stdout.splitlines() if line}

    allowed_files = {
        "app/route_cognition/models.py",
        "migrations/versions/20260618_concept_relationship_candidates.py",
        "tests/test_route_cognition_concept_relationship_candidates.py",
        "docs/research/route_cognition_v1_1_status.md",
    }
    assert changed_files <= allowed_files
    assert not any(path.startswith("content/routes/") for path in changed_files)
    assert "guide.md" not in changed_files
    assert "app/admin/router.py" not in changed_files


def _seed_step_b_base(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO users (id, openid, is_admin)
            VALUES (1, 'concept_candidate_user', 1)
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (id)
            VALUES (1), (2), (3)
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
            VALUES (1, 1, 1, 'manual_drawn', 'LINESTRING(0 0, 1 1)', 'route-hash-a', 10000.0)
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO segments (id, name, distance, start_lat, start_lon, end_lat, end_lon, reference_line)
            VALUES
              (1, 'Whitelisted Segment', 1000.0, 37.8, 112.5, 37.9, 112.6, 'LINESTRING(0 0, 1 1)'),
              (2, 'Raw Segment', 1000.0, 37.8, 112.5, 37.9, 112.6, 'LINESTRING(0 0, 1 1)')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_cognition_segments (segment_id, geometry_hash)
            VALUES (1, 'segment-hash-a')
            """
        )
    )
    db.execute(text("INSERT INTO concept_nodes (id) VALUES (1)"))
    db.execute(text("INSERT INTO route_collections (id) VALUES (1)"))


def _insert_candidate_for_kind(db, table_kind: str, **kwargs) -> None:
    if table_kind == "route":
        _insert_route_candidate(db, **kwargs)
    elif table_kind == "segment":
        _insert_segment_candidate(db, **kwargs)
    elif table_kind == "collection":
        _insert_collection_candidate(db, **kwargs)
    else:
        raise AssertionError(f"unknown table kind: {table_kind}")


def _insert_route_candidate(
    db,
    *,
    id: int = 1,
    route_book_id: int = 1,
    route_version_id: int = 1,
    route_line_hash: str = "route-hash-a",
    concept_node_id: int = 1,
    relation_type: str = "training_theme",
    proposer_kind: str = "agent",
    candidate_status: str = "proposed",
    created_by_judgment_run_id: int | None = 1,
    latest_judgment_run_id: int | None = 2,
    accepted_by_judgment_run_id: int | None = None,
    latest_confidence_state: str = "proposed",
    reviewed_at: str | None = None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO route_concept_candidates (
                id, route_book_id, route_version_id, route_line_hash, concept_node_id,
                relation_type, proposer_kind, candidate_status, created_by_judgment_run_id,
                latest_judgment_run_id, accepted_by_judgment_run_id, latest_confidence,
                latest_confidence_state, latest_evidence_summary_json,
                latest_missing_data_summary_json, latest_contradiction_summary_json,
                reason_summary, metadata_json, created_by, reviewed_by, reviewed_at
            )
            VALUES (
                :id, :route_book_id, :route_version_id, :route_line_hash, :concept_node_id,
                :relation_type, :proposer_kind, :candidate_status, :created_by_judgment_run_id,
                :latest_judgment_run_id, :accepted_by_judgment_run_id, 0.8,
                :latest_confidence_state, NULL, NULL, NULL,
                'candidate reason', NULL, 1, NULL, :reviewed_at
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
            "proposer_kind": proposer_kind,
            "candidate_status": candidate_status,
            "created_by_judgment_run_id": created_by_judgment_run_id,
            "latest_judgment_run_id": latest_judgment_run_id,
            "accepted_by_judgment_run_id": accepted_by_judgment_run_id,
            "latest_confidence_state": latest_confidence_state,
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
    proposer_kind: str = "algorithm",
    candidate_status: str = "proposed",
    created_by_judgment_run_id: int | None = 1,
    latest_judgment_run_id: int | None = 2,
    accepted_by_judgment_run_id: int | None = None,
    latest_confidence_state: str = "proposed",
    reviewed_at: str | None = None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO segment_concept_candidates (
                id, segment_id, segment_geometry_hash, concept_node_id,
                relation_type, proposer_kind, candidate_status, created_by_judgment_run_id,
                latest_judgment_run_id, accepted_by_judgment_run_id, latest_confidence,
                latest_confidence_state, latest_evidence_summary_json,
                latest_missing_data_summary_json, latest_contradiction_summary_json,
                reason_summary, metadata_json, created_by, reviewed_by, reviewed_at
            )
            VALUES (
                :id, :segment_id, :segment_geometry_hash, :concept_node_id,
                :relation_type, :proposer_kind, :candidate_status, :created_by_judgment_run_id,
                :latest_judgment_run_id, :accepted_by_judgment_run_id, 0.7,
                :latest_confidence_state, NULL, NULL, NULL,
                'candidate reason', NULL, 1, NULL, :reviewed_at
            )
            """
        ),
        {
            "id": id,
            "segment_id": segment_id,
            "segment_geometry_hash": segment_geometry_hash,
            "concept_node_id": concept_node_id,
            "relation_type": relation_type,
            "proposer_kind": proposer_kind,
            "candidate_status": candidate_status,
            "created_by_judgment_run_id": created_by_judgment_run_id,
            "latest_judgment_run_id": latest_judgment_run_id,
            "accepted_by_judgment_run_id": accepted_by_judgment_run_id,
            "latest_confidence_state": latest_confidence_state,
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
    proposer_kind: str = "human",
    candidate_status: str = "proposed",
    created_by_judgment_run_id: int | None = 1,
    latest_judgment_run_id: int | None = 2,
    accepted_by_judgment_run_id: int | None = None,
    latest_confidence_state: str = "proposed",
    reviewed_at: str | None = None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO collection_concept_candidates (
                id, collection_id, concept_node_id,
                relation_type, proposer_kind, candidate_status, created_by_judgment_run_id,
                latest_judgment_run_id, accepted_by_judgment_run_id, latest_confidence,
                latest_confidence_state, latest_evidence_summary_json,
                latest_missing_data_summary_json, latest_contradiction_summary_json,
                reason_summary, metadata_json, created_by, reviewed_by, reviewed_at
            )
            VALUES (
                :id, :collection_id, :concept_node_id,
                :relation_type, :proposer_kind, :candidate_status, :created_by_judgment_run_id,
                :latest_judgment_run_id, :accepted_by_judgment_run_id, 0.9,
                :latest_confidence_state, NULL, NULL, NULL,
                'candidate reason', NULL, 1, NULL, :reviewed_at
            )
            """
        ),
        {
            "id": id,
            "collection_id": collection_id,
            "concept_node_id": concept_node_id,
            "relation_type": relation_type,
            "proposer_kind": proposer_kind,
            "candidate_status": candidate_status,
            "created_by_judgment_run_id": created_by_judgment_run_id,
            "latest_judgment_run_id": latest_judgment_run_id,
            "accepted_by_judgment_run_id": accepted_by_judgment_run_id,
            "latest_confidence_state": latest_confidence_state,
            "reviewed_at": reviewed_at,
        },
    )


def _create_step_b_sqlite_tables(db) -> None:
    db.execute(text("CREATE TABLE judgment_runs (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE concept_nodes (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE route_collections (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(
        text(
            """
            CREATE TABLE route_cognition_segments (
                segment_id INTEGER PRIMARY KEY,
                geometry_hash TEXT NOT NULL,
                eligibility_status TEXT NOT NULL DEFAULT 'active',
                FOREIGN KEY(segment_id) REFERENCES segments(id)
            )
            """
        )
    )
    _create_candidate_sqlite_table(
        db,
        table_name="route_concept_candidates",
        target_columns="""
            route_book_id INTEGER NOT NULL,
            route_version_id INTEGER NOT NULL,
            route_line_hash TEXT NOT NULL,
            concept_node_id INTEGER NOT NULL,
        """,
        target_constraints="""
            FOREIGN KEY(route_book_id) REFERENCES route_books(id),
            FOREIGN KEY(route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id),
            FOREIGN KEY(concept_node_id) REFERENCES concept_nodes(id),
            UNIQUE(route_book_id, route_version_id, concept_node_id, relation_type, created_by_judgment_run_id)
        """,
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_route_concept_candidates_open_candidate
            ON route_concept_candidates(route_book_id, route_version_id, concept_node_id, relation_type)
            WHERE candidate_status IN ('proposed', 'needs_review')
            """
        )
    )
    _create_candidate_sqlite_table(
        db,
        table_name="segment_concept_candidates",
        target_columns="""
            segment_id INTEGER NOT NULL,
            segment_geometry_hash TEXT NOT NULL,
            concept_node_id INTEGER NOT NULL,
        """,
        target_constraints="""
            FOREIGN KEY(segment_id) REFERENCES route_cognition_segments(segment_id),
            FOREIGN KEY(concept_node_id) REFERENCES concept_nodes(id),
            UNIQUE(segment_id, concept_node_id, relation_type, created_by_judgment_run_id)
        """,
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_segment_concept_candidates_open_candidate
            ON segment_concept_candidates(segment_id, concept_node_id, relation_type)
            WHERE candidate_status IN ('proposed', 'needs_review')
            """
        )
    )
    _create_candidate_sqlite_table(
        db,
        table_name="collection_concept_candidates",
        target_columns="""
            collection_id INTEGER NOT NULL,
            concept_node_id INTEGER NOT NULL,
        """,
        target_constraints="""
            FOREIGN KEY(collection_id) REFERENCES route_collections(id),
            FOREIGN KEY(concept_node_id) REFERENCES concept_nodes(id),
            UNIQUE(collection_id, concept_node_id, relation_type, created_by_judgment_run_id)
        """,
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_collection_concept_candidates_open_candidate
            ON collection_concept_candidates(collection_id, concept_node_id, relation_type)
            WHERE candidate_status IN ('proposed', 'needs_review')
            """
        )
    )


def _create_candidate_sqlite_table(db, *, table_name: str, target_columns: str, target_constraints: str) -> None:
    db.execute(
        text(
            f"""
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {target_columns}
                relation_type TEXT NOT NULL,
                proposer_kind TEXT NOT NULL,
                candidate_status TEXT NOT NULL,
                created_by_judgment_run_id INTEGER NOT NULL,
                latest_judgment_run_id INTEGER NOT NULL,
                accepted_by_judgment_run_id INTEGER,
                latest_confidence REAL,
                latest_confidence_state TEXT NOT NULL,
                latest_evidence_summary_json TEXT,
                latest_missing_data_summary_json TEXT,
                latest_contradiction_summary_json TEXT,
                reason_summary TEXT,
                metadata_json TEXT,
                created_by INTEGER,
                reviewed_by INTEGER,
                reviewed_at DATETIME,
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
                CHECK (proposer_kind IN ('algorithm', 'agent', 'human', 'imported')),
                CHECK (
                    candidate_status IN (
                        'proposed',
                        'needs_review',
                        'accepted',
                        'rejected',
                        'withdrawn',
                        'superseded',
                        'stale',
                        'inconclusive'
                    )
                ),
                CHECK (latest_confidence IS NULL OR latest_confidence BETWEEN 0 AND 1),
                CHECK (
                    latest_confidence_state IN (
                        'raw',
                        'proposed',
                        'challenged',
                        'stable',
                        'human_accepted',
                        'stale',
                        'inconclusive'
                    )
                ),
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
                UNIQUE(id, accepted_by_judgment_run_id),
                FOREIGN KEY(created_by_judgment_run_id) REFERENCES judgment_runs(id),
                FOREIGN KEY(latest_judgment_run_id) REFERENCES judgment_runs(id),
                FOREIGN KEY(accepted_by_judgment_run_id) REFERENCES judgment_runs(id),
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
                {target_constraints}
            )
            """
        )
    )


def _drop_step_b_tables(db) -> None:
    for table_name in (
        "collection_concept_candidates",
        "segment_concept_candidates",
        "route_concept_candidates",
        "route_cognition_segments",
        "route_collections",
        "concept_nodes",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
