"""
Strava 导入进度表——"搬家进度单"。

当用户绑定 Strava 后，系统需要把历史骑行数据从 Strava 搬过来。
这张表记录搬家进度：总共多少箱（total_activities），
搬完了几箱（tier1/tier2_completed），跳过了几箱（tier2_skipped）。

好比搬家公司的工单：
- 第一层（列表）：先清点所有箱子的标签（名称、日期、大小），不打开
- 第二层（详情+轨迹）：打开每个箱子，取出内容归档到新家

注意事项：
- 一个用户同时只有一个 active 的导入任务
- status 有三种：active（进行中）、paused（暂停/卡死）、completed（全部完成）
- cursor_before 是时间戳游标，断点续传用——服务器重启后从这里继续
"""

from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey, func
from app.database import Base


class StravaImport(Base):
    """
    Strava 历史导入任务表——每个用户绑定 Strava 后创建一条记录，
    追踪整个历史数据搬运过程。

    生命周期：
    1. 用户授权绑定 Strava → 创建记录，status='active'
    2. 后台调度器分批拉取历史活动 → 逐步更新进度计数
    3. 所有活动处理完毕 → status='completed'
    4. 中途出错或超时 → status='paused'，等待恢复

    设计要点：
    - cursor_before 是断点续传的核心：记住上次拉到哪个时间点，
      下次从这里继续，不必从头开始
    - tier1/tier2 对应两层渐进策略：先轻量扫描，再深度拉取
    """

    __tablename__ = "strava_imports"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 所属用户（外键关联 users 表）
    # 一个用户可能多次解绑再绑定，所以不加 UNIQUE——但同时只有一个 active 的
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 用户在 Strava 平台的唯一 ID（冗余存储，方便查询时不必 JOIN users 表）
    strava_athlete_id = Column(BigInteger, nullable=False)

    # 总活动数（第一层拉完列表后更新）
    # 首次创建时为 NULL，表示还没开始扫描；扫描完后填入实际数量
    total_activities = Column(Integer, nullable=True)

    # ===== 进度计数 =====
    # 好比搬家进度：总共 100 箱，清点了 60 箱（tier1），搬完了 40 箱（tier2），跳过了 5 箱
    # server_default="0"：新建记录时数据库自动填 0，不依赖 Python 端
    tier1_completed = Column(Integer, server_default="0")   # 第一层（列表扫描）完成数
    tier2_completed = Column(Integer, server_default="0")   # 第二层（详情+轨迹）完成数
    tier2_skipped = Column(Integer, server_default="0")     # 第二层跳过数（非骑行/无轨迹等）

    # ===== 断点续传游标 =====
    # Strava 的列表接口用 before 参数做分页：传一个时间戳，返回这之前的活动
    # cursor_before 记录上次拉到哪里，下次从这个时间点继续往前翻页
    # 首次导入时为 NULL，表示从最新活动开始
    # 用 DateTime(timezone=True) 映射为 TIMESTAMP WITH TIME ZONE，
    # 确保读出的 datetime 带时区信息，避免 naive vs aware 比较报 TypeError
    cursor_before = Column(DateTime(timezone=True), nullable=True)

    # ===== 状态 =====
    # active：正在搬运中（后台调度器会持续推进）
    # paused：暂停（遇到限流/错误/超时，等待人工或自动恢复）
    # completed：全部完成（所有活动都已处理或跳过）
    status = Column(String(20), server_default="active")

    # ===== 时间戳 =====
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
