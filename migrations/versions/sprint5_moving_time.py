"""Sprint 5 polish：activities 表加 moving_time 字段（移动时间，秒）。

为什么加这一列：
    详情页要展示"移动时间"和"全程耗时"两个字段（图中样式）。
    现有 duration = 全程耗时（elapsed_time，含停车），但**没有"移动时间"**
    （moving_time，去掉停车段的有效骑行时间）。
    Strava 用户：API 直接返回 moving_time，无成本拿到。
    GPX/FIT 用户：用 trackpoints 速度阈值（≥ 1 m/s 视为移动）逐段累加。

设计选型：
    - nullable=True：老活动数据 NULL；前端 fallback 显示 "-"。
    - 不回填历史数据：成本高、价值低（用户主要看新活动）。
    - 单位：秒（与 duration 一致），前端拼 h:mm:ss 格式。

Revision ID: sprint5_moving_time
Revises: sprint5_activity_dedupe
Create Date: 2026-05-14
"""
from alembic import op
import sqlalchemy as sa


revision = "sprint5_moving_time"
down_revision = "sprint5_activity_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """加 moving_time 列。"""
    op.add_column(
        "activities",
        sa.Column(
            "moving_time",
            sa.Integer(),
            nullable=True,
            comment="移动时间（秒，去掉停车段）= Strava 的 moving_time；老数据 NULL",
        ),
    )


def downgrade() -> None:
    """卸 moving_time 列。"""
    op.drop_column("activities", "moving_time")
