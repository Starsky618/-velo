"""add immutable source segment census tables

Revision ID: 20260813_seg_census
Revises: 20260811_internal_connectors
"""

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260813_seg_census"
down_revision = "20260811_internal_connectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "segment_census_batches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("region_key", sa.String(length=64), nullable=False),
        sa.Column("region_version", sa.String(length=64), nullable=False),
        sa.Column("source_platform", sa.String(length=32), nullable=False),
        sa.Column("activity_type", sa.String(length=16), nullable=False),
        sa.Column("protocol_version", sa.String(length=64), nullable=False),
        sa.Column("visibility_context", sa.String(length=64), nullable=False),
        sa.Column("region_definition_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "region_polygon",
            Geometry("POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("root_south", sa.Float(), nullable=False),
        sa.Column("root_west", sa.Float(), nullable=False),
        sa.Column("root_north", sa.Float(), nullable=False),
        sa.Column("root_east", sa.Float(), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("run_status", sa.String(length=32), nullable=False),
        sa.Column("enumeration_status", sa.String(length=32), nullable=False),
        sa.Column("request_status", sa.String(length=16), nullable=False),
        sa.Column("snapshot_status", sa.String(length=16), nullable=False),
        sa.Column("detail_status", sa.String(length=16), nullable=False),
        sa.Column("geometry_status", sa.String(length=16), nullable=False),
        sa.Column("leaderboard_status", sa.String(length=16), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("unique_segment_count", sa.Integer(), nullable=False),
        sa.Column("included_segment_count", sa.Integer(), nullable=False),
        sa.Column("outside_segment_count", sa.Integer(), nullable=False),
        sa.Column("unknown_membership_count", sa.Integer(), nullable=False),
        sa.Column("detail_complete_count", sa.Integer(), nullable=False),
        sa.Column("geometry_complete_count", sa.Integer(), nullable=False),
        sa.Column("leaderboard_complete_count", sa.Integer(), nullable=False),
        sa.Column("saturated_cell_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("pass_summaries_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pass_diff_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_response_retained", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source_platform = 'strava'", name="ck_segment_census_batches_source"),
        sa.CheckConstraint("activity_type = 'riding'", name="ck_segment_census_batches_activity"),
        sa.CheckConstraint(
            "run_status IN ('completed', 'completed_with_errors')",
            name="ck_segment_census_batches_run_status",
        ),
        sa.CheckConstraint(
            "enumeration_status IN ('source_visible_complete', 'indeterminate')",
            name="ck_segment_census_batches_enumeration_status",
        ),
        sa.CheckConstraint(
            "request_status IN ('complete', 'incomplete') "
            "AND snapshot_status IN ('complete', 'partial', 'failed') "
            "AND detail_status IN ('not_collected', 'complete', 'partial', 'failed') "
            "AND geometry_status IN ('not_collected', 'complete', 'partial', 'failed') "
            "AND leaderboard_status IN ('not_collected', 'partial', 'complete')",
            name="ck_segment_census_batches_axis_statuses",
        ),
        sa.CheckConstraint(
            "root_south < root_north AND root_west < root_east",
            name="ck_segment_census_batches_bounds",
        ),
        sa.CheckConstraint(
            "ST_IsValid(region_polygon)",
            name="ck_segment_census_batches_polygon_valid",
        ),
        sa.CheckConstraint(
            "max_depth >= 0 AND request_count >= 0 AND unique_segment_count >= 0 "
            "AND included_segment_count >= 0 AND outside_segment_count >= 0 "
            "AND unknown_membership_count >= 0 "
            "AND detail_complete_count >= 0 AND geometry_complete_count >= 0 "
            "AND leaderboard_complete_count >= 0 "
            "AND saturated_cell_count >= 0 AND error_count >= 0",
            name="ck_segment_census_batches_counts",
        ),
        sa.CheckConstraint(
            "included_segment_count + outside_segment_count + unknown_membership_count "
            "= unique_segment_count",
            name="ck_segment_census_batches_membership_counts",
        ),
        sa.CheckConstraint(
            "detail_complete_count <= unique_segment_count "
            "AND geometry_complete_count <= unique_segment_count "
            "AND leaderboard_complete_count <= unique_segment_count",
            name="ck_segment_census_batches_complete_counts",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_segment_census_batches_region_created",
        "segment_census_batches",
        ["region_key", "created_at"],
    )
    op.create_index(
        "idx_segment_census_batches_status",
        "segment_census_batches",
        ["run_status", "enumeration_status"],
    )

    op.create_table(
        "segment_source_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("census_batch_id", sa.String(length=64), nullable=False),
        sa.Column("source_platform", sa.String(length=32), nullable=False),
        sa.Column("source_segment_id", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activity_type", sa.String(length=16), nullable=False),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=128), nullable=True),
        sa.Column("country", sa.String(length=128), nullable=True),
        sa.Column("is_private", sa.Boolean(), nullable=True),
        sa.Column("is_hazardous", sa.Boolean(), nullable=True),
        sa.Column("climb_category", sa.Integer(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("average_gradient_pct", sa.Float(), nullable=True),
        sa.Column("maximum_gradient_pct", sa.Float(), nullable=True),
        sa.Column("elevation_gain_m", sa.Float(), nullable=True),
        sa.Column("elevation_high_m", sa.Float(), nullable=True),
        sa.Column("elevation_low_m", sa.Float(), nullable=True),
        sa.Column("athlete_count", sa.Integer(), nullable=True),
        sa.Column("effort_count", sa.Integer(), nullable=True),
        sa.Column("star_count", sa.Integer(), nullable=True),
        sa.Column("kom_time_s", sa.Integer(), nullable=True),
        sa.Column("qom_time_s", sa.Integer(), nullable=True),
        sa.Column("overall_best_time_s", sa.Integer(), nullable=True),
        sa.Column("start_lat", sa.Float(), nullable=True),
        sa.Column("start_lon", sa.Float(), nullable=True),
        sa.Column("end_lat", sa.Float(), nullable=True),
        sa.Column("end_lon", sa.Float(), nullable=True),
        sa.Column(
            "source_line",
            Geometry("LINESTRING", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("geometry_point_count", sa.Integer(), nullable=True),
        sa.Column("geometry_original_size", sa.Integer(), nullable=True),
        sa.Column("geometry_resolution", sa.String(length=16), nullable=True),
        sa.Column("query_bounds_relation", sa.String(length=16), nullable=False),
        sa.Column("region_membership", sa.String(length=16), nullable=False),
        sa.Column("seen_passes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detail_status", sa.String(length=16), nullable=False),
        sa.Column("geometry_status", sa.String(length=16), nullable=False),
        sa.Column("leaderboard_status", sa.String(length=16), nullable=False),
        sa.Column("failure_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source_platform = 'strava'", name="ck_segment_source_obs_source"),
        sa.CheckConstraint("activity_type = 'Ride'", name="ck_segment_source_obs_activity"),
        sa.CheckConstraint(
            "detail_status IN ('complete', 'failed')",
            name="ck_segment_source_obs_detail_status",
        ),
        sa.CheckConstraint(
            "geometry_status IN ('complete', 'failed')",
            name="ck_segment_source_obs_geometry_status",
        ),
        sa.CheckConstraint(
            "leaderboard_status IN ('not_collected', 'partial', 'complete')",
            name="ck_segment_source_obs_leaderboard_status",
        ),
        sa.CheckConstraint(
            "query_bounds_relation IN ('inside', 'crosses', 'outside', 'unknown')",
            name="ck_segment_source_obs_bounds_relation",
        ),
        sa.CheckConstraint(
            "region_membership IN ('inside', 'crosses', 'outside', 'unknown')",
            name="ck_segment_source_obs_region_membership",
        ),
        sa.CheckConstraint(
            "(detail_status = 'complete' AND distance_m > 0) OR detail_status = 'failed'",
            name="ck_segment_source_obs_detail_complete",
        ),
        sa.CheckConstraint(
            "(geometry_status = 'complete' AND source_line IS NOT NULL "
            "AND geometry_point_count >= 2 "
            "AND geometry_original_size = geometry_point_count) "
            "OR (geometry_status = 'failed' AND source_line IS NULL)",
            name="ck_segment_source_obs_geometry_complete",
        ),
        sa.CheckConstraint(
            "athlete_count IS NULL OR athlete_count >= 0",
            name="ck_segment_source_obs_athletes",
        ),
        sa.CheckConstraint(
            "effort_count IS NULL OR effort_count >= 0",
            name="ck_segment_source_obs_efforts",
        ),
        sa.CheckConstraint("star_count IS NULL OR star_count >= 0", name="ck_segment_source_obs_stars"),
        sa.ForeignKeyConstraint(
            ["census_batch_id"],
            ["segment_census_batches.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "census_batch_id",
            "source_platform",
            "source_segment_id",
            name="uq_segment_source_obs_batch_source_id",
        ),
    )
    op.create_index(
        "idx_segment_source_obs_source_id",
        "segment_source_observations",
        ["source_platform", "source_segment_id", "observed_at"],
    )
    op.create_index(
        "idx_segment_source_obs_batch",
        "segment_source_observations",
        ["census_batch_id"],
    )
    op.create_index(
        "idx_segment_source_obs_line",
        "segment_source_observations",
        ["source_line"],
        postgresql_using="gist",
    )
    op.execute(sa.text("""
        CREATE FUNCTION reject_segment_census_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'segment census snapshots are append-only';
        END;
        $$
    """))
    for table_name in ("segment_census_batches", "segment_source_observations"):
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
    op.drop_index("idx_segment_source_obs_line", table_name="segment_source_observations")
    op.drop_index("idx_segment_source_obs_batch", table_name="segment_source_observations")
    op.drop_index("idx_segment_source_obs_source_id", table_name="segment_source_observations")
    op.drop_table("segment_source_observations")
    op.drop_index("idx_segment_census_batches_status", table_name="segment_census_batches")
    op.drop_index("idx_segment_census_batches_region_created", table_name="segment_census_batches")
    op.drop_table("segment_census_batches")
    op.execute(sa.text("DROP FUNCTION reject_segment_census_mutation()"))
