"""route_segments 写入测试——像路线装配单的模拟考场，只准登记组件，不准改路线图纸。"""

from __future__ import annotations

import hashlib
import math
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

from app.route_cognition.geometry_hash import hash_segment_geometry_wkt
from app.route_cognition.services.route_segment_writer import (
    RouteSegmentWriterError,
    add_route_custom_geometry,
    add_route_segment_clip,
)


FORBIDDEN_EMPTY_TABLES = (
    "route_concept_candidates",
    "segment_concept_candidates",
    "collection_concept_candidates",
    "route_collection_candidates",
    "segment_collection_candidates",
    "evidence_items",
)


@pytest.fixture()
def route_segment_writer_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_route_segment_writer_tables(db)
    _create_route_segment_writer_tables(db)
    _seed_route_segment_writer_base(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_route_segment_writer_tables(db)


def test_add_route_segment_clip_creates_manual_component_with_copied_hashes(
    db, route_segment_writer_tables
):
    component = add_route_segment_clip(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=1,
        segment_id=1,
        component_geometry="LINESTRING(0 0, 1 1)",
        direction="forward",
        start_fraction=0.1,
        end_fraction=0.9,
        accepted_judgment_run_id=1,
    )

    assert component.route_book_id == 1
    assert component.route_version_id == 1
    assert component.route_line_hash == "route-hash-a"
    assert component.seq == 1
    assert component.component_type == "segment_clip"
    assert component.segment_id == 1
    assert component.segment_geometry_hash == "segment-hash-a"
    assert component.component_geometry_hash == _geometry_hash("LINESTRING(0 0, 1 1)")
    assert component.direction == "forward"
    assert component.membership_status == "active"
    assert component.source_kind == "manual_curated"
    assert component.accepted_judgment_run_type == "human_review"
    assert db.execute(text("SELECT count(*) FROM route_segments")).scalar_one() == 1
    _assert_forbidden_tables_empty(db)


def test_add_route_segment_clip_requires_component_geometry(db, route_segment_writer_tables):
    with pytest.raises(RouteSegmentWriterError, match="component_geometry"):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            segment_id=1,
            component_geometry="",
            direction="forward",
            accepted_judgment_run_id=1,
        )


def test_add_route_segment_clip_rejects_raw_segment(db, route_segment_writer_tables):
    with pytest.raises(RouteSegmentWriterError, match="route_cognition_segments"):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            segment_id=2,
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="forward",
            accepted_judgment_run_id=1,
        )


def test_add_route_segment_clip_rejects_suspended_cognition_segment(
    db, route_segment_writer_tables
):
    db.execute(
        text(
            "UPDATE route_cognition_segments "
            "SET eligibility_status = 'suspended' WHERE segment_id = 1"
        )
    )

    with pytest.raises(RouteSegmentWriterError, match="must be active"):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            segment_id=1,
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="forward",
            accepted_judgment_run_id=1,
        )


def test_add_route_segment_clip_rejects_route_version_book_mismatch(
    db, route_segment_writer_tables
):
    with pytest.raises(RouteSegmentWriterError, match="route_version_id"):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=2,
            seq=1,
            segment_id=1,
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="forward",
            accepted_judgment_run_id=1,
        )


def test_add_route_segment_clip_rejects_non_human_judgment(db, route_segment_writer_tables):
    with pytest.raises(RouteSegmentWriterError):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            segment_id=1,
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="forward",
            accepted_judgment_run_id=3,
        )


def test_add_route_segment_clip_rejects_failed_human_review(db, route_segment_writer_tables):
    with pytest.raises(RouteSegmentWriterError):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            segment_id=1,
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="forward",
            accepted_judgment_run_id=4,
        )


def test_add_route_segment_clip_rejects_candidate_accepted_source_kind(
    db, route_segment_writer_tables
):
    with pytest.raises(RouteSegmentWriterError, match="source_kind"):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            segment_id=1,
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="forward",
            source_kind="candidate_accepted",
            accepted_judgment_run_id=1,
        )


def test_add_route_segment_clip_rejects_legacy_import_without_source(db, route_segment_writer_tables):
    with pytest.raises(RouteSegmentWriterError, match="legacy_import"):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            segment_id=1,
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="forward",
            source_kind="legacy_import",
            accepted_judgment_run_id=1,
        )


def test_add_route_segment_clip_allows_legacy_import_with_source_ref(db, route_segment_writer_tables):
    component = add_route_segment_clip(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=1,
        segment_id=1,
        component_geometry="LINESTRING(0 0, 1 1)",
        direction="forward",
        source_kind="legacy_import",
        source_ref="legacy:route-segments:1",
        accepted_judgment_run_id=1,
    )

    assert component.source_kind == "legacy_import"
    assert component.source_ref == "legacy:route-segments:1"


