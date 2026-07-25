"""保存路线版本的 canonical 距离-海拔网格。

Revision ID: 20260718_route_elev_grid
Revises: 20260713_route_draw_idem
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_route_elev_grid"
down_revision = "20260713_route_draw_idem"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加可复现导出的密集距离-海拔底片；旧路线保持兼容。"""
    op.add_column(
        "route_versions",
        sa.Column("elevation_grid_snapshot", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """回滚会丢掉密集导出底片，但保留原逐点海拔和页面曲线。"""
    op.drop_column("route_versions", "elevation_grid_snapshot")
