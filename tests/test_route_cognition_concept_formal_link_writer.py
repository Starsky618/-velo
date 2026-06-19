"""概念正式关系 writer 测试——把已接受候选盖章进档案柜，但不碰内容和成员表。"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.route_cognition.services.concept_candidate_writer import (
    propose_collection_concept_candidate,
    propose_route_concept_candidate,
    propose_segment_concept_candidate,
)
from app.route_cognition.services.concept_formal_link_writer import (
    ConceptFormalLinkWriterError,
    promote_collection_concept_candidate,
    promote_route_concept_candidate,
    promote_segment_concept_candidate,
)


FORBIDDEN_EMPTY_TABLES = (
    "evidence_items",
    "route_segments",
    "collection_routes",
    "collection_segments",
    "segment_submissions",
)


@pytest.fixture()
def concept_formal_link_writer_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_formal_link_writer_tables(db)
    _create_formal_link_writer_tables(db)
    _seed_formal_link_base_rows(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_formal_link_writer_tables(db)


def test_route_candidate_promotion_creates_formal_route_link_and_updates_candidate(
    db, concept_formal_link_writer_sqlite_tables
):
    candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=1,
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
        reason_summary="proposal reason",
    )

    link = promote_route_concept_candidate(
        db,
        candidate_id=candidate.id,
        accepted_judgment_run_id=10,
        reviewed_by=99,
    )
    updated_candidate = db.execute(
        text(
            """
            SELECT candidate_status, accepted_by_judgment_run_id, latest_judgment_run_id,
                   latest_confidence, latest_confidence_state, reviewed_by, reviewed_at
            FROM route_concept_candidates
            WHERE id = :candidate_id
            """
        ),
        {"candidate_id": candidate.id},
    ).one()

    assert updated_candidate.candidate_status == "accepted"
    assert updated_candidate.accepted_by_judgment_run_id == 10
    assert updated_candidate.latest_judgment_run_id == 10
    assert updated_candidate.latest_confidence == pytest.approx(0.95)
    assert updated_candidate.latest_confidence_state == "human_accepted"
    assert updated_candidate.reviewed_by == 99
    assert updated_candidate.reviewed_at is not None

    assert link.source_kind == "candidate_accepted"
    assert link.source_route_concept_candidate_id == candidate.id
    assert link.accepted_judgment_run_id == 10
    assert link.accepted_judgment_run_type == "human_review"
    assert link.link_status == "active"
    assert link.route_book_id == candidate.route_book_id
    assert link.route_version_id == candidate.route_version_id
    assert link.route_line_hash == candidate.route_line_hash
    assert link.concept_node_id == candidate.concept_node_id
    assert link.relation_type == candidate.relation_type
    assert link.reason_summary == "proposal reason"
    assert link.metadata_json is None
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM segment_concept_links")).scalar_one() == 0
    assert db.execute(text("SELECT count(*) FROM collection_concept_links")).scalar_one() == 0
    for table_name in FORBIDDEN_EMPTY_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0


def test_segment_candidate_promotion_copies_geometry_hash_and_keeps_other_surfaces_unchanged(
    db, concept_formal_link_writer_sqlite_tables
):
    before_segments = _simple_table_snapshot(db, "segments")
    before_efforts = _simple_table_snapshot(db, "segment_efforts")
    before_guides = _route_guides_snapshot(db)
    before_content_routes = _content_routes_snapshot()
    candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=1,
        relation_type="has_risk",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
    )

    link = promote_segment_concept_candidate(
        db,
        candidate_id=candidate.id,
        accepted_judgment_run_id=11,
    )

    assert link.source_kind == "candidate_accepted"
    assert link.source_segment_concept_candidate_id == candidate.id
    assert link.segment_id == candidate.segment_id
    assert link.segment_geometry_hash == candidate.segment_geometry_hash
    assert link.concept_node_id == candidate.concept_node_id
    assert link.relation_type == candidate.relation_type
    assert link.accepted_judgment_run_type == "human_review"
    assert link.metadata_json is None
    assert db.execute(text("SELECT count(*) FROM segment_concept_links")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0
    assert db.execute(text("SELECT count(*) FROM collection_concept_links")).scalar_one() == 0
    assert _simple_table_snapshot(db, "segments") == before_segments
    assert _simple_table_snapshot(db, "segment_efforts") == before_efforts
    assert _route_guides_snapshot(db) == before_guides
    assert _content_routes_snapshot() == before_content_routes


def test_collection_candidate_promotion_creates_formal_collection_link(
    db, concept_formal_link_writer_sqlite_tables
):
    before_guides = _route_guides_snapshot(db)
    before_content_routes = _content_routes_snapshot()
    candidate = propose_collection_concept_candidate(
        db,
        collection_id=1,
        concept_node_id=1,
        relation_type="associated_with",
        proposer_kind="human",
        created_by_judgment_run_id=3,
    )

    link = promote_collection_concept_candidate(
        db,
        candidate_id=candidate.id,
        accepted_judgment_run_id=11,
        reviewed_by=42,
    )

    assert link.source_kind == "candidate_accepted"
    assert link.source_collection_concept_candidate_id == candidate.id
    assert link.collection_id == candidate.collection_id
    assert link.concept_node_id == candidate.concept_node_id
    assert link.relation_type == candidate.relation_type
    assert link.accepted_judgment_run_id == 11
    assert link.accepted_judgment_run_type == "human_review"
    assert link.metadata_json is None
    assert db.execute(
        text("SELECT candidate_status FROM collection_concept_candidates WHERE id = :candidate_id"),
        {"candidate_id": candidate.id},
    ).scalar_one() == "accepted"
    for table_name in FORBIDDEN_EMPTY_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0
    assert _route_guides_snapshot(db) == before_guides
    assert _content_routes_snapshot() == before_content_routes


def test_needs_review_candidate_can_be_promoted(db, concept_formal_link_writer_sqlite_tables):
    candidate = propose_collection_concept_candidate(
        db,
        collection_id=1,
        concept_node_id=1,
        relation_type="story_reference",
        proposer_kind="human",
        candidate_status="needs_review",
        created_by_judgment_run_id=3,
    )

    link = promote_collection_concept_candidate(
        db,
        candidate_id=candidate.id,
        accepted_judgment_run_id=10,
    )

    assert link.source_collection_concept_candidate_id == candidate.id
    assert db.execute(
        text("SELECT candidate_status FROM collection_concept_candidates WHERE id = :candidate_id"),
        {"candidate_id": candidate.id},
    ).scalar_one() == "accepted"


@pytest.mark.parametrize("judgment_run_id", [12, 13])
def test_non_human_review_judgment_cannot_promote_route_candidate(
    db, concept_formal_link_writer_sqlite_tables, judgment_run_id
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

    with pytest.raises(ConceptFormalLinkWriterError, match="human_review"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=judgment_run_id,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


@pytest.mark.parametrize("judgment_run_id", [14, 15, 16])
def test_failed_running_or_cancelled_human_review_cannot_promote_route_candidate(
    db, concept_formal_link_writer_sqlite_tables, judgment_run_id
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

    with pytest.raises(ConceptFormalLinkWriterError, match="succeeded"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=judgment_run_id,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


def test_succeeded_human_review_with_unaccepted_confidence_state_cannot_promote(
    db, concept_formal_link_writer_sqlite_tables
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

    with pytest.raises(ConceptFormalLinkWriterError, match="confidence_state"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=17,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


@pytest.mark.parametrize(
    "candidate_status",
    ["rejected", "stale", "inconclusive", "withdrawn", "superseded"],
)
def test_terminal_candidate_status_cannot_be_promoted(
    db, concept_formal_link_writer_sqlite_tables, candidate_status
):
    candidate_id = _insert_route_candidate(db, candidate_status=candidate_status)

    with pytest.raises(ConceptFormalLinkWriterError, match="candidate_status"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate_id,
            accepted_judgment_run_id=10,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


def test_already_accepted_candidate_cannot_be_promoted_twice(db, concept_formal_link_writer_sqlite_tables):
    candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=1,
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )
    promote_route_concept_candidate(
        db,
        candidate_id=candidate.id,
        accepted_judgment_run_id=10,
    )

    with pytest.raises(ConceptFormalLinkWriterError, match="candidate_status"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=11,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 1


def test_active_duplicate_formal_link_is_blocked_and_candidate_rolls_back(
    db, concept_formal_link_writer_sqlite_tables
):
    first_candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=1,
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )
    promote_route_concept_candidate(
        db,
        candidate_id=first_candidate.id,
        accepted_judgment_run_id=10,
    )
    second_candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=1,
        relation_type="training_theme",
        proposer_kind="human",
        created_by_judgment_run_id=3,
    )
    db.commit()

    with pytest.raises(IntegrityError):
        promote_route_concept_candidate(
            db,
            candidate_id=second_candidate.id,
            accepted_judgment_run_id=11,
        )
    db.rollback()

    assert db.execute(
        text(
            """
            SELECT candidate_status, accepted_by_judgment_run_id
            FROM route_concept_candidates
            WHERE id = :candidate_id
            """
        ),
        {"candidate_id": second_candidate.id},
    ).one() == ("proposed", None)
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 1


def test_segment_candidate_missing_cognition_segment_cannot_promote(
    db, concept_formal_link_writer_sqlite_tables
):
    candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=1,
        relation_type="has_feature",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
    )
    db.execute(text("DELETE FROM route_cognition_segments WHERE segment_id = 1"))

    with pytest.raises(ConceptFormalLinkWriterError, match="route_cognition_segments"):
        promote_segment_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=10,
        )
    assert db.execute(text("SELECT count(*) FROM segment_concept_links")).scalar_one() == 0


def test_segment_candidate_geometry_hash_mismatch_cannot_promote(
    db, concept_formal_link_writer_sqlite_tables
):
    candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=1,
        relation_type="has_feature",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
    )
    db.execute(
        text("UPDATE route_cognition_segments SET geometry_hash = 'segment-hash-new' WHERE segment_id = 1")
    )

    with pytest.raises(ConceptFormalLinkWriterError, match="segment_geometry_hash"):
        promote_segment_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=10,
        )
    assert db.execute(text("SELECT count(*) FROM segment_concept_links")).scalar_one() == 0


def test_segment_acceptance_judgment_target_mismatch_cannot_promote(
    db, concept_formal_link_writer_sqlite_tables
):
    candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=1,
        relation_type="has_feature",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
    )

    with pytest.raises(ConceptFormalLinkWriterError, match="segment_id"):
        promote_segment_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=19,
        )
    assert db.execute(text("SELECT count(*) FROM segment_concept_links")).scalar_one() == 0


def test_segment_acceptance_judgment_with_route_target_cannot_promote(
    db, concept_formal_link_writer_sqlite_tables
):
    candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=1,
        relation_type="has_feature",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
    )

    with pytest.raises(ConceptFormalLinkWriterError, match="route_book_id"):
        promote_segment_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=18,
        )
    assert db.execute(text("SELECT count(*) FROM segment_concept_links")).scalar_one() == 0


def test_route_candidate_route_version_book_mismatch_cannot_promote(
    db, concept_formal_link_writer_sqlite_tables
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
    db.execute(text("UPDATE route_versions SET route_book_id = 2 WHERE id = 1"))

    with pytest.raises(ConceptFormalLinkWriterError, match="route_version"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=10,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


def test_route_candidate_line_hash_mismatch_cannot_promote(db, concept_formal_link_writer_sqlite_tables):
    candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=1,
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )
    db.execute(text("UPDATE route_versions SET line_hash = 'route-hash-new' WHERE id = 1"))

    with pytest.raises(ConceptFormalLinkWriterError, match="route_line_hash"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=10,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


def test_route_acceptance_judgment_target_mismatch_cannot_promote(
    db, concept_formal_link_writer_sqlite_tables
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

    with pytest.raises(ConceptFormalLinkWriterError, match="route_book_id"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=18,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


def test_route_acceptance_judgment_with_segment_target_cannot_promote(
    db, concept_formal_link_writer_sqlite_tables
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

    with pytest.raises(ConceptFormalLinkWriterError, match="segment_id"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=19,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


@pytest.mark.parametrize("judgment_run_id", [18, 19])
def test_collection_acceptance_judgment_with_route_or_segment_target_cannot_promote(
    db, concept_formal_link_writer_sqlite_tables, judgment_run_id
):
    candidate = propose_collection_concept_candidate(
        db,
        collection_id=1,
        concept_node_id=1,
        relation_type="associated_with",
        proposer_kind="human",
        created_by_judgment_run_id=3,
    )

    with pytest.raises(ConceptFormalLinkWriterError, match="target"):
        promote_collection_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=judgment_run_id,
        )
    assert db.execute(text("SELECT count(*) FROM collection_concept_links")).scalar_one() == 0


def test_writer_does_not_call_commit(db, concept_formal_link_writer_sqlite_tables, monkeypatch):
    def fail_commit():
        raise AssertionError("formal link writer must not commit")

    monkeypatch.setattr(db, "commit", fail_commit)
    candidate = propose_collection_concept_candidate(
        db,
        collection_id=1,
        concept_node_id=1,
        relation_type="associated_with",
        proposer_kind="human",
        created_by_judgment_run_id=3,
    )

    promote_collection_concept_candidate(
        db,
        candidate_id=candidate.id,
        accepted_judgment_run_id=10,
    )


def test_writer_does_not_create_manual_curated_or_legacy_import_links(
    db, concept_formal_link_writer_sqlite_tables
):
    candidate = propose_collection_concept_candidate(
        db,
        collection_id=1,
        concept_node_id=1,
        relation_type="associated_with",
        proposer_kind="human",
        created_by_judgment_run_id=3,
    )

    promote_collection_concept_candidate(
        db,
        candidate_id=candidate.id,
        accepted_judgment_run_id=10,
    )

    assert db.execute(
        text(
            """
            SELECT count(*)
            FROM collection_concept_links
            WHERE source_kind IN ('manual_curated', 'legacy_import')
            """
        )
    ).scalar_one() == 0


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


def _seed_formal_link_base_rows(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (
                id, run_type, status, confidence_state, route_book_id, route_version_id,
                segment_id, confidence, result_summary_json, missing_data_json, contradiction_json
            )
            VALUES
                (1, 'semantic_agent', 'succeeded', 'proposed', 1, 1, NULL, 0.71, '{"summary":"route"}', NULL, NULL),
                (2, 'spatial_algorithm', 'succeeded', 'stable', NULL, NULL, 1, 0.62, '{"summary":"segment"}', NULL, NULL),
                (3, 'semantic_agent', 'succeeded', 'stable', NULL, NULL, NULL, 0.66, '{"summary":"collection"}', NULL, NULL),
                (10, 'human_review', 'succeeded', 'human_accepted', NULL, NULL, NULL, 0.95, '{"summary":"accepted"}', NULL, NULL),
                (11, 'human_review', 'succeeded', 'stable', NULL, NULL, NULL, 0.91, '{"summary":"stable accepted"}', NULL, NULL),
                (12, 'semantic_agent', 'succeeded', 'stable', NULL, NULL, NULL, 0.88, NULL, NULL, NULL),
                (13, 'spatial_algorithm', 'succeeded', 'stable', NULL, NULL, NULL, 0.77, NULL, NULL, NULL),
                (14, 'human_review', 'failed', 'human_accepted', NULL, NULL, NULL, 0.2, NULL, NULL, NULL),
                (15, 'human_review', 'running', 'stable', NULL, NULL, NULL, 0.3, NULL, NULL, NULL),
                (16, 'human_review', 'cancelled', 'stable', NULL, NULL, NULL, 0.4, NULL, NULL, NULL),
                (17, 'human_review', 'succeeded', 'proposed', NULL, NULL, NULL, 0.8, NULL, NULL, NULL),
                (18, 'human_review', 'succeeded', 'human_accepted', 2, 2, NULL, 0.93, NULL, NULL, NULL),
                (19, 'human_review', 'succeeded', 'human_accepted', NULL, NULL, 2, 0.94, NULL, NULL, NULL)
            """
        )
    )
    db.execute(text("INSERT INTO route_books (id, name) VALUES (1, 'Route A'), (2, 'Route B')"))
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
    db.execute(text("INSERT INTO concept_nodes (id) VALUES (1), (2)"))
    db.execute(text("INSERT INTO route_collections (id) VALUES (1), (2)"))
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


