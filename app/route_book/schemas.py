"""
路书接口格式——前端创建、查看、删除路线图纸时使用的表格。
"""

from datetime import datetime
import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class ManualDrawnRouteBookRequest(BaseModel):
    """手画路线请求——前端只交线条，海拔由后端统一补齐。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
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
