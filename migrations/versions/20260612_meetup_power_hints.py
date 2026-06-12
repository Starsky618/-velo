"""约骑强度提示 + 常用集合点"""

from alembic import op
import sqlalchemy as sa


revision = "20260612_meetup_power_hints"
down_revision = "20260612_route_guide_gallery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给约骑加可编辑强度提示，并创建用户自己的常用集合点表。"""
    op.add_column("meetups", sa.Column("recommended_power_label", sa.String(length=64), nullable=True))
    op.add_column("meetups", sa.Column("average_speed_range", sa.String(length=64), nullable=True))

    op.create_table(
        "meetup_favorite_places",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("address", sa.String(length=160), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("usage_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "name", name="uq_meetup_favorite_place_user_name"),
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_meetup_favorite_place_latitude"),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_meetup_favorite_place_longitude"),
        sa.CheckConstraint("usage_count >= 1", name="ck_meetup_favorite_place_usage_count"),
    )
    op.create_index(
        "idx_meetup_favorite_places_user_recent",
        "meetup_favorite_places",
        ["user_id", "last_used_at"],
    )


def downgrade() -> None:
    """回滚约骑强度提示和常用集合点表。"""
    op.drop_index("idx_meetup_favorite_places_user_recent", table_name="meetup_favorite_places")
    op.drop_table("meetup_favorite_places")
    op.drop_column("meetups", "average_speed_range")
    op.drop_column("meetups", "recommended_power_label")
