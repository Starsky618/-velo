"""路线专题 Step 2.5 种子演习——在测试库里试建太原专题，不碰真实内容。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

from app.route_cognition.services.route_collection_writer import (
    RouteCollectionWriterError,
    create_route_collection,
)


TAIYUAN_ROUTE_COLLECTIONS = (
    {
        "name": "西山训练体系",
        "slug": "xishan-training-system",
        "collection_type": "area_system",
        "city": "taiyuan",
    },
    {
        "name": "环太原赛路线族",
        "slug": "tour-of-taiyuan-route-family",
        "collection_type": "race_route_family",
        "city": "taiyuan",
    },
    {
        "name": "新手风景路线合集",
        "slug": "beginner-scenic-routes",
        "collection_type": "theme_pack",
        "city": "taiyuan",
    },
    {
        "name": "东山爬坡专题",
        "slug": "dongshan-climbs",
        "collection_type": "theme_pack",
        "city": "taiyuan",
    },
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
def route_collection_seed_dry_run_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_seed_dry_run_tables(db)
    _create_seed_dry_run_tables(db)
    _seed_side_effect_sentinels(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_seed_dry_run_tables(db)


def test_taiyuan_route_collection_seed_creates_private_draft_manual_collections(
    db, route_collection_seed_dry_run_tables
):
    before_content_routes_diff = _content_routes_snapshot()
    before_route_guides = _route_guides_snapshot(db)
    before_route_books = _simple_table_snapshot(db, "route_books")
    before_route_versions = _simple_table_snapshot(db, "route_versions")
    before_segments = _simple_table_snapshot(db, "segments")
    before_segment_efforts = _simple_table_snapshot(db, "segment_efforts")

    for collection in TAIYUAN_ROUTE_COLLECTIONS:
        create_route_collection(
            db,
            name=collection["name"],
            slug=collection["slug"],
            collection_type=collection["collection_type"],
            city=collection["city"],
        )

    rows = db.execute(
        text(
            """
            SELECT name, slug, collection_type, city, visibility, publish_status, source,
                   source_judgment_run_id
            FROM route_collections
            ORDER BY id
            """
        )
    ).all()

    assert [
        {
            "name": row.name,
            "slug": row.slug,
            "collection_type": row.collection_type,
            "city": row.city,
        }
        for row in rows
    ] == [
        {
            "name": collection["name"],
            "slug": collection["slug"],
            "collection_type": collection["collection_type"],
            "city": collection["city"],
        }
        for collection in TAIYUAN_ROUTE_COLLECTIONS
    ]
    assert {row.visibility for row in rows} == {"private"}
    assert {row.publish_status for row in rows} == {"draft"}
    assert {row.source for row in rows} == {"manual"}
    assert {row.source_judgment_run_id for row in rows} == {None}

    for table_name in FORBIDDEN_EMPTY_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0

    assert _route_guides_snapshot(db) == before_route_guides
    assert _simple_table_snapshot(db, "route_books") == before_route_books
    assert _simple_table_snapshot(db, "route_versions") == before_route_versions
    assert _simple_table_snapshot(db, "segments") == before_segments
    assert _simple_table_snapshot(db, "segment_efforts") == before_segment_efforts
    assert _content_routes_snapshot() == before_content_routes_diff


@pytest.mark.parametrize(
    ("metadata_json", "blocked_key"),
    [
        ({"display": {"route_ids": [1]}}, "route_ids"),
        ({"display": {"segment_ids": [2]}}, "segment_ids"),
        ({"members": [{"kind": "routes", "slug": "xishan-training-system"}]}, "members"),
        ({"routes": [{"slug": "tour-of-taiyuan-route-family"}]}, "routes"),
    ],
)
def test_seed_dry_run_metadata_guard_rejects_nested_membership_truth(
    db, route_collection_seed_dry_run_tables, metadata_json, blocked_key
):
    with pytest.raises(RouteCollectionWriterError, match=blocked_key):
        create_route_collection(
            db,
            name="坏的专题元数据",
            slug=f"bad-metadata-{blocked_key.replace('_', '-')}",
            collection_type="theme_pack",
            city="taiyuan",
            metadata_json=metadata_json,
        )


@pytest.mark.parametrize(
    ("stats_json", "blocked_key"),
    [
        ({"nested": {"route_ids": [1]}}, "route_ids"),
        ({"nested": {"segment_ids": [2]}}, "segment_ids"),
        ({"nested": {"members": [{"type": "segments", "name": "climb"}]}}, "members"),
        ({"nested": {"routes": [{"slug": "xishan-training-system"}]}}, "routes"),
        ({"nested": {"ordering": ["route-1", "route-2"]}}, "ordering"),
        ({"nested": {"roles": {"route-1": "main"}}}, "roles"),
    ],
)
def test_seed_dry_run_stats_guard_rejects_nested_membership_truth(
    db, route_collection_seed_dry_run_tables, stats_json, blocked_key
):
    with pytest.raises(RouteCollectionWriterError, match=blocked_key):
        create_route_collection(
            db,
            name="坏的专题统计",
            slug=f"bad-stats-{blocked_key.replace('_', '-')}",
            collection_type="theme_pack",
            city="taiyuan",
            stats_json=stats_json,
        )


def _content_routes_snapshot() -> set[str]:
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


def _simple_table_snapshot(db, table_name: str) -> list[tuple]:
    return [tuple(row) for row in db.execute(text(f"SELECT * FROM {table_name} ORDER BY id")).all()]


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
            INSERT INTO route_books (id, name)
            VALUES (1, 'Route Book Sentinel')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_versions (id, route_book_id, name)
            VALUES (1, 1, 'Route Version Sentinel')
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
    db.execute(
        text(
            """
            CREATE TABLE route_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE route_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_book_id INTEGER NOT NULL,
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
        "route_versions",
        "route_books",
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
