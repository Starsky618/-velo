"""概念正式关系 Step 4.5 种子演习——在测试库里走完候选到正式关系，不碰真实内容。"""

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
from app.route_cognition.services.concept_formal_link_writer import (
    ConceptFormalLinkWriterError,
    promote_collection_concept_candidate,
    promote_route_concept_candidate,
    promote_segment_concept_candidate,
)
from app.route_cognition.services.concept_writer import create_concept_node
from app.route_cognition.services.route_collection_writer import create_route_collection
from tests.test_route_cognition_concept_formal_link_writer import (
    _create_collection_concept_candidate_table,
    _create_collection_concept_link_table,
    _create_route_concept_candidate_table,
    _create_route_concept_link_table,
    _create_segment_concept_candidate_table,
    _create_segment_concept_link_table,
)


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
    "evidence_items",
    "route_segments",
    "collection_routes",
    "collection_segments",
    "segment_submissions",
)


@pytest.fixture()
def concept_formal_link_seed_dry_run_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_seed_dry_run_tables(db)
    _create_seed_dry_run_tables(db)
    _seed_route_segment_guide_and_judgment_rows(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_seed_dry_run_tables(db)


def test_taiyuan_xishan_seed_promotes_candidates_into_only_candidate_accepted_formal_links(
    db, concept_formal_link_seed_dry_run_tables, monkeypatch
):
    def fail_commit():
        raise AssertionError("formal link seed dry-run must not commit")

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
    route_link = promote_route_concept_candidate(
        db,
        candidate_id=route_candidate.id,
        accepted_judgment_run_id=10,
    )
    climb_candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=concept_ids["climbing-training"],
        relation_type="suitable_for",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
    )
    climb_link = promote_segment_concept_candidate(
        db,
        candidate_id=climb_candidate.id,
        accepted_judgment_run_id=11,
    )
    risk_candidate = propose_segment_concept_candidate(
        db,
        segment_id=1,
        concept_node_id=concept_ids["gravel-risk"],
        relation_type="has_risk",
        proposer_kind="algorithm",
        created_by_judgment_run_id=2,
    )
    risk_link = promote_segment_concept_candidate(
        db,
        candidate_id=risk_candidate.id,
        accepted_judgment_run_id=11,
    )
    training_collection_candidate = propose_collection_concept_candidate(
        db,
        collection_id=collection_ids["xishan-training-system"],
        concept_node_id=concept_ids["climbing-training"],
        relation_type="training_theme",
        proposer_kind="agent",
        created_by_judgment_run_id=3,
    )
    training_collection_link = promote_collection_concept_candidate(
        db,
        candidate_id=training_collection_candidate.id,
        accepted_judgment_run_id=12,
    )
    race_collection_candidate = propose_collection_concept_candidate(
        db,
        collection_id=collection_ids["tour-of-taiyuan-route-family"],
        concept_node_id=concept_ids["tour-of-taiyuan"],
        relation_type="part_of_event",
        proposer_kind="human",
        created_by_judgment_run_id=3,
    )
    race_collection_link = promote_collection_concept_candidate(
        db,
        candidate_id=race_collection_candidate.id,
        accepted_judgment_run_id=12,
    )

    route_line_hash = db.execute(text("SELECT line_hash FROM route_versions WHERE id = 1")).scalar_one()
    segment_geometry_hash = db.execute(
        text("SELECT geometry_hash FROM route_cognition_segments WHERE segment_id = 1")
    ).scalar_one()
    promoted_candidates = _promoted_candidate_summary(db)
    formal_link_summary = [
        {
            "source_object": "环西山正骑",
            "relation_type": route_link.relation_type,
            "concept": "新手有氧",
            "candidate_status": promoted_candidates["route"][route_candidate.id],
            "link_table": "route_concept_links",
            "source_candidate_id": route_link.source_route_concept_candidate_id,
            "source_kind": route_link.source_kind,
            "accepted_judgment_run_type": route_link.accepted_judgment_run_type,
        },
        {
            "source_object": "横岭",
            "relation_type": climb_link.relation_type,
            "concept": "爬坡训练",
            "candidate_status": promoted_candidates["segment"][climb_candidate.id],
            "link_table": "segment_concept_links",
            "source_candidate_id": climb_link.source_segment_concept_candidate_id,
            "source_kind": climb_link.source_kind,
            "accepted_judgment_run_type": climb_link.accepted_judgment_run_type,
        },
        {
            "source_object": "横岭",
            "relation_type": risk_link.relation_type,
            "concept": "碎石风险",
            "candidate_status": promoted_candidates["segment"][risk_candidate.id],
            "link_table": "segment_concept_links",
            "source_candidate_id": risk_link.source_segment_concept_candidate_id,
            "source_kind": risk_link.source_kind,
            "accepted_judgment_run_type": risk_link.accepted_judgment_run_type,
        },
        {
            "source_object": "西山训练体系",
            "relation_type": training_collection_link.relation_type,
            "concept": "爬坡训练",
            "candidate_status": promoted_candidates["collection"][training_collection_candidate.id],
            "link_table": "collection_concept_links",
            "source_candidate_id": training_collection_link.source_collection_concept_candidate_id,
            "source_kind": training_collection_link.source_kind,
            "accepted_judgment_run_type": training_collection_link.accepted_judgment_run_type,
        },
        {
            "source_object": "环太原赛路线族",
            "relation_type": race_collection_link.relation_type,
            "concept": "环太原赛",
            "candidate_status": promoted_candidates["collection"][race_collection_candidate.id],
            "link_table": "collection_concept_links",
            "source_candidate_id": race_collection_link.source_collection_concept_candidate_id,
            "source_kind": race_collection_link.source_kind,
            "accepted_judgment_run_type": race_collection_link.accepted_judgment_run_type,
        },
    ]

    assert formal_link_summary == [
        {
            "source_object": "环西山正骑",
            "relation_type": "suitable_for",
            "concept": "新手有氧",
            "candidate_status": "accepted",
            "link_table": "route_concept_links",
            "source_candidate_id": route_candidate.id,
            "source_kind": "candidate_accepted",
            "accepted_judgment_run_type": "human_review",
        },
        {
            "source_object": "横岭",
            "relation_type": "suitable_for",
            "concept": "爬坡训练",
            "candidate_status": "accepted",
            "link_table": "segment_concept_links",
            "source_candidate_id": climb_candidate.id,
            "source_kind": "candidate_accepted",
            "accepted_judgment_run_type": "human_review",
        },
        {
            "source_object": "横岭",
            "relation_type": "has_risk",
            "concept": "碎石风险",
            "candidate_status": "accepted",
            "link_table": "segment_concept_links",
            "source_candidate_id": risk_candidate.id,
            "source_kind": "candidate_accepted",
            "accepted_judgment_run_type": "human_review",
        },
        {
            "source_object": "西山训练体系",
            "relation_type": "training_theme",
            "concept": "爬坡训练",
            "candidate_status": "accepted",
            "link_table": "collection_concept_links",
            "source_candidate_id": training_collection_candidate.id,
            "source_kind": "candidate_accepted",
            "accepted_judgment_run_type": "human_review",
        },
        {
            "source_object": "环太原赛路线族",
            "relation_type": "part_of_event",
            "concept": "环太原赛",
            "candidate_status": "accepted",
            "link_table": "collection_concept_links",
            "source_candidate_id": race_collection_candidate.id,
            "source_kind": "candidate_accepted",
            "accepted_judgment_run_type": "human_review",
        },
    ]
    assert route_candidate.route_line_hash == route_line_hash
    assert route_link.route_line_hash == route_candidate.route_line_hash
    assert climb_candidate.segment_geometry_hash == segment_geometry_hash
    assert risk_candidate.segment_geometry_hash == segment_geometry_hash
    assert climb_link.segment_geometry_hash == climb_candidate.segment_geometry_hash
    assert risk_link.segment_geometry_hash == risk_candidate.segment_geometry_hash
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM segment_concept_links")).scalar_one() == 2
    assert db.execute(text("SELECT count(*) FROM collection_concept_links")).scalar_one() == 2
    assert _all_promoted_candidates_have_acceptance(db)
    assert _no_manual_or_legacy_formal_links(db)
    for table_name in FORBIDDEN_EMPTY_TABLES:
        assert db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one() == 0
    assert _simple_table_snapshot(db, "route_books") == route_book_before
    assert _simple_table_snapshot(db, "route_versions") == route_version_before
    assert _simple_table_snapshot(db, "segments") == segment_before
    assert _simple_table_snapshot(db, "segment_efforts") == effort_before
    assert _route_guides_snapshot(db) == guide_before
    assert _content_routes_snapshot() == content_routes_before


