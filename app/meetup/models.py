"""
约骑数据模型——一张路线图纸上的"集合通知单 + 报名名单 + 相册 + 成绩格子"。

这个文件定义 meetups、meetup_participants、meetup_media、meetup_activities 四张表。
操作注意事项：DRAFT 只允许每个 creator 保留一份；OPEN 之后快照字段不再跟 route_book 或 segment 改名漂移。
输入输出：service 写状态机，cron 把骑行活动挂进 meetup_activities，router 读这些字段返回前端卡片。
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.sql import false, func

from app.database import Base


class Meetup(Base):
    """约骑主表——一次即将发生或已经结束的集体骑行。"""

    __tablename__ = "meetups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    creator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(16), nullable=False, server_default="DRAFT")
    segment_id = Column(Integer, ForeignKey("segments.id", ondelete="SET NULL"), nullable=True)
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="SET NULL"), nullable=True)
    snapshot_route_name = Column(String(128), nullable=False)
    snapshot_distance = Column(Float, nullable=False)
    snapshot_climb = Column(Float, nullable=True)
    snapshot_city = Column(String(32), nullable=False, server_default="unknown")
    start_time = Column(DateTime(timezone=True), nullable=False)
    estimated_end_time = Column(DateTime(timezone=True), nullable=False)
    meeting_point = Column(String(128), nullable=False)
    pace_level = Column(String(16), nullable=False)
    max_participants = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    supply_point = Column(String(128), nullable=True)
    audience_tags = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    visibility = Column(String(16), nullable=False, default="public", server_default="public")
    eligibility_note = Column(String(100), nullable=True)
    safety_note = Column(String(200), nullable=True)
    share_token = Column(String(43), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_meetups_status_start", "status", "start_time"),
        Index("idx_meetups_creator_status", "creator_id", "status"),
        Index(
            "uq_meetups_creator_draft",
            "creator_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'OPEN', 'CANCELLED', 'COMPLETED')",
            name="ck_meetups_status",
        ),
        CheckConstraint(
            "pace_level IN ('relaxed', 'cruise', 'training', 'race')",
            name="ck_meetups_pace_level",
        ),
        CheckConstraint(
            "visibility IN ('public', 'invite_only')",
            name="ck_meetups_visibility",
        ),
        CheckConstraint(
            "max_participants >= 2 AND max_participants <= 20",
            name="ck_meetups_max",
        ),
        CheckConstraint(
            "snapshot_city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', 'chengdu', 'taiyuan', 'unknown')",
            name="ck_meetups_city",
        ),
        # 预计结束必须晚于开始时间。
        # estimated_end_time 由后端按距离/配速公式算出（不是用户手填），正常永远 > start_time；
        # 这条 DB 保险防的是"将来公式改错、写入颠倒的时间对"——让脏数据卡在数据库门口，
        # 而不是流到前端约骑卡片上显示成"结束早于开始"。
        CheckConstraint(
            "estimated_end_time > start_time",
            name="ck_meetups_time_order",
        ),
    )


class MeetupParticipant(Base):
    """约骑报名表——谁已经占了这次约骑的一个名额。"""

    __tablename__ = "meetup_participants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meetup_id = Column(Integer, ForeignKey("meetups.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_creator = Column(Boolean, nullable=False, server_default=false())
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("meetup_id", "user_id", name="uq_meetup_participant_user"),
        Index("idx_meetup_participants_user_joined", "user_id", "joined_at"),
    )


class MeetupMedia(Base):
    """约骑媒体表——创建者给约骑卡片上传的图片或视频。"""

    __tablename__ = "meetup_media"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meetup_id = Column(Integer, ForeignKey("meetups.id", ondelete="CASCADE"), nullable=False)
    uploader_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    type = Column(String(16), nullable=False)
    file_id = Column(String(512), nullable=False)
    caption = Column(String(128), nullable=True)
    seq = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_meetup_media_meetup_seq", "meetup_id", "seq"),
        CheckConstraint("type IN ('image', 'video')", name="ck_meetup_media_type"),
    )


class MeetupActivity(Base):
    """约骑↔活动关联——战报上"每人一格"的那颗钉子。"""

    __tablename__ = "meetup_activities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meetup_id = Column(Integer, ForeignKey("meetups.id", ondelete="CASCADE"), nullable=False)
    activity_id = Column(Integer, ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("meetup_id", "activity_id", name="uq_meetup_activity"),
        UniqueConstraint("meetup_id", "user_id", name="uq_meetup_user_one_cell"),
        Index("idx_meetup_activities_meetup", "meetup_id"),
    )
