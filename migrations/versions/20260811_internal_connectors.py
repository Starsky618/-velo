"""add internal routing connectors

Revision ID: 20260811_internal_connectors
Revises: 20260809_seg_geom_gates
"""

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa


revision = "20260811_internal_connectors"
down_revision = "20260809_seg_geom_gates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "internal_routing_connectors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("city", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column(
            "traversal_policy",
            sa.String(length=16),
            server_default="bidirectional",
            nullable=False,
        ),
        sa.Column("endpoint_a_segment_id", sa.Integer(), nullable=False),
        sa.Column("endpoint_a_position", sa.String(length=8), nullable=False),
        sa.Column("endpoint_b_segment_id", sa.Integer(), nullable=False),
        sa.Column("endpoint_b_position", sa.String(length=8), nullable=False),
        sa.Column("start_lat", sa.Float(), nullable=False),
        sa.Column("start_lon", sa.Float(), nullable=False),
        sa.Column("end_lat", sa.Float(), nullable=False),
        sa.Column("end_lon", sa.Float(), nullable=False),
        sa.Column(
            "reference_line",
            Geometry("LINESTRING", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_point_count", sa.Integer(), nullable=False),
        sa.Column("input_was_reversed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("endpoint_a_snap_m", sa.Float(), nullable=False),
        sa.Column("endpoint_b_snap_m", sa.Float(), nullable=False),
        sa.Column("blocked_provider", sa.String(length=32), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', "
            "'chengdu', 'taiyuan', 'unknown')",
            name="ck_internal_connectors_city",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_internal_connectors_status",
        ),
        sa.CheckConstraint(
            "traversal_policy IN ('bidirectional', 'a_to_b_only')",
            name="ck_internal_connectors_policy",
        ),
        sa.CheckConstraint(
            "endpoint_a_position IN ('start', 'end')",
            name="ck_internal_connectors_a_position",
        ),
        sa.CheckConstraint(
            "endpoint_b_position IN ('start', 'end')",
            name="ck_internal_connectors_b_position",
        ),
        sa.CheckConstraint(
            "source_type IN ('hand_drawn_gpx', 'recorded_gpx', 'reviewed_polyline')",
            name="ck_internal_connectors_source_type",
        ),
        sa.CheckConstraint(
            "distance > 0 AND distance <= 5000 AND source_point_count >= 3",
            name="ck_internal_connectors_geometry",
        ),
        sa.CheckConstraint(
            "endpoint_a_snap_m BETWEEN 0 AND 100 "
            "AND endpoint_b_snap_m BETWEEN 0 AND 100",
            name="ck_internal_connectors_snap",
        ),
        sa.CheckConstraint(
            "endpoint_a_segment_id <> endpoint_b_segment_id",
            name="ck_internal_connectors_distinct_segments",
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_a_segment_id"],
            ["segments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_b_segment_id"],
            ["segments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("geometry_hash", name="uq_internal_connectors_geometry_hash"),
        sa.UniqueConstraint("slug", name="uq_internal_connectors_slug"),
    )
    op.create_index(
        "idx_internal_connectors_endpoints",
        "internal_routing_connectors",
        ["endpoint_a_segment_id", "endpoint_b_segment_id", "status"],
    )
    op.create_index(
        "idx_internal_connectors_geom",
        "internal_routing_connectors",
        ["reference_line"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_internal_connectors_geom",
        table_name="internal_routing_connectors",
    )
    op.drop_index(
        "idx_internal_connectors_endpoints",
        table_name="internal_routing_connectors",
    )
    op.drop_table("internal_routing_connectors")
