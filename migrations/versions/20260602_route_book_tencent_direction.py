"""Allow Tencent direction route books.

Revision ID: 20260602_tencent_route_book
Revises: 20260528_meetup_route_book
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260602_tencent_route_book"
down_revision = "20260528_meetup_route_book"
branch_labels = None
depends_on = None


SOURCE_CHECK_V2 = "source IN ('file_upload', 'activity_derived', 'tencent_direction')"
FILE_TYPE_SOURCE_CHECK_V2 = (
    "(source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL "
    "AND source_activity_id IS NULL) OR "
    "(source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL) OR "
    "(source = 'tencent_direction' AND file_type IS NULL AND file_id IS NULL "
    "AND source_activity_id IS NULL)"
)

SOURCE_CHECK_V1 = "source IN ('file_upload', 'activity_derived')"
FILE_TYPE_SOURCE_CHECK_V1 = (
    "(source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL "
    "AND source_activity_id IS NULL) OR "
    "(source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL)"
)


def upgrade() -> None:
    """把 route_books.source 从 2 种来源扩到 3 种来源。"""
    op.drop_constraint("ck_route_books_file_type_source", "route_books", type_="check")
    op.drop_constraint("ck_route_books_source", "route_books", type_="check")
    op.create_check_constraint("ck_route_books_source", "route_books", SOURCE_CHECK_V2)
    op.create_check_constraint("ck_route_books_file_type_source", "route_books", FILE_TYPE_SOURCE_CHECK_V2)


def downgrade() -> None:
    """回滚前必须先删除或改写 source='tencent_direction' 的路书。"""
    existing = op.get_bind().execute(
        sa.text("SELECT 1 FROM route_books WHERE source = 'tencent_direction' LIMIT 1")
    ).first()
    if existing:
        raise RuntimeError("不能回滚：请先删除或改写 source='tencent_direction' 的路书")
    op.drop_constraint("ck_route_books_file_type_source", "route_books", type_="check")
    op.drop_constraint("ck_route_books_source", "route_books", type_="check")
    op.create_check_constraint("ck_route_books_source", "route_books", SOURCE_CHECK_V1)
    op.create_check_constraint("ck_route_books_file_type_source", "route_books", FILE_TYPE_SOURCE_CHECK_V1)
