"""路线认知写入门禁测试——先确认“谁有资格写正式判断”。"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.route_cognition.services.write_guard import (
    WriteGuardError,
    assert_human_review_judgment,
    assert_imported_has_source,
    assert_metadata_has_no_relationship_truth,
    assert_not_public_without_published,
    assert_published_has_judgment,
)


@pytest.fixture()
def write_guard_sqlite_tables(db):
    db.execute(text("DROP TABLE IF EXISTS judgment_runs"))
    db.execute(
        text(
            """
            CREATE TABLE judgment_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence_state TEXT NOT NULL
            )
            """
        )
    )
    try:
        yield
    finally:
        db.rollback()
        db.execute(text("DROP TABLE IF EXISTS judgment_runs"))


def test_human_review_succeeded_human_accepted_passes(db, write_guard_sqlite_tables):
    _insert_judgment_run(db, confidence_state="human_accepted")

    assert_human_review_judgment(db, 1)


def test_human_review_succeeded_stable_passes(db, write_guard_sqlite_tables):
    _insert_judgment_run(db, confidence_state="stable")

    assert_human_review_judgment(db, 1)


def test_semantic_agent_is_rejected(db, write_guard_sqlite_tables):
    _insert_judgment_run(db, run_type="semantic_agent")

    with pytest.raises(WriteGuardError, match="human_review"):
        assert_human_review_judgment(db, 1)


def test_spatial_algorithm_is_rejected(db, write_guard_sqlite_tables):
    _insert_judgment_run(db, run_type="spatial_algorithm")

    with pytest.raises(WriteGuardError, match="human_review"):
        assert_human_review_judgment(db, 1)


def test_failed_judgment_is_rejected(db, write_guard_sqlite_tables):
    _insert_judgment_run(db, status="failed")

    with pytest.raises(WriteGuardError, match="succeeded"):
        assert_human_review_judgment(db, 1)


def test_running_judgment_is_rejected(db, write_guard_sqlite_tables):
    _insert_judgment_run(db, status="running")

    with pytest.raises(WriteGuardError, match="succeeded"):
        assert_human_review_judgment(db, 1)


def test_public_draft_is_rejected():
    with pytest.raises(WriteGuardError, match="public"):
        assert_not_public_without_published("public", "draft")


def test_published_without_judgment_is_rejected():
    with pytest.raises(WriteGuardError, match="source_judgment_run_id"):
        assert_published_has_judgment("published", None)


def test_imported_without_source_ref_or_judgment_is_rejected():
    with pytest.raises(WriteGuardError, match="source_ref"):
        assert_imported_has_source("imported", None, None)


def test_metadata_json_with_route_ids_is_rejected():
    with pytest.raises(WriteGuardError, match="route_ids"):
        assert_metadata_has_no_relationship_truth({"route_ids": [1, 2]})


def test_metadata_json_with_segment_ids_is_rejected():
    with pytest.raises(WriteGuardError, match="segment_ids"):
        assert_metadata_has_no_relationship_truth({"segment_ids": [1, 2]})


def test_metadata_json_with_collection_ids_is_rejected():
    with pytest.raises(WriteGuardError, match="collection_ids"):
        assert_metadata_has_no_relationship_truth({"collection_ids": [1, 2]})


@pytest.mark.parametrize(
    "metadata_key",
    [
        "route_book_id",
        "route_version_id",
        "route_line_hash",
        "concept_node_id",
        "relation_type",
        "source_route_concept_candidate_id",
        "source_segment_concept_candidate_id",
        "source_collection_concept_candidate_id",
    ],
)
def test_metadata_json_with_real_relationship_field_is_rejected(metadata_key):
    with pytest.raises(WriteGuardError, match=metadata_key):
        assert_metadata_has_no_relationship_truth({metadata_key: "hidden-truth"})


def test_metadata_json_with_nested_relationship_field_is_rejected():
    with pytest.raises(WriteGuardError, match="route_version_id"):
        assert_metadata_has_no_relationship_truth(
            {
                "display": {
                    "route_version_id": 1,
                }
            }
        )


def _insert_judgment_run(
    db,
    *,
    run_type: str = "human_review",
    status: str = "succeeded",
    confidence_state: str = "human_accepted",
) -> None:
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (id, run_type, status, confidence_state)
            VALUES (1, :run_type, :status, :confidence_state)
            """
        ),
        {
            "run_type": run_type,
            "status": status,
            "confidence_state": confidence_state,
        },
    )
