"""路线专题写入测试——只允许创建专题本体，不能顺手装路线成员。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

from app.route_cognition.services.route_collection_writer import (
    RouteCollectionWriterError,
    create_route_collection,
)


FORBIDDEN_EMPTY_TABLES = (
    "collection_routes",
    "collection_segments",
    "collection_concept_links",
    "route_concept_candidates",
    "segment_concept_candidates",
    "collection_concept_candidates",
    "route_collection_candidates",
    "segment_collection_candidates",
    "evidence_items",
)


@pytest.fixture()
def route_collection_writer_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_route_collection_writer_tables(db)
    _create_route_collection_writer_tables(db)
    _seed_sentinels(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_route_collection_writer_tables(db)


def test_create_private_draft_manual_route_collection_succeeds(db, route_collection_writer_sqlite_tables):
    collection = create_route_collection(
        db,
        name="Taiyuan West Hills",
        slug="taiyuan-west-hills",
        collection_type="area_system",
        city="taiyuan",
        description_md="内部草稿专题。",
    )

    assert collection.id == 1
    assert collection.name == "Taiyuan West Hills"
    assert collection.visibility == "private"
    assert collection.publish_status == "draft"
    assert collection.source == "manual"
    assert db.execute(text("SELECT count(*) FROM route_collections")).scalar_one() == 1


def test_create_route_collection_defaults_to_private_draft_manual(db, route_collection_writer_sqlite_tables):
    collection = create_route_collection(
        db,
        name="Default Collection",
        slug="default-collection",
        collection_type="theme_pack",
    )

    assert collection.city == "unknown"
    assert collection.visibility == "private"
    assert collection.publish_status == "draft"
    assert collection.source == "manual"
    assert collection.source_judgment_run_id is None


def test_public_draft_route_collection_fails(db, route_collection_writer_sqlite_tables):
    with pytest.raises(RouteCollectionWriterError, match="public"):
        create_route_collection(
            db,
            name="Public Draft",
            slug="public-draft",
            collection_type="theme_pack",
            visibility="public",
            publish_status="draft",
        )


def test_published_without_source_judgment_run_id_fails(db, route_collection_writer_sqlite_tables):
    with pytest.raises(RouteCollectionWriterError, match="source_judgment_run_id"):
        create_route_collection(
            db,
            name="Published Without Judgment",
            slug="published-without-judgment",
            collection_type="theme_pack",
            publish_status="published",
        )


def test_imported_without_source_ref_or_judgment_fails(db, route_collection_writer_sqlite_tables):
    with pytest.raises(RouteCollectionWriterError, match="source_ref"):
        create_route_collection(
            db,
            name="Imported Without Source",
            slug="imported-without-source",
            collection_type="theme_pack",
            source="imported",
        )


def test_source_judgment_run_id_pointing_to_non_human_judgment_fails(
    db, route_collection_writer_sqlite_tables
):
    _insert_judgment_run(db, id=2, run_type="semantic_agent")

    with pytest.raises(RouteCollectionWriterError, match="human_review"):
        create_route_collection(
            db,
            name="Agent Judgment",
            slug="agent-judgment",
            collection_type="theme_pack",
            source_judgment_run_id=2,
        )


def test_source_judgment_run_id_pointing_to_failed_judgment_fails(
    db, route_collection_writer_sqlite_tables
):
    _insert_judgment_run(db, id=2, status="failed")

    with pytest.raises(RouteCollectionWriterError, match="succeeded"):
        create_route_collection(
            db,
            name="Failed Judgment",
            slug="failed-judgment",
            collection_type="theme_pack",
            source_judgment_run_id=2,
        )


def test_source_judgment_run_id_pointing_to_human_accepted_judgment_succeeds(
    db, route_collection_writer_sqlite_tables
):
    collection = create_route_collection(
        db,
        name="Published Human Reviewed",
        slug="published-human-reviewed",
        collection_type="theme_pack",
        publish_status="published",
        source_judgment_run_id=1,
    )

    assert collection.publish_status == "published"
    assert collection.source_judgment_run_id == 1


@pytest.mark.parametrize(
    ("metadata_json", "blocked_key"),
    [
        ({"route_ids": [1, 2]}, "route_ids"),
        ({"segment_ids": [1, 2]}, "segment_ids"),
        ({"display": {"route_book_id": 1}}, "route_book_id"),
        ({"display": {"concept_ids": [3]}}, "concept_ids"),
        ({"routes": [1]}, "routes"),
        ({"route_slugs": ["west-hills"]}, "route_slugs"),
        ({"display": {"route_names": ["Taiyuan West"]}}, "route_names"),
        ({"display": {"members": [{"id": 1, "kind": "route"}]}}, "members"),
        ({"items": [{"kind": "route", "slug": "west-hills"}]}, "kind"),
        ({"items": [{"kind": "routes", "slug": "west-hills"}]}, "kind"),
        ({"formal_relationship_truth": {"relation_type": "contains"}}, "formal_relationship_truth"),
    ],
)
def test_metadata_json_with_membership_or_relationship_truth_fails(
    db, route_collection_writer_sqlite_tables, metadata_json, blocked_key
):
    with pytest.raises(RouteCollectionWriterError, match=blocked_key):
        create_route_collection(
            db,
            name=f"Bad Metadata {blocked_key}",
            slug=f"bad-metadata-{blocked_key.replace('_', '-')}",
            collection_type="theme_pack",
            metadata_json=metadata_json,
        )


@pytest.mark.parametrize(
    ("stats_json", "blocked_key"),
    [
        ({"route_ids": [1]}, "route_ids"),
        ({"segment_ids": [2]}, "segment_ids"),
        ({"members": {"member_ids": [3]}}, "members"),
        ({"segment_slugs": ["climb-1"]}, "segment_slugs"),
        ({"collection_route_slugs": ["west-hills"]}, "collection_route_slugs"),
        ({"items": [{"type": "segment", "name": "climb-1"}]}, "type"),
        ({"items": [{"type": "segments", "name": "climb-1"}]}, "type"),
        ({"items": [{"entity_type": "route_books", "slug": "west-hills"}]}, "entity_type"),
        ({"roles": {"1": "main"}}, "roles"),
        ({"ordering": ["route-1", "route-2"]}, "ordering"),
    ],
)
def test_stats_json_with_membership_truth_fails(
    db, route_collection_writer_sqlite_tables, stats_json, blocked_key
):
    with pytest.raises(RouteCollectionWriterError, match=blocked_key):
        create_route_collection(
            db,
            name=f"Bad Stats {blocked_key}",
            slug=f"bad-stats-{blocked_key.replace('_', '-')}",
            collection_type="theme_pack",
            stats_json=stats_json,
        )


@pytest.mark.parametrize("source", ["agent", "algorithm", "ai"])
def test_agent_algorithm_or_ai_source_is_rejected(db, route_collection_writer_sqlite_tables, source):
    with pytest.raises(RouteCollectionWriterError, match="source"):
        create_route_collection(
            db,
            name=f"Bad Source {source}",
            slug=f"bad-source-{source}",
            collection_type="theme_pack",
            source=source,
        )


@pytest.mark.parametrize("collection_type", ["concept", "candidate", "bad_type"])
def test_invalid_collection_type_is_rejected(db, route_collection_writer_sqlite_tables, collection_type):
    with pytest.raises(RouteCollectionWriterError, match="collection_type"):
        create_route_collection(
            db,
            name="Bad Type",
            slug="bad-type",
            collection_type=collection_type,
        )


@pytest.mark.parametrize("slug", ["Taiyuan-west", "taiyuan west", "a", "-taiyuan"])
def test_invalid_slug_is_rejected(db, route_collection_writer_sqlite_tables, slug):
    with pytest.raises(RouteCollectionWriterError, match="slug"):
        create_route_collection(
            db,
            name="Bad Slug",
            slug=slug,
            collection_type="theme_pack",
        )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_outside_zero_to_one_is_rejected(
    db, route_collection_writer_sqlite_tables, confidence
):
    with pytest.raises(RouteCollectionWriterError, match="confidence"):
        create_route_collection(
            db,
            name="Bad Confidence",
            slug="bad-confidence",
            collection_type="theme_pack",
            confidence=confidence,
        )


def test_center_lat_and_center_lon_must_be_provided_together(
    db, route_collection_writer_sqlite_tables
):
    with pytest.raises(RouteCollectionWriterError, match="center_lat"):
        create_route_collection(
            db,
            name="Bad Center",
            slug="bad-center",
            collection_type="theme_pack",
            center_lat=37.8,
        )


def test_empty_name_or_city_is_rejected(db, route_collection_writer_sqlite_tables):
    with pytest.raises(RouteCollectionWriterError, match="name"):
        create_route_collection(
            db,
            name="   ",
            slug="empty-name",
            collection_type="theme_pack",
        )

    with pytest.raises(RouteCollectionWriterError, match="city"):
        create_route_collection(
            db,
            name="Empty City",
            slug="empty-city",
            collection_type="theme_pack",
            city=" ",
        )


def test_writer_does_not_create_forbidden_relationship_candidate_or_evidence_rows(
    db, route_collection_writer_sqlite_tables
):
    create_route_collection(
        db,
        name="Side Effect Sentinel",
        slug="side-effect-sentinel",
        collection_type="theme_pack",
    )

    for table_name in FORBIDDEN_EMPTY_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0


def test_writer_does_not_change_route_guides_content_md(db, route_collection_writer_sqlite_tables):
    before = _route_guides_snapshot(db)

    create_route_collection(
        db,
        name="Guide Sentinel",
        slug="guide-sentinel",
        collection_type="theme_pack",
    )

    assert _route_guides_snapshot(db) == before


def test_writer_does_not_change_content_routes_files(db, route_collection_writer_sqlite_tables):
    before = _content_routes_diff_names()

    create_route_collection(
        db,
        name="Content Routes Sentinel",
        slug="content-routes-sentinel",
        collection_type="theme_pack",
    )

    assert _content_routes_diff_names() == before


def _content_routes_diff_names() -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "content/routes"],
        check=True,
        capture_output=True,
        text=True,
    )
    existing_files = {str(path) for path in Path("content/routes").glob("**/*") if path.is_file()}
    return set(result.stdout.splitlines()) | existing_files


def _route_guides_snapshot(db) -> list[tuple[int, str, str]]:
    return [
        (row.id, row.name, row.content_md)
        for row in db.execute(
            text("SELECT id, name, content_md FROM route_guides ORDER BY id")
        ).all()
    ]


def _seed_sentinels(db) -> None:
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


def _create_route_collection_writer_tables(db) -> None:
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
                FOREIGN KEY(source_judgment_run_id) REFERENCES judgment_runs(id)
            )
            """
        )
    )
    db.execute(text("CREATE TABLE collection_routes (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_segments (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_concept_links (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE route_concept_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE segment_concept_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_concept_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE route_collection_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE segment_collection_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE evidence_items (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
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


def _drop_route_collection_writer_tables(db) -> None:
    for table_name in (
        "route_guides",
        "evidence_items",
        "segment_collection_candidates",
        "route_collection_candidates",
        "collection_concept_candidates",
        "segment_concept_candidates",
        "route_concept_candidates",
        "collection_concept_links",
        "collection_segments",
        "collection_routes",
        "route_collections",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
