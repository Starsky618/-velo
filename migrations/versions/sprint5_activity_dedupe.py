"""Sprint 5 task-2：activities 表加 duplicate_of 自引用 FK + index。

为什么加这一列：
    GPX 重复检测（语义级 dedupe）需要标记"哪条 activity 是另一条的重复"。
    现有 file_hash 只查字节级一样（同一文件重传），无法识别"同骑行不同导出"
    （Strava 同步 vs 用户后传 GPX）。

设计选型（详 docs/changelog.md "Sprint 5 task-2" 段）：
    - 选自引用 FK 而非关联表：100 用户量级 / 一个 activity 最多 1 个 duplicate_of /
      查询简单（WHERE duplicate_of IS NULL 过滤主榜）
    - nullable：99% activity 不是 duplicate / 默认 NULL
    - ondelete='SET NULL'：被引用的"主"activity 被删时，duplicate 行不连带删，
      duplicate_of 改回 NULL（视为独立）
    - 加 index：service 层查"哪些 activity 标了 duplicate"用得到（admin 视图 / 历史回扫）

Revision ID: sprint5_activity_dedupe
Revises: phase5_v5_db_changes
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa


revision = "sprint5_activity_dedupe"
down_revision = "phase5_v5_db_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """加 duplicate_of 列 + FK + index。"""
    op.add_column(
        "activities",
        sa.Column(
            "duplicate_of",
            sa.Integer(),
            nullable=True,
            comment="若非 NULL，表示本 activity 是 duplicate_of 引用那条的重复（语义级 dedupe）",
        ),
    )
    # 自引用 FK / SET NULL on delete（被引用的主活动删时，本行 duplicate_of 改 NULL 不连带删）
    op.create_foreign_key(
        "fk_activities_duplicate_of",
        "activities",
        "activities",
        ["duplicate_of"],
        ["id"],
        ondelete="SET NULL",
    )
    # index 加速"哪些 activity 是 duplicate"查询（admin / 历史回扫脚本用）
    op.create_index(
        "ix_activities_duplicate_of",
        "activities",
        ["duplicate_of"],
    )


def downgrade() -> None:
    """卸 index + FK + 列。顺序与 upgrade 反。"""
    op.drop_index("ix_activities_duplicate_of", table_name="activities")
    op.drop_constraint("fk_activities_duplicate_of", "activities", type_="foreignkey")
    op.drop_column("activities", "duplicate_of")
