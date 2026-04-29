"""
通知记录表——"广播室的公告栏"。

每条记录是一个原子事件：某用户在某赛段发生了某件事
（破 PR / 拿 KOM / KOM 被夺 / v5 起：5min 功率进步 / 赛段异步 PB / 月度对比）。
前端拿到列表后按 activity_id 分组聚合展示。

操作注意事项：
- elapsed_time 类型必须是 Integer（和 SegmentEffort 一致），不是 Float
- effort_id 用 ON DELETE SET NULL（不是 CASCADE），避免他人通知被级联删除
- 写入后不可变，没有"更新通知"的场景
- event_type 值集 v5 起从 3 值扩到 6 值（progress_* 系列异步推送）；
  CHECK 约束已同步扩展，老数据 ('pr','kom','kom_lost') 仍在新值集内不受影响
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey,
    UniqueConstraint, Index, CheckConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
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

    # 事件类型 v5 起 6 值：
    # - pr：个人最佳
    # - kom：赛段王
    # - kom_lost：KOM 被夺
    # - progress_5min_power：5 分钟最大平均功率涨 ≥ 5W（task 2.A.1）
    # - progress_segment_pb：赛段 PB 异步推送（与即时反馈同源不重复）
    # - progress_monthly_summary：每月 1 日推上月对比
    # 长度 String(32)：'progress_monthly_summary' 24 字符 + 8 字符余量
    # （v5 task-0.6 Codex 异源审抓出原 String(20) 容不下，alter_column 扩到 32）
    event_type = Column(String(32), nullable=False)

    # ---- 关联实体 ----
    # 哪条赛段。第 4 期 task-7.1 起：外键 SET NULL + nullable=True
    # 赛段被删时通知保留（前端显示"该记录已失效"），不跟着连环删
    segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 触发这条通知的骑行（kom_lost 时存夺走者的活动）
    # 第 4 期 task-7.1 起：外键改为 SET NULL（原 CASCADE）
    activity_id = Column(
        Integer,
        ForeignKey("activities.id", ondelete="SET NULL"),
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
    # tz-aware（第 5 期 task-0.1）：与 datetime.now(timezone.utc) 比较不踩 TypeError
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ---- 已读状态（第 4 期新增）----
    # 配合 idx_notifications_user_unread 部分索引加速 unread_count 查询
    is_read = Column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="是否已读。用户进通知列表页后由 mark-all-read 接口置 true",
    )

    # ---- payload（第 5 期新增 task-0.6）----
    # progress 类 type 用 payload 存 (current_value / prev_value / delta) 数据
    # PR/KOM 类沿用现有 elapsed_time / rank / rival_user_id 字段，payload 留 NULL
    # JSONB（不是 JSON）：PG 原生支持索引和子键查询，比 TEXT 存 JSON 字符串高效
    payload = Column(
        JSONB,
        nullable=True,
        comment="progress 类通知的扩展数据：{current_value, prev_value, delta, ...}",
    )

    __table_args__ = (
        # 幂等防护：同一条成绩不重复生成同类型通知（PR/KOM 类）
        UniqueConstraint("effort_id", "event_type", name="uq_notif_effort_type"),
        # 通知列表查询：按用户 + 时间倒序
        Index("idx_notif_user_created", "user_id", "created_at"),
        # 过期清理
        Index("idx_notif_expires", "expires_at"),
        # progress 类幂等闸门（v5 task-0.6 / spec 5.6 / codex E1 C13）
        # 部分唯一索引：仅 progress_% 类生效（PR/KOM 类 effort_id 通常一致，会冲突，所以排除）
        # 防 worker 重试 / 并发对同一 activity 重复推 progress 通知
        Index(
            "uniq_progress_notification_per_activity",
            "activity_id", "event_type",
            unique=True,
            postgresql_where=text("event_type LIKE 'progress_%'"),
        ),
        # 事件类型约束（v5 task-0.6 扩展：3 值 → 6 值）
        # ORM 与 DB 必须保持一致，否则 alembic --autogenerate 会想"恢复"旧值集
        CheckConstraint(
            "event_type IN ('pr', 'kom', 'kom_lost', "
            "'progress_5min_power', 'progress_segment_pb', 'progress_monthly_summary')",
            name="ck_notif_event_type",
        ),
    )
