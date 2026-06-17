"""Add route versions for route books.

Revision ID: 20260618_route_versions
Revises: 20260612_meetup_power_hints
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry


revision = "20260618_route_versions"
down_revision = "20260612_meetup_power_hints"
branch_labels = None
depends_on = None


SOURCE_CHECK_V3 = (
    "source IN ('file_upload', 'activity_derived', 'tencent_direction', "
    "'manual_drawn', 'curated_composite', 'ai_generated')"
)
FILE_TYPE_SOURCE_CHECK_V3 = (
    "(source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL "
    "AND source_activity_id IS NULL) OR "
    "(source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL) OR "
    "(source = 'tencent_direction' AND file_type IS NULL AND file_id IS NULL "
    "AND source_activity_id IS NULL) OR "
    "(source IN ('manual_drawn', 'curated_composite', 'ai_generated') "
    "AND file_type IS NULL AND file_id IS NULL AND source_activity_id IS NULL)"
)

SOURCE_CHECK_V2 = "source IN ('file_upload', 'activity_derived', 'tencent_direction')"
FILE_TYPE_SOURCE_CHECK_V2 = (
    "(source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL "
    "AND source_activity_id IS NULL) OR "
    "(source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL) OR "
    "(source = 'tencent_direction' AND file_type IS NULL AND file_id IS NULL "
    "AND source_activity_id IS NULL)"
)


def upgrade() -> None:
    """把 route_books 升级成可私有、可发布、可版本化的路线资产。"""
    op.drop_constraint("ck_route_books_file_type_source", "route_books", type_="check")
    op.drop_constraint("ck_route_books_source", "route_books", type_="check")

    op.add_column(
        "route_books",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.add_column(
        "route_books",
        sa.Column("visibility", sa.String(length=16), server_default="private", nullable=False),
    )
    op.add_column(
        "route_books",
        sa.Column("publish_status", sa.String(length=16), server_default="draft", nullable=False),
    )
    op.add_column("route_books", sa.Column("line_hash", sa.String(length=64), nullable=True))
    op.add_column("route_books", sa.Column("elevation_profile", sa.Text(), nullable=True))
    op.add_column("route_books", sa.Column("current_version_id", sa.Integer(), nullable=True))

    op.create_check_constraint("ck_route_books_source", "route_books", SOURCE_CHECK_V3)
    op.create_check_constraint(
        "ck_route_books_visibility",
        "route_books",
        "visibility IN ('private', 'unlisted', 'public')",
    )
    op.create_check_constraint(
        "ck_route_books_publish_status",
        "route_books",
        "publish_status IN ('draft', 'published', 'archived')",
    )
    op.create_check_constraint("ck_route_books_file_type_source", "route_books", FILE_TYPE_SOURCE_CHECK_V3)
    op.create_index("idx_route_books_visibility_status", "route_books", ["visibility", "publish_status"])

    op.create_table(
        "route_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("route_book_id", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="current", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("geometry_source", sa.String(length=32), nullable=False),
        sa.Column("navigation_status", sa.String(length=16), server_default="ready", nullable=False),
        sa.Column(
            "reference_line_snapshot",
            Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("line_hash", sa.String(length=64), nullable=False),
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("climb", sa.Float(), nullable=True),
        sa.Column("elevation_profile", sa.Text(), nullable=True),
        sa.Column("point_count", sa.Integer(), nullable=True),
        sa.Column("component_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("validation_warnings_json", sa.Text(), nullable=True),
        sa.Column("navigation_metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint("version_no >= 1", name="ck_route_versions_version_no"),
        sa.CheckConstraint("status IN ('current', 'archived')", name="ck_route_versions_status"),
        sa.CheckConstraint("navigation_status IN ('pending', 'ready', 'failed')", name="ck_route_versions_navigation_status"),
        sa.CheckConstraint(
            "geometry_source IN ('route_book_reference', 'components_generated', 'normalized_upload', "
            "'file_upload', 'activity_derived', 'tencent_direction', 'manual_drawn', "
            "'curated_composite', 'ai_generated')",
            name="ck_route_versions_geometry_source",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_book_id", "version_no", name="uq_route_versions_route_book_version"),
        sa.UniqueConstraint("id", "route_book_id", name="uq_route_versions_id_route_book"),
    )
    op.create_index("idx_route_versions_geom", "route_versions", ["reference_line_snapshot"], postgresql_using="gist")
    op.create_index("idx_route_versions_navigation_status", "route_versions", ["navigation_status"])
    op.create_index("idx_route_versions_route_book_status", "route_versions", ["route_book_id", "status"])

    op.execute(
        sa.text(
            """
            WITH inserted AS (
                INSERT INTO route_versions (
                    route_book_id,
                    version_no,
                    status,
                    created_by,
                    geometry_source,
                    navigation_status,
                    reference_line_snapshot,
                    line_hash,
                    distance,
                    climb,
                    elevation_profile,
                    point_count,
                    created_at
                )
                SELECT
                    id,
                    1,
                    'current',
                    creator_id,
                    source,
                    'ready',
                    reference_line,
                    encode(sha256(ST_AsEWKB(reference_line)), 'hex'),
                    distance,
                    climb,
                    elevation_profile,
                    ST_NPoints(reference_line),
                    COALESCE(created_at, now())
                FROM route_books
                WHERE reference_line IS NOT NULL
                RETURNING id, route_book_id, line_hash
            )
            UPDATE route_books AS rb
            SET
                current_version_id = inserted.id,
                line_hash = inserted.line_hash,
                updated_at = COALESCE(rb.updated_at, rb.created_at, now())
            FROM inserted
            WHERE rb.id = inserted.route_book_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE route_books
            SET
                visibility = CASE WHEN is_official THEN 'public' ELSE 'private' END,
                publish_status = CASE WHEN is_official THEN 'published' ELSE 'draft' END,
                updated_at = COALESCE(updated_at, created_at, now())
            """
        )
    )

    op.create_foreign_key(
        "fk_route_books_current_version_id",
        "route_books",
        "route_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """回滚会丢失路线版本历史；若已有新来源或已发布状态，先人工处理。"""
    new_source = op.get_bind().execute(
        sa.text(
            """
            SELECT 1
            FROM route_books
            WHERE source NOT IN ('file_upload', 'activity_derived', 'tencent_direction')
            LIMIT 1
            """
        )
    ).first()
    if new_source:
        raise RuntimeError("不能回滚：请先删除或改写 v1.1 新增 route_books.source")

    published = op.get_bind().execute(
        sa.text(
            """
            SELECT 1
            FROM route_books
            WHERE visibility <> 'private' OR publish_status <> 'draft'
            LIMIT 1
            """
        )
    ).first()
    if published:
        raise RuntimeError("不能回滚：请先处理非 private/draft 的 route_books")

    op.drop_constraint("fk_route_books_current_version_id", "route_books", type_="foreignkey")
    op.drop_index("idx_route_versions_route_book_status", table_name="route_versions")
    op.drop_index("idx_route_versions_navigation_status", table_name="route_versions")
    op.drop_index("idx_route_versions_geom", table_name="route_versions")
    op.drop_table("route_versions")

    op.drop_index("idx_route_books_visibility_status", table_name="route_books")
    op.drop_constraint("ck_route_books_file_type_source", "route_books", type_="check")
    op.drop_constraint("ck_route_books_publish_status", "route_books", type_="check")
    op.drop_constraint("ck_route_books_visibility", "route_books", type_="check")
    op.drop_constraint("ck_route_books_source", "route_books", type_="check")
    op.create_check_constraint("ck_route_books_source", "route_books", SOURCE_CHECK_V2)
    op.create_check_constraint("ck_route_books_file_type_source", "route_books", FILE_TYPE_SOURCE_CHECK_V2)

    op.drop_column("route_books", "current_version_id")
    op.drop_column("route_books", "elevation_profile")
    op.drop_column("route_books", "line_hash")
    op.drop_column("route_books", "publish_status")
    op.drop_column("route_books", "visibility")
    op.drop_column("route_books", "updated_at")
