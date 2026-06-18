"""路线认知概念写入测试——只允许安全地创建“概念身份证”。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

from app.route_cognition.services.concept_writer import (
    ConceptWriterError,
    create_concept_node,
)


FORBIDDEN_LINK_TABLES = (
    "route_concept_links",
    "segment_concept_links",
    "collection_concept_links",
)


@pytest.fixture()
def concept_writer_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_concept_writer_tables(db)
    _create_concept_writer_tables(db)
    _seed_base(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_concept_writer_tables(db)


def test_create_private_draft_manual_concept_succeeds(db, concept_writer_sqlite_tables):
    node = create_concept_node(
        db,
        name="FTP Test",
        slug="ftp-test",
        node_type="practice_type",
        summary="人工整理的训练主题。",
    )

    assert node.id == 1
    assert node.visibility == "private"
    assert node.publish_status == "draft"
    assert node.source == "manual"
    assert db.execute(text("SELECT count(*) FROM concept_nodes")).scalar_one() == 1


def test_create_published_concept_without_judgment_fails(db, concept_writer_sqlite_tables):
    with pytest.raises(ConceptWriterError, match="source_judgment_run_id"):
        create_concept_node(
            db,
            name="Published Concept",
            slug="published-concept",
            node_type="practice_type",
            publish_status="published",
        )


def test_create_public_draft_concept_fails(db, concept_writer_sqlite_tables):
    with pytest.raises(ConceptWriterError, match="public"):
        create_concept_node(
            db,
            name="Public Draft",
            slug="public-draft",
            node_type="practice_type",
            visibility="public",
            publish_status="draft",
        )


def test_create_imported_concept_without_source_ref_or_judgment_fails(db, concept_writer_sqlite_tables):
    with pytest.raises(ConceptWriterError, match="source_ref"):
        create_concept_node(
            db,
            name="Imported Concept",
            slug="imported-concept",
            node_type="landmark",
            source="imported",
        )


def test_source_judgment_run_id_pointing_to_non_human_judgment_fails(db, concept_writer_sqlite_tables):
    _insert_judgment_run(db, id=2, run_type="semantic_agent")

    with pytest.raises(ConceptWriterError, match="human_review"):
        create_concept_node(
            db,
            name="Agent Concept",
            slug="agent-concept",
            node_type="landmark",
            source_judgment_run_id=2,
        )


def test_source_judgment_run_id_pointing_to_failed_judgment_fails(db, concept_writer_sqlite_tables):
    _insert_judgment_run(db, id=2, status="failed")

    with pytest.raises(ConceptWriterError, match="succeeded"):
        create_concept_node(
            db,
            name="Failed Judgment Concept",
            slug="failed-judgment-concept",
            node_type="landmark",
            source_judgment_run_id=2,
        )


def test_metadata_json_with_relationship_truth_key_fails(db, concept_writer_sqlite_tables):
    with pytest.raises(ConceptWriterError, match="formal_relationship_truth"):
        create_concept_node(
            db,
            name="Bad Metadata",
            slug="bad-metadata",
            node_type="landmark",
            metadata_json={"formal_relationship_truth": {"route_id": 1}},
        )


def test_metadata_json_with_route_book_id_fails(db, concept_writer_sqlite_tables):
    with pytest.raises(ConceptWriterError, match="route_book_id"):
        create_concept_node(
            db,
            name="Bad Route Metadata",
            slug="bad-route-metadata",
            node_type="landmark",
            metadata_json={"route_book_id": 1},
        )


def test_writer_does_not_create_concept_link_rows(db, concept_writer_sqlite_tables):
    create_concept_node(
        db,
        name="No Link Side Effect",
        slug="no-link-side-effect",
        node_type="landmark",
    )

    for table_name in FORBIDDEN_LINK_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0


def test_writer_does_not_change_route_guides_content_md(db, concept_writer_sqlite_tables):
    before = db.execute(text("SELECT content_md FROM route_guides WHERE id = 1")).scalar_one()

    create_concept_node(
        db,
        name="Route Guide Sentinel",
        slug="route-guide-sentinel",
        node_type="landmark",
    )

    after = db.execute(text("SELECT content_md FROM route_guides WHERE id = 1")).scalar_one()
    assert after == before


def test_writer_does_not_change_content_routes_files(db, concept_writer_sqlite_tables):
    before = _tracked_content_route_changes()

    create_concept_node(
        db,
        name="Content Sentinel",
        slug="content-sentinel",
        node_type="landmark",
    )

    assert _tracked_content_route_changes() == before


def _tracked_content_route_changes() -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "content/routes"],
        check=True,
        capture_output=True,
        text=True,
    )
    existing_files = {str(path) for path in Path("content/routes").glob("**/*") if path.is_file()}
    return set(result.stdout.splitlines()) | existing_files


def _seed_base(db) -> None:
    _insert_judgment_run(db, id=1)
    db.execute(
        text(
            """
            INSERT INTO route_guides (id, name, content_md)
            VALUES (1, 'Guide Sentinel', 'original guide content')
            """
        )
    )


def _insert_judgment_run(
    db,
    *,
    id: int,
    run_type: str = "human_review",
    status: str = "succeeded",
    confidence_state: str = "human_accepted",
) -> None:
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (id, run_type, status, confidence_state)
            VALUES (:id, :run_type, :status, :confidence_state)
            """
        ),
        {
            "id": id,
            "run_type": run_type,
            "status": status,
            "confidence_state": confidence_state,
        },
    )


def _create_concept_writer_tables(db) -> None:
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
    db.execute(
        text(
            """
            CREATE TABLE concept_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                node_type TEXT NOT NULL,
                scope_type TEXT NOT NULL DEFAULT 'global',
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
                UNIQUE(scope_type, scope_value, node_type, slug),
                FOREIGN KEY(source_judgment_run_id) REFERENCES judgment_runs(id)
            )
            """
        )
    )
    db.execute(text("CREATE TABLE route_concept_links (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE segment_concept_links (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_concept_links (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
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


def _drop_concept_writer_tables(db) -> None:
    for table_name in (
        "collection_concept_links",
        "segment_concept_links",
        "route_concept_links",
        "concept_nodes",
        "route_guides",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