@pytest.mark.parametrize("judgment_run_id", [20, 21, 22])
def test_seed_promotion_rejects_non_accepted_human_review_runs(
    db, concept_formal_link_seed_dry_run_tables, judgment_run_id
):
    concept_ids = _create_seed_concepts(db)
    candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=concept_ids["beginner-aerobic"],
        relation_type="suitable_for",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )

    with pytest.raises(ConceptFormalLinkWriterError):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=judgment_run_id,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


@pytest.mark.parametrize("candidate_status", ["rejected", "stale", "inconclusive"])
def test_seed_terminal_candidate_status_cannot_promote(
    db, concept_formal_link_seed_dry_run_tables, candidate_status
):
    concept_ids = _create_seed_concepts(db)
    candidate_id = _insert_route_candidate(
        db,
        candidate_status=candidate_status,
        concept_node_id=concept_ids["beginner-aerobic"],
    )

    with pytest.raises(ConceptFormalLinkWriterError, match="candidate_status"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate_id,
            accepted_judgment_run_id=10,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 0


def test_seed_already_accepted_candidate_cannot_promote_twice(db, concept_formal_link_seed_dry_run_tables):
    concept_ids = _create_seed_concepts(db)
    candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=concept_ids["beginner-aerobic"],
        relation_type="suitable_for",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )
    promote_route_concept_candidate(
        db,
        candidate_id=candidate.id,
        accepted_judgment_run_id=10,
    )

    with pytest.raises(ConceptFormalLinkWriterError, match="candidate_status"):
        promote_route_concept_candidate(
            db,
            candidate_id=candidate.id,
            accepted_judgment_run_id=10,
        )
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 1


