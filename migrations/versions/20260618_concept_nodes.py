"""Add concept node foundation.

Revision ID: 20260618_concept_nodes
Revises: 20260618_route_collections
Create Date: 2026-06-18
"""

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260618_concept_nodes"
down_revision = "20260618_route_collections"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """建立语义概念本体；不创建关系、候选、层级或公开接口。"""
    op.create_table(
        "concept_nodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("scope_type", sa.String(length=16), server_default="global", nullable=False),
        sa.Column("scope_value", sa.String(length=128), server_default="global", nullable=False),
        sa.Column("city", sa.String(length=64), nullable=True),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("visibility", sa.String(length=16), server_default="private", nullable=False),
        sa.Column("publish_status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description_md", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("geom", Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False), nullable=True),
        sa.Column("center_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("center_lon", sa.Numeric(9, 6), nullable=True),
        sa.Column("source", sa.String(length=16), server_default="manual", nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("metadata_json", _jsonb(), nullable=True),
        sa.Column("source_judgment_run_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_concept_nodes_name_nonempty"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9_-]{1,127}$'",
            name="ck_concept_nodes_slug_format",
        ),
        sa.CheckConstraint(
            "node_type IN ('practice_type', 'landmark', 'road_condition', 'safety_risk', "
            "'event', 'local_term', 'place', 'training_theme', 'other')",
            name="ck_concept_nodes_node_type",
        ),
        sa.CheckConstraint(
            "scope_type IN ('global', 'city', 'region')",
            name="ck_concept_nodes_scope_type",
        ),
        sa.CheckConstraint(
            "(scope_type = 'global' AND scope_value = 'global') OR "
            "(scope_type = 'city' AND scope_value <> 'global') OR "
            "(scope_type = 'region' AND scope_value <> 'global')",
            name="ck_concept_nodes_scope_rule",
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')",
            name="ck_concept_nodes_visibility",
        ),
        sa.CheckConstraint(
            "publish_status IN ('draft', 'published', 'archived')",
            name="ck_concept_nodes_publish_status",
        ),
        sa.CheckConstraint("source IN ('manual', 'imported')", name="ck_concept_nodes_source"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_concept_nodes_confidence_range",
        ),
        sa.CheckConstraint(
            "center_lat IS NULL OR (center_lat >= -90 AND center_lat <= 90)",
            name="ck_concept_nodes_center_lat_range",
        ),
        sa.CheckConstraint(
            "center_lon IS NULL OR (center_lon >= -180 AND center_lon <= 180)",
            name="ck_concept_nodes_center_lon_range",
        ),
        sa.CheckConstraint(
            "(center_lat IS NULL AND center_lon IS NULL) OR "
            "(center_lat IS NOT NULL AND center_lon IS NOT NULL)",
            name="ck_concept_nodes_center_pair",
        ),
        sa.CheckConstraint(
            "visibility <> 'public' OR publish_status = 'published'",
            name="ck_concept_nodes_publication_state",
        ),
        sa.CheckConstraint(
            "publish_status <> 'published' OR source_judgment_run_id IS NOT NULL",
            name="ck_concept_nodes_published_judgment",
        ),
        sa.CheckConstraint(
            "source <> 'imported' OR source_ref IS NOT NULL OR source_judgment_run_id IS NOT NULL",
            name="ck_concept_nodes_import_source_ref",
        ),
        sa.CheckConstraint(
            "geom IS NULL OR ("
            "ST_IsValid(geom) "
            "AND upper(replace(GeometryType(geom), 'ST_', '')) IN "
            "('POINT', 'MULTIPOINT', 'LINESTRING', 'MULTILINESTRING', 'POLYGON', 'MULTIPOLYGON')"
            ")",
            name="ck_concept_nodes_geom_valid_type",
        ),
        sa.ForeignKeyConstraint(
            ["source_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_concept_nodes_source_judgment_run",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_concept_nodes_created_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_value",
            "node_type",
            "slug",
            name="uq_concept_nodes_scope_type_scope_value_node_type_slug",
        ),
    )
    op.create_index("idx_concept_nodes_scope", "concept_nodes", ["scope_type", "scope_value"])
    op.create_index("idx_concept_nodes_type", "concept_nodes", ["node_type"])
    op.create_index("idx_concept_nodes_slug", "concept_nodes", ["slug"])
    op.create_index(
        "idx_concept_nodes_visibility_status",
        "concept_nodes",
        ["visibility", "publish_status"],
    )
    op.create_index(
        "idx_concept_nodes_source_judgment",
        "concept_nodes",
        ["source_judgment_run_id"],
    )
    op.create_index("idx_concept_nodes_created_by", "concept_nodes", ["created_by"])
    op.create_index(
        "idx_concept_nodes_geom",
        "concept_nodes",
        ["geom"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    """移除语义概念本体；不触碰 route、segment、collection 或判断台账。"""
    op.drop_index("idx_concept_nodes_geom", table_name="concept_nodes", postgresql_using="gist")
    op.drop_index("idx_concept_nodes_created_by", table_name="concept_nodes")
    op.drop_index("idx_concept_nodes_source_judgment", table_name="concept_nodes")
    op.drop_index("idx_concept_nodes_visibility_status", table_name="concept_nodes")
    op.drop_index("idx_concept_nodes_slug", table_name="concept_nodes")
    op.drop_index("idx_concept_nodes_type", table_name="concept_nodes")
    op.drop_index("idx_concept_nodes_scope", table_name="concept_nodes")
    op.drop_table("concept_nodes")
