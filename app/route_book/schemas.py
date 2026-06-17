"""
路书接口格式——前端创建、查看、删除路线图纸时使用的表格。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RouteBookListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RouteBookResponse]


def route_book_response(route, viewer_user_id: int | None) -> RouteBookResponse:
    """
    把数据库路线翻译成接口响应。

    公开路线像一张可以分享的地图，但 source_activity_id 像背后的私人骑行小票；
    只有创建者自己能看到这张小票，其他人只看路线本身。
    """
    response = RouteBookResponse.model_validate(route)
    if viewer_user_id is None or route.creator_id != viewer_user_id:
        response.source_activity_id = None
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
