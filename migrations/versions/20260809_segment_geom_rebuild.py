"""segment canonical geometry rebuild workflow

Revision ID: 20260809_seg_geom_rebuild
Revises: 20260806_creator_ctx_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "20260809_seg_geom_rebuild"
down_revision = "20260806_creator_ctx_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "segment_geometry_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="staged", nullable=False),
        sa.Column("previous_geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_reference_line_wkt", sa.Text(), nullable=False),
        sa.Column("candidate_reference_line_wkt", sa.Text(), nullable=False),
        sa.Column("previous_snapshot_json", sa.Text(), nullable=False),
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("elevation_gain", sa.Float(), nullable=False),
        sa.Column("elevation_loss", sa.Float(), nullable=False),
        sa.Column("avg_gradient", sa.Float(), nullable=False),
        sa.Column("elevation_profile", sa.Text(), nullable=False),
        sa.Column("max_gradient", sa.Float(), nullable=True),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("city", sa.String(length=32), nullable=False),
        sa.Column("start_lat", sa.Float(), nullable=False),
        sa.Column("start_lon", sa.Float(), nullable=False),
        sa.Column("end_lat", sa.Float(), nullable=False),
        sa.Column("end_lon", sa.Float(), nullable=False),
        sa.Column("match_tolerance", sa.Float(), nullable=False),
        sa.Column("min_match_ratio", sa.Float(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("routing_provider", sa.String(length=16), server_default="tencent", nullable=False),
        sa.Column("routing_mode", sa.String(length=16), server_default="driving", nullable=False),
        sa.Column("original_coordinate_system", sa.String(length=16), server_default="gcj02", nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("dispatch_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('staged', 'processing', 'active', 'superseded', 'failed')",
            name="ck_segment_geometry_revisions_status",
        ),
        sa.CheckConstraint("routing_provider = 'tencent'", name="ck_segment_geometry_revisions_provider"),
        sa.CheckConstraint("routing_mode = 'driving'", name="ck_segment_geometry_revisions_mode"),
        sa.CheckConstraint(
            "original_coordinate_system IN ('gcj02', 'wgs84')",
            name="ck_segment_geometry_revisions_coordinate_system",
        ),
        sa.CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard', 'extreme')",
            name="ck_segment_geometry_revisions_difficulty",
        ),
        sa.CheckConstraint(
            "city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', 'chengdu', 'taiyuan', 'unknown')",
            name="ck_segment_geometry_revisions_city",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_segment_geometry_revisions_segment",
        "segment_geometry_revisions",
        ["segment_id", "created_at"],
    )
    op.create_index(
        "idx_segment_geometry_revisions_status",
        "segment_geometry_revisions",
        ["status"],
    )
    op.create_index(
        "uq_segment_geometry_revisions_one_pending",
        "segment_geometry_revisions",
        ["segment_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('staged', 'processing')"),
    )
    op.create_index(
        "uq_segment_geometry_revisions_one_active",
        "segment_geometry_revisions",
        ["segment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.drop_constraint(
        "ck_segment_geometry_sources_source_type",
        "segment_geometry_sources",
        type_="check",
    )
    op.create_check_constraint(
        "ck_segment_geometry_sources_source_type",
        "segment_geometry_sources",
        "source_type IN ('activity_clip', 'gpx_upload', 'fit_upload', 'admin_import', 'map_reconstruction')",
    )
    op.drop_constraint(
        "ck_segment_geometry_sources_material_pointer",
        "segment_geometry_sources",
        type_="check",
    )
    op.create_check_constraint(
        "ck_segment_geometry_sources_material_pointer",
        "segment_geometry_sources",
        "(source_type = 'activity_clip' AND source_content_hash IS NOT NULL) OR "
        "(source_type IN ('gpx_upload', 'fit_upload', 'admin_import', 'map_reconstruction') "
        "AND (source_file_id IS NOT NULL OR source_url IS NOT NULL OR source_content_hash IS NOT NULL))",
    )

    # 下游行自己保存“审核当时”的 geometry_hash，不能外键绑定到当前白名单 hash。
    # 否则 segment 换线后，要么永远不能重审恢复，要么级联篡改历史证据。
    op.drop_constraint(
        "fk_route_segments_segment_hash",
        "route_segments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_collection_segments_segment_hash",
        "collection_segments",
        type_="foreignkey",
    )


def downgrade() -> None:
    incompatible_history = op.get_bind().execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM route_segments AS rs
                JOIN route_cognition_segments AS rcs ON rcs.segment_id = rs.segment_id
                WHERE rs.segment_id IS NOT NULL
                  AND rs.segment_geometry_hash <> rcs.geometry_hash
            ) OR EXISTS (
                SELECT 1
                FROM collection_segments AS cs
                JOIN route_cognition_segments AS rcs ON rcs.segment_id = cs.segment_id
                WHERE cs.segment_geometry_hash <> rcs.geometry_hash
            )
            """
        )
    ).scalar_one()
    if incompatible_history:
        raise RuntimeError(
            "cannot downgrade segment geometry rebuild: historical membership hashes "
            "no longer match the current route cognition hash"
        )

    op.create_foreign_key(
        "fk_collection_segments_segment_hash",
        "collection_segments",
        "route_cognition_segments",
        ["segment_id", "segment_geometry_hash"],
        ["segment_id", "geometry_hash"],
    )
    op.create_foreign_key(
        "fk_route_segments_segment_hash",
        "route_segments",
        "route_cognition_segments",
        ["segment_id", "segment_geometry_hash"],
        ["segment_id", "geometry_hash"],
    )

    op.drop_constraint(
        "ck_segment_geometry_sources_material_pointer",
        "segment_geometry_sources",
        type_="check",
    )
    op.execute(
        "UPDATE segment_geometry_sources "
        "SET source_type = 'admin_import' "
        "WHERE source_type = 'map_reconstruction'"
    )
    op.create_check_constraint(
        "ck_segment_geometry_sources_material_pointer",
        "segment_geometry_sources",
        "(source_type = 'activity_clip' AND source_content_hash IS NOT NULL) OR "
        "(source_type IN ('gpx_upload', 'fit_upload', 'admin_import') "
        "AND (source_file_id IS NOT NULL OR source_url IS NOT NULL OR source_content_hash IS NOT NULL))",
    )
    op.drop_constraint(
        "ck_segment_geometry_sources_source_type",
        "segment_geometry_sources",
        type_="check",
    )
    op.create_check_constraint(
        "ck_segment_geometry_sources_source_type",
        "segment_geometry_sources",
        "source_type IN ('activity_clip', 'gpx_upload', 'fit_upload', 'admin_import')",
    )

    op.drop_index("uq_segment_geometry_revisions_one_active", table_name="segment_geometry_revisions")
    op.drop_index("uq_segment_geometry_revisions_one_pending", table_name="segment_geometry_revisions")
    op.drop_index("idx_segment_geometry_revisions_status", table_name="segment_geometry_revisions")
    op.drop_index("idx_segment_geometry_revisions_segment", table_name="segment_geometry_revisions")
    op.drop_table("segment_geometry_revisions")
