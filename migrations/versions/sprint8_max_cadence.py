"""Sprint 8：activities 表加 max_cadence 字段（最大踏频，rpm）。

为什么加这一列：
    详情页"踏频"卡当前只有"平均踏频"，缺"最大踏频"配对显示。
    跟"平均功率 / 最大功率"对齐 — 一对显示让用户能看出踏频区间。

设计选型：
    - Float nullable=True：跟 avg_cadence 同类型；老活动 / 无踏频感应车主为 NULL。
    - 不在迁移里回填：单独跑 scripts/backfill_max_cadence_and_power_zones.py
      （合并 #1 + #4 一次扫 trackpoints 算 max_cadence + power_zones）。

Revision ID: sprint8_max_cadence
Revises: persona_engine_seed
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa


revision = "sprint8_max_cadence"
down_revision = "persona_engine_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """加 max_cadence 列。"""
    op.add_column(
        "activities",
        sa.Column(
            "max_cadence",
            sa.Float(),
            nullable=True,
            comment="最大踏频（rpm），老活动 / 无踏频感应为 NULL",
        ),
    )


def downgrade() -> None:
    """卸 max_cadence 列。"""
    op.drop_column("activities", "max_cadence")
