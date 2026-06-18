"""路线认知 Batch 4 测试——把判断台账和外部研究回路先锁成数据库契约。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import JSONB


def _check_sql(table, name: str) -> str:
    checks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == name
    ]
    assert checks
    return str(checks[0].sqltext)


def _composite_fk(table, name: str) -> ForeignKeyConstraint:
    fks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name == name
    ]
    assert fks
    return fks[0]


def _constraint_block(path: str, constraint_name: str) -> str:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if constraint_name in line:
            start = index
            while start > 0 and "ForeignKeyConstraint(" not in lines[start] and "op.create_foreign_key(" not in lines[start]:
                start -= 1

            end = index
            while end < len(lines):
                if end > index and lines[end].strip() in {")", "),"}:
                    return "\n".join(lines[start : end + 1])
                end += 1
            return "\n".join(lines[start:])
    raise AssertionError(f"{constraint_name} not found in {path}")


def test_batch4_models_declare_judgment_research_and_evidence_tables():
    from app.route_cognition.models import (
        EvidenceItem,
        JudgmentRun,
        JudgmentRunEvidence,
        ResearchQuestion,
        ResearchRun,
    )

    assert JudgmentRun.__tablename__ == "judgment_runs"
    assert EvidenceItem.__tablename__ == "evidence_items"
    assert JudgmentRunEvidence.__tablename__ == "judgment_run_evidence"
    assert ResearchQuestion.__tablename__ == "research_questions"
    assert ResearchRun.__tablename__ == "research_runs"

    assert {"route_book_id", "route_version_id", "confidence_state"} <= set(JudgmentRun.__table__.c.keys())
    assert {"first_judgment_run_id", "evidence_type", "rights_status"} <= set(EvidenceItem.__table__.c.keys())
    assert {"judgment_run_id", "evidence_item_id", "evidence_role"} <= set(JudgmentRunEvidence.__table__.c.keys())
    assert {"question_text", "question_type", "status"} <= set(ResearchQuestion.__table__.c.keys())
    assert {"research_question_id", "queries_json", "summary_json"} <= set(ResearchRun.__table__.c.keys())

    assert isinstance(JudgmentRun.__table__.c.params_json.type, JSONB)
    assert isinstance(EvidenceItem.__table__.c.metrics_json.type, JSONB)
    assert isinstance(ResearchRun.__table__.c.summary_json.type, JSONB)


def test_batch4_models_keep_route_version_composite_foreign_keys():
    from app.route_cognition.models import EvidenceItem, JudgmentRun, ResearchQuestion

    for table, name in (
        (JudgmentRun.__table__, "fk_judgment_runs_route_version_book"),
        (ResearchQuestion.__table__, "fk_research_questions_route_version_book"),
        (EvidenceItem.__table__, "fk_evidence_items_route_version_book"),
    ):
        fk = _composite_fk(table, name)
        assert {element.parent.name for element in fk.elements} == {"route_version_id", "route_book_id"}
        assert fk.ondelete is None


def test_route_guides_source_route_version_composite_fk_does_not_set_null_context():
    from app.route_book.models import RouteGuide

    fk = _composite_fk(RouteGuide.__table__, "fk_route_guides_source_route_version")
    assert {element.parent.name for element in fk.elements} == {"source_route_version_id", "route_book_id"}
    assert fk.ondelete is None


def test_batch4_models_declare_required_checks_and_no_candidate_scope():
    from app.route_cognition.models import EvidenceItem, JudgmentRun, JudgmentRunEvidence, ResearchQuestion

    run_type_sql = _check_sql(JudgmentRun.__table__, "ck_judgment_runs_run_type")
    assert "spatial_algorithm" in run_type_sql
    assert "human_review" in run_type_sql

    confidence_sql = _check_sql(JudgmentRun.__table__, "ck_judgment_runs_confidence_range")
    assert "confidence" in confidence_sql

    evidence_type_sql = _check_sql(EvidenceItem.__table__, "ck_evidence_items_evidence_type")
    assert "route_version_geometry" in evidence_type_sql
    assert "human_review_decision" in evidence_type_sql

    rights_sql = _check_sql(EvidenceItem.__table__, "ck_evidence_items_rights_status")
    assert "unknown" in rights_sql
    assert "self_owned" in rights_sql

    role_sql = _check_sql(JudgmentRunEvidence.__table__, "ck_judgment_run_evidence_role")
    assert "contradicting" in role_sql

    question_sql = _check_sql(ResearchQuestion.__table__, "ck_research_questions_question_type")
    assert "event_association" in question_sql
    assert "platform_metric_conflict" in question_sql

    for table in (JudgmentRun.__table__, EvidenceItem.__table__, ResearchQuestion.__table__):
        assert "candidate" not in table.name


def test_route_guides_reserves_source_judgment_run_id_without_rewriting_content():
    from app.route_book.models import RouteGuide

    columns = RouteGuide.__table__.c
    assert "source_judgment_run_id" in columns.keys()
    assert columns.source_judgment_run_id.nullable is True
    assert columns.content_md.nullable is False


def test_evidence_item_documents_fidelity_tier_meaning():
    from app.route_cognition.models import EvidenceItem

    status_path = Path("docs/research/route_cognition_v1_1_status.md")
    combined_text = "\n".join(
        (
            EvidenceItem.__doc__ or "",
            status_path.read_text(encoding="utf-8"),
        )
    )

    for phrase in (
        "1 = raw geometry / raw profile",
        "2 = structured metric",
        "3 = image / screenshot",
        "4 = UGC / web text",
        "5 = model inference",
    ):
        assert phrase in combined_text


def test_batch4_migration_builds_only_judgment_research_evidence_scope():
    migration = "migrations/versions/20260618_route_cognition_batch4.py"
    with open(migration, encoding="utf-8") as f:
        migration_text = f.read()

    for table_name in (
        "judgment_runs",
        "evidence_items",
        "judgment_run_evidence",
        "research_questions",
        "research_runs",
    ):
        assert f'"{table_name}"' in migration_text

    assert "source_judgment_run_id" in migration_text
    assert "route_content_claims" not in migration_text
    assert "candidate" not in migration_text
    assert "concept" not in migration_text
    assert "pgvector" not in migration_text


def test_route_version_book_composite_fks_do_not_set_null_both_context_columns():
    batch4 = "migrations/versions/20260618_route_cognition_batch4.py"
    for name in (
        "fk_judgment_runs_route_version_book",
        "fk_research_questions_route_version_book",
        "fk_evidence_items_route_version_book",
    ):
        assert 'ondelete="SET NULL"' not in _constraint_block(batch4, name)

    route_guides = "migrations/versions/20260618_route_guides_provenance.py"
    assert 'ondelete="SET NULL"' not in _constraint_block(
        route_guides, "fk_route_guides_source_route_version"
    )

    route_exports = "migrations/versions/20260618_route_exports.py"
    for name in (
        "fk_route_export_jobs_route_version_book",
        "fk_route_export_artifacts_route_version_book",
    ):
        assert 'ondelete="SET NULL"' not in _constraint_block(route_exports, name)


@pytest.fixture()
def route_cognition_sqlite_tables(db):
    db.execute(text("PRAGMA foreign_keys=ON"))
    _drop_batch4_tables(db)
    _create_batch4_sqlite_tables(db)
    try:
        yield
    finally:
        db.rollback()
        _drop_batch4_tables(db)


def test_can_create_minimal_judgment_evidence_link_question_and_research_run(db, route_cognition_sqlite_tables):
    _seed_route_version_pair(db)

    db.execute(
        text(
            """
            INSERT INTO judgment_runs (
                id, run_type, status, trigger_type, route_book_id, route_version_id, confidence_state
            )
            VALUES (
                1, 'spatial_algorithm', 'succeeded', 'manual_test', 1, 10, 'stable'
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO evidence_items (
                id, first_judgment_run_id, evidence_type, fidelity_tier, rights_status, display_policy
            )
            VALUES (
                1, 1, 'route_version_geometry', 1, 'self_owned', 'internal_only'
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO judgment_run_evidence (
                id, judgment_run_id, evidence_item_id, evidence_role, assessment_result
            )
            VALUES (
                1, 1, 1, 'primary_physical_basis', 'supports'
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO research_questions (
                id, question_text, question_type, priority, status, route_book_id, route_version_id
            )
            VALUES (
                1, 'Why did this route spike?', 'abnormal_popularity', 'normal', 'open', 1, 10
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO research_runs (
                id, research_question_id, status, used_evidence_count, contradicting_evidence_count
            )
            VALUES (
                1, 1, 'queued', 0, 0
            )
            """
        )
    )

    assert db.execute(text("SELECT count(*) FROM judgment_runs")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM evidence_items")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM judgment_run_evidence")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM research_questions")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM research_runs")).scalar_one() == 1


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        (
            """
            INSERT INTO judgment_runs (
                run_type, status, trigger_type, confidence, confidence_state
            )
            VALUES ('spatial_algorithm', 'succeeded', 'manual_test', 1.2, 'stable')
            """,
            {},
        ),
        (
            """
            INSERT INTO evidence_items (
                first_judgment_run_id, evidence_type, fidelity_tier, rights_status, display_policy
            )
            VALUES (1, 'bad_type', 3, 'unknown', 'internal_only')
            """,
            {},
        ),
        (
            """
            INSERT INTO evidence_items (
                first_judgment_run_id, evidence_type, fidelity_tier, rights_status, display_policy
            )
            VALUES (1, 'ugc_text', 3, 'pirated', 'internal_only')
            """,
            {},
        ),
        (
            """
            INSERT INTO evidence_items (
                first_judgment_run_id, evidence_type, fidelity_tier, rights_status, display_policy
            )
            VALUES (1, 'ugc_text', 3, 'unknown', 'public')
            """,
            {},
        ),
        (
            """
            INSERT INTO evidence_items (
                evidence_type, fidelity_tier, rights_status, display_policy
            )
            VALUES ('ugc_text', 3, 'unknown', 'internal_only')
            """,
            {},
        ),
    ],
)
def test_batch4_sqlite_constraints_reject_invalid_values(db, route_cognition_sqlite_tables, sql, params):
    db.execute(
        text(
            """
            INSERT INTO judgment_runs (id, run_type, status, trigger_type, confidence_state)
            VALUES (1, 'spatial_algorithm', 'succeeded', 'manual_test', 'stable')
            """
        )
    )
    with pytest.raises(IntegrityError):
        db.execute(text(sql), params)


def test_route_book_version_mismatch_is_rejected_by_composite_fk(db, route_cognition_sqlite_tables):
    _seed_route_version_pair(db)
    db.execute(
        text(
            """
            INSERT INTO route_books (id, name, distance, source, city)
            VALUES (2, 'other route', 1000.0, 'file_upload', 'unknown')
            """
        )
    )

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                """
                INSERT INTO judgment_runs (
                    run_type, status, trigger_type, route_book_id, route_version_id, confidence_state
                )
                VALUES (
                    'spatial_algorithm', 'succeeded', 'manual_test', 2, 10, 'stable'
                )
                """
            )
        )


def _seed_route_version_pair(db) -> None:
    db.execute(
        text(
            """
            INSERT INTO route_books (id, name, distance, source, city)
            VALUES (1, 'test route', 1000.0, 'file_upload', 'unknown')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO route_versions (
                id, route_book_id, version_no, geometry_source, reference_line_snapshot, line_hash, distance
            )
            VALUES (
                10, 1, 1, 'file_upload', 'LINESTRING(0 0, 1 1)', 'hash', 1000.0
            )
            """
        )
    )


def _create_batch4_sqlite_tables(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE judgment_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                route_book_id INTEGER,
                route_version_id INTEGER,
                segment_id INTEGER,
                confidence NUMERIC,
                confidence_state TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CHECK (run_type IN ('spatial_algorithm', 'semantic_agent', 'adversarial_agent', 'human_review', 'research_synthesis', 'hybrid')),
                CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
                CHECK (confidence_state IN ('raw', 'proposed', 'challenged', 'stable', 'human_accepted', 'stale', 'inconclusive')),
                CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
                FOREIGN KEY(route_book_id) REFERENCES route_books(id),
                FOREIGN KEY(route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE evidence_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_judgment_run_id INTEGER NOT NULL,
                evidence_type TEXT NOT NULL,
                fidelity_tier INTEGER NOT NULL,
                route_book_id INTEGER,
                route_version_id INTEGER,
                rights_status TEXT NOT NULL DEFAULT 'unknown',
                display_policy TEXT NOT NULL DEFAULT 'internal_only',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CHECK (evidence_type IN ('route_version_geometry', 'verified_segment_geometry', 'internal_structured_metric', 'platform_metric', 'elevation_profile_image', 'ugc_text', 'web_page_text', 'model_inference', 'human_observation', 'human_review_decision')),
                CHECK (fidelity_tier BETWEEN 1 AND 5),
                CHECK (rights_status IN ('unknown', 'allowed', 'forbidden', 'licensed', 'self_owned')),
                CHECK (display_policy IN ('internal_only', 'summarize_only', 'display_allowed')),
                FOREIGN KEY(first_judgment_run_id) REFERENCES judgment_runs(id),
                FOREIGN KEY(route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE judgment_run_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                judgment_run_id INTEGER NOT NULL,
                evidence_item_id INTEGER NOT NULL,
                evidence_role TEXT NOT NULL,
                assessment_result TEXT NOT NULL,
                CHECK (evidence_role IN ('primary_input', 'primary_physical_basis', 'supporting', 'contradicting', 'background', 'weak_signal', 'comparison_target')),
                CHECK (assessment_result IN ('input', 'supports', 'contradicts', 'neutral', 'unverifiable', 'insufficient')),
                UNIQUE(judgment_run_id, evidence_item_id, evidence_role),
                FOREIGN KEY(judgment_run_id) REFERENCES judgment_runs(id),
                FOREIGN KEY(evidence_item_id) REFERENCES evidence_items(id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE research_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT NOT NULL,
                question_type TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'normal',
                status TEXT NOT NULL DEFAULT 'open',
                route_book_id INTEGER,
                route_version_id INTEGER,
                CHECK (question_type IN ('event_association', 'route_family_membership', 'name_origin', 'safety_condition', 'abnormal_popularity', 'foreign_rider_spike', 'platform_metric_conflict', 'physical_semantic_gap', 'content_rights_check', 'other')),
                CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
                CHECK (status IN ('open', 'researching', 'answered', 'unknown', 'contradicted', 'dismissed')),
                FOREIGN KEY(route_version_id, route_book_id) REFERENCES route_versions(id, route_book_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE research_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                research_question_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                used_evidence_count INTEGER NOT NULL DEFAULT 0,
                contradicting_evidence_count INTEGER NOT NULL DEFAULT 0,
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
                CHECK (used_evidence_count >= 0),
                CHECK (contradicting_evidence_count >= 0),
                FOREIGN KEY(research_question_id) REFERENCES research_questions(id)
            )
            """
        )
    )


def _drop_batch4_tables(db) -> None:
    for table_name in (
        "research_runs",
        "research_questions",
        "judgment_run_evidence",
        "evidence_items",
        "judgment_runs",
    ):
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
