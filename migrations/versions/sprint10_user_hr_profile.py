"""Sprint 10：users 表加 birth_year / max_hr（FTP 心率门控估算）。

Revision ID: sprint10_user_hr_profile
Revises: sprint9_persona_cleanup
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa


revision = "sprint10_user_hr_profile"
down_revision = "sprint9_persona_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "birth_year",
            sa.Integer(),
            nullable=True,
            comment="出生年份；后端按当前年份现算年龄，不存会过期的 age",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "max_hr",
            sa.Integer(),
            nullable=True,
            comment="用户自填最大心率 bpm；FTP 估算心率门槛优先使用",
        ),
    )
    op.create_check_constraint(
        "ck_users_birth_year_range",
        "users",
        "birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100",
    )
    op.create_check_constraint(
        "ck_users_max_hr_range",
        "users",
        "max_hr IS NULL OR max_hr BETWEEN 120 AND 220",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_max_hr_range", "users", type_="check")
    op.drop_constraint("ck_users_birth_year_range", "users", type_="check")
    op.drop_column("users", "max_hr")
    op.drop_column("users", "birth_year")
