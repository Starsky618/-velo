"""Create route_book and meetup tables.

Revision ID: 20260528_meetup_route_book
Revises: sprint10_daily_training_load
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry


revision = "20260528_meetup_route_book"
down_revision = "sprint10_daily_training_load"
branch_labels = None
depends_on = None


CITY_CHECK = "IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', 'chengdu', 'taiyuan', 'unknown')"


def upgrade() -> None:
    op.create_table(
        "route_books",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("climb", sa.Float(), nullable=True),
        sa.Column("reference_line", Geometry("LINESTRING", srid=4326, spatial_index=False), nullable=False),
        sa.Column("file_id", sa.String(length=512), nullable=True),
        sa.Column("file_type", sa.String(length=8), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_activity_id", sa.Integer(), nullable=True),
        sa.Column("city", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], name="fk_route_books_creator_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_activity_id"], ["activities.id"], name="fk_route_books_source_activity_id", ondelete="SET NULL"
        ),
        sa.CheckConstraint("source IN ('file_upload', 'activity_derived')", name="ck_route_books_source"),
        sa.CheckConstraint(f"city {CITY_CHECK}", name="ck_route_books_city"),
        sa.CheckConstraint(
            "(source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL "
            "AND source_activity_id IS NULL) OR "
            "(source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL)",
            name="ck_route_books_file_type_source",
        ),
    )
    op.create_index("idx_route_books_geom", "route_books", ["reference_line"], postgresql_using="gist")
    op.create_index("idx_route_books_creator_created", "route_books", ["creator_id", sa.text("created_at DESC")])

    op.create_table(
        "meetups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=True),
        sa.Column("route_book_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_route_name", sa.String(length=128), nullable=False),
        sa.Column("snapshot_distance", sa.Float(), nullable=False),
        sa.Column("snapshot_climb", sa.Float(), nullable=True),
        sa.Column("snapshot_city", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estimated_end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meeting_point", sa.String(length=128), nullable=False),
        sa.Column("pace_level", sa.String(length=16), nullable=False),
        sa.Column("max_participants", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], name="fk_meetups_creator_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], name="fk_meetups_segment_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], name="fk_meetups_route_book_id", ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('DRAFT', 'OPEN', 'CANCELLED', 'COMPLETED')", name="ck_meetups_status"),
        sa.CheckConstraint("pace_level IN ('relaxed', 'cruise', 'training', 'race')", name="ck_meetups_pace_level"),
        sa.CheckConstraint("max_participants >= 2 AND max_participants <= 20", name="ck_meetups_max"),
        sa.CheckConstraint(f"snapshot_city {CITY_CHECK}", name="ck_meetups_city"),
        sa.CheckConstraint("estimated_end_time > start_time", name="ck_meetups_time_order"),
    )
    op.create_index("idx_meetups_status_start", "meetups", ["status", "start_time"])
    op.create_index("idx_meetups_creator_status", "meetups", ["creator_id", "status"])
    op.create_index(
        "uq_meetups_creator_draft",
        "meetups",
        ["creator_id"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
    )

    op.create_table(
        "meetup_participants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("meetup_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_creator", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["meetup_id"], ["meetups.id"], name="fk_meetup_participants_meetup_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_meetup_participants_user_id", ondelete="CASCADE"),
        sa.UniqueConstraint("meetup_id", "user_id", name="uq_meetup_participant_user"),
    )
    op.create_index("idx_meetup_participants_user_joined", "meetup_participants", ["user_id", "joined_at"])

    op.create_table(
        "meetup_media",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("meetup_id", sa.Integer(), nullable=False),
        sa.Column("uploader_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("file_id", sa.String(length=512), nullable=False),
        sa.Column("caption", sa.String(length=128), nullable=True),
        sa.Column("seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["meetup_id"], ["meetups.id"], name="fk_meetup_media_meetup_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], name="fk_meetup_media_uploader_id", ondelete="SET NULL"),
        sa.CheckConstraint("type IN ('image', 'video')", name="ck_meetup_media_type"),
    )
    op.create_index("idx_meetup_media_meetup_seq", "meetup_media", ["meetup_id", "seq"])


def downgrade() -> None:
    op.drop_index("idx_meetup_media_meetup_seq", table_name="meetup_media")
    op.drop_table("meetup_media")
    op.drop_index("idx_meetup_participants_user_joined", table_name="meetup_participants")
    op.drop_table("meetup_participants")
    op.drop_index("uq_meetups_creator_draft", table_name="meetups")
    op.drop_index("idx_meetups_creator_status", table_name="meetups")
    op.drop_index("idx_meetups_status_start", table_name="meetups")
    op.drop_table("meetups")
    op.drop_index("idx_route_books_creator_created", table_name="route_books")
    op.drop_index("idx_route_books_geom", table_name="route_books")
    op.drop_table("route_books")
