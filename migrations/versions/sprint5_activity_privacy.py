"""Sprint 5 task-4.1：新增骑行隐私表。

Revision ID: sprint5_activity_privacy
Revises: sprint5_moving_time
Create Date: 2026-05-15
"""

from alembic import op
import sqlalchemy as sa


revision = "sprint5_activity_privacy"
down_revision = "sprint5_moving_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建骑行隐私表和 visibility 索引。"""
    op.create_table(
        "activity_privacy",
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="public"),
        sa.Column("hide_power", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hide_heartrate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "visibility IN ('public', 'private')",
            name="ck_activity_privacy_visibility",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("activity_id"),
    )
    op.create_index(
        "idx_activity_privacy_visibility",
        "activity_privacy",
        ["visibility"],
    )


def downgrade() -> None:
    """删除骑行隐私表和索引。"""
    op.drop_index("idx_activity_privacy_visibility", table_name="activity_privacy")
    op.drop_table("activity_privacy")
