"""Add meetup create prototype fields.

Revision ID: 20260603_meetup_create_fields
Revises: 20260602_tencent_route_book
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260603_meetup_create_fields"
down_revision = "20260602_tencent_route_book"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给发起约骑新原型补上可持久化的组织者字段。"""
    op.add_column("meetups", sa.Column("supply_point", sa.String(length=128), nullable=True))
    op.add_column(
        "meetups",
        sa.Column("audience_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "meetups",
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="public"),
    )
    op.add_column("meetups", sa.Column("eligibility_note", sa.String(length=100), nullable=True))
    op.add_column("meetups", sa.Column("safety_note", sa.String(length=200), nullable=True))
    op.add_column("meetups", sa.Column("share_token", sa.String(length=43), nullable=True))
    op.create_check_constraint(
        "ck_meetups_visibility",
        "meetups",
        "visibility IN ('public', 'invite_only')",
    )


def downgrade() -> None:
    """回滚发起约骑新原型字段。"""
    op.drop_constraint("ck_meetups_visibility", "meetups", type_="check")
    op.drop_column("meetups", "share_token")
    op.drop_column("meetups", "safety_note")
    op.drop_column("meetups", "eligibility_note")
    op.drop_column("meetups", "visibility")
    op.drop_column("meetups", "audience_tags")
    op.drop_column("meetups", "supply_point")
