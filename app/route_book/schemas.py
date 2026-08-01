"""
路书接口格式——前端创建、查看、删除路线图纸时使用的表格。
"""

from datetime import datetime
import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.route_book.export_service import can_export_route


RouteBookSource = Literal[
    "file_upload",
    "activity_derived",
    "tencent_direction",
    "manual_drawn",
    "curated_composite",
    "ai_generated",
]
RouteBookCreateSource = Literal["file_upload", "activity_derived"]
RouteBookFileType = Literal["gpx", "fit"]
RouteExportFormat = Literal["gpx", "tcx"]
RouteExportTargetPlatform = Literal["generic", "garmin", "igpsport", "magene", "wahoo"]
RouteExportBlockReason = Literal["no_route_book", "no_current_version", "not_public", "no_elevation"]
City = Literal["beijing", "shanghai", "hangzhou", "shenzhen", "chengdu", "taiyuan", "unknown"]
RouteBookVisibility = Literal["private", "unlisted", "public"]
RouteBookPublishStatus = Literal["draft", "published", "archived"]
RouteDrawCoordinateSystem = Literal["gcj02"]
RouteDrawMode = Literal["snap", "freehand"]
ManualDrawnCoordinateSystem = Literal["wgs84", "gcj02"]


class RouteBookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    name: str
    distance: float
    climb: float | None = None
    file_id: str | None = None
    file_type: RouteBookFileType | None = None
    source: RouteBookSource
    source_activity_id: int | None = None
    city: City
    visibility: RouteBookVisibility
    publish_status: RouteBookPublishStatus
    current_version_id: int | None = None
    preview_points: list[list[float]] = Field(default_factory=list)
    elevation_ready: bool = False
    elevation_profile: list[list[float]] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("elevation_profile", mode="before")
    @classmethod
    def parse_elevation_profile(cls, value):
        if value is None or isinstance(value, list):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, list) else None


class RouteBookListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RouteBookResponse]


class RouteBookDetailResponse(BaseModel):
    """路书详情页数据——只给页面看路线本身，不泄露内部文件钥匙。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    name: str
    distance: float
    climb: float | None = None
    preview_points: list[list[float]] = Field(default_factory=list)
    elevation_ready: bool = False
    elevation_profile: list[list[float]] | None = None
    export_ready: bool = False
    export_formats: list[RouteExportFormat] = Field(default_factory=list)
    export_block_reason: RouteExportBlockReason | None = None
    anonymous_export_download_allowed: bool = False

    @field_validator("elevation_profile", mode="before")
    @classmethod
    def parse_elevation_profile(cls, value):
        if value is None or isinstance(value, list):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, list) else None


def route_book_detail_response(
    route,
    viewer_user_id: int | None,
    *,
    export_ready: bool,
    export_formats: list[RouteExportFormat],
    export_block_reason: RouteExportBlockReason | None,
) -> RouteBookDetailResponse:
    response = RouteBookDetailResponse.model_validate(route)
    response.elevation_ready = bool(response.elevation_profile and len(response.elevation_profile) >= 2)
    response.export_ready = export_ready
    response.export_formats = export_formats
    response.export_block_reason = export_block_reason
    response.anonymous_export_download_allowed = can_export_route(route, current_user_id=None)
    return response


class RouteExportCreateRequest(BaseModel):
    """导出请求——用户点下载时只说想要哪种文件、偏向哪个码表品牌。"""

    model_config = ConfigDict(extra="forbid")

    format: RouteExportFormat
    target_platform: RouteExportTargetPlatform | None = "generic"


class RouteExportResponse(BaseModel):
    """导出结果——只给下载地址，不把仓库内部 file_id 交给前端。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int
    artifact_id: int
    route_book_id: int
    route_version_id: int
    format: RouteExportFormat
    filename: str
    download_url: str


def route_book_response(
    route,
    viewer_user_id: int | None,
    *,
    include_elevation_profile: bool = False,
) -> RouteBookResponse:
    """
    把数据库路线翻译成接口响应。

    公开路线像一张可以分享的地图，但 source_activity_id 像背后的私人骑行小票；
    只有创建者自己能看到这张小票，其他人只看路线本身。
    """
    response = RouteBookResponse.model_validate(route)
    if viewer_user_id is None or route.creator_id != viewer_user_id:
        response.source_activity_id = None
    has_elevation_profile = bool(response.elevation_profile and len(response.elevation_profile) >= 2)
    if not include_elevation_profile:
        response.elevation_profile = None
    response.elevation_ready = has_elevation_profile
    return response


class RouteGuideListItem(BaseModel):
    """官方路线列表卡片——只给书架页展示最必要的信息。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    city: str
    ready: bool
    cover_url: str | None = None
    highlights: list[str] | None = None
    distance: float | None = None
    climb: float | None = None


class RouteGuideListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RouteGuideListItem]


class RouteGuideOut(BaseModel):
    """官方路线详情——像一本摊开的导览手册，轨迹还没挂好时也能先读文字。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    city: str
    ready: bool
    content_md: str
    cover_url: str | None = None
    # 实景图 URL 数组——只进详情不进列表（书架页用不上，省流量）；None = 没图，前端整块隐藏
    gallery_urls: list[str] | None = None
    highlights: list[str] | None = None
    elevation_profile: list[list[float]] | None = None
    route_book_id: int | None = None
    distance: float | None = None
    climb: float | None = None
    preview_points: list[list[float]] | None = None
    export_ready: bool
    export_formats: list[RouteExportFormat] = Field(default_factory=list)
    export_block_reason: RouteExportBlockReason | None = None


