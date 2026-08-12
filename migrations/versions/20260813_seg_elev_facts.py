"""add immutable per-observation GLO-30 elevation facts

Revision ID: 20260813_seg_elev_facts
Revises: 20260813_seg_census
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260813_seg_elev_facts"
down_revision = "20260813_seg_census"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_segment_source_obs_id_batch",
        "segment_source_observations",
        ["id", "census_batch_id"],
    )

    op.create_table(
        "segment_elevation_fact_batches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("census_batch_id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("geometry_normalization_version", sa.String(length=64), nullable=False),
        sa.Column("run_status", sa.String(length=32), nullable=False),
        sa.Column("input_observation_count", sa.Integer(), nullable=False),
        sa.Column("eligible_geometry_count", sa.Integer(), nullable=False),
        sa.Column("source_incomplete_count", sa.Integer(), nullable=False),
        sa.Column("source_incomplete_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("complete_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope = 'inside_or_crosses'",
            name="ck_segment_elev_fact_batch_scope",
        ),
        sa.CheckConstraint(
            "run_status IN ('completed', 'completed_with_failures')",
            name="ck_segment_elev_fact_batch_status",
        ),
        sa.CheckConstraint(
            "input_observation_count >= 0 AND eligible_geometry_count >= 0 "
            "AND source_incomplete_count >= 0 AND complete_count >= 0 "
            "AND failed_count >= 0",
            name="ck_segment_elev_fact_batch_counts",
        ),
        sa.CheckConstraint(
            "eligible_geometry_count + source_incomplete_count = input_observation_count "
            "AND complete_count + failed_count = eligible_geometry_count",
            name="ck_segment_elev_fact_batch_accounting",
        ),
        sa.CheckConstraint(
            "(run_status = 'completed' AND source_incomplete_count = 0 AND failed_count = 0) "
            "OR (run_status = 'completed_with_failures' "
            "AND (source_incomplete_count > 0 OR failed_count > 0))",
            name="ck_segment_elev_fact_batch_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["census_batch_id"],
            ["segment_census_batches.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "census_batch_id",
            name="uq_segment_elev_fact_batch_id_census",
        ),
        sa.UniqueConstraint(
            "census_batch_id",
            "algorithm_version",
            "geometry_normalization_version",
            "scope",
            name="uq_segment_elev_fact_batch_inputs",
        ),
    )
    op.create_index(
        "idx_segment_elev_fact_batch_census",
        "segment_elevation_fact_batches",
        ["census_batch_id"],
    )

    op.create_table(
        "segment_elevation_facts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("fact_batch_id", sa.String(length=64), nullable=False),
        sa.Column("census_batch_id", sa.String(length=64), nullable=False),
        sa.Column("source_observation_id", sa.Integer(), nullable=False),
        sa.Column("source_segment_id", sa.String(length=64), nullable=False),
        sa.Column("source_geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("geometry_normalization_version", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("fact_status", sa.String(length=16), nullable=False),
        sa.Column("method_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("elevation_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("elevation_profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_point_count", sa.Integer(), nullable=False),
        sa.Column("elevation_point_count", sa.Integer(), nullable=True),
        sa.Column("derived_distance_m", sa.Float(), nullable=True),
        sa.Column("climb_m", sa.Float(), nullable=True),
        sa.Column("descent_m", sa.Float(), nullable=True),
        sa.Column("start_elevation_m", sa.Float(), nullable=True),
        sa.Column("end_elevation_m", sa.Float(), nullable=True),
        sa.Column("minimum_elevation_m", sa.Float(), nullable=True),
        sa.Column("maximum_elevation_m", sa.Float(), nullable=True),
        sa.Column("net_elevation_change_m", sa.Float(), nullable=True),
        sa.Column("average_gradient_pct", sa.Float(), nullable=True),
        sa.Column("maximum_gradient_pct", sa.Float(), nullable=True),
        sa.Column("maximum_gradient_window_m", sa.Float(), nullable=True),
        sa.Column("source_distance_difference_pct", sa.Float(), nullable=True),
        sa.Column("quality_flags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "fact_status IN ('complete', 'failed')",
            name="ck_segment_elev_fact_status",
        ),
        sa.CheckConstraint(
            "source_point_count >= 2 AND "
            "(elevation_point_count IS NULL OR elevation_point_count >= 2)",
            name="ck_segment_elev_fact_point_counts",
        ),
        sa.CheckConstraint(
            "source_distance_difference_pct IS NULL OR source_distance_difference_pct >= 0",
            name="ck_segment_elev_fact_distance_diff",
        ),
        sa.CheckConstraint(
            "(fact_status = 'complete' AND elevation_snapshot_json IS NOT NULL "
            "AND elevation_profile_json IS NOT NULL "
            "AND elevation_point_count = source_point_count "
            "AND derived_distance_m > 0 AND climb_m >= 0 AND descent_m >= 0 "
            "AND start_elevation_m IS NOT NULL AND end_elevation_m IS NOT NULL "
            "AND minimum_elevation_m IS NOT NULL AND maximum_elevation_m IS NOT NULL "
            "AND net_elevation_change_m IS NOT NULL AND average_gradient_pct IS NOT NULL "
            "AND maximum_gradient_pct IS NOT NULL AND maximum_gradient_window_m > 0 "
            "AND failure_json IS NULL) OR "
            "(fact_status = 'failed' AND elevation_snapshot_json IS NULL "
            "AND elevation_profile_json IS NULL AND elevation_point_count IS NULL "
            "AND derived_distance_m IS NULL AND climb_m IS NULL AND descent_m IS NULL "
            "AND start_elevation_m IS NULL AND end_elevation_m IS NULL "
            "AND minimum_elevation_m IS NULL AND maximum_elevation_m IS NULL "
            "AND net_elevation_change_m IS NULL AND average_gradient_pct IS NULL "
            "AND maximum_gradient_pct IS NULL AND maximum_gradient_window_m IS NULL "
            "AND failure_json IS NOT NULL)",
            name="ck_segment_elev_fact_payload",
        ),
        sa.ForeignKeyConstraint(
            ["fact_batch_id", "census_batch_id"],
            [
                "segment_elevation_fact_batches.id",
                "segment_elevation_fact_batches.census_batch_id",
            ],
            ondelete="RESTRICT",
            name="fk_segment_elev_fact_batch_census",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id", "census_batch_id"],
            [
                "segment_source_observations.id",
                "segment_source_observations.census_batch_id",
            ],
            ondelete="RESTRICT",
            name="fk_segment_elev_fact_source_observation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_observation_id",
            "source_geometry_hash",
            "algorithm_version",
            name="uq_segment_elev_fact_input_version",
        ),
    )
    op.create_index(
        "idx_segment_elev_fact_batch",
        "segment_elevation_facts",
        ["fact_batch_id"],
    )
    op.create_index(
        "idx_segment_elev_fact_source",
        "segment_elevation_facts",
        ["source_segment_id"],
    )
    op.create_index(
        "idx_segment_elev_fact_geometry_hash",
        "segment_elevation_facts",
        ["source_geometry_hash"],
    )

    for table_name in (
        "segment_elevation_fact_batches",
        "segment_elevation_facts",
    ):
        op.execute(sa.text(f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_segment_census_mutation()
        """))
        op.execute(sa.text(f"""
            CREATE TRIGGER trg_{table_name}_no_truncate
            BEFORE TRUNCATE ON {table_name}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_segment_census_mutation()
        """))


def downgrade() -> None:
    op.drop_index("idx_segment_elev_fact_geometry_hash", table_name="segment_elevation_facts")
    op.drop_index("idx_segment_elev_fact_source", table_name="segment_elevation_facts")
    op.drop_index("idx_segment_elev_fact_batch", table_name="segment_elevation_facts")
    op.drop_table("segment_elevation_facts")
    op.drop_index(
        "idx_segment_elev_fact_batch_census",
        table_name="segment_elevation_fact_batches",
    )
    op.drop_table("segment_elevation_fact_batches")
    op.drop_constraint(
        "uq_segment_source_obs_id_batch",
        "segment_source_observations",
        type_="unique",
    )
