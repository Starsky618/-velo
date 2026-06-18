"""概念候选 Step 3.5 种子演习——在测试库里试连路线、赛段、专题和概念，不转正。"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.route_cognition.services.concept_candidate_writer import (
    ConceptCandidateWriterError,
    propose_collection_concept_candidate,
    propose_route_concept_candidate,
    propose_segment_concept_candidate,
)
from app.route_cognition.services.concept_writer import create_concept_node
from app.route_cognition.services.route_collection_writer import create_route_collection


CONCEPT_SEEDS = (
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
        "name": "碎石风险",
        "slug": "gravel-risk",
        "node_type": "safety_risk",
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
)

COLLECTION_SEEDS = (
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
    "route_concept_links",
    "segment_concept_links",
    "collection_concept_links",
    "evidence_items",
    "route_segments",
    "collection_routes",
    "collection_segments",
    "segment_submissions",
)


@pytest.fixture()
def concept_candidate_seed_dry_run_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_seed_dry_run_tables(db)
    _create_seed_dry_run_tables(db)
    _seed_route_segment_and_judgment_rows(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_seed_dry_run_tables(db)


def test_taiyuan_xishan_concept_candidate_seed_creates_only_proposed_candidates(
    db, concept_candidate_seed_dry_run_tables, monkeypatch
):
    def fail_commit():
        raise AssertionError("candidate seed dry-run must not commit")

    monkeypatch.setattr(db, "commit", fail_commit)

    concept_ids = _create_seed_concepts(db)
    collection_ids = _create_seed_collections(db)
    route_book_before = _simple_table_snapshot(db, "route_books")
    route_version_before = _simple_table_snapshot(db, "route_versions")
    segment_before = _simple_table_snapshot(db, "segments")
    effort_before = _simple_table_snapshot(db, "segment_efforts")
    guide_before = _route_guides_snapshot(db)
    content_routes_before = _content_routes_snapshot()

    route_candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=concept_ids["beginner-aerobic"],
        relation_type="suitable_for",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )
    climb_candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=concept_ids["climbing-training"],
        relation_type="suitable_for",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
    )
    risk_candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=concept_ids["gravel-risk"],
        relation_type="has_risk",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
    )
    training_collection_candidate = propose_collection_concept_candidate(
        db,
        collection_id=collection_ids["xishan-training-system"],
        concept_node_id=concept_ids["climbing-training"],
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=3,
    )
    race_collection_candidate = propose_collection_concept_candidate(
        db,
        collection_id=collection_ids["tour-of-taiyuan-route-family"],
        concept_node_id=concept_ids["tour-of-taiyuan"],
        relation_type="part_of_event",
        proposer_kind="human",
        created_by_judgment_run_id=4,
    )

    route_line_hash = db.execute(
        text("SELECT line_hash FROM route_versions WHERE id = 1")
    ).scalar_one()
    segment_geometry_hash = db.execute(
        text("SELECT geometry_hash FROM route_cognition_segments WHERE segment_id = 1")
    ).scalar_one()

    candidate_summary = [
        {
            "source_object": "环西山正骑",
            "relation_type": route_candidate.relation_type,
            "concept": "新手有氧",
            "candidate_status": route_candidate.candidate_status,
            "accepted_by_judgment_run_id": route_candidate.accepted_by_judgment_run_id,
        },
        {
            "source_object": "横岭",
            "relation_type": climb_candidate.relation_type,
            "concept": "爬坡训练",
            "candidate_status": climb_candidate.candidate_status,
            "accepted_by_judgment_run_id": climb_candidate.accepted_by_judgment_run_id,
        },
        {
            "source_object": "横岭",
            "relation_type": risk_candidate.relation_type,
            "concept": "碎石风险",
            "candidate_status": risk_candidate.candidate_status,
            "accepted_by_judgment_run_id": risk_candidate.accepted_by_judgment_run_id,
        },
        {
            "source_object": "西山训练体系",
            "relation_type": training_collection_candidate.relation_type,
            "concept": "爬坡训练",
            "candidate_status": training_collection_candidate.candidate_status,
            "accepted_by_judgment_run_id": training_collection_candidate.accepted_by_judgment_run_id,
        },
        {
            "source_object": "环太原赛路线族",
            "relation_type": race_collection_candidate.relation_type,
            "concept": "环太原赛",
            "candidate_status": race_collection_candidate.candidate_status,
            "accepted_by_judgment_run_id": race_collection_candidate.accepted_by_judgment_run_id,
        },
    ]

    assert candidate_summary == [
        {
            "source_object": "环西山正骑",
            "relation_type": "suitable_for",
            "concept": "新手有氧",
            "candidate_status": "proposed",
            "accepted_by_judgment_run_id": None,
        },
        {
            "source_object": "横岭",
            "relation_type": "suitable_for",
            "concept": "爬坡训练",
            "candidate_status": "proposed",
            "accepted_by_judgment_run_id": None,
        },
        {
            "source_object": "横岭",
            "relation_type": "has_risk",
            "concept": "碎石风险",
            "candidate_status": "proposed",
            "accepted_by_judgment_run_id": None,
        },
        {
            "source_object": "西山训练体系",
            "relation_type": "training_theme",
            "concept": "爬坡训练",
            "candidate_status": "proposed",
            "accepted_by_judgment_run_id": None,
        },
        {
            "source_object": "环太原赛路线族",
            "relation_type": "part_of_event",
            "concept": "环太原赛",
            "candidate_status": "proposed",
            "accepted_by_judgment_run_id": None,
        },
    ]
    assert route_candidate.route_line_hash == route_line_hash
    assert climb_candidate.segment_geometry_hash == segment_geometry_hash
    assert risk_candidate.segment_geometry_hash == segment_geometry_hash
    assert [
        candidate.latest_judgment_run_id
        for candidate in (
            route_candidate,
            climb_candidate,
            risk_candidate,
            training_collection_candidate,
            race_collection_candidate,
        )
    ] == [1, 2, 2, 3, 4]
    assert [
        candidate.created_by_judgment_run_id
        for candidate in (
            route_candidate,
            climb_candidate,
            risk_candidate,
            training_collection_candidate,
            race_collection_candidate,
        )
    ] == [1, 2, 2, 3, 4]

    assert db.execute(text("SELECT count(*) FROM route_concept_candidates")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM segment_concept_candidates")).scalar_one() == 2
    assert db.execute(text("SELECT count(*) FROM collection_concept_candidates")).scalar_one() == 2
    for table_name in FORBIDDEN_EMPTY_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0
    assert _simple_table_snapshot(db, "route_books") == route_book_before
    assert _simple_table_snapshot(db, "route_versions") == route_version_before
    assert _simple_table_snapshot(db, "segments") == segment_before
    assert _simple_table_snapshot(db, "segment_efforts") == effort_before
    assert _route_guides_snapshot(db) == guide_before
    assert _content_routes_snapshot() == content_routes_before


@pytest.mark.parametrize(
    ("metadata_json", "blocked_key"),
    [
        ({"route_book_id": 1}, "route_book_id"),
        ({"nested": {"segment_id": 1}}, "segment_id"),
        ({"items": [{"collection_id": 1}]}, "collection_id"),
        ({"relationType": "has_risk"}, "relationType"),
        ({"routeIds": [1]}, "routeIds"),
        ({"formalLinkIds": [1]}, "formalLinkIds"),
    ],
)
def test_candidate_seed_metadata_guard_rejects_relationship_truth(
    db, concept_candidate_seed_dry_run_tables, metadata_json, blocked_key
):
    concept_ids = _create_seed_concepts(db)

    with pytest.raises(ConceptCandidateWriterError, match=blocked_key):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=concept_ids["beginner-aerobic"],
            relation_type="suitable_for",
            proposer_kind="agent",
            created_by_judgment_run_id=1,
            metadata_json=metadata_json,
        )


def test_candidate_seed_route_version_book_mismatch_fails(db, concept_candidate_seed_dry_run_tables):
    concept_ids = _create_seed_concepts(db)

    with pytest.raises(ConceptCandidateWriterError, match="route_version"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=2,
            concept_node_id=concept_ids["beginner-aerobic"],
            relation_type="suitable_for",
            proposer_kind="agent",
            created_by_judgment_run_id=3,
        )


def test_candidate_seed_raw_segment_without_cognition_whitelist_fails(
    db, concept_candidate_seed_dry_run_tables
):
    concept_ids = _create_seed_concepts(db)

    with pytest.raises(ConceptCandidateWriterError, match="route_cognition_segments"):
        propose_segment_concept_candidate(
            db,
            segment_id=2,
            concept_node_id=concept_ids["climbing-training"],
            relation_type="suitable_for",
            proposer_kind="algorithm",
            created_by_judgment_run_id=3,
        )


@pytest.mark.parametrize("judgment_run_id", [5, 6, 7])
def test_candidate_seed_failed_running_or_cancelled_judgment_fails(
    db, concept_candidate_seed_dry_run_tables, judgment_run_id
):
    concept_ids = _create_seed_concepts(db)

    with pytest.raises(ConceptCandidateWriterError, match="succeeded"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=concept_ids["beginner-aerobic"],
            relation_type="suitable_for",
            proposer_kind="agent",
            created_by_judgment_run_id=judgment_run_id,
        )


def test_candidate_seed_writer_cannot_create_accepted_candidate(db, concept_candidate_seed_dry_run_tables):
    concept_ids = _create_seed_concepts(db)

    with pytest.raises(ConceptCandidateWriterError, match="candidate_status"):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=concept_ids["beginner-aerobic"],
            relation_type="suitable_for",
            proposer_kind="agent",
            candidate_status="accepted",
            created_by_judgment_run_id=1,
        )


def test_candidate_seed_duplicate_open_candidate_is_blocked_by_partial_unique(
    db, concept_candidate_seed_dry_run_tables
):
    concept_ids = _create_seed_concepts(db)
    propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=concept_ids["beginner-aerobic"],
        relation_type="suitable_for",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )

    with pytest.raises(IntegrityError):
        propose_route_concept_candidate(
            db,
            route_book_id=1,
            route_version_id=1,
            concept_node_id=concept_ids["beginner-aerobic"],
            relation_type="suitable_for",
            proposer_kind="agent",
            candidate_status="needs_review",
            created_by_judgment_run_id=3,
        )


def _create_seed_concepts(db) -> dict[str, int]:
    concept_ids: dict[str, int] = {}
    for concept in CONCEPT_SEEDS:
        node = create_concept_node(
            db,
            name=concept["name"],
            slug=concept["slug"],
            node_type=concept["node_type"],
            scope_type=concept["scope_type"],
            scope_value=concept["scope_value"],
            city=concept.get("city"),
            region=concept.get("region"),
            summary=f"{concept['name']} candidate dry-run",
        )
        concept_ids[concept["slug"]] = node.id
    return concept_ids


def _create_seed_collections(db) -> dict[str, int]:
    collection_ids: dict[str, int] = {}
    for collection in COLLECTION_SEEDS:
        route_collection = create_route_collection(
            db,
            name=collection["name"],
            slug=collection["slug"],
            collection_type=collection["collection_type"],
            city=collection["city"],
        )
        collection_ids[collection["slug"]] = route_collection.id
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


def _route_guides_snapshot(db) -> list[tuple[int, str, str]]:
    return [
        (row.id, row.name, row.content_md)
        for row in db.execute(
            text("SELECT id, name, content_md FROM route_guides ORDER BY id")
        ).all()
    ]


def _simple_table_snapshot(db, table_name: str) -> list[tuple]:
    return [tuple(row) for row in db.execute(text(f"SELECT * FROM {table_name} ORDER BY id")).all()]


def _seed_route_segment_and_judgment_rows(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (
                id, run_type, status, confidence_state, route_book_id, route_version_id,
                segment_id, confidence
            )
            VALUES
                (1, 'semantic_agent', 'succeeded', 'proposed', 1, 1, NULL, 0.71),
                (2, 'spatial_algorithm', 'succeeded', 'proposed', NULL, NULL, 1, 0.78),
                (3, 'semantic_agent', 'succeeded', 'stable', NULL, NULL, NULL, 0.82),
                (4, 'human_review', 'succeeded', 'stable', NULL, NULL, NULL, 0.91),
                (5, 'semantic_agent', 'failed', 'stale', 1, 1, NULL, 0.20),
                (6, 'spatial_algorithm', 'running', 'raw', NULL, NULL, 1, 0.30),
                (7, 'human_review', 'cancelled', 'inconclusive', NULL, NULL, NULL, 0.40)
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_books (
                id, name, distance, reference_line, source, city, visibility, publish_status,
                line_hash
            )
            VALUES
                (
                    1, '环西山正骑', 42000.0, 'LINESTRING(0 0, 1 1)',
                    'manual_drawn', 'taiyuan', 'private', 'draft', 'route-book-hash-a'
                ),
                (
                    2, '备用错配路线', 12000.0, 'LINESTRING(2 2, 3 3)',
                    'manual_drawn', 'taiyuan', 'private', 'draft', 'route-book-hash-b'
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
            VALUES
                (
                    1, 1, 1, 'current', 'route_book_reference', 'ready',
                    'LINESTRING(0 0, 1 1)', 'route-version-line-hash-a', 42000.0
                ),
                (
                    2, 2, 1, 'current', 'route_book_reference', 'ready',
                    'LINESTRING(2 2, 3 3)', 'route-version-line-hash-b', 12000.0
                )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO segments (id, name, reference_line)
            VALUES
                (1, '横岭', 'LINESTRING(0 0, 1 1)'),
                (2, '裸赛段', 'LINESTRING(3 3, 4 4)')
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
    db.execute(
        text(
            """
            INSERT INTO route_guides (id, name, content_md)
            VALUES (1, 'Guide Sentinel', 'original guide content')
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
                confidence_state TEXT NOT NULL,
                route_book_id INTEGER,
                route_version_id INTEGER,
                segment_id INTEGER,
                confidence REAL,
                result_summary_json TEXT,
                missing_data_json TEXT,
                contradiction_json TEXT
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
            CREATE TABLE route_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                distance REAL NOT NULL,
                reference_line TEXT NOT NULL,
                source TEXT NOT NULL,
                city TEXT NOT NULL DEFAULT 'unknown',
                visibility TEXT NOT NULL DEFAULT 'private',
                publish_status TEXT NOT NULL DEFAULT 'draft',
                line_hash TEXT,
                current_version_id INTEGER
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
                status TEXT NOT NULL DEFAULT 'current',
                geometry_source TEXT NOT NULL,
                navigation_status TEXT NOT NULL DEFAULT 'ready',
                reference_line_snapshot TEXT NOT NULL,
                line_hash TEXT NOT NULL,
                distance REAL NOT NULL
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
    db.execute(text("CREATE TABLE route_concept_links (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE segment_concept_links (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_concept_links (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE evidence_items (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE route_segments (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_routes (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_segments (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
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


def _drop_seed_dry_run_tables(db) -> None:
    for table_name in (
        "segment_submissions",
        "collection_segments",
        "collection_routes",
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
        "route_versions",
        "route_books",
        "route_collections",
        "concept_nodes",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