def test_add_route_segment_clip_rejects_invalid_direction(db, route_segment_writer_tables):
    with pytest.raises(RouteSegmentWriterError, match="direction"):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            segment_id=1,
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="sideways",
            accepted_judgment_run_id=1,
        )


@pytest.mark.parametrize(
    ("start_fraction", "end_fraction"),
    [
        (0.8, 0.8),
        (0.9, 0.1),
    ],
)
def test_add_route_segment_clip_rejects_start_fraction_not_before_end(
    db, route_segment_writer_tables, start_fraction, end_fraction
):
    with pytest.raises(RouteSegmentWriterError, match="fraction"):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            segment_id=1,
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="forward",
            start_fraction=start_fraction,
            end_fraction=end_fraction,
            accepted_judgment_run_id=1,
        )


@pytest.mark.parametrize(
    ("start_fraction", "end_fraction"),
    [
        (-0.1, 0.8),
        (0.1, 1.2),
        (0.1, None),
        (None, 0.9),
        (math.nan, 0.9),
        (0.1, math.inf),
    ],
)
def test_add_route_segment_clip_rejects_fraction_outside_allowed_shape(
    db, route_segment_writer_tables, start_fraction, end_fraction
):
    with pytest.raises(RouteSegmentWriterError, match="fraction"):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            segment_id=1,
            component_geometry="LINESTRING(0 0, 1 1)",
            direction="forward",
            start_fraction=start_fraction,
            end_fraction=end_fraction,
            accepted_judgment_run_id=1,
        )


def test_add_route_segment_clip_rejects_active_duplicate_seq(db, route_segment_writer_tables):
    add_route_segment_clip(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=7,
        segment_id=1,
        component_geometry="LINESTRING(0 0, 1 1)",
        direction="forward",
        accepted_judgment_run_id=1,
    )

    with pytest.raises(RouteSegmentWriterError, match="active seq"):
        add_route_segment_clip(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=7,
            segment_id=3,
            component_geometry="LINESTRING(0 0, 2 2)",
            direction="reverse",
            accepted_judgment_run_id=7,
        )


@pytest.mark.parametrize("history_status", ["deprecated", "superseded"])
def test_add_route_segment_clip_allows_inactive_history_before_new_active(
    db, route_segment_writer_tables, history_status
):
    add_route_segment_clip(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=3,
        segment_id=1,
        component_geometry="LINESTRING(0 0, 1 1)",
        direction="forward",
        membership_status=history_status,
        accepted_judgment_run_id=1,
    )
    add_route_segment_clip(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=3,
        segment_id=3,
        component_geometry="LINESTRING(0 0, 2 2)",
        direction="reverse",
        membership_status="active",
        accepted_judgment_run_id=7,
    )

    assert db.execute(text("SELECT count(*) FROM route_segments")).scalar_one() == 2


def test_add_route_custom_geometry_creates_manual_component(db, route_segment_writer_tables):
    component = add_route_custom_geometry(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=1,
        component_geometry="LINESTRING(1 1, 2 2)",
        accepted_judgment_run_id=7,
    )

    assert component.route_book_id == 1
    assert component.route_version_id == 1
    assert component.route_line_hash == "route-hash-a"
    assert component.component_type == "custom_geometry"
    assert component.segment_id is None
    assert component.segment_geometry_hash is None
    assert component.direction is None
    assert component.start_fraction is None
    assert component.end_fraction is None
    assert component.component_geometry_hash == _geometry_hash("LINESTRING(1 1, 2 2)")
    assert component.accepted_judgment_run_type == "human_review"
    _assert_forbidden_tables_empty(db)


def test_component_geometry_hash_uses_stable_line_hash_normalization(
    db, route_segment_writer_tables
):
    first = add_route_custom_geometry(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=1,
        component_geometry="LINESTRING(1 1, 2 2)",
        accepted_judgment_run_id=7,
    )
    second = add_route_custom_geometry(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=2,
        component_geometry="LINESTRING(1 1,    2 2)",
        accepted_judgment_run_id=7,
    )

    assert first.component_geometry_hash == second.component_geometry_hash


