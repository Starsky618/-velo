"""route_guides 表 + route_books.is_official（Sprint 14 T7）"""

from alembic import op
import sqlalchemy as sa


revision = "20260612_route_guides"
down_revision = "20260611_meetup_activities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建路线百科表，并给路书表加官方路线标记。"""
    op.create_table(
        "route_guides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("city", sa.String(32), server_default="太原", nullable=False),
        sa.Column("route_book_id", sa.Integer(), nullable=True),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("cover_url", sa.String(512), nullable=True),
        sa.Column("highlights", sa.Text(), nullable=True),
        sa.Column("elevation_profile", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("name", name="uq_route_guides_name"),
        sa.UniqueConstraint("route_book_id", name="uq_route_guides_route_book_id"),
    )
    op.add_column(
        "route_books",
        sa.Column("is_official", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """回滚路线百科表和官方路线标记。"""
    op.drop_column("route_books", "is_official")
    op.drop_table("route_guides")
