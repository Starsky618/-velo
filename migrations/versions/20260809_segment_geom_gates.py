"""segment geometry deterministic gates

Revision ID: 20260809_seg_geom_gates
Revises: 20260809_seg_geom_rebuild
"""

from alembic import op
import sqlalchemy as sa


revision = "20260809_seg_geom_gates"
down_revision = "20260809_seg_geom_rebuild"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "segment_routing_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ready", nullable=False),
        sa.Column("routing_provider", sa.String(length=16), server_default="tencent", nullable=False),
        sa.Column("routing_mode", sa.String(length=16), server_default="driving", nullable=False),
        sa.Column("control_points_json", sa.Text(), nullable=False),
        sa.Column("reference_line_wkt", sa.Text(), nullable=False),
        sa.Column("geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("provider_distance_m", sa.Float(), nullable=False),
        sa.Column("measured_distance_m", sa.Float(), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('ready', 'consumed')",
            name="ck_segment_routing_candidates_status",
        ),
        sa.CheckConstraint(
            "routing_provider = 'tencent'",
            name="ck_segment_routing_candidates_provider",
        ),
        sa.CheckConstraint(
            "routing_mode = 'driving'",
            name="ck_segment_routing_candidates_mode",
        ),
        sa.CheckConstraint(
            "provider_distance_m > 0 AND measured_distance_m > 0",
            name="ck_segment_routing_candidates_distance",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_segment_routing_candidates_segment",
        "segment_routing_candidates",
        ["segment_id", "created_at"],
    )
    op.add_column(
        "segment_geometry_revisions",
        sa.Column("source_segment_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "segment_geometry_revisions",
        sa.Column("source_distance_m", sa.Float(), nullable=True),
    )
    op.add_column(
        "segment_geometry_revisions",
        sa.Column("source_observation_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "segment_geometry_revisions",
        sa.Column("routing_candidate_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_segment_geometry_revisions_routing_candidate",
        "segment_geometry_revisions",
        "segment_routing_candidates",
        ["routing_candidate_id"],
        ["id"],
        ondelete="NO ACTION",
    )
    op.add_column(
        "segment_geometry_revisions",
        sa.Column("candidate_payload_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "segment_geometry_revisions",
        sa.Column("validation_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "segment_geometry_revisions",
        sa.Column("validation_metrics_json", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_segment_geometry_revisions_source_distance",
        "segment_geometry_revisions",
        "source_distance_m IS NULL OR source_distance_m > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_segment_geometry_revisions_source_distance",
        "segment_geometry_revisions",
        type_="check",
    )
    op.drop_column("segment_geometry_revisions", "validation_metrics_json")
    op.drop_column("segment_geometry_revisions", "validation_version")
    op.drop_column("segment_geometry_revisions", "candidate_payload_hash")
    op.drop_constraint(
        "fk_segment_geometry_revisions_routing_candidate",
        "segment_geometry_revisions",
        type_="foreignkey",
    )
    op.drop_column("segment_geometry_revisions", "routing_candidate_id")
    op.drop_column("segment_geometry_revisions", "source_observation_id")
    op.drop_column("segment_geometry_revisions", "source_distance_m")
    op.drop_column("segment_geometry_revisions", "source_segment_id")
    op.drop_index(
        "idx_segment_routing_candidates_segment",
        table_name="segment_routing_candidates",
    )
    op.drop_table("segment_routing_candidates")
