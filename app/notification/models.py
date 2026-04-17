"""
通知记录表——"广播室的公告栏"。

每条记录是一个原子事件：某用户在某赛段发生了某件事（破 PR / 拿 KOM / KOM 被夺）。
前端拿到列表后按 activity_id 分组聚合展示。

操作注意事项：
- elapsed_time 类型必须是 Integer（和 SegmentEffort 一致），不是 Float
- effort_id 用 ON DELETE SET NULL（不是 CASCADE），避免他人通知被级联删除
- 写入后不可变，没有"更新通知"的场景
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey,
    UniqueConstraint, Index, CheckConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class Notification(Base):
    """
    通知记录——"公告栏上的一张便签"。

    可以把它想象成体育馆公告栏上的便签纸：
    "张三在滨河东路冲刺段跑出了 312 秒，排名第 1！（KOM）"
    便签贴上去后不会修改，60 天后自动撕掉。

    和 SegmentEffort（成绩单）的区别：
    成绩单是事实记录，永久保存；便签是通知，有过期时间。
    成绩变了排名会变，但便签记录的是"那一刻"的排名快照。
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)

    # 通知接收人
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 事件类型：pr（个人最佳）/ kom（赛段王）/ kom_lost（KOM 被夺）
    event_type = Column(String(20), nullable=False)

    # ---- 关联实体 ----
    # 哪条赛段
    segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 触发这条通知的骑行（kom_lost 时存夺走者的活动）
    activity_id = Column(
        Integer,
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=True,
    )
    # 关联的成绩记录（删成绩后通知保留，只是看不到详情）
    effort_id = Column(
        Integer,
        ForeignKey("segment_efforts.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ---- 事件快照数据 ----
    # 成绩用时（秒，整数，与 SegmentEffort.elapsed_time 类型一致）
    # kom_lost 时为 null
    elapsed_time = Column(Integer, nullable=True)
    # 排名快照。PR 且排名 > 10 时为 null（前端只显示"新 PR"）
    rank = Column(Integer, nullable=True)

    # ---- KOM 被夺时的对手信息 ----
    rival_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ---- 生命周期 ----
    # created_at + 60 天，过期后由定时任务清理
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # ---- 已读状态（第 4 期新增）----
    # 配合 idx_notifications_user_unread 部分索引加速 unread_count 查询
    is_read = Column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="是否已读。用户进通知列表页后由 mark-all-read 接口置 true",
    )

    __table_args__ = (
        # 幂等防护：同一条成绩不重复生成同类型通知
        UniqueConstraint("effort_id", "event_type", name="uq_notif_effort_type"),
        # 通知列表查询：按用户 + 时间倒序
        Index("idx_notif_user_created", "user_id", "created_at"),
        # 过期清理
        Index("idx_notif_expires", "expires_at"),
        # 事件类型约束
        CheckConstraint(
            "event_type IN ('pr', 'kom', 'kom_lost')",
            name="ck_notif_event_type",
        ),
    )
