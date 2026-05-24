"""
训练负荷数据模型像一本"每日训练账本"，每个用户每天一页。

操作注意事项：这张表是 Sprint 10 的防火墙式扩展，不能把 CTL/ATL/TSB
塞回 users 或 activities 核心表；后续回填脚本、API 和 worker 只能通过
这里的 DailyTrainingLoad 模型读写同一份日快照。

输入/输出数据流：输入来自 activities.tss 按北京时间归日后的每日汇总；
输出给训练日历页、worker 增量更新和 Sprint 12 教练总结读取。
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)

from app.database import Base


class DailyTrainingLoad(Base):
    """每日训练负荷表——每个用户每天一行 CTL/ATL/TSB 快照。"""

    __tablename__ = "daily_training_load"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE", name="fk_daily_training_load_user_id"),
        nullable=False,
    )
    # date 存北京时间自然日。可以把它理解成账本页码：2026-05-25 这一页，
    # 汇总的是北京时间这一天内的所有 completed cycling 活动。
    date = Column(Date, nullable=False)

    ctl = Column(Float, nullable=False)
    atl = Column(Float, nullable=False)
    tsb = Column(Float, nullable=False)
    tss_today = Column(Float, nullable=False)
    weekly_tss = Column(Integer, nullable=False)
    status_band = Column(String(20), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_daily_training_load_user_date"),
        CheckConstraint(
            "status_band IN ('fresh', 'ok', 'tired', 'overreached')",
            name="ck_daily_training_load_status_band",
        ),
        Index("idx_dtl_user_date", "user_id", date.desc()),
    )

