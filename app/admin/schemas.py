"""admin 模块请求/响应格式。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
