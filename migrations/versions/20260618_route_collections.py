"""Add route collection foundation.

Revision ID: 20260618_route_collections
Revises: 20260618_route_cognition_batch5
Create Date: 2026-06-18
"""

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260618_route_collections"
down_revision = "20260618_route_cognition_batch5"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """建立路线专题容器本体；不创建成员关系、不回填旧路线或 segment。"""
    op.create_table(
        "route_collections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("collection_type", sa.String(length=32), nullable=False),
        sa.Column("city", sa.String(length=64), server_default="unknown", nullable=False),
        sa.Column("visibility", sa.String(length=16), server_default="private", nullable=False),
        sa.Column("publish_status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("description_md", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("geom", Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False), nullable=True),
        sa.Column("center_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("center_lon", sa.Numeric(9, 6), nullable=True),
        sa.Column("source", sa.String(length=16), server_default="manual", nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("stats_json", _jsonb(), nullable=True),
        sa.Column("metadata_json", _jsonb(), nullable=True),
        sa.Column("source_judgment_run_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_route_collections_name_nonempty"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9_-]{1,127}$'",
            name="ck_route_collections_slug_format",
        ),
        sa.CheckConstraint(
            "collection_type IN ('area_system', 'route_family', 'race_route_family', "
            "'training_corridor', 'theme_pack', 'other')",
            name="ck_route_collections_collection_type",
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')",
            name="ck_route_collections_visibility",
        ),
        sa.CheckConstraint(
            "publish_status IN ('draft', 'published', 'archived')",
            name="ck_route_collections_publish_status",
        ),
        sa.CheckConstraint("source IN ('manual', 'imported')", name="ck_route_collections_source"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_route_collections_confidence_range",
        ),
        sa.CheckConstraint(
            "center_lat IS NULL OR (center_lat >= -90 AND center_lat <= 90)",
            name="ck_route_collections_center_lat_range",
        ),
        sa.CheckConstraint(
            "center_lon IS NULL OR (center_lon >= -180 AND center_lon <= 180)",
            name="ck_route_collections_center_lon_range",
        ),
        sa.CheckConstraint(
            "(center_lat IS NULL AND center_lon IS NULL) OR "
            "(center_lat IS NOT NULL AND center_lon IS NOT NULL)",
            name="ck_route_collections_center_pair",
        ),
        sa.CheckConstraint(
            "visibility <> 'public' OR publish_status = 'published'",
            name="ck_route_collections_publication_state",
        ),
        sa.CheckConstraint(
            "publish_status <> 'published' OR source_judgment_run_id IS NOT NULL",
            name="ck_route_collections_published_judgment",
        ),
        sa.CheckConstraint(
            "source <> 'imported' OR source_ref IS NOT NULL OR source_judgment_run_id IS NOT NULL",
            name="ck_route_collections_import_source_ref",
        ),
        sa.CheckConstraint(
            "geom IS NULL OR ("
            "ST_IsValid(geom) "
            "AND upper(replace(GeometryType(geom), 'ST_', '')) IN "
            "('POLYGON', 'MULTIPOLYGON', 'LINESTRING', 'MULTILINESTRING')"
            ")",
            name="ck_route_collections_geom_valid_type",
        ),
        sa.ForeignKeyConstraint(
            ["source_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_route_collections_source_judgment_run",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_route_collections_created_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("city", "slug", name="uq_route_collections_city_slug"),
    )
    op.create_index("idx_route_collections_city", "route_collections", ["city"])
    op.create_index("idx_route_collections_slug", "route_collections", ["slug"])
    op.create_index("idx_route_collections_collection_type", "route_collections", ["collection_type"])
    op.create_index(
        "idx_route_collections_visibility_publish_status",
        "route_collections",
        ["visibility", "publish_status"],
    )
    op.create_index("idx_route_collections_created_by", "route_collections", ["created_by"])
    op.create_index(
        "idx_route_collections_source_judgment_run",
        "route_collections",
        ["source_judgment_run_id"],
    )
    op.create_index("idx_route_collections_source", "route_collections", ["source"])
    op.create_index(
        "idx_route_collections_geom",
        "route_collections",
        ["geom"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    """移除 Batch 7 路线专题容器；不触碰旧路线、segment 或判断台账。"""
    op.drop_index("idx_route_collections_geom", table_name="route_collections", postgresql_using="gist")
    op.drop_index("idx_route_collections_source", table_name="route_collections")
    op.drop_index("idx_route_collections_source_judgment_run", table_name="route_collections")
    op.drop_index("idx_route_collections_created_by", table_name="route_collections")
    op.drop_index("idx_route_collections_visibility_publish_status", table_name="route_collections")
    op.drop_index("idx_route_collections_collection_type", table_name="route_collections")
    op.drop_index("idx_route_collections_slug", table_name="route_collections")
    op.drop_index("idx_route_collections_city", table_name="route_collections")
    op.drop_table("route_collections")
