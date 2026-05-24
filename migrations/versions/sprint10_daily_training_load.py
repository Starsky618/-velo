"""Sprint 10 task-1：创建 daily_training_load 每日训练负荷表。

Revision ID: sprint10_daily_training_load
Revises: sprint10_user_hr_profile
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "sprint10_daily_training_load"
down_revision = "sprint10_user_hr_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """建每日训练负荷快照表，不动 users / activities 核心表。"""

    op.create_table(
        "daily_training_load",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("ctl", sa.Float(), nullable=False),
        sa.Column("atl", sa.Float(), nullable=False),
        sa.Column("tsb", sa.Float(), nullable=False),
        sa.Column("tss_today", sa.Float(), nullable=False),
        sa.Column("weekly_tss", sa.Integer(), nullable=False),
        sa.Column("status_band", sa.String(length=20), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_daily_training_load_user_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "date",
            name="uq_daily_training_load_user_date",
        ),
        sa.CheckConstraint(
            "status_band IN ('fresh', 'ok', 'tired', 'overreached')",
            name="ck_daily_training_load_status_band",
        ),
    )
    op.create_index(
        "idx_dtl_user_date",
        "daily_training_load",
        ["user_id", sa.text("date DESC")],
    )


def downgrade() -> None:
    """回滚每日训练负荷表，回到 sprint10_user_hr_profile。"""

    op.drop_index("idx_dtl_user_date", table_name="daily_training_load")
    op.drop_table("daily_training_load")
