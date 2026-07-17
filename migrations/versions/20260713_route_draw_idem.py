"""给手画路线保存增加独立于路线生命周期的幂等凭据。

Revision ID: 20260713_route_draw_idem
Revises: 20260629_route_elev_points
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa


revision = "20260713_route_draw_idem"
down_revision = "20260629_route_elev_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """请求记录不随路线删除，避免迟到重放把用户已删除的路线复活。"""
    op.create_table(
        "route_book_save_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("client_request_id", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("route_book_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id",
            "client_request_id",
            name="uq_route_save_req_creator_key",
        ),
        sa.UniqueConstraint("route_book_id", name="uq_route_save_req_route"),
    )


def downgrade() -> None:
    """空账本可以回滚；已有请求时拒绝静默丢掉幂等与删除 tombstone。"""
    request_count = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM route_book_save_requests")
    ).scalar_one()
    if request_count:
        raise RuntimeError("保存请求账本已有数据，拒绝会丢失幂等保护的 downgrade")
    op.drop_table("route_book_save_requests")
