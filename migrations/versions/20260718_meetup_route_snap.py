"""为约骑冻结发布时的路线几何，避免私有路书泄露或删除后丢图。

Revision ID: 20260718_meetup_route_snap
Revises: 20260713_route_draw_idem
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_meetup_route_snap"
down_revision = "20260713_route_draw_idem"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meetups", sa.Column("snapshot_route_points", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("meetups", "snapshot_route_points")