def test_add_route_custom_geometry_allows_valid_multilinestring(db, route_segment_writer_tables):
    component = add_route_custom_geometry(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=1,
        component_geometry="MULTILINESTRING((0 0, 1 1), (1 1, 2 2))",
        accepted_judgment_run_id=7,
    )

    assert component.component_type == "custom_geometry"
    assert component.component_geometry_hash == _geometry_hash("MULTILINESTRING((0 0, 1 1), (1 1, 2 2))")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"segment_id": 1},
        {"direction": "forward"},
        {"start_fraction": 0.1},
        {"end_fraction": 0.9},
    ],
)
def test_add_route_custom_geometry_rejects_segment_clip_fields(
    db, route_segment_writer_tables, kwargs
):
    with pytest.raises(RouteSegmentWriterError):
        add_route_custom_geometry(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            component_geometry="LINESTRING(1 1, 2 2)",
            accepted_judgment_run_id=7,
            **kwargs,
        )


def test_add_route_custom_geometry_requires_component_geometry(db, route_segment_writer_tables):
    with pytest.raises(RouteSegmentWriterError, match="component_geometry"):
        add_route_custom_geometry(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            component_geometry=None,
            accepted_judgment_run_id=7,
        )


@pytest.mark.parametrize("component_geometry", ["POINT(1 1)", "POLYGON((0 0, 1 1, 1 0, 0 0))"])
def test_add_route_custom_geometry_rejects_non_line_geometry(
    db, route_segment_writer_tables, component_geometry
):
    with pytest.raises(RouteSegmentWriterError, match="line"):
        add_route_custom_geometry(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            component_geometry=component_geometry,
            accepted_judgment_run_id=7,
        )


@pytest.mark.parametrize(
    "component_geometry",
    [
        "LINESTRING(foo)",
        "LINESTRING(0 0)",
        "LINESTRING(0 0, 1 1,)",
        "LINESTRING(0 0,, 1 1)",
        "LINESTRING(0 0 foo, 1 1 bar)",
        "SRID=3857;LINESTRING(0 0, 1 1)",
        "MULTILINESTRING((0 0, 1 1),)",
        "MULTILINESTRING((0 0, 1 1)(2 2, 3 3))",
        "MULTILINESTRING((0 0, 1 1),, (2 2, 3 3))",
    ],
)
def test_add_route_custom_geometry_rejects_invalid_line_geometry(
    db, route_segment_writer_tables, component_geometry
):
    with pytest.raises(RouteSegmentWriterError, match="component_geometry"):
        add_route_custom_geometry(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            component_geometry=component_geometry,
            accepted_judgment_run_id=7,
        )


def test_add_route_custom_geometry_rejects_active_duplicate_seq(db, route_segment_writer_tables):
    add_route_custom_geometry(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=4,
        component_geometry="LINESTRING(1 1, 2 2)",
        accepted_judgment_run_id=7,
    )

    with pytest.raises(RouteSegmentWriterError, match="active seq"):
        add_route_custom_geometry(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=4,
            component_geometry="LINESTRING(2 2, 3 3)",
            accepted_judgment_run_id=7,
        )


@pytest.mark.parametrize(
    "metadata_json",
    [
        {"nested": [{"route_ids": [1]}]},
        {"Nested": [{"Route_Book_Id": 1}]},
        {"deep": {"segments": [{"id": 1}]}},
        {"deep": {"component_geometry_hash": "fake"}},
        {"deep": {"reference_line": "LINESTRING(0 0, 1 1)"}},
        {"deep": {"reference_line_snapshot": "LINESTRING(0 0, 1 1)"}},
        {"deep": {"geometry": "LINESTRING(0 0, 1 1)"}},
        {"deep": {"line_hash": "fake"}},
        {"deep": {"coordinates": [[0, 0], [1, 1]]}},
        {"deep": {"polyline": "fake"}},
        {"deep": {"ordering": [1, 2]}},
        {"deep": {"roles": ["supporting"]}},
    ],
)
def test_route_segment_metadata_cannot_hide_composition_truth(
    db, route_segment_writer_tables, metadata_json
):
    with pytest.raises(RouteSegmentWriterError, match="metadata_json"):
        add_route_custom_geometry(
            db,
            route_book_id=1,
            route_version_id=1,
            seq=1,
            component_geometry="LINESTRING(1 1, 2 2)",
            metadata_json=metadata_json,
            accepted_judgment_run_id=7,
        )


