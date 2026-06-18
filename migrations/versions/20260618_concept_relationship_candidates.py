"""Add typed concept relationship candidate tables.

Revision ID: 20260618_concept_rel_candidates
Revises: 20260618_concept_nodes
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260618_concept_rel_candidates"
down_revision = "20260618_concept_nodes"
branch_labels = None
depends_on = None


RELATION_TYPE_CHECK = (
    "relation_type IN ('suitable_for', 'passes_near', 'has_feature', 'has_risk', "
    "'part_of_event', 'story_reference', 'training_theme', 'local_name', 'associated_with')"
)
PROPOSER_KIND_CHECK = "proposer_kind IN ('algorithm', 'agent', 'human', 'imported')"
CANDIDATE_STATUS_CHECK = (
    "candidate_status IN ('proposed', 'needs_review', 'accepted', 'rejected', "
    "'withdrawn', 'superseded', 'stale', 'inconclusive')"
)
CONFIDENCE_STATE_CHECK = (
    "latest_confidence_state IN ('raw', 'proposed', 'challenged', 'stable', "
    "'human_accepted', 'stale', 'inconclusive')"
)
ACCEPTANCE_GATE_CHECK = (
    "((candidate_status = 'accepted' AND accepted_by_judgment_run_id IS NOT NULL "
    "AND reviewed_at IS NOT NULL) OR "
    "(candidate_status <> 'accepted' AND accepted_by_judgment_run_id IS NULL))"
)
OPEN_CANDIDATE_WHERE = "candidate_status IN ('proposed', 'needs_review')"


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("proposer_kind", sa.String(length=16), nullable=False),
        sa.Column("candidate_status", sa.String(length=16), nullable=False),
        sa.Column("created_by_judgment_run_id", sa.Integer(), nullable=False),
        sa.Column("latest_judgment_run_id", sa.Integer(), nullable=False),
        sa.Column("accepted_by_judgment_run_id", sa.Integer(), nullable=True),
        sa.Column("latest_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("latest_confidence_state", sa.String(length=32), nullable=False),
        sa.Column("latest_evidence_summary_json", _jsonb(), nullable=True),
        sa.Column("latest_missing_data_summary_json", _jsonb(), nullable=True),
        sa.Column("latest_contradiction_summary_json", _jsonb(), nullable=True),
        sa.Column("reason_summary", sa.Text(), nullable=True),
        sa.Column("metadata_json", _jsonb(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _common_constraints(table_name: str) -> list[sa.schema.Constraint]:
    return [
        sa.CheckConstraint(RELATION_TYPE_CHECK, name=f"ck_{table_name}_relation_type"),
        sa.CheckConstraint(PROPOSER_KIND_CHECK, name=f"ck_{table_name}_proposer_kind"),
        sa.CheckConstraint(CANDIDATE_STATUS_CHECK, name=f"ck_{table_name}_candidate_status"),
        sa.CheckConstraint(
            "latest_confidence IS NULL OR (latest_confidence >= 0 AND latest_confidence <= 1)",
            name=f"ck_{table_name}_latest_confidence_range",
        ),
        sa.CheckConstraint(CONFIDENCE_STATE_CHECK, name=f"ck_{table_name}_latest_confidence_state"),
        sa.CheckConstraint(ACCEPTANCE_GATE_CHECK, name=f"ck_{table_name}_acceptance_gate"),
        sa.ForeignKeyConstraint(
            ["created_by_judgment_run_id"],
            ["judgment_runs.id"],
            name=f"fk_{table_name}_created_by_judgment_run",
        ),
        sa.ForeignKeyConstraint(
            ["latest_judgment_run_id"],
            ["judgment_runs.id"],
            name=f"fk_{table_name}_latest_judgment_run",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_judgment_run_id"],
            ["judgment_runs.id"],
            name=f"fk_{table_name}_accepted_by_judgment_run",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=f"fk_{table_name}_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name=f"fk_{table_name}_reviewed_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "accepted_by_judgment_run_id", name=f"uq_{table_name}_formal_gate"),
    ]


def _create_common_indexes(table_name: str, target_indexes: list[str], open_columns: list[str]) -> None:
    for column_name in target_indexes:
        op.create_index(f"idx_{table_name}_{column_name}", table_name, [column_name])
    op.create_index(f"idx_{table_name}_concept_node", table_name, ["concept_node_id"])
    op.create_index(f"idx_{table_name}_status", table_name, ["candidate_status"])
    op.create_index(f"idx_{table_name}_relation_type", table_name, ["relation_type"])
    op.create_index(f"idx_{table_name}_created_by_run", table_name, ["created_by_judgment_run_id"])
    op.create_index(f"idx_{table_name}_latest_run", table_name, ["latest_judgment_run_id"])
    op.create_index(f"idx_{table_name}_accepted_run", table_name, ["accepted_by_judgment_run_id"])
    op.create_index(f"idx_{table_name}_created_by", table_name, ["created_by"])
    op.create_index(f"idx_{table_name}_reviewed_by", table_name, ["reviewed_by"])
    op.create_index(
        f"uq_{table_name}_open_candidate",
        table_name,
        open_columns,
        unique=True,
        postgresql_where=sa.text("candidate_status IN ('proposed', 'needs_review')"),
    )


def _drop_common_indexes(table_name: str, target_indexes: list[str]) -> None:
    op.drop_index(f"uq_{table_name}_open_candidate", table_name=table_name)
    op.drop_index(f"idx_{table_name}_reviewed_by", table_name=table_name)
    op.drop_index(f"idx_{table_name}_created_by", table_name=table_name)
    op.drop_index(f"idx_{table_name}_accepted_run", table_name=table_name)
    op.drop_index(f"idx_{table_name}_latest_run", table_name=table_name)
    op.drop_index(f"idx_{table_name}_created_by_run", table_name=table_name)
    op.drop_index(f"idx_{table_name}_relation_type", table_name=table_name)
    op.drop_index(f"idx_{table_name}_status", table_name=table_name)
    op.drop_index(f"idx_{table_name}_concept_node", table_name=table_name)
    for column_name in reversed(target_indexes):
        op.drop_index(f"idx_{table_name}_{column_name}", table_name=table_name)


def upgrade() -> None:
    """建立三张 typed concept 关系候选表；不创建正式关系、成员关系或公开接口。"""
    op.create_table(
        "route_concept_candidates",
        sa.Column("route_book_id", sa.Integer(), nullable=False),
        sa.Column("route_version_id", sa.Integer(), nullable=False),
        sa.Column("route_line_hash", sa.String(length=64), nullable=False),
        sa.Column("concept_node_id", sa.Integer(), nullable=False),
        *_common_columns(),
        sa.ForeignKeyConstraint(
            ["route_book_id"],
            ["route_books.id"],
            name="fk_route_concept_candidates_route_book",
        ),
        sa.ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_concept_candidates_route_version_book",
        ),
        sa.ForeignKeyConstraint(
            ["concept_node_id"],
            ["concept_nodes.id"],
            name="fk_route_concept_candidates_concept_node",
        ),
        sa.UniqueConstraint(
            "route_book_id",
            "route_version_id",
            "concept_node_id",
            "relation_type",
            "created_by_judgment_run_id",
            name="uq_route_concept_candidates_idempotency",
        ),
        *_common_constraints("route_concept_candidates"),
    )
    _create_common_indexes(
        "route_concept_candidates",
        ["route_book_id", "route_version_id"],
        ["route_book_id", "route_version_id", "concept_node_id", "relation_type"],
    )

    op.create_table(
        "segment_concept_candidates",
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("segment_geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("concept_node_id", sa.Integer(), nullable=False),
        *_common_columns(),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["route_cognition_segments.segment_id"],
            name="fk_segment_concept_candidates_segment",
        ),
        sa.ForeignKeyConstraint(
            ["concept_node_id"],
            ["concept_nodes.id"],
            name="fk_segment_concept_candidates_concept_node",
        ),
        sa.UniqueConstraint(
            "segment_id",
            "concept_node_id",
            "relation_type",
            "created_by_judgment_run_id",
            name="uq_segment_concept_candidates_idempotency",
        ),
        *_common_constraints("segment_concept_candidates"),
    )
    _create_common_indexes(
        "segment_concept_candidates",
        ["segment_id"],
        ["segment_id", "concept_node_id", "relation_type"],
    )

    op.create_table(
        "collection_concept_candidates",
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("concept_node_id", sa.Integer(), nullable=False),
        *_common_columns(),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["route_collections.id"],
            name="fk_collection_concept_candidates_collection",
        ),
        sa.ForeignKeyConstraint(
            ["concept_node_id"],
            ["concept_nodes.id"],
            name="fk_collection_concept_candidates_concept_node",
        ),
        sa.UniqueConstraint(
            "collection_id",
            "concept_node_id",
            "relation_type",
            "created_by_judgment_run_id",
            name="uq_collection_concept_candidates_idempotency",
        ),
        *_common_constraints("collection_concept_candidates"),
    )
    _create_common_indexes(
        "collection_concept_candidates",
        ["collection_id"],
        ["collection_id", "concept_node_id", "relation_type"],
    )


def downgrade() -> None:
    """移除三张 concept 关系候选表；不触碰 concept 本体或任何正式关系。"""
    _drop_common_indexes("collection_concept_candidates", ["collection_id"])
    op.drop_table("collection_concept_candidates")

    _drop_common_indexes("segment_concept_candidates", ["segment_id"])
    op.drop_table("segment_concept_candidates")

    _drop_common_indexes("route_concept_candidates", ["route_book_id", "route_version_id"])
    op.drop_table("route_concept_candidates")
