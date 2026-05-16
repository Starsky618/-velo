"""sprint6_user_city_widen：放宽 user.city 到任意中文字符串（Tim 2026-05-17 真用拍）。

背景：Sprint 6 task-4 用户反馈 city 6 城太窄 / 想要全国所有省级 + 地级市标签。
方案：user.city 放宽到 String(64) + 删 ck_users_city CHECK 约束 / 应用层校验长度。

语义解耦：
- users.city：用户**手填**的家乡标签（picker 选省+市 / 任意中文）
- activities.city：worker hook 自动推断的活动起点（仍是 6 城+unknown / 不动）

activities 表 + ck_activities_city CHECK 约束**不动**。

Revision ID: sprint6_user_city_widen
Revises: persona_engine_init
Create Date: 2026-05-17

链路：sprint6_activity_city → persona_engine_init → sprint6_user_city_widen
（原 down_revision 写的是 sprint6_activity_city / 与 persona_engine_init 分叉双 head /
2026-05-17 部署时 alembic 报 "Multiple head revisions" / 改接在 persona_engine_init 后）
"""

from alembic import op
import sqlalchemy as sa


revision = "sprint6_user_city_widen"
down_revision = "persona_engine_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """删 ck_users_city CHECK + city String(32) → String(64)。"""
    op.drop_constraint("ck_users_city", "users", type_="check")
    op.alter_column(
        "users",
        "city",
        existing_type=sa.String(32),
        type_=sa.String(64),
        existing_nullable=True,
        existing_comment="所属城市：beijing/shanghai/hangzhou/shenzhen/chengdu/taiyuan/unknown 或 NULL",
        comment="用户手填家乡标签：任意中文字符串（picker 选省+市 / ≤ 32 字符）或 NULL",
    )


def downgrade() -> None:
    """回滚：city String(64) → String(32) + 恢复 ck_users_city CHECK。

    ⚠️ 注意：downgrade 前必须先把所有 city 值清理为 6 城+unknown+NULL / 否则 CHECK 加不上。
    生产用 downgrade 几乎只在紧急回滚场景 / 接受可能 fail（先 UPDATE 清理脏数据再 downgrade）。
    """
    op.alter_column(
        "users",
        "city",
        existing_type=sa.String(64),
        type_=sa.String(32),
        existing_nullable=True,
    )
    op.create_check_constraint(
        "ck_users_city",
        "users",
        "city IS NULL OR city IN ('beijing', 'shanghai', 'hangzhou', "
        "'shenzhen', 'chengdu', 'taiyuan', 'unknown')",
    )
