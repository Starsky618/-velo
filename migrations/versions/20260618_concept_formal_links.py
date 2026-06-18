"""Add concept formal relationship foundation.

Revision ID: 20260618_concept_formal_links
Revises: 20260618_concept_rel_candidates
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260618_concept_formal_links"
down_revision = "20260618_concept_rel_candidates"
branch_labels = None
depends_on = None


RELATION_TYPE_CHECK = (
    "relation_type IN ('suitable_for', 'passes_near', 'has_feature', 'has_risk', "
    "'part_of_event', 'story_reference', 'training_theme', 'local_name', 'associated_with')"
)
LINK_STATUS_CHECK = "link_status IN ('active', 'deprecated', 'superseded')"
SOURCE_KIND_CHECK = "source_kind IN ('candidate_accepted', 'manual_curated', 'legacy_import')"
ACCEPTED_JUDGMENT_TYPE_CHECK = "accepted_judgment_run_type = 'human_review'"


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def _common_formal_columns(source_candidate_column: str) -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("link_status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("accepted_judgment_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "accepted_judgment_run_type",
            sa.String(length=32),
            server_default="human_review",
            nullable=False,
        ),
        sa.Column(source_candidate_column, sa.Integer(), nullable=True),
        sa.Column("display_priority", sa.Integer(), nullable=True),
        sa.Column("reason_summary", sa.Text(), nullable=True),
        sa.Column("metadata_json", _jsonb(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _common_formal_constraints(table_name: str) -> list[sa.schema.Constraint]:
    source_candidate_column = _source_candidate_column(table_name)
    return [
        sa.CheckConstraint(RELATION_TYPE_CHECK, name=f"ck_{table_name}_relation_type"),
        sa.CheckConstraint(LINK_STATUS_CHECK, name=f"ck_{table_name}_link_status"),
        sa.CheckConstraint(SOURCE_KIND_CHECK, name=f"ck_{table_name}_source_kind"),
        sa.CheckConstraint(ACCEPTED_JUDGMENT_TYPE_CHECK, name=f"ck_{table_name}_accepted_judgment_run_type"),
        sa.CheckConstraint(
            f"((source_kind = 'candidate_accepted' AND {source_candidate_column} IS NOT NULL) OR "
            f"(source_kind IN ('manual_curated', 'legacy_import') AND {source_candidate_column} IS NULL))",
            name=f"ck_{table_name}_source_gate",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_judgment_run_id", "accepted_judgment_run_type"],
            ["judgment_runs.id", "judgment_runs.run_type"],
            name=f"fk_{table_name}_accepted_judgment_run",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=f"fk_{table_name}_created_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(source_candidate_column, name=f"uq_{table_name}_source_candidate"),
        sa.PrimaryKeyConstraint("id"),
    ]


def _source_candidate_column(table_name: str) -> str:
    return {
        "route_concept_links": "source_route_concept_candidate_id",
        "segment_concept_links": "source_segment_concept_candidate_id",
        "collection_concept_links": "source_collection_concept_candidate_id",
    }[table_name]


def _create_common_indexes(table_name: str, target_indexes: list[str], active_columns: list[str]) -> None:
    for column_name in target_indexes:
        op.create_index(f"idx_{table_name}_{column_name}", table_name, [column_name])
    op.create_index(f"idx_{table_name}_concept_node", table_name, ["concept_node_id"])
    op.create_index(f"idx_{table_name}_relation_type", table_name, ["relation_type"])
    op.create_index(f"idx_{table_name}_status", table_name, ["link_status"])
    op.create_index(f"idx_{table_name}_source_kind", table_name, ["source_kind"])
    op.create_index(f"idx_{table_name}_accepted_judgment", table_name, ["accepted_judgment_run_id"])
    op.create_index(f"idx_{table_name}_source_candidate", table_name, [_source_candidate_column(table_name)])
    op.create_index(f"idx_{table_name}_created_by", table_name, ["created_by"])
    op.create_index(
        f"uq_{table_name}_active",
        table_name,
        active_columns,
        unique=True,
        postgresql_where=sa.text("link_status = 'active'"),
    )


def _drop_common_indexes(table_name: str, target_indexes: list[str]) -> None:
    op.drop_index(f"uq_{table_name}_active", table_name=table_name)
    op.drop_index(f"idx_{table_name}_created_by", table_name=table_name)
    op.drop_index(f"idx_{table_name}_source_candidate", table_name=table_name)
    op.drop_index(f"idx_{table_name}_accepted_judgment", table_name=table_name)
    op.drop_index(f"idx_{table_name}_source_kind", table_name=table_name)
    op.drop_index(f"idx_{table_name}_status", table_name=table_name)
    op.drop_index(f"idx_{table_name}_relation_type", table_name=table_name)
    op.drop_index(f"idx_{table_name}_concept_node", table_name=table_name)
    for column_name in reversed(target_indexes):
        op.drop_index(f"idx_{table_name}_{column_name}", table_name=table_name)


def upgrade() -> None:
    """建立 concept 正式关系表；不创建 membership、API、admin UI 或其他候选表。"""
    op.create_unique_constraint("uq_judgment_runs_id_run_type", "judgment_runs", ["id", "run_type"])
    op.create_unique_constraint(
        "uq_route_concept_candidates_wide_formal_gate",
        "route_concept_candidates",
        [
            "id",
            "accepted_by_judgment_run_id",
            "route_book_id",
            "route_version_id",
            "route_line_hash",
            "concept_node_id",
            "relation_type",
        ],
    )
    op.create_unique_constraint(
        "uq_segment_concept_candidates_wide_formal_gate",
        "segment_concept_candidates",
        [
            "id",
            "accepted_by_judgment_run_id",
            "segment_id",
            "segment_geometry_hash",
            "concept_node_id",
            "relation_type",
        ],
    )
    op.create_unique_constraint(
        "uq_collection_concept_candidates_wide_formal_gate",
        "collection_concept_candidates",
        [
            "id",
            "accepted_by_judgment_run_id",
            "collection_id",
            "concept_node_id",
            "relation_type",
        ],
    )

    op.create_table(
        "route_concept_links",
        sa.Column("route_book_id", sa.Integer(), nullable=False),
        sa.Column("route_version_id", sa.Integer(), nullable=False),
        sa.Column("route_line_hash", sa.String(length=64), nullable=False),
        sa.Column("concept_node_id", sa.Integer(), nullable=False),
        *_common_formal_columns("source_route_concept_candidate_id"),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], name="fk_route_concept_links_route_book"),
        sa.ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_concept_links_route_version_book",
        ),
        sa.ForeignKeyConstraint(["concept_node_id"], ["concept_nodes.id"], name="fk_route_concept_links_concept_node"),
        sa.ForeignKeyConstraint(
            [
                "source_route_concept_candidate_id",
                "accepted_judgment_run_id",
                "route_book_id",
                "route_version_id",
                "route_line_hash",
                "concept_node_id",
                "relation_type",
            ],
            [
                "route_concept_candidates.id",
                "route_concept_candidates.accepted_by_judgment_run_id",
                "route_concept_candidates.route_book_id",
                "route_concept_candidates.route_version_id",
                "route_concept_candidates.route_line_hash",
                "route_concept_candidates.concept_node_id",
                "route_concept_candidates.relation_type",
            ],
            name="fk_route_concept_links_source_candidate_wide",
        ),
        *_common_formal_constraints("route_concept_links"),
    )
    _create_common_indexes(
        "route_concept_links",
        ["route_book_id", "route_version_id"],
        ["route_book_id", "route_version_id", "concept_node_id", "relation_type"],
    )

    op.create_table(
        "segment_concept_links",
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("segment_geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("concept_node_id", sa.Integer(), nullable=False),
        *_common_formal_columns("source_segment_concept_candidate_id"),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["route_cognition_segments.segment_id"],
            name="fk_segment_concept_links_segment",
        ),
        sa.ForeignKeyConstraint(["concept_node_id"], ["concept_nodes.id"], name="fk_segment_concept_links_concept_node"),
        sa.ForeignKeyConstraint(
            [
                "source_segment_concept_candidate_id",
                "accepted_judgment_run_id",
                "segment_id",
                "segment_geometry_hash",
                "concept_node_id",
                "relation_type",
            ],
            [
                "segment_concept_candidates.id",
                "segment_concept_candidates.accepted_by_judgment_run_id",
                "segment_concept_candidates.segment_id",
                "segment_concept_candidates.segment_geometry_hash",
                "segment_concept_candidates.concept_node_id",
                "segment_concept_candidates.relation_type",
            ],
            name="fk_segment_concept_links_source_candidate_wide",
        ),
        *_common_formal_constraints("segment_concept_links"),
    )
    _create_common_indexes(
        "segment_concept_links",
        ["segment_id"],
        ["segment_id", "concept_node_id", "relation_type"],
    )

    op.create_table(
        "collection_concept_links",
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("concept_node_id", sa.Integer(), nullable=False),
        *_common_formal_columns("source_collection_concept_candidate_id"),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["route_collections.id"],
            name="fk_collection_concept_links_collection",
        ),
        sa.ForeignKeyConstraint(
            ["concept_node_id"],
            ["concept_nodes.id"],
            name="fk_collection_concept_links_concept_node",
        ),
        sa.ForeignKeyConstraint(
            [
                "source_collection_concept_candidate_id",
                "accepted_judgment_run_id",
                "collection_id",
                "concept_node_id",
                "relation_type",
            ],
            [
                "collection_concept_candidates.id",
                "collection_concept_candidates.accepted_by_judgment_run_id",
                "collection_concept_candidates.collection_id",
                "collection_concept_candidates.concept_node_id",
                "collection_concept_candidates.relation_type",
            ],
            name="fk_collection_concept_links_source_candidate_wide",
        ),
        *_common_formal_constraints("collection_concept_links"),
    )
    _create_common_indexes(
        "collection_concept_links",
        ["collection_id"],
        ["collection_id", "concept_node_id", "relation_type"],
    )


def downgrade() -> None:
    """移除 concept 正式关系基础；保留 Step B 候选表自身。"""
    _drop_common_indexes("collection_concept_links", ["collection_id"])
    op.drop_table("collection_concept_links")

    _drop_common_indexes("segment_concept_links", ["segment_id"])
    op.drop_table("segment_concept_links")

    _drop_common_indexes("route_concept_links", ["route_book_id", "route_version_id"])
    op.drop_table("route_concept_links")

    op.drop_constraint(
        "uq_collection_concept_candidates_wide_formal_gate",
        "collection_concept_candidates",
        type_="unique",
    )
    op.drop_constraint(
        "uq_segment_concept_candidates_wide_formal_gate",
        "segment_concept_candidates",
        type_="unique",
    )
    op.drop_constraint("uq_route_concept_candidates_wide_formal_gate", "route_concept_candidates", type_="unique")
    op.drop_constraint("uq_judgment_runs_id_run_type", "judgment_runs", type_="unique")
