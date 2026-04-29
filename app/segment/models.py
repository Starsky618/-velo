"""
赛段数据模型——"赛道图纸 + 成绩记录本 + 内容运营档案"。

四张表（v5 起新增 2 张）：
1. segments（赛道图纸）：一条固定路线的定义——名称、起终点、参考路线、匹配参数
2. segment_efforts（成绩记录本）：每个用户在每条赛道上的骑行成绩
3. segment_ai_drafts（AI 草稿间，v5 新增）：AI 写的赛段介绍 + 编辑改稿，状态机化审核
4. segment_curation_pool（候选池，v5 新增）：周期性脚本算分 + 团队人工勾选精选

好比学校操场的跑道：
- segments 是"哪条跑道、多长、从哪到哪"（跑道本身不会变）
- segment_efforts 是"张三在第一跑道跑了 12 秒，李四跑了 13 秒"（每次跑都留一条记录）
- segment_ai_drafts 是"赛道介绍卡的草稿盒"——AI 先写一稿，编辑改稿，主管审批
- segment_curation_pool 是"候选名单"——脚本按热度算分推荐，团队挑出精选

注意事项：
- reference_line 是 PostGIS 的 LINESTRING，存储赛段的参考折线
  （一组经纬度坐标连成的线，用于匹配骑行轨迹是否经过这条赛段）
- match_tolerance：匹配容差，单位米，轨迹点距参考线多近才算"在赛段上"
- min_match_ratio：最低覆盖率，轨迹点中有多大比例在容差内才算匹配成功
- segment_efforts 有联合唯一约束 (segment_id, activity_id)：一次骑行在同一赛段只能有一条成绩
- 删除 Activity 时，对应的 efforts 通过外键 ON DELETE CASCADE 自动清理
- segments 上的 difficulty / city 是 NOT NULL + 默认值，老数据自动填 'medium' / 'unknown'，
  task 0.7 回填脚本会算出精确值替换默认值
- 删除 Segment 时 ai_drafts / curation_pool 通过外键 CASCADE 自动清理；
  删除编辑用户（editor_user_id）时草稿通过 SET NULL 保留稿子，只丢编辑人记录
"""

from geoalchemy2 import Geometry
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, false, func,
)

from app.database import Base


