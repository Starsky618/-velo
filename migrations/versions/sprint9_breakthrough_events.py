"""Sprint 9 task-8：breakthrough_events 新表。

干啥用：
-------
新建 breakthrough_events 表，存放"用户突破自己 ftp"的检测事件。
每次 worker 解析完活动跑一遍 eFTP 估算，若估算值 > 当前 ftp × 1.05，
就写一条 pending 事件；用户下次进 settings 页时弹窗提示是否更新 ftp。

新表不动现有表 → 部署零风险（无 ALTER）。

Revision ID: sprint9_breakthrough_events
Revises: sprint9_training_metrics
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa


revision = "sprint9_breakthrough_events"
down_revision = "sprint9_training_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新建 breakthrough_events 表 + 复合索引。"""
    op.create_table(
        "breakthrough_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "activity_id", sa.Integer(),
            sa.ForeignKey("activities.id"),
            nullable=False,
        ),
        sa.Column(
            "detected_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=True,
        ),
        sa.Column(
            "old_ftp", sa.Integer(), nullable=False,
            comment="检测时刻用户当前的 ftp（W）",
        ),
        sa.Column(
            "suggested_ftp", sa.Integer(), nullable=False,
            comment="estimator 算出来的建议新 ftp（W）",
        ),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="pending",
            comment="pending / accepted / rejected / expired",
        ),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False,
            comment="detected_at + 7 days；GET endpoint 自动过期 pending",
        ),
    )
    # 复合索引：查"该用户的所有 pending"是高频路径（settings onShow 每次都拉）
    op.create_index(
        "idx_breakthrough_user_status",
        "breakthrough_events",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_breakthrough_user_status", table_name="breakthrough_events")
    op.drop_table("breakthrough_events")
