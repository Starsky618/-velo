"""
路书数据模型——用户自己的"路线图纸库"。

这个文件定义 route_books 和 route_guides 两张表：前者像路线图纸，后者像官方导览手册。
操作注意事项：source_activity_id 允许后续变成 NULL，这是源活动被删后的合法孤儿态。
输入输出：service 写入 name / distance / reference_line / source，meetup 读取这些字段做快照。
"""

import re
import struct

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.sql import false, func

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
    is_official = Column(Boolean, nullable=False, server_default=false())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    visibility = Column(String(16), nullable=False, server_default="private")
    publish_status = Column(String(16), nullable=False, server_default="draft")
    line_hash = Column(String(64), nullable=True)
    elevation_profile = Column(Text, nullable=True)
    current_version_id = Column(
        Integer,
        ForeignKey(
            "route_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_route_books_current_version_id",
        ),
        nullable=True,
    )

    __table_args__ = (
        Index("idx_route_books_geom", "reference_line", postgresql_using="gist"),
        Index("idx_route_books_creator_created", "creator_id", text("created_at DESC")),
        Index("idx_route_books_visibility_status", "visibility", "publish_status"),
        CheckConstraint(
            "source IN ('file_upload', 'activity_derived', 'tencent_direction', "
            "'manual_drawn', 'curated_composite', 'ai_generated')",
            name="ck_route_books_source",
        ),
        CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')",
            name="ck_route_books_visibility",
        ),
        CheckConstraint(
            "publish_status IN ('draft', 'published', 'archived')",
            name="ck_route_books_publish_status",
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
            "AND source_activity_id IS NULL) OR "
            "(source IN ('manual_drawn', 'curated_composite', 'ai_generated') "
            "AND file_type IS NULL AND file_id IS NULL AND source_activity_id IS NULL)",
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


class RouteVersion(Base):
    """路线版本表——给每张路线图纸拍下不可变的"第几版底片"。"""

    __tablename__ = "route_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="CASCADE"), nullable=False)
    version_no = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, server_default="current")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    geometry_source = Column(String(32), nullable=False)
    navigation_status = Column(String(16), nullable=False, server_default="ready")
    reference_line_snapshot = Column(Geometry("LINESTRING", srid=4326, spatial_index=False), nullable=False)
    line_hash = Column(String(64), nullable=False)
    distance = Column(Float, nullable=False)
    climb = Column(Float, nullable=True)
    elevation_profile = Column(Text, nullable=True)
    point_count = Column(Integer, nullable=True)
    component_snapshot_hash = Column(String(64), nullable=True)
    validation_warnings_json = Column(Text, nullable=True)
    navigation_metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("route_book_id", "version_no", name="uq_route_versions_route_book_version"),
        UniqueConstraint("id", "route_book_id", name="uq_route_versions_id_route_book"),
        Index("idx_route_versions_route_book_status", "route_book_id", "status"),
        Index("idx_route_versions_navigation_status", "navigation_status"),
        Index("idx_route_versions_geom", "reference_line_snapshot", postgresql_using="gist"),
        CheckConstraint("version_no >= 1", name="ck_route_versions_version_no"),
        CheckConstraint("status IN ('current', 'archived')", name="ck_route_versions_status"),
        CheckConstraint("navigation_status IN ('pending', 'ready', 'failed')", name="ck_route_versions_navigation_status"),
        CheckConstraint(
            "geometry_source IN ('route_book_reference', 'components_generated', 'normalized_upload', "
            "'file_upload', 'activity_derived', 'tencent_direction', 'manual_drawn', "
            "'curated_composite', 'ai_generated')",
            name="ck_route_versions_geometry_source",
        ),
    )


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


