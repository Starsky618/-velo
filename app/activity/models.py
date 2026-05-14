"""
骑行活动数据模型——"运动记录表格"。

这里定义了两张核心表：
1. activities（骑行主表）：每次骑行的"成绩单"——总距离、总时间、爬升、速度、功率等
2. trackpoints（轨迹点表）：每次骑行的"GPS 足迹"——每隔几秒记录一次经纬度和传感器数据

两者的关系好比：activities 是一本书的"目录摘要"，trackpoints 是"正文全文"。
前端渲染地图时用 simplified_track（精简版轨迹，存在 activities 表里），
赛段匹配时用 trackpoints（全量逐点数据，需要时间戳和传感器数据）。

注意事项：
- activities 表有 4 种状态：pending → processing → completed / failed（后两者是并列终态，不可互相转换）
- 解析完成前（pending/processing），统计字段（distance 等）都是 NULL
- trackpoints 的 geom 字段使用 PostGIS 的 POINT 类型，用于空间查询
- 删除 activity 时，对应的 trackpoints 会自动级联删除（ON DELETE CASCADE）
- 距离单位：数据库存米（m），API 返回时再转公里（km）
"""

from geoalchemy2 import Geometry
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, DateTime, Text,
    ForeignKey, Index, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class Activity(Base):
    """
    骑行活动主表——每次骑行的"成绩单"。

    生命周期：
    1. 用户上传 GPX → 创建记录，status='pending'，只填 user_id + file_url
    2. Worker 开始解析 → status='processing'
    3. 解析成功 → status='completed'，填充所有统计字段和轨迹数据
    4. 解析失败 → status='failed'，填 error_message 记录错误原因
    """

    __tablename__ = "activities"

    # ===== 基础信息 =====
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 所属用户（外键关联 users 表）
    # 好比图书馆借书记录里的"借阅人"字段
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 骑行标题（可选），用户可以给骑行起个名字，如"晨骑阳澄湖"
    title = Column(String(128), nullable=True)

    # 状态机：pending → processing → completed → failed
    # 用字符串而非整数，方便调试和日志阅读
    status = Column(String(20), nullable=False, server_default="pending")

    # 文件存储路径（由 StorageBackend 管理）
    # nullable=True：Strava 导入的活动没有本地文件，file_url 为 NULL
    # GPX/FIT 上传的活动此字段一定有值，Strava 来源的活动此字段为 NULL
    file_url = Column(Text, nullable=True)

    # 文件内容的 SHA-256 哈希值（64 位十六进制字符串）
    # 用于去重：同一用户上传完全相同的文件时，秒级拦截返回已有记录
    # nullable=True：历史记录没有哈希值，不影响 UNIQUE 约束（NULL != NULL）
    file_hash = Column(String(64), nullable=True)

    # 解析失败时的错误信息，方便排查问题
    error_message = Column(Text, nullable=True)

    # ===== 解析完成后填充的统计数据 =====
    # 这些字段在上传时都是 NULL，异步解析成功后才会被填充

    distance = Column(Float, nullable=True)          # 总距离（米）
    duration = Column(Integer, nullable=True)         # 全程耗时（秒，含停车）= Strava 的 elapsed_time
    moving_time = Column(Integer, nullable=True)      # 移动时间（秒，去掉停车）= Strava 的 moving_time；Strava 导入直接拿，GPX/FIT 用 trackpoints 速度阈值算
    elevation_gain = Column(Float, nullable=True)     # 总爬升（米）
    avg_speed = Column(Float, nullable=True)          # 平均速度（km/h）
    max_speed = Column(Float, nullable=True)          # 最大速度（km/h）
    avg_power = Column(Float, nullable=True)          # 平均功率（W），GPX 无功率数据则为 NULL
    max_power = Column(Float, nullable=True)          # 最大功率（W）
    avg_hr = Column(Float, nullable=True)             # 平均心率（bpm）
    max_hr = Column(Float, nullable=True)             # 最大心率
    avg_cadence = Column(Float, nullable=True)        # 平均踏频（rpm）
    calories = Column(Float, nullable=True)           # 估算卡路里（kcal）
    normalized_power = Column(Float, nullable=True)   # 标准化功率（NP），FIT 自带，GPX/Strava 为 NULL
    # 用 DateTime(timezone=True) 让 PostgreSQL 用 TIMESTAMP WITH TIME ZONE 存储，
    # 读出来的 datetime 自带 tzinfo，避免与 datetime.now(timezone.utc) 比较时报
    # naive vs aware TypeError（陷阱 #2）。第 5 期统一改造（task-0.1）。
    started_at = Column(DateTime(timezone=True), nullable=True)   # 骑行开始时间（UTC）
    finished_at = Column(DateTime(timezone=True), nullable=True)  # 骑行结束时间（UTC）

    # 数据来源标记：gpx / fit / strava，老数据为 NULL（都是 GPX）
    data_source = Column(String(20), nullable=True)

    # 活动类型（第 4 期种子字段）：cycling（骑行）/ running（预留）/ hiking（预留）
    # 目前只有 cycling 一种值，保留字段为未来多运动扩展留口
    # 非 cycling 活动由解析器入口分流：不做赛段匹配 / 不记功率区间
    activity_type = Column(
        String(20),
        nullable=False,
        server_default="cycling",
        comment="活动类型：cycling（骑行）/ running（预留）/ hiking（预留）",
    )

    # Strava 活动 ID（去重用）：一条 Strava 活动只导入一次
    # 好比快递单号——同一个单号不能入库两次
    # UNIQUE 约束是数据库层最后防线：即使应用层的"先查后写"被并发请求绕过，
    # 数据库也会用 IntegrityError 拦住重复插入
    # nullable=True：非 Strava 来源的活动（GPX/FIT 上传）此字段为 NULL
    strava_activity_id = Column(BigInteger, unique=True, nullable=True)

    # ===== 语义级 dedupe（Sprint 5 task-2）=====
    # 若非 NULL → 本 activity 是 duplicate_of 引用那条的"语义重复"（同骑行不同导出格式）
    # 现有 file_hash UNIQUE 只防字节级重传 / 但 Strava 同步 vs 用户后传 GPX 字节肯定不同 → 漏判
    # 4 维 signature 比对（时间+距离+时长+起点 GPS）+ completeness score 决定哪份保留
    # 列表查询全部 WHERE duplicate_of IS NULL 过滤 / 详情查询不过滤（用户能看 duplicate）
    # FK ondelete=SET NULL：被引用的主活动删时不连带删 / 本行 duplicate_of 改 NULL（视为独立）
    duplicate_of = Column(
        Integer,
        ForeignKey("activities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ===== JSONB 字段（结构化数据，存为 JSON 格式）=====

    # 简化轨迹：Douglas-Peucker 算法压缩后的坐标点列表
    # 格式：[{lat, lon, ele}, ...] 约 500-1000 个点
    # 用途：前端地图渲染 + 骑行卡片绘制，单次 API 响应 <100KB
    simplified_track = Column(JSONB, nullable=True)

    # 每 10km 分段数据
    # 格式：[{km:"0-10", avg_speed, avg_power, avg_hr, elevation_gain}, ...]
    # 用途：让用户看到每段的配速变化，像马拉松分段计时
    splits = Column(JSONB, nullable=True)

    # 功率区间分布（依赖用户 FTP，无 FTP 则为 NULL）
    # 格式：[{zone:"Z1", name:"恢复", min_w, max_w, seconds, percent}, ...]
    # 用途：展示骑行强度分布，帮助训练分析
    power_zones = Column(JSONB, nullable=True)

    # ===== 时间戳 =====
    # tz-aware（第 5 期 task-0.1）：避免 naive vs aware 比较 TypeError
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ===== 索引 =====
    # 加速常见查询：按用户+状态筛选、按用户+开始时间排序
    __table_args__ = (
        Index("idx_activities_user_status", "user_id", "status"),
        Index("idx_activities_user_started", "user_id", "started_at"),
        # 同一用户 + 同一文件哈希 = 重复上传，数据库层最后防线
        UniqueConstraint("user_id", "file_hash", name="uq_user_file_hash"),
    )


class Trackpoint(Base):
    """
    轨迹点表——骑行的"GPS 足迹"。

    GPX 文件里每隔几秒记录一个点，包含经纬度、海拔、时间戳，
    以及传感器数据（心率、踏频、功率）。
    解析 GPX 时按顺序（seq）逐点写入这张表。

    好比你走路时每隔几步就在地上画个×，
    最后连起来就是你走过的完整路线。

    geom 字段是 PostGIS 的空间点，用于赛段匹配时的空间查询
    （比如"这个轨迹点在不在某条赛段 50 米范围内"）。
    """

    __tablename__ = "trackpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 所属骑行活动（级联删除：删活动时自动删轨迹点）
    activity_id = Column(
        Integer,
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 序号：标记这个点在轨迹中的顺序（第 1 个点、第 2 个点...）
    seq = Column(Integer, nullable=False)

    # 经纬度（必填）
    latitude = Column(Float, nullable=False)    # 纬度，如 30.2741
    longitude = Column(Float, nullable=False)   # 经度，如 120.1551

    # 海拔（米），GPS 精度有限，可能为空
    elevation = Column(Float, nullable=True)

    # 时间戳：这个点是什么时候经过的（tz-aware UTC，第 5 期 task-0.1）
    timestamp = Column(DateTime(timezone=True), nullable=True)

    # 传感器数据（可选，取决于骑行设备是否有对应传感器）
    heart_rate = Column(Integer, nullable=True)  # 心率（bpm）
    cadence = Column(Integer, nullable=True)     # 踏频（rpm）
    power = Column(Integer, nullable=True)       # 功率（W）

    # v2 新增：逐点速度和累计距离（翻译层计算后写入）
    speed = Column(Float, nullable=True)         # 瞬时速度（m/s），老数据为 NULL
    distance = Column(Float, nullable=True)      # 累计距离（米），老数据为 NULL

    # PostGIS 空间点，SRID 4326 = WGS84 坐标系（GPS 使用的坐标系）
    # 用于空间查询：ST_DWithin 判断点是否在赛段附近
    geom = Column(Geometry("POINT", srid=4326), nullable=True)

    # ===== 索引 =====
    __table_args__ = (
        # 按 activity_id 查询（查某次骑行的所有轨迹点）
        Index("idx_trackpoints_activity", "activity_id"),
        # 空间索引（GIST）：加速"附近的点"类查询
        Index("idx_trackpoints_geom", "geom", postgresql_using="gist"),
    )
