"""collection membership Step 5A.5 种子演习——在测试库里给太原专题插成员卡片。"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

from app.route_cognition.services.collection_membership_writer import (
    CollectionMembershipWriterError,
    add_collection_route,
    add_collection_segment,
)
from app.route_cognition.services.route_collection_writer import create_route_collection


TAIYUAN_COLLECTION_SEEDS = (
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
)

FORBIDDEN_EMPTY_TABLES = (
    "route_segments",
    "route_concept_candidates",
    "segment_concept_candidates",
    "collection_concept_candidates",
    "route_collection_candidates",
    "segment_collection_candidates",
    "collection_route_candidates",
    "collection_segment_candidates",
    "route_segment_candidates",
    "evidence_items",
    "segment_submissions",
)


@pytest.fixture()
def collection_membership_seed_dry_run_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_seed_dry_run_tables(db)
    _create_seed_dry_run_tables(db)
    _seed_route_segment_and_judgment_rows(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_seed_dry_run_tables(db)


def test_taiyuan_xishan_collection_membership_seed_creates_only_formal_memberships(
    db, collection_membership_seed_dry_run_tables, monkeypatch
):
    def fail_commit():
        raise AssertionError("collection membership seed dry-run must not commit")

    monkeypatch.setattr(db, "commit", fail_commit)
    collection_ids = _create_seed_collections(db)
    route_book_before = _simple_table_snapshot(db, "route_books")
    route_version_before = _simple_table_snapshot(db, "route_versions")
    segment_before = _simple_table_snapshot(db, "segments")
    effort_before = _simple_table_snapshot(db, "segment_efforts")
    guide_before = _route_guides_snapshot(db)
    content_routes_before = _content_routes_snapshot()

    training_route = add_collection_route(
        db,
        collection_id=collection_ids["xishan-training-system"],
        route_book_id=1,
        reviewed_route_version_id=1,
        role="primary",
        seq=1,
        reason_summary="Schema-owner reviewed Xishan route membership.",
        accepted_judgment_run_id=1,
    )
    training_segment = add_collection_segment(
        db,
        collection_id=collection_ids["xishan-training-system"],
        segment_id=1,
        role="core",
        seq=2,
        reason_summary="Schema-owner reviewed Xishan segment membership.",
        accepted_judgment_run_id=2,
    )
    race_route = add_collection_route(
        db,
        collection_id=collection_ids["tour-of-taiyuan-route-family"],
        route_book_id=1,
        reviewed_route_version_id=1,
        role="featured",
        seq=1,
        reason_summary="Schema-owner reviewed race route family membership.",
        accepted_judgment_run_id=1,
    )

    route_line_hash = db.execute(text("SELECT line_hash FROM route_versions WHERE id = 1")).scalar_one()
    segment_geometry_hash = db.execute(
        text("SELECT geometry_hash FROM route_cognition_segments WHERE segment_id = 1")
    ).scalar_one()
    route_rows = db.execute(
        text(
            """
            SELECT
                rc.name AS collection,
                rb.name AS target,
                'collection_routes' AS table_name,
                cr.source_kind,
                cr.membership_status,
                cr.reviewed_route_line_hash,
                rv.line_hash AS source_hash,
                cr.accepted_judgment_run_type,
                jr.status AS judgment_status,
                jr.confidence_state AS judgment_confidence_state,
                cr.reason_summary,
                cr.seq
            FROM collection_routes cr
            JOIN route_collections rc ON rc.id = cr.collection_id
            JOIN route_books rb ON rb.id = cr.route_book_id
            JOIN route_versions rv ON rv.id = cr.reviewed_route_version_id
                                  AND rv.route_book_id = cr.route_book_id
            JOIN judgment_runs jr ON jr.id = cr.accepted_judgment_run_id
                                  AND jr.run_type = cr.accepted_judgment_run_type
            ORDER BY cr.collection_id, cr.seq
            """
        )
    ).all()
    segment_rows = db.execute(
        text(
            """
            SELECT
                rc.name AS collection,
                s.name AS target,
                'collection_segments' AS table_name,
                cs.source_kind,
                cs.membership_status,
                cs.segment_geometry_hash,
                rcs.geometry_hash AS source_hash,
                cs.accepted_judgment_run_type,
                jr.status AS judgment_status,
                jr.confidence_state AS judgment_confidence_state,
                cs.reason_summary,
                cs.seq
            FROM collection_segments cs
            JOIN route_collections rc ON rc.id = cs.collection_id
            JOIN segments s ON s.id = cs.segment_id
            JOIN route_cognition_segments rcs ON rcs.segment_id = cs.segment_id
            JOIN judgment_runs jr ON jr.id = cs.accepted_judgment_run_id
                                  AND jr.run_type = cs.accepted_judgment_run_type
            ORDER BY cs.collection_id, cs.seq
            """
        )
    ).all()
    membership_summary = [
        {
            "collection": row.collection,
            "target": row.target,
            "table": row.table_name,
            "source_kind": row.source_kind,
            "membership_status": row.membership_status,
            "accepted_judgment_run_type": row.accepted_judgment_run_type,
            "judgment_status": row.judgment_status,
            "judgment_confidence_state": row.judgment_confidence_state,
            "hash_matches_source": (
                row.reviewed_route_line_hash == row.source_hash
                if row.table_name == "collection_routes"
                else row.segment_geometry_hash == row.source_hash
            ),
            "reason_summary": row.reason_summary,
        }
        for row in [route_rows[0], segment_rows[0], route_rows[1]]
    ]

    assert membership_summary == [
        {
            "collection": "西山训练体系",
            "target": "环西山正骑",
            "table": "collection_routes",
            "source_kind": "manual_curated",
            "membership_status": "active",
            "accepted_judgment_run_type": "human_review",
            "judgment_status": "succeeded",
            "judgment_confidence_state": "human_accepted",
            "hash_matches_source": True,
            "reason_summary": "Schema-owner reviewed Xishan route membership.",
        },
        {
            "collection": "西山训练体系",
            "target": "横岭",
            "table": "collection_segments",
            "source_kind": "manual_curated",
            "membership_status": "active",
            "accepted_judgment_run_type": "human_review",
            "judgment_status": "succeeded",
            "judgment_confidence_state": "stable",
            "hash_matches_source": True,
            "reason_summary": "Schema-owner reviewed Xishan segment membership.",
        },
        {
            "collection": "环太原赛路线族",
            "target": "环西山正骑",
            "table": "collection_routes",
            "source_kind": "manual_curated",
            "membership_status": "active",
            "accepted_judgment_run_type": "human_review",
            "judgment_status": "succeeded",
            "judgment_confidence_state": "human_accepted",
            "hash_matches_source": True,
            "reason_summary": "Schema-owner reviewed race route family membership.",
        },
    ]
    assert training_route.reviewed_route_line_hash == route_line_hash
    assert race_route.reviewed_route_line_hash == route_line_hash
    assert training_segment.segment_geometry_hash == segment_geometry_hash
    assert {training_route.accepted_judgment_run_type, race_route.accepted_judgment_run_type} == {
        "human_review"
    }
    assert training_segment.accepted_judgment_run_type == "human_review"
    assert db.execute(text("SELECT count(*) FROM collection_routes")).scalar_one() == 2
    assert db.execute(text("SELECT count(*) FROM collection_segments")).scalar_one() == 1
    _assert_forbidden_tables_empty(db)
    assert _simple_table_snapshot(db, "route_books") == route_book_before
    assert _simple_table_snapshot(db, "route_versions") == route_version_before
    assert _simple_table_snapshot(db, "segments") == segment_before
    assert _simple_table_snapshot(db, "segment_efforts") == effort_before
    assert _route_guides_snapshot(db) == guide_before
    assert _content_routes_snapshot() == content_routes_before


def test_seed_rejects_raw_segment_not_in_route_cognition_segments(
    db, collection_membership_seed_dry_run_tables
):
    collection_ids = _create_seed_collections(db)

    with pytest.raises(CollectionMembershipWriterError, match="route_cognition_segments"):
        add_collection_segment(
            db,
            collection_id=collection_ids["xishan-training-system"],
            segment_id=2,
            role="core",
            accepted_judgment_run_id=7,
        )


def test_seed_rejects_route_version_book_mismatch(db, collection_membership_seed_dry_run_tables):
    collection_ids = _create_seed_collections(db)

    with pytest.raises(CollectionMembershipWriterError, match="reviewed_route_version_id"):
        add_collection_route(
            db,
            collection_id=collection_ids["xishan-training-system"],
            route_book_id=1,
            reviewed_route_version_id=2,
            role="primary",
            accepted_judgment_run_id=7,
        )


@pytest.mark.parametrize(
    ("writer", "kwargs"),
    [
        (
            add_collection_route,
            {
                "route_book_id": 1,
                "reviewed_route_version_id": 1,
                "role": "primary",
                "accepted_judgment_run_id": 1,
            },
        ),
        (
            add_collection_segment,
            {
                "segment_id": 1,
                "role": "core",
                "accepted_judgment_run_id": 2,
            },
        ),
    ],
)
def test_seed_rejects_candidate_accepted_source_kind(
    db, collection_membership_seed_dry_run_tables, writer, kwargs
):
    collection_ids = _create_seed_collections(db)

    with pytest.raises(CollectionMembershipWriterError, match="source_kind"):
        writer(
            db,
            collection_id=collection_ids["xishan-training-system"],
            source_kind="candidate_accepted",
            **kwargs,
        )


@pytest.mark.parametrize(
    ("writer", "kwargs"),
    [
        (
            add_collection_route,
            {
                "route_book_id": 1,
                "reviewed_route_version_id": 1,
                "role": "primary",
                "accepted_judgment_run_id": 1,
            },
        ),
        (
            add_collection_segment,
            {
                "segment_id": 1,
                "role": "core",
                "accepted_judgment_run_id": 2,
            },
        ),
    ],
)
def test_seed_rejects_legacy_import_without_source(
    db, collection_membership_seed_dry_run_tables, writer, kwargs
):
    collection_ids = _create_seed_collections(db)

    with pytest.raises(CollectionMembershipWriterError, match="legacy_import"):
        writer(
            db,
            collection_id=collection_ids["xishan-training-system"],
            source_kind="legacy_import",
            **kwargs,
        )


@pytest.mark.parametrize(
    ("writer", "kwargs"),
    [
        (
            add_collection_route,
            {
                "route_book_id": 1,
                "reviewed_route_version_id": 1,
                "role": "primary",
            },
        ),
        (
            add_collection_segment,
            {
                "segment_id": 1,
                "role": "core",
            },
        ),
    ],
)
def test_seed_rejects_non_human_judgment(db, collection_membership_seed_dry_run_tables, writer, kwargs):
    collection_ids = _create_seed_collections(db)

    with pytest.raises(CollectionMembershipWriterError):
        writer(
            db,
            collection_id=collection_ids["xishan-training-system"],
            accepted_judgment_run_id=3,
            **kwargs,
        )


def test_seed_rejects_active_duplicate_collection_route(db, collection_membership_seed_dry_run_tables):
    collection_ids = _create_seed_collections(db)
    add_collection_route(
        db,
        collection_id=collection_ids["xishan-training-system"],
        route_book_id=1,
        reviewed_route_version_id=1,
        role="primary",
        seq=1,
        accepted_judgment_run_id=1,
    )

    with pytest.raises(CollectionMembershipWriterError, match="active route"):
        add_collection_route(
            db,
            collection_id=collection_ids["xishan-training-system"],
            route_book_id=1,
            reviewed_route_version_id=1,
            role="featured",
            seq=2,
            accepted_judgment_run_id=1,
        )


def test_seed_rejects_active_duplicate_collection_segment(db, collection_membership_seed_dry_run_tables):
    collection_ids = _create_seed_collections(db)
    add_collection_segment(
        db,
        collection_id=collection_ids["xishan-training-system"],
        segment_id=1,
        role="core",
        seq=1,
        accepted_judgment_run_id=2,
    )

    with pytest.raises(CollectionMembershipWriterError, match="active segment"):
        add_collection_segment(
            db,
            collection_id=collection_ids["xishan-training-system"],
            segment_id=1,
            role="supporting",
            seq=2,
            accepted_judgment_run_id=2,
        )


@pytest.mark.parametrize("history_status", ["deprecated", "superseded"])
def test_seed_history_membership_does_not_block_new_active(
    db, collection_membership_seed_dry_run_tables, history_status
):
    collection_ids = _create_seed_collections(db)
    add_collection_route(
        db,
        collection_id=collection_ids["xishan-training-system"],
        route_book_id=1,
        reviewed_route_version_id=1,
        role="primary",
        membership_status=history_status,
        accepted_judgment_run_id=1,
    )
    add_collection_segment(
        db,
        collection_id=collection_ids["xishan-training-system"],
        segment_id=1,
        role="core",
        membership_status=history_status,
        accepted_judgment_run_id=2,
    )

    add_collection_route(
        db,
        collection_id=collection_ids["xishan-training-system"],
        route_book_id=1,
        reviewed_route_version_id=1,
        role="featured",
        membership_status="active",
        accepted_judgment_run_id=1,
    )
    add_collection_segment(
        db,
        collection_id=collection_ids["xishan-training-system"],
        segment_id=1,
        role="supporting",
        membership_status="active",
        accepted_judgment_run_id=2,
    )

    assert db.execute(text("SELECT count(*) FROM collection_routes")).scalar_one() == 2
    assert db.execute(text("SELECT count(*) FROM collection_segments")).scalar_one() == 2


def _create_seed_collections(db) -> dict[str, int]:
    collection_ids: dict[str, int] = {}
    for seed in TAIYUAN_COLLECTION_SEEDS:
        collection = create_route_collection(
            db,
            name=seed["name"],
            slug=seed["slug"],
            collection_type=seed["collection_type"],
            city=seed["city"],
        )
        collection_ids[seed["slug"]] = collection.id
    return collection_ids


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


def _route_guides_snapshot(db) -> list[tuple[int, str]]:
    return [
        (row.id, row.content_md)
        for row in db.execute(text("SELECT id, content_md FROM route_guides ORDER BY id")).all()
    ]


def _simple_table_snapshot(db, table_name: str) -> list[tuple]:
    return [tuple(row) for row in db.execute(text(f"SELECT * FROM {table_name} ORDER BY id")).all()]


def _assert_forbidden_tables_empty(db) -> None:
    for table_name in FORBIDDEN_EMPTY_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0


def _seed_route_segment_and_judgment_rows(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (
                id, run_type, status, confidence_state, route_book_id, route_version_id, segment_id
            )
            VALUES
                (1, 'human_review', 'succeeded', 'human_accepted', 1, 1, NULL),
                (2, 'human_review', 'succeeded', 'stable', NULL, NULL, 1),
                (3, 'semantic_agent', 'succeeded', 'stable', NULL, NULL, NULL),
                (7, 'human_review', 'succeeded', 'stable', NULL, NULL, NULL)
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_books (
                id, name, distance, reference_line, source, city, visibility, publish_status
            )
            VALUES
                (1, '环西山正骑', 42000.0, 'LINESTRING(0 0, 1 1)', 'manual_drawn', 'taiyuan', 'private', 'draft'),
                (2, '错配路线', 12000.0, 'LINESTRING(2 2, 3 3)', 'manual_drawn', 'taiyuan', 'private', 'draft')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_versions (
                id, route_book_id, version_no, reference_line_snapshot, line_hash, distance
            )
            VALUES
                (1, 1, 1, 'LINESTRING(0 0, 1 1)', 'route-version-line-hash-xishan', 42000.0),
                (2, 2, 1, 'LINESTRING(2 2, 3 3)', 'route-version-line-hash-other', 12000.0)
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO segments (id, name, reference_line)
            VALUES
                (1, '横岭', 'LINESTRING(0 0, 1 1)'),
                (2, '裸赛段', 'LINESTRING(8 8, 9 9)')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_cognition_segments (segment_id, geometry_hash)
            VALUES (1, 'segment-geometry-hash-hengling')
            """
        )
    )
    db.execute(text("INSERT INTO segment_efforts (id, segment_id) VALUES (1, 1)"))
    db.execute(text("INSERT INTO route_guides (id, content_md) VALUES (1, 'original guide')"))