def test_seed_same_source_candidate_cannot_create_two_formal_links(db, concept_formal_link_seed_dry_run_tables):
    concept_ids = _create_seed_concepts(db)
    candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=concept_ids["beginner-aerobic"],
        relation_type="suitable_for",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )
    promote_route_concept_candidate(
        db,
        candidate_id=candidate.id,
        accepted_judgment_run_id=10,
    )

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(
                text(
                    """
                    INSERT INTO route_concept_links (
                        route_book_id, route_version_id, route_line_hash, concept_node_id,
                        relation_type, link_status, source_kind, accepted_judgment_run_id,
                        accepted_judgment_run_type, source_route_concept_candidate_id
                    )
                    VALUES (
                        1, 1, :route_line_hash, :concept_node_id,
                        'suitable_for', 'deprecated', 'candidate_accepted', 10,
                        'human_review', :candidate_id
                    )
                    """
                ),
                {
                    "route_line_hash": candidate.route_line_hash,
                    "concept_node_id": concept_ids["beginner-aerobic"],
                    "candidate_id": candidate.id,
                },
            )

    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 1


def test_seed_duplicate_active_formal_link_rolls_candidate_back(db, concept_formal_link_seed_dry_run_tables):
    concept_ids = _create_seed_concepts(db)
    first_candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=concept_ids["beginner-aerobic"],
        relation_type="suitable_for",
        proposer_kind="agent",
        created_by_judgment_run_id=1,
    )
    promote_route_concept_candidate(
        db,
        candidate_id=first_candidate.id,
        accepted_judgment_run_id=10,
    )
    second_candidate = propose_route_concept_candidate(
        db,
        route_book_id=1,
        route_version_id=1,
        concept_node_id=concept_ids["beginner-aerobic"],
        relation_type="suitable_for",
        proposer_kind="human",
        created_by_judgment_run_id=3,
    )
    # 这里提交的是测试库里的基线状态，像先把地板钉住，再故意推倒第二步看会不会回滚。
    # writer 本身仍然不提交事务。
    db.commit()

    with pytest.raises(IntegrityError):
        promote_route_concept_candidate(
            db,
            candidate_id=second_candidate.id,
            accepted_judgment_run_id=10,
        )
    db.rollback()

    assert db.execute(
        text(
            """
            SELECT candidate_status, accepted_by_judgment_run_id
            FROM route_concept_candidates
            WHERE id = :candidate_id
            """
        ),
        {"candidate_id": second_candidate.id},
    ).one() == ("proposed", None)
    assert db.execute(text("SELECT count(*) FROM route_concept_links")).scalar_one() == 1


def test_seed_raw_segment_cannot_enter_candidate_or_formal_link(db, concept_formal_link_seed_dry_run_tables):
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
    assert db.execute(text("SELECT count(*) FROM segment_concept_candidates")).scalar_one() == 0
    assert db.execute(text("SELECT count(*) FROM segment_concept_links")).scalar_one() == 0


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
            summary=f"{concept['name']} formal link seed dry-run",
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
        for row in db.execute(text("SELECT id, name, content_md FROM route_guides ORDER BY id")).all()
    ]


def _simple_table_snapshot(db, table_name: str) -> list[tuple]:
    return [tuple(row) for row in db.execute(text(f"SELECT * FROM {table_name} ORDER BY id")).all()]


def _promoted_candidate_summary(db) -> dict[str, dict[int, str]]:
    return {
        "route": {
            row.id: row.candidate_status
            for row in db.execute(text("SELECT id, candidate_status FROM route_concept_candidates")).all()
        },
        "segment": {
            row.id: row.candidate_status
            for row in db.execute(text("SELECT id, candidate_status FROM segment_concept_candidates")).all()
        },
        "collection": {
            row.id: row.candidate_status
            for row in db.execute(text("SELECT id, candidate_status FROM collection_concept_candidates")).all()
        },
    }


