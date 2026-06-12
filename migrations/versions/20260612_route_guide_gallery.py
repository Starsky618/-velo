"""route_guides 加 gallery_urls 实景图列（路线百科实景图链路）"""

from alembic import op
import sqlalchemy as sa


revision = "20260612_route_guide_gallery"
down_revision = "20260612_route_guides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给路线百科加实景图 URL 列表列——可空，老数据不受影响。"""
    op.add_column("route_guides", sa.Column("gallery_urls", sa.Text(), nullable=True))


def downgrade() -> None:
    """回滚实景图列。"""
    op.drop_column("route_guides", "gallery_urls")
