"""admin 模块请求/响应格式。"""

from datetime import datetime
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

AiDraftStatus = Literal["pending", "human_edited", "approved", "rejected"]
City = Literal[
    "beijing",
    "shanghai",
    "hangzhou",
    "shenzhen",
    "chengdu",
    "taiyuan",
    "unknown",
]
Difficulty = Literal["easy", "medium", "hard", "extreme"]


class WhoamiResponse(BaseModel):
    """当前管理员身份响应。"""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    nickname: str | None = None
    is_admin: bool
    created_at: datetime


class CurationPoolItem(BaseModel):
    """候选池列表的一行，给后台 H5 勾选精选赛段用。"""

    id: int
    segment_id: int
    segment_name: str
    segment_city: str
    segment_difficulty: str
    pool_score: float
    pool_reason: str | None = None
    selected_for_v5: bool
    selected_by_user_id: int | None = None
    selected_at: datetime | None = None


class CurationPoolListResponse(BaseModel):
    """候选池分页响应。"""

    items: list[CurationPoolItem]
    total: int
    selected_count: int


class CurationPoolPatchRequest(BaseModel):
    """候选池勾选请求。"""

    selected_for_v5: bool


class AiDraftResponse(BaseModel):
    """AI 草稿审核列表的一行，给后台 H5 审稿台使用。"""

    id: int
    segment_id: int
    segment_name: str
    ai_draft_text: str
    human_edited_text: str | None = None
    status: AiDraftStatus
    editor_user_id: int | None = None
    updated_at: datetime


class AiDraftListResponse(BaseModel):
    """AI 草稿审核分页响应。"""

    items: list[AiDraftResponse]
    total: int


class AiDraftPatchRequest(BaseModel):
    """AI 草稿编辑请求。"""

    human_edited_text: str | None = None
    status: AiDraftStatus | None = None


class AdminSegmentResponse(BaseModel):
    """admin 批量管理列表的一行，含公开字段 + 内部运营状态。"""

    id: int
    name: str
    description: str | None = None
    distance: float
    elevation_gain: float | None = None
    elevation_loss: float | None = None
    avg_gradient: float | None = None
    max_gradient: float | None = None
    difficulty: Difficulty
    city: City
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    match_tolerance: float
    min_match_ratio: float
    created_at: datetime | None = None
    draft_status: AiDraftStatus | None = None
    pool_status: Literal["selected", "candidate"] | None = None


class AdminSegmentListResponse(BaseModel):
    """admin 批量管理分页响应。"""

    items: list[AdminSegmentResponse]
    total: int
    page: int
    page_size: int


class AdminSegmentPatchRequest(BaseModel):
    """admin 批量修正赛段元数据，只允许 4 个运营字段。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    city: City | None = None
    difficulty: Difficulty | None = None


class FromActivityRequest(BaseModel):
    """从已完成骑行轨迹裁剪赛段的 admin 请求。"""

    model_config = ConfigDict(extra="forbid")

    activity_id: int
    name: str = Field(..., min_length=2, max_length=128)
    start_index: int = Field(..., ge=0)
    end_index: int = Field(..., gt=0)
    city: City | None = None
    difficulty: Difficulty | None = None

    @model_validator(mode="after")
    def end_must_gt_start(self):
        """终点索引必须晚于起点索引，像剪绳子不能倒着剪。"""
        if self.end_index <= self.start_index:
            raise ValueError("end_index must > start_index")
        return self


class FromGpxRequest(BaseModel):
    """admin 从 GPX 解析后的坐标点创建赛段。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2, max_length=128)
    description: str | None = Field(None, max_length=2000)
    reference_points: list[dict] = Field(..., min_length=2)
    match_tolerance: float | None = Field(None, gt=0, le=200)
    min_match_ratio: float | None = Field(None, ge=0, le=1)
    coordinate_system: Literal["gcj02", "wgs84"] = "gcj02"

    @field_validator("reference_points")
    @classmethod
    def validate_points(cls, v):
        """每个点都要有经纬度，就像地址必须同时有街道和门牌。"""
        for p in v:
            if "lat" not in p or "lon" not in p:
                raise ValueError("每个点必须含 lat/lon")
            lat = p["lat"]
            lon = p["lon"]
            if not isinstance(lat, int | float) or not isinstance(lon, int | float):
                raise ValueError("lat/lon 必须是数字")
            if not (-90 <= lat <= 90):
                raise ValueError(f"lat 越界: {lat}")
            if not (-180 <= lon <= 180):
                raise ValueError(f"lon 越界: {lon}")
        return v


class SegmentGeometryRebuildRequest(BaseModel):
    """用腾讯驾车折线替换同一个现实赛段的标准几何。"""

    model_config = ConfigDict(extra="forbid")

    reference_points: list[dict] = Field(..., min_length=2, max_length=2000)
    source_url: HttpUrl
    coordinate_system: Literal["gcj02", "wgs84"] = "gcj02"
    routing_provider: Literal["tencent"] = "tencent"
    routing_mode: Literal["driving"] = "driving"

    @field_validator("reference_points")
    @classmethod
    def validate_points(cls, value):
        for point in value:
            if "lat" not in point or "lon" not in point:
                raise ValueError("每个点必须含 lat/lon")
            lat = point["lat"]
            lon = point["lon"]
            if (
                isinstance(lat, bool)
                or isinstance(lon, bool)
                or not isinstance(lat, int | float)
                or not isinstance(lon, int | float)
            ):
                raise ValueError("lat/lon 必须是数字")
            if not math.isfinite(lat) or not math.isfinite(lon):
                raise ValueError("lat/lon 必须是有限数字")
            if not (-90 <= lat <= 90):
                raise ValueError(f"lat 越界: {lat}")
            if not (-180 <= lon <= 180):
                raise ValueError(f"lon 越界: {lon}")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_strava_segment_url(cls, value: HttpUrl):
        host = (value.host or "").lower()
        if host != "strava.com" and not host.endswith(".strava.com"):
            raise ValueError("source_url 必须是 Strava 公开赛段链接")
        if not value.path.startswith("/segments/"):
            raise ValueError("source_url 必须指向 Strava segment 页面")
        return value


class SegmentGeometryRevisionResponse(BaseModel):
    """标准几何替换任务状态。"""

    id: int
    segment_id: int
    status: Literal["staged", "processing", "active", "superseded", "failed"]
    previous_geometry_hash: str
    candidate_geometry_hash: str
    routing_provider: Literal["tencent"]
    routing_mode: Literal["driving"]
    source_url: str
    job_id: str | None = None
    dispatch_claimed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    activated_at: datetime | None = None


class TrackpointItem(BaseModel):
    """单个轨迹点的 admin 视图。

    字段名沿用 model 的 timestamp / seq；lat/lon 简写与其他 segment endpoint 一致；
    elevation 用全称避免与 ele 缩写在前端引发歧义。
    """

    seq: int
    lat: float
    lon: float
    elevation: float | None = None
    timestamp: datetime | None = None


class AdminActivityTrackpointsResponse(BaseModel):
    """admin 查任意活动 trackpoints 的响应。

    给 segment-creator.html 工具用：admin 输入 activity_id 后拉全量轨迹点，
    在浏览器里渲染海拔图 + 地图，再拖选起终点裁出赛段。
    """

    activity_id: int
    total: int
    trackpoints: list[TrackpointItem]
