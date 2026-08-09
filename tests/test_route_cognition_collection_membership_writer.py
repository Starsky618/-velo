"""collection 成员写入测试——像给专题目录夹插索引卡，只准插路线/赛段成员卡。"""

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


FORBIDDEN_EMPTY_TABLES = (
    "route_segments",
    "route_concept_candidates",
    "segment_concept_candidates",
    "collection_concept_candidates",
    "evidence_items",
)


@pytest.fixture()
def collection_membership_writer_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_collection_membership_tables(db)
    _create_collection_membership_tables(db)
    _seed_collection_membership_base(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_collection_membership_tables(db)


def test_add_collection_route_creates_manual_membership_with_route_version_hash(
    db, collection_membership_writer_tables
):
    membership = add_collection_route(
        db,
        collection_id=1,
        route_book_id=1,
        reviewed_route_version_id=1,
        role="primary",
        seq=1,
        importance=80,
        accepted_judgment_run_id=1,
    )

    assert membership.collection_id == 1
    assert membership.route_book_id == 1
    assert membership.reviewed_route_version_id == 1
    assert membership.reviewed_route_line_hash == "route-hash-a"
    assert membership.membership_status == "active"
    assert membership.source_kind == "manual_curated"
    assert membership.accepted_judgment_run_type == "human_review"
    assert db.execute(text("SELECT count(*) FROM collection_routes")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM collection_segments")).scalar_one() == 0
    _assert_forbidden_tables_empty(db)


def test_add_collection_route_rejects_route_version_book_mismatch(db, collection_membership_writer_tables):
    with pytest.raises(CollectionMembershipWriterError, match="reviewed_route_version_id"):
        add_collection_route(
            db,
            collection_id=1,
            route_book_id=1,
            reviewed_route_version_id=2,
            role="primary",
            accepted_judgment_run_id=1,
        )


@pytest.mark.parametrize("judgment_run_id", [3, 4])
def test_add_collection_route_rejects_non_accepted_human_review_judgment(
    db, collection_membership_writer_tables, judgment_run_id
):
    with pytest.raises(CollectionMembershipWriterError):
        add_collection_route(
            db,
            collection_id=1,
            route_book_id=1,
            reviewed_route_version_id=1,
            role="primary",
            accepted_judgment_run_id=judgment_run_id,
        )


@pytest.mark.parametrize("judgment_run_id", [2, 5])
def test_add_collection_route_rejects_human_review_for_other_target(
    db, collection_membership_writer_tables, judgment_run_id
):
    with pytest.raises(CollectionMembershipWriterError, match="judgment"):
        add_collection_route(
            db,
            collection_id=1,
            route_book_id=1,
            reviewed_route_version_id=1,
            role="primary",
            accepted_judgment_run_id=judgment_run_id,
        )


def test_add_collection_route_rejects_candidate_accepted_source_kind(db, collection_membership_writer_tables):
    with pytest.raises(CollectionMembershipWriterError, match="source_kind"):
        add_collection_route(
            db,
            collection_id=1,
            route_book_id=1,
            reviewed_route_version_id=1,
            role="primary",
            source_kind="candidate_accepted",
            accepted_judgment_run_id=1,
        )


def test_add_collection_route_rejects_legacy_import_without_source(db, collection_membership_writer_tables):
    with pytest.raises(CollectionMembershipWriterError, match="legacy_import"):
        add_collection_route(
            db,
            collection_id=1,
            route_book_id=1,
            reviewed_route_version_id=1,
            role="primary",
            source_kind="legacy_import",
            accepted_judgment_run_id=1,
        )


def test_add_collection_route_allows_legacy_import_with_source_ref(db, collection_membership_writer_tables):
    membership = add_collection_route(
        db,
        collection_id=1,
        route_book_id=1,
        reviewed_route_version_id=1,
        role="reference",
        source_kind="legacy_import",
        source_ref="legacy:collection-routes:1",
        accepted_judgment_run_id=1,
    )

    assert membership.source_kind == "legacy_import"
    assert membership.source_ref == "legacy:collection-routes:1"


def test_add_collection_route_rejects_active_duplicate_route(db, collection_membership_writer_tables):
    add_collection_route(
        db,
        collection_id=1,
        route_book_id=1,
        reviewed_route_version_id=1,
        role="primary",
        seq=1,
        accepted_judgment_run_id=1,
    )

    with pytest.raises(CollectionMembershipWriterError, match="active route"):
        add_collection_route(
            db,
            collection_id=1,
            route_book_id=1,
            reviewed_route_version_id=1,
            role="featured",
            seq=2,
            accepted_judgment_run_id=1,
        )


def test_add_collection_route_allows_deprecated_history_before_new_active(db, collection_membership_writer_tables):
    add_collection_route(
        db,
        collection_id=1,
        route_book_id=1,
        reviewed_route_version_id=1,
        role="primary",
        membership_status="deprecated",
        accepted_judgment_run_id=1,
    )
    add_collection_route(
        db,
        collection_id=1,
        route_book_id=1,
        reviewed_route_version_id=1,
        role="featured",
        membership_status="active",
        accepted_judgment_run_id=1,
    )

    assert db.execute(text("SELECT count(*) FROM collection_routes")).scalar_one() == 2


def test_add_collection_route_rejects_active_duplicate_seq(db, collection_membership_writer_tables):
    add_collection_route(
        db,
        collection_id=1,
        route_book_id=1,
        reviewed_route_version_id=1,
        role="primary",
        seq=7,
        accepted_judgment_run_id=1,
    )

    with pytest.raises(CollectionMembershipWriterError, match="active seq"):
        add_collection_route(
            db,
            collection_id=1,
            route_book_id=2,
            reviewed_route_version_id=2,
            role="featured",
            seq=7,
            accepted_judgment_run_id=7,
        )


def test_add_collection_segment_creates_manual_membership_with_segment_hash(
    db, collection_membership_writer_tables
):
    membership = add_collection_segment(
        db,
        collection_id=1,
        segment_id=1,
        role="core",
        seq=1,
        importance=75,
        accepted_judgment_run_id=2,
    )

    assert membership.collection_id == 1
    assert membership.segment_id == 1
    assert membership.segment_geometry_hash == "segment-hash-a"
    assert membership.membership_status == "active"
    assert membership.source_kind == "manual_curated"
    assert membership.accepted_judgment_run_type == "human_review"
    assert db.execute(text("SELECT count(*) FROM collection_segments")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM collection_routes")).scalar_one() == 0
    _assert_forbidden_tables_empty(db)


def test_add_collection_segment_rejects_raw_segment(db, collection_membership_writer_tables):
    with pytest.raises(CollectionMembershipWriterError, match="route_cognition_segments"):
        add_collection_segment(
            db,
            collection_id=1,
            segment_id=2,
            role="core",
            accepted_judgment_run_id=2,
        )


def test_add_collection_segment_rejects_suspended_cognition_segment(
    db, collection_membership_writer_tables
):
    db.execute(
        text(
            "UPDATE route_cognition_segments "
            "SET eligibility_status = 'suspended' WHERE segment_id = 1"
        )
    )

    with pytest.raises(CollectionMembershipWriterError, match="must be active"):
        add_collection_segment(
            db,
            collection_id=1,
            segment_id=1,
            role="core",
            accepted_judgment_run_id=2,
        )


def test_add_collection_segment_rejects_non_human_judgment(db, collection_membership_writer_tables):
    with pytest.raises(CollectionMembershipWriterError):
        add_collection_segment(
            db,
            collection_id=1,
            segment_id=1,
            role="core",
            accepted_judgment_run_id=3,
        )


@pytest.mark.parametrize("judgment_run_id", [1, 6])
def test_add_collection_segment_rejects_human_review_for_other_target(
    db, collection_membership_writer_tables, judgment_run_id
):
    with pytest.raises(CollectionMembershipWriterError, match="judgment"):
        add_collection_segment(
            db,
            collection_id=1,
            segment_id=1,
            role="core",
            accepted_judgment_run_id=judgment_run_id,
        )


def test_add_collection_segment_rejects_candidate_accepted_source_kind(db, collection_membership_writer_tables):
    with pytest.raises(CollectionMembershipWriterError, match="source_kind"):
        add_collection_segment(
            db,
            collection_id=1,
            segment_id=1,
            role="core",
            source_kind="candidate_accepted",
            accepted_judgment_run_id=2,
        )


def test_add_collection_segment_rejects_legacy_import_without_source(db, collection_membership_writer_tables):
    with pytest.raises(CollectionMembershipWriterError, match="legacy_import"):
        add_collection_segment(
            db,
            collection_id=1,
            segment_id=1,
            role="core",
            source_kind="legacy_import",
            accepted_judgment_run_id=2,
        )


def test_add_collection_segment_allows_legacy_import_with_reason_summary(db, collection_membership_writer_tables):
    membership = add_collection_segment(
        db,
        collection_id=1,
        segment_id=1,
        role="supporting",
        source_kind="legacy_import",
        reason_summary="legacy reviewed segment membership",
        accepted_judgment_run_id=2,
    )

    assert membership.source_kind == "legacy_import"
    assert membership.reason_summary == "legacy reviewed segment membership"


def test_add_collection_segment_rejects_active_duplicate_segment(db, collection_membership_writer_tables):
    add_collection_segment(
        db,
        collection_id=1,
        segment_id=1,
        role="core",
        seq=1,
        accepted_judgment_run_id=2,
    )

    with pytest.raises(CollectionMembershipWriterError, match="active segment"):
        add_collection_segment(
            db,
            collection_id=1,
            segment_id=1,
            role="supporting",
            seq=2,
            accepted_judgment_run_id=2,
        )


def test_add_collection_segment_allows_deprecated_history_before_new_active(
    db, collection_membership_writer_tables
):
    add_collection_segment(
        db,
        collection_id=1,
        segment_id=1,
        role="core",
        membership_status="deprecated",
        accepted_judgment_run_id=2,
    )
    add_collection_segment(
        db,
        collection_id=1,
        segment_id=1,
        role="supporting",
        membership_status="active",
        accepted_judgment_run_id=2,
    )

    assert db.execute(text("SELECT count(*) FROM collection_segments")).scalar_one() == 2


def test_add_collection_segment_rejects_active_duplicate_seq(db, collection_membership_writer_tables):
    add_collection_segment(
        db,
        collection_id=1,
        segment_id=1,
        role="core",
        seq=4,
        accepted_judgment_run_id=2,
    )

    with pytest.raises(CollectionMembershipWriterError, match="active seq"):
        add_collection_segment(
            db,
            collection_id=1,
            segment_id=3,
            role="supporting",
            seq=4,
            accepted_judgment_run_id=7,
        )


@pytest.mark.parametrize(
    ("writer", "kwargs", "metadata_json"),
    [
        (
            add_collection_route,
            {
                "collection_id": 1,
                "route_book_id": 1,
                "reviewed_route_version_id": 1,
                "role": "primary",
                "accepted_judgment_run_id": 1,
            },
            {"nested": [{"routes": [1]}]},
        ),
        (
            add_collection_route,
            {
                "collection_id": 1,
                "route_book_id": 1,
                "reviewed_route_version_id": 1,
                "role": "primary",
                "accepted_judgment_run_id": 1,
            },
            {"Nested": [{"Reviewed_Route_Line_Hash": "fake"}]},
        ),
        (
            add_collection_segment,
            {
                "collection_id": 1,
                "segment_id": 1,
                "role": "core",
                "accepted_judgment_run_id": 2,
            },
            {"nested": [{"roles": ["core"]}]},
        ),
        (
            add_collection_segment,
            {
                "collection_id": 1,
                "segment_id": 1,
                "role": "core",
                "accepted_judgment_run_id": 2,
            },
            {"Nested": [{"Segment_Geometry_Hash": "fake"}]},
        ),
    ],
)
def test_membership_metadata_cannot_hide_membership_truth(
    db, collection_membership_writer_tables, writer, kwargs, metadata_json
):
    with pytest.raises(CollectionMembershipWriterError, match="metadata_json"):
        writer(db, **kwargs, metadata_json=metadata_json)


def test_membership_writer_does_not_commit_or_mutate_forbidden_surfaces(
    db, collection_membership_writer_tables, monkeypatch
):
    def fail_commit():
        raise AssertionError("collection membership writer must not commit")

    monkeypatch.setattr(db, "commit", fail_commit)
    route_book_before = _simple_table_snapshot(db, "route_books")
    route_version_before = _simple_table_snapshot(db, "route_versions")
    segment_before = _simple_table_snapshot(db, "segments")
    effort_before = _simple_table_snapshot(db, "segment_efforts")
    guide_before = _route_guides_snapshot(db)
    content_routes_before = _content_routes_snapshot()

    add_collection_route(
        db,
        collection_id=1,
        route_book_id=1,
        reviewed_route_version_id=1,
        role="primary",
        seq=1,
        accepted_judgment_run_id=1,
    )
    add_collection_segment(
        db,
        collection_id=1,
        segment_id=1,
        role="core",
        seq=2,
        accepted_judgment_run_id=2,
    )

    assert _simple_table_snapshot(db, "route_books") == route_book_before
    assert _simple_table_snapshot(db, "route_versions") == route_version_before
    assert _simple_table_snapshot(db, "segments") == segment_before
    assert _simple_table_snapshot(db, "segment_efforts") == effort_before
    assert _route_guides_snapshot(db) == guide_before
    assert _content_routes_snapshot() == content_routes_before
    _assert_forbidden_tables_empty(db)
    _assert_candidate_tables_absent(db)


def _create_collection_membership_tables(db) -> None:
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
    db.execute(text("CREATE TABLE route_collections (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(
        text(
            """
            CREATE TABLE route_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                distance REAL NOT NULL,
                reference_line TEXT NOT NULL,
                source TEXT NOT NULL,
                city TEXT NOT NULL DEFAULT 'unknown'
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
                eligibility_status TEXT NOT NULL DEFAULT 'active',
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
    db.execute(text("CREATE TABLE route_segments (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE route_concept_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE segment_concept_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_concept_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE evidence_items (id INTEGER PRIMARY KEY AUTOINCREMENT)"))


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
                CHECK (role IN ('primary', 'featured', 'alternate', 'connector', 'reference', 'supporting')),
                CHECK (membership_status IN ('active', 'deprecated', 'superseded')),
                CHECK (source_kind IN ('manual_curated', 'legacy_import')),
                CHECK (accepted_judgment_run_type = 'human_review'),
                CHECK (source_kind <> 'legacy_import' OR source_ref IS NOT NULL OR reason_summary IS NOT NULL),
                CHECK (seq IS NULL OR seq >= 1),
                CHECK (importance IS NULL OR (importance >= 0 AND importance <= 100)),
                CHECK (display_priority IS NULL OR (display_priority >= 0 AND display_priority <= 100)),
                FOREIGN KEY(collection_id) REFERENCES route_collections(id),
                FOREIGN KEY(route_book_id) REFERENCES route_books(id),
                FOREIGN KEY(reviewed_route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id),
                FOREIGN KEY(accepted_judgment_run_id, accepted_judgment_run_type) REFERENCES judgment_runs(id, run_type)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_collection_routes_active_route
            ON collection_routes(collection_id, route_book_id)
            WHERE membership_status = 'active'
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_collection_routes_active_seq
            ON collection_routes(collection_id, seq)
            WHERE membership_status = 'active' AND seq IS NOT NULL
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
                CHECK (role IN ('core', 'connector', 'landmark', 'risk_area', 'training_interval', 'supporting')),
                CHECK (membership_status IN ('active', 'deprecated', 'superseded')),
                CHECK (source_kind IN ('manual_curated', 'legacy_import')),
                CHECK (accepted_judgment_run_type = 'human_review'),
                CHECK (source_kind <> 'legacy_import' OR source_ref IS NOT NULL OR reason_summary IS NOT NULL),
                CHECK (seq IS NULL OR seq >= 1),
                CHECK (importance IS NULL OR (importance >= 0 AND importance <= 100)),
                CHECK (display_priority IS NULL OR (display_priority >= 0 AND display_priority <= 100)),
                FOREIGN KEY(collection_id) REFERENCES route_collections(id),
                FOREIGN KEY(segment_id) REFERENCES route_cognition_segments(segment_id),
                FOREIGN KEY(segment_id, segment_geometry_hash) REFERENCES route_cognition_segments(segment_id, geometry_hash),
                FOREIGN KEY(accepted_judgment_run_id, accepted_judgment_run_type) REFERENCES judgment_runs(id, run_type)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_collection_segments_active_segment
            ON collection_segments(collection_id, segment_id)
            WHERE membership_status = 'active'
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_collection_segments_active_seq
            ON collection_segments(collection_id, seq)
            WHERE membership_status = 'active' AND seq IS NOT NULL
            """
        )
    )


def _seed_collection_membership_base(db) -> None:
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
                (4, 'human_review', 'failed', 'human_accepted', 1, 1, NULL),
                (5, 'human_review', 'succeeded', 'human_accepted', 2, 2, NULL),
                (6, 'human_review', 'succeeded', 'stable', NULL, NULL, 3),
                (7, 'human_review', 'succeeded', 'stable', NULL, NULL, NULL)
            """
        )
    )
    db.execute(text("INSERT INTO route_collections (id) VALUES (1), (2)"))
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
                id, route_book_id, version_no, reference_line_snapshot, line_hash, distance
            )
            VALUES
                (1, 1, 1, 'LINESTRING(0 0, 1 1)', 'route-hash-a', 10000.0),
                (2, 2, 1, 'LINESTRING(0 0, 2 2)', 'route-hash-b', 12000.0)
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO segments (id, name, reference_line)
            VALUES
                (1, 'Whitelisted Segment A', 'LINESTRING(0 0, 1 1)'),
                (2, 'Raw Segment', 'LINESTRING(9 9, 10 10)'),
                (3, 'Whitelisted Segment B', 'LINESTRING(0 0, 2 2)')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_cognition_segments (segment_id, geometry_hash)
            VALUES
                (1, 'segment-hash-a'),
                (3, 'segment-hash-b')
            """
        )
    )
    db.execute(text("INSERT INTO segment_efforts (id, segment_id) VALUES (1, 1)"))
    db.execute(text("INSERT INTO route_guides (id, content_md) VALUES (1, 'original guide')"))


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


def _assert_candidate_tables_absent(db) -> None:
    for table_name in (
        "route_segment_candidates",
        "collection_route_candidates",
        "collection_segment_candidates",
    ):
        row = db.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
            {"table_name": table_name},
        ).first()
        assert row is None


def _drop_collection_membership_tables(db) -> None:
    for table_name in (
        "evidence_items",
        "collection_concept_candidates",
        "segment_concept_candidates",
        "route_concept_candidates",
        "collection_segments",
        "collection_routes",
        "route_segments",
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