def _all_promoted_candidates_have_acceptance(db) -> bool:
    for table_name in (
        "route_concept_candidates",
        "segment_concept_candidates",
        "collection_concept_candidates",
    ):
        missing = db.execute(
            text(
                f"""
                SELECT count(*)
                FROM {table_name}
                WHERE candidate_status = 'accepted'
                  AND accepted_by_judgment_run_id IS NULL
                """
            )
        ).scalar_one()
        if missing != 0:
            return False
    return True


def _no_manual_or_legacy_formal_links(db) -> bool:
    for table_name in (
        "route_concept_links",
        "segment_concept_links",
        "collection_concept_links",
    ):
        unexpected = db.execute(
            text(
                f"""
                SELECT count(*)
                FROM {table_name}
                WHERE source_kind IN ('manual_curated', 'legacy_import')
                """
            )
        ).scalar_one()
        if unexpected != 0:
            return False
    return True


def _seed_route_segment_guide_and_judgment_rows(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (
                id, run_type, status, confidence_state, route_book_id, route_version_id,
                segment_id, confidence, result_summary_json, missing_data_json, contradiction_json
            )
            VALUES
                (1, 'semantic_agent', 'succeeded', 'proposed', 1, 1, NULL, 0.71, '{"summary":"route proposal"}', NULL, NULL),
                (2, 'spatial_algorithm', 'succeeded', 'stable', NULL, NULL, 1, 0.62, '{"summary":"segment proposal"}', NULL, NULL),
                (3, 'semantic_agent', 'succeeded', 'stable', NULL, NULL, NULL, 0.66, '{"summary":"collection proposal"}', NULL, NULL),
                (10, 'human_review', 'succeeded', 'human_accepted', 1, 1, NULL, 0.95, '{"summary":"route accepted"}', NULL, NULL),
                (11, 'human_review', 'succeeded', 'stable', NULL, NULL, 1, 0.91, '{"summary":"segment accepted"}', NULL, NULL),
                (12, 'human_review', 'succeeded', 'human_accepted', NULL, NULL, NULL, 0.93, '{"summary":"collection accepted"}', NULL, NULL),
                (20, 'semantic_agent', 'succeeded', 'stable', NULL, NULL, NULL, 0.88, NULL, NULL, NULL),
                (21, 'human_review', 'failed', 'human_accepted', NULL, NULL, NULL, 0.2, NULL, NULL, NULL),
                (22, 'human_review', 'running', 'stable', NULL, NULL, NULL, 0.3, NULL, NULL, NULL)
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
            VALUES (
                1, '环西山正骑', 42000.0, 'LINESTRING(0 0, 1 1)',
                'manual_drawn', 'taiyuan', 'private', 'draft', 'route-book-hash-a'
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
                1, 1, 1, 'current', 'route_book_reference', 'ready',
                'LINESTRING(0 0, 1 1)', 'route-version-line-hash-a', 42000.0
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
    db.execute(text("INSERT INTO route_guides (id, name, content_md) VALUES (1, 'Guide Sentinel', 'original')"))


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
                contradiction_json TEXT,
                UNIQUE (id, run_type)
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
                distance REAL NOT NULL,
                UNIQUE (id, route_book_id)
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
    db.execute(text("CREATE TABLE segment_efforts (id INTEGER PRIMARY KEY AUTOINCREMENT, segment_id INTEGER NOT NULL)"))
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
    _create_route_concept_link_table(db)
    _create_segment_concept_link_table(db)
    _create_collection_concept_link_table(db)
    db.execute(text("CREATE TABLE evidence_items (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE route_segments (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_routes (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE collection_segments (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    db.execute(text("CREATE TABLE segment_submissions (id INTEGER PRIMARY KEY AUTOINCREMENT)"))


def _insert_route_candidate(db, *, candidate_status: str, concept_node_id: int) -> int:
    db.execute(
        text(
            """
            INSERT INTO route_concept_candidates (
                id, route_book_id, route_version_id, route_line_hash, concept_node_id,
                relation_type, proposer_kind, candidate_status, created_by_judgment_run_id,
                latest_judgment_run_id, accepted_by_judgment_run_id, latest_confidence,
                latest_confidence_state, reviewed_at
            )
            VALUES (
                100, 1, 1, 'route-version-line-hash-a', :concept_node_id,
                'suitable_for', 'agent', :candidate_status, 1,
                1, :accepted_by_judgment_run_id, 0.71,
                'proposed', :reviewed_at
            )
            """
        ),
        {
            "candidate_status": candidate_status,
            "concept_node_id": concept_node_id,
            "accepted_by_judgment_run_id": 10 if candidate_status == "accepted" else None,
            "reviewed_at": "2026-06-18 00:00:00" if candidate_status == "accepted" else None,
        },
    )
    return 100


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
