"""概念候选写入测试——只允许把关系判断放进待审队列，不盖正式章。"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.route_cognition.services.concept_candidate_writer import (
    ConceptCandidateWriterError,
    propose_collection_concept_candidate,
    propose_route_concept_candidate,
    propose_segment_concept_candidate,
)


FORBIDDEN_EMPTY_TABLES = (
    "route_concept_links",
    "segment_concept_links",
    "collection_concept_links",
    "evidence_items",
    "collection_routes",
    "collection_segments",
    "route_segments",
    "segment_submissions",
)


@pytest.fixture()
def concept_candidate_writer_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_candidate_writer_tables(db)
    _create_candidate_writer_tables(db)
    _seed_base_rows(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_candidate_writer_tables(db)


def test_valid_route_concept_candidate_succeeds_and_copies_route_line_hash(
    db, concept_candidate_writer_sqlite_tables
):
    candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=1,
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )

    assert candidate.id == 1
    assert candidate.candidate_status == "proposed"
    assert candidate.accepted_by_judgment_run_id is None
    assert candidate.latest_judgment_run_id == 1
    assert candidate.route_line_hash == "route-hash-a"
    assert db.execute(text("SELECT route_line_hash FROM route_concept_candidates")).scalar_one() == "route-hash-a"


def test_route_version_book_mismatch_fails(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="route_version"):
        propose_route_concept_candidate(
            db,
            route_book_id=2,
            route_version_id=1,
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="agent",
            created_by_judgment_run_id=2,
        )


def test_route_candidate_missing_concept_node_fails(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="concept_node"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=999,
            relation_type="training_theme",
            proposer_kind="agent",
            created_by_judgment_run_id=1,
        )


@pytest.mark.parametrize("judgment_run_id", [3, 4, 5])
def test_failed_running_or_cancelled_judgment_cannot_create_route_candidate(
    db, concept_candidate_writer_sqlite_tables, judgment_run_id
):
    with pytest.raises(ConceptCandidateWriterError, match="succeeded"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="agent",
            created_by_judgment_run_id=judgment_run_id,
        )


def test_created_by_judgment_run_id_must_exist(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="created_by_judgment_run_id"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="agent",
            created_by_judgment_run_id=999,
        )


@pytest.mark.parametrize("latest_judgment_run_id", [3, 4, 5, 999])
def test_latest_judgment_run_id_must_exist_and_be_succeeded(
    db, concept_candidate_writer_sqlite_tables, latest_judgment_run_id
):
    with pytest.raises(ConceptCandidateWriterError, match="latest_judgment_run_id"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="agent",
            created_by_judgment_run_id=1,
            latest_judgment_run_id=latest_judgment_run_id,
        )


def test_invalid_relation_type_fails(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="relation_type"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=1,
            relation_type="related_to",
            proposer_kind="agent",
            created_by_judgment_run_id=1,
        )


def test_invalid_proposer_kind_fails(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="proposer_kind"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="semantic_agent",
            created_by_judgment_run_id=1,
        )


@pytest.mark.parametrize(
    "candidate_status",
    ["accepted", "rejected", "withdrawn", "superseded", "stale", "inconclusive"],
)
def test_writer_only_allows_proposed_or_needs_review_candidate_status(
    db, concept_candidate_writer_sqlite_tables, candidate_status
):
    with pytest.raises(ConceptCandidateWriterError, match="candidate_status"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="agent",
            candidate_status=candidate_status,
            created_by_judgment_run_id=1,
        )
    with pytest.raises(ConceptCandidateWriterError, match="candidate_status"):
        propose_segment_concept_candidate(
            db,
            segment_id=1,
            concept_node_id=1,
            relation_type="has_feature",
            proposer_kind="algorithm",
            candidate_status=candidate_status,
            created_by_judgment_run_id=1,
        )
    with pytest.raises(ConceptCandidateWriterError, match="candidate_status"):
        propose_collection_concept_candidate(
            db,
            collection_id=1,
            concept_node_id=1,
            relation_type="associated_with",
            proposer_kind="human",
            candidate_status=candidate_status,
            created_by_judgment_run_id=1,
        )


def test_route_writer_does_not_accept_manual_route_line_hash(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(TypeError):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            route_line_hash="wrong-hash",
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="agent",
            created_by_judgment_run_id=1,
        )


def test_route_writer_does_not_create_route_concept_links(db, concept_candidate_writer_sqlite_tables):
    propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=1,
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )

    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


def test_valid_segment_concept_candidate_succeeds_and_copies_geometry_hash(
    db, concept_candidate_writer_sqlite_tables
):
    candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=1,
        relation_type="has_feature",
        proposer_kind="algorithm",
        created_by_judgment_run_id=1,
    )

    assert candidate.id == 1
    assert candidate.segment_geometry_hash == "segment-hash-a"
    assert candidate.candidate_status == "proposed"
    assert candidate.accepted_by_judgment_run_id is None
    assert db.execute(text("SELECT segment_geometry_hash FROM segment_concept_candidates")).scalar_one() == (
        "segment-hash-a"
    )


def test_raw_segment_without_route_cognition_entry_fails(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="route_cognition_segments"):
        propose_segment_concept_candidate(
            db,
            segment_id=2,
            concept_node_id=1,
            relation_type="has_feature",
            proposer_kind="algorithm",
            created_by_judgment_run_id=2,
        )


def test_segment_candidate_missing_concept_node_fails(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="concept_node"):
        propose_segment_concept_candidate(
            db,
            segment_id=1,
            concept_node_id=999,
            relation_type="has_feature",
            proposer_kind="algorithm",
            created_by_judgment_run_id=1,
        )


def test_segment_writer_does_not_accept_manual_segment_geometry_hash(
    db, concept_candidate_writer_sqlite_tables
):
    with pytest.raises(TypeError):
        propose_segment_concept_candidate(
            db,
            segment_id=1,
            segment_geometry_hash="wrong-hash",
            concept_node_id=1,
            relation_type="has_feature",
            proposer_kind="algorithm",
            created_by_judgment_run_id=1,
        )


def test_segment_writer_does_not_mutate_links_segments_or_efforts(db, concept_candidate_writer_sqlite_tables):
    before_segments = _simple_table_snapshot(db, "segments")
    before_efforts = _simple_table_snapshot(db, "segment_efforts")

    propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=1,
        relation_type="has_feature",
        proposer_kind="algorithm",
        created_by_judgment_run_id=1,
    )

    assert db.execute(text("SELECT count(*) FROM segment_concept_links")).scalar_one() == 0
    assert _simple_table_snapshot(db, "segments") == before_segments
    assert _simple_table_snapshot(db, "segment_efforts") == before_efforts


def test_valid_collection_concept_candidate_succeeds(db, concept_candidate_writer_sqlite_tables):
    candidate = propose_collection_concept_candidate(
        db,
        collection_id=1,
        concept_node_id=1,
        relation_type="associated_with",
        proposer_kind="human",
        created_by_judgment_run_id=1,
    )

    assert candidate.id == 1
    assert candidate.collection_id == 1
    assert candidate.candidate_status == "proposed"
    assert candidate.accepted_by_judgment_run_id is None


def test_succeeded_human_review_judgment_can_propose_candidate(db, concept_candidate_writer_sqlite_tables):
    candidate = propose_collection_concept_candidate(
        db,
        collection_id=1,
        concept_node_id=1,
        relation_type="associated_with",
        proposer_kind="human",
        created_by_judgment_run_id=7,
    )

    assert candidate.latest_judgment_run_id == 7
    assert candidate.accepted_by_judgment_run_id is None


def test_collection_candidate_missing_collection_fails(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="collection"):
        propose_collection_concept_candidate(
            db,
            collection_id=999,
            concept_node_id=1,
            relation_type="associated_with",
            proposer_kind="human",
            created_by_judgment_run_id=1,
        )


def test_collection_candidate_missing_concept_node_fails(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="concept_node"):
        propose_collection_concept_candidate(
            db,
            collection_id=1,
            concept_node_id=999,
            relation_type="associated_with",
            proposer_kind="human",
            created_by_judgment_run_id=1,
        )


def test_collection_writer_does_not_mutate_links_or_membership_tables(
    db, concept_candidate_writer_sqlite_tables
):
    propose_collection_concept_candidate(
        db,
        collection_id=1,
        concept_node_id=1,
        relation_type="associated_with",
        proposer_kind="human",
        created_by_judgment_run_id=1,
    )

    assert db.execute(text("SELECT count(*) FROM collection_concept_links")).scalar_one() == 0
    assert db.execute(text("SELECT count(*) FROM collection_routes")).scalar_one() == 0
    assert db.execute(text("SELECT count(*) FROM collection_segments")).scalar_one() == 0


def test_missing_created_by_judgment_run_id_fails(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="created_by_judgment_run_id"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="agent",
            created_by_judgment_run_id=None,
        )


def test_latest_judgment_run_id_defaults_to_created_by_judgment_run_id(
    db, concept_candidate_writer_sqlite_tables
):
    candidate = propose_collection_concept_candidate(
        db,
        collection_id=1,
        concept_node_id=1,
        relation_type="associated_with",
        proposer_kind="human",
        created_by_judgment_run_id=2,
    )

    assert candidate.latest_judgment_run_id == 2
    assert candidate.latest_confidence == pytest.approx(0.82)
    assert candidate.latest_confidence_state == "stable"


def test_route_candidate_created_judgment_target_mismatch_fails(
    db, concept_candidate_writer_sqlite_tables
):
    with pytest.raises(ConceptCandidateWriterError, match="route_book_id"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="agent",
            created_by_judgment_run_id=6,
        )


def test_route_candidate_latest_judgment_target_mismatch_fails(
    db, concept_candidate_writer_sqlite_tables
):
    with pytest.raises(ConceptCandidateWriterError, match="latest_judgment_run_id"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="agent",
            created_by_judgment_run_id=1,
            latest_judgment_run_id=6,
        )


def test_segment_candidate_judgment_target_mismatch_fails(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="segment_id"):
        propose_segment_concept_candidate(
            db,
            segment_id=1,
            concept_node_id=1,
            relation_type="has_feature",
            proposer_kind="algorithm",
            created_by_judgment_run_id=6,
        )


def test_latest_projection_cannot_be_overridden(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="latest_confidence"):
        propose_collection_concept_candidate(
            db,
            collection_id=1,
            concept_node_id=1,
            relation_type="associated_with",
            proposer_kind="human",
            created_by_judgment_run_id=2,
            latest_confidence=0.1,
        )


def test_latest_summary_projection_cannot_be_faked(db, concept_candidate_writer_sqlite_tables):
    with pytest.raises(ConceptCandidateWriterError, match="latest_evidence_summary_json"):
        propose_collection_concept_candidate(
            db,
            collection_id=1,
            concept_node_id=1,
            relation_type="associated_with",
            proposer_kind="human",
            created_by_judgment_run_id=2,
            latest_evidence_summary_json={"fake": True},
        )


@pytest.mark.parametrize(
    ("metadata_json", "blocked_key"),
    [
        ({"route_book_id": 1}, "route_book_id"),
        ({"nested": {"segment_id": 1}}, "segment_id"),
        ({"items": [{"collection_id": 1}]}, "collection_id"),
        ({"source_candidate_id": 1}, "source_candidate_id"),
        ({"relation_type": "has_feature"}, "relation_type"),
        ({"formal_link_id": 1}, "formal_link_id"),
        ({"routeIds": [1]}, "routeIds"),
        ({"relationType": "has_feature"}, "relationType"),
        ({"formalLinkIds": [1]}, "formalLinkIds"),
        ({"route-ids": [1]}, "route-ids"),
        ({"members": [{"kind": "routes", "slug": "west-hills"}]}, "members"),
        ({"routes": ["west-hills"]}, "routes"),
        ({"segments": ["climb"]}, "segments"),
        ({"collections": ["xishan"]}, "collections"),
        ({"ordering": ["route-1"]}, "ordering"),
        ({"roles": {"route-1": "main"}}, "roles"),
    ],
)
def test_metadata_json_cannot_hide_target_or_relationship_truth(
    db, concept_candidate_writer_sqlite_tables, metadata_json, blocked_key
):
    with pytest.raises(ConceptCandidateWriterError, match=blocked_key):
        propose_collection_concept_candidate(
            db,
            collection_id=1,
            concept_node_id=1,
            relation_type="associated_with",
            proposer_kind="human",
            created_by_judgment_run_id=1,
            metadata_json=metadata_json,
        )


def test_duplicate_open_candidate_is_blocked_by_db_partial_unique(
    db, concept_candidate_writer_sqlite_tables
):
    propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=1,
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )

    with pytest.raises(IntegrityError):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=1,
            relation_type="training_theme",
            proposer_kind="agent",
            candidate_status="needs_review",
            created_by_judgment_run_id=2,
        )


def test_rejected_history_does_not_block_new_proposed_candidate(db, concept_candidate_writer_sqlite_tables):
    _insert_rejected_route_candidate(db)

    candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=1,
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )

    assert candidate.id == 2
    assert db.execute(text("SELECT count(*) FROM route_concept_candidates")).scalar_one() == 2


def test_writer_does_not_create_evidence_or_mutate_route_and_content_surfaces(
    db, concept_candidate_writer_sqlite_tables
):
    before_route_books = _simple_table_snapshot(db, "route_books")
    before_route_versions = _simple_table_snapshot(db, "route_versions")
    before_route_guides = _route_guides_snapshot(db)
    before_content_routes = _content_routes_snapshot()

    propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=1,
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )

    for table_name in FORBIDDEN_EMPTY_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0
    assert _simple_table_snapshot(db, "route_books") == before_route_books
    assert _simple_table_snapshot(db, "route_versions") == before_route_versions
    assert _route_guides_snapshot(db) == before_route_guides
    assert _content_routes_snapshot() == before_content_routes


def test_writer_does_not_call_commit(db, concept_candidate_writer_sqlite_tables, monkeypatch):
    def fail_commit():
        raise AssertionError("candidate writer must not commit")

    monkeypatch.setattr(db, "commit", fail_commit)

    propose_collection_concept_candidate(
        db,
        collection_id=1,
        concept_node_id=1,
        relation_type="associated_with",
        proposer_kind="human",
        created_by_judgment_run_id=1,
    )


def _content_routes_snapshot() -> set[str]:
    file_hashes = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in Path("content/routes").glob("**/*")
        if path.is_file()
    }
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "content/routes"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {f"{path}:{digest}" for path, digest in file_hashes.items()} | {
        f"git-diff:{path}" for path in result.stdout.splitlines()
    }


def _route_guides_snapshot(db) -> list[tuple[int, str, str]]:
    return [
        (row.id, row.name, row.content_md)
        for row in db.execute(
            text("SELECT id, name, content_md FROM route_guides ORDER BY id")
        ).all()
    ]


def _simple_table_snapshot(db, table_name: str) -> list[tuple]:
    return [tuple(row) for row in db.execute(text(f"SELECT * FROM {table_name} ORDER BY id")).all()]


def _seed_base_rows(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (id, run_type, status, confidence_state)
            VALUES
                (1, 'semantic_agent', 'succeeded', 'proposed'),
                (2, 'spatial_algorithm', 'succeeded', 'stable'),
                (3, 'semantic_agent', 'failed', 'stale'),
                (4, 'spatial_algorithm', 'running', 'raw'),
                (5, 'human_review', 'cancelled', 'inconclusive'),
                (6, 'semantic_agent', 'succeeded', 'proposed'),
                (7, 'human_review', 'succeeded', 'stable')
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE judgment_runs
            SET route_book_id = 1, route_version_id = 1, segment_id = 1, confidence = 0.71
            WHERE id = 1
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE judgment_runs
            SET confidence = 0.82
            WHERE id = 2
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE judgment_runs
            SET route_book_id = 2, route_version_id = 2, segment_id = 2, confidence = 0.66
            WHERE id = 6
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_books (id, name)
            VALUES (1, 'Route A'), (2, 'Route B')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_versions (id, route_book_id, line_hash)
            VALUES
                (1, 1, 'route-hash-a'),
                (2, 2, 'route-hash-b')
            """
        )
    )
    db.execute(text("INSERT INTO concept_nodes (id) VALUES (1)"))
    db.execute(text("INSERT INTO route_collections (id) VALUES (1)"))
    db.execute(
        text(
            """
            INSERT INTO segments (id, reference_line)
            VALUES
                (1, 'LINESTRING(0 0, 1 1)'),
                (2, 'LINESTRING(0 0, 2 2)')
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
    db.execute(text("INSERT INTO segment_efforts (id, segment_id) VALUES (1, 1)"))
    db.execute(text("INSERT INTO route_guides (id, name, content_md) VALUES (1, 'Guide', 'original')"))


def _insert_rejected_route_candidate(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO route_concept_candidates (
                id, route_book_id, route_version_id, route_line_hash, concept_node_id,
                relation_type, proposer_kind, candidate_status, created_by_judgment_run_id,
                latest_judgment_run_id, accepted_by_judgment_run_id, latest_confidence,
                latest_confidence_state, reason_summary, metadata_json
            )
            VALUES (
                1, 1, 1, 'route-hash-a', 1,
                'training_theme', 'agent', 'rejected', 2,
                2, NULL, 0.8,
                'proposed', 'old rejected candidate', NULL
            )
            """
        )
    )