def _create_seed_dry_run_tables(db) -> None:
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
                UNIQUE(id, run_type)
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE route_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                distance REAL NOT NULL,
                reference_line TEXT NOT NULL,
                source TEXT NOT NULL,
                city TEXT NOT NULL DEFAULT 'unknown',
                visibility TEXT NOT NULL DEFAULT 'private',
                publish_status TEXT NOT NULL DEFAULT 'draft'
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
                version_no INTEGER NOT NULL,
                reference_line_snapshot TEXT NOT NULL,
                line_hash TEXT NOT NULL,
                distance REAL NOT NULL,
                UNIQUE(id, route_book_id),
                FOREIGN KEY(route_book_id) REFERENCES route_books(id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                reference_line TEXT NOT NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE route_cognition_segments (
                segment_id INTEGER PRIMARY KEY,
                geometry_hash TEXT NOT NULL,
                UNIQUE(segment_id, geometry_hash),
                FOREIGN KEY(segment_id) REFERENCES segments(id)
            )
            """
        )
    )
    db.execute(text("CREATE TABLE segment_efforts (id INTEGER PRIMARY KEY AUTOINCREMENT, segment_id INTEGER NOT NULL)"))
    db.execute(text("CREATE TABLE route_guides (id INTEGER PRIMARY KEY AUTOINCREMENT, content_md TEXT NOT NULL)"))
    _create_collection_routes_table(db)
    _create_collection_segments_table(db)
    for table_name in FORBIDDEN_EMPTY_TABLES:
        db.execute(text(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY AUTOINCREMENT)"))


def _create_collection_routes_table(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE collection_routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                route_book_id INTEGER NOT NULL,
                reviewed_route_version_id INTEGER NOT NULL,
                reviewed_route_line_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                seq INTEGER,
                importance INTEGER,
                membership_status TEXT NOT NULL DEFAULT 'active',
                source_kind TEXT NOT NULL,
                source_ref TEXT,
                accepted_judgment_run_id INTEGER NOT NULL,
                accepted_judgment_run_type TEXT NOT NULL DEFAULT 'human_review',
                display_priority INTEGER,
                reason_summary TEXT,
                metadata_json TEXT,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(collection_id) REFERENCES route_collections(id),
                FOREIGN KEY(route_book_id) REFERENCES route_books(id),
                FOREIGN KEY(reviewed_route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id),
                FOREIGN KEY(accepted_judgment_run_id, accepted_judgment_run_type) REFERENCES judgment_runs(id, run_type)
            )
            """
        )
    )


def _create_collection_segments_table(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE collection_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                segment_geometry_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                seq INTEGER,
                importance INTEGER,
                membership_status TEXT NOT NULL DEFAULT 'active',
                source_kind TEXT NOT NULL,
                source_ref TEXT,
                accepted_judgment_run_id INTEGER NOT NULL,
                accepted_judgment_run_type TEXT NOT NULL DEFAULT 'human_review',
                display_priority INTEGER,
                reason_summary TEXT,
                metadata_json TEXT,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(collection_id) REFERENCES route_collections(id),
                FOREIGN KEY(segment_id) REFERENCES route_cognition_segments(segment_id),
                FOREIGN KEY(segment_id, segment_geometry_hash) REFERENCES route_cognition_segments(segment_id, geometry_hash),
                FOREIGN KEY(accepted_judgment_run_id, accepted_judgment_run_type) REFERENCES judgment_runs(id, run_type)
            )
            """
        )
    )


def _drop_seed_dry_run_tables(db) -> None:
    for table_name in (
        *FORBIDDEN_EMPTY_TABLES,
        "collection_segments",
        "collection_routes",
        "route_guides",
        "segment_efforts",
        "route_cognition_segments",
        "segments",
        "route_versions",
        "route_books",
        "route_collections",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
