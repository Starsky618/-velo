"""First Visible Slice 测试——像总彩排一样，把路线认知的最小内部演示串起来。

注意事项：这里只在测试数据库里搭临时舞台，不写真实库、不改内容文件，也不新增任何产品入口。
数据流：测试先用现有 writer 创建概念、专题、候选、正式关系、专题成员和路线组件，
最后从内部表读出一份 snapshot，证明这些零件能被安全拼成一个可看的演示结构。
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from app.route_cognition.services.collection_membership_writer import (
    add_collection_route,
    add_collection_segment,
)
from app.route_cognition.services.concept_candidate_writer import (
    propose_collection_concept_candidate,
    propose_route_concept_candidate,
    propose_segment_concept_candidate,
)
from app.route_cognition.services.concept_formal_link_writer import (
    promote_collection_concept_candidate,
    promote_route_concept_candidate,
    promote_segment_concept_candidate,
)
from app.route_cognition.services.demo_snapshot import build_first_visible_slice_demo_snapshot
from app.route_cognition.services.concept_writer import create_concept_node
from app.route_cognition.services.route_collection_writer import create_route_collection
from app.route_cognition.services.route_segment_writer import (
    add_route_custom_geometry,
    add_route_segment_clip,
)
from tests.test_route_cognition_collection_membership_seed_dry_run import (
    _create_collection_routes_table,
    _create_collection_segments_table,
)
from tests.test_route_cognition_concept_formal_link_writer import (
    _create_collection_concept_candidate_table,
    _create_collection_concept_link_table,
    _create_route_concept_candidate_table,
    _create_route_concept_link_table,
    _create_segment_concept_candidate_table,
    _create_segment_concept_link_table,
)
from tests.test_route_cognition_route_segment_writer import _create_route_segments_table


EXPECTED_SNAPSHOT = """西山训练体系
- route: 环西山正骑
- segment: 横岭
- route concepts: 新手有氧
- segment concepts: 爬坡训练 / 碎石风险
- collection concepts: 爬坡训练
- route composition:
  1. custom_geometry
  2. 横岭 segment_clip
  3. custom_geometry