def _create_candidate_writer_tables(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE judgment_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence_state TEXT NOT NULL,
                route_book_id INTEGER,
                route_version_id INTEGER,
                segment_id INTEGER,
                confidence REAL,
                result_summary_json TEXT,
                missing_data_json TEXT,
                contradiction_json TEXT
            )
            """
        )
    )
    db.execute(text("CREATE TABLE route_books (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"))
    db.execute(
        text(
            """
            CREATE TABLE route_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_book_id INTEGER NOT NULL,
                line_hash TEXT NOT NULL
            )
            """
        )
    )
    db.execute(text("CREATE TABLE concept_nodes (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE route_collections (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(
        text(
            """
            CREATE TABLE segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_line TEXT
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE route_cognition_segments (
                segment_id INTEGER PRIMARY KEY,
                geometry_hash TEXT NOT NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE segment_efforts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id INTEGER NOT NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE route_guides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                content_md TEXT NOT NULL
            )
            """
        )
    )
    _create_route_concept_candidate_table(db)
    _create_segment_concept_candidate_table(db)
    _create_collection_concept_candidate_table(db)
    db.execute(text("CREATE TABLE route_concept_links (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE segment_concept_links (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_concept_links (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE evidence_items (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_routes (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_segments (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE route_segments (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE segment_submissions (id INTEGER PRIMARY KEY AUTOINCREMENT)"))


def _create_route_concept_candidate_table(db) -> None:
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """
        )
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


def _create_segment_concept_candidate_table(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE segment_concept_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id INTEGER NOT NULL,
                segment_geometry_hash TEXT NOT NULL,
                concept_node_id INTEGER NOT NULL,
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """
        )
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


def _create_collection_concept_candidate_table(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE collection_concept_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                concept_node_id INTEGER NOT NULL,
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """
        )
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


def _drop_candidate_writer_tables(db) -> None:
    for table_name in (
        "collection_segments",
        "collection_routes",
        "segment_submissions",
        "route_segments",
        "evidence_items",
        "collection_concept_links",
        "segment_concept_links",
        "route_concept_links",
        "collection_concept_candidates",
        "segment_concept_candidates",
        "route_concept_candidates",
        "route_guides",
        "segment_efforts",
        "route_cognition_segments",
        "segments",
        "route_collections",
        "concept_nodes",
        "route_versions",
        "route_books",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
