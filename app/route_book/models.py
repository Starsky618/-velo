"""
路书数据模型——用户自己的"路线图纸库"。

这个文件只定义 route_books 表：它保存用户上传、从活动衍生、或腾讯地图规划出来的路线线条。
操作注意事项：source_activity_id 允许后续变成 NULL，这是源活动被删后的合法孤儿态。
输入输出：service 写入 name / distance / reference_line / source，meetup 读取这些字段做快照。
"""

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.sql import func

from app.database import Base


class RouteBook(Base):
    """路书表——用户保存的一张路线图纸。"""

    __tablename__ = "route_books"

    id = Column(Integer, primary_key=True, autoincrement=True)
    creator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(128), nullable=False)
    distance = Column(Float, nullable=False)
    climb = Column(Float, nullable=True)
    reference_line = Column(Geometry("LINESTRING", srid=4326, spatial_index=False), nullable=False)
    file_id = Column(String(512), nullable=True)
    file_type = Column(String(8), nullable=True)
    source = Column(String(32), nullable=False)
    source_activity_id = Column(Integer, ForeignKey("activities.id", ondelete="SET NULL"), nullable=True)
    city = Column(String(32), nullable=False, server_default="unknown")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_route_books_geom", "reference_line", postgresql_using="gist"),
        Index("idx_route_books_creator_created", "creator_id", text("created_at DESC")),
        CheckConstraint(
            "source IN ('file_upload', 'activity_derived', 'tencent_direction')",
            name="ck_route_books_source",
        ),
        CheckConstraint(
            "city IN ('beijing', 'shanghai', 'hangzhou', 'shenzhen', 'chengdu', 'taiyuan', 'unknown')",
            name="ck_route_books_city",
        ),
        CheckConstraint(
            "(source = 'file_upload' AND file_type IN ('gpx', 'fit') AND file_id IS NOT NULL "
            "AND source_activity_id IS NULL) OR "
            "(source = 'activity_derived' AND file_type IS NULL AND file_id IS NULL) OR "
            "(source = 'tencent_direction' AND file_type IS NULL AND file_id IS NULL "
            "AND source_activity_id IS NULL)",
            name="ck_route_books_file_type_source",
        ),
    )