环太原赛路线族
- collection concepts: 环太原赛"""


@dataclass(frozen=True)
class _ConceptSeed:
    key: str
    name: str
    slug: str
    node_type: str
    scope_type: str
    scope_value: str
    city: str | None = None
    region: str | None = None


@dataclass(frozen=True)
class _CollectionSeed:
    key: str
    name: str
    slug: str
    collection_type: str
    city: str


CONCEPT_SEEDS = (
    _ConceptSeed(
        key="beginner_aerobic",
        name="新手有氧",
        slug="beginner-aerobic",
        node_type="training_theme",
        scope_type="city",
        scope_value="taiyuan",
        city="taiyuan",
    ),
    _ConceptSeed(
        key="climbing_training",
        name="爬坡训练",
        slug="climbing-training",
        node_type="training_theme",
        scope_type="region",
        scope_value="taiyuan-xishan",
        city="taiyuan",
        region="taiyuan-xishan",
    ),
    _ConceptSeed(
        key="gravel_risk",
        name="碎石风险",
        slug="gravel-risk",
        node_type="safety_risk",
        scope_type="region",
        scope_value="taiyuan-xishan",
        city="taiyuan",
        region="taiyuan-xishan",
    ),
    _ConceptSeed(
        key="tour_of_taiyuan",
        name="环太原赛",
        slug="tour-of-taiyuan",
        node_type="event",
        scope_type="city",
        scope_value="taiyuan",
        city="taiyuan",
    ),
)


COLLECTION_SEEDS = (
    _CollectionSeed(
        key="xishan_training_system",
        name="西山训练体系",
        slug="xishan-training-system",
        collection_type="area_system",
        city="taiyuan",
    ),
    _CollectionSeed(
        key="tour_of_taiyuan_route_family",
        name="环太原赛路线族",
        slug="tour-of-taiyuan-route-family",
        collection_type="race_route_family",
        city="taiyuan",
    ),
)


FORBIDDEN_EMPTY_TABLES = (
    "evidence_items",
    "route_segment_candidates",
    "collection_route_candidates",
    "collection_segment_candidates",
    "route_collection_candidates",
    "segment_collection_candidates",
    "segment_submissions",
)


def test_first_visible_slice_dry_run_creates_readable_internal_snapshot(db, monkeypatch):
    _drop_first_visible_slice_tables(db)
    _clear_existing_authority_tables(db)
    try:
        _create_first_visible_slice_tables(db)
        _seed_authority_and_judgment_rows(db)
        monkeypatch.setattr(db, "commit", _fail_if_writer_commits)

        authority_before = _authority_snapshot(db)
        segment_efforts_before = _table_snapshot(db, "segment_efforts")
        content_routes_before = _content_routes_snapshot()

        concepts = _create_concepts(db)
        collections = _create_collections(db)
        _create_and_promote_concept_links(db, concepts=concepts, collections=collections)
        _create_collection_memberships(db, collections=collections)
        _create_route_composition(db)

        snapshot = build_first_visible_slice_demo_snapshot(
            db,
            xishan_collection_slug=collections["xishan_training_system"].slug,
            event_collection_slug=collections["tour_of_taiyuan_route_family"].slug,
        )

        assert snapshot == EXPECTED_SNAPSHOT
        assert _table_count(db, "concept_nodes") == 4
        assert _table_count(db, "route_collections") == 2
        assert _table_count(db, "route_concept_candidates") == 1
        assert _table_count(db, "segment_concept_candidates") == 2
        assert _table_count(db, "collection_concept_candidates") == 2
        assert _table_count(db, "route_concept_links") == 1
        assert _table_count(db, "segment_concept_links") == 2
        assert _table_count(db, "collection_concept_links") == 2
        assert _table_count(db, "collection_routes") == 1
        assert _table_count(db, "collection_segments") == 1
        assert _table_count(db, "route_segments") == 3

        route_segments = db.execute(
            text(
                """
                SELECT seq, component_type, segment_id, segment_geometry_hash,
                       component_geometry_hash, route_line_hash, membership_status
                FROM route_segments
                ORDER BY seq
                """
            )
        ).all()
        assert [(row.seq, row.component_type) for row in route_segments] == [
            (1, "custom_geometry"),
            (2, "segment_clip"),
            (3, "custom_geometry"),
        ]
        assert route_segments[1].segment_id == 1
        assert route_segments[1].segment_geometry_hash == "segment-geometry-hash-hengling"
        assert all(row.component_geometry_hash for row in route_segments)
        assert all(row.route_line_hash == "route-version-line-hash-a" for row in route_segments)
        assert all(row.membership_status == "active" for row in route_segments)

        collection_route = db.execute(
            text(
                """
                SELECT reviewed_route_line_hash, source_kind, membership_status
                FROM collection_routes
                """
            )
        ).one()
        assert collection_route.reviewed_route_line_hash == "route-version-line-hash-a"
        assert collection_route.source_kind == "manual_curated"
        assert collection_route.membership_status == "active"

        collection_segment = db.execute(
            text(
                """
                SELECT segment_geometry_hash, source_kind, membership_status
                FROM collection_segments
                """
            )
        ).one()
        assert collection_segment.segment_geometry_hash == "segment-geometry-hash-hengling"
        assert collection_segment.source_kind == "manual_curated"
        assert collection_segment.membership_status == "active"

        for table_name in FORBIDDEN_EMPTY_TABLES:
            assert _table_count(db, table_name) == 0
        assert _authority_snapshot(db) == authority_before
        assert _table_snapshot(db, "segment_efforts") == segment_efforts_before
        assert _content_routes_snapshot() == content_routes_before
    finally:
        _drop_first_visible_slice_tables(db)


def _create_concepts(db) -> dict[str, object]:
    created = {}
    for seed in CONCEPT_SEEDS:
        created[seed.key] = create_concept_node(
            db,
            name=seed.name,
            slug=seed.slug,
            node_type=seed.node_type,
            scope_type=seed.scope_type,
            scope_value=seed.scope_value,
            city=seed.city,
            region=seed.region,
            visibility="private",
            publish_status="draft",
            source="manual",
        )
    return created


def _create_collections(db) -> dict[str, object]:
    created = {}
    for seed in COLLECTION_SEEDS:
        created[seed.key] = create_route_collection(
            db,
            name=seed.name,
            slug=seed.slug,
            collection_type=seed.collection_type,
            city=seed.city,
            visibility="private",
            publish_status="draft",
            source="manual",
        )
    return created


def _create_and_promote_concept_links(db, *, concepts: dict[str, object], collections: dict[str, object]) -> None:
    route_candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=concepts["beginner_aerobic"].id,
        relation_type="suitable_for",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
        latest_judgment_run_id=1,
        reason_summary="环西山正骑适合低强度长时间骑行。",
    )
    promote_route_concept_candidate(
        db,
        candidate_id=route_candidate.id,
        accepted_judgment_run_id=10,
    )

    climbing_candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=concepts["climbing_training"].id,
        relation_type="suitable_for",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
        latest_judgment_run_id=2,
        reason_summary="横岭可作为爬坡训练段。",
    )
    promote_segment_concept_candidate(
        db,
        candidate_id=climbing_candidate.id,
        accepted_judgment_run_id=11,
    )

    gravel_candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=concepts["gravel_risk"].id,
        relation_type="has_risk",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
        latest_judgment_run_id=2,
        reason_summary="横岭局部路面有碎石风险。",
    )
    promote_segment_concept_candidate(
        db,
        candidate_id=gravel_candidate.id,
        accepted_judgment_run_id=11,
    )

    xishan_collection_candidate = propose_collection_concept_candidate(
        db,
        collection_id=collections["xishan_training_system"].id,
        concept_node_id=concepts["climbing_training"].id,
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=3,
        latest_judgment_run_id=3,
        reason_summary="西山训练体系的核心主题是爬坡训练。",
    )
    promote_collection_concept_candidate(
        db,
        candidate_id=xishan_collection_candidate.id,
        accepted_judgment_run_id=12,
    )

    event_collection_candidate = propose_collection_concept_candidate(
        db,
        collection_id=collections["tour_of_taiyuan_route_family"].id,
        concept_node_id=concepts["tour_of_taiyuan"].id,
        relation_type="part_of_event",
        proposer_kind="agent",
        created_by_judgment_run_id=3,
        latest_judgment_run_id=3,
        reason_summary="环太原赛路线族属于环太原赛事件语境。",
    )
    promote_collection_concept_candidate(
        db,
        candidate_id=event_collection_candidate.id,
        accepted_judgment_run_id=12,
    )


def _create_collection_memberships(db, *, collections: dict[str, object]) -> None:
    add_collection_route(
        db,
        collection_id=collections["xishan_training_system"].id,
        route_book_id=1,
        reviewed_route_version_id=1,
        role="primary",
        seq=1,
        membership_status="active",
        source_kind="manual_curated",
        accepted_judgment_run_id=10,
        reason_summary="环西山正骑是西山训练体系的主线。",
    )
    add_collection_segment(
        db,
        collection_id=collections["xishan_training_system"].id,
        segment_id=1,
        role="core",
        seq=2,
        membership_status="active",
        source_kind="manual_curated",
        accepted_judgment_run_id=11,
        reason_summary="横岭是西山训练体系里的核心爬坡段。",
    )


def _create_route_composition(db) -> None:
    add_route_custom_geometry(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=1,
        component_geometry="LINESTRING(112.40 37.75, 112.42 37.76)",
        membership_status="active",
        source_kind="manual_curated",
        accepted_judgment_run_id=10,
        reason_summary="进山连接段。",
    )
    add_route_segment_clip(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=2,
        segment_id=1,
        component_geometry="LINESTRING(112.42 37.76, 112.45 37.78)",
        direction="forward",
        membership_status="active",
        source_kind="manual_curated",
        accepted_judgment_run_id=13,
        reason_summary="横岭 segment_clip。",
    )
    add_route_custom_geometry(
        db,
        route_book_id=1,
        route_version_id=1,
        seq=3,
        component_geometry="LINESTRING(112.45 37.78, 112.47 37.79)",
        membership_status="active",
        source_kind="manual_curated",
        accepted_judgment_run_id=10,
        reason_summary="出山连接段。",
    )


def _create_first_visible_slice_tables(db) -> None:
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
                UNIQUE(id, run_type)
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
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
            CREATE TABLE route_cognition_segments (
                segment_id INTEGER PRIMARY KEY,
                geometry_hash TEXT NOT NULL,
                eligibility_status TEXT NOT NULL DEFAULT 'active',
                UNIQUE(segment_id, geometry_hash)
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
    _create_collection_routes_table(db)
    _create_collection_segments_table(db)
    _create_route_segments_table(db)
    for table_name in FORBIDDEN_EMPTY_TABLES:
        db.execute(text(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY AUTOINCREMENT)"))


def _seed_authority_and_judgment_rows(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (
                id, run_type, status, confidence_state, route_book_id, route_version_id,
                segment_id, confidence, result_summary_json, missing_data_json, contradiction_json
            )
            VALUES
                (1, 'semantic_agent', 'succeeded', 'proposed', 1, 1, NULL, 0.68,
                    '{"summary":"route candidate proposed"}', '{}', '{}'),
                (2, 'spatial_algorithm', 'succeeded', 'stable', NULL, NULL, 1, 0.74,
                    '{"summary":"segment candidate proposed"}', '{}', '{}'),
                (3, 'semantic_agent', 'succeeded', 'stable', NULL, NULL, NULL, 0.70,
                    '{"summary":"collection candidate proposed"}', '{}', '{}'),
                (10, 'human_review', 'succeeded', 'human_accepted', 1, 1, NULL, 0.93,
                    '{"summary":"route accepted"}', '{}', '{}'),
                (11, 'human_review', 'succeeded', 'stable', NULL, NULL, 1, 0.91,
                    '{"summary":"segment accepted"}', '{}', '{}'),
                (12, 'human_review', 'succeeded', 'human_accepted', NULL, NULL, NULL, 0.90,
                    '{"summary":"collection accepted"}', '{}', '{}'),
                (13, 'human_review', 'succeeded', 'human_accepted', 1, 1, 1, 0.92,
                    '{"summary":"route segment accepted"}', '{}', '{}')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_books (
                id, name, distance, reference_line, source, city, visibility, publish_status,
                line_hash, current_version_id
            )
            VALUES (
                1, '环西山正骑', 42000.0, 'LINESTRING(112.40 37.75, 112.47 37.79)',
                'manual_drawn', 'taiyuan', 'private', 'draft', 'route-book-current-hash-a', 1
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_versions (
                id, route_book_id, version_no, status, geometry_source, navigation_status,
                reference_line_snapshot, line_hash, distance
            )
            VALUES (
                1, 1, 1, 'current', 'manual_drawn', 'ready',
                'LINESTRING(112.40 37.75, 112.47 37.79)', 'route-version-line-hash-a', 42000.0
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO segments (
                id, name, distance, start_lat, start_lon, end_lat, end_lon, reference_line, city
            )
            VALUES (
                1, '横岭', 2800.0, 37.76, 112.42, 37.78, 112.45,
                'LINESTRING(112.42 37.76, 112.45 37.78)', 'taiyuan'
            )
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
    db.execute(
        text(
            """
            INSERT INTO segment_efforts (
                id, segment_id, activity_id, user_id, elapsed_time, start_index, end_index
            )
            VALUES (1, 1, 1, 1, 600, 0, 10)
            """
        )
    )


def _authority_snapshot(db) -> dict[str, list[tuple]]:
    return {
        "route_books": _table_snapshot(db, "route_books"),
        "route_versions": _table_snapshot(db, "route_versions"),
        "segments": _table_snapshot(db, "segments"),
    }


def _table_snapshot(db, table_name: str) -> list[tuple]:
    return [tuple(row) for row in db.execute(text(f"SELECT * FROM {table_name} ORDER BY id")).all()]


def _table_count(db, table_name: str) -> int:
    return db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()


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


def _fail_if_writer_commits() -> None:
    raise AssertionError("writer must not call db.commit()")


def _clear_existing_authority_tables(db) -> None:
    for table_name in ("segment_efforts", "route_versions", "route_books", "segments"):
        db.execute(text(f"DELETE FROM {table_name}"))


def _drop_first_visible_slice_tables(db) -> None:
    for table_name in (
        *FORBIDDEN_EMPTY_TABLES,
        "route_segments",
        "collection_segments",
        "collection_routes",
        "collection_concept_links",
        "segment_concept_links",
        "route_concept_links",
        "collection_concept_candidates",
        "segment_concept_candidates",
        "route_concept_candidates",
        "route_cognition_segments",
        "route_collections",
        "concept_nodes",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