class Segment(Base):
    """
    赛段表——"赛道图纸"。

    每条赛段由管理员创建，定义了一段固定路线。
    用户骑行经过时，Worker 会自动匹配并记录成绩。
    """

    __tablename__ = "segments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 赛段名称和描述
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)

    # 赛段长度和爬升
    distance = Column(Float, nullable=False)          # 米
    elevation_gain = Column(Float, nullable=True)      # 米
    elevation_loss = Column(Float, nullable=True)      # 累计海拔下降（米）
    avg_gradient = Column(Float, nullable=True)        # 平均坡度（%）
    elevation_profile = Column(Text, nullable=True)    # 海拔采样 JSON 数组（约 80 个数值）

    # 起终点坐标（冗余存储，方便快速查询和前端显示，无需每次解析 reference_line）
    start_lat = Column(Float, nullable=False)
    start_lon = Column(Float, nullable=False)
    end_lat = Column(Float, nullable=False)
    end_lon = Column(Float, nullable=False)

    # 参考路线：PostGIS LINESTRING，一组坐标连成的折线
    # 匹配算法用这条线判断骑行轨迹是否经过赛段
    reference_line = Column(Geometry("LINESTRING", srid=4326), nullable=False)

    # 匹配参数
    # match_tolerance：轨迹点距参考线多近（米）才算"在赛段上"，默认 50 米
    match_tolerance = Column(Float, server_default="50.0")
    # min_match_ratio：轨迹点中至少多大比例在容差内才算匹配成功，默认 80%
    min_match_ratio = Column(Float, server_default="0.8")

    # ===== 第 5 期新增：内容深化 3 字段（防火墙破例）=====
    # 读这些字段时禁止 truthiness 判空（CLAUDE.md 陷阱 #1）：
    #   - 'medium'/'unknown' 都是 truthy 字符串，但语义可能是"未回填"或"算法判定"
    #   - 必须用 == 比对具体值，或显式 IS NULL（虽然这里 NOT NULL 不会 NULL）
    # difficulty：4 档枚举，由 distance + elevation_gain + max_gradient 算出
    # 注意：'medium' 既可能是"老数据未回填的兜底默认"也可能是"算法判定就是 medium"，
    # 业务代码无法靠值区分这两种语义；task 0.7 回填脚本必须自带"已回填"标记或一次性逻辑
    difficulty = Column(
        String(16),
        nullable=False,
        server_default="medium",
        comment="赛段难度：easy / medium / hard / extreme",
    )
    # max_gradient：100m 滑窗最大坡度（%），可能算不出（轨迹点不足/缺海拔）所以允许 NULL
    max_gradient = Column(Float, nullable=True)
    # city：所属城市枚举，用 6 主城 + unknown 兜底
    # 防止前端按城市筛选时漏数据，老数据回填前默认 'unknown'
    # 同样存在"unknown 是否真未填"语义模糊——业务代码用 city == 'unknown' 显式比较
    city = Column(
        String(32),
        nullable=False,
        server_default="unknown",
        comment="所属城市：beijing/shanghai/hangzhou/shenzhen/chengdu/taiyuan/unknown",
    )

    # tz-aware（第 5 期 task-0.1）：统一时区元数据，避免 naive vs aware TypeError
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 空间索引：加速"附近有哪些赛段"的查询
    # CHECK 约束 + (city, difficulty) 复合索引：列表筛选场景常组合用
    __table_args__ = (
        Index("idx_segments_geom", "reference_line", postgresql_using="gist"),
        CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard', 'extreme')",
            name="ck_segments_difficulty",
        ),
        CheckConstraint(
            "city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', "
            "'chengdu', 'taiyuan', 'unknown')",
            name="ck_segments_city",
        ),
        Index("idx_segments_city_difficulty", "city", "difficulty"),
    )


class SegmentEffort(Base):
    """
    赛段成绩表——"每次跑赛道的计时记录"。

    每当 Worker 解析完一次骑行，会自动检查轨迹是否经过已知赛段。
    如果匹配成功，就在这里记一条成绩。

    联合唯一约束：一次骑行（activity_id）在同一赛段（segment_id）只能有一条成绩。
    这防止重复匹配。
    """

    __tablename__ = "segment_efforts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 哪条赛段
    segment_id = Column(Integer, ForeignKey("segments.id"), nullable=False)
    # 哪次骑行（删活动时自动删成绩）
    activity_id = Column(
        Integer,
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 谁的成绩（冗余存储，方便排行榜查询不用 JOIN activities → users）
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 成绩数据
    elapsed_time = Column(Integer, nullable=False)     # 用时（秒）
    avg_speed = Column(Float, nullable=True)           # 平均速度（km/h）
    avg_power = Column(Float, nullable=True)           # 平均功率（W）

    # 匹配到的轨迹点范围（trackpoint 的 seq 值）
    # 记录下来方便前端高亮显示匹配到的轨迹段
    start_index = Column(Integer, nullable=False)
    end_index = Column(Integer, nullable=False)

    # tz-aware（第 5 期 task-0.1）：统一时区元数据，避免 naive vs aware TypeError
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # 联合唯一：一次骑行在同一赛段只有一条成绩
        UniqueConstraint("segment_id", "activity_id", name="uq_segment_activity"),
        # 排行榜查询索引：按赛段+用时排序
        Index("idx_efforts_segment_time", "segment_id", "elapsed_time"),
        # 用户成绩查询索引
        Index("idx_efforts_user", "user_id"),
        # PR 检测索引：查"用户在某赛段的最佳成绩"，三列支持 index-only scan
        # 好比在档案馆建立"赛段→用户→用时"的三级目录，直接翻到结果，无需全表扫描
        Index("idx_efforts_segment_user_time", "segment_id", "user_id", "elapsed_time"),
    )


