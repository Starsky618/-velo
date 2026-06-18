"""Add formal route and collection membership tables.

Revision ID: 20260618_membership_formal
Revises: 20260618_concept_formal_links
Create Date: 2026-06-18
"""

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260618_membership_formal"
down_revision = "20260618_concept_formal_links"
branch_labels = None
depends_on = None


MEMBERSHIP_STATUS_CHECK = "membership_status IN ('active', 'deprecated', 'superseded')"
SOURCE_KIND_CHECK = "source_kind IN ('manual_curated', 'legacy_import')"
ACCEPTED_JUDGMENT_TYPE_CHECK = "accepted_judgment_run_type = 'human_review'"
LEGACY_SOURCE_CHECK = (
    "source_kind <> 'legacy_import' OR source_ref IS NOT NULL OR reason_summary IS NOT NULL"
)
DISPLAY_PRIORITY_CHECK = "display_priority IS NULL OR (display_priority >= 0 AND display_priority <= 100)"


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def _common_membership_columns() -> list[sa.Column]:
    return [
        sa.Column("membership_status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("accepted_judgment_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "accepted_judgment_run_type",
            sa.String(length=32),
            server_default="human_review",
            nullable=False,
        ),
        sa.Column("display_priority", sa.Integer(), nullable=True),
        sa.Column("reason_summary", sa.Text(), nullable=True),
        sa.Column("metadata_json", _jsonb(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _common_membership_constraints(table_name: str) -> list[sa.schema.Constraint]:
    return [
        sa.CheckConstraint(MEMBERSHIP_STATUS_CHECK, name=f"ck_{table_name}_membership_status"),
        sa.CheckConstraint(SOURCE_KIND_CHECK, name=f"ck_{table_name}_source_kind"),
        sa.CheckConstraint(ACCEPTED_JUDGMENT_TYPE_CHECK, name=f"ck_{table_name}_accepted_judgment_run_type"),
        sa.CheckConstraint(LEGACY_SOURCE_CHECK, name=f"ck_{table_name}_legacy_source"),
        sa.CheckConstraint(DISPLAY_PRIORITY_CHECK, name=f"ck_{table_name}_display_priority_range"),
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
        sa.PrimaryKeyConstraint("id"),
    ]


def _create_route_segments() -> None:
    op.create_table(
        "route_segments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("route_book_id", sa.Integer(), nullable=False),
        sa.Column("route_version_id", sa.Integer(), nullable=False),
        sa.Column("route_line_hash", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("component_type", sa.String(length=32), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=True),
        sa.Column("segment_geometry_hash", sa.String(length=64), nullable=True),
        sa.Column("component_geometry", Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False), nullable=False),
        sa.Column("component_geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=True),
        sa.Column("start_fraction", sa.Numeric(8, 7), nullable=True),
        sa.Column("end_fraction", sa.Numeric(8, 7), nullable=True),
        *_common_membership_columns(),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], name="fk_route_segments_route_book"),
        sa.ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_segments_route_version_book",
        ),
        sa.ForeignKeyConstraint(["segment_id"], ["route_cognition_segments.segment_id"], name="fk_route_segments_segment"),
        sa.ForeignKeyConstraint(
            ["segment_id", "segment_geometry_hash"],
            ["route_cognition_segments.segment_id", "route_cognition_segments.geometry_hash"],
            name="fk_route_segments_segment_hash",
        ),
        sa.CheckConstraint("seq >= 1", name="ck_route_segments_seq_positive"),
        sa.CheckConstraint(
            "component_type IN ('segment_clip', 'custom_geometry')",
            name="ck_route_segments_component_type",
        ),
        sa.CheckConstraint(
            "((component_type = 'segment_clip' "
            "AND segment_id IS NOT NULL "
            "AND segment_geometry_hash IS NOT NULL "
            "AND component_geometry IS NOT NULL "
            "AND component_geometry_hash IS NOT NULL "
            "AND direction IN ('forward', 'reverse')) "
            "OR (component_type = 'custom_geometry' "
            "AND segment_id IS NULL "
            "AND segment_geometry_hash IS NULL "
            "AND component_geometry IS NOT NULL "
            "AND component_geometry_hash IS NOT NULL "
            "AND direction IS NULL))",
            name="ck_route_segments_component_contract",
        ),
        sa.CheckConstraint(
            "((start_fraction IS NULL AND end_fraction IS NULL) OR "
            "(component_type = 'segment_clip' "
            "AND start_fraction IS NOT NULL "
            "AND end_fraction IS NOT NULL "
            "AND start_fraction >= 0 "
            "AND end_fraction <= 1 "
            "AND start_fraction < end_fraction))",
            name="ck_route_segments_fraction_range",
        ),
        sa.CheckConstraint(
            "ST_IsValid(component_geometry) "
            "AND upper(replace(GeometryType(component_geometry), 'ST_', '')) IN "
            "('LINESTRING', 'MULTILINESTRING')",
            name="ck_route_segments_component_geometry_valid_type",
        ),
        *_common_membership_constraints("route_segments"),
    )
    op.create_index("idx_route_segments_route_version", "route_segments", ["route_version_id"])
    op.create_index("idx_route_segments_segment", "route_segments", ["segment_id"])
    op.create_index("idx_route_segments_status", "route_segments", ["membership_status"])
    op.create_index("idx_route_segments_accepted_judgment", "route_segments", ["accepted_judgment_run_id"])
    op.create_index("idx_route_segments_geom", "route_segments", ["component_geometry"], postgresql_using="gist")
    op.create_index(
        "uq_route_segments_active_seq",
        "route_segments",
        ["route_book_id", "route_version_id", "seq"],
        unique=True,
        postgresql_where=sa.text("membership_status = 'active'"),
    )


def _create_collection_routes() -> None:
    op.create_table(
        "collection_routes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("route_book_id", sa.Integer(), nullable=False),
        sa.Column("reviewed_route_version_id", sa.Integer(), nullable=False),
        sa.Column("reviewed_route_line_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=True),
        *_common_membership_columns(),
        sa.ForeignKeyConstraint(["collection_id"], ["route_collections.id"], name="fk_collection_routes_collection"),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], name="fk_collection_routes_route_book"),
        sa.ForeignKeyConstraint(
            ["reviewed_route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_collection_routes_route_version_book",
        ),
        sa.CheckConstraint(
            "role IN ('primary', 'featured', 'alternate', 'connector', 'reference', 'supporting')",
            name="ck_collection_routes_role",
        ),
        sa.CheckConstraint("seq IS NULL OR seq >= 1", name="ck_collection_routes_seq_positive"),
        sa.CheckConstraint(
            "importance IS NULL OR (importance >= 0 AND importance <= 100)",
            name="ck_collection_routes_importance_range",
        ),
        *_common_membership_constraints("collection_routes"),
    )
    op.create_index("idx_collection_routes_collection", "collection_routes", ["collection_id"])
    op.create_index("idx_collection_routes_route_book", "collection_routes", ["route_book_id"])
    op.create_index("idx_collection_routes_reviewed_route_version", "collection_routes", ["reviewed_route_version_id"])
    op.create_index("idx_collection_routes_status", "collection_routes", ["membership_status"])
    op.create_index("idx_collection_routes_accepted_judgment", "collection_routes", ["accepted_judgment_run_id"])
    op.create_index(
        "uq_collection_routes_active_route",
        "collection_routes",
        ["collection_id", "route_book_id"],
        unique=True,
        postgresql_where=sa.text("membership_status = 'active'"),
    )
    op.create_index(
        "uq_collection_routes_active_seq",
        "collection_routes",
        ["collection_id", "seq"],
        unique=True,
        postgresql_where=sa.text("membership_status = 'active' AND seq IS NOT NULL"),
    )


def _create_collection_segments() -> None:
    op.create_table(
        "collection_segments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("segment_geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=True),
        *_common_membership_columns(),
        sa.ForeignKeyConstraint(["collection_id"], ["route_collections.id"], name="fk_collection_segments_collection"),
        sa.ForeignKeyConstraint(["segment_id"], ["route_cognition_segments.segment_id"], name="fk_collection_segments_segment"),
        sa.ForeignKeyConstraint(
            ["segment_id", "segment_geometry_hash"],
            ["route_cognition_segments.segment_id", "route_cognition_segments.geometry_hash"],
            name="fk_collection_segments_segment_hash",
        ),
        sa.CheckConstraint(
            "role IN ('core', 'connector', 'landmark', 'risk_area', 'training_interval', 'supporting')",
            name="ck_collection_segments_role",
        ),
        sa.CheckConstraint("seq IS NULL OR seq >= 1", name="ck_collection_segments_seq_positive"),
        sa.CheckConstraint(
            "importance IS NULL OR (importance >= 0 AND importance <= 100)",
            name="ck_collection_segments_importance_range",
        ),
        *_common_membership_constraints("collection_segments"),
    )
    op.create_index("idx_collection_segments_collection", "collection_segments", ["collection_id"])
    op.create_index("idx_collection_segments_segment", "collection_segments", ["segment_id"])
    op.create_index("idx_collection_segments_status", "collection_segments", ["membership_status"])
    op.create_index("idx_collection_segments_accepted_judgment", "collection_segments", ["accepted_judgment_run_id"])
    op.create_index(
        "uq_collection_segments_active_segment",
        "collection_segments",
        ["collection_id", "segment_id"],
        unique=True,
        postgresql_where=sa.text("membership_status = 'active'"),
    )
    op.create_index(
        "uq_collection_segments_active_seq",
        "collection_segments",
        ["collection_id", "seq"],
        unique=True,
        postgresql_where=sa.text("membership_status = 'active' AND seq IS NOT NULL"),
    )


