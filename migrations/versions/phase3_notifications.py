"""
第 3 期：新建 notifications 表。

纯新建表，不涉及已有表修改，迁移风险低。
"""
from alembic import op
import sqlalchemy as sa


revision = "phase3_notifications"
down_revision = "phase2_strava_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("effort_id", sa.Integer(), sa.ForeignKey("segment_efforts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("elapsed_time", sa.Integer(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("rival_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_unique_constraint("uq_notif_effort_type", "notifications", ["effort_id", "event_type"])
    op.create_index("idx_notif_user_created", "notifications", ["user_id", "created_at"])
    op.create_index("idx_notif_expires", "notifications", ["expires_at"])

    # SQLite 不支持 CHECK 约束中的 IN 语法，PostgreSQL 专用
    # 测试环境用 SQLite，生产环境用 PostgreSQL
    try:
        op.create_check_constraint(
            "ck_notif_event_type", "notifications",
            "event_type IN ('pr', 'kom', 'kom_lost')",
        )
    except Exception:
        pass  # SQLite 跳过


def downgrade() -> None:
    op.drop_table("notifications")