class SegmentAiDraft(Base):
    """
    AI 赛段介绍草稿（第 5 期 task 5.B.2 + 5.D.2）——"赛道介绍卡的草稿盒"。

    一条赛段只能有一份草稿（UNIQUE segment_id），状态机：
        pending → human_edited → approved / rejected
    可以把它想象成图书馆的"导览牌草稿":
    - AI 先写一稿放进盒子（pending）
    - 编辑改稿替换内容（human_edited）
    - 主管审批通过（approved）→ 同步到 Segment.description 显示给用户
    - 主管打回（rejected）→ 草稿留档但不发布

    注意事项：
    - approved 状态触发同步到 Segment.description 的逻辑在 admin/service.py
      （编排层），本 model 只存数据
    - editor_user_id 用 SET NULL：编辑离职后草稿保留，只丢编辑人记录
    """
    __tablename__ = "segment_ai_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 一条赛段一份草稿，删赛段时草稿连带删
    # 注：UNIQUE 由下方 __table_args__ 的 uq_segment_ai_drafts_segment_id 保证；
    # 不在这里加列级 unique=True，否则 SQLAlchemy 会再建一个匿名 UNIQUE 重复约束
    segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    # AI 第一稿原文（不可改，留作对比）
    ai_draft_text = Column(Text, nullable=False)
    # 编辑改稿后的版本（NULL 表示编辑还没动过）
    human_edited_text = Column(Text, nullable=True)
    # 状态机：pending / human_edited / approved / rejected
    status = Column(String(16), nullable=False, server_default="pending")
    # 最后改稿人（删人时用 SET NULL 保留草稿）
    editor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # tz-aware：与全局时间比较不踩 TypeError
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'human_edited', 'approved', 'rejected')",
            name="ck_segment_ai_drafts_status",
        ),
        # 一条赛段一份草稿（应用层冗余约束 + DB 层硬保证）
        UniqueConstraint("segment_id", name="uq_segment_ai_drafts_segment_id"),
        # admin 审核台按状态筛 pending 草稿
        Index("idx_ai_drafts_status", "status"),
    )


class SegmentCurationPool(Base):
    """
    赛段候选池（第 5 期 task 5.D.1）——"精选赛段的候选名单"。

    周期性脚本（task 3.C.1）按热度算 pool_score，写进这张表（每周一次）。
    admin 团队在 H5 后台勾选 selected_for_v5=true 的赛段进入精选展示。

    可以把它想象成评委初筛 + 团队精选的两段式选秀：
    - 第一段：脚本看活动数 / KOM 频率 / 难度分布给每条赛段打分
      （pool_score）入候选名单
    - 第二段：team 在候选名单里勾选 selected_for_v5=true 的赛段进精选页

    注意事项：
    - selected_at / selected_by_user_id 在勾选时一起填，记录"谁在何时选的"
    - 删赛段时连带删（CASCADE）
    - 删勾选人时只丢勾选人记录（SET NULL）
    - UNIQUE segment_id：候选池脚本幂等保证（同一赛段不重复入池）
    """
    __tablename__ = "segment_curation_pool"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # UNIQUE 由 __table_args__ 的 uq_curation_pool_segment_id 保证（不在列级再加 unique=True）
    segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 脚本算出的热度分数（高 = 候选优先级高）
    pool_score = Column(Float, nullable=False)
    # 入池原因（'high_attempts' / 'frequent_kom' / 'difficulty_balance' / 'manual_added'）
    pool_reason = Column(String(64), nullable=True)
    # 是否被人工勾选进精选（true 才在前端精选页显示）
    selected_for_v5 = Column(Boolean, server_default=false(), nullable=False)
    # 谁勾选的（删人时用 SET NULL 保留勾选状态）
    selected_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    selected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("segment_id", name="uq_curation_pool_segment_id"),
        # admin 列表常按"已选 / 未选"筛
        Index("idx_curation_pool_selected", "selected_for_v5"),
    )
