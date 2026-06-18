"""路线认知 Step 1.5 种子演习——在测试库里试建太原/西山概念，不碰真实内容。"""

from __future__ import annotations

import subprocess

import pytest
from sqlalchemy import text

from app.route_cognition.services.concept_writer import ConceptWriterError, create_concept_node


TAIYUAN_XISHAN_CONCEPTS = (
    {
        "name": "FTP 测试",
        "slug": "ftp-test",
        "node_type": "practice_type",
        "scope_type": "city",
        "scope_value": "taiyuan",
        "city": "taiyuan",
    },
    {
        "name": "新手有氧",
        "slug": "beginner-aerobic",
        "node_type": "training_theme",
        "scope_type": "city",
        "scope_value": "taiyuan",
        "city": "taiyuan",
    },
    {
        "name": "爬坡训练",
        "slug": "climbing-training",
        "node_type": "training_theme",
        "scope_type": "region",
        "scope_value": "taiyuan-xishan",
        "region": "taiyuan-xishan",
    },
    {
        "name": "废道",
        "slug": "abandoned-road",
        "node_type": "local_term",
        "scope_type": "region",
        "scope_value": "taiyuan-xishan",
        "region": "taiyuan-xishan",
    },
    {
        "name": "网红桥",
        "slug": "viral-bridge",
        "node_type": "landmark",
        "scope_type": "region",
        "scope_value": "taiyuan-xishan",
        "region": "taiyuan-xishan",
    },
    {
        "name": "环太原赛",
        "slug": "tour-of-taiyuan",
        "node_type": "event",
        "scope_type": "city",
        "scope_value": "taiyuan",
        "city": "taiyuan",
    },
    {
        "name": "奥申体育公园",
        "slug": "aoshen-sports-park",
        "node_type": "place",
        "scope_type": "city",
        "scope_value": "taiyuan",
        "city": "taiyuan",
    },
    {
        "name": "碎石风险",
        "slug": "gravel-risk",
        "node_type": "safety_risk",
        "scope_type": "region",
        "scope_value": "taiyuan-xishan",
        "region": "taiyuan-xishan",
    },
)

FORBIDDEN_EMPTY_TABLES = (
    "route_concept_links",
    "segment_concept_links",
    "collection_concept_links",
    "route_concept_candidates",
    "segment_concept_candidates",
    "collection_concept_candidates",
    "evidence_items",
)


@pytest.fixture()
def concept_seed_dry_run_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_seed_dry_run_tables(db)
    _create_seed_dry_run_tables(db)
    _seed_side_effect_sentinels(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_seed_dry_run_tables(db)


def test_taiyuan_xishan_seed_concepts_create_private_draft_manual_nodes(db, concept_seed_dry_run_tables):
    before_content_routes_diff = _content_routes_diff_names()
    before_route_guide_content = db.execute(text("SELECT content_md FROM route_guides WHERE id = 1")).scalar_one()
    before_route_collection_name = db.execute(text("SELECT name FROM route_collections WHERE id = 1")).scalar_one()
    before_segment_name = db.execute(text("SELECT name FROM segments WHERE id = 1")).scalar_one()
    before_effort_count = db.execute(text("SELECT count(*) FROM segment_efforts")).scalar_one()

    for concept in TAIYUAN_XISHAN_CONCEPTS:
        create_concept_node(
            db,
            name=concept["name"],
            slug=concept["slug"],
            node_type=concept["node_type"],
            scope_type=concept["scope_type"],
            scope_value=concept["scope_value"],
            city=concept.get("city"),
            region=concept.get("region"),
            summary=f"{concept['name']} seed dry-run",
        )

    rows = db.execute(
        text(
            """
            SELECT name, slug, node_type, scope_type, scope_value, visibility, publish_status, source,
                   source_judgment_run_id
            FROM concept_nodes
            ORDER BY id
            """
        )
    ).all()

    assert [
        {
            "name": row.name,
            "slug": row.slug,
            "node_type": row.node_type,
            "scope_type": row.scope_type,
            "scope_value": row.scope_value,
        }
        for row in rows
    ] == [
        {
            "name": concept["name"],
            "slug": concept["slug"],
            "node_type": concept["node_type"],
            "scope_type": concept["scope_type"],
            "scope_value": concept["scope_value"],
        }
        for concept in TAIYUAN_XISHAN_CONCEPTS
    ]
    assert {row.visibility for row in rows} == {"private"}
    assert {row.publish_status for row in rows} == {"draft"}
    assert {row.source for row in rows} == {"manual"}
    assert {row.source_judgment_run_id for row in rows} == {None}

    for table_name in FORBIDDEN_EMPTY_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0

    assert db.execute(text("SELECT content_md FROM route_guides WHERE id = 1")).scalar_one() == before_route_guide_content
    assert db.execute(text("SELECT name FROM route_collections WHERE id = 1")).scalar_one() == before_route_collection_name
    assert db.execute(text("SELECT name FROM segments WHERE id = 1")).scalar_one() == before_segment_name
    assert db.execute(text("SELECT count(*) FROM segment_efforts")).scalar_one() == before_effort_count
    assert _content_routes_diff_names() == before_content_routes_diff


def test_seed_dry_run_metadata_guard_rejects_relationship_truth(db, concept_seed_dry_run_tables):
    with pytest.raises(ConceptWriterError, match="route_book_id"):
        create_concept_node(
            db,
            name="坏的种子概念",
            slug="bad-seed-concept",
            node_type="landmark",
            scope_type="city",
            scope_value="taiyuan",
            city="taiyuan",
            metadata_json={"display": {"route_book_id": 1}},
        )


def _content_routes_diff_names() -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "content/routes"],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def _seed_side_effect_sentinels(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO route_guides (id, name, content_md)
            VALUES (1, 'Guide Sentinel', 'original guide content')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_collections (id, name)
            VALUES (1, 'Collection Sentinel')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO segments (id, name)
            VALUES (1, 'Segment Sentinel')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO segment_efforts (id, segment_id)
            VALUES (1, 1)
            """
        )
    )


def _create_seed_dry_run_tables(db) -> None:
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
    db.execute(text("CREATE TABLE route_concept_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE segment_concept_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_concept_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
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
    db.execute(
        text(
            """
            CREATE TABLE route_collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
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


def _drop_seed_dry_run_tables(db) -> None:
    for table_name in (
        "segment_efforts",
        "segments",
        "route_collections",
        "route_guides",
        "evidence_items",
        "collection_concept_candidates",
        "segment_concept_candidates",
        "route_concept_candidates",
        "collection_concept_links",
        "segment_concept_links",
        "route_concept_links",
        "concept_nodes",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
