"""
路书接口格式——前端创建、查看、删除路线图纸时使用的表格。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


RouteBookSource = Literal["file_upload", "activity_derived"]
RouteBookFileType = Literal["gpx", "fit"]
City = Literal["beijing", "shanghai", "hangzhou", "shenzhen", "chengdu", "taiyuan", "unknown"]


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
    created_at: datetime | None = None


class RouteBookListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RouteBookResponse]


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
