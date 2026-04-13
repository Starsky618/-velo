"""
赛段数据模型——"赛道图纸 + 成绩记录本"。

两张表：
1. segments（赛道图纸）：一条固定路线的定义——名称、起终点、参考路线、匹配参数
2. segment_efforts（成绩记录本）：每个用户在每条赛道上的骑行成绩

好比学校操场的跑道：
- segments 是"哪条跑道、多长、从哪到哪"（跑道本身不会变）
- segment_efforts 是"张三在第一跑道跑了 12 秒，李四跑了 13 秒"（每次跑都留一条记录）

注意事项：
- reference_line 是 PostGIS 的 LINESTRING，存储赛段的参考折线
  （一组经纬度坐标连成的线，用于匹配骑行轨迹是否经过这条赛段）
- match_tolerance：匹配容差，单位米，轨迹点距参考线多近才算"在赛段上"
- min_match_ratio：最低覆盖率，轨迹点中有多大比例在容差内才算匹配成功
- segment_efforts 有联合唯一约束 (segment_id, activity_id)：一次骑行在同一赛段只能有一条成绩
- 删除 Activity 时，对应的 efforts 通过外键 ON DELETE CASCADE 自动清理
"""

from geoalchemy2 import Geometry
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text,
    ForeignKey, Index, UniqueConstraint, func,
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

    created_at = Column(DateTime, server_default=func.now())

    # 空间索引：加速"附近有哪些赛段"的查询
    __table_args__ = (
        Index("idx_segments_geom", "reference_line", postgresql_using="gist"),
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

    created_at = Column(DateTime, server_default=func.now())

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