def test_route_segment_writer_does_not_commit_or_mutate_forbidden_surfaces(
    db, route_segment_writer_tables, monkeypatch
):
    def fail_commit():
        raise AssertionError("route segment writer must not commit")

    monkeypatch.setattr(db, "commit", fail_commit)
    route_book_before = _simple_table_snapshot(db, "route_books")
    route_version_before = _simple_table_snapshot(db, "route_versions")
    segment_before = _simple_table_snapshot(db, "segments")
    effort_before = _simple_table_snapshot(db, "segment_efforts")
    guide_before = _route_guides_snapshot(db)
    content_routes_before = _content_routes_snapshot()

    add_route_segment_clip(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=1,
        segment_id=1,
        component_geometry="LINESTRING(0 0, 1 1)",
        direction="forward",
        accepted_judgment_run_id=1,
    )
    add_route_custom_geometry(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=2,
        component_geometry="LINESTRING(1 1, 2 2)",
        accepted_judgment_run_id=7,
    )

    assert _simple_table_snapshot(db, "route_books") == route_book_before
    assert _simple_table_snapshot(db, "route_versions") == route_version_before
    assert _simple_table_snapshot(db, "segments") == segment_before
    assert _simple_table_snapshot(db, "segment_efforts") == effort_before
    assert _route_guides_snapshot(db) == guide_before
    assert _content_routes_snapshot() == content_routes_before
    _assert_forbidden_tables_empty(db)
    _assert_candidate_tables_absent(db)


def _create_route_segment_writer_tables(db) -> None:
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
    _create_route_segments_table(db)
    for table_name in FORBIDDEN_EMPTY_TABLES:
        db.execute(text(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY AUTOINCREMENT)"))


def _create_route_segments_table(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE route_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_book_id INTEGER NOT NULL,
                route_version_id INTEGER NOT NULL,
                route_line_hash TEXT NOT NULL,
                seq INTEGER NOT NULL,
                component_type TEXT NOT NULL,
                segment_id INTEGER,
                segment_geometry_hash TEXT,
                component_geometry TEXT NOT NULL,
                component_geometry_hash TEXT NOT NULL,
                direction TEXT,
                start_fraction REAL,
                end_fraction REAL,
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
                CHECK (seq >= 1),
                CHECK (component_type IN ('segment_clip', 'custom_geometry')),
                CHECK (membership_status IN ('active', 'deprecated', 'superseded')),
                CHECK (source_kind IN ('manual_curated', 'legacy_import')),
                CHECK (accepted_judgment_run_type = 'human_review'),
                CHECK (source_kind <> 'legacy_import' OR source_ref IS NOT NULL OR reason_summary IS NOT NULL),
                CHECK (display_priority IS NULL OR (display_priority >= 0 AND display_priority <= 100)),
                CHECK (
                    (
                        component_type = 'segment_clip'
                        AND segment_id IS NOT NULL
                        AND segment_geometry_hash IS NOT NULL
                        AND component_geometry IS NOT NULL
                        AND component_geometry_hash IS NOT NULL
                        AND direction IN ('forward', 'reverse')
                    )
                    OR
                    (
                        component_type = 'custom_geometry'
                        AND segment_id IS NULL
                        AND segment_geometry_hash IS NULL
                        AND component_geometry IS NOT NULL
                        AND component_geometry_hash IS NOT NULL
                        AND direction IS NULL
                    )
                ),
                CHECK (
                    (start_fraction IS NULL AND end_fraction IS NULL)
                    OR (
                        component_type = 'segment_clip'
                        AND start_fraction IS NOT NULL
                        AND end_fraction IS NOT NULL
                        AND start_fraction >= 0
                        AND end_fraction <= 1
                        AND start_fraction < end_fraction
                    )
                ),
                CHECK (
                    component_geometry LIKE 'LINESTRING%'
                    OR component_geometry LIKE 'MULTILINESTRING%'
                    OR component_geometry LIKE 'SRID=4326;LINESTRING%'
                    OR component_geometry LIKE 'SRID=4326;MULTILINESTRING%'
                ),
                FOREIGN KEY(route_book_id) REFERENCES route_books(id),
                FOREIGN KEY(route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id),
                FOREIGN KEY(segment_id) REFERENCES route_cognition_segments(segment_id),
                FOREIGN KEY(segment_id, segment_geometry_hash)
                    REFERENCES route_cognition_segments(segment_id, geometry_hash),
                FOREIGN KEY(accepted_judgment_run_id, accepted_judgment_run_type)
                    REFERENCES judgment_runs(id, run_type)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_route_segments_active_seq
            ON route_segments(route_book_id, route_version_id, seq)
            WHERE membership_status = 'active'
            """
        )
    )


def _seed_route_segment_writer_base(db) -> None:
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


def _geometry_hash(component_geometry: str) -> str:
    return hash_segment_geometry_wkt(component_geometry)


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


def _drop_route_segment_writer_tables(db) -> None:
    for table_name in (
        *FORBIDDEN_EMPTY_TABLES,
        "route_segments",
        "route_guides",
        "segment_efforts",
        "route_cognition_segments",
        "segments",
        "route_versions",
        "route_books",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
