"""保存路线版本逐点海拔快照。

Revision ID: 20260629_route_elev_points
Revises: 20260618_membership_formal
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260629_route_elev_points"
down_revision = "20260618_membership_formal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给导出链路一份逐点海拔底片；不改前端海拔曲线字段语义。"""
    op.add_column("route_versions", sa.Column("elevation_points_snapshot", sa.Text(), nullable=True))


def downgrade() -> None:
    """回滚会丢掉导出用逐点海拔，route_books 展示曲线不受影响。"""
    op.drop_column("route_versions", "elevation_points_snapshot")
