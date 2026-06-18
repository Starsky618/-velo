"""增加正式 segment 进入路线认知系统的可信入口。

Revision ID: 20260618_route_cognition_batch5
Revises: 20260618_route_cognition_batch4
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260618_route_cognition_batch5"
down_revision = "20260618_route_cognition_batch4"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """建立 Batch 5 segment 几何来源和认知白名单；不自动回填旧 segment。"""
    op.create_table(
        "segment_geometry_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_activity_id", sa.Integer(), nullable=True),
        sa.Column("source_file_id", sa.String(length=512), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_start_index", sa.Integer(), nullable=True),
        sa.Column("source_end_index", sa.Integer(), nullable=True),
        sa.Column("source_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_coordinate_system", sa.String(length=16), nullable=True),
        sa.Column("geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=True),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("quality_status", sa.String(length=16), nullable=False),
        sa.Column("quality_metrics_json", _jsonb(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('activity_clip', 'gpx_upload', 'fit_upload', 'admin_import')",
            name="ck_segment_geometry_sources_source_type",
        ),
        sa.CheckConstraint(
            "quality_status IN ('verified', 'needs_review', 'rejected', 'deprecated')",
            name="ck_segment_geometry_sources_quality_status",
        ),
        sa.CheckConstraint(
            "original_coordinate_system IS NULL OR "
            "original_coordinate_system IN ('wgs84', 'gcj02', 'unknown')",
            name="ck_segment_geometry_sources_coordinate_system",
        ),
        sa.CheckConstraint(
            "source_start_index IS NULL OR source_end_index IS NULL "
            "OR source_start_index < source_end_index",
            name="ck_segment_geometry_sources_index_order",
        ),
        sa.CheckConstraint(
            "("
            "source_type = 'activity_clip' "
            "AND source_content_hash IS NOT NULL"
            ") OR ("
            "source_type IN ('gpx_upload', 'fit_upload', 'admin_import') "
            "AND ("
            "source_file_id IS NOT NULL "
            "OR source_url IS NOT NULL "
            "OR source_content_hash IS NOT NULL"
            ")"
            ")",
            name="ck_segment_geometry_sources_material_pointer",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_segment_geometry_sources_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["segments.id"],
            name="fk_segment_geometry_sources_segment",
        ),
        sa.ForeignKeyConstraint(
            ["source_activity_id"],
            ["activities.id"],
            name="fk_segment_geometry_sources_source_activity",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "segment_id", name="uq_segment_geometry_sources_id_segment"),
        sa.UniqueConstraint(
            "id",
            "segment_id",
            "geometry_hash",
            name="uq_segment_geometry_sources_id_segment_geometry_hash",
        ),
    )
    op.create_index("idx_segment_geometry_sources_segment", "segment_geometry_sources", ["segment_id"])
    op.create_index("idx_segment_geometry_sources_source_type", "segment_geometry_sources", ["source_type"])
    op.create_index(
        "idx_segment_geometry_sources_activity",
        "segment_geometry_sources",
        ["source_activity_id"],
    )
    op.create_index("idx_segment_geometry_sources_file", "segment_geometry_sources", ["source_file_id"])
    op.create_index(
        "idx_segment_geometry_sources_geometry_hash",
        "segment_geometry_sources",
        ["geometry_hash"],
    )
    op.create_index("idx_segment_geometry_sources_quality", "segment_geometry_sources", ["quality_status"])

    op.create_table(
        "route_cognition_segments",
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("primary_geometry_source_id", sa.Integer(), nullable=True),
        sa.Column("review_basis", sa.String(length=32), nullable=False),
        sa.Column("eligibility_status", sa.String(length=16), nullable=False),
        sa.Column("geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("accepted_judgment_run_id", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "review_basis IN ('provenance_verified', 'legacy_reviewed')",
            name="ck_route_cognition_segments_review_basis",
        ),
        sa.CheckConstraint(
            "eligibility_status IN ('active', 'suspended', 'deprecated')",
            name="ck_route_cognition_segments_eligibility_status",
        ),
        sa.CheckConstraint(
            "accepted_judgment_run_id IS NOT NULL "
            "AND geometry_hash IS NOT NULL "
            "AND normalization_version IS NOT NULL "
            "AND reviewed_at IS NOT NULL",
            name="ck_route_cognition_segments_required_review_fields",
        ),
        sa.CheckConstraint(
            "("
            "review_basis = 'provenance_verified' "
            "AND primary_geometry_source_id IS NOT NULL"
            ") OR ("
            "review_basis = 'legacy_reviewed' "
            "AND primary_geometry_source_id IS NULL"
            ")",
            name="ck_route_cognition_segments_review_basis_source",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_route_cognition_segments_accepted_judgment",
        ),
        sa.ForeignKeyConstraint(
            ["primary_geometry_source_id", "segment_id"],
            ["segment_geometry_sources.id", "segment_geometry_sources.segment_id"],
            name="fk_route_cognition_segments_primary_source_segment",
        ),
        sa.ForeignKeyConstraint(
            ["primary_geometry_source_id", "segment_id", "geometry_hash"],
            [
                "segment_geometry_sources.id",
                "segment_geometry_sources.segment_id",
                "segment_geometry_sources.geometry_hash",
            ],
            name="fk_route_cognition_segments_primary_source_geometry_hash",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name="fk_route_cognition_segments_reviewed_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["segments.id"],
            name="fk_route_cognition_segments_segment",
        ),
        sa.PrimaryKeyConstraint("segment_id"),
        sa.UniqueConstraint(
            "primary_geometry_source_id",
            name="uq_route_cognition_segments_primary_source",
        ),
    )
    op.create_index(
        "idx_route_cognition_segments_eligibility",
        "route_cognition_segments",
        ["eligibility_status"],
    )
    op.create_index(
        "idx_route_cognition_segments_review_basis",
        "route_cognition_segments",
        ["review_basis"],
    )
    op.create_index(
        "idx_route_cognition_segments_judgment",
        "route_cognition_segments",
        ["accepted_judgment_run_id"],
    )
    op.create_index(
        "idx_route_cognition_segments_reviewed_by",
        "route_cognition_segments",
        ["reviewed_by"],
    )
    op.create_index(
        "idx_route_cognition_segments_geometry_hash",
        "route_cognition_segments",
        ["geometry_hash"],
    )


def downgrade() -> None:
    """移除 Batch 5 segment 入口；不触碰旧 segments 或 judgment 台账。"""
    op.drop_table("route_cognition_segments")
    op.drop_table("segment_geometry_sources")