class RouteGuide(Base):
    """官方路线主实体（D11）——装裱好的导览手册，可以先于轨迹图纸存在。"""

    __tablename__ = "route_guides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)
    city = Column(String(32), nullable=False, server_default="太原")
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="SET NULL"), nullable=True, unique=True)
    content_md = Column(Text, nullable=False)
    cover_url = Column(String(512), nullable=True)
    # 实景图 URL 数组的 JSON 文本（如 ["/uploads/route_covers/jueweishan/g01.jpg", ...]）。
    # 真相源是 content/routes/<路线>/ 里除 cover.* 外的图片文件，发布脚本扫描生成——
    # 这列只是投影，NULL = 这条路线还没放实景图（前端整块隐藏长廊）。
    gallery_urls = Column(Text, nullable=True)
    highlights = Column(Text, nullable=True)
    elevation_profile = Column(Text, nullable=True)
    source_ref = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=True)
    imported_at = Column(DateTime(timezone=True), nullable=True)
    source_route_version_id = Column(Integer, nullable=True)
    source_judgment_run_id = Column(
        Integer,
        ForeignKey("judgment_runs.id", name="fk_route_guides_source_judgment_run", ondelete="SET NULL"),
        nullable=True,
    )
    content_origin = Column(String(32), nullable=False, server_default="legacy_import")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "content_origin IN ('content_routes_import', 'legacy_import')",
            name="ck_route_guides_content_origin",
        ),
        ForeignKeyConstraint(
            ["source_route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_guides_source_route_version",
        ),
        Index("idx_route_guides_source_judgment_run", "source_judgment_run_id"),
    )


class RouteExportJob(Base):
    """路线导出任务——记录用户要把哪一版路线打包成什么文件。"""

    __tablename__ = "route_export_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="CASCADE"), nullable=False)
    # route_version_id 故意不挂单列 FK：下面的组合 FK fk_route_export_jobs_route_version_book
    # 已经把 (route_version_id, route_book_id) 一起约束到 route_versions(id, route_book_id)，
    # 既保证 version 存在、又保证它确实属于这本路书。再加一条单列 FK 是重复约束（多一条无用索引 + 语义噪音），故省去。
    route_version_id = Column(Integer, nullable=False)
    requester_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    target_platform = Column(String(32), nullable=True)
    export_format = Column(String(8), nullable=False)
    export_mode = Column(String(24), nullable=False, server_default="download_file")
    status = Column(String(16), nullable=False, server_default="queued")
    simplification_strategy_json = Column(Text, nullable=True)
    target_constraints_json = Column(Text, nullable=True)
    include_course_points = Column(Boolean, nullable=False, server_default=false())
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_export_jobs_route_version_book",
            ondelete="CASCADE",
        ),
        CheckConstraint("export_format IN ('gpx', 'tcx')", name="ck_route_export_jobs_format"),
        CheckConstraint(
            "export_mode IN ('download_file', 'manual_upload')",
            name="ck_route_export_jobs_mode",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_route_export_jobs_status",
        ),
        CheckConstraint("include_course_points = false", name="ck_route_export_jobs_no_course_points"),
        Index("idx_route_export_jobs_route_version", "route_version_id"),
        Index("idx_route_export_jobs_route_book", "route_book_id"),
        Index("idx_route_export_jobs_requester", "requester_id"),
        Index("idx_route_export_jobs_status_created", "status", "created_at"),
        Index("idx_route_export_jobs_format", "export_format"),
    )


class RouteExportArtifact(Base):
    """路线导出产物——保存导出文件的内部钥匙，不直接给前端公开。"""

    __tablename__ = "route_export_artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    export_job_id = Column(Integer, ForeignKey("route_export_jobs.id", ondelete="CASCADE"), nullable=False)
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="CASCADE"), nullable=False)
    # 同 route_export_jobs：route_version_id 由下面的组合 FK fk_route_export_artifacts_route_version_book
    # 统一约束，不再单独挂单列 FK，避免重复。
    route_version_id = Column(Integer, nullable=False)
    format = Column(String(8), nullable=False)
    file_id = Column(String(512), nullable=False)
    file_size = Column(Integer, nullable=True)
    content_hash = Column(String(64), nullable=True)
    input_point_count = Column(Integer, nullable=True)
    output_point_count = Column(Integer, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_export_artifacts_route_version_book",
            ondelete="CASCADE",
        ),
        CheckConstraint("format IN ('gpx', 'tcx')", name="ck_route_export_artifacts_format"),
        Index("idx_route_export_artifacts_job", "export_job_id"),
        Index("idx_route_export_artifacts_route_version", "route_version_id"),
        Index("idx_route_export_artifacts_route_book", "route_book_id"),
        Index("idx_route_export_artifacts_content_hash", "content_hash"),
        Index("idx_route_export_artifacts_expires", "expires_at"),
    )


# 注册 Batch 4 的 judgment_runs 表，让 route_guides.source_judgment_run_id 的字符串外键
# 在单独创建 RouteGuide 测试表时也能找到“审稿编号登记簿”。
import app.route_cognition.models  # noqa: E402,F401
