"""Allow official RouteBooks projected from frozen Strava research observations.

Revision ID: 20260814_climb_projection
Revises: 20260813_seg_elev_facts
"""

import sqlalchemy as sa

from alembic import op


revision = "20260814_climb_projection"
down_revision = "20260813_seg_elev_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_route_books_source", "route_books", type_="check")
    op.drop_constraint("ck_route_books_file_type_source", "route_books", type_="check")
    op.drop_constraint("ck_route_versions_geometry_source", "route_versions", type_="check")
    op.create_check_constraint(
        "ck_route_books_source",
        "route_books",
        "source IN ('file_upload', 'activity_derived', 'tencent_direction', "
        "'manual_drawn', 'curated_composite', 'ai_generated', 'strava_projection')",
    )
    op.create_check_constraint(
        "ck_route_books_file_type_source",
        "route_books",
        "(source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL "
        "AND source_activity_id IS NULL) OR "
        "(source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL) OR "
        "(source = 'tencent_direction' AND file_type IS NULL AND file_id IS NULL "
        "AND source_activity_id IS NULL) OR "
        "(source = 'strava_projection' AND file_type IS NULL AND file_id IS NOT NULL "
        "AND source_activity_id IS NULL) OR "
        "(source IN ('manual_drawn', 'curated_composite', 'ai_generated') "
        "AND file_type IS NULL AND file_id IS NULL AND source_activity_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_route_versions_geometry_source",
        "route_versions",
        "geometry_source IN ('route_book_reference', 'components_generated', 'normalized_upload', "
        "'file_upload', 'activity_derived', 'tencent_direction', 'manual_drawn', "
        "'curated_composite', 'ai_generated', 'strava_projection')",
    )
    op.create_index(
        "uq_route_books_strava_projection_file_id",
        "route_books",
        ["file_id"],
        unique=True,
        postgresql_where=sa.text("source = 'strava_projection'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_route_books_strava_projection_file_id",
        table_name="route_books",
    )
    op.drop_constraint("ck_route_versions_geometry_source", "route_versions", type_="check")
    op.drop_constraint("ck_route_books_file_type_source", "route_books", type_="check")
    op.drop_constraint("ck_route_books_source", "route_books", type_="check")
    op.create_check_constraint(
        "ck_route_books_source",
        "route_books",
        "source IN ('file_upload', 'activity_derived', 'tencent_direction', "
        "'manual_drawn', 'curated_composite', 'ai_generated')",
    )
    op.create_check_constraint(
        "ck_route_books_file_type_source",
        "route_books",
        "(source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL "
        "AND source_activity_id IS NULL) OR "
        "(source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL) OR "
        "(source = 'tencent_direction' AND file_type IS NULL AND file_id IS NULL "
        "AND source_activity_id IS NULL) OR "
        "(source IN ('manual_drawn', 'curated_composite', 'ai_generated') "
        "AND file_type IS NULL AND file_id IS NULL AND source_activity_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_route_versions_geometry_source",
        "route_versions",
        "geometry_source IN ('route_book_reference', 'components_generated', 'normalized_upload', "
        "'file_upload', 'activity_derived', 'tencent_direction', 'manual_drawn', "
        "'curated_composite', 'ai_generated')",
    )