def upgrade() -> None:
    """建立正式 membership 表；不创建候选表、不开放 API、不回填旧数据。"""
    op.create_unique_constraint(
        "uq_route_cognition_segments_segment_geometry_hash",
        "route_cognition_segments",
        ["segment_id", "geometry_hash"],
    )
    _create_route_segments()
    _create_collection_routes()
    _create_collection_segments()


def downgrade() -> None:
    """移除正式 membership 表；保留 Step C concept 正式关系。"""
    op.drop_index("uq_collection_segments_active_seq", table_name="collection_segments")
    op.drop_index("uq_collection_segments_active_segment", table_name="collection_segments")
    op.drop_index("idx_collection_segments_accepted_judgment", table_name="collection_segments")
    op.drop_index("idx_collection_segments_status", table_name="collection_segments")
    op.drop_index("idx_collection_segments_segment", table_name="collection_segments")
    op.drop_index("idx_collection_segments_collection", table_name="collection_segments")
    op.drop_table("collection_segments")

    op.drop_index("uq_collection_routes_active_seq", table_name="collection_routes")
    op.drop_index("uq_collection_routes_active_route", table_name="collection_routes")
    op.drop_index("idx_collection_routes_accepted_judgment", table_name="collection_routes")
    op.drop_index("idx_collection_routes_status", table_name="collection_routes")
    op.drop_index("idx_collection_routes_reviewed_route_version", table_name="collection_routes")
    op.drop_index("idx_collection_routes_route_book", table_name="collection_routes")
    op.drop_index("idx_collection_routes_collection", table_name="collection_routes")
    op.drop_table("collection_routes")

    op.drop_index("uq_route_segments_active_seq", table_name="route_segments")
    op.drop_index("idx_route_segments_geom", table_name="route_segments")
    op.drop_index("idx_route_segments_accepted_judgment", table_name="route_segments")
    op.drop_index("idx_route_segments_status", table_name="route_segments")
    op.drop_index("idx_route_segments_segment", table_name="route_segments")
    op.drop_index("idx_route_segments_route_version", table_name="route_segments")
    op.drop_table("route_segments")

    op.drop_constraint(
        "uq_route_cognition_segments_segment_geometry_hash",
        "route_cognition_segments",
        type_="unique",
    )
