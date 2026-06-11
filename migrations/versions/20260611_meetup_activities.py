"""meetup_activities 关联表（Sprint 13 T1）

约骑↔活动的自动关联落点：attach tick 每 5 分钟把约骑当天的骑行挂进来，
战报页每人一格靠它点亮。双 UNIQUE 像两道闸门：同场同活动不能重复，
同场同人也只能占一个格子。
"""

from alembic import op
import sqlalchemy as sa


revision = "20260611_meetup_activities"
down_revision = "20260603_meetup_create_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建约骑活动关联表。"""
    op.create_table(
        "meetup_activities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("meetup_id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["meetup_id"], ["meetups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("meetup_id", "activity_id", name="uq_meetup_activity"),
        sa.UniqueConstraint("meetup_id", "user_id", name="uq_meetup_user_one_cell"),
    )
    op.create_index("idx_meetup_activities_meetup", "meetup_activities", ["meetup_id"])


def downgrade() -> None:
    """回滚约骑活动关联表。"""
    op.drop_index("idx_meetup_activities_meetup", table_name="meetup_activities")
    op.drop_table("meetup_activities")