def _create_formal_link_writer_tables(db) -> None:
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
                contradiction_json TEXT,
                UNIQUE (id, run_type)
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
                line_hash TEXT NOT NULL,
                UNIQUE (id, route_book_id)
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
    _create_route_concept_link_table(db)
    _create_segment_concept_link_table(db)
    _create_collection_concept_link_table(db)
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE (
                    id, accepted_by_judgment_run_id, route_book_id, route_version_id,
                    route_line_hash, concept_node_id, relation_type
                )
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE (
                    id, accepted_by_judgment_run_id, segment_id, segment_geometry_hash,
                    concept_node_id, relation_type
                )
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE (
                    id, accepted_by_judgment_run_id, collection_id, concept_node_id, relation_type
                )
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


def _create_route_concept_link_table(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE route_concept_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_book_id INTEGER NOT NULL,
                route_version_id INTEGER NOT NULL,
                route_line_hash TEXT NOT NULL,
                concept_node_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                link_status TEXT NOT NULL DEFAULT 'active',
                source_kind TEXT NOT NULL,
                accepted_judgment_run_id INTEGER NOT NULL,
                accepted_judgment_run_type TEXT NOT NULL DEFAULT 'human_review',
                source_route_concept_candidate_id INTEGER,
                display_priority INTEGER,
                reason_summary TEXT,
                metadata_json TEXT,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CHECK (source_kind = 'candidate_accepted'),
                CHECK (accepted_judgment_run_type = 'human_review'),
                UNIQUE (source_route_concept_candidate_id),
                FOREIGN KEY (route_book_id) REFERENCES route_books(id),
                FOREIGN KEY (route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id),
                FOREIGN KEY (concept_node_id) REFERENCES concept_nodes(id),
                FOREIGN KEY (accepted_judgment_run_id, accepted_judgment_run_type)
                    REFERENCES judgment_runs(id, run_type),
                FOREIGN KEY (
                    source_route_concept_candidate_id, accepted_judgment_run_id, route_book_id,
                    route_version_id, route_line_hash, concept_node_id, relation_type
                )
                    REFERENCES route_concept_candidates(
                        id, accepted_by_judgment_run_id, route_book_id, route_version_id,
                        route_line_hash, concept_node_id, relation_type
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


def _create_segment_concept_link_table(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE segment_concept_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id INTEGER NOT NULL,
                segment_geometry_hash TEXT NOT NULL,
                concept_node_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                link_status TEXT NOT NULL DEFAULT 'active',
                source_kind TEXT NOT NULL,
                accepted_judgment_run_id INTEGER NOT NULL,
                accepted_judgment_run_type TEXT NOT NULL DEFAULT 'human_review',
                source_segment_concept_candidate_id INTEGER,
                display_priority INTEGER,
                reason_summary TEXT,
                metadata_json TEXT,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CHECK (source_kind = 'candidate_accepted'),
                CHECK (accepted_judgment_run_type = 'human_review'),
                UNIQUE (source_segment_concept_candidate_id),
                FOREIGN KEY (segment_id) REFERENCES route_cognition_segments(segment_id),
                FOREIGN KEY (concept_node_id) REFERENCES concept_nodes(id),
                FOREIGN KEY (accepted_judgment_run_id, accepted_judgment_run_type)
                    REFERENCES judgment_runs(id, run_type),
                FOREIGN KEY (
                    source_segment_concept_candidate_id, accepted_judgment_run_id, segment_id,
                    segment_geometry_hash, concept_node_id, relation_type
                )
                    REFERENCES segment_concept_candidates(
                        id, accepted_by_judgment_run_id, segment_id, segment_geometry_hash,
                        concept_node_id, relation_type
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


def _create_collection_concept_link_table(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE collection_concept_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                concept_node_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                link_status TEXT NOT NULL DEFAULT 'active',
                source_kind TEXT NOT NULL,
                accepted_judgment_run_id INTEGER NOT NULL,
                accepted_judgment_run_type TEXT NOT NULL DEFAULT 'human_review',
                source_collection_concept_candidate_id INTEGER,
                display_priority INTEGER,
                reason_summary TEXT,
                metadata_json TEXT,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CHECK (source_kind = 'candidate_accepted'),
                CHECK (accepted_judgment_run_type = 'human_review'),
                UNIQUE (source_collection_concept_candidate_id),
                FOREIGN KEY (collection_id) REFERENCES route_collections(id),
                FOREIGN KEY (concept_node_id) REFERENCES concept_nodes(id),
                FOREIGN KEY (accepted_judgment_run_id, accepted_judgment_run_type)
                    REFERENCES judgment_runs(id, run_type),
                FOREIGN KEY (
                    source_collection_concept_candidate_id, accepted_judgment_run_id, collection_id,
                    concept_node_id, relation_type
                )
                    REFERENCES collection_concept_candidates(
                        id, accepted_by_judgment_run_id, collection_id, concept_node_id, relation_type
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


def _insert_route_candidate(db, *, candidate_status: str) -> int:
    db.execute(
        text(
            """
            INSERT INTO route_concept_candidates (
                id, route_book_id, route_version_id, route_line_hash, concept_node_id,
                relation_type, proposer_kind, candidate_status, created_by_judgment_run_id,
                latest_judgment_run_id, accepted_by_judgment_run_id, latest_confidence,
                latest_confidence_state, reviewed_at
            )
            VALUES (
                100, 1, 1, 'route-hash-a', 1,
                'training_theme', 'agent', :candidate_status, 1,
                1, :accepted_by_judgment_run_id, 0.71,
                'proposed', :reviewed_at
            )
            """
        ),
        {
            "candidate_status": candidate_status,
            "accepted_by_judgment_run_id": 10 if candidate_status == "accepted" else None,
            "reviewed_at": "2026-06-18 00:00:00" if candidate_status == "accepted" else None,
        },
    )
    return 100


def _drop_formal_link_writer_tables(db) -> None:
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
