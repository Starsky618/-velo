"""Sprint 9 task-1：activities 表加 snapshot_ftp / intensity_factor / tss 字段。

Revision ID: sprint9_training_metrics
Revises: sprint8_max_cadence
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa


revision = "sprint9_training_metrics"
down_revision = "sprint8_max_cadence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activities",
        sa.Column("snapshot_ftp", sa.Integer(), nullable=True,
                  comment="这条活动锁定的 FTP（W）；跟 user.ftp 解耦；改 user.ftp 不影响历史"),
    )
    op.add_column(
        "activities",
        sa.Column("intensity_factor", sa.Float(), nullable=True,
                  comment="IF = NP / snapshot_ftp"),
    )
    op.add_column(
        "activities",
        sa.Column("tss", sa.Float(), nullable=True,
                  comment="TSS = (秒 × NP × IF) / (snapshot_ftp × 3600) × 100"),
    )


def downgrade() -> None:
    op.drop_column("activities", "tss")
    op.drop_column("activities", "intensity_factor")
    op.drop_column("activities", "snapshot_ftp")