class ActivityCandidateItem(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    title: str | None = None
    distance: float | None = None
    elevation_gain: float | None = None
    city: City | None = None
    started_at: datetime | None = None


class ActivityCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ActivityCandidateItem]


class TencentDirectionRouteBookRequest(BaseModel):
    """腾讯地图生成路书的请求体。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    from_lat: float = Field(..., ge=-90, le=90)
    from_lon: float = Field(..., ge=-180, le=180)
    to_lat: float = Field(..., ge=-90, le=90)
    to_lon: float = Field(..., ge=-180, le=180)

    @model_validator(mode="after")
    def reject_same_point(self):
        if self.from_lat == self.to_lat and self.from_lon == self.to_lon:
            raise ValueError("起点和终点不能相同")
        return self


class ManualDrawnSnapPreviewRequest(BaseModel):
    """手画路线预览请求——只看这段线怎么贴路，不保存正式路线。"""

    model_config = ConfigDict(extra="forbid")

    coordinate_system: RouteDrawCoordinateSystem
    mode: RouteDrawMode
    supports_detour_confirmation: bool = False
    points: list[tuple[float, float]] = Field(..., min_length=2, max_length=120)

    @field_validator("points")
    @classmethod
    def validate_points(cls, points: list[tuple[float, float]]):
        for index, (lon, lat) in enumerate(points):
            if not math.isfinite(lon) or not math.isfinite(lat):
                raise ValueError(f"第 {index + 1} 个路线点不是有效数字")
            if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                raise ValueError(f"第 {index + 1} 个路线点超出经纬度范围")
        return points


class ManualDrawnSnapPreviewResponse(BaseModel):
    """手画路线预览结果——灰线是用户原线，橙线是临时贴路线。"""

    model_config = ConfigDict(extra="forbid")

    mode: RouteDrawMode
    coordinate_system: RouteDrawCoordinateSystem
    snapped_points: list[list[float]]
    display_points: list[list[float]]
    raw_points: list[list[float]]
    anchor_points: list[list[float]]
    raw_distance_m: float
    distance_m: float
    provider_distance_m: float
    segment_count: int
    provider_point_count: int = Field(ge=2)
    requires_confirmation: bool = False
    warnings: list[str] = Field(default_factory=list)
    failed_segment: int | None = None


class ManualDrawnElevationPreviewRequest(BaseModel):
    """已贴路线的海拔预览请求——只计算，不写入正式路书。"""

    model_config = ConfigDict(extra="forbid")

    coordinate_system: ManualDrawnCoordinateSystem = "gcj02"
    points: list[tuple[float, float]] = Field(..., min_length=2, max_length=500)

    @field_validator("points")
    @classmethod
    def validate_points(cls, points: list[tuple[float, float]]):
        for index, (lon, lat) in enumerate(points):
            if not math.isfinite(lon) or not math.isfinite(lat):
                raise ValueError(f"第 {index + 1} 个路线点不是有效数字")
            if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                raise ValueError(f"第 {index + 1} 个路线点超出经纬度范围")
        return points


class ManualDrawnElevationPreviewResponse(BaseModel):
    """路线编辑页的非持久化海拔结果。"""

    model_config = ConfigDict(extra="forbid")

    coordinate_system: ManualDrawnCoordinateSystem
    distance_m: float
    climb_m: float
    descent_m: float
    elevation_profile: list[list[float]]


class ManualDrawnRawPointsSummary(BaseModel):
    """原始手画线摘要——像抽样照片，只留少量点用于排查，不存完整触摸轨迹。"""

    model_config = ConfigDict(extra="forbid")

    total_raw_points: int | None = Field(None, ge=0)
    sample: list[tuple[float, float]] = Field(default_factory=list, max_length=20)

    @field_validator("sample")
    @classmethod
    def validate_sample(cls, points: list[tuple[float, float]]):
        for index, (lon, lat) in enumerate(points):
            if not math.isfinite(lon) or not math.isfinite(lat):
                raise ValueError(f"第 {index + 1} 个原始采样点不是有效数字")
            if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                raise ValueError(f"第 {index + 1} 个原始采样点超出经纬度范围")
        return points


class ManualDrawnDrawMetadata(BaseModel):
    """手画保存附带信息——记录这条线怎么画出来，方便以后排查和导出解释。"""

    model_config = ConfigDict(extra="forbid")

    tool: str | None = Field(None, min_length=1, max_length=64)
    snap_provider: str | None = Field(None, min_length=1, max_length=64)
    segment_count: int | None = Field(None, ge=0, le=500)
    freehand_segment_count: int | None = Field(None, ge=0, le=500)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    raw_points_summary: ManualDrawnRawPointsSummary | None = None


class ManualDrawnRouteBookRequest(BaseModel):
    """手画路线请求——前端只交线条，海拔由后端统一补齐。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    client_request_id: str = Field(
        ...,
        min_length=16,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    coordinate_system: ManualDrawnCoordinateSystem = "wgs84"
    points: list[tuple[float, float]] = Field(..., min_length=2, max_length=500)
    draw_metadata: ManualDrawnDrawMetadata | None = None

    @field_validator("points")
    @classmethod
    def validate_points(cls, points: list[tuple[float, float]]):
        for index, (lon, lat) in enumerate(points):
            if not math.isfinite(lon) or not math.isfinite(lat):
                raise ValueError(f"第 {index + 1} 个路线点不是有效数字")
            if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                raise ValueError(f"第 {index + 1} 个路线点超出经纬度范围")
        return points
