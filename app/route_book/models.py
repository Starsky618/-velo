"""
路书数据模型——用户自己的"路线图纸库"。

这个文件只定义 route_books 表：它保存用户上传、从活动衍生、或腾讯地图规划出来的路线线条。
操作注意事项：source_activity_id 允许后续变成 NULL，这是源活动被删后的合法孤儿态。
输入输出：service 写入 name / distance / reference_line / source，meetup 读取这些字段做快照。
"""

import re
import struct

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

    @property
    def preview_points(self) -> list[list[float]]:
        """
        把数据库里的路线线条翻译成前端能直接画的点。

        可以把 reference_line 想象成仓库里的"施工图纸"：PostGIS 看得懂，
        但小程序地图只认一串 [经度, 纬度] 点。这个属性就是把施工图纸摊平，
        变成前端画红线需要的描图纸。
        """
        value = self.reference_line
        cached = getattr(self, "_preview_points_override", None)
        if cached is not None:
            return cached
        if value is None:
            return []

        try:
            if isinstance(value, str):
                return _preview_points_from_wkt(value)
            data = getattr(value, "data", value)
            if isinstance(data, str):
                return _preview_points_from_wkt(data)
            return _preview_points_from_wkb(data)
        except (AttributeError, TypeError, ValueError, struct.error):
            return []


def _preview_points_from_wkt(wkt: str) -> list[list[float]]:
    match = re.search(r"LINESTRING\s*\((.+)\)", wkt, re.IGNORECASE)
    if not match:
        return []
    points: list[list[float]] = []
    for pair in match.group(1).split(","):
        parts = pair.strip().split()
        if len(parts) < 2:
            continue
        points.append([float(parts[0]), float(parts[1])])
    return points


def _preview_points_from_wkb(data: object) -> list[list[float]]:
    raw = _wkb_bytes(data)
    if len(raw) < 9:
        return []

    byte_order = raw[0]
    if byte_order == 0:
        endian = ">"
    elif byte_order == 1:
        endian = "<"
    else:
        return []

    geom_type = struct.unpack(endian + "I", raw[1:5])[0]
    has_srid = bool(geom_type & 0x20000000)
    base_type = geom_type & 0xFF
    if base_type != 2:
        return []

    offset = 5
    if has_srid:
        offset += 4
    if len(raw) < offset + 4:
        return []

    point_count = struct.unpack(endian + "I", raw[offset : offset + 4])[0]
    offset += 4
    expected_len = offset + point_count * 16
    if len(raw) < expected_len:
        return []

    points: list[list[float]] = []
    for _ in range(point_count):
        lon, lat = struct.unpack(endian + "dd", raw[offset : offset + 16])
        points.append([float(lon), float(lat)])
        offset += 16
    return points


def _wkb_bytes(data: object) -> bytes:
    if data is None:
        return b""
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, memoryview):
        return data.tobytes()
    if hasattr(data, "tobytes"):
        return data.tobytes()
    if isinstance(data, str):
        try:
            return bytes.fromhex(data)
        except ValueError:
            return b""
    return b""
